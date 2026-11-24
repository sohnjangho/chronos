"""관리 포인트 계산·저장·차이. 버전을 만들 때(store.schedules.create_schedule·store.versions._save) 부르고, 지연 분석
(programs.delays.service)은 버전을 만들지 않으므로 열린 사건을 넣은 「가정」 포인트(`what_if`)만 계산한다(저장 안 함).

계산은 그 버전 일정에 그 버전의 조건을 넣고 자원 맞춤까지 한 값(`run(prepare_stored(...))` = 지연 분석의 `level(...).cpm`).
앞 버전 포인트는 저장한 것을 쓰고, 없으면(이 기능 전 버전) 지금 설정으로 계산해 같이 둔다.
앞 버전이 없거나 계산되지 않으면 차이는 None(「처음 계산」 — 카드를 내지 않는다).
"""

import logging

from sqlalchemy.orm import Session

from app.core.cpm import CpmResult, ScheduleError
from app.core.delay import DelayAnalysis
from app.core.model import Schedule
from app.core.points import Point, PointsDiff, compute_points, diff_points
from app.harness.assemble import prepare_stored
from app.points import card
from app.store import delays as delays_store
from app.store import points as points_store
from app.store.schedules import NotFound, end_write, load, run
from app.store.settings import points_config

logger = logging.getLogger(__name__)


def _state(session: Session, schedule_id: int, version: int, computed: CpmResult | None = None
           ) -> tuple[Schedule, CpmResult]:
    """(조건 넣은 일정, 맞춘 CPM). computed 를 주면 다시 계산하지 않는다. NotFound·ScheduleError 는 그대로."""
    schedule, conditions, _ = load(session, schedule_id, version)
    ready = prepare_stored(schedule, conditions)
    return ready, computed if computed is not None else run(ready)


def _points(session: Session, ready: Schedule, cpm: CpmResult) -> tuple[Point, ...]:
    cfg = points_config(session)
    return compute_points(ready, cpm, tf_days=cfg.tf_days, window_weeks=cfg.window_weeks)


def _tf(cpm: CpmResult) -> dict[str, int]:
    return {i: row.tf for i, row in cpm.rows.items()}


def _previous(session: Session, schedule_id: int, version: int) -> tuple[tuple[Point, ...] | None, dict[str, int]]:
    """(앞 버전 포인트, 앞 버전 CPM 여유). 저장한 포인트가 있으면 그것을, 없으면 계산해 둔다. 앞 버전이 없거나
    계산되지 않으면 (None, {})."""
    if version <= 1:
        return None, {}
    try:
        ready, cpm = _state(session, schedule_id, version - 1)
    except (NotFound, ScheduleError):
        return None, {}
    stored = points_store.get(session, schedule_id, version - 1)
    if stored is None:
        stored = _points(session, ready, cpm)
        points_store.put(session, schedule_id, version - 1, stored)
    return stored, _tf(cpm)


def refresh(session: Session, schedule_id: int, version: int, *, computed: CpmResult | None = None
            ) -> PointsDiff | None:
    """그 버전의 포인트를 계산해 표에 두고(덮어씀) 앞 버전과의 차이를 돌려준다. flush·commit 은 부른 쪽.

    computed = 그 버전의 run(일정, 조건) 결과(있으면 다시 맞추지 않는다). 없는 버전이면 NotFound, 계산이 안 되는
    일정이면 ScheduleError(아무것도 적지 않는다).
    """
    return _refresh(session, schedule_id, version, computed)[0]


def _refresh(session: Session, schedule_id: int, version: int, computed: CpmResult | None
             ) -> tuple[PointsDiff | None, tuple[Point, ...], tuple[Point, ...], Schedule, CpmResult]:
    """refresh 와 같고 (차이, 앞 포인트, 이 버전 포인트, 조건 넣은 일정, 맞춘 CPM) 을 준다(카드가 빠진 까닭을 가른다)."""
    ready, cpm = _state(session, schedule_id, version, computed)
    cur = _points(session, ready, cpm)
    prev, prev_tf = _previous(session, schedule_id, version)
    points_store.put(session, schedule_id, version, cur)
    return diff_points(prev, cur, prev_tf=prev_tf), prev or (), cur, ready, cpm


def refresh_quietly(session: Session, schedule_id: int, version: int, *, commit: bool,
                    computed: CpmResult | None = None) -> PointsDiff | None:
    """버전을 만든 뒤 훅: refresh 와 카드 차이 적기(app.points.card.remember)를 SAVEPOINT 안에서 하고 commit(아니면 flush).
    새 포인트가 있으면 바깥 트랜잭션이 commit 된 뒤 외부 영향 찾기를 띄운다. 실패는 로그 한 줄만 남기고 None —
    SAVEPOINT 만 되돌리므로 부른 쪽의 저장(commit 이 아니면 아직 열린 트랜잭션)을 깨지 않는다.
    (pysqlite 로 확인: 바깥 트랜잭션이 쓰는 중이든 아니든 안쪽만 되돌아간다 — 시험 test_points_service.)
    """
    try:
        with session.begin_nested():
            diff, prev, cur, ready, cpm = _refresh(session, schedule_id, version, computed)
            look = diff is not None and card.remember(
                session, schedule_id, version, what_if=False, diff=diff, points=cur,
                before={p.activity_id: p for p in prev}, ready=ready, cpm=cpm, trigger=card.version_trigger(version))
        if look:  # 외부 영향은 저장이 commit 된 뒤 뒤에서 찾는다(응답을 막지 않는다)
            card.launch_after_commit(session, schedule_id, version, what_if=False)
        end_write(session, commit)
        return diff
    except Exception as e:  # 어떤 실패도 저장을 막지 않는다
        if commit:  # 부른 쪽의 쓰기는 이미 commit 됨 — 깨진 세션만 정리
            session.rollback()
        logger.warning("관리 포인트 계산 실패: 일정 %s 버전 %s (%s)", schedule_id, version, type(e).__name__)
        logger.debug("관리 포인트 계산 실패 자세히", exc_info=True)
        return None


def what_if(session: Session, schedule_id: int, analysis: DelayAnalysis | None = None
            ) -> tuple[tuple[Point, ...], PointsDiff]:
    """열린 지연 사건을 넣은 일정(지연 분석의 마지막 상태)의 포인트와, 지금 버전 포인트(저장한 것, 없으면 계산)와의 차이.

    저장하지 않는다(버전이 아니다). analysis = 방금 한 `store.delays` 분석(있으면 다시 분석·맞춤을 하지 않는다).
    없는 일정이면 NotFound, 깨진 일정이면 ScheduleError.
    """
    if analysis is None:
        analysis, _, _ = delays_store.analyze_open(session, schedule_id)
    n = load(session, schedule_id)[2]
    base = points_store.get(session, schedule_id, n)
    if base is None:
        base = _points(session, *_state(session, schedule_id, n, analysis.base_cpm))
    points = _points(session, analysis.final_schedule, analysis.final_cpm)
    diff = diff_points(base, points, prev_tf=_tf(analysis.base_cpm))
    assert diff is not None  # base 는 None 이 아니다
    return points, diff


def remember_what_if(session: Session, schedule_id: int, analysis: DelayAnalysis | None = None
                     ) -> tuple[tuple[Point, ...], PointsDiff, int, bool]:
    """what_if 를 계산해 카드 차이(what_if 줄, 지금 버전 n)를 적는다(flush 만). → (포인트, 차이, n, 뒤에서 외부 영향을
    찾아야 하는가 — 부른 쪽이 commit 한 뒤 card.launch(…, n, what_if=True)). NotFound·ScheduleError 는 그대로."""
    if analysis is None:
        analysis, _, _ = delays_store.analyze_open(session, schedule_id)
    points, diff = what_if(session, schedule_id, analysis)
    n = load(session, schedule_id)[2]
    base = points_store.get(session, schedule_id, n) or ()
    events = delays_store.open_events(session, schedule_id)
    names = {a.id: a.name for a in analysis.final_schedule.activities}
    last = max(events, key=lambda e: e.id, default=None)
    trigger = {"kind": "delay", "version": n, "delay_ids": sorted(e.id for e in events),
               "latest": None if last is None else {"id": last.id, "activity_id": last.activity_id,
                                                    "name": names.get(last.activity_id, last.activity_id),
                                                    "days": last.days}}
    look = card.remember(session, schedule_id, n, what_if=True, diff=diff, points=points,
                         before={p.activity_id: p for p in base}, ready=analysis.final_schedule, cpm=analysis.final_cpm,
                         trigger=trigger)
    return points, diff, n, look
