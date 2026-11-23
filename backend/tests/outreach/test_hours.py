"""연락 근무시간 — 순수 계산. 시각은 모두 KST 로 판정한다."""

from datetime import UTC, date, datetime

import pytest

from app.core.calendar import KOREA_HOLIDAYS
from app.core.model import CalendarSpec
from app.outreach.hours import (
    DEFAULT_END,
    DEFAULT_START,
    KST,
    clamp,
    is_working,
    label,
    next_start,
)

KR = CalendarSpec(days_per_week=5, holidays=KOREA_HOLIDAYS)  # 프로젝트 달력 "KR"
NIGHT = {"days": [0, 1, 2, 3, 4], "start": "22:00", "end": "06:00"}  # 월~금 밤, 자정을 넘음


def kst(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=KST)


def test_defaults_are_eight_to_six():
    assert (DEFAULT_START.hour, DEFAULT_START.minute) == (8, 0)
    assert (DEFAULT_END.hour, DEFAULT_END.minute) == (18, 0)


def test_start_minute_is_inside_end_minute_is_outside():
    assert not is_working(None, KR, kst(2026, 11, 27, 7, 59))
    assert is_working(None, KR, kst(2026, 11, 27, 8, 0))
    assert is_working(None, KR, kst(2026, 11, 27, 17, 59))
    assert not is_working(None, KR, kst(2026, 11, 27, 18, 0))


def test_empty_hours_use_project_calendar_days():
    six = CalendarSpec(days_per_week=6)
    sat = kst(2026, 11, 28, 10)
    assert not is_working(None, KR, sat)
    assert not is_working({}, KR, sat)
    assert is_working(None, six, sat)
    assert not is_working(None, six, kst(2026, 11, 29, 10))  # 일요일


def test_friday_evening_goes_to_monday_start():
    fri = kst(2026, 11, 27, 19)
    assert not is_working(None, KR, fri)
    assert next_start(None, KR, fri) == kst(2026, 11, 30, 8)
    assert next_start(None, KR, kst(2026, 11, 28, 12)) == kst(2026, 11, 30, 8)  # 토요일 낮
    assert next_start(None, KR, kst(2026, 11, 27, 7, 59)) == kst(2026, 11, 27, 8)  # 같은 날 아침


@pytest.mark.parametrize(
    "now,expected",
    [
        (kst(2026, 12, 24, 18), kst(2026, 12, 28, 8)),  # 2026 성탄절(금) 전날 저녁
        (kst(2026, 9, 23, 18, 30), kst(2026, 9, 28, 8)),  # 2026 추석 연휴(목~토) 전날
        (kst(2028, 9, 29, 18), kst(2028, 10, 6, 8)),  # 2028 추석·개천절(월~목) 앞 금요일
        (kst(2028, 10, 6, 18), kst(2028, 10, 10, 8)),  # 2028 한글날(월) 앞 금요일
        (kst(2027, 2, 5, 18), kst(2027, 2, 10, 8)),  # 2027 설날 연휴·대체 공휴일
    ],
)
def test_holiday_is_skipped(now, expected):
    assert next_start(None, KR, now) == expected


@pytest.mark.parametrize("day", [date(2026, 12, 25), date(2026, 6, 3), date(2028, 10, 4), date(2028, 4, 12)])
def test_holiday_daytime_is_not_working(day):
    assert not is_working(None, KR, kst(day.year, day.month, day.day, 10))


def test_overnight_hours():
    assert not is_working(NIGHT, KR, kst(2026, 11, 23, 21, 59))  # 월 밤 시작 1분 전
    assert is_working(NIGHT, KR, kst(2026, 11, 23, 22))  # 월 22:00 시작
    assert is_working(NIGHT, KR, kst(2026, 11, 24, 5, 59))  # 화 새벽 — 월요일 근무의 끝자락
    assert not is_working(NIGHT, KR, kst(2026, 11, 24, 6))  # 끝 시각은 밖
    assert is_working(NIGHT, KR, kst(2026, 11, 28, 2))  # 토 새벽 — 금요일 근무
    assert not is_working(NIGHT, KR, kst(2026, 11, 29, 2))  # 일 새벽 — 토요일은 근무일 아님
    assert not is_working(NIGHT, KR, kst(2026, 11, 30, 2))  # 월 새벽 — 일요일 근무 없음
    assert next_start(NIGHT, KR, kst(2026, 11, 24, 6)) == kst(2026, 11, 24, 22)
    assert next_start(NIGHT, KR, kst(2026, 11, 28, 6)) == kst(2026, 11, 30, 22)  # 토 아침 → 월 밤
    assert label(NIGHT, KR, kst(2026, 11, 23, 23)) == "근무 중 · 06:00 까지"


def test_overnight_shift_belongs_to_the_day_it_starts():
    assert is_working(NIGHT, KR, kst(2026, 12, 25, 3))  # 목(평일) 밤에 시작해 성탄절 새벽까지
    assert not is_working(NIGHT, KR, kst(2026, 12, 25, 23))  # 성탄절 밤에는 시작하지 않음
    assert next_start(NIGHT, KR, kst(2026, 12, 25, 6)) == kst(2026, 12, 28, 22)


def test_utc_input_is_judged_in_kst():
    assert is_working(None, KR, datetime(2026, 11, 27, 0, 0, tzinfo=UTC))  # = 금 09:00 KST
    late = datetime(2026, 11, 27, 9, 30, tzinfo=UTC)  # = 금 18:30 KST
    assert not is_working(None, KR, late)
    assert next_start(None, KR, late) == kst(2026, 11, 30, 8)
    assert is_working(None, KR, datetime(2026, 11, 26, 23, 0))  # 시간대 없음 = UTC → 금 08:00 KST
    assert not is_working(None, KR, datetime(2026, 11, 27, 9, 0))  # 시간대 없음 → 금 18:00 KST
    assert next_start(None, KR, datetime(2026, 11, 27, 9, 0)).tzinfo == KST


def test_person_hours_override_days_but_not_holidays():
    wed_sat = {"days": [2, 5], "start": "09:00", "end": "17:00"}
    assert is_working(wed_sat, KR, kst(2026, 11, 28, 10))  # 토요일 — 달력은 쉬지만 이 사람은 일함
    assert not is_working(wed_sat, KR, kst(2026, 11, 24, 10))  # 화요일 — 달력은 일하지만 이 사람은 쉼
    assert not is_working(wed_sat, KR, kst(2026, 11, 25, 8, 30))  # 수요일이지만 이 사람 시작 전
    assert not is_working(wed_sat, KR, kst(2026, 10, 3, 10))  # 2026 개천절(토) — 공휴일은 쉼
    assert not is_working(wed_sat, KR, kst(2028, 10, 4, 10))  # 2028 추석 연휴(수)
    assert next_start(wed_sat, KR, kst(2028, 10, 4, 10)) == kst(2028, 10, 7, 9)
    assert next_start(wed_sat, KR, kst(2026, 11, 25, 17)) == kst(2026, 11, 28, 9)
    assert label(wed_sat, KR, kst(2026, 11, 25, 17)) == "근무 밖 · 토 09:00 부터"


def test_working_now_returns_now():
    now = kst(2026, 11, 23, 10, 17)
    assert next_start(None, KR, now) == now
    as_utc = datetime(2026, 11, 23, 1, 17, tzinfo=UTC)
    assert next_start(None, KR, as_utc) == now


def test_clamp_inside_is_unchanged():
    inside = kst(2026, 11, 26, 13, 5)
    assert clamp(None, KR, inside) == inside
    assert clamp(None, KR, kst(2026, 11, 27, 18)) == kst(2026, 11, 30, 8)


def test_label():
    assert label(None, KR, kst(2026, 11, 23, 10)) == "근무 중 · 18:00 까지"
    assert label(None, KR, kst(2026, 11, 27, 19)) == "근무 밖 · 월 08:00 부터"


def test_equal_start_and_end_is_a_full_day():
    mon_all_day = {"days": [0], "start": "09:00", "end": "09:00"}
    assert is_working(mon_all_day, KR, kst(2026, 11, 23, 9))
    assert is_working(mon_all_day, KR, kst(2026, 11, 24, 8, 59))
    assert not is_working(mon_all_day, KR, kst(2026, 11, 24, 9))


def test_no_working_day_raises():
    never = {"days": [], "start": "09:00", "end": "18:00"}
    assert not is_working(never, KR, kst(2026, 11, 23, 10))
    with pytest.raises(ValueError):
        next_start(never, KR, kst(2026, 11, 23, 10))
