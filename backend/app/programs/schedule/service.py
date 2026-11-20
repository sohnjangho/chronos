"""일정 읽기·고치기·버전.

고칠 때마다: 지금 버전 확인(409) → 고침 적용 → 계산 확인(저장된 조건을 넣어, 422, 저장 안 함) → 새 버전 저장.
바뀐 것이 없으면 버전을 만들지 않고 지금 일정을 돌려준다. 계획 칸(기간·관계·제약·이름·종류·WBS·자원·꼬리표)을
고치면 계획 변경(Plan 을 새로 찍음), 실적 칸·진도·남은 기간·Data Date·가중치만 고치면 앞 Plan 을 물려받는다
(store.view.plan_changed, PM 결정 11-20 밤).
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.errors import ApiError
from app.programs.schedule import edits
from app.programs.schedule.edits import Edit
from app.programs.schedule.schemas import (
    ActivityCreate,
    ActivityPatch,
    PredecessorsIn,
    ScheduleItem,
    SchedulePatch,
    ScheduleView,
    VersionOut,
    WeightModeIO,
)
from app.programs.schedule.view import build_view
from app.store.messages import SCHEDULE_ERROR_MESSAGES
from app.store.schedules import NotFound, get_record, get_version, list_records, load
from app.store.tables import User
from app.store.versions import VersionConflict, list_versions, restore, save_new_version
from app.store.view import plan_changed, run

CONFLICT_MESSAGE = "그 사이 일정이 바뀌었습니다. 다시 불러와 주세요."


def _invalid(e: ScheduleError) -> ApiError:
    return ApiError(422, "schedule_invalid", SCHEDULE_ERROR_MESSAGES[e.code], e.detail)


def _conflict(current: int) -> ApiError:
    return ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": current})


def _check_schedule(session: Session, schedule_id: int) -> None:
    try:
        get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None


def get_view(
    session: Session, schedule_id: int, computed: tuple[int, CpmResult] | None = None
) -> ScheduleView:
    _check_schedule(session, schedule_id)
    try:
        return build_view(session, schedule_id, computed)
    except ScheduleError as e:
        raise _invalid(e) from None


def list_schedules(session: Session) -> list[ScheduleItem]:
    """일정 목록. finish 는 화면과 같은 계산값(깨진 일정이면 None)."""
    items = []
    for rec in list_records(session):
        schedule, conditions, n = load(session, rec.id)
        try:
            finish = run(schedule, conditions).finish
        except ScheduleError:
            finish = None
        items.append(
            ScheduleItem(
                id=rec.id,
                name=rec.name,
                domain=rec.domain,
                level=rec.level,
                version=n,
                finish=finish,
                updated_at=get_version(session, rec.id, n).created_at,
            )
        )
    return items


def versions(session: Session, schedule_id: int) -> list[VersionOut]:
    _check_schedule(session, schedule_id)
    return [
        VersionOut(
            n=v.n,
            note=v.note,
            by_kind=v.by_kind,
            by_name=v.by_name,
            is_plan=v.is_plan,
            created_at=v.created_at,
        )
        for v in list_versions(session, schedule_id)
    ]


def _write(
    session: Session,
    schedule_id: int,
    base_version: int,
    user: User,
    edit: Callable[[Schedule], Edit],
) -> ScheduleView:
    _check_schedule(session, schedule_id)
    schedule, conditions, n = load(session, schedule_id)
    if base_version != n:
        raise _conflict(n)
    result = edit(schedule)
    if not result.changes:
        return get_view(session, schedule_id)
    try:
        cpm = run(result.schedule, conditions)  # 저장할 조건을 넣어 확인(화면과 같은 계산)
    except ScheduleError as e:
        raise _invalid(e) from None
    try:
        saved = save_new_version(
            session,
            schedule_id,
            result.schedule,
            conditions,
            by_kind="user",
            by_name=user.name,
            note=result.note,
            changes=result.changes,
            base_version=base_version,
            plan_change=plan_changed(schedule, result.schedule),
            computed=cpm,
        )
    except VersionConflict as e:
        raise _conflict(e.current) from None
    return get_view(session, schedule_id, (saved, cpm))


def patch_activity(
    session: Session, schedule_id: int, aid: str, body: ActivityPatch, user: User
) -> ScheduleView:
    fields = body.model_dump(mode="json", exclude_unset=True, exclude={"base_version"})
    return _write(
        session, schedule_id, body.base_version, user,
        lambda s: edits.patch_activity(s, aid, fields),
    )


def add_activity(
    session: Session, schedule_id: int, body: ActivityCreate, user: User
) -> ScheduleView:
    return _write(
        session, schedule_id, body.base_version, user, lambda s: edits.add_activity(s, body)
    )


def delete_activity(
    session: Session, schedule_id: int, aid: str, base_version: int, user: User
) -> ScheduleView:
    return _write(
        session, schedule_id, base_version, user, lambda s: edits.delete_activity(s, aid)
    )


def set_predecessors(
    session: Session, schedule_id: int, aid: str, body: PredecessorsIn, user: User
) -> ScheduleView:
    return _write(
        session, schedule_id, body.base_version, user,
        lambda s: edits.set_predecessors(s, aid, body.items),
    )


def patch_schedule(session: Session, schedule_id: int, body: SchedulePatch, user: User) -> ScheduleView:
    """일정 칸(Data Date) 고치기. 확인 차례와 오류는 액티비티 고치기와 같다."""
    return _write(
        session, schedule_id, body.base_version, user, lambda s: edits.set_data_date(s, body.data_date)
    )


def set_weight_mode(session: Session, schedule_id: int, body: WeightModeIO) -> WeightModeIO:
    """가중치 방식 바꾸기. 버전을 만들지 않는다(일정 내용이 아니라 보는 방식)."""
    _check_schedule(session, schedule_id)
    get_record(session, schedule_id).weight_mode = body.mode
    session.commit()
    return WeightModeIO(mode=body.mode)


def restore_version(
    session: Session, schedule_id: int, n: int, base_version: int, user: User
) -> ScheduleView:
    _check_schedule(session, schedule_id)
    try:
        restore(session, schedule_id, n, by_name=user.name, base_version=base_version)
    except NotFound:
        raise ApiError(404, "not_found", "버전을 찾을 수 없습니다.") from None
    except ScheduleError as e:
        raise _invalid(e) from None
    except VersionConflict as e:
        raise _conflict(e.current) from None
    return get_view(session, schedule_id)
