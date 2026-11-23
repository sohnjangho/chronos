"""탐색기: 볼 수 있는 일정 목록과 관리자의 일정 지우기.

일정은 로그인한 누구나 본다(일정 API 와 같음). 지우기는 일정·모든 버전·변경 이력과 그 일정의 주소록·연락 기록
(store.outreach.purge_schedule — 일정 id 가 다시 쓰여도 새 일정에 나타나지 않게)을 한 트랜잭션에 지운다.
그 일정의 승인 대기 건은 더 반영할 곳이 없으므로 conflict 로 닫는다(승인하면 없는 일정에 쓰게 되므로).
"""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.errors import ApiError
from app.programs.explorer.schemas import DeletedOut, TreeOut, TreeSchedule
from app.store.outreach import purge_schedule
from app.store.schedules import (
    NotFound,
    get_record,
    get_version,
    list_records,
    load,
    run,
)
from app.store.tables import Approval, ChangeLog, ScheduleRecord, ScheduleVersion, User

DELETED_NOTE = "일정을 지웠습니다."


def tree(session: Session) -> TreeOut:
    items = []
    for rec in list_records(session):
        schedule, conditions, n = load(session, rec.id)
        try:
            finish = run(schedule, conditions).finish
        except ScheduleError:
            finish = None
        items.append(TreeSchedule(id=rec.id, name=rec.name, domain=rec.domain, level=rec.level, version=n,
                                  finish=finish, updated_at=get_version(session, rec.id, n).created_at))
    return TreeOut(schedules=items)


def _close_pending(session: Session, schedule_id: int, user: User) -> None:
    rows = session.scalars(select(Approval).where(Approval.schedule_id == schedule_id, Approval.status == "pending"))
    now = datetime.now(UTC)
    for row in rows:
        row.status, row.decided_by, row.decided_at, row.note = "conflict", user.name, now, DELETED_NOTE


def delete_schedule(session: Session, schedule_id: int, user: User) -> DeletedOut:
    try:
        get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None
    _close_pending(session, schedule_id, user)
    session.execute(delete(ChangeLog).where(ChangeLog.schedule_id == schedule_id))
    session.execute(delete(ScheduleVersion).where(ScheduleVersion.schedule_id == schedule_id))
    session.execute(delete(ScheduleRecord).where(ScheduleRecord.id == schedule_id))
    purge_schedule(session, schedule_id)
    session.commit()
    return DeletedOut(deleted=schedule_id)
