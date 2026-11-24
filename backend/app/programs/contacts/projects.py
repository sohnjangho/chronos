"""「참여 프로젝트」(11-24 PM — 한 사람이 여러 프로젝트를 맡는다): 같은 사람을 다른 프로젝트에 등록하고 빼기.

- 등록: 그 프로젝트에 같은 사람 열쇠(person_key)의 줄을 만든다. 함께 저장되는 칸(links.SHARED_COPIED·수신 거부)은 이 줄에서
  옮기고, 협력사(그 프로젝트의 것 — 꼭 고른다)·담당은 그 프로젝트 것, 근무시간·메모는 비운다. 예전에 뺀(숨긴) 줄이 있으면
  그 줄을 다시 보인다(연락 기록이 그 줄에 그대로 있다).
- 그 프로젝트에 같은 번호의 다른 연락처가 이미 보이면 새 줄을 만들지 않고 409 same_number_there(detail 에 그 연락처 id 만) —
  화면은 「같은 사람으로 연결」(link_contact_id)을 묻는다. 잇기는 같은 번호이고 아직 누구와도 이어지지 않은 줄만, 함께 저장되는
  칸은 이 줄의 값으로, 수신 거부는 어느 한쪽이라도 켜져 있으면 둘 다(풀리는 쪽으로 가지 않는다).
- 빼기: 그 프로젝트의 줄을 **숨긴다**(지우지 않는다 — 문자·통화 기록이 그 줄을 가리킨다). 지금 연 프로젝트는 [숨기기]로.
- 관리할 수 있는 프로젝트(manageable): 관리자·사용자는 모든 일정, 현장 관리자는 없음(주소록 자체가 403). 관리자 등급인 사람을
  새 프로젝트에 등록하거나 잇는 것으로 등급이 생기거나 바뀌면 관리자만(links.check_level).
- 오류 글에 번호를 싣지 않는다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone
from app.programs.contacts import links, service
from app.programs.contacts.schemas import PersonDetail, ProjectAdd, ProjectChoice
from app.store.schedules import list_records
from app.store.tables import ScheduleRecord, User
from app.store.tables_outreach import Contact, ContactCompany

ALREADY_HERE = "이미 이 프로젝트의 연락처입니다."
OWN_PROJECT = "지금 연 프로젝트에서 빼려면 [숨기기]를 쓰세요."
ALREADY_LINKED = "이미 그 프로젝트에 등록되어 있습니다."
NOT_LINKED = "그 프로젝트에 등록되어 있지 않습니다."
COMPANY_REQUIRED = "그 프로젝트의 협력사를 골라 주세요."
SAME_NUMBER_THERE = "그 프로젝트에 같은 번호의 연락처가 이미 있습니다. 같은 사람으로 연결할 수 있습니다."
NOT_SAME_NUMBER = "번호가 같은 연락처만 같은 사람으로 연결할 수 있습니다."
LINKED_ELSEWHERE = "그 연락처는 이미 다른 사람과 연결되어 있습니다."


def manageable(session: Session, user: User) -> list[ScheduleRecord]:
    """이 사용자가 주소록을 관리할 수 있는 프로젝트(일정 id 순). 프로젝트마다 권한이 생기면 여기 한 곳을 바꾼다."""
    return [] if user.role == "field" else list_records(session)


def _target(session: Session, user: User, schedule_id: int) -> int:
    if schedule_id not in {record.id for record in manageable(session, user)}:
        raise ApiError(404, "not_found", service.SCHEDULE_NOT_FOUND)
    return schedule_id


def _there(group: list[Contact], schedule_id: int) -> Contact | None:
    return next((row for row in group if row.schedule_id == schedule_id), None)


def choices(session: Session, schedule_id: int, contact_id: int, user: User) -> list[ProjectChoice]:
    src = service._person(session, schedule_id, contact_id)
    shown = {row.schedule_id: row for row in [src, *links.linked(session, src)] if not row.hidden or row.id == src.id}
    out = []
    for record in manageable(session, user):
        row = shown.get(record.id)
        company = session.get(ContactCompany, row.company_id) if row is not None else None
        out.append(ProjectChoice(schedule_id=record.id, name=record.name, linked=row is not None,
                                 current=record.id == schedule_id, contact_id=row.id if row else None,
                                 company_id=row.company_id if row else None, company_name=company.name if company else None))
    return out


def _same_number(session: Session, schedule_id: int, number: str | None, key: str) -> Contact | None:
    """그 프로젝트에서 같은 번호로 보이는, 이 사람이 아닌 연락처."""
    if not number:
        return None
    return session.scalar(select(Contact).where(Contact.schedule_id == schedule_id, Contact.phone == number,
                                                Contact.hidden.is_(False), Contact.person_key.is_distinct_from(key))
                          .order_by(Contact.id).limit(1))


def _settle_pair(session: Session, src: Contact, row: Contact) -> None:
    """수신 거부는 어느 한쪽이라도 보이면 둘 다(번호 기록도) — 잇는다고 풀리지 않는다."""
    if service._shows_do_not_contact(session, src) or service._shows_do_not_contact(session, row):
        reason = src.dnc_reason or row.dnc_reason
        for person in (src, row):
            person.do_not_contact, person.dnc_reason = True, reason
        service._mark(session, src.phone, reason)


def add(session: Session, schedule_id: int, contact_id: int, body: ProjectAdd, user: User) -> PersonDetail:
    """그 프로젝트에 이 사람을 등록(위 머리 글). 검사를 모두 마친 뒤에 쓴다. → 이 줄의 자세히(project_links 포함)."""
    src = service._person(session, schedule_id, contact_id)
    if body.schedule_id == schedule_id:
        raise ApiError(422, "own_project", ALREADY_HERE)
    target = _target(session, user, body.schedule_id)
    if body.role_title is not None:
        service.check_texts({"role_title": body.role_title})
    key = links.ensure_key(src)
    row = _there(links.linked(session, src), target)
    if row is not None and not row.hidden:
        raise ApiError(409, "already_linked", ALREADY_LINKED)
    if row is None and body.link_contact_id is not None:
        row = _adopt(session, src, target, body.link_contact_id)
    if body.company_id is not None:
        service._company(session, target, body.company_id)
    elif row is None:
        raise ApiError(422, "company_required", COMPANY_REQUIRED)
    if row is None and (clash := _same_number(session, target, src.phone, key)) is not None:
        raise ApiError(409, "same_number_there", SAME_NUMBER_THERE, detail={"contact_id": clash.id})
    before = row.access_level if row is not None else None
    links.check_level(user, [before], src.access_level)
    if row is None:
        row = Contact(schedule_id=target, company_id=body.company_id, person_key=key, phone=src.phone,
                      role_title=src.role_title, hours_json=None, note="")
        session.add(row)
    row.person_key, row.hidden = key, False
    links.copy_shared(src, row)
    if body.company_id is not None:
        row.company_id = body.company_id
    if body.role_title is not None:
        row.role_title = body.role_title
    _settle_pair(session, src, row)
    links.record_level(session, row, before, user)
    session.commit()
    return service._detail(session, schedule_id, src)


def _adopt(session: Session, src: Contact, target: int, contact_id: int) -> Contact:
    """「같은 사람으로 연결」: 그 프로젝트의 같은 번호 연락처(아직 누구와도 이어지지 않은 것)."""
    row = service._person(session, target, contact_id)
    if not src.phone or phone.normalize(row.phone or "") != phone.normalize(src.phone):
        raise ApiError(422, "not_same_number", NOT_SAME_NUMBER)
    if links.linked(session, row):
        raise ApiError(409, "linked_elsewhere", LINKED_ELSEWHERE)
    return row


def remove(session: Session, schedule_id: int, contact_id: int, other_id: int, user: User) -> PersonDetail:
    """그 프로젝트의 이 사람 줄을 숨긴다(지우지 않음 — 연락 기록은 그대로). → 이 줄의 자세히."""
    src = service._person(session, schedule_id, contact_id)
    if other_id == schedule_id:
        raise ApiError(422, "own_project", OWN_PROJECT)
    target = _target(session, user, other_id)
    row = _there(links.linked(session, src), target)
    if row is None or row.hidden:
        raise ApiError(404, "not_found", NOT_LINKED)
    row.hidden = True
    session.commit()
    return service._detail(session, schedule_id, src)
