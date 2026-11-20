"""근거 검색(Liner Search API): 요청 모양·결과 읽기·오류 설명·연결 확인·키 보호. 진짜 Liner 는 부르지 않는다."""

import asyncio
import json
import logging

import httpx
import pytest

from app.llm import search
from app.llm.search import SearchFailed, SearchNotReady, liner_search
from app.store.tables import LlmConnection
from tests.llm_doubles import KEY, add_connection
from tests.search_doubles import hit, mock, web_body


@pytest.fixture
def liner_conn(session) -> LlmConnection:
    return add_connection(session)


async def test_web_search_request_and_parse(session, liner_conn):
    t = mock(200, {"requestId": "r", "results": [{"title": "골조 공기 기준", "url": "https://example.com/a", "hostname": "example.com", "description": "층당 8~12일", "date": "2026-03-01"}], "totalCount": 1})
    r = await liner_search(session, "철근콘크리트 층당 골조 공기", transport=t)
    assert t.last.method == "POST" and t.last.url.path == "/api/v1/tools/search/web"
    assert t.last.headers["x-api-key"] == KEY and t.last.headers["content-type"] == "application/json"
    assert json.loads(t.last.content) == {"query": "철근콘크리트 층당 골조 공기", "max_results": 5, "include_knowledge": False}
    assert r.hits[0].title == "골조 공기 기준"
    assert r.hits == [search.SearchHit("골조 공기 기준", "https://example.com/a", "example.com", "층당 8~12일", "2026-03-01")]
    assert r.latency_ms >= 0 and "authorization" not in t.last.headers


async def test_scholar_body_and_fields(session, liner_conn):
    paper = hit("철근콘크리트 골조 공기 연구", "https://journal.example.org/p/1", hostname="journal.example.org",
                authors=["김하늘"], journal="가상 건설학회지", citationCount=12)
    t = mock(200, web_body(paper))
    r = await liner_search(session, "골조 공기", "scholar", max_results=3, transport=t)
    assert t.last.url.path == "/api/v1/tools/search/scholar"
    assert json.loads(t.last.content) == {"query": "골조 공기", "max_results": 3}  # include_knowledge 없음
    assert r.hits[0].authors == ("김하늘",) and r.hits[0].citation_count == 12 and r.hits[0].journal == "가상 건설학회지"


@pytest.mark.parametrize("status,code,message", [
    (400, "bad_request", "검색 요청 형식이 맞지 않습니다."),
    (401, "bad_key", "API 키가 맞지 않습니다."),
    (402, "no_credit", "Liner 크레딧이 부족합니다."),
    (429, "rate_limited", "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요."),
    (500, "server_error", "검색 서버에 문제가 생겼습니다."),
    (502, "server_error", "검색 서버에 문제가 생겼습니다."),
])
async def test_search_errors_are_explained(session, liner_conn, status, code, message):
    with pytest.raises(SearchFailed) as e:
        await liner_search(session, "q", transport=mock(status, {}))
    assert e.value.code == code and e.value.message == message and str(e.value) == message
    assert e.value.__cause__ is None and e.value.__context__ is None  # 요청(머리글)을 든 예외가 따라붙지 않는다


@pytest.mark.parametrize("exc,code,message", [
    (httpx.ReadTimeout("느림"), "timeout", "응답이 너무 늦습니다."),
    (httpx.ConnectError("안 됨"), "bad_url", "주소에 연결할 수 없습니다."),
])
async def test_transport_failures_are_explained(session, liner_conn, exc, code, message):
    with pytest.raises(SearchFailed) as e:
        await liner_search(session, "q", transport=mock(200, exc))
    assert (e.value.code, e.value.message) == (code, message)


@pytest.mark.parametrize("body", ["<html>점검 중</html>", {"requestId": "r"}, {"results": "없음"}, ["목록"]])
async def test_unreadable_200_is_unknown(session, liner_conn, body):
    with pytest.raises(SearchFailed) as e:
        await liner_search(session, "q", transport=mock(200, body))
    assert (e.value.code, e.value.message) == ("unknown", "검색 결과를 읽지 못했습니다.")


async def test_the_call_has_its_own_time_limit(session, liner_conn):
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=web_body())

    with pytest.raises(SearchFailed) as e:
        await liner_search(session, "q", timeout_s=0.05, transport=httpx.MockTransport(slow))
    assert e.value.code == "timeout"


async def test_not_ready_without_liner(session):
    with pytest.raises(SearchNotReady) as e:
        await liner_search(session, "q")
    assert e.value.message == "근거 검색에는 Liner 연결이 필요합니다. 설정에서 연결해 주세요."


async def test_not_ready_when_the_default_connection_is_not_liner(session, liner_conn):
    liner_conn.provider = "openai_compatible"
    session.commit()
    t = mock(200, web_body())
    with pytest.raises(SearchNotReady) as e:
        await liner_search(session, "q", transport=t)
    assert e.value.message == "근거 검색은 Liner 연결에서만 됩니다." and t.requests == []


@pytest.mark.parametrize("ciphertext", ["깨진-암호문", None])
async def test_not_ready_when_the_key_cannot_be_read(session, liner_conn, ciphertext):
    from app.security.crypto import encrypt
    liner_conn.secret_ciphertext = ciphertext or encrypt("키 에 공백")  # 풀 수 없음 / 머리글에 실을 수 없음
    session.commit()
    t = mock(200, web_body())
    with pytest.raises(SearchNotReady) as e:
        await liner_search(session, "q", transport=t)
    assert e.value.message == "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요." and t.requests == []


async def test_only_web_links_are_kept_and_names_are_filled(session, liner_conn):
    t = mock(200, web_body(
        hit("스크립트", "javascript:alert(1)"),
        hit("주소 없음", None),
        {"title": "제목만"},
        "글 한 줄",
        hit("", "https://docs.example.net/x", hostname=None, description=None, date=None),
        hit("너무 긴 주소", "https://example.com/" + "a" * 1200),
        hit("t" * 400, "https://example.com/b", hostname="h" * 300, date="2026-03-01T00:00:00.000Z/더 붙은 글"),
    ))
    r = await liner_search(session, "q", transport=t)
    assert r.hits == [
        search.SearchHit("https://docs.example.net/x", "https://docs.example.net/x", "docs.example.net", "", None),
        search.SearchHit("t" * 300, "https://example.com/b", "h" * 200, "층당 8~12일", "2026-03-01T00:00:00."),
    ]  # 표 칸 길이(제목 300·호스트 200·날짜 20)에 맞춘다


async def test_no_more_hits_than_asked(session, liner_conn):
    t = mock(200, web_body(*[hit(f"근거 {i}", f"https://example.com/{i}") for i in range(4)]))
    r = await liner_search(session, "q", max_results=2, transport=t)
    assert [h.title for h in r.hits] == ["근거 0", "근거 1"]


async def test_module_transport_is_used_when_set(session, liner_conn, monkeypatch):
    t = mock(200, web_body())
    monkeypatch.setattr(search, "TRANSPORT", t)
    r = await liner_search(session, "q")
    assert len(t.requests) == 1 and r.hits[0].url == "https://example.com/a"


async def test_http_client_ignores_proxy_environment(session, liner_conn, monkeypatch):
    seen = {}
    real = httpx.AsyncClient

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(search.httpx, "AsyncClient", spy)
    await liner_search(session, "q", transport=mock(200, web_body()))
    assert seen["trust_env"] is False


async def test_key_is_not_in_logs_or_errors(session, liner_conn, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SearchFailed) as e:
        await liner_search(session, "q", transport=mock(401, {"error": "bad"}))
    assert KEY not in caplog.text and KEY not in repr(e.value) and KEY not in str(vars(e.value))
    assert "bad_key" in caplog.text
