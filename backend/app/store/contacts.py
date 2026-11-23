"""주소록 읽기(Task 61). 주소록은 일정(프로젝트)마다 따로다.

일정 id 를 받는 함수는 그 일정 것만 본다 — 다른 일정의 연락처·협력사 id 는 없는 것과 같다(NotFound).
모든 일정을 보는 함수는 코드 전용이다: by_number 는 하네스의 문·일꾼만(번호로 등급·수신 거부를 정할 때),
by_name 은 신원 규칙만 부른다. 번호(number)는 app.outreach.phone.normalize 로 정리해서 본다.
「숨김」은 숨긴 사람과 숨긴 협력사의 사람이다.
"""

import unicodedata
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from app.core.model import CalendarSpec
from app.outreach.phone import normalize
from app.store.schedules import NotFound, load
from app.store.tables_outreach import Contact, ContactCompany

__all__ = ["NotFound", "by_name", "by_number", "calendar_of", "get_company", "get_contact", "listed", "search"]

DEFAULT_CALENDAR = CalendarSpec(days_per_week=5)


def get_contact(session: Session, schedule_id: int, contact_id: int) -> Contact:
    """그 일정의 연락처(숨긴 사람도). 없거나 다른 일정 것이면 NotFound."""
    row = session.get(Contact, contact_id)
    if row is None or row.schedule_id != schedule_id:
        raise NotFound(contact_id)
    return row


def get_company(session: Session, schedule_id: int, company_id: int) -> ContactCompany:
    """그 일정의 협력사(숨긴 것도). 없거나 다른 일정 것이면 NotFound."""
    row = session.get(ContactCompany, company_id)
    if row is None or row.schedule_id != schedule_id:
        raise NotFound(company_id)
    return row


def listed(
    session: Session, schedule_id: int, *, include_hidden: bool = False
) -> list[tuple[ContactCompany, list[Contact]]]:
    """그 일정의 협력사마다 사람들. 협력사·사람 모두 이름 순(같으면 id 순). 숨긴 것은 include_hidden 일 때만."""
    companies = select(ContactCompany).where(ContactCompany.schedule_id == schedule_id)
    people = select(Contact).where(Contact.schedule_id == schedule_id)
    if not include_hidden:
        companies = companies.where(ContactCompany.hidden.is_(False))
        people = people.where(Contact.hidden.is_(False))
    by_company: dict[int, list[Contact]] = {}
    for person in session.scalars(people.order_by(Contact.name, Contact.id)):
        by_company.setdefault(person.company_id, []).append(person)
    rows = session.scalars(companies.order_by(ContactCompany.name, ContactCompany.id))
    return [(company, by_company.get(company.id, [])) for company in rows]


def _shown() -> tuple[ColumnElement[bool], ...]:
    """숨기지 않은 사람이고 그 협력사도 숨기지 않았다(_with_company 로 붙인 문에 쓴다)."""
    return Contact.hidden.is_(False), ContactCompany.hidden.is_(False)


def _with_company() -> Select[tuple[Contact]]:
    return select(Contact).join(ContactCompany, ContactCompany.id == Contact.company_id)


def search(
    session: Session, schedule_id: int, query: str, limit: int = 5, *, company_ids: Sequence[int] | None = None
) -> list[Contact]:
    """그 일정에서 이름·담당에 query 가 든 사람(숨김 뺌). 이름이 query 와 같은 사람 먼저, 그다음 이름 순.
    company_ids 를 주면 그 협력사 사람만. query 의 %·_ 는 글자 그대로 찾는다."""
    q = unicodedata.normalize("NFC", query.strip())  # 저장된 이름은 NFC(주소록 API) — macOS 의 NFD 입력도 같은 이름
    stmt = _with_company().where(
        Contact.schedule_id == schedule_id,
        ContactCompany.schedule_id == schedule_id,
        *_shown(),
        or_(Contact.name.contains(q, autoescape=True), Contact.role_title.contains(q, autoescape=True)),
    )
    if company_ids is not None:
        stmt = stmt.where(Contact.company_id.in_(company_ids))
    return list(session.scalars(stmt.order_by(Contact.name != q, Contact.name, Contact.id).limit(limit)))


def by_number(session: Session, number: str) -> list[Contact]:
    """모든 일정에서 이 번호의 사람(숨긴 사람도 — 수신 거부가 번호를 따라가게), id 순. 코드 전용(문·일꾼).
    번호는 phone.normalize 로 정리해서 찾고, 정리되지 않으면(빈 글·메모 섞인 글 …) []."""
    target = normalize(number)
    if target is None:
        return []
    return list(session.scalars(select(Contact).where(Contact.phone == target).order_by(Contact.id)))


def by_name(session: Session, name: str) -> list[Contact]:
    """모든 일정에서 이름이 정확히 같은 사람(숨김 뺌), id 순. 신원 규칙 전용."""
    name = unicodedata.normalize("NFC", name.strip())  # 저장된 이름은 NFC — NFD 로 들어온 주장도 같은 이름
    if not name:
        return []
    return list(session.scalars(_with_company().where(Contact.name == name, *_shown()).order_by(Contact.id)))


def calendar_of(session: Session, schedule_id: int | None) -> CalendarSpec:
    """그 일정의 지금 버전 달력. 일정이 없으면(None·없는 id) 주 5일 기본."""
    if schedule_id is None:
        return DEFAULT_CALENDAR
    try:
        return load(session, schedule_id)[0].calendar
    except NotFound:
        return DEFAULT_CALENDAR
