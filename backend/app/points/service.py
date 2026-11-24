"""관리 포인트 계산·저장·차이. 버전 저장(store.versions._save)과 지연 분석(programs.delays.service) 뒤에 부른다.

계산은 그 버전 일정에 그 버전의 조건을 넣고 자원 맞춤까지 한 값(`run(prepare_stored(...))` = 지연 분석의 `level(...).cpm`).
앞 버전 포인트는 저장한 것을 쓰고, 없으면(이 기능 전 버전·첫 버전이 저장 뒤 계산되지 않음) 지금 설정으로 계산해 같이 둔다.
앞 버전이 없거나 계산되지 않으면 차이는 None(「처음 계산」 — 카드를 내지 않는다).
"""

import logging

from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.core.points import Point, PointsDiff, compute_points, diff_points
from app.harness.assemble import prepare_stored
from app.store import points as points_store
from app.store.schedules import NotFound, end_write, load, run
from app.store.settings import points_config

logger = logging.getLogger(__name__)


def _compute(session: Session, schedule_id: int, version: int) -> tuple[Point, ...]:
    """없는 버전이면 NotFound, 계산이 안 되면 ScheduleError."""
    schedule, conditions, _ = load(session, schedule_id, version)
    ready = prepare_stored(schedule, conditions)
    cfg = points_config(session)
    return compute_points(ready, run(ready), tf_days=cfg.tf_days, window_weeks=cfg.window_weeks)


def _previous(session: Session, schedule_id: int, version: int) -> tuple[Point, ...] | None:
    if version <= 1:
        return None
    stored = points_store.get(session, schedule_id, version - 1)
    if stored is not None:
        return stored
    try:
        prev = _compute(session, schedule_id, version - 1)
    except (NotFound, ScheduleError):
        return None
    points_store.put(session, schedule_id, version - 1, prev)
    return prev


def refresh(session: Session, schedule_id: int, version: int) -> PointsDiff | None:
    """그 버전의 포인트를 계산해 표에 두고(덮어씀) 앞 버전과의 차이를 돌려준다. flush·commit 은 부른 쪽.

    없는 버전이면 NotFound, 계산이 안 되는 일정이면 ScheduleError(아무것도 적지 않는다).
    """
    cur = _compute(session, schedule_id, version)
    prev = _previous(session, schedule_id, version)
    points_store.put(session, schedule_id, version, cur)
    return diff_points(prev, cur)


def refresh_quietly(session: Session, schedule_id: int, version: int, *, commit: bool) -> PointsDiff | None:
    """저장·분석 뒤 훅: refresh 하고 commit(아니면 flush). 실패는 로그 한 줄만 남기고 None — 부른 쪽의 저장을 깨지 않는다.

    commit 이면 실패 때 되돌린다(부른 쪽의 쓰기는 이미 commit 됨). commit 이 아니면 refresh 가 계산을 다 끝낸 뒤에만
    줄을 더하므로 계산 실패는 세션에 아무것도 남기지 않는다.
    """
    try:
        diff = refresh(session, schedule_id, version)
        end_write(session, commit)
        return diff
    except Exception as e:  # noqa: BLE001 — 어떤 실패도 저장을 막지 않는다
        if commit:
            session.rollback()
        logger.warning("관리 포인트 계산 실패: 일정 %s 버전 %s (%s)", schedule_id, version, type(e).__name__)
        return None
