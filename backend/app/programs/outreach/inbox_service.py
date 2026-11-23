"""들어온 문자 화면 API(계획 4 Task 85): 모르는 번호 묶음 · 확인할 보고 · 연락처 제안 · 긴급 보고 알림.

- 번호: 응답은 가린 꼴(phone.mask)과 peer_key 뿐. 글(받은 문자·요약·보고·이름)은 내보낼 때 redact.hide_phones 를 거친다
  (저장된 보고 글은 이미 가렸지만 받은 문자 원문은 아니다). 묶음·주소록에 넣기는 peer_key 로 가리키고, 번호는 서버가 찾는다.
- 모르는 번호 = 일정 없는 문자·통화 줄(store.outreach.unknown_messages·unknown_calls)을 번호로 묶은 것. 표마다 최근
  SCAN_ROWS 줄까지 본다(그보다 오래된 줄은 묶음에 들지 않는다).
- 격리: 일정의 보고 목록에는 그 일정 줄만, 일정 없는 보고는 따로 된 길로만. 제안 목록은 그 일정의 것 + 일정 없는 것(모르는 번호가
  알려 준 새 연락처 — 받아들이면 지금 일정에 든다). 다른 일정의 줄은 없는 것과 같은 404.
- 사람 만들기·언어 바꾸기는 주소록 서비스(사람 양식과 같은 검사 — check_texts·check_phone·check_channels·협력사 격리)로만 한다.
  검사는 줄을 바꾸기 전에 끝내고, 제안은 조건부 UPDATE 하나로 한 번만 정한다.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone
from app.outreach.redact import hide_phones
from app.outreach.text.responder import HELD_REASON
from app.programs.contacts import service as address_book
from app.programs.contacts.schemas import CompanyIn, PersonDetail, PersonIn, PersonPatch
from app.store import contacts, outreach
from app.store.schedules import NotFound, get_record
from app.store.tables import ScheduleRecord, User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactProposal,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

SCAN_ROWS = 500  # 모르는 번호 묶음 — 표마다 보는 최근 줄 수
LIST_ROWS = 200  # 보고·제안 목록 한 번에(새것부터)
LINE_CHARS = 60  # 묶음의 마지막 글
ALERT_WINDOW = timedelta(hours=1)  # since 가 없을 때(처음 물을 때) 돌아보는 시간
ALERT_ROWS = 20
REPORT_KINDS = ("delay", "problem", "change_request", "message", "emergency", "review", "other")

PEER_404 = "그 상대를 찾을 수 없습니다."
REPORT_404 = "보고를 찾을 수 없습니다."
PROPOSAL_404 = "제안을 찾을 수 없습니다."
SCHEDULE_404 = "일정을 찾을 수 없습니다."


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: str | None) -> str:
    return hide_phones(value or "")


def _key(number: str | None) -> str:
    return phone.peer_key(number or phone.NO_NUMBER)


def _schedule(session: Session, schedule_id: int) -> ScheduleRecord:
    try:
        return get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_404) from None


# ── 꼴 ──────────────────────────────────────────────────────────────────────

class EventOut(BaseModel):
    rule: str
    verdict: str
    detail: str | None


class UnknownPeerOut(BaseModel):
    """모르는 번호 한 묶음. last_kind·last_direction 은 마지막 줄의 것(통화면 글은 요약 — 없으면 "")."""

    peer_key: str
    number_masked: str
    last_at: datetime
    messages: int
    calls: int
    last_line: str
    last_kind: Literal["message", "call"]
    last_direction: str
    blocked: bool  # 관리자 차단 목록에 있음
    known: bool  # 지금 어느 주소록에든(숨기지 않은 사람으로) 있음


class PeerLineOut(BaseModel):
    kind: Literal["message", "call"]
    id: int
    direction: str
    at: datetime
    text: str  # 문자 글 또는 통화 요약(번호 가림)
    status: str
    message_kind: str | None  # 문자만: normal | auto_reply | notice | dnc_confirm
    events: list[EventOut]


class UnknownDetailOut(BaseModel):
    peer_key: str
    number_masked: str
    blocked: bool
    known: bool
    lines: list[PeerLineOut]  # 오래된 것부터


class AddPeerIn(BaseModel):
    """모르는 번호를 지금 일정 주소록에 — 협력사는 고르거나(company_id) 새로 만든다(company_name), 둘 가운데 하나."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(max_length=100)
    role_title: str = Field(default="", max_length=100)
    company_id: int | None = None
    company_name: str | None = Field(default=None, max_length=100)


class AcceptIn(BaseModel):
    """제안 받아들이기. 새 연락처는 협력사 하나(company_id | company_name), name·role_title 을 주면 제안 글 대신 쓴다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company_id: int | None = None
    company_name: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    role_title: str | None = Field(default=None, max_length=100)


class ReportOut(BaseModel):
    id: int
    schedule_id: int | None
    medium: str  # sms | call — 화면은 「문자로 받은 보고」/「전화로 받은 보고」
    kind: str  # delay | problem | change_request | message | emergency | review | other
    text: str
    quote: str  # 들은 말(번호 가림)
    quote_found: bool  # 들은 말이 받아쓰기·받은 글에서 찾아짐(근거)
    status: str  # open | reviewed
    contact_id: int | None
    contact_name: str | None
    peer_masked: str | None  # 연락처가 없을 때 그 줄의 상대(가린 꼴)
    peer_key: str | None  # 그때 「모르는 번호」 묶음으로 가는 손잡이
    message_id: int | None
    call_id: int | None
    draft_id: int | None  # kind review: 뒤 확인에 걸려 남은 답 초안(「확인 뒤 보내기」)
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None


class ProposalOut(BaseModel):
    id: int
    kind: str  # new | language
    schedule_id: int | None  # None = 모르는 번호에서 온 것(받아들이면 지금 일정에)
    name: str
    role_title: str
    company_name: str
    number_masked: str | None  # kind new 의 번호(가린 꼴)
    language: str | None
    contact_id: int | None  # kind language 의 그 사람
    contact_name: str | None
    source: Literal["sms", "call"] | None  # 어디서 받았나
    created_at: datetime


class DecidedOut(BaseModel):
    id: int
    status: str


class AlertOut(BaseModel):
    """긴급 보고 하나 — 토스트 글을 만들 칸만(보고 글·번호 없음)."""

    id: int
    schedule_id: int | None
    schedule_name: str | None
    medium: str
    contact_name: str | None
    created_at: datetime


class AlertsOut(BaseModel):
    now: datetime  # 다음 물음의 since 로 쓴다(서버 시계)
    items: list[AlertOut]  # 새것부터


# ── 모르는 번호 ──────────────────────────────────────────────────────────────

def _events(log: object) -> list[EventOut]:
    if not isinstance(log, list):
        return []
    return [EventOut(rule=str(e.get("rule")), verdict=str(e.get("verdict")),
                     detail=None if e.get("detail") is None else _text(str(e.get("detail"))))
            for e in log if isinstance(e, dict)]


def _line(row: OutreachMessage | OutreachCall) -> PeerLineOut:
    is_message = isinstance(row, OutreachMessage)
    return PeerLineOut(kind="message" if is_message else "call", id=row.id, direction=row.direction,
                       at=as_utc(row.created_at), text=_text(row.body if is_message else row.summary_ko),
                       status=row.status, message_kind=row.kind if is_message else None, events=_events(row.harness_json))


def _unknown_rows(session: Session) -> list[OutreachMessage | OutreachCall]:
    rows = [*outreach.unknown_messages(session, limit=SCAN_ROWS), *outreach.unknown_calls(session, limit=SCAN_ROWS)]
    return sorted(rows, key=lambda r: (as_utc(r.created_at), r.id))


def _keyed(rows: list[OutreachMessage | OutreachCall]) -> dict[str, list[OutreachMessage | OutreachCall]]:
    """peer_key → 그 번호의 줄(오래된 것부터). 같은 번호는 한 번만 셈한다."""
    cache: dict[str | None, str] = {}
    groups: dict[str, list[OutreachMessage | OutreachCall]] = {}
    for row in rows:
        if row.peer_number not in cache:
            cache[row.peer_number] = _key(row.peer_number)
        groups.setdefault(cache[row.peer_number], []).append(row)
    return groups


def _number(rows: list[OutreachMessage | OutreachCall]) -> str | None:
    return next((r.peer_number for r in rows if r.peer_number and r.peer_number != phone.NO_NUMBER), None)


def _flags(session: Session, number: str | None, blocked: set[str]) -> tuple[bool, bool]:
    if number is None:
        return False, False
    stored = phone.normalize(number) or number
    known = any(not p.hidden for p in contacts.by_number(session, number))
    return stored in blocked, known


def unknown_list(session: Session) -> list[UnknownPeerOut]:
    blocked = set(session.scalars(select(BlockedNumber.number)))
    out = []
    for key, rows in _keyed(_unknown_rows(session)).items():
        last, number = rows[-1], _number(rows)
        is_blocked, known = _flags(session, number, blocked)
        text = last.body if isinstance(last, OutreachMessage) else last.summary_ko
        out.append(UnknownPeerOut(
            peer_key=key, number_masked=phone.mask(number), last_at=as_utc(last.created_at),
            messages=sum(isinstance(r, OutreachMessage) for r in rows), calls=sum(isinstance(r, OutreachCall) for r in rows),
            last_line=_text(text)[:LINE_CHARS], last_kind="message" if isinstance(last, OutreachMessage) else "call",
            last_direction=last.direction, blocked=is_blocked, known=known))
    return sorted(out, key=lambda p: p.last_at, reverse=True)


def _peer_rows(session: Session, key: str) -> list[OutreachMessage | OutreachCall]:
    rows = _keyed(_unknown_rows(session)).get(key)
    if not rows:
        raise ApiError(404, "peer_not_found", PEER_404)
    return rows


def unknown_detail(session: Session, key: str) -> UnknownDetailOut:
    rows = _peer_rows(session, key)
    number = _number(rows)
    is_blocked, known = _flags(session, number, set(session.scalars(select(BlockedNumber.number))))
    return UnknownDetailOut(peer_key=key, number_masked=phone.mask(number), blocked=is_blocked, known=known,
                            lines=[_line(r) for r in rows])


def add_peer(session: Session, schedule_id: int, key: str, body: AddPeerIn) -> PersonDetail:
    """[주소록에 넣기] — 번호는 peer_key 로 서버가 찾는다(화면에 내리지 않는다). 사람 양식과 같은 검사로 지금 일정에."""
    _schedule(session, schedule_id)
    if key == _key(None):
        raise ApiError(422, "peer_has_no_number", "번호가 없는 상대는 주소록에 넣을 수 없습니다.")
    number = _number(_peer_rows(session, key))
    if number is None:
        raise ApiError(422, "peer_has_no_number", "번호가 없는 상대는 주소록에 넣을 수 없습니다.")
    person = _checked_person(body.name, body.role_title, number)
    company = _checked_company(session, schedule_id, body.company_id, body.company_name)
    return _make_person(session, schedule_id, person, company)


# ── 사람 만들기(주소록 서비스로) ─────────────────────────────────────────────

def _checked_person(name: str, role_title: str, number: str | None) -> PersonIn:
    """사람 양식과 같은 꼴·검사를 줄을 바꾸기 전에(협력사는 아직 0). 값은 오류에 싣지 않는다."""
    try:
        draft = PersonIn(name=name, role_title=role_title, company_id=0)
    except ValidationError:
        raise ApiError(422, "invalid_proposal", "이름(1~100자)과 담당(100자까지)을 확인해 주세요.") from None
    address_book.check_texts(draft.model_dump())
    address_book.check_phone(number)
    return draft.model_copy(update={"phone": number})


def _checked_company(session: Session, schedule_id: int, company_id: int | None, company_name: str | None) -> int | str:
    """고른 협력사 id(이 일정 것인지 확인) 또는 새로 만들 협력사 이름(검사만 — 만들기는 나중)."""
    if (company_id is None) == (not company_name):
        raise ApiError(422, "company_required", "협력사를 고르거나 새 협력사 이름을 넣어 주세요(둘 가운데 하나).")
    if company_id is not None:
        try:
            contacts.get_company(session, schedule_id, company_id)
        except contacts.NotFound:  # 다른 일정·없는 협력사는 같은 404(주소록 API 와 같은 글)
            raise ApiError(404, "not_found", address_book.COMPANY_NOT_FOUND) from None
        return company_id
    try:
        CompanyIn(name=company_name)
    except ValidationError:
        raise ApiError(422, "invalid_company", "협력사 이름(1~100자)을 확인해 주세요.") from None
    address_book.check_texts({"name": company_name})
    return company_name


def _make_person(session: Session, schedule_id: int, person: PersonIn, company: int | str) -> PersonDetail:
    if isinstance(company, str):
        company = address_book.create_company(session, schedule_id, CompanyIn(name=company)).id
    return address_book.create_person(session, schedule_id, person.model_copy(update={"company_id": company}))


# ── 연락처 제안 ──────────────────────────────────────────────────────────────

def _proposal_out(session: Session, row: ContactProposal) -> ProposalOut:
    who = session.get(Contact, row.contact_id) if row.contact_id is not None else None
    if who is not None and who.schedule_id != row.schedule_id:
        who = None
    source = "call" if row.call_id is not None else "sms" if row.message_id is not None else None
    return ProposalOut(
        id=row.id, kind=row.kind, schedule_id=row.schedule_id, name=_text(row.name), role_title=_text(row.role_title),
        company_name=_text(row.company_name), number_masked=None if row.phone is None else phone.mask(row.phone),
        language=row.language, contact_id=who.id if who else None, contact_name=_text(who.name) if who else None,
        source=source, created_at=as_utc(row.created_at))


def _visible(schedule_id: int):
    return or_(ContactProposal.schedule_id == schedule_id, ContactProposal.schedule_id.is_(None))


def proposals(session: Session, schedule_id: int) -> list[ProposalOut]:
    _schedule(session, schedule_id)
    rows = session.scalars(select(ContactProposal).where(_visible(schedule_id), ContactProposal.status == "pending")
                           .order_by(ContactProposal.id.desc()).limit(LIST_ROWS))
    return [_proposal_out(session, r) for r in rows]


def _pending(session: Session, schedule_id: int, proposal_id: int) -> ContactProposal:
    row = session.get(ContactProposal, proposal_id)
    if row is None or not (row.schedule_id is None or row.schedule_id == schedule_id):
        raise ApiError(404, "proposal_not_found", PROPOSAL_404)
    if row.status != "pending":
        raise ApiError(409, "already_decided", "이미 정한 제안입니다.")
    return row


def _decide(session: Session, row: ContactProposal, schedule_id: int, status: str, user: User) -> None:
    """pending → status 를 한 번만(조건부 UPDATE). 일정 없는 제안은 지금 일정의 것이 된다. commit 은 부른 쪽."""
    done = session.execute(
        update(ContactProposal).where(ContactProposal.id == row.id, ContactProposal.status == "pending")
        .values(status=status, schedule_id=schedule_id, decided_by=user.name, decided_at=_now())
        .execution_options(synchronize_session=False))
    if done.rowcount != 1:
        session.rollback()
        raise ApiError(409, "already_decided", "이미 정한 제안입니다.")


def _undo(session: Session, proposal_id: int, schedule_id: int | None) -> None:
    session.rollback()
    session.execute(update(ContactProposal).where(ContactProposal.id == proposal_id)
                    .values(status="pending", schedule_id=schedule_id, decided_by=None, decided_at=None))
    session.commit()


def accept(session: Session, schedule_id: int, proposal_id: int, body: AcceptIn, user: User) -> PersonDetail:
    """new → 지금 일정에 사람(협력사는 고르거나 새로). language → 그 사람의 언어를 바꿈. 검사를 모두 지난 뒤에만 제안을 정한다."""
    _schedule(session, schedule_id)
    row = _pending(session, schedule_id, proposal_id)
    was = row.schedule_id
    if row.kind == "language":
        try:
            change = PersonPatch(language=row.language)
        except ValidationError:
            raise ApiError(422, "unsupported_language", "주소록에서 고를 수 없는 언어입니다.") from None
        if row.contact_id is None or was != schedule_id:
            raise ApiError(404, "proposal_not_found", PROPOSAL_404)
        address_book.person(session, schedule_id, row.contact_id)  # 다른 일정·지워진 사람 → 404 not_found
        _decide(session, row, schedule_id, "accepted", user)
        try:
            return address_book.patch_person(session, schedule_id, row.contact_id, change, user)
        except ApiError:
            _undo(session, proposal_id, was)
            raise
    person = _checked_person(row.name if body.name is None else body.name,
                             row.role_title if body.role_title is None else body.role_title, row.phone)
    company = _checked_company(session, schedule_id, body.company_id, body.company_name)
    _decide(session, row, schedule_id, "accepted", user)
    try:
        return _make_person(session, schedule_id, person, company)
    except ApiError:
        _undo(session, proposal_id, was)
        raise


def reject(session: Session, schedule_id: int, proposal_id: int, user: User) -> DecidedOut:
    _schedule(session, schedule_id)
    row = _pending(session, schedule_id, proposal_id)
    _decide(session, row, schedule_id, "rejected", user)
    session.commit()
    return DecidedOut(id=proposal_id, status="rejected")


# ── 확인할 보고 ──────────────────────────────────────────────────────────────

def _linked_peer(session: Session, row: ContactReport) -> str | None:
    linked = (session.get(OutreachMessage, row.message_id) if row.message_id is not None
              else session.get(OutreachCall, row.call_id) if row.call_id is not None else None)
    if linked is None or linked.schedule_id != row.schedule_id:
        return None
    return linked.peer_number


def _held_draft(session: Session, row: ContactReport) -> int | None:
    if row.kind != "review" or row.message_id is None:
        return None
    return session.scalar(select(OutreachMessage.id).where(
        OutreachMessage.reply_to_id == row.message_id, OutreachMessage.direction == "out",
        OutreachMessage.status == "draft", OutreachMessage.fail_reason == HELD_REASON,
        OutreachMessage.schedule_id.is_(None) if row.schedule_id is None else OutreachMessage.schedule_id == row.schedule_id,
    ).order_by(OutreachMessage.id.desc()).limit(1))


def _report_out(session: Session, row: ContactReport) -> ReportOut:
    who = session.get(Contact, row.contact_id) if row.contact_id is not None else None
    if who is not None and who.schedule_id != row.schedule_id:
        who = None
    number = None if who is not None else _linked_peer(session, row)
    return ReportOut(
        id=row.id, schedule_id=row.schedule_id, medium=row.medium, kind=row.kind, text=_text(row.text),
        quote=_text(row.quote), quote_found=row.quote_found, status=row.status, contact_id=who.id if who else None,
        contact_name=_text(who.name) if who else None, peer_masked=None if number is None else phone.mask(number),
        peer_key=None if number is None else _key(number), message_id=row.message_id, call_id=row.call_id,
        draft_id=_held_draft(session, row), created_at=as_utc(row.created_at), reviewed_by=row.reviewed_by,
        reviewed_at=None if row.reviewed_at is None else as_utc(row.reviewed_at))


def _where_schedule(schedule_id: int | None):
    return ContactReport.schedule_id.is_(None) if schedule_id is None else ContactReport.schedule_id == schedule_id


def reports(session: Session, schedule_id: int | None, status: str) -> list[ReportOut]:
    """schedule_id 가 None 이면 일정 없는 보고. status: open | reviewed | all. 새것부터 LIST_ROWS 줄까지."""
    if schedule_id is not None:
        _schedule(session, schedule_id)
    stmt = select(ContactReport).where(_where_schedule(schedule_id))
    if status != "all":
        stmt = stmt.where(ContactReport.status == status)
    rows = session.scalars(stmt.order_by(ContactReport.created_at.desc(), ContactReport.id.desc()).limit(LIST_ROWS))
    return [_report_out(session, r) for r in rows]


def review(session: Session, schedule_id: int | None, report_id: int, user: User) -> ReportOut:
    """[확인함] — open → reviewed 한 번만. 다른 일정(또는 일정 있는 보고를 일정 없는 길로)은 404."""
    row = session.get(ContactReport, report_id)
    if row is None or row.schedule_id != schedule_id:
        raise ApiError(404, "report_not_found", REPORT_404)
    done = session.execute(
        update(ContactReport).where(ContactReport.id == report_id, ContactReport.status == "open")
        .values(status="reviewed", reviewed_by=user.name, reviewed_at=_now()).execution_options(synchronize_session=False))
    if done.rowcount != 1:
        session.rollback()
        raise ApiError(409, "already_reviewed", "이미 확인한 보고입니다.")
    session.commit()
    session.refresh(row)
    return _report_out(session, row)


# ── 긴급 보고 알림 ───────────────────────────────────────────────────────────

def alerts(session: Session, since: datetime | None) -> AlertsOut:
    """확인하지 않은 긴급 보고(kind emergency) 가운데 since 뒤(같은 때 포함) 것. since 가 없으면 ALERT_WINDOW 안."""
    now = _now()
    floor = now - ALERT_WINDOW if since is None else as_utc(since)
    rows = session.scalars(select(ContactReport).where(
        ContactReport.kind == "emergency", ContactReport.status == "open", ContactReport.created_at >= floor)
        .order_by(ContactReport.created_at.desc(), ContactReport.id.desc()).limit(ALERT_ROWS))
    items = []
    for row in rows:
        record = session.get(ScheduleRecord, row.schedule_id) if row.schedule_id is not None else None
        who = session.get(Contact, row.contact_id) if row.contact_id is not None else None
        name = _text(who.name) if who is not None and who.schedule_id == row.schedule_id else None
        items.append(AlertOut(id=row.id, schedule_id=row.schedule_id, schedule_name=_text(record.name) if record else None,
                              medium=row.medium, contact_name=name, created_at=as_utc(row.created_at)))
    return AlertsOut(now=now, items=items)
