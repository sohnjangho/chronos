"""일정 초안(schedule_drafts): 생성 루프의 결과를 승인(첫 저장) 전까지 둔다.

일정은 `to_json` 으로 넣는다. 자원 맞춤이 넣는 `pinned_start` 는 들어가지 않는다(맞춤 전 일정을 넣는다).
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.model import Schedule
from app.harness.checks import CheckReport, Violation
from app.harness.conditions import Condition
from app.store.schedules import NotFound, to_json
from app.store.tables import ScheduleDraft


def violation_json(v: Violation) -> dict:
    return {
        "condition_id": v.condition_id,
        "message": v.message,
        "activity_ids": list(v.activity_ids),
        "amount": v.amount,
    }


def report_json(report: CheckReport) -> dict:
    """CheckReport → JSON 모양(칸 이름 그대로, 위반·알림은 violation_json)."""
    return {
        "passed": list(report.passed),
        "violations": [violation_json(v) for v in report.violations],
        "notices": [violation_json(v) for v in report.notices],
        "uncheckable": list(report.uncheckable),
        "skipped": list(report.skipped),
        "invalid": [dict(i) for i in report.invalid],
    }


def create_draft(
    session: Session,
    *,
    chat_session_id: int | None,
    domain: str,
    level: str,
    schedule: Schedule,
    conditions: Sequence[Condition],
    report: CheckReport,
    assumptions: Sequence[dict],
) -> int:
    """초안 한 줄을 넣고 commit 한 뒤 id 를 준다."""
    row = ScheduleDraft(
        chat_session_id=chat_session_id,
        domain=domain,
        level=level,
        schedule_json=to_json(schedule),
        conditions_json=[c.to_dict() for c in conditions],
        report_json=report_json(report),
        assumptions_json=[dict(a) for a in assumptions],
    )
    session.add(row)
    session.commit()
    return row.id


def get_draft(session: Session, draft_id: int) -> ScheduleDraft:
    """없으면 NotFound."""
    row = session.get(ScheduleDraft, draft_id)
    if row is None:
        raise NotFound(draft_id)
    return row
