from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.errors import ApiError
from app.programs.contacts import copy, csv_import, service
from app.programs.contacts.schemas import (
    AddressBookOut,
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    CopyIn,
    CopyOut,
    CopySourceDetail,
    CopySourceOut,
    ImportOut,
    PersonDetail,
    PersonIn,
    PersonPatch,
    ReadOut,
    RevealOut,
)
from app.security.deps import require_admin, require_contacts
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
def patch_person(
    schedule_id: int, contact_id: int, body: PersonPatch, session: SessionDep, user: UserDep
) -> PersonDetail:
    """보낸 칸만. 보이던 수신 거부를 끄는 것(do_not_contact: false)은 관리자만 — 그 번호가 있는 모든 일정에서 풀린다."""
    return service.patch_person(session, schedule_id, contact_id, body, user)


@router.post("/{schedule_id}/contacts/people/{contact_id}/reveal")
def reveal(schedule_id: int, contact_id: int, session: SessionDep, user: UserDep, response: Response) -> RevealOut:
    """전체 번호(010-0000-0199). 번호가 없으면 null. 머리글 Cache-Control: no-store."""
    response.headers["Cache-Control"] = "no-store"
    return service.reveal(session, schedule_id, contact_id, user)


@router.post("/{schedule_id}/contacts/people/{contact_id}/read")
def mark_read(schedule_id: int, contact_id: int, session: SessionDep) -> ReadOut:
    """받은 메시지를 읽음으로. → {read: 이번에 바꾼 수}."""
    return service.mark_read(session, schedule_id, contact_id)


@router.post("/{schedule_id}/contacts/import")
async def import_csv(
    schedule_id: int, request: Request, session: SessionDep, user: UserDep, dry_run: bool = True
) -> ImportOut:
    """multipart: 파일 칸 `file`, 선택 `skip`(건너뛸 행 번호 — 칸마다 하나 또는 「3,5」). dry_run=1(기본) 미리 보기, 0 넣기.
    몸은 로그인·역할(의존성)과 Content-Length(1MB + 여유) 를 본 뒤에만 읽는다. 규칙은 csv_import 머리 글."""
    csv_import.check_length(request.headers)
    async with request.form(max_files=1, max_fields=csv_import.MAX_FIELDS) as form:
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ApiError(422, "csv_missing_file", csv_import.NO_FILE)
        data = await upload.read(csv_import.MAX_BYTES + 1)
        skip = form.getlist("skip")
    return await run_in_threadpool(csv_import.run, session, schedule_id, data, skip, dry_run=dry_run, user=user)


@router.get("/{schedule_id}/contacts/copy-sources", dependencies=[Depends(require_admin)])
def copy_sources(schedule_id: int, session: SessionDep) -> list[CopySourceOut]:
    """관리자만. 이 일정 밖의 일정들과 그 보이는 사람 수."""
    return copy.sources(session, schedule_id)


@router.get("/{schedule_id}/contacts/copy-sources/{other_id}", dependencies=[Depends(require_admin)])
def copy_source(schedule_id: int, other_id: int, session: SessionDep) -> CopySourceDetail:
    """관리자만. 그 일정의 보이는 협력사·사람(번호는 가린 꼴), already_here = 복사하면 건너뛸 사람."""
    return copy.source(session, schedule_id, other_id)


@router.post("/{schedule_id}/contacts/copy", dependencies=[Depends(require_admin)])
def copy_people(schedule_id: int, body: CopyIn, session: SessionDep, user: UserDep) -> CopyOut:
    """관리자만. 고른 사람을 새 줄로 복사 → {copied, skipped, refused}. 규칙은 copy 머리 글."""
    return copy.copy(session, schedule_id, body, user)
