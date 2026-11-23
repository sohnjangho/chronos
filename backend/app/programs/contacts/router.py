from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.contacts import service
from app.programs.contacts.schemas import (
    AddressBookOut,
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    PersonDetail,
    PersonIn,
    PersonPatch,
    ReadOut,
    RevealOut,
)
from app.security.deps import require_contacts
from app.store.tables import User

# 주소록은 일정(프로젝트)마다 따로다. 관리자·사용자만(현장 관리자 403 field_no_contacts). 다른 일정의 id 는 404.
# 응답의 번호는 가린 꼴만이고, 전체 번호는 POST …/reveal 한 곳(캐시 금지·로그 한 줄).
router = APIRouter(prefix="/api/schedules", tags=["contacts"], dependencies=[Depends(require_contacts)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(require_contacts)]


@router.get("/{schedule_id}/contacts")
def address_book(schedule_id: int, session: SessionDep, include_hidden: bool = False) -> AddressBookOut:
    return service.address_book(session, schedule_id, include_hidden)


@router.post("/{schedule_id}/contacts/companies", status_code=201)
def create_company(schedule_id: int, body: CompanyIn, session: SessionDep) -> CompanyOut:
    return service.create_company(session, schedule_id, body)


@router.patch("/{schedule_id}/contacts/companies/{company_id}")
def patch_company(schedule_id: int, company_id: int, body: CompanyPatch, session: SessionDep) -> CompanyOut:
    return service.patch_company(session, schedule_id, company_id, body)


@router.post("/{schedule_id}/contacts/people", status_code=201)
def create_person(schedule_id: int, body: PersonIn, session: SessionDep) -> PersonDetail:
    return service.create_person(session, schedule_id, body)


@router.get("/{schedule_id}/contacts/people/{contact_id}")
def person(schedule_id: int, contact_id: int, session: SessionDep) -> PersonDetail:
    return service.person(session, schedule_id, contact_id)


@router.patch("/{schedule_id}/contacts/people/{contact_id}")
def patch_person(schedule_id: int, contact_id: int, body: PersonPatch, session: SessionDep) -> PersonDetail:
    return service.patch_person(session, schedule_id, contact_id, body)


@router.post("/{schedule_id}/contacts/people/{contact_id}/reveal")
def reveal(schedule_id: int, contact_id: int, session: SessionDep, user: UserDep, response: Response) -> RevealOut:
    """전체 번호(010-0000-0199). 번호가 없으면 null. 머리글 Cache-Control: no-store."""
    response.headers["Cache-Control"] = "no-store"
    return service.reveal(session, schedule_id, contact_id, user)


@router.post("/{schedule_id}/contacts/people/{contact_id}/read")
def mark_read(schedule_id: int, contact_id: int, session: SessionDep) -> ReadOut:
    """받은 메시지를 읽음으로. → {read: 이번에 바꾼 수}."""
    return service.mark_read(session, schedule_id, contact_id)
