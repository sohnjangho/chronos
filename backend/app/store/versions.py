"""새 버전 쌓기·되돌리기·버전 목록.

버전은 지우지 않는다. 새 버전을 만들 때 받은 base_version 이 지금 버전인지 확인하고
지금 버전 번호를 올리는 일을 한 UPDATE 문으로 한다(같은 base 로 두 번 저장하면 하나만 된다).

쓰는 함수는 모두 `commit: bool = True` 를 받는다. False 면 flush 만 하고 커밋하지 않으며,
충돌이 나도 세션을 되돌리지 않는다(부른 쪽이 같은 트랜잭션에서 다른 행을 더 쓰고 끝낸다).
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.model import Schedule
from app.store.diff import schedule_changes
from app.store.schedules import end_write, get_record, get_version, load, run, to_json
from app.store.tables import ChangeLog, ScheduleRecord, ScheduleVersion


class VersionConflict(Exception):
    """받은 base_version 이 지금 버전이 아니다."""

    def __init__(self, current: int) -> None:
        super().__init__(current)
        self.current = current


def _current_in_db(session: Session, schedule_id: int) -> int:
    """세션에 든 객체가 아니라 DB 의 지금 버전 번호."""
    return session.scalar(
        select(ScheduleRecord.current_version).where(ScheduleRecord.id == schedule_id)
    )


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
    commit: bool = True,
) -> int:
    """base_version+1 번 버전과 변경 이력 한 줄을 저장한다. 계산 확인은 부르는 쪽이 한다."""
    get_record(session, schedule_id)  # 없는 일정이면 NotFound
    n = base_version + 1
    bumped = session.execute(
        update(ScheduleRecord)
        .where(ScheduleRecord.id == schedule_id, ScheduleRecord.current_version == base_version)
        .values(current_version=n)
    )
    if bumped.rowcount != 1:
        current = _current_in_db(session, schedule_id)
        if commit:
            session.rollback()
        raise VersionConflict(current)
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
    end_write(session, commit)
    return n


def restore(
    session: Session,
    schedule_id: int,
    n: int,
    *,
    by_name: str,
    base_version: int | None = None,
    commit: bool = True,
) -> int:
    """n번 버전의 내용(일정·조건)을 새 버전으로 만든다. 이력은 지우지 않는다.

    base_version 을 주면 그것이 지금 버전인지 확인한다(없으면 지금 버전 위에 쌓는다).
    n번 일정이 계산되지 않으면 ScheduleError 를 내고 아무것도 저장하지 않는다.
    변경 이력에는 지금 버전 → n번 내용의 차이를 적는다.
    """
    schedule, conditions, _ = load(session, schedule_id, n)
    current, _, current_n = load(session, schedule_id)
    base = current_n if base_version is None else base_version
    if base != current_n:
        raise VersionConflict(current_n)
    run(schedule)
    return save_new_version(
        session,
        schedule_id,
        schedule,
        conditions,
        by_kind="user",
        by_name=by_name,
        note=f"{n}번 버전으로 되돌림",
        changes=schedule_changes(current, schedule),
        base_version=base,
        commit=commit,
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



def mark_plan(session: Session, schedule_id: int, n: int, *, commit: bool = True) -> None:
    """n번 버전만 Plan 으로 둔다(같은 일정의 다른 버전은 is_plan False). 없는 버전이면 NotFound."""
    get_version(session, schedule_id, n)
    for v in session.scalars(
        select(ScheduleVersion).where(ScheduleVersion.schedule_id == schedule_id)
    ):
        v.is_plan = v.n == n
    end_write(session, commit)
