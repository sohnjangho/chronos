"""근거 검색 시험용 가짜 Liner Search 서버. 네트워크를 쓰지 않는다(httpx.MockTransport).

`mock(200, web_body(...))` 는 받은 요청을 `.requests`·`.last` 에 남기는 transport 다.
`body` 대신 예외를 주면 그 예외를 던지고, 글(str)을 주면 그 글을 그대로 답한다.
"""

import json

import httpx


class SearchMock(httpx.MockTransport):
    def __init__(self, status: int, body: object) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.body = status, body
        super().__init__(self._handle)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        if isinstance(self.body, str):
            return httpx.Response(self.status, text=self.body)
        return httpx.Response(self.status, json=self.body)


def mock(status: int, body: object) -> SearchMock:
    return SearchMock(status, body)


def hit(title: str = "골조 공기 기준", url: str = "https://example.com/a", **over) -> dict:
    """Search API 의 results[] 한 줄(가상 자료)."""
    return {"title": title, "url": url, "hostname": "example.com", "faviconUrl": "https://example.com/f.ico",
            "description": "층당 8~12일", "date": "2026-03-01", **over}


def web_body(*hits: dict) -> dict:
    items = list(hits) or [hit()]
    return {"requestId": "r", "results": items, "totalCount": len(items)}


class McpMock(httpx.MockTransport):
    """가짜 Liner MCP(Streamable HTTP, 실측 11-20 모양). initialize → notifications/initialized → tools/call 에 답한다.

    `call` 이 dict 면 tools/call 의 JSON-RPC 메시지, int 면 그 상태(빈 본문), 예외면 던진다.
    `init_status` 를 주면 initialize 가 그 상태로 답한다. `sse=True` 면 JSON-RPC 응답을 `data:` 줄로 보낸다.
    """

    def __init__(self, rows: list[dict] | None = None, *, sse: bool = False, session_id: str | None = None,
                 call: object = None, init_status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.rows = [hit()] if rows is None else rows
        self.sse, self.session_id, self.call, self.init_status = sse, session_id, call, init_status
        super().__init__(self.handle)

    def bodies(self, method: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if json.loads(r.content)["method"] == method]

    def of(self, method: str) -> httpx.Request:
        return next(r for r in self.requests if json.loads(r.content)["method"] == method)

    def _reply(self, message: dict, headers: dict | None = None) -> httpx.Response:
        if self.sse:
            text = f"event: message\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream", **(headers or {})})
        return httpx.Response(200, json=message, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        method = body["method"]
        if method == "initialize":
            if self.init_status != 200:
                return httpx.Response(self.init_status, json={})
            headers = {"mcp-session-id": self.session_id} if self.session_id else None
            return self._reply({"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                "serverInfo": {"name": "liner-mcp", "version": "1.0.0"}}}, headers)
        if method == "notifications/initialized":
            return httpx.Response(202)
        if isinstance(self.call, Exception):
            raise self.call
        if isinstance(self.call, int):
            return httpx.Response(self.call, json={})
        if isinstance(self.call, dict):
            return self._reply({"jsonrpc": "2.0", "id": body["id"], **self.call})
        text = json.dumps(web_body(*self.rows), ensure_ascii=False)
        return self._reply({"jsonrpc": "2.0", "id": body["id"],
                            "result": {"content": [{"type": "text", "text": text}], "isError": False}})


def mock_json(rows: list[dict] | None = None, **over) -> McpMock:
    return McpMock(rows, **over)


def mock_sse(rows: list[dict] | None = None, **over) -> McpMock:
    return McpMock(rows, sse=True, **over)


def route(mcp: httpx.MockTransport, web: httpx.MockTransport) -> httpx.MockTransport:
    """주소가 /mcp 로 끝나면 MCP 가짜로, 아니면 Search API 가짜로 보낸다."""
    return httpx.MockTransport(lambda r: (mcp if r.url.path.endswith("/mcp") else web).handle_request(r))
