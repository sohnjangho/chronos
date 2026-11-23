"""주소록(일정 = 프로젝트마다 따로): 목록·협력사·사람 쓰기·상세·번호 보기·읽음.

- 격리: 모든 함수가 일정 id 를 받는다. 다른 일정의 협력사·사람 id(본문의 company_id 도)는 없는 id 와 같은 404·같은 글이다.
- 번호: 응답은 가린 꼴(phone.mask)만. 전체 번호는 reveal 한 곳이고, 부를 때마다 로그 한 줄(사용자·연락처 id — 번호 없이).
- 번호 입력: 받는 번호인지는 app.outreach.phone.normalize 만 정한다(여기에 번호 규칙을 두지 않는다 — 그 모듈의 규칙이
  바뀌면 이 API 도 따라간다). 받지 않는 번호는 422 invalid_phone, 오류 글에 값을 싣지 않는다. 비우면(null·빈 글) 번호 없음.
  번호가 바뀌면 「번호 오류」 표시(phone_invalid)를 내린다 — 새 번호는 아직 틀린 번호로 확인되지 않았다.
- 근무시간 입력(check_hours 한 곳): 요일 0~6 하나 이상, 시각 HH:MM(00:00~23:59), 시작 ≠ 끝. 끝이 시작보다 이르면 자정을 넘는
  근무(app.outreach.hours). **시작 == 끝은 받지 않는다**: hours 모듈은 그것을 꼭 하루(24시간) 근무로 읽는데, 같은 시각을 잘못
  넣으면 한밤 전화가 열린다(근무시간 밖 전화는 실패로 본다). 24시간 근무를 받기로 하면 check_hours 의 그 줄만 지운다.
- 입력 검사는 모두 줄을 고치기 전에 끝낸다(검사에 걸리면 아무것도 바뀌지 않는다).
"""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import hours as work_hours
from app.outreach import phone
from app.outreach.redact import hide_phones
from app.programs.contacts.schemas import (
    ActivityRef,
    AddressBookOut,
    CompanyGroup,
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    HoursIn,
    PersonBrief,
    PersonDetail,
    PersonIn,
    PersonPatch,
    ReadOut,
    RevealOut,
)
from app.store import contacts
from app.store.schedules import NotFound, get_record, load
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)

logger = logging.getLogger(__name__)

SCHEDULE_NOT_FOUND = "일정을 찾을 수 없습니다."
PERSON_NOT_FOUND = "연락처를 찾을 수 없습니다."
COMPANY_NOT_FOUND = "협력사를 찾을 수 없습니다."
BAD_PHONE = "전화번호 형식이 맞지 않습니다."
BAD_DAYS = "근무 요일을 하나 이상 골라 주세요."
BAD_TIME = "시각은 HH:MM 으로 넣어 주세요."
SAME_TIME = "시작과 끝 시각이 같습니다. 끝나는 시각을 다르게 넣어 주세요."
LAST_LINE_CHARS = 30
_HHMM = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_CHANNELS = (("sms", "can_sms"), ("kakao", "can_kakao"), ("call", "can_call"))


def _now() -> datetime:
    return datetime.now(UTC)


# ── 찾기(격리) ──────────────────────────────────────────────────────────────────

def _schedule(session: Session, schedule_id: int) -> None:
    try:
        get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND) from None


def _person(session: Session, schedule_id: int, contact_id: int) -> Contact:
    try:
        return contacts.get_contact(session, schedule_id, contact_id)
    except contacts.NotFound:
        raise ApiError(404, "not_found", PERSON_NOT_FOUND) from None


def _company(session: Session, schedule_id: int, company_id: int) -> ContactCompany:
    try:
        return contacts.get_company(session, schedule_id, company_id)
    except contacts.NotFound:
        raise ApiError(404, "not_found", COMPANY_NOT_FOUND) from None


# ── 입력 검사 ───────────────────────────────────────────────────────────────────

def check_phone(raw: str | None) -> str | None:
    """입력 번호 → 저장 꼴(숫자만). 비면 None. 받는 번호인지는 phone.normalize 가 정한다 — 아니면 422(값 없이)."""
    if raw is None or not raw.strip():
        return None
    number = phone.normalize(raw)
    if number is None:
        raise ApiError(422, "invalid_phone", BAD_PHONE)
    return number


def check_hours(given: HoursIn | None) -> dict | None:
    """근무시간 입력 → hours_json. None 은 프로젝트 기본. 규칙은 모듈 머리 글(시작 == 끝은 받지 않음)."""
    if given is None:
        return None
    if not given.days or any(day < 0 or day > 6 for day in given.days):
        raise ApiError(422, "invalid_hours", BAD_DAYS)
    if not (_HHMM.fullmatch(given.start) and _HHMM.fullmatch(given.end)):
        raise ApiError(422, "invalid_hours", BAD_TIME)
    if given.start == given.end:
        raise ApiError(422, "invalid_hours", SAME_TIME)
    return {"days": sorted(set(given.days)), "start": given.start, "end": given.end}


# ── 응답 만들기 ─────────────────────────────────────────────────────────────────

def _threads(session: Session, schedule_id: int, contact_id: int | None = None) -> tuple[dict[int, int], dict[int, str]]:
    """(연락처마다 읽지 않은 받은 메시지 수, 연락처마다 마지막 메시지 앞 30자). 이 일정의 줄만.
    마지막 줄은 번호를 가린 뒤에 자른다(자른 뒤에 가리면 번호 조각이 남는다)."""
    mine = [OutreachMessage.schedule_id == schedule_id, OutreachMessage.contact_id.is_not(None)]
    if contact_id is not None:
        mine.append(OutreachMessage.contact_id == contact_id)
    unread = session.execute(
        select(OutreachMessage.contact_id, func.count())
        .where(*mine, OutreachMessage.direction == "in", OutreachMessage.read_at.is_(None))
        .group_by(OutreachMessage.contact_id)
    )
    last_ids = select(func.max(OutreachMessage.id)).where(*mine).group_by(OutreachMessage.contact_id)
    last = session.execute(
        select(OutreachMessage.contact_id, OutreachMessage.body).where(OutreachMessage.id.in_(last_ids))
    )
    return {cid: n for cid, n in unread}, {cid: hide_phones(body)[:LAST_LINE_CHARS] for cid, body in last}


def _dashed(number: str | None) -> str | None:
    """저장 꼴(01000000199) → 010-0000-0199. 앞자리 나누기는 phone.mask 의 것을 쓴다. 나눌 수 없으면 저장된 그대로."""
    if number is None:
        return None
    area, sep, _ = phone.mask(number).partition("-****-")
    if not sep:
        return number
    return f"{area}-{number[len(area):-4]}-{number[-4:]}"


def _company_out(row: ContactCompany) -> CompanyOut:
    return CompanyOut(id=row.id, name=row.name, trade=row.trade, note=row.note, hidden=row.hidden)


def _brief(row: Contact, unread: dict[int, int], last: dict[int, str]) -> PersonBrief:
    return PersonBrief(
        id=row.id, name=row.name, role_title=row.role_title, company_id=row.company_id,
        phone_masked=phone.mask(row.phone), has_phone=bool(row.phone),
        channels=[channel for channel, flag in _CHANNELS if getattr(row, flag)], unread=unread.get(row.id, 0),
        do_not_contact=row.do_not_contact, phone_invalid=row.phone_invalid, last_line=last.get(row.id),
        hidden=row.hidden,
    )


def _linked(session: Session, schedule_id: int, contact_id: int) -> list[ActivityRef]:
    """이 일정에서 이 사람과 주고받은 메시지·통화에 연결된 작업(지금 버전에 있는 것, 일정 차례)."""
    ids: set[str] = set()
    for table in (OutreachMessage, OutreachCall):
        ids.update(session.scalars(select(table.activity_id).where(
            table.schedule_id == schedule_id, table.contact_id == contact_id, table.activity_id.is_not(None))))
    if not ids:
        return []
    schedule, _, _ = load(session, schedule_id)
    return [ActivityRef(id=a.id, name=a.name) for a in schedule.activities if a.id in ids]


def _detail(session: Session, schedule_id: int, row: Contact) -> PersonDetail:
    unread, last = _threads(session, schedule_id, row.id)
    calendar, now = contacts.calendar_of(session, schedule_id), _now()
    return PersonDetail(
        **_brief(row, unread, last).model_dump(),
        hours=row.hours_json,
        working_now=work_hours.is_working(row.hours_json, calendar, now),
        hours_label=work_hours.label(row.hours_json, calendar, now),
        gender=row.gender, language=row.language, voice_mode=row.voice_mode, voice_id=row.voice_id,
        dnc_reason=row.dnc_reason, note=row.note, linked_activities=_linked(session, schedule_id, row.id),
    )


# ── 길 ─────────────────────────────────────────────────────────────────────────

def address_book(session: Session, schedule_id: int, include_hidden: bool) -> AddressBookOut:
    """협력사별 사람(이름 순). 숨긴 협력사·사람은 include_hidden 일 때만. 셈은 이 일정 것만."""
    _schedule(session, schedule_id)
    unread, last = _threads(session, schedule_id)
    groups = [
        CompanyGroup(**_company_out(company).model_dump(), people=[_brief(p, unread, last) for p in people])
        for company, people in contacts.listed(session, schedule_id, include_hidden=include_hidden)
    ]
    pending = session.scalar(select(func.count()).select_from(ContactProposal).where(
        ContactProposal.schedule_id == schedule_id, ContactProposal.status == "pending"))
    reports = session.scalar(select(func.count()).select_from(ContactReport).where(
        ContactReport.schedule_id == schedule_id, ContactReport.status == "open"))
    return AddressBookOut(companies=groups, proposals_pending=pending, reports_open=reports)


def create_company(session: Session, schedule_id: int, body: CompanyIn) -> CompanyOut:
    _schedule(session, schedule_id)
    row = ContactCompany(schedule_id=schedule_id, **body.model_dump())
    session.add(row)
    session.commit()
    return _company_out(row)


def patch_company(session: Session, schedule_id: int, company_id: int, body: CompanyPatch) -> CompanyOut:
    row = _company(session, schedule_id, company_id)
    for column, value in body.model_dump(exclude_unset=True).items():
        setattr(row, column, value)
    session.commit()
    return _company_out(row)


def create_person(session: Session, schedule_id: int, body: PersonIn) -> PersonDetail:
    number, hours_json = check_phone(body.phone), check_hours(body.hours)
    _company(session, schedule_id, body.company_id)
    row = Contact(schedule_id=schedule_id, phone=number, hours_json=hours_json,
                  **body.model_dump(exclude={"phone", "hours"}))
    session.add(row)
    session.commit()
    return _detail(session, schedule_id, row)


def patch_person(session: Session, schedule_id: int, contact_id: int, body: PersonPatch) -> PersonDetail:
    """보낸 칸만. 숨기기는 hidden. 검사(번호·근무시간·협력사)를 모두 마친 뒤에 고친다."""
    row = _person(session, schedule_id, contact_id)
    fields = body.model_dump(exclude_unset=True, exclude={"phone", "hours"})
    sent = body.model_fields_set
    number = check_phone(body.phone) if "phone" in sent else row.phone
    if "hours" in sent:
        fields["hours_json"] = check_hours(body.hours)
    if "company_id" in fields:
        _company(session, schedule_id, fields["company_id"])
    if number != row.phone:
        fields.update(phone=number, phone_invalid=False)
    for column, value in fields.items():
        setattr(row, column, value)
    session.commit()
    return _detail(session, schedule_id, row)


def person(session: Session, schedule_id: int, contact_id: int) -> PersonDetail:
    return _detail(session, schedule_id, _person(session, schedule_id, contact_id))


def reveal(session: Session, schedule_id: int, contact_id: int, user: User) -> RevealOut:
    """전체 번호를 보이는 단 한 곳. 누가 어느 연락처를 봤는지 로그 한 줄(번호 없이)."""
    row = _person(session, schedule_id, contact_id)
    logger.info("번호 보기: 사용자 %s · 연락처 %s", user.id, row.id)
    return RevealOut(phone=_dashed(row.phone))


def mark_read(session: Session, schedule_id: int, contact_id: int) -> ReadOut:
    """이 일정에서 이 사람에게서 받은 메시지 가운데 읽지 않은 것을 읽음으로."""
    row = _person(session, schedule_id, contact_id)
    done = session.execute(update(OutreachMessage).where(
        OutreachMessage.schedule_id == schedule_id, OutreachMessage.contact_id == row.id,
        OutreachMessage.direction == "in", OutreachMessage.read_at.is_(None),
    ).values(read_at=_now()))
    session.commit()
    return ReadOut(read=done.rowcount)
