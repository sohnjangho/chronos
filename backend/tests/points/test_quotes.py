"""관리 포인트 위험 줄의 근거 문장: 뒤에서 채운다(pending → ready|failed). 부른 쪽을 막지 않는다. 진짜 Liner 는 부르지 않는다."""

import asyncio
import json

import httpx
import pytest

from app.llm import search_agent
from app.llm.search_agent import AgentQuote
from app.points import quotes
from tests.llm_doubles import KEY, add_connection

OK_BODY = {"references": [{"title": "기상 특보 기준", "url": "https://weather.example.go.kr/a"}],
           "chunks": [{"type": "data-search-chunks",
                       "data": {"referenceChunks": [{"referenceId": 1, "text": "호우주의보는 3시간 60mm 이상일 때 낸다."}]}}]}
KEY_ARGS = (7, 3, "A120", "weather")


@pytest.fixture
def conn(session):
    return add_connection(session)


def answer(monkeypatch, body: object = OK_BODY, gate: asyncio.Event | None = None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if gate is not None:
            await gate.wait()
        if isinstance(body, str):
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=body)

    monkeypatch.setattr(search_agent, "TRANSPORT", httpx.MockTransport(handle))
    return seen


async def test_fill_returns_at_once_then_ready(session, conn, monkeypatch):
    gate = asyncio.Event()
    seen = answer(monkeypatch, gate=gate)
    task = quotes.fill(*KEY_ARGS, question="골조 타설 기간 비 예보")
    assert task is not None
    state = quotes.get(session, *KEY_ARGS)
    assert (state.status, state.quotes, state.message) == ("pending", [], "근거 문장 찾는 중")
    gate.set()
    await task
    session.expire_all()
    state = quotes.get(session, *KEY_ARGS)
    assert state.status == "ready" and state.message == ""
    assert state.quotes == [AgentQuote("호우주의보는 3시간 60mm 이상일 때 낸다.", "https://weather.example.go.kr/a", "기상 특보 기준")]
    assert json.loads(seen[0].content)["messages"][0]["content"] == "골조 타설 기간 비 예보"


async def test_data_error_ends_failed(session, conn, monkeypatch):
    answer(monkeypatch, "data: " + json.dumps({"type": "data-error", "data": {"message": KEY}}) + "\n\ndata: [DONE]\n\n")
    await quotes.fill(*KEY_ARGS, question="q")
    session.expire_all()
    state = quotes.get(session, *KEY_ARGS)
    assert (state.status, state.quotes, state.error_code) == ("failed", [], "agent_error")
    assert state.message == "근거 문장을 찾지 못했습니다"
    row = session.get(quotes.PointQuote, KEY_ARGS)
    assert KEY not in str(vars(row))


async def test_time_limit_ends_failed(session, conn, monkeypatch):
    answer(monkeypatch, gate=asyncio.Event())  # 끝내 답하지 않는다
    monkeypatch.setattr(quotes, "TIMEOUT_S", 0.05)
    await quotes.fill(*KEY_ARGS, question="q")
    session.expire_all()
    assert (quotes.get(session, *KEY_ARGS).status, quotes.get(session, *KEY_ARGS).error_code) == ("failed", "timeout")


async def test_no_connection_ends_failed(session, monkeypatch):
    seen = answer(monkeypatch)
    await quotes.fill(*KEY_ARGS, question="q")
    session.expire_all()
    assert quotes.get(session, *KEY_ARGS).error_code == "no_connection" and seen == []


async def test_pending_or_ready_is_not_asked_again_but_failed_is(session, conn, monkeypatch):
    gate = asyncio.Event()
    seen = answer(monkeypatch, gate=gate)
    first = quotes.fill(*KEY_ARGS, question="q")
    assert quotes.fill(*KEY_ARGS, question="q") is None  # 찾는 중
    gate.set()
    await first
    assert quotes.fill(*KEY_ARGS, question="q") is None  # 채워짐
    assert len(seen) == 1
    answer(monkeypatch, "data: [DONE]\n\n")
    await quotes.fill(7, 3, "A130", "materials", question="q")
    session.expire_all()
    assert quotes.get(session, 7, 3, "A130", "materials").status == "failed"
    seen = answer(monkeypatch)
    await quotes.fill(7, 3, "A130", "materials", question="q")  # 실패는 다시 찾을 수 있다
    session.expire_all()
    assert quotes.get(session, 7, 3, "A130", "materials").status == "ready" and len(seen) == 1


async def test_unknown_is_none_and_keys_are_separate(session, conn, monkeypatch):
    answer(monkeypatch)
    assert quotes.get(session, *KEY_ARGS) is None
    await quotes.fill(*KEY_ARGS, question="q")
    session.expire_all()
    assert quotes.get(session, 7, 4, "A120", "weather") is None
    assert quotes.get(session, 7, 3, "A120", "fx") is None
