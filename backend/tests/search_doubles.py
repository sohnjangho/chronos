"""근거 검색 시험용 가짜 Liner Search 서버. 네트워크를 쓰지 않는다(httpx.MockTransport).

`mock(200, web_body(...))` 는 받은 요청을 `.requests`·`.last` 에 남기는 transport 다.
`body` 대신 예외를 주면 그 예외를 던지고, 글(str)을 주면 그 글을 그대로 답한다.
"""

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
