"""근무일 달력. 날짜 셈은 전부 여기서 한다."""

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from datetime import date, timedelta
from functools import lru_cache

from app.core.model import BlockedPeriod, CalendarSpec

_DAY = timedelta(days=1)
# 근무일을 찾아 훑는 한도(약 20년). 넘으면 근무일이 없는 달력으로 본다.
_MAX_SCAN = 7320
_MIN = date.min.toordinal()
_END = date.max.toordinal() + 1  # 서수 범위 [_MIN, _END)
# 미리 센 근무일을 붙들어 두는 범위의 상한(약 100년). 더 넓은 물음은 그때만 센다.
_KEEP = 36600


def _in_period(d: date, period: BlockedPeriod) -> bool:
    md = (d.month, d.day)
    if period.start_md <= period.end_md:
        return period.start_md <= md <= period.end_md
    return md >= period.start_md or md <= period.end_md  # 해를 넘기는 기간


class NoWorkdayError(ValueError):
    """훑는 한도 안에 근무일이 없다."""

    def __init__(self, tags: tuple[str, ...]) -> None:
        super().__init__(f"no workday within {_MAX_SCAN} days for tags {tags!r}")
        self.tags = tags


class _Workdays:
    """한 꼬리표 조합의 근무일 서수를 차례로 모아 둔 목록. 물은 범위만큼 앞뒤로 넓힌다.

    넓힐 때는 새 (lo, hi, 목록) 묶음을 한 번에 바꿔 끼우므로, 읽는 쪽은 늘 앞뒤가 맞는 묶음을 본다.
    """

    def __init__(self, is_workday: Callable[[int], bool]) -> None:
        self._is_workday = is_workday
        self._win: tuple[int, int, list[int]] = (0, 0, [])  # [lo, hi) 안의 근무일

    def cover(self, a: int, b: int) -> list[int]:
        """[a, b) 를 덮는 근무일 목록. 넓힐 때는 적어도 지금 크기만큼 넓힌다."""
        a, b = max(a, _MIN), min(b, _END)
        lo, hi, days = self._win
        if lo <= a and b <= hi:
            return days
        size = max(hi - lo, 366)
        new_lo = max(min(a, lo - size), _MIN) if a < lo else lo
        new_hi = min(max(b, hi + size), _END) if b > hi else hi
        if lo == hi or new_hi - new_lo > _KEEP:  # 처음이거나 너무 멀다: 물은 범위만 센다
            days = self._scan(a, b)
            if b - a <= _KEEP:
                self._win = (a, b, days)
            return days
        days = self._scan(new_lo, lo) + days + self._scan(hi, new_hi)
        self._win = (new_lo, new_hi, days)
        return days

    def _scan(self, a: int, b: int) -> list[int]:
        return [o for o in range(a, b) if self._is_workday(o)]

    def after(self, o: int, n: int) -> int | None:
        """o 뒤(o 빼고) n 번째 근무일. o 에서 _MAX_SCAN 일 안에 없으면 None."""
        span = min(2 * n + 14, _MAX_SCAN)
        while True:
            days = self.cover(o + 1, o + 1 + span)
            i = bisect_right(days, o) + n - 1
            if i < len(days):
                return days[i] if days[i] - o <= _MAX_SCAN else None
            if span >= _MAX_SCAN or o + 1 + span >= _END:
                return None
            span = min(span * 4, _MAX_SCAN)

    def before(self, o: int, n: int) -> int | None:
        """o 앞(o 빼고) n 번째 근무일. o 에서 _MAX_SCAN 일 안에 없으면 None."""
        span = min(2 * n + 14, _MAX_SCAN)
        while True:
            days = self.cover(o - span, o)
            i = bisect_left(days, o) - n
            if i >= 0:
                return days[i] if o - days[i] <= _MAX_SCAN else None
            if span >= _MAX_SCAN or o - span <= _MIN:
                return None
            span = min(span * 4, _MAX_SCAN)


@lru_cache(maxsize=64)
def _shared(
    days_per_week: int, holidays: frozenset[date], blocked: tuple[BlockedPeriod, ...]
) -> dict[tuple[str, ...], _Workdays]:
    """같은 달력이면 인스턴스가 달라도(계산마다 새로 만든다) 미리 센 근무일을 같이 쓴다. 꼬리표 → 근무일 목록."""
    return {}


class WorkCalendar:
    def __init__(self, spec: CalendarSpec) -> None:
        self._days_per_week = spec.days_per_week
        self._holidays = frozenset(spec.holidays)
        self._blocked = spec.blocked
        self._by_tags = _shared(self._days_per_week, self._holidays, self._blocked)

    def is_workday(self, d: date, tags: tuple[str, ...] = ()) -> bool:
        """5일 근무는 토·일, 6일 근무는 일요일만 쉰다. 금지 기간은 같은 꼬리표에만 적용."""
        if d.weekday() >= self._days_per_week:
            return False
        if d in self._holidays:
            return False
        return not any(p.tag in tags and _in_period(d, p) for p in self._blocked)

    def _workdays(self, tags: tuple[str, ...]) -> _Workdays:
        found = self._by_tags.get(tags)
        if found is None:
            found = self._by_tags[tags] = _Workdays(lambda o: self.is_workday(date.fromordinal(o), tags))
        return found

    def _seek(self, d: date, step: timedelta, tags: tuple[str, ...]) -> date:
        """d 부터 step 쪽으로 _MAX_SCAN 일(d 포함) 안의 첫 근무일."""
        if self.is_workday(d, tags):
            return d
        o = d.toordinal()
        days = self._workdays(tags)
        found = days.after(o - 1, 1) if step.days > 0 else days.before(o + 1, 1)
        if found is not None:
            return date.fromordinal(found)
        if not _MIN <= o + step.days * _MAX_SCAN < _END:  # 하루씩 훑던 때처럼 날짜 끝을 넘으면
            raise OverflowError("date value out of range")
        raise NoWorkdayError(tags)

    def next_workday(self, d: date, tags: tuple[str, ...] = ()) -> date:
        """d 가 일하는 날이면 d, 아니면 그 뒤 첫 근무일."""
        return self._seek(d, _DAY, tags)

    def prev_workday(self, d: date, tags: tuple[str, ...] = ()) -> date:
        """d 가 일하는 날이면 d, 아니면 그 앞 마지막 근무일."""
        return self._seek(d, -_DAY, tags)

    def shift(self, d: date, n: int, tags: tuple[str, ...] = ()) -> date:
        """d 에서 근무일 n 개만큼 뒤(n>0)·앞(n<0)으로 옮긴 날. n=0 이면 d."""
        if n == 0:
            return d
        days = self._workdays(tags)
        o = d.toordinal()
        found = days.after(o, n) if n > 0 else days.before(o, -n)
        if found is not None:
            return date.fromordinal(found)
        # 드문 경우(근무일이 없거나 _MAX_SCAN 일 넘게 떨어진 달력, 날짜 끝): 한 개씩 옮겨 같은 오류를 낸다
        step = _DAY if n > 0 else -_DAY
        for _ in range(abs(n)):
            d = self._seek(d + step, step, tags)
        return d

    def add_workdays(self, start: date, n: int, tags: tuple[str, ...] = ()) -> date:
        """start 에 시작하는 n일짜리 작업의 종료일(포함). n=0 이면 start.

        n<0 이면 거꾸로: start 에 끝나는 |n|일짜리 작업의 시작일.
        """
        if n > 0:
            return self.shift(self.next_workday(start, tags), n - 1, tags)
        if n < 0:
            return self.shift(self.prev_workday(start, tags), n + 1, tags)
        return start

    def workdays_between(self, a: date, b: date, tags: tuple[str, ...] = ()) -> int:
        """a 다음 날부터 b 까지 일하는 날 수 (b<a 면 음수)."""
        if b < a:
            return -self.workdays_between(b, a, tags)
        lo, hi = a.toordinal(), b.toordinal()
        days = self._workdays(tags).cover(lo + 1, hi + 1)
        return bisect_right(days, hi) - bisect_right(days, lo)


# 2027년 대한민국 공휴일(대체 공휴일 포함) — 자료 상수
KOREA_HOLIDAYS_2027: tuple[date, ...] = (
    date(2027, 1, 1),  # 신정
    date(2027, 2, 6),  # 설날 연휴
    date(2027, 2, 7),  # 설날
    date(2027, 2, 8),  # 설날 연휴
    date(2027, 2, 9),  # 설날 대체 공휴일
    date(2027, 3, 1),  # 삼일절
    date(2027, 5, 1),  # 노동절
    date(2027, 5, 3),  # 노동절 대체 공휴일
    date(2027, 5, 5),  # 어린이날
    date(2027, 5, 13),  # 부처님오신날
    date(2027, 6, 6),  # 현충일
    date(2027, 7, 17),  # 제헌절
    date(2027, 7, 19),  # 제헌절 대체 공휴일
    date(2027, 8, 15),  # 광복절
    date(2027, 8, 16),  # 광복절 대체 공휴일
    date(2027, 9, 14),  # 추석 연휴
    date(2027, 9, 15),  # 추석
    date(2027, 9, 16),  # 추석 연휴
    date(2027, 10, 3),  # 개천절
    date(2027, 10, 4),  # 개천절 대체 공휴일
    date(2027, 10, 9),  # 한글날
    date(2027, 10, 11),  # 한글날 대체 공휴일
    date(2027, 12, 25),  # 성탄절
    date(2027, 12, 27),  # 성탄절 대체 공휴일
)
