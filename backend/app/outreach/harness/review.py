"""연락 하네스의 뒤 확인(Task 68) — 모델 없이 코드만. 통화가 끝난 뒤(받아쓰기의 에이전트 말)와 자동 답이 나가기 전(보내려는
글)에, 우리 쪽 말을 **상대가 실제로 한 말**과 **도구가 실제로 돌려준 것**에 견준다. 문자와 통화가 같은 함수·같은 깃발·같은
사건 꼴을 쓰고, 다른 것은 부른 쪽이 `clean` 으로 하는 일뿐이다(문자는 보내지 않고 초안에 둔다, 통화는 보고만 남는다).

지키는 것은 하나: **틀린 「깨끗함」이 없어야 한다.** 그래서 헷갈리면 깃발이고, 검사마다 「다 보지 못했으면 지나가지 않는다」.
- 상대 말이 한 줄도 없음 · 근거 말이 없는 답 · 상한을 넘은 말 · 읽을 수 없는 날짜 꼴 · 다 읽지 못한 작업 이름 → 깃발.
- 예외가 나면 판정이 없다 — 부른 쪽은 「깨끗하지 않음」으로 다뤄야 한다.

깃발(types.REVIEW_FLAGS 만 쓴다)과 규칙:
1. unsupported_answer — 그 줄 answers_json 의 답마다, 그 줄에 달린 contact_reports(kind review 밖)의 근거 말마다
   quote_found = heard(근거 말, 상대 말). 답은 근거 말이 비었거나 못 들었으면 깃발, 보고는 근거 말이 **있는데** 못 들었을 때만
   (take_message·handoff_to_human 의 메모는 근거 칸이 없는 도구가 남긴다). 상대 말이 없으면 늘 깃발.
2. unsupported_date — said 의 날짜 말마다 도구 결과의 날짜 가운데 그것이 가리킬 수 있는 날이 있어야 한다(_READERS 의 글).
   글자가 아니라 날로 견준다. 상대가 말한 날짜를 되받아 말한 것도 근거가 아니다(날짜는 도구가 준 것만 — rules_text 와 같다).
3. out_of_scope_said — 범위의 일정(과 그 줄의 일정)의 작업 이름(4자 이상) 가운데 이 상대에게 허용되지 않은 것을 말함.
   허용은 도구와 같은 뜻이다(_allowed): facts "all" 이면 그 일정 전부, "trade" 면 공종 말·연결된 작업·마일스톤, "none"
   (현장을 고르기 전 포함)이면 없음.
4. money_said — 숫자+원·만원·천원·억·만, 한글로 읽은 수+원, 「계약금」·「단가」, 통화 기호(_MONEY).
5. disclosed_to_unknown — 아무것도 들을 수 없는 등급(unknown·withheld·do_not_contact …)에게 **어느 일정이든** 그 이름이나
   작업 이름(4자 이상)을 말함. 등급은 부른 쪽이 주는 caller_class(Caller.caller_class)와 범위의 등급 가운데 엄한 쪽.

남기는 것(check 가 곧바로 commit): quote_found, 깃발마다 사건 하나(문자 blocked · 통화 noted, detail 은 고정 글과 건수뿐),
깃발이 있으면 contact_reports(kind review, 「내용 확인 필요」) 한 줄 — 같은 줄에 이미 있으면 더 만들지 않는다. 사건과 보고에는
말한 글·상대 글·번호·날짜·이름을 싣지 않는다.

tool_results 는 부른 쪽이 주는 그대로다(Toolbox.results). dict 인 항목만 읽고, 그 안 어느 열쇠든 글 값(목록·dict 속 포함,
MAX_TOOL_DEPTH 겹까지)과 date·datetime 값에서 **날이 든 날짜**(YYYY-MM-DD · M월 D일 · M/D)를 찾는다. 모르는 꼴은 근거가
되지 않을 뿐 오류가 아니다.
"""

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from functools import partial
from itertools import pairwise
from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.model import Schedule
from app.outreach import redact
from app.outreach.harness import events
from app.outreach.harness.types import (
    GRANT_CEILING,
    REVIEW_FLAGS,
    CallerClass,
    Ref,
    Scope,
)
from app.store import outreach, schedules
from app.store.tables import FieldItem, ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

# 상한 — 넘는 것은 견주지 않고, 견주지 못한 것은 「깨끗함」이 아니다.
MAX_SAID_LINES = 2000  # said 줄 수. 넘으면 날짜·이름·금액 깃발
MAX_PEER_LINES = 2000  # 상대 말 줄 수. 넘는 줄은 근거가 아니다
MAX_LINE_CHARS = 2000  # 한 줄 글자 수. said 는 넘으면 깃발, 상대 말은 그 뒤가 근거가 아니다
MAX_TEXT_CHARS = 200_000  # said 전체·상대 말 전체 글자 수(같은 규칙)
MAX_QUOTE_CHARS = 300  # 근거 말. 넘으면 못 들은 것
MAX_ANSWERS = MAX_REPORTS = 200  # 답·보고. 넘는 것은 못 들은 것
MAX_TOOL_VALUES, MAX_TOOL_DEPTH = 5000, 6  # 도구 결과에서 읽는 값의 수·겹. 넘는 것은 근거가 아니다
MAX_SCHEDULES, MAX_NAMES = 200, 20_000  # 이름을 읽는 일정·작업 수. 넘으면 이름 깃발
MAX_LINKED_ROWS = 5000  # 연결된 작업을 찾는 메시지·통화 줄(새것부터). 넘으면 옛 연결은 허용이 아니다
MAX_SPANS = 1000  # 이름이 나온 자리를 세는 수
MIN_NAME = 4
HEARD_RATIO = 0.85
TAIL_WORDS = 4  # 맞은 말 뒤로 뒤집는 말을 찾는 낱말 수

REVIEW_KIND, REVIEW_TEXT = "review", "내용 확인 필요"
UNCHECKED, NO_PEER = "상한을 넘어 다 견주지 못함", "상대 말이 없음"
_SAID = {  # 깃발(돌려주는 차례) → 사건에 남기는 고정 글
    "unsupported_answer": "답의 근거 말이 상대 말에 없음",
    "unsupported_date": "도구 결과에 없는 날짜를 말함",
    "out_of_scope_said": "범위 밖 작업 이름을 말함",
    "money_said": "금액·계약을 말함",
    "disclosed_to_unknown": "모르는 상대에게 일정·작업 이름을 말함",
}
if frozenset(_SAID) != REVIEW_FLAGS:
    raise ValueError("뒤 확인의 깃발이 types.REVIEW_FLAGS 와 다릅니다")


@dataclass(frozen=True)
class Verdict:
    """뒤 확인의 판정. flags 는 REVIEW_FLAGS 의 이름(_SAID 차례), clean 은 깃발이 하나도 없음."""

    clean: bool
    flags: list[str]


def _norm(text: str) -> str:
    """견줄 글: 같은 글자는 같은 꼴로(NFKC — 전각 숫자 포함·대소문자), 보이지 않는 글자 없이."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _flat(text: str) -> str:
    """글자와 숫자만(빈칸·문장부호 없이)."""
    return "".join(ch for ch in _norm(text) if ch.isalnum())


def _listed(value: object) -> list:
    """줄 목록. 글 하나는 한 줄로, 목록이 아닌 것은 빈 목록으로."""
    if isinstance(value, str):
        return [value]
    return list(value) if isinstance(value, list | tuple) else []


# ── heard: 상대가 그 말을 했는가 ─────────────────────────────────────

_WORD = re.compile(r"[^\W_]+")
_JOSA = ("에서는", "에게는", "으로는", "에서", "에게", "한테", "까지", "부터", "으로", "에는", "에도", "이나", "이랑",
         "은", "는", "이", "가", "을", "를", "에", "의", "도", "로", "와", "과", "만", "요")
_JOSA_RE = f"(?:{'|'.join(_JOSA)})?"
_STOP = re.compile(r"[.?!\n。]")
_FINAL = ("다", "요", "죠", "까", "음", "임", "함", "됨")  # 문장을 맺는 끝
_TURN = re.compile(r"않|없|못|불가|어렵|어려|힘들|힘듭|힘든|힘드|곤란|모르|모릅|모를|몰라|아니|아닙|아닌|아뇨|말고|취소|미정|여부"
                   r"|글쎄|봐야|냐|^안$|^안(?:되|돼|됩|될|됨|됐|하|합|해|했|할|가|갑|갔|와|옵|왔|오)"
                   r"|(?:면|지|지는|지도|지만)$")  # 뒤집는 말 · 모른다는 말 · 조건과 바람(「가능하면」「가능할지」「가능하지만」)
_SOFT = frozenset("은는이을를에의도로요다니습합함입임네죠해하됩돼되음")  # 비슷한 줄에서 달라도 되는 글자(조사·끝)


@dataclass(frozen=True)
class _Line:
    """상대 말 한 줄: 낱말, 낱말 뒤의 사이 글, 낱말을 붙인 글, 낱말이 시작하는 자리 → 차례, 낱말이 끝나는 자리."""

    words: tuple[str, ...]
    gaps: tuple[str, ...]
    flat: str
    starts: dict[int, int]
    ends: tuple[int, ...]
    asks: bool


def _line(raw: str) -> _Line | None:
    text = _norm(redact.hide_phones(raw))
    found = list(_WORD.finditer(text))
    if not found:
        return None
    words = tuple(m.group() for m in found)
    gaps = tuple(text[m.end(): after.start()] for m, after in pairwise(found)) + (text[found[-1].end():],)
    starts, ends, at = {}, [], 0
    for index, word in enumerate(words):
        starts[at] = index
        at += len(word)
        ends.append(at)
    return _Line(words, gaps, "".join(words), starts, tuple(ends), "?" in text or words[-1].endswith("까"))


def _lines(lines: object) -> list[_Line]:
    """상대 말(상한 안의 것만 — 글이 아닌 줄·빈 줄은 근거가 아니다)."""
    out, left = [], MAX_TEXT_CHARS
    for raw in _listed(lines)[:MAX_PEER_LINES]:
        if not isinstance(raw, str):
            continue
        raw = raw[:MAX_LINE_CHARS]
        left -= len(raw)
        if left < 0:
            break
        if (line := _line(raw)) is not None:
            out.append(line)
    return out


def _stem(word: str) -> str:
    """끝의 조사 하나를 뗀 말. 남는 말이 한 글자거나 숫자로 끝나면(「6만」) 떼지 않는다."""
    for josa in _JOSA:
        stem = word[: -len(josa)]
        if word.endswith(josa) and len(stem) >= 2 and not stem[-1].isdigit():
            return stem
    return word


def _turned(line: _Line, start: int, end: int) -> bool:
    """맞은 자리의 말이 뒤집히거나 물음인가: 바로 앞 낱말이 「안」·「못」이거나, 그 문장의 남은 말(TAIL_WORDS 낱말까지)에
    뒤집는 말(_TURN — 않·없·못·말고·미정, 조건 「…면」「…지」「…지만」)이 있거나, 물음으로 끝난다."""
    first = line.starts[start]
    if first and line.words[first - 1] in ("안", "못") and not _STOP.search(line.gaps[first - 1]):
        return True
    at = bisect_right(line.ends, end - 1)
    piece, tail = line.flat[end: line.ends[at]], []
    for _ in range(TAIL_WORDS + 1):
        if piece:
            tail.append(piece)
        if at == len(line.words) - 1 or _STOP.search(line.gaps[at]) or line.words[at].endswith(_FINAL):
            break
        at += 1
        piece = line.words[at]
    turned = any(_TURN.search(piece) for piece in tail if piece not in _JOSA)  # 조사만 남은 조각(「까지」)은 뒤집는 말이 아니다
    return turned or "?" in line.gaps[at] or line.words[at].endswith("까")


def _close(flat: str, line: _Line) -> bool:
    """줄 전체가 근거 말과 거의 같은가(difflib 비율). 다른 곳은 조사·끝 글자뿐이어야 한다 — 숫자·요일·「안」·「못」이 다르면
    비슷해도 다른 말이다. 물음인 줄은 근거가 아니다."""
    other = line.flat
    if line.asks or 2 * min(len(flat), len(other)) < HEARD_RATIO * (len(flat) + len(other)):
        return False
    matcher = SequenceMatcher(None, flat, other, autojunk=False)
    if min(matcher.real_quick_ratio(), matcher.quick_ratio()) < HEARD_RATIO or matcher.ratio() < HEARD_RATIO:
        return False
    return all(tag == "equal" or set(flat[a:b] + other[c:d]) <= _SOFT for tag, a, b, c, d in matcher.get_opcodes())


def _heard(quote: object, lines: list[_Line]) -> bool:
    if not isinstance(quote, str) or len(quote) > MAX_QUOTE_CHARS:
        return False
    words = _WORD.findall(_norm(redact.hide_phones(quote)))
    if not words:
        return False
    stems = [_stem(word) for word in words]
    # 낱말 사이에는 조사 하나가 더 있어도 된다 — 숫자 바로 뒤는 빼고(「6 개」가 「6만 개」에 맞지 않게)
    pattern = re.compile("".join(re.escape(stem) + ("" if stem[-1].isdigit() else _JOSA_RE) for stem in stems[:-1])
                         + re.escape(stems[-1]))
    flat = "".join(words)
    for line in lines:
        at = line.flat.find(stems[0])
        while at != -1:  # 줄의 낱말이 시작하는 자리에서만(「가능」이 「불가능」 안에서 맞지 않게)
            if at in line.starts and (hit := pattern.match(line.flat, at)) and not _turned(line, at, hit.end()):
                return True
            at = line.flat.find(stems[0], at + 1)
        if _close(flat, line):
            return True
    return False


def heard(quote: str, lines: list[str]) -> bool:
    """상대가 그 말을 했는가. lines 는 **상대** 말·글만 넘긴다(우리 쪽 말은 근거가 아니다).

    빈칸·문장부호·전각·낱말 끝의 조사 차이를 지우고, 근거 말이 한 줄의 낱말이 시작하는 자리부터 이어서 들어 있으면 참 —
    다만 그 문장이 뒤집히거나(않습니다·안·못·말고 …) 물음이면 거짓. 그렇게 들어 있지 않아도 줄 전체가 difflib 비율
    HEARD_RATIO 이상이고 다른 곳이 조사·끝 글자뿐이면 참. 빈 근거 말·상한 밖(MAX_PEER_LINES·MAX_LINE_CHARS·
    MAX_QUOTE_CHARS)은 거짓."""
    return _heard(quote, _lines(lines))


# ── 날짜 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _When:
    """said 의 날짜 말 하나가 가리킬 수 있는 날: 준 칸이 모두 맞는 날(해·달·날·요일·기간). never 는 어느 날도 아님."""

    year: int | None = None
    month: int | None = None
    day: int | None = None
    weekdays: frozenset[int] | None = None
    first: date | None = None
    last: date | None = None
    never: bool = False
    span: tuple[int, int] | None = None  # 날(日)의 범위 — 「11월 초」는 1~10일

    def fits(self, day: date) -> bool:
        return (not self.never and self.year in (None, day.year) and self.month in (None, day.month)
                and self.day in (None, day.day) and (self.weekdays is None or day.weekday() in self.weekdays)
                and (self.first is None or self.first <= day <= self.last)
                and (self.span is None or self.span[0] <= day.day <= self.span[1]))


_Found = list[_When] | None  # None 이면 날짜 말이 아니다(그 자리를 다음 규칙에 넘긴다)
_D = r"\d{1,2}"
_KN = r"(?:[이삼]?십[일이삼사오육칠팔구]?|[일이삼사오육칠팔구])"  # 한글로 읽은 1~39
_KDIGIT = {ch: n for n, ch in enumerate("일이삼사오육칠팔구", 1)}
_KMONTH = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "유": 6, "육": 6, "칠": 7, "팔": 8, "구": 9, "시": 10, "십": 10,
           "십일": 11, "십이": 12}
_GAP = r"(?:\s*(?:[~\-–,·/]|및|에서|부터|과|와)\s*)"
_DAYS = rf"(?P<days>(?:(?:{_D}|{_KN}){_GAP}){{0,6}}(?:{_D}|{_KN}))\s*일(?!요일)"  # 「28일」「28~30일」「이십팔일」
_NDAYS = rf"(?P<ndays>{_D}(?:{_GAP}{_D}){{0,6}})(?![\d.])(?!\s*(?:층|동|호|명|개|대|톤|평|%|차|회|건|곳))"  # 「11월 28」(일 없이)
_PART = r"\s*(?P<part>초순|중순|하순|말경|말(?!일|씀)|초)"
_SPANS = {"초": (1, 10), "초순": (1, 10), "중순": (11, 20), "하순": (21, 31), "말": (21, 31), "말경": (21, 31)}
_TAIL = r"(?P<more>(?:\s*[~\-–,]\s*\d{1,2}(?![\d/.]))*)"  # 「11/28~30」의 뒤 날
_BARE = r"(?<![0-9a-z/.\-])"  # 숫자 날짜의 앞: 다른 숫자·영문·기호에 붙어 있지 않다
_LONE = r"(?<![가-힣])"  # 다른 낱말 속에서도 나오는 말의 앞(「입금일」의 금일, 「회사월급」의 사월)
_THEN = r"(?=$|[^가-힣]|에|엔|은|는|도|까|부|쯤|내|안|로|의|이|가|중|초|자|날|경|께|인|입)"
_WEEKDAYS = {ch: n for n, ch in enumerate("월화수목금토일")}
_YEAR_WORDS = {"작년": -1, "올해": 0, "금년": 0, "내년": 1, "명년": 1}
_MONTH_WORDS = {"지난달": -1, "저번달": -1, "전월": -1, "이번달": 0, "이달": 0, "금월": 0, "당월": 0, "다음달": 1, "내달": 1,
                "익월": 1, "다다음달": 2}
_WEEK_WORDS = {"지난주": -1, "저번주": -1, "이번주": 0, "금주": 0, "다음주": 1, "내주": 1, "차주": 1, "담주": 1, "다다음주": 2}
_DAY_WORDS = {"그저께": -2, "엊그제": -2, "그제": -2, "어제": -1, "오늘": 0, "금일": 0, "내일": 1, "명일": 1, "익일": 1,
              "낼": 1, "모레": 2, "내일모레": 2, "낼모레": 2, "글피": 3}
_NATIVE = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "여드레": 8, "아흐레": 9,
           "열흘": 10, "보름": 15}
_COUNT = {"한": 1, "일": 1, "두": 2, "이": 2, "세": 3, "석": 3, "삼": 3, "네": 4, "넉": 4, "사": 4}
_WAY = r"\s*(?:쯤|정도|가량)?\s*(?P<way>뒤|후|전|있다가)"
_UNIT = (r"%|[a-z°]|배|톤|미터|센티|밀리|킬로|평|개|명|층|동|호|회|차|번|시간|분|초|도|만|천|억|원|퍼센트|프로|점|루베|헤베|인치"
         r"|리터|그램|대|장|건|년|주")


def _knum(word: str) -> int:
    tens, ones = word.partition("십")[::2] if "십" in word else ("", word)
    return (_KDIGIT.get(tens, 1) * 10 if "십" in word else 0) + _KDIGIT.get(ones, 0)


def _days(text: str | None) -> list[int]:
    return [int(part) if part.isdigit() else _knum(part) for part in re.findall(rf"{_D}|{_KN}", text or "")]


def _shift_month(today: date, months: int) -> tuple[int, int]:
    index = today.year * 12 + today.month - 1 + months
    return index // 12, index % 12 + 1


def _week(today: date, weeks: int) -> date:
    """그 주의 월요일."""
    return today - timedelta(days=today.weekday()) + timedelta(weeks=weeks)


def _on(day: date, last: date | None = None) -> list[_When]:
    return [_When(first=day, last=last or day)]


def _numeric(m: re.Match, today: date) -> _Found:
    """2026-11-28 · 2026.11.28 · 2026/11/28 — 없는 날(13월)이어도 날짜 말이다(어느 날에도 맞지 않는다)."""
    return [_When(int(m["y"]), int(m["m"]), int(m["d"]))]


def _numeric_short(m: re.Match, today: date) -> _Found:
    """26.11.28 · 26/11/28 — 달·날이 될 수 있는 수일 때만."""
    month, day = int(m["m"]), int(m["d"])
    return [_When(2000 + int(m["y"]), month, day)] if 1 <= month <= 12 and 1 <= day <= 31 else None


def _korean(m: re.Match, today: date) -> _Found:
    """[해] M월 [D일 …] — 해는 숫자(두 자리는 20xx)나 올해·내년·작년, 달·날은 숫자나 한글로 읽은 수(십일월 이십팔일).
    날이 없으면 그 달 어느 날이든(「11월 말」도 달로만 본다)."""
    year = None
    if m["y"]:
        year = int(m["y"]) + (2000 if len(m["y"]) == 2 else 0)
    elif m["yw"]:
        year = today.year + _YEAR_WORDS[m["yw"]]
    month = int(m["m"]) if m["m"] else _KMONTH[m["km"]]
    return [_When(year, month, day) for day in _days(m["days"] or m["ndays"])] or [_When(year, month, span=_SPANS.get(m["part"]))]


def _relative_month(m: re.Match, today: date) -> _Found:
    """이번 달·다음 달·지난달 [D일] — 날이 없으면 그 달 어느 날이든."""
    year, month = _shift_month(today, _MONTH_WORDS["".join(m["w"].split())])
    return [_When(year, month, day) for day in _days(m["days"] or m["ndays"])] or [_When(year, month, span=_SPANS.get(m["part"]))]


def _year_only(m: re.Match, today: date) -> _Found:
    """2027년 · 올해 · 내년 — 그 해 어느 날이든."""
    return [_When(int(m["y"]) if m["y"] else today.year + _YEAR_WORDS[m["yw"]])]


def _month_day(m: re.Match, today: date, swap: bool = False) -> _Found:
    """11/28 · 11.28 · 11. 28. · 11-28 (뒤 날 「~30」 포함) — 달·날이 될 수 있는 수일 때만(11.28 은 뒤에 단위가 붙지 않았을
    때만, 빈칸을 둔 꼴은 끝에 점이 있을 때만 — 「3. 5명」은 아니다). swap 이면(/·- 꼴) 날/달 차례(30/11)도 읽는다 — 24/7 은 아니다."""
    month, day = int(m["m"]), int(m["d"])
    if swap and 13 <= month <= 31 and 1 <= day <= 12 and (month, day) != (24, 7):
        month, day = day, month
    days = [day, *_days(m.groupdict().get("more"))]
    return [_When(month=month, day=one) for one in days] if 1 <= month <= 12 and 1 <= day <= 31 else None


def _days_off(m: re.Match, today: date) -> _Found:
    """N일 뒤·후·전 · 삼일 뒤 · 사흘 뒤 — 오늘에서 센 그날."""
    count = int(m["n"]) if m["n"] else _knum(m["k"]) if m["k"] else _NATIVE[m["w"]]
    return _on(today + timedelta(days=-count if m["way"] == "전" else count))


def _weeks_off(m: re.Match, today: date) -> _Found:
    """N주 뒤·후·전 — 오늘에서 센 날이 든 주(월~일)."""
    count = int(m["n"]) if m["n"].isdigit() else _COUNT[m["n"]]
    monday = _week(today + timedelta(weeks=-count if m["way"] == "전" else count), 0)
    return _on(monday, monday + timedelta(days=6))


def _months_off(m: re.Match, today: date) -> _Found:
    """N달·N개월 뒤·후·전 — 그 달 어느 날이든."""
    count = int(m["n"]) if m["n"].isdigit() else _COUNT[m["n"]]
    return [_When(*_shift_month(today, -count if m["way"] == "전" else count))]


def _relative_week(m: re.Match, today: date) -> _Found:
    """이번 주·다음 주·지난주 [X요일|말] — 요일이 있으면 그날, 「주말」이면 그 주 토·일, 없으면 그 주(월~일)."""
    monday = _week(today, _WEEK_WORDS["".join(m["w"].split())])
    if m["wd"]:
        return _on(monday + timedelta(days=_WEEKDAYS[m["wd"]]))
    return _on(monday + timedelta(days=5 if m["we"] else 0), monday + timedelta(days=6))


def _day_word(m: re.Match, today: date) -> _Found:
    """오늘·내일·모레·글피·어제 … — 오늘에서 센 그날."""
    return _on(today + timedelta(days=_DAY_WORDS["".join(m.group().split())]))


def _day_only(m: re.Match, today: date) -> _Found:
    """28일 · 28~30일 · 이십팔일 — 달은 도구 결과가 정한다(그 날짜가 든 날이면 된다). 32 이상(「45일」)은 날짜 말이 아니다.
    「3일 걸립니다」처럼 기간일 수도 있지만 가르지 않는다 — 날로 읽는다."""
    days = [day for day in _days(m["days"] if "days" in m.groupdict() else m["k"]) if 1 <= day <= 31]
    return [_When(day=day) for day in days] or None


def _weekday(m: re.Match, today: date) -> _Found:
    """토요일 · 토욜 · (토) · 주말 — 그 요일인 날이면 된다."""
    name = m["a"] or m["b"] or m["c"]
    return [_When(weekdays=frozenset({_WEEKDAYS[name]}) if name else frozenset({5, 6}))]


def _vague(m: re.Match, today: date) -> _Found:
    """월말·말일·월초·연말·주초·추석·연휴 … — 날짜 말이지만 날을 정할 수 없다. 받쳐 줄 수 없다."""
    return [_When(never=True)]


# 위에서부터 차례로 읽고, 읽은 자리는 지운다(뒤 규칙이 두 번 세지 않게). 앞의 다섯은 도구 결과에서 날짜를 찾을 때도 쓴다.
_READERS: tuple[tuple[re.Pattern, Callable[[re.Match, date], _Found]], ...] = (
    (re.compile(rf"{_BARE}(?P<y>(?:19|20)\d{{2}})\s*[-./]\s*(?P<m>{_D})\s*[-./]\s*(?P<d>{_D})(?!\d)"), _numeric),
    (re.compile(rf"{_BARE}(?P<y>\d{{2}})[./\-](?P<m>{_D})[./\-](?P<d>{_D})(?![\d./\-])"), _numeric_short),
    (re.compile(rf"(?:(?:(?<!\d)(?P<y>(?:19|20)\d{{2}}|\d{{2}})\s*년|(?P<yw>{'|'.join(_YEAR_WORDS)}))\s*)?"
                rf"(?:(?<![\d.])(?P<m>{_D})\s*|{_LONE}(?P<km>십일|십이|일|이|삼|사|오|유|육|칠|팔|구|시|십))월(?!요일)"
                rf"(?:\s*{_DAYS}|\s*{_NDAYS}|{_PART})?"), _korean),
    (re.compile(rf"{_BARE}(?P<m>{_D})\s*/\s*(?P<d>{_D}){_TAIL}(?![\d/])"), partial(_month_day, swap=True)),
    (re.compile(rf"{_BARE}(?P<m>{_D})\.(?P<d>{_D}){_TAIL}(?!\d)(?!\.\d)(?!\.?\s*(?:{_UNIT}))"), _month_day),
    (re.compile(rf"{_BARE}(?P<m>{_D})\.\s+(?P<d>{_D})\.(?!\d)"), _month_day),
    # 여기부터는 said 만 — 도구 결과에서는 읽지 않는다(_DATED)
    (re.compile(rf"{_BARE}(?P<m>{_D})[\-–](?P<d>{_D}){_TAIL}(?![\d\-–])(?!\s*(?:{_UNIT}|일))"), partial(_month_day, swap=True)),
    (re.compile(r"(?<!\d)(?P<y>20\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?!\d)"), _numeric),  # 20261128
    (re.compile(rf"(?P<w>다다음\s*달|다음\s*달|이번\s*달|지난\s*달|저번\s*달|{_LONE}(?:내달|익월|이달|금월|당월|전월))"
                rf"(?:\s*{_DAYS}|\s*{_NDAYS}|{_PART})?"), _relative_month),
    (re.compile(rf"(?<!\d)(?P<y>(?:19|20)\d{{2}})\s*년|(?P<yw>{'|'.join(_YEAR_WORDS)})"), _year_only),
    (re.compile(rf"(?:(?<![\d.])(?P<n>\d{{1,3}})\s*일|{_LONE}(?P<k>{_KN})일|(?P<w>{'|'.join(_NATIVE)})){_WAY}"), _days_off),
    (re.compile(rf"(?P<n>(?<![\d.]){_D}|{_LONE}(?:{'|'.join(_COUNT)}))\s*주(?:일)?{_WAY}"), _weeks_off),
    (re.compile(rf"(?P<n>(?<![\d.]){_D}|{_LONE}(?:{'|'.join(_COUNT)}))\s*(?:달|개월){_WAY}"), _months_off),
    (re.compile(rf"(?P<w>다다음\s*주|다음\s*주|이번\s*주|지난\s*주|저번\s*주|{_LONE}(?:내주|차주|금주|담주))"
                rf"(?:\s*(?P<wd>[월화수목금토일])요일|\s*(?P<we>말)(?!씀|하|고)|{_THEN})"), _relative_week),
    (re.compile(rf"그저께|엊그제|내일\s*모레|{_LONE}(?:낼\s*모레|낼|그제|금일|명일|익일|모레|글피)|어제|오늘|(?<!안)내일"), _day_word),
    (re.compile(rf"(?<![\d.,])(?P<days>(?:{_D}{_GAP}){{0,6}}{_D})\s*일(?!요일)"), _day_only),
    (re.compile(rf"{_LONE}(?P<k>[이삼]?십[일이삼사오육칠팔구]?)\s?일{_THEN}"), _day_only),
    (re.compile(r"(?P<a>[월화수목금토일])요일|(?P<b>[월화수목금토일])욜|\((?P<c>[월화수목금토일])\)|주말"), _weekday),
    (re.compile(rf"월말|월초|월중|말일|연말|연초|초순|중순|하순|{_LONE}(?:주초|주중)|초하루|그믐"
                r"|설날|설\s*연휴|추석|성탄절|크리스마스|새해|명절|연휴|상반기|하반기|당일|전날|이튿날|(?:다음|그)\s*날(?!씨)"
                r"|(?<![a-z])d\s*-\s*(?:\d{1,3}(?!\d)|day)|디데이|휴일|어린이날|한글날|현충일|광복절|개천절|삼일절|제헌절"
                r"|(?:첫|둘|셋|넷|다섯|마지막)\s*째?\s*주(?!문|소|민|요)"), _vague),
)
_DATED = 6  # 날이 든 날짜를 읽는 규칙의 수(도구 결과에는 이것만)


def _mentions(text: str, today: date, readers=_READERS) -> list[_When]:
    """글(_norm 을 거친 것)의 날짜 말 전부."""
    out: list[_When] = []
    for pattern, read in readers:
        kept, at = [], 0
        for hit in pattern.finditer(text):
            found = read(hit, today)
            if found is None:
                continue
            out += found
            kept += [text[at: hit.start()], "|" * (hit.end() - hit.start())]
            at = hit.end()
        text = "".join([*kept, text[at:]])
    return out


def _nearest(when: _When, today: date) -> date | None:
    """날이 든 날짜 말의 그날. 해가 없으면 오늘에서 가장 가까운 해. 없는 날이면 None."""
    days = []
    for year in ((when.year,) if when.year is not None else (today.year - 1, today.year, today.year + 1)):
        try:
            days.append(date(year, when.month, when.day))
        except ValueError:
            continue
    return min(days, key=lambda day: abs((day - today).days), default=None)


def _tool_dates(tool_results: object, today: date) -> set[date]:
    """도구 결과의 날짜(모듈 머리 글). 상한(MAX_TOOL_VALUES 값·MAX_TOOL_DEPTH 겹) 밖은 읽지 않는다."""
    out: set[date] = set()
    left = MAX_TOOL_VALUES

    def walk(node: Any, depth: int) -> None:
        nonlocal left
        if left <= 0 or depth > MAX_TOOL_DEPTH:
            return
        left -= 1
        if isinstance(node, datetime):
            out.add(node.astimezone(outreach.KST).date() if node.tzinfo else node.date())
        elif isinstance(node, date):
            out.add(node)
        elif isinstance(node, str):
            for when in _mentions(_norm(node[:MAX_LINE_CHARS]), today, _READERS[:_DATED]):
                if when.day is not None and (day := _nearest(when, today)) is not None:
                    out.add(day)
        elif isinstance(node, dict | list | tuple):
            for item in (node.values() if isinstance(node, dict) else node):
                if left <= 0:
                    break
                walk(item, depth + 1)

    for entry in _listed(tool_results):
        if isinstance(entry, dict):
            walk(entry, 0)
    return out


def _unsupported_dates(text: str, tool_results: object, today: date) -> int:
    whens = _mentions(text, today)
    if not whens:
        return 0
    days = _tool_dates(tool_results, today)
    return sum(1 for when in whens if not any(when.fits(day) for day in days))


# ── 금액 ─────────────────────────────────────────────────────────────

_NUM = r"\d[\d,]*(?:\.\d+)?"
_COUNTED = (r"명|개|평|톤|장|대|건|회|번|매|부|권|년|시간|km|m|제곱|세제곱|리터|킬로|그램|포|본|루베|헤베|가구|세대|마리|보|화소"
            r"|볼트|와트|배|층|동|호|가지|군데|곳|차례")
_KMONEY = "일이삼사오육칠팔구십백천만억조"
_MONEY = re.compile(
    rf"{_NUM}\s*(?:[십백천만억조]\s*)*원"  # 5000원 · 3만 원 · 5천원 · 2억 원
    rf"|{_NUM}\s*(?:[십백천]\s*)*(?:억|만(?!\s*(?:{_COUNTED})))"  # 2억 · 300만(「3만 명」은 아니다)
    rf"|{_LONE}(?:수|몇)?\s*(?P<kor>[{_KMONEY}]+(?:\s+[{_KMONEY}]+)*)\s*원"  # 삼백만 원 · 오천원 · 만 원
    rf"|{_LONE}(?:[{_KMONEY[:12]}]+억|[{_KMONEY[:9]}][{_KMONEY[:12]}]*[십백천]만)(?!\s*(?:{_COUNTED}))"  # 일억 · 삼천만(「이만」「천만에요」는 아니다)
    rf"|계약금|단가"
    rf"|[₩$€¥]\s*\d|\d\s*(?:달러|유로|usd|krw|won)"
)


def _money(text: str) -> int:
    """금액 말의 수. 한글로 읽은 수는 자리 말(십·백·천·만·억·조)이 있어야 한다 — 「사원」·「구원」·「조원」은 아니다."""
    count = 0
    for hit in _MONEY.finditer(text):
        kor = "".join((hit["kor"] or "").split())
        count += not hit["kor"] or (any(ch in "십백천만억조" for ch in kor) and (len(kor) >= 2 or kor in "십백천만억"))
    return count


# ── 작업 이름 ────────────────────────────────────────────────────────

_TRADE_SPLIT = re.compile(r"[\s,，/·・ㆍ‧|;()]+")
_MILESTONES = ("start_ms", "finish_ms")
_MIN_TRADE_WORD = 2


def _plain(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def _long(name: str) -> bool:
    """견줄 이름인가 — NFC·빈칸을 뺀 글자가 MIN_NAME 자 이상(「C-1동」은 4자). 견주기는 글자·숫자만(_flat)으로 한다."""
    return len(_plain(name)) >= MIN_NAME


def _linked(session: Session, schedule_id: int, contact_ids: Collection[int]) -> set[str]:
    """그 일정의 그 연락처들과 주고받은 메시지·통화, 거기 달린 현장 항목에 연결된 작업 id."""
    people = list(session.scalars(select(Contact.id).where(Contact.schedule_id == schedule_id, Contact.id.in_(contact_ids))))
    if not people:
        return set()
    found: set[str] = set()
    items: set[int] = set()
    for model in (OutreachMessage, OutreachCall):
        rows = session.execute(select(model.activity_id, model.field_item_id).where(
            model.schedule_id == schedule_id, model.contact_id.in_(people)).order_by(model.id.desc()).limit(MAX_LINKED_ROWS))
        for activity_id, field_item_id in rows:
            found.update([activity_id] if activity_id else [])
            items.update([field_item_id] if field_item_id is not None else [])
    if items:
        found.update(session.scalars(select(FieldItem.activity_id).where(
            FieldItem.schedule_id == schedule_id, FieldItem.id.in_(items))))
    return found


def _allowed_ids(session: Session, schedule_id: int, schedule: Schedule, company_ids: Collection[int],
                 contact_ids: Collection[int]) -> set[str]:
    """그 일정에서 그 협력사·그 사람에게 말해도 되는 작업 id — **도구의 facts.allowed_for 와 같은 규칙을 옮겨 적은 것**
    (그 모듈은 Task 67 이 쓰는 중이라 불러오지 않았다. 시험 test_allowed_names_mean_the_same_as_in_the_tools 가 둘을 견준다):
    그 사람의 메시지·통화·현장 항목에 연결된 작업 + 이름이나 WBS 이름(윗 WBS 포함)에 협력사 공종 말이 든 작업 + 마일스톤.
    그 일정의 협력사가 없으면 빈 집합."""
    trades = list(session.scalars(select(ContactCompany.trade).where(
        ContactCompany.schedule_id == schedule_id, ContactCompany.id.in_(company_ids))))
    if not trades:
        return set()
    words = [word for word in {_plain(part) for trade in trades for part in _TRADE_SPLIT.split(trade)}
             if len(word) >= _MIN_TRADE_WORD]
    nodes = {node.code: node for node in schedule.wbs}
    out = _linked(session, schedule_id, contact_ids) & {activity.id for activity in schedule.activities}
    for activity in schedule.activities:
        names, code = [activity.name], activity.wbs
        while code in nodes and len(names) <= len(nodes) + 1:
            names.append(nodes[code].name)
            code = nodes[code].parent
        text = _plain(" ".join(names))
        if activity.kind in _MILESTONES or any(word in text for word in words):
            out.add(activity.id)
    return out


def _allowed(session: Session, schedule_id: int, schedule: Schedule, scope: Scope) -> set[str] | None:
    """그 일정에서 이 범위에 허용된 작업 id(None 은 전부). 범위 밖 일정·사실 수준 none(현장을 고르기 전 포함)은 없음."""
    if schedule_id not in scope.schedule_ids or scope.facts == "none":
        return set()
    if scope.facts == "all":
        return None
    return _allowed_ids(session, schedule_id, schedule, scope.company_ids, scope.contact_ids)


class _Book:
    """이름을 읽는 한 번의 뒤 확인: 일정은 한 번만 읽고, 읽은 작업 수가 MAX_NAMES 를 넘으면 full 이 거짓이 된다."""

    def __init__(self, session: Session) -> None:
        self.session, self.read, self.left, self.full = session, {}, MAX_NAMES, True

    def schedule(self, schedule_id: int) -> Schedule | None:
        if schedule_id not in self.read:
            try:
                self.read[schedule_id] = schedules.load(self.session, schedule_id)[0]
            except schedules.NotFound:
                self.read[schedule_id] = None
        return self.read[schedule_id]

    def names(self, schedule: Schedule):
        """(작업 id, 견줄 이름) — MIN_NAME 자 이상만. 상한을 넘으면 거기서 멈춘다."""
        for activity in schedule.activities:
            self.left -= 1
            if self.left < 0:
                self.full = False
                return
            if _long(activity.name) and (name := _flat(activity.name)):
                yield activity.id, name


def _scope_names(session: Session, scope: Scope, row_schedule: int | None) -> tuple[set[str], set[str], bool]:
    """(허용된 이름, 범위 밖 이름, 다 읽었는가) — 범위의 일정과 그 줄의 일정에서. 허용된 작업과 이름이 같으면 허용이다."""
    ids = list(dict.fromkeys([*scope.schedule_ids, *([] if row_schedule is None else [row_schedule])]))
    book, allowed, barred = _Book(session), set(), set()
    for schedule_id in ids[:MAX_SCHEDULES]:
        if (schedule := book.schedule(schedule_id)) is None:
            continue
        ok = _allowed(session, schedule_id, schedule, scope)
        for activity_id, name in book.names(schedule):
            (allowed if ok is None or activity_id in ok else barred).add(name)
    return allowed, barred - allowed, book.full and len(ids) <= MAX_SCHEDULES


def _every_name(session: Session) -> tuple[set[str], bool]:
    """(모든 일정의 이름과 작업 이름, 다 읽었는가)."""
    rows = session.execute(select(ScheduleRecord.id, ScheduleRecord.name).order_by(ScheduleRecord.id)
                           .limit(MAX_SCHEDULES + 1)).all()
    book, names = _Book(session), set()
    for schedule_id, title in rows[:MAX_SCHEDULES]:
        if _long(title or "") and (flat := _flat(title)):
            names.add(flat)
        if (schedule := book.schedule(schedule_id)) is not None:
            names.update(name for _, name in book.names(schedule))
    return names, book.full and len(rows) <= MAX_SCHEDULES


def _spans(text: str, names: Collection[str]) -> list[tuple[int, int]]:
    """그 이름들이 나온 자리(MAX_SPANS 개까지)."""
    out: list[tuple[int, int]] = []
    for name in names:
        at = text.find(name)
        while at != -1 and len(out) < MAX_SPANS:
            out.append((at, at + len(name)))
            at = text.find(name, at + 1)
    return out


def _named(text: str, barred: Collection[str], allowed: Collection[str] = ()) -> int:
    """범위 밖 이름이 나온 수. 허용된 이름 **안**에 든 것(「가람동 전기 배선 철근 관통부」 속의 「전기 배선」)은 세지 않고,
    허용된 이름을 품은 더 긴 범위 밖 이름은 센다. 서로 품은 자리는 긴 것 하나로 센다."""
    hits = _spans(text, barred)
    if hits and allowed:
        free = _spans(text, allowed)
        hits = [hit for hit in hits if not any(a <= hit[0] and hit[1] <= b for a, b in free)]
    unique = set(hits)
    return sum(1 for hit in unique if not any(o != hit and o[0] <= hit[0] and hit[1] <= o[1] for o in unique))


# ── check ────────────────────────────────────────────────────────────


def _said_text(said: object) -> tuple[str, bool]:
    """(견줄 글 — 줄을 줄바꿈으로 이어 _norm, 다 담았는가). 글이 아닌 줄·상한을 넘는 줄 수·글자 수가 있으면 거짓."""
    lines = _listed(said)
    kept = [line[:MAX_LINE_CHARS] for line in lines[:MAX_SAID_LINES] if isinstance(line, str)]
    whole = (isinstance(said, str | list | tuple) and len(kept) == len(lines)
             and all(len(line) <= MAX_LINE_CHARS for line in lines) and sum(map(len, kept)) <= MAX_TEXT_CHARS)
    return _norm("\n".join(kept)[:MAX_TEXT_CHARS]), whole


def _mark_answers(row: OutreachMessage | OutreachCall, peers: list[_Line]) -> int:
    """answers_json 의 답마다 quote_found 를 적고, 근거가 없는 답의 수를 준다(꼴이 틀린 답·상한 밖의 답 포함)."""
    stored = row.answers_json
    if stored is None:
        return 0
    if not isinstance(stored, list):
        return 1
    marked, bad = [], 0
    for index, entry in enumerate(stored):
        found = index < MAX_ANSWERS and isinstance(entry, dict) and _heard(entry.get("quote"), peers)
        bad += not found
        marked.append({**entry, "quote_found": found} if isinstance(entry, dict) else entry)
    if marked != stored:
        row.answers_json = marked  # 새 목록(같은 목록을 고치면 저장되지 않는다)
    return bad


def _mark_reports(session: Session, ref: Ref, peers: list[_Line]) -> int:
    """그 줄에 달린 보고 가운데 근거 말이 있는 것마다 quote_found 를 적고, 못 들은 수를 준다(상한 밖 포함)."""
    link = ContactReport.call_id if ref.kind == "call" else ContactReport.message_id
    rows = session.scalars(select(ContactReport).where(link == ref.row_id, ContactReport.kind != REVIEW_KIND)
                           .order_by(ContactReport.id).limit(MAX_REPORTS + 1)).all()
    bad = int(len(rows) > MAX_REPORTS)
    for report in rows[:MAX_REPORTS]:
        if (report.quote or "").strip():
            report.quote_found = _heard(report.quote, peers)
            bad += not report.quote_found
    return bad


def _strict(scope: Scope, caller_class: str | None) -> bool:
    """아무것도 들을 수 없는 등급인가 — 준 등급과 범위의 등급 가운데 엄한 쪽."""
    return "none" in (GRANT_CEILING[scope.caller_class], GRANT_CEILING.get(caller_class or scope.caller_class))


def check(session: Session, ref: Ref, *, said: list[str], peer_lines: list[str], tool_results: list[dict], scope: Scope,
          caller_class: CallerClass | None = None, now: datetime | None = None) -> Verdict:
    """뒤 확인 한 번(모듈 머리 글). said 는 통화면 받아쓰기의 에이전트 말, 문자면 보내려는 글. peer_lines 는 상대 말·글만,
    tool_results 는 그 통화·응대의 도구 결과(Toolbox.results), scope 는 지금의 범위(현장을 굳혔으면 굳은 것 — box.scope),
    caller_class 는 Caller.caller_class(주지 않으면 범위의 등급 — 닫힌 범위의 등급은 unknown 이라 더 엄해질 뿐이다),
    now 는 「오늘」(서울 날짜)을 정하는 시각(시험용 — 없으면 지금).

    quote_found·사건·보고 한 줄을 적고 **commit 한다.** 줄이 없으면 NotFound, 범위·등급이 틀리면 TypeError·ValueError."""
    if not isinstance(scope, Scope) or not isinstance(ref, Ref):
        raise TypeError("check 는 Ref 와 Scope 를 받습니다")
    if caller_class is not None and caller_class not in get_args(CallerClass):
        raise ValueError("등급표에 없는 등급입니다")
    row = session.get(OutreachCall if ref.kind == "call" else OutreachMessage, ref.row_id)
    if row is None:
        raise outreach.NotFound(ref.row_id)
    today = as_utc(now or datetime.now(UTC)).astimezone(outreach.KST).date()
    notes: dict[str, str] = {}

    peers = _lines(peer_lines)
    unheard = _mark_answers(row, peers) + _mark_reports(session, ref, peers)
    if not peers or unheard:
        notes["unsupported_answer"] = f"{unheard}건" if peers else NO_PEER

    text, whole = _said_text(said)
    flat = "".join(ch for ch in text if ch.isalnum())
    counts = {"unsupported_date": _unsupported_dates(text, tool_results, today), "money_said": _money(text)}
    read = {}
    if flat or not whole:
        allowed, barred, read["out_of_scope_said"] = _scope_names(session, scope, row.schedule_id)
        counts["out_of_scope_said"] = _named(flat, barred, allowed)
        if _strict(scope, caller_class):
            names, read["disclosed_to_unknown"] = _every_name(session)
            counts["disclosed_to_unknown"] = _named(flat, names)
    for flag, count in counts.items():
        if not whole or not read.get(flag, True):
            notes[flag] = UNCHECKED
        elif count:
            notes[flag] = f"{count}건"

    flags = [flag for flag in _SAID if flag in notes]
    session.flush()
    for flag in flags:
        events.record(session, ref, flag, "blocked" if ref.kind == "message" else "noted", f"{_SAID[flag]} · {notes[flag]}",
                      now=now)
    link = {"call_id" if ref.kind == "call" else "message_id": ref.row_id}
    if flags and session.scalar(select(ContactReport.id).filter_by(kind=REVIEW_KIND, **link).limit(1)) is None:
        outreach.add_report(session, schedule_id=row.schedule_id, medium="call" if ref.kind == "call" else "sms",
                            contact_id=row.contact_id, kind=REVIEW_KIND, text=redact.hide_phones(REVIEW_TEXT), **link)
    session.commit()
    return Verdict(not flags, flags)
