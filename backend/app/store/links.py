"""승인 결과를 승인 건에 이어진 것에 알린다. 결정과 같은 트랜잭션에서 flush 만 한다(commit 은 부르는 쪽).

- after_apply: 복사본(link_kind 'scenario')은 applied 가 되고, 그 복사본에 넣은 지연 사건은 그 버전에 반영된 것
  (reflected)이 된다 — 다시 넣지 않는다. Plan 다시 잡기(reset_plan)는 하지 않는다(PM 11-20).
- after_reject·after_conflict: 복사본을 다시 open 으로(낡았으면 화면이 낡음으로 보인다).
"""

from sqlalchemy.orm import Session

from app.store import delays, scenarios
from app.store.tables import Approval, Scenario


def _scenario(session: Session, row: Approval) -> Scenario | None:
    if row.link_kind != "scenario" or row.link_id is None:
        return None
    return session.get(Scenario, row.link_id)


def after_apply(session: Session, row: Approval) -> None:
    """row.schedule_id·row.version 이 채워진 뒤(store.approvals.apply 끝)에 부른다."""
    scenario = _scenario(session, row)
    if scenario is not None:
        scenarios.set_status(session, scenario, "applied", approval_id=row.id)
        delays.mark_reflected(session, list(scenario.delay_event_ids), row.version)


def after_reject(session: Session, row: Approval) -> None:
    scenario = _scenario(session, row)
    if scenario is not None:
        scenarios.set_status(session, scenario, "open")


def after_conflict(session: Session, row: Approval) -> None:
    after_reject(session, row)
