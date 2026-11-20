"""분야 검색(Liner MCP search_legal·search_business): 세션 열기·결과 읽기·오류 설명·키 보호.

진짜 Liner 는 부르지 않는다(httpx.MockTransport). 모양은 11-20 실측(docs/dev-journal/2026-11.md)을 따른다.
"""

import asyncio
import json
import logging

import httpx
import pytest

from app.llm import mcp_client, search
from app.llm.mcp_client import call_tool, field_search
from app.llm.search import SearchFailed, SearchHit
from tests.llm_doubles import KEY, add_connection
from tests.search_doubles import hit, mock_json, mock_sse

BASE = "https://platform.liner.com/api/v1"


async def test_call_tool_json_response():
    t = mock_json([{"title": "건축법 시행령", "url": "https://law.example/1"}])
    r = await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=t)
    assert r[0]["title"] == "건축법 시행령"
    assert [json.loads(x.content)["method"] for x in t.requests] == ["initialize", "notifications/initialized",
                                                                     "tools/call"]
    assert all(x.method == "POST" and str(x.url) == f"{BASE}/mcp" for x in t.requests)
    assert t.of("tools/call").headers["accept"] == "application/json, text/event-stream"
    call = t.bodies("tools/call")[0]
    assert call["jsonrpc"] == "2.0" and call["params"] == {"name": "search_legal", "arguments": {"query": "q"}}
    assert "id" not in t.bodies("notifications/initialized")[0]
    assert t.of("tools/call").headers["mcp-protocol-version"] == "2025-06-18"


async def test_call_tool_sse_response():
    r = await call_tool(BASE, "k", "search_business", {"query": "q"},
                        transport=mock_sse([hit("철근 납기", "https://supplier.example/1")]))
    assert r[0]["url"].startswith("https://") and r[0]["title"] == "철근 납기"


async def test_session_id_is_reused():
    t = mock_json(session_id="s-123")
    await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=t)
    assert "mcp-session-id" not in t.of("initialize").headers
    assert t.of("notifications/initialized").headers["mcp-session-id"] == "s-123"
    assert t.of("tools/call").headers["mcp-session-id"] == "s-123"


async def test_no_session_header_when_the_server_gives_none():
    t = mock_json()  # 실측: Liner 는 Mcp-Session-Id 를 주지 않았다
    await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=t)
    assert all("mcp-session-id" not in x.headers for x in t.requests)


async def test_bearer_header_and_no_key_in_errors(caplog):
    caplog.set_level(logging.DEBUG)
    t = mock_json(init_status=401)
    with pytest.raises(SearchFailed) as e:
        await call_tool(BASE, KEY, "search_legal", {"query": "q"}, transport=t)
    assert t.requests[0].headers["authorization"] == f"Bearer {KEY}" and "x-api-key" not in t.requests[0].headers
    assert e.value.code == "bad_key" and e.value.message == "API 키가 맞지 않습니다."
    assert KEY not in str(e.value) and KEY not in caplog.text
    assert e.value.__cause__ is None and e.value.__context__ is None  # 요청(머리글)을 든 예외가 따라붙지 않는다


@pytest.mark.parametrize("call,code", [
    (429, "rate_limited"),
    (503, "server_error"),
    ({"error": {"code": -32602, "message": "Invalid params"}}, "bad_request"),
    ({"error": {"code": -32603, "message": "Internal error"}}, "server_error"),
    ({"result": {"content": [{"type": "text", "text": "검색 실패"}], "isError": True}}, "server_error"),
    ({"result": {"content": [{"type": "text", "text": "JSON 아님"}], "isError": False}}, "unknown"),
    ({"result": {"content": [{"type": "text", "text": "{\"answer\": 1}"}]}}, "unknown"),
    ({"result": "글"}, "unknown"),
    (httpx.ReadTimeout("느림"), "timeout"),
    (httpx.ConnectError("안 됨"), "bad_url"),
])
async def test_failures_use_the_search_messages(call, code):
    with pytest.raises(SearchFailed) as e:
        await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=mock_json(call=call))
    assert e.value.code == code and e.value.message == search.FAILED_MESSAGES[code]
    assert e.value.__context__ is None


async def test_structured_content_is_read():
    t = mock_json(call={"result": {"content": [], "structuredContent": {"results": [hit()]}}})
    r = await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=t)
    assert r[0]["url"] == "https://example.com/a"


async def test_sse_skips_other_messages():
    class Noisy(httpx.MockTransport):
        def __init__(self):
            super().__init__(self.handle)

        def handle(self, request):
            body = json.loads(request.content)
            if body["method"] == "notifications/initialized":
                return httpx.Response(202)
            if body["method"] == "initialize":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
            result = {"content": [{"type": "text", "text": json.dumps({"results": [hit()]})}]}
            text = (": ping\n\nevent: message\ndata: {\"jsonrpc\": \"2.0\", \"method\": \"notifications/progress\"}\n\n"
                    f"data: {json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result})}\n\n")
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream; charset=utf-8"})

    r = await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=Noisy())
    assert r[0]["title"] == "골조 공기 기준"


async def test_the_call_has_its_own_time_limit():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    with pytest.raises(SearchFailed) as e:
        await call_tool(BASE, "k", "search_legal", {"query": "q"}, timeout=0.05, transport=httpx.MockTransport(slow))
    assert e.value.code == "timeout"


async def test_field_search_uses_the_default_connection(session):
    add_connection(session)
    t = mock_json([hit("착공신고 처리 기한", "https://law.example/2"), hit("주소 없음", "javascript:alert(1)")])
    r = await field_search(session, "착공신고 처리 기한", "legal", max_results=3, transport=t)
    assert t.of("tools/call").headers["authorization"] == f"Bearer {KEY}"
    assert t.bodies("tools/call")[0]["params"] == {"name": "search_legal",
                                                   "arguments": {"query": "착공신고 처리 기한", "limit": 3}}
    assert r.hits == [SearchHit("착공신고 처리 기한", "https://law.example/2", "example.com", "층당 8~12일", "2026-03-01")]
    assert r.latency_ms >= 0


async def test_field_search_business_and_module_transport(session, monkeypatch):
    add_connection(session)
    t = mock_json()
    monkeypatch.setattr(search, "TRANSPORT", t)
    await field_search(session, "철근 공급업체 납기", "business")
    assert t.bodies("tools/call")[0]["params"]["name"] == "search_business"
    assert mcp_client.FIELD_TOOLS == {"legal": "search_legal", "business": "search_business"}


async def test_field_search_needs_a_liner_connection(session):
    with pytest.raises(search.SearchNotReady):
        await field_search(session, "q", "legal", transport=mock_json())


async def test_field_search_time_limit_matches_web(session, monkeypatch):
    add_connection(session)
    seen = {}

    async def fake_call(base_url, secret, name, arguments, *, timeout, transport):
        seen["timeout"] = timeout
        return []

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    await field_search(session, "q", "legal")
    assert seen["timeout"] == 20
