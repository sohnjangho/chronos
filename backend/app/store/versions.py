"""새 버전 쌓기·되돌리기·버전 목록.

버전은 지우지 않는다. 새 버전을 만들 때 받은 base_version 이 지금 버전인지 확인하고
지금 버전 번호를 올리는 일을 한 UPDATE 문으로 한다(같은 base 로 두 번 저장하면 하나만 된다).
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.model import Schedule
from app.store.schedules import get_record, load, to_json
from app.store.tables import ChangeLog, ScheduleRecord, ScheduleVersion


class VersionConflict(Exception):
    """받은 base_version 이 지금 버전이 아니다."""

    def __init__(self, current: int) -> None:
        super().__init__(current)
        self.current = current


def save_new_version(
    session: Session,
    schedule_id: int,
    schedule: Schedule,
    conditions: list[dict],
    *,
    by_kind: str,
    by_name: str,
    note: str,
    changes: list[dict],
    base_version: int,
) -> int:
    """base_version 다음 번호로 새 버전과 변경 이력 한 줄을 저장하고 그 번호를 준다."""
    get_record(session, schedule_id)  # 없는 일정이면 NotFound
    n = base_version + 1
    bumped = session.execute(
        update(ScheduleRecord)
        .where(ScheduleRecord.id == schedule_id, ScheduleRecord.current_version == base_version)
        .values(current_version=n)
        .execution_options(synchronize_session=False)
    )
    if bumped.rowcount != 1:
        session.rollback()
        raise VersionConflict(get_record(session, schedule_id).current_version)
    session.add(
        ScheduleVersion(
            schedule_id=schedule_id,
            n=n,
            snapshot_json=to_json(schedule),
            conditions_json=list(conditions),
            note=note,
            by_kind=by_kind,
            by_name=by_name,
        )
    )
    session.add(
        ChangeLog(
            schedule_id=schedule_id,
            version_n=n,
            by_kind=by_kind,
            by_name=by_name,
            summary=note,
            changes_json=list(changes),
        )
    )
    session.commit()
    return n


def restore(
    session: Session,
    schedule_id: int,
    n: int,
    *,
    by_name: str,
    base_version: int | None = None,
) -> int:
    """n번 버전의 내용(일정·조건)을 새 버전으로 만든다. 이력은 지우지 않는다.

    base_version 을 주면 그것이 지금 버전인지 확인한다(없으면 지금 버전 위에 쌓는다).
    """
    schedule, conditions, _ = load(session, schedule_id, n)
    base = base_version
    if base is None:
        base = get_record(session, schedule_id).current_version
    return save_new_version(
        session,
        schedule_id,
        schedule,
        conditions,
        by_kind="user",
        by_name=by_name,
        note=f"{n}번 버전으로 되돌림",
        changes=[],
        base_version=base,
    )


def list_versions(session: Session, schedule_id: int) -> list[ScheduleVersion]:
    """버전 목록, 새것부터. 없는 일정이면 NotFound."""
    get_record(session, schedule_id)
    return list(
        session.scalars(
            select(ScheduleVersion)
            .where(ScheduleVersion.schedule_id == schedule_id)
            .order_by(ScheduleVersion.n.desc())
        )
    )

