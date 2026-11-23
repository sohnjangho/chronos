"""기상청 공공데이터(공공데이터포털): ASOS 일자료(`AsosDalyInfoService`)와 단기예보(`VilageFcstInfoService_2.0`).

- 키는 질의 `serviceKey` 로만 보낸다. 인코딩 키(`%` 가 있음)는 그대로, 디코딩 키는 한 번만 인코딩한다.
  키가 주소에 실리므로 주소·예외 글은 기록하지 않고, httpx 의 요청 기록 줄에서도 키를 지운다(_HideServiceKey).
- 실패는 KmaFailed(code, 한국어 message). 게이트웨이 오류(`OpenAPI_ServiceResponse.cmmMsgHeader`, JSON 또는 XML)의
  returnReasonCode 와 응답 머리(`response.header.resultCode`)를 같은 표로 읽는다. 03(NO_DATA)은 빈 목록이다.
- 다시 시도하지 않는다. 값은 코드가 읽기만 한다(TMN·TMX 가 없는 날은 None — TMP 로 채우지 않는다).
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://apis.data.go.kr/1360000"
ASOS_PATH = "/AsosDalyInfoService/getWthrDataList"
FCST_PATH = "/VilageFcstInfoService_2.0/getVilageFcst"
KST = ZoneInfo("Asia/Seoul")
RELEASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)  # 단기예보 발표 시각. 각 발표 + 10분부터 받는다
FCST_ROWS = 1500  # 실측 totalCount 1016(한 번에 받는다)
ASOS_MAX_DAYS = 999
TIMEOUT_S = 20.0

# 시험이 가짜 transport 를 바꿔 끼운다.
TRANSPORT: httpx.AsyncBaseTransport | None = None

FAILED_MESSAGES = {
    "not_registered": "이 서비스키는 해당 기상청 서비스에 등록되지 않았습니다(공공데이터포털에서 활용신청을 확인해 주세요).",
    "key_expired": "서비스키 활용 기간이 지났습니다(공공데이터포털에서 기간을 연장해 주세요).",
    "ip_not_allowed": "이 서버의 IP 가 서비스키에 등록되지 않았습니다(공공데이터포털에서 허용 IP 를 확인해 주세요).",
    "rate_limited": "공공데이터포털 호출 한도를 넘었습니다. 내일 다시 해 주세요.",
    "bad_key": "서비스키가 맞지 않습니다. 설정에서 키를 확인해 주세요.",
    "bad_request": "기상청 요청 형식이 맞지 않습니다.",
    "server_error": "기상청 서버에 문제가 생겼습니다. 잠시 뒤 다시 해 주세요.",
    "timeout": "기상청 응답이 너무 늦습니다.",
    "bad_url": "기상청 주소에 연결할 수 없습니다.",
    "unknown": "기상청 응답을 읽지 못했습니다.",
}
# returnReasonCode·resultCode → code. 00 정상, 03 자료 없음은 따로 다룬다.
REASONS = {
    "30": "not_registered", "31": "key_expired", "32": "ip_not_allowed", "22": "rate_limited",
    "20": "bad_key", "21": "bad_key", "33": "bad_key",
    "10": "bad_request", "11": "bad_request", "12": "bad_url",
    "01": "server_error", "02": "server_error", "04": "server_error", "05": "server_error",
}
STATUS = {400: "bad_request", 401: "bad_key", 403: "bad_key", 404: "bad_url", 429: "rate_limited"}
_XML_CODE = re.compile(r"<(returnReasonCode|resultCode)>\s*(\d+)\s*<")


@dataclass(frozen=True)
class KmaConn:
    base_url: str
    key: str  # 인코딩·디코딩 어느 쪽이든


@dataclass(frozen=True)
class DayObs:
    date: date
    tavg: float | None  # avgTa
    tmin: float | None  # minTa
    rain_mm: float  # sumRn. 빈 값 = 비 없음(0)


@dataclass(frozen=True)
class DayFcst:
    date: date
    tmin: float | None  # TMN(없으면 None)
    tmax: float | None  # TMX(없으면 None)
    pop: int | None  # 그날 POP 의 최댓값(%)


class KmaFailed(Exception):
    """불렀지만 실패했다. code 는 FAILED_MESSAGES 의 열쇠. 키·주소는 담지 않는다."""

    def __init__(self, code: str) -> None:
        super().__init__(FAILED_MESSAGES[code])
        self.code, self.message = code, FAILED_MESSAGES[code]


class _HideServiceKey(logging.Filter):
    """httpx 가 남기는 요청 줄(주소 포함)에서 serviceKey 값을 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        if "serviceKey=" in text:
            record.msg, record.args = re.sub(r"serviceKey=[^&\s\"']*", "serviceKey=…", text), ()
        return True


logging.getLogger("httpx").addFilter(_HideServiceKey())


def encoded(key: str) -> str:
    return key if "%" in key else quote(key, safe="")


def base_datetime(now: datetime) -> tuple[str, str]:
    """(base_date, base_time). 02·05·…·23시 발표, 발표 + 10분부터. 02:10 전이면 전날 2300. now 는 KST."""
    for hour in reversed(RELEASE_HOURS):
        if (now.hour, now.minute) >= (hour, 10):
            return now.strftime("%Y%m%d"), f"{hour:02d}00"
    return (now - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def _reason(data: object, text: str) -> str | None:
    """게이트웨이 오류·응답 머리의 코드(글). JSON 이 아니면 XML 글에서 찾는다."""
    if isinstance(data, dict):
        gate = data.get("OpenAPI_ServiceResponse")
        if isinstance(gate, dict):
            return str((gate.get("cmmMsgHeader") or {}).get("returnReasonCode") or "99")
        header = (data.get("response") or {}).get("header") if isinstance(data.get("response"), dict) else None
        return str(header.get("resultCode")) if isinstance(header, dict) else None
    found = _XML_CODE.search(text)
    return found.group(2) if found else None


async def _get(conn: KmaConn, path: str, params: dict[str, str]) -> list[dict]:
    """한 번 불러 item 목록을 돌려준다. NO_DATA 면 []. 실패는 KmaFailed(except 밖에서 던진다)."""
    url = f"{conn.base_url.rstrip('/')}{path}?serviceKey={encoded(conn.key)}&{urlencode(params)}"
    code: str | None = None
    try:
        async with httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_S, trust_env=False) as http:
            response = await http.get(url)
    except httpx.TimeoutException:
        code = "timeout"
    except httpx.HTTPError as exc:  # 예외 글에 주소(키)가 있어 종류만 남긴다
        code = "bad_url" if isinstance(exc, httpx.ConnectError | httpx.UnsupportedProtocol) else "unknown"
    if code is None:
        try:
            data: object = response.json()
        except ValueError:
            data = None
        reason = _reason(data, response.text)
        if reason == "03":
            return []
        if reason not in (None, "00"):
            code = REASONS.get(reason.zfill(2), "unknown")
        elif response.status_code >= 500:
            code = "server_error"
        elif response.status_code >= 400:
            code = STATUS.get(response.status_code, "unknown")
        elif reason is None or not isinstance(data, dict):  # 읽을 수 없는 본문(XML 성공 응답 등)
            code = "unknown"
    if code is not None:
        logger.warning("기상청 호출 실패: %s code=%s", path, code)
        raise KmaFailed(code)
    body = data["response"].get("body") or {}
    items = (body.get("items") or {}) if isinstance(body, dict) else {}
    rows = items.get("item") if isinstance(items, dict) else None
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _num(value: object) -> float | None:
    try:
        return float(value) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


async def asos_daily(conn: KmaConn, stn: str, start: date, end: date) -> list[DayObs]:
    """지점 stn 의 start~end 일자료(날짜 차례). 한 번에 999일까지."""
    if (end - start).days + 1 > ASOS_MAX_DAYS:
        raise ValueError("한 번에 999일까지 받는다.")
    rows = await _get(conn, ASOS_PATH, {
        "pageNo": "1", "numOfRows": str(ASOS_MAX_DAYS), "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": start.strftime("%Y%m%d"), "endDt": end.strftime("%Y%m%d"), "stnIds": stn})
    days = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("tm")))
        except ValueError:
            continue
        days.append(DayObs(day, _num(row.get("avgTa")), _num(row.get("minTa")), _num(row.get("sumRn")) or 0.0))
    return sorted(days, key=lambda d: d.date)


async def short_forecast(conn: KmaConn, nx: int, ny: int, *, now: datetime | None = None) -> list[DayFcst]:
    """격자 nx·ny 의 단기예보를 하루별로(날짜 차례). TMN·TMX 는 그날 값 그대로, POP 은 그날 최댓값."""
    base_date, base_time = base_datetime(now or datetime.now(KST))
    rows = await _get(conn, FCST_PATH, {
        "pageNo": "1", "numOfRows": str(FCST_ROWS), "dataType": "JSON", "base_date": base_date,
        "base_time": base_time, "nx": str(nx), "ny": str(ny)})
    found: dict[str, dict[str, float | None]] = {}
    for row in rows:
        category, value = row.get("category"), _num(row.get("fcstValue"))
        day = found.setdefault(str(row.get("fcstDate")), {"TMN": None, "TMX": None, "POP": None})
        if category in ("TMN", "TMX") and value is not None and day[category] is None:
            day[category] = value
        elif category == "POP" and value is not None:
            day["POP"] = value if day["POP"] is None else max(day["POP"], value)
    out = []
    for key, day in sorted(found.items()):
        try:
            when = datetime.strptime(key, "%Y%m%d").date()
        except ValueError:
            continue
        out.append(DayFcst(when, day["TMN"], day["TMX"], None if day["POP"] is None else int(day["POP"])))
    return out
