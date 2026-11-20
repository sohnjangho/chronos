"""내 규칙 목록·켜고 끄기·지우기. 규칙을 끄거나 지워도 이미 그 조건을 가진 일정은 그대로다(일정은 사본을 가진다)."""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.rules.schemas import DeletedOut, EnabledIn, RuleOut
from app.store import my_rules
from app.store.schedules import NotFound, get_record, load
from app.store.tables import MyRule, User

NOT_FOUND_MESSAGE = "규칙을 찾을 수 없습니다."
SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
NOT_OWNER_MESSAGE = "만든 사람이나 관리자만 지울 수 있습니다."


def _out(row: MyRule, present: set[str] | None) -> RuleOut:
    cid = row.condition_json.get("id")
    return RuleOut(id=row.id, scope=row.scope, domain=row.domain, schedule_id=row.schedule_id,
                   condition=row.condition_json, enabled=row.enabled, created_by=row.created_by,
                   created_at=row.created_at, in_schedule=None if present is None else cid in present)


def list_rules(session: Session, domain: str | None, schedule_id: int | None) -> list[RuleOut]:
    """schedule_id 를 주면 그 일정 분야(domain 을 안 주면)의 분야 범위 + 그 일정 범위와 in_schedule."""
    if schedule_id is None:
        return [_out(r, None) for r in my_rules.listed(session, domain=domain)]
    try:
        domain = domain or get_record(session, schedule_id).domain
        _, stored, _ = load(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None
    present = {d.get("id") for d in stored if isinstance(d, dict)}
    return [_out(r, present) for r in my_rules.listed(session, domain=domain, schedule_id=schedule_id)]


def _get(session: Session, rule_id: int) -> MyRule:
    try:
        return my_rules.get(session, rule_id)
    except my_rules.NotFound:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE) from None


def set_enabled(session: Session, rule_id: int, body: EnabledIn) -> RuleOut:
    row = _get(session, rule_id)
    my_rules.set_enabled(session, row, body.enabled)
    session.commit()
    return _out(row, None)


def delete(session: Session, rule_id: int, user: User) -> DeletedOut:
    """만든 사람(이름)이나 관리자만. 아니면 403 not_owner."""
    row = _get(session, rule_id)
    if user.role != "admin" and row.created_by != user.name:
        raise ApiError(403, "not_owner", NOT_OWNER_MESSAGE)
    my_rules.delete(session, row)
    session.commit()
    return DeletedOut(deleted=rule_id)
