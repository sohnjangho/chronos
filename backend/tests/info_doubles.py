"""범용 정보 API 시험용 가짜 서버·가짜 이름 풀이. 네트워크를 쓰지 않는다(httpx.MockTransport · RESOLVE 바꿔 끼우기).

공공데이터포털 모양은 tests/kma_doubles.py 의 게이트웨이 오류(gateway_body·gateway_xml)를 같이 쓴다. 값은 모두 가상이다.
"""

from urllib.parse import quote

import httpx

KEY = "GENfakeKEY+9876/5432zyxwVUTSrqpo=="  # 디코딩 키 꼴(가짜)
KEY_ENCODED = quote(KEY, safe="")  # 인코딩 키 꼴(% 포함)
BASE = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService"
HOST = "apis.data.go.kr"
PUBLIC_IP = "93.184.216.34"


def public(host: str, port: int) -> list[str]:
    """늘 공인 IP 하나로 푼다."""
    return [PUBLIC_IP]


def holiday_body() -> dict:
    return {"response": {
        "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
        "body": {"items": {"item": [{"dateKind": "01", "dateName": "기독탄신일", "isHoliday": "Y",
                                     "locdate": 20261225, "seq": 1}]},
                 "numOfRows": 10, "pageNo": 1, "totalCount": 1}}}


HOLIDAY_XML = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><response><header><resultCode>00</resultCode>"
               "<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items>"
               "<item><dateKind>01</dateKind><dateName>기독탄신일</dateName><locdate>20261225</locdate></item>"
               "<item><dateKind>01</dateKind><dateName>신정</dateName><locdate>20270101</locdate></item>"
               "</items><totalCount>2</totalCount></body></response>")


async def _chunks(body: bytes):
    yield body


def streamed(response: httpx.Response) -> httpx.Response:
    """실제 소켓처럼 아직 읽지 않은 응답으로(httpx 는 bytes 로 만든 응답을 미리 읽는다 — aiter_raw 를 쓸 수 없다)."""
    if not response.is_stream_consumed:
        return response
    return httpx.Response(response.status_code, headers=response.headers, content=_chunks(response.content))


class ApiMock(httpx.MockTransport):
    """값은 (상태, 본문[, 머리글]) · httpx.Response · 예외, 또는 request → 그것(동기·비동기).

    본문이 dict·list 면 JSON, str 이면 글(기본 text/xml), bytes 면 그대로. 받은 요청은 `.requests` 에 남는다.
    응답은 늘 아직 읽지 않은 흐름으로 준다(streamed). 압축 본문은 미리 풀리지 않게 async 반복자로 만들어 넘긴다.
    """

    def __init__(self, answer: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self.answer = (200, holiday_body()) if answer is None else answer
        super().__init__(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answer
        if callable(answer):
            answer = answer(request)
            if hasattr(answer, "__await__"):
                answer = await answer
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return streamed(answer)
        status, body, *rest = answer
        headers = rest[0] if rest else None
        if isinstance(body, dict | list):
            return streamed(httpx.Response(status, json=body, headers=headers))
        if isinstance(body, bytes):
            return streamed(httpx.Response(status, content=body, headers=headers))
        return streamed(httpx.Response(status, text=body, headers=headers or {"content-type": "text/xml;charset=UTF-8"}))
