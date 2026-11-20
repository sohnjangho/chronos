"""새 버전 쌓기·되돌리기·버전 목록.

버전은 지우지 않는다. 새 버전을 만들 때 받은 base_version 이 지금 버전인지 확인하고
지금 버전 번호를 올리는 일을 한 UPDATE 문으로 한다(같은 base 로 두 번 저장하면 하나만 된다).

쓰는 함수는 모두 `commit: bool = True` 를 받는다. False 면 flush 만 하고 커밋하지 않으며,
충돌이 나도 세션을 되돌리지 않는다(부른 쪽이 같은 트랜잭션에서 다른 행을 더 쓰고 끝낸다).

Plan(PM 결정 11-20 밤): 버전마다 plan_json 을 둔다. 새 버전을 만드는 쪽이 계획 변경인지(plan_change) 반드시 정한다
— 계획 변경이면 그 버전의 계산(실적 포함)을 고정하고, 아니면(실적·Data Date·지연 반영안) 앞 버전의 것을 그대로 물려받는다.
되돌리기는 되돌린 버전의 plan_json 을 그대로 가져온다.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.core.model import Schedule
from app.store.diff import schedule_changes
from app.store.schedules import (
    end_write,
    get_record,
    get_version,
    load,
    plan_snapshot,
    run,
    to_json,
)
from app.store.tables import ChangeLog, ScheduleRecord, ScheduleVersion


class VersionConflict(Exception):
    """받은 base_version 이 지금 버전이 아니다."""

    def __init__(self, current: int) -> None:
        super().__init__(current)
        self.current = current


def _fresh_record(session: Session, schedule_id: int) -> ScheduleRecord:
    """세션의 일정 객체. current_version 은 다음에 읽을 때 DB 에서 다시 읽게 해 둔다."""
    record = get_record(session, schedule_id)  # 없는 일정이면 NotFound
    session.expire(record, ["current_version"])
    return record


def _bump(session: Session, schedule_id: int, base_version: int) -> bool:
    """DB 의 지금 버전이 base_version 이면 하나 올리고 True. 세션 객체는 건드리지 않는다.

    "evaluate" 동기화는 DB 에서 0줄이 바뀌어도 낡은 세션 객체를 base+1 로 바꾸므로 끈다.
    부르는 쪽이 _fresh_record 로 값을 만료시켜 DB 값을 다시 읽는다.
    """
    result = session.execute(
        update(ScheduleRecord)
        .where(ScheduleRecord.id == schedule_id, ScheduleRecord.current_version == base_version)
        .values(current_version=base_version + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _plan(session: Session, schedule_id: int, base_version: int, schedule: Schedule, conditions: list[dict],
          plan_change: bool) -> dict | None:
    """새 버전(base_version+1)의 plan_json. 계획 변경이면 그 버전의 계산(실적 포함), 아니면 앞 버전의 것 그대로.

    저장은 계산을 확인하지 않으므로(부르는 쪽이 한다) 계산이 안 되는 일정이면 None(고정할 Plan 없음 — plan_of 가
    예전 방식으로 계산해 보고, 그것도 안 되면 Plan 없음). 없는 base 면 None(_bump 가 충돌을 낸다).
    """
    if plan_change:
        try:
            return plan_snapshot(run(schedule, conditions), base_version + 1)
        except ScheduleError:
            return None
    base = session.get(ScheduleVersion, (schedule_id, base_version))
    return base.plan_json if base is not None else None


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
    plan_change: bool,
    commit: bool = True,
) -> int:
    """base_version+1 번 버전과 변경 이력 한 줄을 저장한다. 계산 확인은 부르는 쪽이 한다.

    plan_change(기본값 없음 — 부르는 쪽이 꼭 정한다): True 면 이 버전의 계산을 Plan 으로 고정하고,
    False 면 앞 버전의 Plan 을 물려받는다(모듈 설명글).
    """
    plan = _plan(session, schedule_id, base_version, schedule, conditions, plan_change)
    return _save(session, schedule_id, schedule, conditions, plan, by_kind=by_kind, by_name=by_name, note=note,
                 changes=changes, base_version=base_version, commit=commit)


def _save(
    session: Session,
    schedule_id: int,
    schedule: Schedule,
    conditions: list[dict],
    plan: dict | None,
    *,
    by_kind: str,
    by_name: str,
    note: str,
    changes: list[dict],
    base_version: int,
    commit: bool,
) -> int:
    n = base_version + 1
    bumped = _bump(session, schedule_id, base_version)
    record = _fresh_record(session, schedule_id)
    if not bumped:
        current = record.current_version
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
            plan_json=plan,
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
    """n번 버전의 내용(일정·조건)과 Plan(plan_json)을 새 버전으로 만든다. 이력은 지우지 않는다.

    base_version 을 주면 그것이 지금 버전인지 확인한다(없으면 지금 버전 위에 쌓는다).
    n번 일정이 n번의 조건을 넣고 계산되지 않으면 ScheduleError 를 내고 아무것도 저장하지 않는다.
    변경 이력에는 지금 버전 → n번 내용의 차이를 적는다.
    """
    schedule, conditions, _ = load(session, schedule_id, n)
    plan = get_version(session, schedule_id, n).plan_json
    _fresh_record(session, schedule_id)  # 지금 버전은 세션의 낡은 값이 아니라 DB 값으로
    current, _, current_n = load(session, schedule_id)
    base = current_n if base_version is None else base_version
    if base != current_n:
        raise VersionConflict(current_n)
    run(schedule, conditions)
    return _save(
        session,
        schedule_id,
        schedule,
        conditions,
        plan,
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
    """n번 버전에만 「처음 계획」 표시(is_plan)를 둔다(같은 일정의 다른 버전은 False). 없는 버전이면 NotFound.

    표시는 버전 목록·비교 화면에만 쓰고 Plan 칸은 정하지 않는다(Plan = 버전의 plan_json, store.view).
    """
    get_version(session, schedule_id, n)
    for v in session.scalars(
        select(ScheduleVersion).where(ScheduleVersion.schedule_id == schedule_id)
    ):
        v.is_plan = v.n == n
    end_write(session, commit)
