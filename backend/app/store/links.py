"""승인 결과를 승인 건에 이어진 것에 알린다. 결정과 같은 트랜잭션에서 flush 만 한다(commit 은 부르는 쪽).

- after_apply: 복사본(link_kind 'scenario')은 applied 가 되고, 그 복사본에 넣은 지연 사건은 그 버전에 반영된 것
  (reflected)이 된다 — 다시 넣지 않는다. Plan 다시 잡기(reset_plan)는 하지 않는다(PM 11-20).
- after_reject·after_conflict: 복사본을 다시 open 으로(낡았으면 화면이 낡음으로 보인다).
- 내 규칙(link_kind 'rule'): 승인되면 rule_json 으로 내 규칙을 만든다(만든 사람 = 낸 사람). 거부·충돌이면 아무것도 남기지 않는다.
- 사진 사람 판독(현장 사진 줄, response_choice human): 거부·충돌이면 그 줄을 다시 사람 판독 대기(human_wait)로 — 숫자·승인 건을
  떼고, 거부된 시도는 payload human_history 에 남긴다(리뷰 3, PM 11-24).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.store import delays, my_rules, scenarios
from app.store.tables import Approval, FieldItem, Scenario


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
    if row.link_kind == "rule" and row.rule_json:
        rule = row.rule_json
        my_rules.create(session, scope=rule["scope"], domain=rule["domain"], schedule_id=rule.get("schedule_id"),
                        condition_json=rule["condition"], approval_id=row.id, created_by=row.requested_by)


def _human_photo_back(session: Session, row: Approval, outcome: str) -> None:
    photo = session.scalars(select(FieldItem).where(
        FieldItem.approval_id == row.id, FieldItem.kind == "photo", FieldItem.response_choice == "human")).first()
    if photo is None:
        return
    payload = dict(photo.payload_json or {})
    tried = payload.pop("human_read", {})
    payload["human_history"] = [*payload.get("human_history", []),
                                {**tried, "outcome": outcome, "approval_id": row.id, "closed_at": datetime.now(UTC).isoformat()}]
    photo.payload_json = payload
    photo.status, photo.approval_id, photo.response_choice = "human_wait", None, "unread"
    photo.reported_progress, photo.reported_rd = None, None


def after_reject(session: Session, row: Approval, outcome: str = "rejected") -> None:
    scenario = _scenario(session, row)
    if scenario is not None:
        scenarios.set_status(session, scenario, "open")
    _human_photo_back(session, row, outcome)


def after_conflict(session: Session, row: Approval) -> None:
    after_reject(session, row, "conflict")
