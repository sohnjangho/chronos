"""근무일 달력. 날짜 셈은 전부 여기서 한다."""

from datetime import date, timedelta

from app.core.model import BlockedPeriod, CalendarSpec

_DAY = timedelta(days=1)
# 근무일을 찾아 훑는 한도(약 20년). 넘으면 근무일이 없는 달력으로 본다.
_MAX_SCAN = 7320


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


class WorkCalendar:
    def __init__(self, spec: CalendarSpec) -> None:
        self._days_per_week = spec.days_per_week
        self._holidays = frozenset(spec.holidays)
        self._blocked = spec.blocked

    def is_workday(self, d: date, tags: tuple[str, ...] = ()) -> bool:
        """5일 근무는 토·일, 6일 근무는 일요일만 쉰다. 금지 기간은 같은 꼬리표에만 적용."""
        if d.weekday() >= self._days_per_week:
            return False
        if d in self._holidays:
            return False
        return not any(p.tag in tags and _in_period(d, p) for p in self._blocked)

    def _seek(self, d: date, step: timedelta, tags: tuple[str, ...]) -> date:
        for _ in range(_MAX_SCAN):
            if self.is_workday(d, tags):
                return d
            d += step
        raise NoWorkdayError(tags)

    def next_workday(self, d: date, tags: tuple[str, ...] = ()) -> date:
        """d 가 일하는 날이면 d, 아니면 그 뒤 첫 근무일."""
        return self._seek(d, _DAY, tags)

    def prev_workday(self, d: date, tags: tuple[str, ...] = ()) -> date:
        """d 가 일하는 날이면 d, 아니면 그 앞 마지막 근무일."""
        return self._seek(d, -_DAY, tags)

    def shift(self, d: date, n: int, tags: tuple[str, ...] = ()) -> date:
        """d 에서 근무일 n 개만큼 뒤(n>0)·앞(n<0)으로 옮긴 날. n=0 이면 d."""
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
        count = 0
        d = a
        while d < b:
            d += _DAY
            count += self.is_workday(d, tags)
        return count


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
