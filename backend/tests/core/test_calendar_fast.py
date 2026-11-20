"""빠른 근무일 계산이 예전(하루씩 세던) 계산과 같은 답을 내는지 무작위로 맞대 본다."""

import random
import time
from calendar import monthrange
from datetime import date, timedelta

from app.core.calendar import KOREA_HOLIDAYS_2027, NoWorkdayError, WorkCalendar
from app.core.model import BlockedPeriod, CalendarSpec

# ---- 기준: 바꾸기 전 app/core/calendar.py 의 WorkCalendar 를 그대로 옮긴 것 ----

_DAY = timedelta(days=1)
_MAX_SCAN = 7320


def _in_period(d: date, period: BlockedPeriod) -> bool:
    md = (d.month, d.day)
    if period.start_md <= period.end_md:
        return period.start_md <= md <= period.end_md
    return md >= period.start_md or md <= period.end_md  # 해를 넘기는 기간


class OracleCalendar:
    def __init__(self, spec: CalendarSpec) -> None:
        self._days_per_week = spec.days_per_week
        self._holidays = frozenset(spec.holidays)
        self._blocked = spec.blocked

    def is_workday(self, d: date, tags: tuple[str, ...] = ()) -> bool:
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
        return self._seek(d, _DAY, tags)

    def prev_workday(self, d: date, tags: tuple[str, ...] = ()) -> date:
        return self._seek(d, -_DAY, tags)

    def shift(self, d: date, n: int, tags: tuple[str, ...] = ()) -> date:
        step = _DAY if n > 0 else -_DAY
        for _ in range(abs(n)):
            d = self._seek(d + step, step, tags)
        return d

    def add_workdays(self, start: date, n: int, tags: tuple[str, ...] = ()) -> date:
        if n > 0:
            return self.shift(self.next_workday(start, tags), n - 1, tags)
        if n < 0:
            return self.shift(self.prev_workday(start, tags), n + 1, tags)
        return start

    def workdays_between(self, a: date, b: date, tags: tuple[str, ...] = ()) -> int:
        if b < a:
            return -self.workdays_between(b, a, tags)
        count = 0
        d = a
        while d < b:
            d += _DAY
            count += self.is_workday(d, tags)
        return count


# ---- 맞대 보기 도구 ----

TAGS = ("타설", "철골", "도장")


def outcome(fn, *args):
    """값 또는 (예외 종류, 글)."""
    try:
        return fn(*args)
    except (NoWorkdayError, OverflowError) as e:
        return (type(e).__name__, str(e))


def assert_same(spec: CalendarSpec, method: str, *args) -> None:
    new = outcome(getattr(WorkCalendar(spec), method), *args)
    old = outcome(getattr(OracleCalendar(spec), method), *args)
    assert new == old, (spec, method, args)


def random_md(rng: random.Random) -> tuple[int, int]:
    month = rng.randint(1, 12)
    return (month, rng.randint(1, monthrange(2028, month)[1]))  # 2/29 도 나온다


def random_spec(rng: random.Random) -> CalendarSpec:
    base = date(2024, 1, 1).toordinal()
    holidays = tuple(date.fromordinal(base + k) for k in rng.sample(range(8 * 366), rng.randint(0, 40)))
    blocked = tuple(
        BlockedPeriod(random_md(rng), random_md(rng), rng.choice(TAGS)) for _ in range(rng.randint(0, 3))
    )  # 시작 > 끝 이면 해를 넘기는 기간
    return CalendarSpec(rng.choice((5, 6, 7)), holidays, blocked)


def random_tags(rng: random.Random) -> tuple[str, ...]:
    return tuple(rng.sample(TAGS, rng.randint(0, 2)))


def random_day(rng: random.Random) -> date:
    return date(2025, 1, 1) + timedelta(days=rng.randint(0, 7 * 365))


def check_random_case(rng: random.Random, new: WorkCalendar, old: OracleCalendar) -> None:
    tags, d = random_tags(rng), random_day(rng)
    other = d + timedelta(days=rng.randint(-400, 400))  # 거꾸로·같은 날 포함
    n = rng.randint(-60, 60)
    for method, args in (
        ("is_workday", (d, tags)),
        ("next_workday", (d, tags)),
        ("prev_workday", (d, tags)),
        ("shift", (d, n, tags)),
        ("add_workdays", (d, n, tags)),
        ("workdays_between", (d, other, tags)),
    ):
        got = outcome(getattr(new, method), *args)
        want = outcome(getattr(old, method), *args)
        assert got == want, (method, args)


# ---- 무작위 맞대 보기 ----


def test_random_calendars_match_oracle():
    rng = random.Random(20261120)
    for _ in range(300):  # 달력 300개 × 경우 12개 × 함수 6개
        spec = random_spec(rng)
        new, old = WorkCalendar(spec), OracleCalendar(spec)
        for _ in range(12):
            check_random_case(rng, new, old)


def test_fresh_instances_of_same_spec_match_oracle():
    """같은 달력을 매번 새로 만들어도(계산마다 새로 만드는 compute 처럼) 같은 답."""
    rng = random.Random(7)
    specs = [random_spec(rng) for _ in range(5)]
    for _ in range(1500):
        spec = rng.choice(specs)
        check_random_case(rng, WorkCalendar(spec), OracleCalendar(spec))


def test_far_apart_queries_in_random_order_match_oracle():
    """앞뒤로 멀리 흩어진 물음 — 미리 센 범위가 양쪽으로 자라는 길을 지난다."""
    rng = random.Random(11)
    spec = CalendarSpec(5, KOREA_HOLIDAYS_2027, (BlockedPeriod((12, 1), (2, 28), "타설"),))
    new, old = WorkCalendar(spec), OracleCalendar(spec)
    for _ in range(400):
        tags = random_tags(rng)
        d = date(2000, 1, 1) + timedelta(days=rng.randint(0, 60 * 365))
        e = d + timedelta(days=rng.randint(-3000, 3000))
        n = rng.choice((rng.randint(-5, 5), rng.randint(-800, 800)))
        assert outcome(new.workdays_between, d, e, tags) == outcome(old.workdays_between, d, e, tags)
        assert outcome(new.shift, d, n, tags) == outcome(old.shift, d, n, tags)
        assert outcome(new.add_workdays, e, n, tags) == outcome(old.add_workdays, e, n, tags)


# ---- 가장자리 ----

NO_WORKDAY = CalendarSpec(7, blocked=(BlockedPeriod((1, 1), (12, 31), "x"),))
# 2/29 만 일하는 달력: 근무일 사이가 4~8년
LEAP_ONLY = (BlockedPeriod((1, 1), (2, 28), "x"), BlockedPeriod((3, 1), (12, 31), "x"))


def test_calendar_without_workdays_matches_oracle():
    d = date(2027, 3, 1)
    for tags in (("x",), (), ("y",)):
        for method, args in (
            ("next_workday", (d, tags)),
            ("prev_workday", (d, tags)),
            ("shift", (d, 3, tags)),
            ("shift", (d, -2, tags)),
            ("add_workdays", (d, 4, tags)),
            ("add_workdays", (d, -4, tags)),
            ("workdays_between", (d, d + timedelta(days=500), tags)),
            ("workdays_between", (d, d - timedelta(days=500), tags)),
        ):
            assert_same(NO_WORKDAY, method, *args)


def test_sparse_leap_day_calendar_matches_oracle():
    tags = ("x",)
    for dpw in (5, 6, 7):
        spec = CalendarSpec(dpw, blocked=LEAP_ONLY)
        for d in (date(2027, 3, 1), date(2028, 2, 29), date(2099, 6, 1), date(2101, 1, 1)):
            for n in (-7, -3, -1, 1, 2, 5, 9):
                assert_same(spec, "shift", d, n, tags)
                assert_same(spec, "add_workdays", d, n, tags)
            assert_same(spec, "next_workday", d, tags)
            assert_same(spec, "prev_workday", d, tags)
            assert_same(spec, "workdays_between", d, d + timedelta(days=11000), tags)


def test_gap_longer_than_scan_limit_raises_like_oracle():
    """2/29 를 공휴일로 지워 근무일 사이가 20년을 넘으면 그 사이를 건너는 이동만 실패한다."""
    holes = tuple(date(y, 2, 29) for y in range(2028, 2048, 4))  # 2024 → 2048: 24년
    spec = CalendarSpec(7, holes, LEAP_ONLY)
    tags = ("x",)
    for d in (date(2023, 1, 1), date(2024, 2, 29), date(2030, 1, 1), date(2048, 3, 1), date(2050, 1, 1)):
        for n in (-3, -2, -1, 1, 2, 3):
            assert_same(spec, "shift", d, n, tags)
            assert_same(spec, "add_workdays", d, n, tags)
        assert_same(spec, "next_workday", d, tags)
        assert_same(spec, "prev_workday", d, tags)
        assert_same(spec, "workdays_between", d, date(2049, 1, 1), tags)


def test_scan_limit_boundary_matches_oracle():
    """다음·앞 근무일이 정확히 훑는 한도 언저리(7319·7320·7321일)에 있을 때."""
    holes = tuple(date(y, 2, 29) for y in range(2028, 2048, 4))  # 근무일 2024-02-29 다음은 2048-02-29
    spec = CalendarSpec(7, holes, LEAP_ONLY)
    tags = ("x",)
    first, last = date(2024, 2, 29), date(2048, 2, 29)
    for k in (7318, 7319, 7320, 7321):
        before_last, after_first = last - timedelta(days=k), first + timedelta(days=k)
        assert_same(spec, "next_workday", before_last, tags)
        assert_same(spec, "shift", before_last, 1, tags)
        assert_same(spec, "prev_workday", after_first, tags)
        assert_same(spec, "shift", after_first, -1, tags)


def test_scan_limit_at_date_range_ends_matches_oracle():
    """근무일 없는 달력에서 훑는 한도가 날짜 끝에 걸칠 때 OverflowError·NoWorkdayError 가 갈리는 자리."""
    for k in (7318, 7319, 7320, 7321):
        for n in (1, 2):
            assert_same(NO_WORKDAY, "shift", date.max - timedelta(days=k), n, ("x",))
            assert_same(NO_WORKDAY, "shift", date.min + timedelta(days=k), -n, ("x",))
        assert_same(NO_WORKDAY, "next_workday", date.max - timedelta(days=k), ("x",))
        assert_same(NO_WORKDAY, "prev_workday", date.min + timedelta(days=k), ("x",))


def test_date_range_ends_match_oracle():
    near_max, near_min = date.max - timedelta(days=10), date.min + timedelta(days=10)
    for spec, tags in ((CalendarSpec(5), ()), (CalendarSpec(7), ()), (NO_WORKDAY, ("x",))):
        for d in (date.max, near_max, date.min, near_min):
            for n in (-30, -1, 1, 30):
                assert_same(spec, "shift", d, n, tags)
                assert_same(spec, "add_workdays", d, n, tags)
            assert_same(spec, "next_workday", d, tags)
            assert_same(spec, "prev_workday", d, tags)
        assert_same(spec, "workdays_between", near_max, date.max, tags)
        assert_same(spec, "workdays_between", date.max, near_min.replace(year=9990), tags)
        assert_same(spec, "workdays_between", date.min, near_min, tags)


# ---- 빠르기 ----


def run_benchmark(cal, seed: int) -> float:
    rng, start = random.Random(seed), date(2027, 1, 1)
    t = time.perf_counter()
    for _ in range(3000):
        a = start + timedelta(days=rng.randint(0, 365))
        b = a + timedelta(days=rng.randint(-200, 200))
        tags = ("타설",) if rng.random() < 0.3 else ()
        cal.workdays_between(a, b, tags)
        cal.shift(a, rng.randint(-20, 20), tags)
        cal.add_workdays(b, rng.randint(1, 15), tags)
        cal.next_workday(a, tags)
    return time.perf_counter() - t


def test_fast_calendar_is_at_least_five_times_faster():
    """같은 물음 묶음(여유 셈·이동·기간 끝·다음 근무일)을 예전 계산과 견준다.

    번갈아 다섯 번 재어 각자 가장 빠른 값을 쓴다(다른 일이 잠깐 몰려도 흔들리지 않게).
    """
    spec = CalendarSpec(5, KOREA_HOLIDAYS_2027, (BlockedPeriod((12, 1), (2, 28), "타설"),))
    run_benchmark(WorkCalendar(spec), 3)  # 미리 세기는 계산마다 다시 하지 않으므로 한 번 데운다
    rounds = [(run_benchmark(OracleCalendar(spec), 3), run_benchmark(WorkCalendar(spec), 3)) for _ in range(5)]
    old, new = min(r[0] for r in rounds), min(r[1] for r in rounds)
    assert old / new >= 5, f"old {old:.3f}s new {new:.3f}s ×{old / new:.1f}"
