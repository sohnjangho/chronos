"""Search Agent(`POST /agents/search`, stream:false): 출처 문장만 읽기·200 안 data-error·시간 초과·빈 성공 없음·키 보호·비용 기록.

진짜 Liner 는 부르지 않는다(httpx.MockTransport). 응답 모양(stream:false)은 문서가 정확히 적지 않아 JSON(chunks)과 SSE 둘 다 본다.
"""

import asyncio
import json
import logging

import httpx
import pytest
from sqlalchemy import select

from app.llm import search_agent
from app.llm.search_agent import AgentQuote, SearchAgentFailed, ask
from app.store.tables import LlmCall
from tests.llm_doubles import KEY, add_connection

ANSWER = "야간 타설은 22시까지 허용된다[1]."


class AgentMock(httpx.MockTransport):
    """받은 요청을 남기고 정한 답을 준다. body 가 str 이면 SSE 글, 예외면 던진다."""

    def __init__(self, body: object, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.body, self.status = body, status
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        if isinstance(self.body, str):
            return httpx.Response(self.status, text=self.body, headers={"content-type": "text/event-stream"})
        return httpx.Response(self.status, json=self.body)


def sse(*events: dict) -> str:
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events) + "data: [DONE]\n\n"


REFS = [{"title": "건설공사 소음 기준", "url": "https://law.example.go.kr/noise"},
        {"title": "동절기 콘크리트 지침", "url": "https://kcs.example.or.kr/winter"}]
CHUNKS = {"referenceChunks": [
    {"referenceId": 1, "text": "특정공사의 야간 작업은 22시까지로 한다."},
    {"referenceId": 2, "text": "일 평균기온 4℃ 이하에서는 한중 콘크리트로 시공한다."},
]}


@pytest.fixture
def conn(session):
    return add_connection(session)


@pytest.fixture
def use(monkeypatch):
    def install(t: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
        monkeypatch.setattr(search_agent, "TRANSPORT", t)
        return t
    return install


def calls(session) -> list[LlmCall]:
    session.expire_all()
    return list(session.scalars(select(LlmCall).where(LlmCall.purpose == "search_agent")))


async def test_json_body_gives_quotes_and_drops_the_answer(session, conn, use):
    t = use(AgentMock({"answer": ANSWER, "references": REFS, "chunks": [
        {"type": "start"}, {"type": "data-search-chunks", "data": CHUNKS}, {"type": "finish"}]}))
    got = await ask(session, "야간 타설 허용 시간")
    req = t.requests[0]
    assert req.method == "POST" and req.url.path == "/api/v1/agents/search"
    assert req.headers["x-api-key"] == KEY and "authorization" not in req.headers
    assert json.loads(req.content) == {"messages": [{"role": "user", "content": "야간 타설 허용 시간"}],
                                       "mode": "general", "stream": False}
    assert got == [AgentQuote("특정공사의 야간 작업은 22시까지로 한다.", REFS[0]["url"], REFS[0]["title"]),
                   AgentQuote("일 평균기온 4℃ 이하에서는 한중 콘크리트로 시공한다.", REFS[1]["url"], REFS[1]["title"])]
    assert all(ANSWER not in q.text for q in got)


async def test_sse_body_is_read_too(session, conn, use):
    use(AgentMock(sse({"type": "start"}, {"type": "text-delta", "delta": ANSWER},
                      {"type": "data-search-references", "data": {"references": REFS}},
                      {"type": "data-search-chunks", "data": CHUNKS}, {"type": "finish"})))
    got = await ask(session, "q", mode="scholar")
    assert [q.url for q in got] == [REFS[0]["url"], REFS[1]["url"]]


async def test_scholar_mode_is_sent(session, conn, use):
    t = use(AgentMock(sse({"type": "data-search-chunks", "data": CHUNKS},
                          {"type": "data-search-references", "data": {"references": REFS}})))
    await ask(session, "q", mode="scholar")
    assert json.loads(t.requests[0].content)["mode"] == "scholar"


async def test_chunk_with_its_own_link_and_bad_links_dropped(session, conn, use):
    use(AgentMock({"chunks": [{"type": "data-search-chunks", "data": {"referenceChunks": [
        {"text": "문장 하나", "url": "https://a.example.com/x", "title": "가"},
        {"text": "링크 없음"},
        {"text": "스크립트", "url": "javascript:alert(1)", "title": "나"},
        {"text": "", "url": "https://b.example.com", "title": "빈 문장"},
        {"text": "문장 하나", "url": "https://a.example.com/x", "title": "가"},  # 같은 것 두 번
    ]}}]}))
    assert await ask(session, "q") == [AgentQuote("문장 하나", "https://a.example.com/x", "가")]


async def test_data_error_inside_200_fails(session, conn, use):
    use(AgentMock(sse({"type": "start"}, {"type": "data-search-chunks", "data": CHUNKS},
                      {"type": "data-error", "id": "data-error-1", "data": {"code": "DOWNSTREAM_ERROR", "retryable": True}})))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    assert e.value.code == "agent_error"
    assert e.value.__cause__ is None and e.value.__context__ is None


async def test_data_error_in_json_chunks_fails(session, conn, use):
    use(AgentMock({"answer": "", "chunks": [{"type": "data-error", "data": {"code": "X"}}]}))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    assert e.value.code == "agent_error"


@pytest.mark.parametrize("body", [sse(), sse({"type": "start"}, {"type": "finish"}),
                                  {"answer": ANSWER, "references": REFS, "chunks": []}, "<html>점검 중</html>", ["목록"]])
async def test_done_without_chunks_is_not_success(session, conn, use, body):
    use(AgentMock(body))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    assert e.value.code == "no_quotes"


async def test_time_limit(session, conn, use):
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"chunks": []})

    use(httpx.MockTransport(slow))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q", timeout=0.05)
    assert e.value.code == "timeout"


@pytest.mark.parametrize("status,code", [(401, "bad_key"), (402, "no_credit"), (429, "rate_limited"), (502, "server_error")])
async def test_http_errors(session, conn, use, status, code):
    use(AgentMock({"error": "x"}, status=status))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    assert e.value.code == code


async def test_not_ready_without_liner_sends_nothing(session, use):
    t = use(AgentMock({"chunks": []}))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    assert e.value.code == "no_connection" and t.requests == [] and calls(session) == []


async def test_key_is_not_in_logs_errors_or_rows(session, conn, use, caplog):
    caplog.set_level(logging.DEBUG)
    use(AgentMock({"error": KEY}, status=401))
    with pytest.raises(SearchAgentFailed) as e:
        await ask(session, "q")
    use(AgentMock(sse({"type": "data-error", "data": {"message": KEY}})))
    with pytest.raises(SearchAgentFailed) as e2:
        await ask(session, "q")
    for err in (e.value, e2.value):
        assert KEY not in str(err) and KEY not in repr(err) and KEY not in str(vars(err))
    assert KEY not in caplog.text
    assert all(KEY not in str(vars(row)) for row in calls(session))


async def test_cost_is_recorded(session, conn, use):
    use(AgentMock({"chunks": [{"type": "data-search-chunks", "data": CHUNKS}], "references": REFS}))
    await ask(session, "q")
    use(AgentMock(sse({"type": "data-error", "data": {}})))
    with pytest.raises(SearchAgentFailed):
        await ask(session, "q")
    ok, bad = calls(session)
    assert (ok.ok, ok.cost, ok.error_code) == (True, search_agent.COST_PER_CALL, None)
    assert ok.model == ok.requested_model == search_agent.MODEL and ok.latency_ms >= 0
    assert (bad.ok, bad.error_code) == (False, "agent_error")
