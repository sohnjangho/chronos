"""관리 포인트(계획 5 A): 끝나지 않은 task 가운데 크리티컬이거나 전체 여유(TF)가 k 근무일 이하이고,
Data Date(없으면 일정 시작)부터 w 주(달력 주 — 근무일이 아니다) 안에 시작하는 것. 진행 중인 것(ES 가 Data Date 앞)도 넣는다.

날짜·여유는 받은 CPM 행 그대로 쓴다(부르는 쪽이 지연 분석과 같은 맞춘 값 `level(...).cpm` 을 준다). 판단은 없다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.cpm import CpmResult
from app.core.model import Schedule


@dataclass(frozen=True)
class Point:
    activity_id: str
    name: str
    critical: bool
    tf: int
    es: date
    ef: date


@dataclass(frozen=True)
class PointsDiff:
    added: tuple[Point, ...]  # 새로 들어온 포인트(뒤 버전 차례)
    removed: tuple[str, ...]  # 빠진 포인트 id(앞 버전 차례)
    tightened: tuple[tuple[str, int, int], ...]  # (id, 앞 tf, 뒤 tf) — 두 버전 모두 포인트이고 여유가 줄어든 것
    became_critical: tuple[str, ...] = ()  # 두 버전 모두 포인트이고 크리티컬이 아니었다가 크리티컬이 된 것(뒤 차례)
    # added·became_critical·tightened id 의 앞 상태 여유(앞에 포인트가 아니었으면 앞 상태 CPM 에서, 모르면 빠짐)
    before_tf: dict[str, int] = field(default_factory=dict)


def compute_points(schedule: Schedule, cpm: CpmResult, *, tf_days: int, window_weeks: int) -> tuple[Point, ...]:
    """ES 순(같으면 일정 차례)."""
    edge = (schedule.data_date or schedule.start) + timedelta(weeks=window_weeks)
    out = []
    for a in schedule.activities:
        row = cpm.rows.get(a.id)
        if row is None or a.kind != "task" or a.actual_finish is not None:
            continue
        if (row.critical or row.tf <= tf_days) and row.es <= edge:
            out.append(Point(a.id, a.name, row.critical, row.tf, row.es, row.ef))
    return tuple(sorted(out, key=lambda p: p.es))


def diff_points(
    prev: tuple[Point, ...] | None, cur: tuple[Point, ...], *, prev_tf: Mapping[str, int] | None = None
) -> PointsDiff | None:
    """앞 버전이 없으면(처음 계산) None. prev_tf = 앞 상태 CPM 의 모든 액티비티 여유(before_tf 를 채우는 데만 쓴다)."""
    if prev is None:
        return None
    before = {p.activity_id: p for p in prev}
    now = {p.activity_id for p in cur}
    added = tuple(p for p in cur if p.activity_id not in before)
    became = tuple(p.activity_id for p in cur
                   if p.activity_id in before and p.critical and not before[p.activity_id].critical)
    tightened = tuple((p.activity_id, before[p.activity_id].tf, p.tf)
                      for p in cur if p.activity_id in before and p.tf < before[p.activity_id].tf)
    known = {**(prev_tf or {}), **{i: p.tf for i, p in before.items()}}
    ids = [p.activity_id for p in added] + list(became) + [t[0] for t in tightened]
    return PointsDiff(
        added=added,
        removed=tuple(p.activity_id for p in prev if p.activity_id not in now),
        tightened=tightened,
        became_critical=became,
        before_tf={i: known[i] for i in ids if i in known},
    )
