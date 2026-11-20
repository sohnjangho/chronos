"""보고서용 그림: Liner Visualization API(`POST {base_url}/tools/visualization`, stream:false) + 받은 HTML 숫자 대조.

- 요청 글 = 코드에 둔 고정 틀(FRAME) + 표 CSV. 표는 app.store.visuals 가 저장된 일정에서 만든다. `is_search_context` 는
  넣지 않는다(외부 숫자가 섞이지 않게). 응답(실측 11-20): {chunks: [start, start-step, data-atlas, finish-step, finish]},
  data-atlas.data.atlasArtifact = {html, theme, description, resourceId}. 약 11초.
- 키는 기본 LLM 연결(provider liner)의 것을 서버에서 풀어 `x-api-key` 머리글로만 보낸다. 기록·예외·결과에 담지 않는다.
- 초당 2회 한도: 호출 시작 사이를 MIN_GAP_S 이상 둔다(한 번에 하나씩).
- 대조(verify, 컨트롤러 판정 11-20): (a) 우리 표의 모든 값·날짜가 HTML 에 그대로 있다. (b) 차트 데이터 배열
  (`data: [...]`·`labels: [...]`·`const x = [...]`)에 표에 없는 값·날짜가 없다. (c) 축 범위(min·max·suggestedMin·
  suggestedMax)의 날짜는 표 날짜 범위에서 한 달(31일) 안. (d) 그 밖에 HTML 어디에도 표에 없는 날짜가 없다.
  차트 설정(`new Chart(`)을 읽지 못하면 실패다.
- make: 같은 입력의 통과한 그림이 있으면 다시 부르지 않는다. 실패하면 한 번 다시, 또 실패하면 우리 그림(fallback)으로
  저장하고 「Liner 그림 검증 실패 → 기본 그림」을 경고로 남긴다. 부르기 전에 commit 한다(쓰기 잠금을 쥐고 기다리지 않게).
"""

import asyncio
import csv
import hashlib
import html as html_lib
import io
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from sqlalchemy.orm import Session

from app.llm.assignments import default_connection
from app.llm.connections import secret_is_sendable
from app.security.crypto import SecretUnreadable, decrypt
from app.store import visuals
from app.store.tables import Visual
from app.store.visuals import VisualTable

logger = logging.getLogger(__name__)

# 시험이 가짜 transport 를 바꿔 끼운다. None 이 아니면 liner_visualize 의 transport 인자 대신 쓴다.
TRANSPORT: httpx.AsyncBaseTransport | None = None
MIN_GAP_S = 0.5  # 초당 2회 한도
TIMEOUT_S = 45.0  # 한 번 부르기(문서: 평균 20~30초, 실측 11초)
ATTEMPTS = 2  # 처음 + 다시 한 번
AXIS_SLACK = timedelta(days=31)

CHARTS = {"timeline": "작업별 시작부터 끝까지를 가로 막대(기간)로 보이는 그림",
          "bars": "첫 열을 항목으로 하는 가로 막대 그래프(숫자 열마다 막대)",
          "line": "첫 열(날짜)을 x축으로 하는 선 그래프(숫자 열마다 선)"}
FRAME = ("아래 표의 값만 그대로 써서 {chart}을 그려라. 값을 계산·반올림·추정·추가하지 마라. 표에 없는 날짜나 값을 넣지 "
         "마라. 이름·날짜(YYYY-MM-DD)·숫자는 표에 적힌 글자 그대로 쓴다. 빈 칸은 값이 없는 것이다. 제목: {title}\n\n")
FAILED_MESSAGES = {"not_ready": "Liner 연결이 없어 기본 그림", "verify": "Liner 그림 검증 실패 → 기본 그림"}
_STATUS_CODES = {400: "bad_request", 401: "bad_key", 402: "no_credit", 403: "bad_key", 404: "bad_url", 429: "rate_limited"}
_NO_RETRY = frozenset({"bad_request", "bad_key", "no_credit", "bad_url"})  # 다시 해도 같은 실패
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError)

_last_start = 0.0
_lock = asyncio.Lock()


class VisualNotReady(Exception):
    """부를 수 없다(연결 없음·Liner 연결 아님·키를 읽을 수 없음). 보내지 않았다."""


class VisualFailed(Exception):
    """불렀지만 그림을 받지 못했다. code: bad_request·bad_key·no_credit·rate_limited·server_error·timeout·bad_url·unknown."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Atlas:
    html: str
    theme: str
    description: str
    resource_id: str
    latency_ms: int


@dataclass(frozen=True)
class Verdict:
    ok: bool
    passed: int  # HTML 에 그대로 있는 표 값 수
    total: int  # 표 값 수(빈 칸 빼고)
    problems: list[str]
    external: list[str]  # 외부 script·link 주소(받은 차례)


# ── 부르기 ───────────────────────────────────────────────────────────


def _target(session: Session) -> tuple[str, str]:
    """(주소, 키). 부른 쪽 세션의 쌓인 변경을 flush 하지 않는다."""
    with session.no_autoflush:
        conn = default_connection(session)
    if conn is None or conn.provider != "liner":
        raise VisualNotReady
    try:
        key = decrypt(conn.secret_ciphertext)
    except SecretUnreadable:
        raise VisualNotReady from None
    if not secret_is_sendable(key):
        raise VisualNotReady
    return conn.base_url.rstrip("/"), key


def _code(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return "server_error" if status >= 500 else _STATUS_CODES.get(status, "unknown")
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol | httpx.ConnectError):
        return "bad_url"
    return "unknown"


class _Unreadable(ValueError):
    """200 이지만 그림(data-atlas 의 html)이 없다 — data-error 이거나 모양이 다르다(→ unknown)."""


def _text(art: dict, key: str) -> str:
    return art[key] if isinstance(art.get(key), str) else ""


def _atlas(data: object, latency_ms: int) -> Atlas:
    """chunks 의 data-atlas 에서 atlasArtifact 를 읽는다. 없으면 _Unreadable."""
    chunks = data.get("chunks") if isinstance(data, dict) else None
    arts = [c["data"].get("atlasArtifact") for c in chunks or []
            if isinstance(c, dict) and c.get("type") == "data-atlas" and isinstance(c.get("data"), dict)
            ] if isinstance(chunks, list) else []
    art = next((a for a in arts if isinstance(a, dict) and _text(a, "html")), None)
    if art is None:
        raise _Unreadable
    return Atlas(art["html"], _text(art, "theme"), _text(art, "description"), _text(art, "resourceId"), latency_ms)


async def _wait_turn() -> None:
    global _last_start
    gap = MIN_GAP_S - (time.monotonic() - _last_start)
    if gap > 0:
        await asyncio.sleep(gap)
    _last_start = time.monotonic()


async def liner_visualize(session: Session, query: str, *, timeout_s: float = TIMEOUT_S,
                          transport: httpx.AsyncBaseTransport | None = None) -> Atlas:
    """한 번 그린다. 부를 수 없으면 VisualNotReady(보내지 않음), 보낸 뒤 실패하면 VisualFailed. 세션은 읽기만 한다."""
    base_url, key = _target(session)
    chosen = TRANSPORT if TRANSPORT is not None else transport
    code: str | None = None
    async with _lock:
        await _wait_turn()
        start = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_s):
                # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
                async with httpx.AsyncClient(transport=chosen, timeout=timeout_s, trust_env=False) as http:
                    response = await http.post(f"{base_url}/tools/visualization",
                                               headers={"x-api-key": key, "Content-Type": "application/json"},
                                               json={"query": query, "stream": False})
            response.raise_for_status()
            atlas = _atlas(response.json(), int((time.perf_counter() - start) * 1000))
        except _FAILURES as exc:
            code = _code(exc)
            logger.warning("Liner 그림 부르기 실패: code=%s (%s)", code, type(exc).__name__)  # 예외 내용은 남기지 않는다
    if code is not None:
        raise VisualFailed(code)  # except 밖에서 던져 요청(머리글)을 든 예외가 따라붙지 않게
    return atlas


# ── 요청 글 ──────────────────────────────────────────────────────────


def cell_text(v: object) -> str:
    return "" if v is None else str(v)


def query_text(table: VisualTable) -> str:
    """고정 틀 + CSV(머리줄 = 열 이름)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(table.columns)
    writer.writerows([[cell_text(v) for v in row] for row in table.rows])
    return FRAME.format(chart=CHARTS[table.chart], title=table.title) + out.getvalue()


# ── 대조 ─────────────────────────────────────────────────────────────

_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_INLINE = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_EXTERNAL = re.compile(r"""<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ARRAY = re.compile(r"(?:\b(?:data|labels)\s*:|\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=)\s*\[")
_BOUND = re.compile(r"\b(?:min|max|suggestedMin|suggestedMax)\s*:\s*([^,}\n]+)")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|var)\(.*\)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_QUOTES = "'\"`"


def _string_end(text: str, i: int) -> int:
    """text[i] 가 따옴표일 때 그 글의 닫는 따옴표 다음 위치."""
    quote, i = text[i], i + 1
    while i < len(text) and text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _array_end(text: str, i: int) -> int:
    """text[i] == '[' 의 짝 ']' 다음 위치(글·주석 안의 괄호는 세지 않는다). 짝이 없으면 len(text)."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c in _QUOTES:
            i = _string_end(text, i)
            continue
        if text.startswith("//", i):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl
            continue
        depth += (c == "[") - (c == "]")
        i += 1
        if depth == 0:
            return i
    return len(text)


def _tokens(text: str) -> list[str | float]:
    """배열 글 안의 값: 글(따옴표, 뒤에 ':' 가 오는 열쇠는 뺌)과 숫자. 이름(c0·null·new Date)은 건너뛴다."""
    out: list[str | float] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in _QUOTES:
            end = _string_end(text, i)
            if not text[end:].lstrip().startswith(":"):
                out.append(text[i + 1:end - 1].replace("\\'", "'").replace('\\"', '"'))
            i = end
        elif c.isalpha() or c in "_$":
            while i < len(text) and (text[i].isalnum() or text[i] in "_$."):
                i += 1
        elif (m := _NUMBER.match(text, i)) and (c != "-" or m.end() > i + 1):
            out.append(float(m.group()))
            i = m.end()
        else:
            i += 1
    return out


def _data_tokens(script: str) -> list[str | float]:
    found: list[str | float] = []
    for m in _ARRAY.finditer(script):
        start = m.end() - 1
        found += _tokens(script[start + 1:_array_end(script, start) - 1])
    return found


def _add(problems: list[str], text: str) -> None:
    if text not in problems:
        problems.append(text)


def _check_data(tokens: list[str | float], table: VisualTable, problems: list[str]) -> None:
    cells = [v for row in table.rows for v in row if v is not None]
    texts = {cell_text(v) for v in cells} | set(table.columns) | {table.title}
    numbers = {float(v) for v in cells if isinstance(v, int | float) and not isinstance(v, bool)}
    for t in tokens:
        if isinstance(t, float):
            if t not in numbers:
                _add(problems, f"데이터에 표에 없는 값: {t:g}")
        elif _DATE.fullmatch(t):
            if t not in texts:
                _add(problems, f"데이터에 표에 없는 날짜: {t}")
        elif t.strip() and not _COLOR.fullmatch(t.strip()) and t not in texts:
            _add(problems, f"데이터에 표에 없는 값: {t}")


def _check_bounds(scripts: list[str], dates: set[str], problems: list[str]) -> set[str]:
    """축 범위의 날짜를 본다. 돌려주는 것은 축 범위에 쓰인 날짜(통과 여부와 상관없이 — (d) 에서 다시 세지 않게)."""
    lo = min(map(date.fromisoformat, dates)) - AXIS_SLACK if dates else None
    hi = max(map(date.fromisoformat, dates)) + AXIS_SLACK if dates else None
    seen: set[str] = set()
    for script in scripts:
        for m in _BOUND.finditer(script):
            for d in _DATE.findall(m.group(1)):
                seen.add(d)
                if lo is None or hi is None or not lo <= date.fromisoformat(d) <= hi:
                    _add(problems, f"축 범위가 표 날짜에서 한 달 넘게 벗어남: {d}")
    return seen


def verify(page: str, table: VisualTable) -> Verdict:
    """받은 HTML 을 우리 표와 맞춰 본다(모듈 설명의 (a)~(d)). problems 가 비면 통과."""
    problems: list[str] = []
    cells = [cell_text(v) for row in table.rows for v in row if v is not None]
    missing = [c for c in cells if c not in page and html_lib.escape(c) not in page]
    for c in missing:
        _add(problems, f"HTML 에 없는 표 값: {c}")
    scripts = [s for s in _INLINE.findall(page) if "new Chart(" in s]
    tokens = [t for s in scripts for t in _data_tokens(s)]
    if not tokens:
        _add(problems, "차트 설정을 읽지 못함")
    _check_data(tokens, table, problems)
    dates = {c for c in cells if _DATE.fullmatch(c)}
    bounds = _check_bounds(scripts, dates, problems)
    reported = {p.rsplit(": ", 1)[-1] for p in problems}
    for d in dict.fromkeys(_DATE.findall(page)):
        if d not in dates and d not in bounds and d not in reported:
            _add(problems, f"표에 없는 날짜: {d}")
    external = list(dict.fromkeys(u for u in _EXTERNAL.findall(page) if re.match(r"(?:https?:)?//", u)))
    return Verdict(not problems, len(cells) - len(missing), len(cells), problems, external)


# ── 만들기 ───────────────────────────────────────────────────────────


@dataclass
class _Outcome:
    atlas: Atlas | None = None
    verdict: Verdict | None = None
    attempts: int = 0
    note: str = ""


async def _draw(session: Session, query: str, table: VisualTable,
                transport: httpx.AsyncBaseTransport | None) -> _Outcome:
    """ATTEMPTS 번까지 그려 대조한다. 통과하면 note 가 빈다."""
    out = _Outcome()
    for _ in range(ATTEMPTS):
        try:
            out.attempts += 1
            out.atlas = await liner_visualize(session, query, transport=transport)
        except VisualNotReady:
            return _Outcome(attempts=0, note=FAILED_MESSAGES["not_ready"])
        except VisualFailed as e:
            out.atlas, out.verdict, out.note = None, None, f"Liner 그림 실패({e.code}) → 기본 그림"
            if e.code in _NO_RETRY:
                break
            continue
        out.verdict = verify(out.atlas.html, table)
        out.note = "" if out.verdict.ok else FAILED_MESSAGES["verify"]
        if out.verdict.ok:
            break
    return out


def input_key(table: VisualTable, query: str) -> str:
    raw = json.dumps([table.kind, table.version, table.data_date and table.data_date.isoformat(), query],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def make(session: Session, *, kind: str, schedule_id: int, version: int | None, today: date, created_by: str,
               transport: httpx.AsyncBaseTransport | None = None) -> Visual:
    """표를 만들고 그림 한 장을 저장해 돌려준다(flush 만). 표를 만들 수 없으면 store.visuals 의 예외 그대로."""
    table = visuals.build(session, kind, schedule_id, version, today=today)
    query = query_text(table)
    key = input_key(table, query)
    if (found := visuals.find_verified(session, schedule_id, key)) is not None:
        return found
    session.commit()  # Liner 를 기다리는 동안 쓰기 잠금을 쥐지 않는다
    o = await _draw(session, query, table, transport)
    ok = o.verdict is not None and o.verdict.ok
    total = o.verdict.total if o.verdict else sum(v is not None for row in table.rows for v in row)
    row = visuals.save(
        session, schedule_id=schedule_id, table=table, key=key, html=o.atlas.html if o.atlas else "",
        theme=o.atlas.theme if o.atlas else "", description=o.atlas.description if o.atlas else "",
        resource_id=o.atlas.resource_id if o.atlas else "", verified=ok, passed=o.verdict.passed if o.verdict else 0,
        total=total, problems=o.verdict.problems if o.verdict else [], external=o.verdict.external if o.verdict else [],
        attempts=o.attempts, fallback=not ok, note=o.note, latency_ms=o.atlas.latency_ms if o.atlas else None,
        created_by=created_by,
    )
    if not ok:
        logger.warning("%s: 일정 %s · %s · 시도 %s · 그림 %s", o.note, schedule_id, kind, o.attempts, row.id)
    return row
