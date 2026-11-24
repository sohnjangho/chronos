"""보고서용 그림의 숫자 대조(순수 함수). Liner Visualization 이 준 HTML 을 우리 표(app.store.visuals.VisualTable)와 맞춘다.

DB·네트워크를 쓰지 않는다. 규칙(컨트롤러 판정 11-20 · 리뷰 fix 1·2):
(a) 열마다(table.roles) — charted 열의 값은 차트 자료(데이터 배열의 값)에 **개수까지** 있다(글은 똑같이, 숫자는 수로).
    shown 열의 값(막대 그림의 날짜·상태 같은 글)은 보이는 표 칸(<td>·<th>)에 그대로 있다. 둘을 합해 passed/total.
(b) 차트 데이터 배열(`data: [...]`·`labels: [...]`·`const x = [...]`)에 표에 없는 값·날짜가 없다.
(c) 축 범위(min·max·suggestedMin·suggestedMax)의 날짜는 표 날짜 범위에서 한 달(31일) 안.
(d) HTML 어디에도 표에 없는 날짜가 없다.
(e) 보이는 글 — 본문 글 전체(script·style·head 빼고: 표·제목·<p>·figcaption·svg <text>·sr-only 모두), aria-label,
    차트 설정의 title·label 글과 tick·tooltip callback 안의 글자(글자가 든 것만) — 의 숫자는 표의 숫자이거나 표의 글·열
    이름 안의 것이다. 숫자는 부호(-, −)와 천 단위 쉼표까지 읽는다(-2, 1,234).
(f) 외부 script·link 는 ALLOWED_PREFIXES 로 시작하는 주소만(화면 iframe 의 CSP 와 같은 목록).
차트 설정(`new Chart(`)을 읽지 못하면 실패다.
"""

import html as html_lib
import re
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, timedelta

from app.store.visuals import VisualTable

AXIS_SLACK = timedelta(days=31)
# 실측 외부 주소의 앞부분(화면 frontend/src/shared/visual/VisualFrame.tsx 의 CSP 와 같은 목록).
ALLOWED_PREFIXES = (
    "https://cdn.jsdelivr.net/npm/@liner-fe/design-token@",
    "https://cdn.jsdelivr.net/npm/pretendard@",
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/",
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    passed: int  # 열 규칙대로 찾은 표 값 수(charted 는 차트 자료에 개수까지, shown 은 보이는 표 칸에)
    total: int  # 표 값 수(빈 칸 빼고)
    problems: list[str]
    external: list[str]  # 외부 script·link 주소(받은 차례)


def cell_text(v: object) -> str:
    return "" if v is None else str(v)


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


def _array_end(text: str, i: int, pair: str = "[]") -> int:
    """text[i] == pair[0] 의 짝 pair[1] 다음 위치(글·주석 안의 괄호는 세지 않는다). 짝이 없으면 len(text)."""
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
        depth += (c == pair[0]) - (c == pair[1])
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


_CELL = re.compile(r"<(t[dh])\b[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_UNSHOWN = re.compile(r"<(script|style|head|title|template)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ARIA = re.compile(r"\baria-label\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
# 부호(-, −)와 천 단위 쉼표까지: -2, −2, 1,234, 12.5. 글자·숫자·점·쉼표·붙임표 바로 뒤의 숫자는 그 일부라 따로 세지 않는다.
_SHOWN_NUMBER = re.compile(r"(?<![A-Za-z\d.,\-−])[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_CHART_TEXT = re.compile(r"\b(?:text|label|title)\s*:\s*(['\"`])((?:\\.|(?!\1).)*)\1")
_CALLBACK = re.compile(r"\bcallbacks?\s*:")
_TEMPLATE_PART = re.compile(r"\$\{[^}]*\}")
_LETTER = re.compile(r"[^\W\d_]")


def _literals(code: str) -> list[str]:
    """코드 조각 안의 글 상수(따옴표·역따옴표). 역따옴표의 ${…} 는 뺀다."""
    out, i = [], 0
    while i < len(code):
        if code[i] in _QUOTES:
            end = _string_end(code, i)
            out.append(_TEMPLATE_PART.sub(" ", code[i + 1:end - 1]))
            i = end
        else:
            i += 1
    return out


def _chart_texts(script: str) -> list[str]:
    """차트 설정에서 화면에 나오는 글: title·label·text 글, callback(s) 안의 글자가 든 글 상수(padStart 의 '0' 같은 것은 뺀다)."""
    found = [m.group(2) for m in _CHART_TEXT.finditer(script)]
    for m in _CALLBACK.finditer(script):
        start = script.find("{", m.end())
        if start < 0:
            continue
        found += [t for t in _literals(script[start:_array_end(script, start, "{}")]) if _LETTER.search(t)]
    return found


def _shown_texts(page: str, scripts: list[str]) -> list[str]:
    body = html_lib.unescape(_TAG.sub(" ", _UNSHOWN.sub(" ", page)))
    arias = [m.group(1) or m.group(2) or "" for m in _ARIA.finditer(page)]
    return [body, *(html_lib.unescape(a) for a in arias), *(t for s in scripts for t in _chart_texts(s))]


def _value(text: str) -> float:
    return float(text.replace("−", "-").replace(",", ""))


_KO_YMD = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_KO_YM = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월")
_KO_MD = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_KO_Y = re.compile(r"(?<!\d)(\d{4})\s*년")
_KO_M = re.compile(r"(?<!\d)(\d{1,2})\s*월")
_SEP_YMD = re.compile(r"(?<!\d)(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?!\d)")
_SEP_YM = re.compile(r"(?<!\d)(\d{4})[./-](\d{1,2})(?!\d)")
_DOT_MD = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{2})(?![\d.])")
_SLASH_MD = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")
_YEAR_4 = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _known_dates(table: VisualTable) -> tuple[set[date], bool]:
    row_dates: set[date] = set()
    for row in table.rows:
        for v in row:
            if isinstance(v, str):
                for m in _DATE.findall(v):
                    with suppress(ValueError):
                        row_dates.add(date.fromisoformat(m))
    dates = set(row_dates)
    if table.data_date is not None:
        dates.add(table.data_date)
    return dates, bool(row_dates)


def _strip_known_dates(text: str, dates: set[date], has_row_dates: bool) -> str:
    """표 날짜(및 data_date)에서 파생된 로캘·축약 날짜 표현만 제거한다(임의 숫자는 남긴다)."""
    rest = _DATE.sub(" ", text)
    if not dates:
        return rest
    ymd = {(d.year, d.month, d.day) for d in dates}
    ym = {(d.year, d.month) for d in dates}
    md = {(d.month, d.day) for d in dates}
    years = {d.year for d in dates}
    months = {d.month for d in dates}

    rest = _KO_YMD.sub(lambda m: " " if (int(m[1]), int(m[2]), int(m[3])) in ymd else m.group(0), rest)
    rest = _KO_YM.sub(lambda m: " " if (int(m[1]), int(m[2])) in ym else m.group(0), rest)
    rest = _KO_MD.sub(lambda m: " " if (int(m[1]), int(m[2])) in md else m.group(0), rest)
    rest = _KO_Y.sub(lambda m: " " if int(m[1]) in years else m.group(0), rest)
    rest = _SEP_YMD.sub(lambda m: " " if (int(m[1]), int(m[2]), int(m[3])) in ymd else m.group(0), rest)
    rest = _SEP_YM.sub(lambda m: " " if (int(m[1]), int(m[2])) in ym else m.group(0), rest)
    rest = _DOT_MD.sub(lambda m: " " if (int(m[1]), int(m[2])) in md else m.group(0), rest)
    rest = _SLASH_MD.sub(lambda m: " " if (int(m[1]), int(m[2])) in md else m.group(0), rest)
    if has_row_dates:
        rest = _KO_M.sub(lambda m: " " if int(m[1]) in months else m.group(0), rest)
        rest = _YEAR_4.sub(lambda m: " " if int(m[1]) in years else m.group(0), rest)
    return rest


def _check_visible(page: str, scripts: list[str], table: VisualTable, problems: list[str]) -> None:
    """(e) 보이는 글의 숫자: 표의 날짜 표기와 표의 글·열 이름·제목을 지운 뒤 남은 숫자는 표의 숫자여야 한다."""
    cells = [v for row in table.rows for v in row if v is not None]
    known = sorted({v for v in cells if isinstance(v, str)} | set(table.columns) | {table.title}, key=len, reverse=True)
    numbers = {float(v) for v in cells if isinstance(v, int | float) and not isinstance(v, bool)}
    dates, has_row_dates = _known_dates(table)
    for text in _shown_texts(page, scripts):
        rest = _strip_known_dates(text, dates, has_row_dates)
        for k in known:
            rest = rest.replace(k, " ") if k else rest
        for n in _SHOWN_NUMBER.findall(rest):
            if _value(n) not in numbers:
                _add(problems, f"보이는 글에 표에 없는 숫자: {n}")


def _key(v: object) -> tuple[str, object]:
    """세는 열쇠: 숫자(숫자 꼴 글 포함)는 수로, 글은 글 그대로."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return "n", float(v)
    text = cell_text(v)
    return ("n", float(text)) if _NUMBER.fullmatch(text) else ("s", text)


def _missing(table: VisualTable, tokens: list[str | float], page: str) -> tuple[list[str], list[str]]:
    """(a) (차트 자료에 없는 charted 값, 보이는 표 칸에 없는 shown 값). 둘 다 개수까지 센다."""
    pool = Counter(_key(t) for t in tokens)
    shown = Counter(html_lib.unescape(_TAG.sub(" ", m.group(2))).strip() for m in _CELL.finditer(page))
    charted_missing, shown_missing = [], []
    for row in table.rows:
        for i, v in enumerate(row):
            if v is None:
                continue
            bag, key, miss = (pool, _key(v), charted_missing) if table.role(i) == "charted" else \
                (shown, cell_text(v), shown_missing)
            if bag[key] > 0:
                bag[key] -= 1
            else:
                miss.append(cell_text(v))
    return charted_missing, shown_missing


def _allowed(url: str) -> bool:
    return (f"https:{url}" if url.startswith("//") else url).startswith(ALLOWED_PREFIXES)


def verify(page: str, table: VisualTable) -> Verdict:
    """받은 HTML 을 우리 표와 맞춰 본다(모듈 설명의 (a)~(f)). problems 가 비면 통과."""
    problems: list[str] = []
    values = [v for row in table.rows for v in row if v is not None]
    scripts = [s for s in _INLINE.findall(page) if "new Chart(" in s]
    tokens = [t for s in scripts for t in _data_tokens(s)]
    if not tokens:
        _add(problems, "차트 설정을 읽지 못함")
    charted_missing, shown_missing = _missing(table, tokens, page)
    for c in charted_missing:
        _add(problems, f"차트 자료에 없는 표 값: {c}")
    for c in shown_missing:
        _add(problems, f"보이는 표에 없는 값: {c}")
    _check_data(tokens, table, problems)
    cells = [cell_text(v) for v in values]
    dates = {c for c in cells if _DATE.fullmatch(c)}
    bounds = _check_bounds(scripts, dates, problems)
    reported = {p.rsplit(": ", 1)[-1] for p in problems}
    for d in dict.fromkeys(_DATE.findall(page)):
        if d not in dates and d not in bounds and d not in reported:
            _add(problems, f"표에 없는 날짜: {d}")
    _check_visible(page, scripts, table, problems)
    external = list(dict.fromkeys(u for u in _EXTERNAL.findall(page) if re.match(r"(?:https?:)?//", u)))
    for u in external:
        if not _allowed(u):
            _add(problems, f"허용하지 않은 외부 주소: {u}")
    passed = len(values) - len(charted_missing) - len(shown_missing)
    return Verdict(not problems, passed, len(values), problems, external)
