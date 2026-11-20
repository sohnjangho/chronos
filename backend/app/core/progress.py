"""공정률과 S-커브.

값은 0~1(한 액티비티가 끝난 몫)이고, 날짜 d 의 값은 "d 날 아침 = 전날까지 한 일" 이다. cpm 의 Data Date
규칙(남은 일을 Data Date 부터 센다)과 같은 뜻이다. 근무일은 액티비티의 꼬리표 달력으로 센다.
- planned: Plan 막대를 근무일로 고르게 나눈 몫.
- actual: 실적. Data Date 뒤는 모른다(None). 진행 중이면 진도를 [실적 시작, Data Date) 에 고르게 나눈다.
- forecast: 예측. Data Date 앞은 없다(None). 진행 중이면 남은 몫을 [Data Date, 지금 종료] 에 고르게 나눈다.
퍼센트(weighted·curve)는 가중치 합으로 나눈 값 × 100, 소수 1자리다.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.core.calendar import WorkCalendar

Unit = Literal["week", "month"]
ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Bar:
    """한 액티비티의 막대. start/finish = 지금 계산(es/ef), plan_* = Plan 계산(없으면 None)."""

    id: str
    kind: str
    wbs: str
    weight: float
    plan_start: date | None
    plan_finish: date | None
    start: date
    finish: date
    actual_start: date | None
    actual_finish: date | None
    progress: float
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurvePoint:
    """S-커브의 한 점. 값은 퍼센트(소수 1자리). period 는 앞 점에서 늘어난 양(첫 점은 0 에서)."""

    date: date
    plan_cum: float
    actual_cum: float | None
    forecast_cum: float | None
    plan_period: float
    actual_period: float | None


def _days(cal: WorkCalendar, a: date, b: date, tags: tuple[str, ...]) -> int:
    """[a, b) 의 근무일 수. b ≤ a 면 0."""
    if b <= a:
        return 0
    return cal.workdays_between(a - ONE_DAY, b - ONE_DAY, tags)


def _share(cal: WorkCalendar, kind: str, start: date, finish: date, day: date, tags: tuple[str, ...]) -> float:
    """[start, finish] 를 근무일로 고르게 나눠 day 아침까지 끝난 몫. 마일스톤은 finish 다음 날부터 1."""
    n = _days(cal, start, finish + ONE_DAY, tags) if kind == "task" else 0
    if n == 0:
        return 1.0 if day > finish else 0.0
    return min(_days(cal, start, day, tags) / n, 1.0)


def _started(bar: Bar) -> date | None:
    """실적 시작일. 실적 시작 없이 끝났으면 지금 계산 시작과 실적 종료 가운데 이른 날. 시작 안 했으면 None."""
    if bar.actual_start is not None:
        return bar.actual_start
    if bar.actual_finish is not None:
        return min(bar.start, bar.actual_finish)
    return None


def planned(bar: Bar, cal: WorkCalendar, day: date) -> float:
    """Plan 이 없으면 0. 마일스톤은 day > plan_finish 이면 1. task 는 min(k/n, 1)
    (n = [plan_start, plan_finish] 의 근무일 수, k = [plan_start, day) 의 근무일 수)."""
    if bar.plan_start is None or bar.plan_finish is None:
        return 0.0
    return _share(cal, bar.kind, bar.plan_start, bar.plan_finish, day, bar.tags)


def _done_share(bar: Bar, cal: WorkCalendar, day: date) -> float:
    """끝난 작업(actual_finish 있음)의 몫: day > 실적 종료면 1, day ≤ 실적 시작이면 0, 그 사이는 k/n
    (창 [실적 시작, 실적 종료 다음 날), 끝난 작업의 진도는 1). 창에 근무일이 없으면 1."""
    finish = bar.actual_finish
    if day > finish:
        return 1.0
    started = _started(bar)
    if day <= started:
        return 0.0
    n = _days(cal, started, finish + ONE_DAY, bar.tags)
    return min(_days(cal, started, day, bar.tags) / n, 1.0) if n else 1.0


def actual(bar: Bar, cal: WorkCalendar, day: date, data_date: date) -> float | None:
    """day > data_date 면 None. 끝났고 day > 실적 종료면 1. 시작 안 했거나 day ≤ 실적 시작이면 0.
    그 밖에는 진도 × k/n — 창 [실적 시작, end)(진행 중 end = data_date, 끝남 end = 실적 종료 다음 날).
    끝난 작업의 진도는 1 로 본다. 실적 시작 없이 끝난 작업은 지금 계산 시작과 실적 종료 가운데 이른 날에서 센다.
    창에 근무일이 없으면(예: 토요일 시작, 월요일 Data Date) 진도 그대로다."""
    if day > data_date:
        return None
    if bar.actual_finish is not None:
        return _done_share(bar, cal, day)
    started = bar.actual_start
    if started is None or day <= started:
        return 0.0
    n = _days(cal, started, data_date, bar.tags)
    if n == 0:
        return bar.progress
    return bar.progress * min(_days(cal, started, day, bar.tags) / n, 1.0)


def forecast(bar: Bar, cal: WorkCalendar, day: date, data_date: date) -> float | None:
    """day < data_date 면 None. Data Date 에는 actual 과 같은 값이다(아침 규칙).
    - 끝남: actual 과 같은 식(day > 실적 종료면 1).
    - 시작 전: 지금 계산 [start, finish] 로 planned 와 같은 식.
    - 진행 중: p0 + (1−p0) × min(k/n, 1). p0 = Data Date 아침의 실적(실적 시작이 Data Date 이후면 0),
      창 [s, finish], s = max(Data Date, 실적 시작), k = [s, day) 의 근무일 수."""
    if day < data_date:
        return None
    if bar.actual_finish is not None:
        return _done_share(bar, cal, day)
    if bar.actual_start is None:
        return _share(cal, bar.kind, bar.start, bar.finish, day, bar.tags)
    p0 = actual(bar, cal, data_date, data_date) or 0.0
    since = max(data_date, bar.actual_start)
    n = _days(cal, since, bar.finish + ONE_DAY, bar.tags)
    if n == 0:
        return 1.0 if day > bar.finish else p0
    return p0 + (1 - p0) * min(_days(cal, since, day, bar.tags) / n, 1.0)


def _month_firsts(first: date, end: date) -> list[date]:
    """first 다음 달부터 end 앞까지의 매달 1일."""
    out, y, m = [], first.year, first.month
    while True:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        day = date(y, m, 1)
        if day >= end:
            return out
        out.append(day)


def points(bars: list[Bar], data_date: date, unit: Unit) -> list[date]:
    """S-커브의 날짜들. 시작 = Plan·지금 시작 가운데 가장 이른 날, 끝 = Plan·지금 종료 가운데 가장 늦은 날 + 1일.
    week = 시작 + 7k(끝 전까지) + 끝, month = 시작 + 다음 달들 1일 + 끝. Data Date 가 그 사이면 끼운다."""
    starts = [x for b in bars for x in (b.plan_start, b.start) if x is not None]
    ends = [x for b in bars for x in (b.plan_finish, b.finish) if x is not None]
    if not starts or not ends:
        return []
    first, end = min(starts), max(ends) + ONE_DAY
    if unit == "week":
        days = [first + timedelta(weeks=k) for k in range((end - first).days // 7 + 1)]
        days = [x for x in days if x < end]
    else:
        days = [first, *_month_firsts(first, end)]
    days.append(end)
    if first < data_date < end:
        days.append(data_date)
    return sorted(set(days))


def half_up(x: float, digits: int = 0) -> float:
    """반올림. 0.5 는 0 에서 먼 쪽으로(12.5 → 13, 0.25 → 0.3, −0.25 → −0.3), −0.0 은 0.0.
    round() 의 짝수 반올림과 이진 소수 오차를 피하려고 십진수(짧은 표기)로 센다."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(q) + 0.0


def _pct(x: float) -> float:
    """소수 1자리 퍼센트."""
    return half_up(x, 1)


def weighted(bars: list[Bar], fractions: dict[str, float]) -> float:
    """Σ w·f / Σ w × 100, 소수 1자리. 가중치 합이 0 이면 0. (가중치는 합이 1 이 되게 나눈 값이라
    Σ w·f × 100 과 같다. 합으로 다시 나누는 것은 소수 4자리 반올림 때문에 끝점이 100 에서 벗어나지 않게 하려는 것.)"""
    total = sum(b.weight for b in bars)
    if total <= 0:
        return 0.0
    return _pct(sum(b.weight * fractions.get(b.id, 0.0) for b in bars) / total * 100)


def spi(plan_pct: float, actual_pct: float) -> float | None:
    """실적 ÷ 계획, 소수 2자리. 계획이 0 이면 None."""
    if plan_pct <= 0:
        return None
    return half_up(actual_pct / plan_pct, 2)


def _at(bars: list[Bar], cal: WorkCalendar, day: date, data_date: date) -> tuple[float, float | None, float | None]:
    plan = weighted(bars, {b.id: planned(b, cal, day) for b in bars})
    act = None if day > data_date else weighted(bars, {b.id: actual(b, cal, day, data_date) or 0.0 for b in bars})
    fc = None if day < data_date else weighted(bars, {b.id: forecast(b, cal, day, data_date) or 0.0 for b in bars})
    return plan, act, fc


def curve(bars: list[Bar], cal: WorkCalendar, *, data_date: date, unit: Unit) -> list[CurvePoint]:
    """points 의 날마다 누적 계획·실적(Data Date 까지)·예측(Data Date 부터)과 구간 증가량."""
    out: list[CurvePoint] = []
    prev_plan = prev_act = 0.0
    for day in points(bars, data_date, unit):
        plan, act, fc = _at(bars, cal, day, data_date)
        act_period = None if act is None else _pct(act - prev_act)
        out.append(CurvePoint(day, plan, act, fc, _pct(plan - prev_plan), act_period))
        prev_plan, prev_act = plan, prev_act if act is None else act
    return out


def start_block(
    cal: WorkCalendar, pred: Bar, rel_type: str, lag: int, data_date: date, tags: tuple[str, ...] = ()
) -> str | None:
    """선행 관계 하나가 Data Date 아침에 후행 task(꼬리표 tags)의 시작을 막는 까닭. 막지 않으면 None.

    FS 는 선행 종료, SS 는 선행 시작에서 lag 근무일(꼬리표 없는 달력, 음수면 앞당김) 뒤에 시작할 수 있다 — cpm 과 같은
    아침·저녁 규칙(선행 종료는 저녁, 시작 마일스톤은 아침, 종료 마일스톤은 저녁). 선행 날짜는 지금 계산 날짜이고
    실적이 있으면 그것이 곧 실적이다. FF·SF 는 시작을 막지 않는다. "오늘" 은 Data Date(후행 달력의 다음 근무일).
    - 선행이 Data Date 아침까지 끝나지(FS) / 시작하지(SS) 않았으면 lag ≥ 0 일 때 늘 막힘: "선행 미완료" / "선행 미착수".
      앞당김(lag < 0)이면 지금 계산 날짜로 센 가능일이 오늘보다 늦을 때만 막힌다.
    - 끝났거나 시작했는데 lag 이 아직 다 지나지 않았으면 "선행 뒤 n일 대기"(n = lag).
    """
    if rel_type == "FS":
        evening, anchor, reason = pred.kind != "start_ms", pred.finish, "선행 미완료"
        ready = pred.actual_finish is not None and pred.actual_finish < data_date
    elif rel_type == "SS":
        evening, anchor, reason = pred.kind == "finish_ms", pred.start, "선행 미착수"
        started = _started(pred)
        ready = started is not None and started <= data_date
    else:
        return None
    if lag:
        anchor = cal.shift(cal.prev_workday(anchor) if evening else anchor, lag)
    earliest = cal.next_workday(anchor + ONE_DAY if evening else anchor, tags)
    blocked = cal.next_workday(data_date, tags) < earliest or (not ready and lag >= 0)
    if not blocked:
        return None
    return f"선행 뒤 {lag}일 대기" if ready else reason
