"""기상청(공공데이터포털) 시험용 가짜 서버. 네트워크를 쓰지 않는다(httpx.MockTransport).

응답 모양은 PM 실측(11-20, probe_kma.py)을 따른다.
- 정상: `{response: {header: {resultCode, resultMsg}, body: {dataType, items: {item: [...]}, pageNo, numOfRows, totalCount}}}`
- 게이트웨이 오류(키 등록 안 됨 등, HTTP 403): `{OpenAPI_ServiceResponse: {cmmMsgHeader: {errMsg, returnAuthMsg, returnReasonCode}}}`
- ASOS 일자료 값은 모두 글(str)이고 없는 값은 빈 글이다. 단기예보 fcstValue 는 글, nx·ny 는 수.
"""

from urllib.parse import quote

import httpx

KEY = "FAKEkmaKEY+0123/4567abcdEFGHijkl=="  # 디코딩 키 꼴(가짜)
KEY_ENCODED = quote(KEY, safe="")  # 인코딩 키 꼴(% 포함)


def ok_body(items: list[dict], total: int | None = None) -> dict:
    return {"response": {
        "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
        "body": {"dataType": "JSON", "items": {"item": items}, "pageNo": 1, "numOfRows": len(items),
                 "totalCount": len(items) if total is None else total}}}


def no_data_body() -> dict:
    return {"response": {"header": {"resultCode": "03", "resultMsg": "NO_DATA"}}}


def gateway_body(code: str, auth_msg: str = "등록되지 않은 서비스키") -> dict:
    return {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
        "errMsg": "SERVICE ERROR", "returnAuthMsg": auth_msg, "returnReasonCode": code}}}


def gateway_xml(code: str) -> str:
    return ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
            f"<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>{code}"
            "</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")


def asos_day(tm: str, avg: str, tmin: str, rain: str = "", stn: str = "108") -> dict:
    """ASOS 일자료 한 줄(가상 값). 실제 응답은 칸이 더 많다 — 몇 개만 둔다."""
    return {"stnId": stn, "stnNm": "서울", "tm": tm, "avgTa": avg, "minTa": tmin, "minTaHrmt": "",
            "maxTa": "", "sumRn": rain, "avgWs": "1.5", "avgRhm": "60.0"}


def fcst(day: str, time: str, category: str, value: str, base: tuple[str, str] = ("20261120", "2000")) -> dict:
    return {"baseDate": base[0], "baseTime": base[1], "category": category, "fcstDate": day,
            "fcstTime": time, "fcstValue": value, "nx": 60, "ny": 127}


class KmaMock(httpx.MockTransport):
    """경로로 ASOS·단기예보를 나눈다. 값은 (상태, 본문) 또는 request → (상태, 본문) 함수.

    본문이 dict 면 JSON, str 이면 XML 글, 예외면 던진다. 받은 요청은 `.requests` 에 남는다.
    """

    def __init__(self, asos: object = None, fcst: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self.asos, self.fcst = asos, fcst
        super().__init__(self._handle)

    def of(self, service: str) -> list[httpx.Request]:
        return [r for r in self.requests if service in r.url.path]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.asos if "AsosDalyInfoService" in request.url.path else self.fcst
        if callable(answer):
            answer = answer(request)
        if answer is None:
            return httpx.Response(599)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers={"content-type": "text/xml;charset=UTF-8"})
        return httpx.Response(status, json=body)
