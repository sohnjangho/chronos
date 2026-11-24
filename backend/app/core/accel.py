"""당김 효과(계획 5 F, 「당겨도 소용 있나」): 이동 묶음이 당긴 일수 가운데 준공에 반영된 일수와, 넣은 뒤 약속을 정하는 줄.

계산은 기존 엔진만 쓴다 — `apply_moves` → `compute` → `level(shift=True)` 로 넣기 전·뒤 준공을 구한다. 판단은 없다.

당긴 일수(pulled_days) = 묶음의 이동마다 센 일수의 합
- compress: 받은 일정의 od − 새 od.
- parallel: 넣기 전 크리티컬 사슬에서 그 관계가 후행을 당기는 일수 = 선행 od − SS lag
  (FS 0 이면 후행은 선행이 끝난 뒤, SS+lag 면 선행 시작 lag 일 뒤에 시작한다).
- add_resource: 0 으로 센다(기간을 줄이지 않는다). 이 이동만 있는 묶음은 finish_gain 만 본다 —
  ratio 는 준공이 당겨지면 1.0, 아니면 0.0.
반영 일수(finish_gain) = 넣기 전 준공 → 넣은 뒤 준공의 근무일(받은 일정의 달력, 단축안의 이득과 같은 셈).
ratio = finish_gain / pulled_days, warn = ratio < warn_ratio(같으면 경고하지 않는다).

다음 결정 줄(next_chain) = 넣은 뒤 맞춘 일정의 크리티컬 패스(위상 순) 가운데 묶음이 건드리지 않은 task(끝난 것 제외).
same_chain = 넣기 전 크리티컬 패스에 같은 규칙을 쓴 줄과 같다(같은 줄이 계속 약속을 정한다).
next_chain_points = 그 가운데 넣은 뒤 일정의 관리 포인트(`compute_points`)인 것.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.model import Schedule
from app.core.points import compute_points
from app.core.resources import LevelResult, level
from app.core.shorten import Move, apply_moves


class AccelRefused(ValueError):
    """당길 수 없는 요청(없는 작업·마일스톤·실적 있음·더 줄일 기간 없음). 메시지는 사용자에게 그대로 보인다."""


@dataclass(frozen=True)
class AccelResult:
    pulled_days: int
    finish_before: date
    finish_after: date
    finish_gain: int
    ratio: float
    warn: bool
    next_chain: tuple[str, ...]  # 액티비티 id, 위상 순
    next_chain_points: tuple[str, ...]  # next_chain 가운데 관리 포인트(같은 차례)
    same_chain: bool


def pull_request(schedule: Schedule, activity_id: str, days: int) -> Sequence[Move]:
    """「〔작업〕을 days 일 당기면?」 — 그 작업 od 를 days 만큼 줄이는 압축 하나(최소 1, 관계는 그대로)."""
    a = next((a for a in schedule.activities if a.id == activity_id), None)
    if a is None:
        raise AccelRefused(f"작업을 찾을 수 없습니다: {activity_id}")
    if a.kind != "task":
        raise AccelRefused(f"{a.name} 은(는) 마일스톤이라 당길 기간이 없습니다.")
    if a.actual_start is not None or a.actual_finish is not None:
        raise AccelRefused(f"{a.name} 은(는) 실적이 있어 당길 수 없습니다.")
    if a.od <= 1:
        raise AccelRefused(f"{a.name} 은(는) 기간이 {a.od}일이라 더 줄일 수 없습니다.")
    od = max(1, a.od - days)
    return (Move(f"cmp:{a.id}", "compress", (a.id,), f"{a.name} 기간 {a.od}일 → {od}일", od=od),)


def _pulled(schedule: Schedule, moves: Sequence[Move]) -> int:
    ods = {a.id: a.od for a in schedule.activities}
    total = 0
    for m in moves:
        if m.kind == "compress":
            total += ods[m.activity_ids[0]] - m.od
        elif m.kind == "parallel":
            total += ods[m.relation.pred] - m.relation.lag
    return total


def _chain(schedule: Schedule, lv: LevelResult, touched: set[str]) -> tuple[str, ...]:
    acts = {a.id: a for a in schedule.activities}
    return tuple(i for i in lv.cpm.critical_path
                 if i not in touched and acts[i].kind == "task" and acts[i].actual_finish is None)


def accel_effect(
    schedule: Schedule, moves: Sequence[Move], *, warn_ratio: float, tf_days: int, window_weeks: int
) -> AccelResult:
    """schedule(조건을 넣은 일정)에 moves 를 넣기 전·뒤를 맞춰 견준다. tf_days·window_weeks 는 관리 포인트 설정값."""
    before = level(schedule, compute(schedule), shift=True)
    after_schedule = apply_moves(schedule, moves)
    after = level(after_schedule, compute(after_schedule), shift=True)
    gain = WorkCalendar(schedule.calendar).workdays_between(after.finish, before.finish)
    pulled = _pulled(schedule, moves)
    ratio = gain / pulled if pulled > 0 else (1.0 if gain > 0 else 0.0)
    touched = {i for m in moves for i in m.activity_ids}
    chain = _chain(after_schedule, after, touched)
    points = {p.activity_id for p in compute_points(after_schedule, after.cpm, tf_days=tf_days,
                                                    window_weeks=window_weeks)}
    return AccelResult(
        pulled_days=pulled, finish_before=before.finish, finish_after=after.finish, finish_gain=gain,
        ratio=ratio, warn=ratio < warn_ratio, next_chain=chain,
        next_chain_points=tuple(i for i in chain if i in points),
        same_chain=chain == _chain(schedule, before, touched),
    )
