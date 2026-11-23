"""다른 프로젝트에서 복사(Task 76) — 관리자만(라우터의 require_admin). 다른 일정의 주소록을 읽는 길은 이것뿐이다.

- 목록(sources): 이 일정 밖의 일정과 그 보이는 사람 수. 한 일정(source): 보이는 협력사·사람, 번호는 가린 꼴·종류만.
- 복사(copy): 고른 사람을 새 줄로(협력사는 같은 이름의 보이는 협력사가 있으면 그것, 없으면 이름·공종·메모를 복사해 새로).
  근무시간·성별·언어·음성·메모·수신 거부(까닭 포함)를 그대로 옮기고, 복사한 뒤에는 서로 이어지지 않는다.
  「이미 있음」은 CSV 가져오기와 같은 판정(csv_import.Book — 같은 번호(정리한 꼴), 또는 같은 협력사·이름)이고 건너뛴다.
- 수신 거부: 원래 줄에 표시가 있으면 새 줄에도 표시하고 그 번호 기록을 남긴다(service._settle_do_not_contact — 같은 꾸러미의
  주소록 입력과 같은 함수). 번호 기준 수신 거부는 store.outreach 가 그대로 보이므로 복사가 풀거나 지우는 일은 없다.
- 격리: 고른 id 가 하나라도 그 일정 것이 아니면(없거나 셋째 일정) 없는 id 와 같은 404 이고 아무것도 복사하지 않는다.
- 옮기는 값은 주소록 입력 검사를 다시 받는다(글자·번호·근무시간·음성). 걸리는 예전 줄은 복사하지 않고 refused 로 센다.
  채널은 원래 줄에서 끈 것은 끈 채로, 켠 것은 번호 종류가 되는 것만(check_channels).
"""

import logging

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone
from app.programs.contacts import csv_import, service
from app.programs.contacts.schemas import (
    CopyCompanyOut,
    CopyIn,
    CopyOut,
    CopyPersonOut,
    CopySourceDetail,
    CopySourceOut,
    HoursIn,
)
from app.store import contacts, outreach
from app.store.schedules import NotFound, get_record, list_records
from app.store.tables import ScheduleRecord, User
from app.store.tables_outreach import Contact, ContactCompany

logger = logging.getLogger(__name__)

SAME_SCHEDULE = "같은 프로젝트에서는 복사할 수 없습니다. 다른 프로젝트를 골라 주세요."


def sources(session: Session, schedule_id: int) -> list[CopySourceOut]:
    service._schedule(session, schedule_id)
    counts = dict(session.execute(
        select(Contact.schedule_id, func.count())
        .join(ContactCompany, ContactCompany.id == Contact.company_id)
        .where(Contact.hidden.is_(False), ContactCompany.hidden.is_(False))
        .group_by(Contact.schedule_id)
    ).all())
    return [CopySourceOut(schedule_id=r.id, name=r.name, people=counts.get(r.id, 0))
            for r in list_records(session) if r.id != schedule_id]


def _source(session: Session, schedule_id: int, other_id: int) -> ScheduleRecord:
    service._schedule(session, schedule_id)
    if other_id == schedule_id:
        raise ApiError(422, "same_schedule", SAME_SCHEDULE)
    try:
        return get_record(session, other_id)
    except NotFound:
        raise ApiError(404, "not_found", service.SCHEDULE_NOT_FOUND) from None


def source(session: Session, schedule_id: int, other_id: int) -> CopySourceDetail:
    record = _source(session, schedule_id, other_id)
    book = csv_import.existing(session, schedule_id)
    listed = contacts.listed(session, other_id)
    refused = outreach.do_not_contact_numbers(session, [p.phone for _, people in listed for p in people if p.phone])
    companies = []
    for company, people in listed:
        rows = []
        for p in people:
            number = phone.normalize(p.phone)
            rows.append(CopyPersonOut(
                id=p.id, name=p.name, role_title=p.role_title, phone_masked=phone.mask(p.phone),
                phone_kind=phone.kind(p.phone), has_phone=bool(p.phone),
                do_not_contact=bool(p.do_not_contact) or number in refused,
                already_here=book.match(company.name, p.name, number) is not None,
            ))
        companies.append(CopyCompanyOut(id=company.id, name=company.name, trade=company.trade, people=rows))
    return CopySourceDetail(schedule_id=record.id, name=record.name, companies=companies)


def _checked(src: Contact, company: ContactCompany) -> dict:
    """옮길 값(주소록 입력 검사를 다시 거친 것). 걸리면 ApiError·ValidationError."""
    service.check_texts({"name": src.name, "role_title": src.role_title, "note": src.note, "dnc_reason": src.dnc_reason})
    service.check_texts({"name": company.name, "trade": company.trade, "note": company.note})
    number = service.check_phone(src.phone)
    off = {column: False for column in service.NUMBER_CHANNELS if not getattr(src, column)}
    hours = service.check_hours(HoursIn(**src.hours_json)) if src.hours_json else None
    service.check_voice(src.voice_mode, src.voice_id)
    return dict(
        name=src.name, role_title=src.role_title, phone=number, **service.check_channels(number, off, renumbered=True),
        hours_json=hours, gender=src.gender, language=src.language, voice_mode=src.voice_mode, voice_id=src.voice_id,
        dnc_reason=src.dnc_reason, phone_invalid=src.phone_invalid, note=src.note,
    )


def copy(session: Session, schedule_id: int, body: CopyIn, user: User) -> CopyOut:
    other = _source(session, schedule_id, body.from_schedule_id).id
    ids = list(dict.fromkeys(body.contact_ids))
    csv_import.begin_write(session)
    picked = {row.id: row for row in session.scalars(
        select(Contact).where(Contact.id.in_(ids), Contact.schedule_id == other))}
    if len(picked) != len(ids):
        raise ApiError(404, "not_found", service.PERSON_NOT_FOUND)
    companies = {row.id: row for row in session.scalars(select(ContactCompany).where(
        ContactCompany.id.in_({row.company_id for row in picked.values()}), ContactCompany.schedule_id == other))}
    book = csv_import.existing(session, schedule_id)
    copied = skipped = refused = 0
    for contact_id in ids:
        src, company = picked[contact_id], companies.get(picked[contact_id].company_id)
        try:
            if company is None:
                raise ApiError(404, "not_found", service.COMPANY_NOT_FOUND)
            values = _checked(src, company)
        except (ApiError, ValidationError):
            refused += 1
            continue
        if book.match(company.name, src.name, values["phone"]) is not None:
            skipped += 1
            continue
        target = csv_import.company_id(session, schedule_id, book, company.name, company.trade, company.note)
        row = Contact(schedule_id=schedule_id, company_id=target, **values)
        session.add(row)
        service._settle_do_not_contact(session, row, None, False, True if src.do_not_contact else None)
        book.add(company.name, src.name, values["phone"])
        copied += 1
    session.commit()
    logger.info("연락처 복사: 일정 %s ← %s · 사용자 %s · 복사 %d · 건너뜀 %d · 거절 %d",
                schedule_id, other, user.id, copied, skipped, refused)
    return CopyOut(copied=copied, skipped=skipped, refused=refused)
