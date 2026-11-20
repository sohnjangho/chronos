"""기상청 공공데이터 실측(Task 52 Step 0): ASOS 일자료 1번 + 단기예보 1번을 부르고 응답 모양을 찍는다.

사용(저장소 폴더에서, 키는 명령줄 환경 변수로만):
    KMA_SERVICE_KEY='<서비스키>' backend/.venv/bin/python backend/scripts/probe_kma.py

- 키는 환경 변수 `KMA_SERVICE_KEY` 로만 받는다. 인코딩 키(`%` 가 들어 있음)는 그대로, 디코딩 키는 한 번만
  인코딩해 질의 `serviceKey` 에 싣는다. 주소·키는 찍지 않고, 찍는 글에서 키와 키처럼 긴 토큰을 지운다.
- 요청은 최대 2번. 앱 DB·data/ 는 건드리지 않는다.
- ASOS: 서울(108), 지난 12월 1~7일. 단기예보: 서울 격자 60·127, 오늘 발표 규칙(02·05·…·23시 + 10분, KST).
- 인증 실패 등은 XML 로 오므로 오류 코드·글을 읽어 찍는다.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote, urlencode
from zoneinfo import ZoneInfo

import httpx

MAX_REQUESTS = 2
TIMEOUT_S = 30.0
KST = ZoneInfo("Asia/Seoul")
ASOS_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
FCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
RELEASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
ASOS_FIELDS = ("tm", "stnId", "stnNm", "avgTa", "minTa", "maxTa", "sumRn")
FCST_CATEGORIES = ("TMN", "TMX", "POP")
XML_TAGS = ("errMsg", "returnAuthMsg", "returnReasonCode", "resultCode", "resultMsg")


class Probe:
    def __init__(self, key: str) -> None:
        self._secrets = {s for s in (key, unquote(key), quote(unquote(key), safe="")) if s}
        # 인코딩 키는 그대로 쓰고, 디코딩 키만 한 번 인코딩한다(두 번 인코딩하면 인증 실패).
        self._key_q = key if "%" in key else quote(key, safe="")
        self.sent = 0

    def clean(self, text: object, limit: int = 200) -> str:
        """키와 키처럼 긴 토큰을 지우고 한 줄로 자른다."""
        out = str(text)
        for s in self._secrets:
            out = out.replace(s, "…")
        out = re.sub(r"[A-Za-z0-9%+/=_\-]{40,}", "…", out)
        return re.sub(r"\s+", " ", out).strip()[:limit]

    def get(self, http: httpx.Client, label: str, url: str, params: dict[str, str]) -> object:
        """한 번 보내고 JSON(dict) 또는 None 을 돌려준다. 상태·종류·시간·결과 코드를 찍는다."""
        if self.sent >= MAX_REQUESTS:
            raise SystemExit("요청 상한에 닿아 멈춘다.")
        self.sent += 1
        full = f"{url}?serviceKey={self._key_q}&{urlencode(params)}"  # 키는 이미 인코딩됨 — params 와 따로 붙인다
        start = time.perf_counter()
        try:
            r = http.get(full)
        except httpx.HTTPError as e:  # 메시지에 주소(키)가 들어 있을 수 있어 종류만 찍는다
            print(f"[{self.sent}] {label}: 통신 실패 {type(e).__name__} ({ms_since(start)}ms)")
            return None
        kind = r.headers.get("content-type", "-")
        print(f"[{self.sent}] {label}: HTTP {r.status_code} · {kind} · {ms_since(start)}ms · {len(r.content)}B")
        try:
            data = r.json()
        except ValueError:
            show_non_json(self, r.text)
            return None
        header = data.get("response", {}).get("header", {}) if isinstance(data, dict) else {}
        print(f"    resultCode={header.get('resultCode')} resultMsg={self.clean(header.get('resultMsg'))}")
        gate = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {}) if isinstance(data, dict) else {}
        if gate:  # 게이트웨이 오류(인증·등록·한도)는 JSON 이어도 이 칸에 까닭이 온다
            print("    게이트웨이 오류: " + self.clean(" · ".join(f"{k}={gate.get(k)}" for k in XML_TAGS[:3]), 300))
        print(f"    구조: {structure(data)}")
        return data


def ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def show_non_json(p: Probe, text: str) -> None:
    """XML(인증 실패 등)이면 오류 칸을, 아니면 본문 앞부분을 찍는다."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        print(f"    JSON·XML 아님. 본문: {p.clean(text, 300)}")
        return
    found = {tag: el.text for tag in XML_TAGS if (el := root.find(f".//{tag}")) is not None}
    print(f"    XML 응답(뿌리 <{root.tag}>): {p.clean(found, 300) if found else p.clean(text, 300)}")


def structure(obj: object, depth: int = 0) -> str:
    """dict/list 의 칸 이름만 펼쳐 한 줄로 보인다(값은 빼고)."""
    if depth > 5:
        return "…"
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{k}: {structure(v, depth + 1)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return f"[{len(obj)}× {structure(obj[0], depth + 1)}]" if obj else "[]"
    return type(obj).__name__


def items_of(data: object) -> tuple[list[dict], object]:
    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    items = body.get("items") if isinstance(body, dict) else None
    rows = items.get("item") if isinstance(items, dict) else None
    if isinstance(rows, dict):  # 한 줄이면 목록이 아니라 dict 로 오는 경우가 있다
        rows = [rows]
    return (rows if isinstance(rows, list) else []), (body.get("totalCount") if isinstance(body, dict) else None)


def show_asos(p: Probe, data: object) -> None:
    rows, total = items_of(data)
    print(f"    item {len(rows)}줄 (totalCount={total})")
    if not rows:
        return
    print(f"    칸 {len(rows[0])}개: {sorted(rows[0])}")
    for row in rows[:7]:
        print("      " + p.clean(" · ".join(f"{k}={row.get(k)!r}" for k in ASOS_FIELDS), 200))


def show_fcst(p: Probe, data: object) -> None:
    rows, total = items_of(data)
    print(f"    item {len(rows)}줄 (totalCount={total})")
    if not rows:
        return
    print(f"    칸: {sorted(rows[0])}")
    print(f"    첫 줄: {p.clean(json.dumps(rows[0], ensure_ascii=False), 300)}")
    print(f"    category 종류: {sorted({r.get('category') for r in rows})}")
    by_date: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        if r.get("category") in FCST_CATEGORIES:
            cell = by_date.setdefault(str(r.get("fcstDate")), {c: [] for c in FCST_CATEGORIES})
            cell[r["category"]].append(f"{r.get('fcstTime')}={r.get('fcstValue')!r}")
    for day, cats in sorted(by_date.items()):
        pop = cats["POP"]
        print(f"      {day}: TMN {cats['TMN']} · TMX {cats['TMX']} · POP {len(pop)}개 예 {pop[:4]}")


def last_december() -> tuple[str, str]:
    year = date.today().year - 1
    return f"{year}1201", f"{year}1207"


def base_datetime(now: datetime) -> tuple[str, str]:
    """단기예보 발표 규칙: 02·05·…·23시 발표, 각 발표 + 10분부터 받을 수 있다. 02:10 전이면 전날 23시."""
    for hour in reversed(RELEASE_HOURS):
        if (now.hour, now.minute) >= (hour, 10):
            return now.strftime("%Y%m%d"), f"{hour:02d}00"
    return (now - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def main() -> int:
    key = os.environ.get("KMA_SERVICE_KEY", "").strip()
    if not key:
        print("환경 변수 KMA_SERVICE_KEY 가 없다. 멈춘다.")
        return 1
    p = Probe(key)
    print(f"키 형태: {'인코딩 키(% 포함 — 그대로 씀)' if '%' in key else '디코딩 키(한 번 인코딩해 씀)'} · {len(key)}자")
    if '%25' in key:
        print('    주의: %25 가 있음 — 인코딩 키를 한 번 더 인코딩한 것으로 보입니다(디코딩 키를 넣어 보세요).')
    if len(key) > 150:
        print('    주의: 공공데이터포털 일반 인증키(약 100자 안팎)보다 깁니다 — 키 두 개를 붙였거나 다른 글이 섞였는지 확인하세요.')
    start_dt, end_dt = last_december()
    now = datetime.now(KST)
    base_date, base_time = base_datetime(now)
    with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as http:
        print(f"\nASOS 일자료: 서울 108 · {start_dt}~{end_dt}")
        asos = p.get(http, "AsosDalyInfoService/getWthrDataList", ASOS_URL, {
            "pageNo": "1", "numOfRows": "10", "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
            "startDt": start_dt, "endDt": end_dt, "stnIds": "108"})
        if asos is not None:
            show_asos(p, asos)
        print(f"\n단기예보: 격자 60·127 · 지금 {now:%Y-%m-%d %H:%M} KST → base {base_date} {base_time}")
        fcst = p.get(http, "VilageFcstInfoService_2.0/getVilageFcst", FCST_URL, {
            "pageNo": "1", "numOfRows": "1000", "dataType": "JSON",
            "base_date": base_date, "base_time": base_time, "nx": "60", "ny": "127"})
        if fcst is not None:
            show_fcst(p, fcst)
    print(f"\n요청 수: {p.sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
