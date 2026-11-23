from datetime import date

import pytest

from app.core.calendar import (
    KOREA_HOLIDAYS_2026,
    KOREA_HOLIDAYS_2027,
    KOREA_HOLIDAYS_2028,
    WorkCalendar,
)
from app.core.model import BlockedPeriod, CalendarSpec
from app.harness.assemble import holidays_of

MON = date(2027, 3, 1)  # 2027-03-01은 월요일
CAL5 = WorkCalendar(CalendarSpec(days_per_week=5))


def test_five_day_week_skips_weekend():
    assert CAL5.is_workday(date(2027, 3, 5))
    assert not CAL5.is_workday(date(2027, 3, 6))
    assert not CAL5.is_workday(date(2027, 3, 7))


def test_six_day_week_works_saturday_rests_sunday():
    cal = WorkCalendar(CalendarSpec(days_per_week=6))
    assert cal.is_workday(date(2027, 3, 6))
    assert not cal.is_workday(date(2027, 3, 7))


def test_seven_day_week_works_every_day():
    cal = WorkCalendar(CalendarSpec(days_per_week=7))
    assert cal.is_workday(date(2027, 3, 6)) and cal.is_workday(date(2027, 3, 7))


def test_holiday_is_not_workday():
    cal = WorkCalendar(CalendarSpec(5, holidays=(MON,)))
    assert not cal.is_workday(MON)
    assert cal.next_workday(MON) == date(2027, 3, 2)


def test_next_workday_keeps_a_workday():
    assert CAL5.next_workday(MON) == MON
    assert CAL5.next_workday(date(2027, 3, 6)) == date(2027, 3, 8)


def test_add_workdays_zero_and_one_return_start():
    assert CAL5.add_workdays(MON, 0) == MON
    assert CAL5.add_workdays(MON, 1) == MON


def test_add_workdays_counts_start_and_skips_weekend():
    assert CAL5.add_workdays(MON, 3) == date(2027, 3, 3)
    assert CAL5.add_workdays(MON, 5) == date(2027, 3, 5)
    assert CAL5.add_workdays(MON, 6) == date(2027, 3, 8)


def test_add_workdays_from_non_workday_starts_on_next_workday():
    assert CAL5.add_workdays(date(2027, 3, 6), 1) == date(2027, 3, 8)


def test_add_workdays_negative_gives_start_of_job_ending_on_date():
    assert CAL5.add_workdays(date(2027, 3, 5), -1) == date(2027, 3, 5)
    assert CAL5.add_workdays(date(2027, 3, 8), -2) == date(2027, 3, 5)
    assert CAL5.add_workdays(date(2027, 3, 5), -5) == MON


def test_shift_moves_by_workdays_both_ways():
    assert CAL5.shift(MON, 0) == MON
    assert CAL5.shift(MON, 2) == date(2027, 3, 3)
    assert CAL5.shift(date(2027, 3, 5), 1) == date(2027, 3, 8)
    assert CAL5.shift(date(2027, 3, 8), -1) == date(2027, 3, 5)


def test_workdays_between_forward_and_backward():
    assert CAL5.workdays_between(MON, MON) == 0
    assert CAL5.workdays_between(date(2027, 3, 2), date(2027, 3, 5)) == 3
    assert CAL5.workdays_between(date(2027, 3, 5), date(2027, 3, 8)) == 1
    assert CAL5.workdays_between(date(2027, 3, 12), date(2027, 3, 5)) == -5


def test_blocked_period_wrapping_year_end():
    cal = WorkCalendar(CalendarSpec(7, blocked=(BlockedPeriod((12, 1), (2, 28), "타설"),)))
    tags = ("타설",)
    assert not cal.is_workday(date(2027, 12, 1), tags)
    assert not cal.is_workday(date(2027, 12, 31), tags)
    assert not cal.is_workday(date(2028, 1, 15), tags)
    assert not cal.is_workday(date(2027, 2, 28), tags)
    assert cal.is_workday(date(2027, 3, 1), tags)
    assert cal.is_workday(date(2027, 11, 30), tags)
    assert cal.is_workday(date(2028, 1, 15))
    assert cal.is_workday(date(2028, 1, 15), ("철골",))
    assert cal.next_workday(date(2026, 12, 10), tags) == date(2027, 3, 1)
    # 기간 끝은 적힌 월·일 그대로다: 윤년의 2/29 는 (2,28) 기간 밖
    assert cal.next_workday(date(2027, 12, 10), tags) == date(2028, 2, 29)


def test_calendar_without_any_workday_raises():
    cal = WorkCalendar(CalendarSpec(7, blocked=(BlockedPeriod((1, 1), (12, 31), "x"),)))
    with pytest.raises(ValueError):
        cal.next_workday(MON, ("x",))


def test_korea_holidays_2027_include_fixed_days():
    assert {date(2027, 1, 1), date(2027, 3, 1), date(2027, 5, 5), date(2027, 8, 15), date(2027, 10, 3), date(2027, 10, 9), date(2027, 12, 25)} <= set(KOREA_HOLIDAYS_2027)


def test_korea_holidays_2027_count_and_substitutes():
    assert len(KOREA_HOLIDAYS_2027) == 24
    assert len(set(KOREA_HOLIDAYS_2027)) == 24
    assert {date(2027, 5, 3), date(2027, 7, 19), date(2027, 12, 27)} <= set(KOREA_HOLIDAYS_2027)


def test_kr_calendar_rests_on_2026_and_2028_holidays():
    """I3: 달력 조건의 "KR" 은 2026·2027·2028년 공휴일을 모두 쉰다(2027년 표는 그대로)."""
    kr = holidays_of("KR")
    assert {date(2026, 12, 25), date(2028, 1, 1)} <= set(kr)
    assert set(KOREA_HOLIDAYS_2027) <= set(kr)
    assert list(kr) == sorted(set(kr))  # 날짜 순, 겹침 없음
    cal = WorkCalendar(CalendarSpec(6, kr))
    assert not cal.is_workday(date(2026, 12, 25)) and not cal.is_workday(date(2028, 1, 1))
    # 2026-12-19(토)에 시작하는 6일 작업: 성탄절(금)을 건너뛰어 12-26(토)에 끝난다(전에는 12-25)
    assert cal.add_workdays(date(2026, 12, 19), 6) == date(2026, 12, 26)


def test_korea_holidays_2026_and_2028_substitutes_and_lunar_days():
    """I3: 음력 명절(KST 새달)·선거일·대체 공휴일. 2028 설은 1-27(새달 00:12 KST), 추석이 개천절과 겹쳐 10-5 대체."""
    h26, h28 = set(KOREA_HOLIDAYS_2026), set(KOREA_HOLIDAYS_2028)
    assert (len(KOREA_HOLIDAYS_2026), len(h26), len(KOREA_HOLIDAYS_2028), len(h28)) == (22, 22, 18, 18)
    assert {date(2026, 2, 17), date(2026, 5, 24), date(2026, 9, 25), date(2026, 6, 3)} <= h26  # 설·부처님·추석·지방선거
    assert {date(2026, 3, 2), date(2026, 5, 25), date(2026, 8, 17), date(2026, 10, 5)} <= h26  # 대체 공휴일
    assert date(2026, 6, 8) not in h26  # 현충일(토)은 대체하지 않는다
    assert {date(2028, 1, 26), date(2028, 1, 27), date(2028, 1, 28), date(2028, 5, 2), date(2028, 4, 12)} <= h28
    assert {date(2028, 10, 2), date(2028, 10, 3), date(2028, 10, 4), date(2028, 10, 5)} <= h28
    assert date(2028, 1, 3) not in h28  # 신정(토)은 대체하지 않는다
