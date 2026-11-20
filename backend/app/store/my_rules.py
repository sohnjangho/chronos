"""내 규칙(my_rules): 사용자가 늘 쓰는 방식을 조건 하나로 둔 것. 승인된 뒤에만 만든다(store.links.after_apply).

scope 'domain' = 그 분야의 새 일정 생성에 모두 들어간다(켜져 있을 때). 'schedule' = 그 일정 하나(그 일정의 버전에 조건 사본이
들어간다). 규칙을 끄거나 지워도 이미 그 조건을 가진 일정은 그대로다(일정은 사본을 가진다).
쓰기는 flush 만 한다(commit 은 부르는 쪽).
"""

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.harness.conditions import Condition, read_conditions
from app.store.schedules import NotFound
from app.store.tables import MyRule

__all__ = ["NotFound", "create", "delete", "for_context", "for_generation", "get", "has_condition", "listed",
           "set_enabled"]


def create(session: Session, *, scope: str, domain: str, schedule_id: int | None, condition_json: dict,
           approval_id: int | None, created_by: str) -> MyRule:
    row = MyRule(scope=scope, domain=domain, schedule_id=schedule_id, condition_json=dict(condition_json),
                 approval_id=approval_id, created_by=created_by)
    session.add(row)
    session.flush()
    return row


def get(session: Session, rule_id: int) -> MyRule:
    """없으면 NotFound."""
    row = session.get(MyRule, rule_id)
    if row is None:
        raise NotFound(rule_id)
    return row


def has_condition(session: Session, condition_id: str) -> bool:
    """이 조건 id 의 내 규칙이 저장돼 있는가(켜짐과 상관없이)."""
    query = select(MyRule.id).where(MyRule.condition_json["id"].as_string() == condition_id)
    return session.scalar(query) is not None


def listed(session: Session, *, domain: str | None = None, schedule_id: int | None = None) -> list[MyRule]:
    """id 순. schedule_id 를 주면 분야 범위(domain 을 주면 그 분야만) + 그 일정 범위만. 아니면 domain 으로만 거른다."""
    query = select(MyRule).order_by(MyRule.id)
    in_domain = MyRule.domain == domain if domain is not None else true()
    if schedule_id is not None:
        domain_scope = (MyRule.scope == "domain") & in_domain
        query = query.where(or_(domain_scope, (MyRule.scope == "schedule") & (MyRule.schedule_id == schedule_id)))
    elif domain is not None:
        query = query.where(in_domain)
    return list(session.scalars(query))


def _conditions(rows: list[MyRule]) -> list[Condition]:
    return read_conditions([r.condition_json for r in rows if r.enabled])[0]  # 읽을 수 없는 것은 넣지 않는다


def for_generation(session: Session, domain: str) -> list[Condition]:
    """새 일정 생성에 넣을 내 규칙: 그 분야의 켜진 분야 범위 규칙(id 순)."""
    return _conditions([r for r in listed(session, domain=domain) if r.scope == "domain"])


def for_context(session: Session, *, domain: str | None, schedule_id: int | None) -> list[Condition]:
    """대화 맥락에 보일 켜진 내 규칙. 일정이 있으면 그 분야의 분야 범위 + 그 일정 범위, 없으면 모든 분야 범위."""
    if schedule_id is None:
        return _conditions([r for r in listed(session) if r.scope == "domain"])
    return _conditions(listed(session, domain=domain, schedule_id=schedule_id))


def set_enabled(session: Session, row: MyRule, enabled: bool) -> None:
    row.enabled = enabled
    session.flush()


def delete(session: Session, row: MyRule) -> None:
    session.delete(row)
    session.flush()
