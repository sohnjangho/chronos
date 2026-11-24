"""「관리 포인트」 창(계획 5 Task 11, 시안 B 3주 보드)이 읽는 것 — 읽기만 한다(버전·카드·바깥 찾기를 만들지 않는다).

- history: 보드 칸(window — Data Date 부터 w 주, 마지막 칸 끝 = 포인트 계산의 창 끝), 버전마다 포인트 수와 들어옴·빠짐(까닭)·
  여유 줄어듦(저장한 카드 차이 그대로), 열린 지연의 가정(미리 보기) 줄(열린 지연이 있을 때만 — 주의할 일정과 같은 규칙,
  open_delays 에 그 수), activity 를 주면 그 작업의 버전별 여유(여유 흐름).
  여유는 그 버전에 포인트였으면 저장한 값, 아니면 그 버전 일정(조건 넣고 자원 맞춤)을 계산한 값 — 엔진 값만, 지어내지 않는다.
- accel: points.accel_check 와 같은 계산(tools.points.accel_check.check). 일정은 바뀌지 않는다. 없는 작업 404, 실적이 있으면 409
  (받은 id 를 글에 되풀이하지 않는다), 그 밖의 거절(마일스톤·더 줄일 기간 없음) 422.
권한은 일정 읽기와 같다(로그인한 누구나 — 현장 관리자 포함). 조회·연락 API(app.programs.points)와 같은 경로 아래에 붙는다.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.accel import AccelRefused
from app.core.cpm import ScheduleError
from app.core.points import Point
from app.db import get_session
from app.errors import ApiError
from app.harness.assemble import prepare_stored
from app.points import card
from app.security.deps import current_user
from app.store import points as points_store
from app.store.delays import open_events
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load, run
from app.store.settings import points_config
from app.store.tables import ScheduleVersion
from app.tools.points import accel_check

SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
PREVIEW_NOTE = "열린 지연을 넣은 가정"
NO_ACTIVITY = "작업을 찾을 수 없습니다."
HAS_ACTUALS = "실적이 있는 작업은 당길 수 없습니다."
ACTIVITY_ID_MAX = 64
HISTORY_MAX = 30  # 바뀜 기록에 싣는 최근 버전 수
FLOAT_MAX = 8  # 여유 흐름에 싣는 최근 버전 수(포인트가 아니었던 버전은 그 버전을 계산한다)

board_router = APIRouter(prefix="/api/schedules", tags=["points"], dependencies=[Depends(current_user)])
SessionDep = Annotated[Session, Depends(get_session)]


class AccelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=365)  # 당길 근무일(도구 points.accel_check 와 같은 범위)


def _current(session: Session, schedule_id: int):
    """(지금 일정, 지금 버전). 없는 일정 404."""
    try:
        get_record(session, schedule_id)
        schedule, _, n = load(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None
    return schedule, n


def _window(data_date, weeks: int) -> dict:
    """주 칸 w 개. 마지막 칸 끝 = Data Date + w 주(core.points 의 창 끝 — 그날 시작하는 작업도 포인트)."""
    cols = []
    for i in range(weeks):
        start = data_date + timedelta(weeks=i)
        end = data_date + timedelta(weeks=weeks) if i == weeks - 1 else start + timedelta(days=6)
        cols.append({"start": start.isoformat(), "end": end.isoformat()})
    return {"data_date": data_date.isoformat(), "weeks": cols}


def _entry(version: int, *, saved_at, note: str, points: list[dict] | None, row: card.PointCard | None,
           what_if: bool = False) -> dict:
    data = row.data_json if row is not None else None
    return {
        "version": version, "what_if": what_if, "saved_at": saved_at.isoformat() if saved_at else None, "note": note,
        "recorded": data is not None,  # 카드 차이를 적었는가(처음 계산·이 기능 전 버전이면 False)
        "count": None if points is None else len(points),
        "critical": None if points is None else sum(1 for p in points if p["critical"]),
        "new": list(data["new"]) if data else [], "more": data["more"] if data else 0,
        "tightened": list(data["tightened"]) if data else [], "removed": list(data["removed"]) if data else [],
    }


def _float(session: Session, schedule_id: int, activity_id: str, versions: list[int],
           stored: dict[int, tuple[Point, ...]]) -> list[dict]:
    out = []
    for v in sorted(versions):
        hit = next((p for p in stored.get(v, ()) if p.activity_id == activity_id), None)
        if hit is not None:
            out.append({"version": v, "tf": hit.tf, "critical": hit.critical, "point": True})
            continue
        tf = critical = None
        try:
            schedule, conditions, _ = load(session, schedule_id, v)
            row = run(prepare_stored(schedule, conditions)).rows.get(activity_id)
        except (NotFound, ScheduleError):
            row = None
        if row is not None:
            tf, critical = row.tf, row.critical
        out.append({"version": v, "tf": tf, "critical": critical, "point": False})
    return out


def history(session: Session, schedule_id: int, activity: str | None = None) -> dict:
    schedule, n = _current(session, schedule_id)
    cfg = points_config(session)
    stored = points_store.by_version(session, schedule_id)
    rows = {r.version: r for r in session.scalars(select(card.PointCard).where(
        card.PointCard.schedule_id == schedule_id, card.PointCard.what_if.is_(False)))}
    metas = session.execute(
        select(ScheduleVersion.n, ScheduleVersion.created_at, ScheduleVersion.note)
        .where(ScheduleVersion.schedule_id == schedule_id).order_by(ScheduleVersion.n.desc()).limit(HISTORY_MAX)
    ).all()
    versions = []
    for v, at, note in metas:
        points = stored.get(v)
        versions.append(_entry(v, saved_at=at, note=note or "", row=rows.get(v),
                               points=None if points is None else [card.point_json(p) for p in points]))
    open_delays = len(open_events(session, schedule_id))
    guess = card.get(session, schedule_id, n, what_if=True) if open_delays else None  # 주의할 일정과 같은 규칙
    preview = None if guess is None else _entry(n, saved_at=guess.updated_at, note=PREVIEW_NOTE, row=guess,
                                                points=list(guess.points_json), what_if=True)
    return {
        "schedule_id": schedule_id, "version": n,
        "basis": {"tf_days": cfg.tf_days, "window_weeks": cfg.window_weeks},
        "window": _window(schedule.data_date or schedule.start, cfg.window_weeks),
        "versions": versions, "preview": preview, "open_delays": open_delays,
        "float": None if activity is None else _float(session, schedule_id, activity,
                                                      [m[0] for m in metas[:FLOAT_MAX]], stored),
    }


def accel(session: Session, schedule_id: int, activity_id: str, days: int) -> dict:
    schedule, _ = _current(session, schedule_id)
    act = next((a for a in schedule.activities if a.id == activity_id), None)
    if act is None:  # 받은 id 를 글에 되풀이하지 않는다
        raise ApiError(404, "not_found", NO_ACTIVITY)
    if act.actual_start is not None or act.actual_finish is not None:
        raise ApiError(409, "has_actuals", HAS_ACTUALS)
    try:
        out = accel_check.check(session, schedule_id, activity_id, days)
    except AccelRefused as e:
        raise ApiError(422, "accel_refused", str(e)) from None
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None
    return out.model_dump(mode="json")


@board_router.get("/{schedule_id}/points/history")
def get_history(schedule_id: int, session: SessionDep, activity: Annotated[str | None, Query(max_length=50)] = None
                ) -> dict:
    """보드 칸·버전별 바뀜 기록·가정 줄, activity 를 주면 그 작업의 버전별 여유."""
    return history(session, schedule_id, activity)


@board_router.post("/{schedule_id}/points/{activity_id}/accel")
def post_accel(schedule_id: int, activity_id: Annotated[str, Path(max_length=ACTIVITY_ID_MAX)], body: AccelIn,
               session: SessionDep) -> dict:
    """「당겨도 소용 있나」 — 도구 points.accel_check 와 같은 계산(읽기)."""
    return accel(session, schedule_id, activity_id, body.days)
