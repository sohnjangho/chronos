from datetime import date

import pytest

from app.core.calendar import KOREA_HOLIDAYS_2027, WorkCalendar
from app.core.model import BlockedPeriod, CalendarSpec

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
