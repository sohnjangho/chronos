"""공정률·S-커브 계산(app.core.progress). 값은 0~1, 날짜 d 의 값 = "d 날 아침(전날까지)" 기준."""

from datetime import date

import pytest

from app.core.calendar import WorkCalendar
from app.core.model import BlockedPeriod, CalendarSpec
from app.core.progress import (
    Bar,
    actual,
    curve,
    forecast,
    half_up,
    planned,
    points,
    spi,
    start_block,
    weighted,
)

CAL = WorkCalendar(CalendarSpec(days_per_week=5))


def d(m: int, day: int, y: int = 2027) -> date:
    return date(y, m, day)


WEEK = (date(2027, 3, 1), date(2027, 3, 5))  # 3/1(월)~3/5(금)


def bar(i="A", kind="task", w=1.0, plan=WEEK, now=WEEK, act=(None, None), p=0.0, **k):
    return Bar(
        id=i, kind=kind, wbs="1", weight=w, plan_start=plan[0], plan_finish=plan[1], start=now[0], finish=now[1],
        actual_start=act[0], actual_finish=act[1], progress=p, **k,
    )


# --- planned -------------------------------------------------------------------------------------


def test_planned_without_plan_is_zero():
    assert planned(bar(plan=(None, None)), CAL, d(3, 10)) == 0.0


def test_planned_task_counts_workdays_before_the_morning():
    b = bar()  # Plan 3/1(월)~3/5(금), 5 근무일
    assert [planned(b, CAL, x) for x in (d(2, 26), d(3, 1), d(3, 3), d(3, 5), d(3, 6), d(3, 20))] == [
        0.0, 0.0, 0.4, 0.8, 1.0, 1.0
    ]


def test_planned_skips_weekends():
    b = bar(plan=(d(3, 5), d(3, 9)))  # 금·월·화 = 3 근무일
    assert planned(b, CAL, d(3, 8)) == pytest.approx(1 / 3)  # 금요일 하루 끝남(토·일은 세지 않음)


def test_planned_milestone_is_done_the_day_after():
    m = bar(kind="finish_ms", plan=(d(3, 12), d(3, 12)))
    assert (planned(m, CAL, d(3, 12)), planned(m, CAL, d(3, 13))) == (0.0, 1.0)


def test_planned_uses_the_activity_tags():
    cal = WorkCalendar(CalendarSpec(days_per_week=5, blocked=(BlockedPeriod((3, 3), (3, 4), "타설"),)))
    b = bar(plan=(d(3, 1), d(3, 9)), tags=("타설",))  # 3/3·3/4 는 이 작업의 쉬는 날 → 5 근무일
    assert planned(b, cal, d(3, 5)) == pytest.approx(2 / 5)


# --- actual --------------------------------------------------------------------------------------


def test_actual_after_data_date_is_none():
    assert actual(bar(act=(d(3, 1), None), p=0.2), CAL, d(3, 4), d(3, 3)) is None


def test_actual_before_start_is_zero():
    assert actual(bar(), CAL, d(3, 3), d(3, 3)) == 0.0  # 실적 시작 없음
    assert actual(bar(act=(d(3, 2), None), p=0.5), CAL, d(3, 2), d(3, 3)) == 0.0  # 시작하는 날 아침


def test_actual_in_progress_spreads_progress_up_to_the_data_date():
    b = bar(act=(d(3, 1), None), p=0.2)  # 창 [3/1, 3/3) = 2 근무일
    assert [actual(b, CAL, x, d(3, 3)) for x in (d(3, 2), d(3, 3))] == [pytest.approx(0.1), pytest.approx(0.2)]


def test_actual_finished_is_one_after_the_actual_finish():
    b = bar(act=(d(3, 1), d(3, 5)), p=1.0)  # 창 [3/1, 3/6) = 5 근무일
    assert [actual(b, CAL, x, d(3, 15)) for x in (d(3, 3), d(3, 5), d(3, 6))] == [
        pytest.approx(0.4), pytest.approx(0.8), 1.0
    ]


def test_actual_finished_without_actual_start_starts_at_the_bar_start():
    b = bar(now=(d(3, 1), d(3, 5)), act=(None, d(3, 5)), p=1.0)
    assert (actual(b, CAL, d(3, 3), d(3, 15)), actual(b, CAL, d(3, 8), d(3, 15))) == (pytest.approx(0.4), 1.0)


def test_actual_started_on_a_non_workday_right_before_the_data_date():
    b = bar(act=(d(3, 6), None), p=0.3)  # 토요일 시작, Data Date 월요일 → 창에 근무일 없음
    assert actual(b, CAL, d(3, 8), d(3, 8)) == 0.3


# --- forecast ------------------------------------------------------------------------------------


def test_forecast_before_data_date_is_none():
    assert forecast(bar(), CAL, d(3, 2), d(3, 3)) is None


def test_forecast_finished_follows_the_actual_finish():
    """끝난 작업의 예측은 실적과 같은 식(day > 실적 종료면 1) — fix round 1 판단 m2."""
    b = bar(act=(d(3, 1), d(3, 5)), p=1.0)
    assert (forecast(b, CAL, d(3, 3), d(3, 3)), forecast(b, CAL, d(3, 6), d(3, 3))) == (pytest.approx(0.4), 1.0)


def test_forecast_not_started_follows_the_current_dates():
    b = bar(plan=(d(3, 8), d(3, 12)), now=(d(3, 9), d(3, 15)))  # 지금 3/9~3/15
    assert [forecast(b, CAL, x, d(3, 3)) for x in (d(3, 3), d(3, 15), d(3, 16))] == [0.0, pytest.approx(0.8), 1.0]


def test_forecast_in_progress_spreads_the_rest_to_the_finish():
    b = bar(now=(d(3, 1), d(3, 8)), act=(d(3, 1), None), p=0.2)  # 창 [3/3, 3/8] = 4 근무일
    assert [forecast(b, CAL, x, d(3, 3)) for x in (d(3, 3), d(3, 8), d(3, 15))] == [
        pytest.approx(0.2), pytest.approx(0.8), 1.0
    ]


# --- points --------------------------------------------------------------------------------------


def _fixture_bars() -> list[Bar]:
    """A(5, Plan 3/1~3/5, 실적 3/1 시작 진도 0.2, 지금 3/1~3/8) → B(5, Plan 3/8~3/12, 지금 3/9~3/15) → M(준공)."""
    return [
        bar("A", w=0.5, now=(d(3, 1), d(3, 8)), act=(d(3, 1), None), p=0.2),
        bar("B", w=0.5, plan=(d(3, 8), d(3, 12)), now=(d(3, 9), d(3, 15))),
        bar("M", kind="finish_ms", w=0.0, plan=(d(3, 12), d(3, 12)), now=(d(3, 15), d(3, 15))),
    ]


def test_weekly_points_insert_the_data_date():
    assert points(_fixture_bars(), d(3, 3), "week") == [d(3, 1), d(3, 3), d(3, 8), d(3, 15), d(3, 16)]


def test_monthly_points_use_first_days():
    b = [bar(plan=(d(1, 15), d(2, 10)), now=(d(1, 15), d(3, 15)))]
    assert points(b, d(1, 20), "month") == [d(1, 15), d(1, 20), d(2, 1), d(3, 1), d(3, 16)]


def test_points_leave_out_a_data_date_outside_the_range():
    assert points(_fixture_bars(), d(4, 1), "week") == [d(3, 1), d(3, 8), d(3, 15), d(3, 16)]


def test_points_skip_missing_plan_dates():
    b = [bar(plan=(None, None), now=(d(3, 2), d(3, 4)))]
    assert points(b, d(3, 3), "week") == [d(3, 2), d(3, 3), d(3, 5)]


# --- weighted · spi ------------------------------------------------------------------------------


def test_weighted_is_a_percentage_with_one_decimal():
    bars = [bar("A", w=0.5), bar("B", w=0.5)]
    assert weighted(bars, {"A": 0.4, "B": 0.0}) == 20.0
    assert weighted(bars, {"A": 1 / 3, "B": 0.0}) == 16.7


def test_weighted_without_weights_is_zero():
    assert weighted([bar("A", w=0.0)], {"A": 1.0}) == 0.0


def test_weighted_ignores_rounding_of_four_decimal_weights():
    bars = [bar(str(i), w=0.3333) for i in range(3)]  # 합 0.9999
    assert weighted(bars, {b.id: 1.0 for b in bars}) == 100.0


def test_spi():
    assert (spi(20.0, 10.0), spi(0.0, 5.0), spi(30.0, 10.0), spi(100.0, 0.0)) == (0.5, None, 0.33, 0.0)


# --- curve ---------------------------------------------------------------------------------------


def test_curve_matches_the_brief_example():
    c = curve(_fixture_bars(), CAL, data_date=d(3, 3), unit="week")
    assert [x.date for x in c] == [d(3, 1), d(3, 3), d(3, 8), d(3, 15), d(3, 16)]
    assert [x.plan_cum for x in c] == [0.0, 20.0, 50.0, 100.0, 100.0]
    assert [x.actual_cum for x in c] == [0.0, 10.0, None, None, None]
    assert [x.forecast_cum for x in c] == [None, 10.0, 40.0, 90.0, 100.0]
    assert [x.plan_period for x in c] == [0.0, 20.0, 30.0, 50.0, 0.0]
    assert [x.actual_period for x in c] == [0.0, 10.0, None, None, None]


def test_curve_without_bars_is_empty():
    assert curve([], CAL, data_date=d(3, 3), unit="week") == []


# --- fix round 1 ---------------------------------------------------------------------------------


def test_finished_without_actual_start_after_its_finish_is_one():
    """지금 계산 시작이 실적 종료보다 늦게 잡혀 있어도 실적 종료 다음 날부터 1(m3)."""
    b = bar(now=(d(3, 8), d(3, 12)), act=(None, d(3, 5)), p=1.0)
    assert (actual(b, CAL, d(3, 8), d(3, 15)), actual(b, CAL, d(3, 5), d(3, 15))) == (1.0, 0.0)


def test_actual_and_forecast_agree_when_finishing_on_the_data_date():
    """Data Date 에 끝난 작업: 그 날 아침에는 아직 다 끝나지 않았다 — 실적·예측 모두(m2)."""
    b = bar(now=(d(3, 1), d(3, 3)), act=(d(3, 1), d(3, 3)), p=1.0)  # 창 [3/1, 3/4) = 3 근무일, 아침까지 2
    assert actual(b, CAL, d(3, 3), d(3, 3)) == forecast(b, CAL, d(3, 3), d(3, 3)) == pytest.approx(2 / 3)
    assert forecast(b, CAL, d(3, 4), d(3, 3)) == 1.0


def test_actual_and_forecast_agree_when_starting_on_the_data_date():
    """Data Date 에 시작한 작업: 그 날 아침에는 한 일이 없다. 예측은 0 에서 지금 종료까지 오른다(m2)."""
    b = bar(now=(d(3, 3), d(3, 8)), act=(d(3, 3), None), p=0.3)  # 창 [3/3, 3/8] = 4 근무일
    assert actual(b, CAL, d(3, 3), d(3, 3)) == forecast(b, CAL, d(3, 3), d(3, 3)) == 0.0
    assert forecast(b, CAL, d(3, 5), d(3, 3)) == pytest.approx(0.5)


def test_curve_lines_meet_at_the_data_date():
    bars = [
        bar("A", w=0.5, now=(d(3, 1), d(3, 3)), act=(d(3, 1), d(3, 3)), p=1.0),
        bar("B", w=0.5, plan=(d(3, 4), d(3, 8)), now=(d(3, 3), d(3, 9)), act=(d(3, 3), None), p=0.4),
    ]
    at = next(x for x in curve(bars, CAL, data_date=d(3, 3), unit="week") if x.date == d(3, 3))
    assert at.actual_cum == at.forecast_cum == 33.3


def test_half_up_rounds_halves_away_from_zero():
    assert (half_up(12.5), half_up(0.25, 1), half_up(0.125, 2), half_up(-0.25, 1), half_up(-0.04, 1)) == (
        13.0, 0.3, 0.13, -0.3, 0.0
    )
    assert spi(8.0, 1.0) == 0.13  # round() 라면 0.12


# --- start_block (앞으로 3주의 막힘) ---------------------------------------------------------------


def test_fs_blocks_until_the_predecessor_finishes():
    a = bar(now=(d(3, 1), d(3, 8)), act=(d(3, 1), None), p=0.2)
    assert start_block(CAL, a, "FS", 0, d(3, 3)) == "선행 미완료"


def test_fs_lag_waits_whole_workdays_after_the_actual_finish():
    a = bar(act=(d(3, 1), d(3, 5)), p=1.0)  # 금요일 저녁 끝, lag 2 → 월·화 기다리고 수요일 아침
    assert start_block(CAL, a, "FS", 2, d(3, 9)) == "선행 뒤 2일 대기"
    assert start_block(CAL, a, "FS", 2, d(3, 10)) is None


def test_fs_without_lag_is_free_the_next_workday_even_from_a_weekend_data_date():
    a = bar(act=(d(3, 1), d(3, 5)), p=1.0)
    assert (start_block(CAL, a, "FS", 0, d(3, 6)), start_block(CAL, a, "FS", 0, d(3, 8))) == (None, None)


def test_fs_finishing_on_the_data_date_is_not_finished_that_morning():
    a = bar(now=(d(3, 1), d(3, 3)), act=(d(3, 1), d(3, 3)), p=1.0)
    assert start_block(CAL, a, "FS", 0, d(3, 3)) == "선행 미완료"


def test_fs_lead_lets_the_successor_start_before_the_predecessor_finishes():
    a = bar(now=(d(3, 1), d(3, 8)), act=(d(3, 1), None), p=0.2)  # 지금 종료 3/8(월)
    assert start_block(CAL, a, "FS", -4, d(3, 3)) is None  # 3/8 저녁에서 근무일 4 앞 = 3/2 저녁 → 3/3 아침
    assert start_block(CAL, a, "FS", -3, d(3, 3)) == "선행 미완료"  # 3/3 저녁 → 3/4 아침


def test_ss_needs_the_predecessor_started():
    started = bar(now=(d(3, 1), d(3, 8)), act=(d(3, 1), None), p=0.2)
    waiting = bar(plan=(d(3, 8), d(3, 12)), now=(d(3, 9), d(3, 15)))
    assert start_block(CAL, started, "SS", 0, d(3, 3)) is None
    assert start_block(CAL, waiting, "SS", 0, d(3, 3)) == "선행 미착수"
    assert start_block(CAL, started, "SS", 3, d(3, 3)) == "선행 뒤 3일 대기"  # 3/1 아침 + 근무일 3 → 3/4
    assert start_block(CAL, started, "SS", 3, d(3, 4)) is None


def test_ff_and_sf_never_block_the_start():
    waiting = bar(plan=(d(3, 8), d(3, 12)), now=(d(3, 9), d(3, 15)))
    assert (start_block(CAL, waiting, "FF", 0, d(3, 3)), start_block(CAL, waiting, "SF", 2, d(3, 3))) == (None, None)
