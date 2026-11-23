"""뒤 확인(Task 68)의 날짜 읽기 — review.py 에서 옮긴 것. said 와 도구 결과의 글에서 날짜 말을 읽어, 그 말이 가리킬 수 있는
날(_When)로 바꾼다. 상한과 도구 결과 훑기는 review.py 에 있다(_tool_dates · _unsupported_dates)."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial


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
