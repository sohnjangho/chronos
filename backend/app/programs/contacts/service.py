"""주소록(일정 = 프로젝트마다 따로): 목록·협력사·사람 쓰기·상세·번호 보기·읽음. 자세한 규칙은 계획 4 task-72-report.md.

- 격리: 다른 일정의 협력사·사람 id(본문의 company_id 도)는 없는 id 와 같은 404·같은 글.
- 번호: 응답은 가린 꼴만. 전체 번호는 reveal 한 곳 — DB 기록(store.contact_reveals, 번호 없음, 사용자마다 10분 30번 —
  세기와 넣기가 한 문장)과 로그 한 줄. 번호 규칙은 phone 모듈만(normalize·storable·can_sms·can_call), 오류 글에 값 없음.
- 채널(check_channels): 문자·카카오톡은 phone.can_sms, 전화는 phone.can_call. 만들 때·번호가 바뀔 때 보내지 않은 칸은 그 값.
- 수신 거부(_settle_do_not_contact): 번호가 걸리면 늘 번호 기록이 있다. 번호를 바꾸거나 빼면 옛 번호에 남고 새 번호로
  따라가지 않는다. 번호 기록을 지우는 것은 관리자의 끄기(clear_do_not_contact)뿐.
- 글자(check_texts): 글은 NFC 로 바꾼 뒤(schemas.Nfc) 본다. 이름·담당·공종에 Cc·Cf·Zl·Zp, 메모·까닭에 줄 바꿈·탭 밖의 Cc·
  글 방향 글자·줄/문단 구분·폭 없는 빈칸이면 422 invalid_text. 음성: manual 이면 voice_id 필요, 꼴은 영문·숫자·._:- 64자.
- 근무시간(check_hours): 요일 0~6 겹치지 않게, HH:MM, 시작 ≠ 끝(hours 모듈은 같으면 24시간으로 읽지만 잘못 넣으면 한밤
  전화가 열려 받지 않는다 — 받으려면 그 줄만 지운다). 끝 < 시작은 자정을 넘는 근무.
- 입력 검사는 모두 줄을 고치기 전에 끝낸다(검사에 걸리면 아무것도 바뀌지 않는다).
"""

import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta

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
from app.store import contact_reveals, contacts, outreach
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
NOT_STORABLE = "주소록에 둘 수 없는 번호입니다."
NUMBER_CHANNELS = {  # 칸 → (그 칸을 정하는 phone 함수, 안 될 때의 까닭)
    "can_sms": ("can_sms", "문자는 휴대전화 번호로만 보낼 수 있습니다."),
    "can_kakao": ("can_sms", "카카오톡 알림은 휴대전화 번호로만 보낼 수 있습니다."),
    "can_call": ("can_call", "이 번호로는 전화를 걸 수 없습니다."),
}
ADMIN_CLEARS = "수신 거부는 관리자만 풀 수 있습니다(이 번호가 있는 모든 프로젝트에서 풀립니다)."
TOO_MANY_REVEALS = "번호 보기는 10분에 30번까지입니다. 잠시 뒤에 다시 해 주세요."
REVEAL_LIMIT, REVEAL_WINDOW = 30, timedelta(minutes=10)  # 리뷰 판정(감사·남용 막기) — 연락 한도(limits)와 따로
LINE_FIELDS = ("name", "role_title", "trade")  # 화면 머리·프롬프트·첫마디에 한 줄로 들어가는 글
FREE_FIELDS = ("note", "dnc_reason")
LINE_TEXT = "이름·담당·공종에는 줄 바꿈이나 보이지 않는 제어 글자를 쓸 수 없습니다."
FREE_TEXT = "메모·까닭에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다."
NO_VOICE = "음성을 직접 지정하려면 음성을 골라 주세요."
VOICE_SHAPE = "음성 id 는 영문·숫자와 . _ : - 로 64자까지입니다."
_VOICE_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_LINE_BAD = frozenset({"Cc", "Cf", "Zl", "Zp"})
# 메모에서 막는 보이지 않는 글자: 글 방향 바꾸기·표시(Bidi_Control 전부), 줄·문단 구분, 폭 없는 빈칸
_FREE_HIDDEN = (frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))
                | {0x200E, 0x200F, 0x061C, 0x2028, 0x2029, 0x200B})
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
    """입력 번호 → 저장 꼴(숫자만). 비면 None. 번호인지는 phone.normalize, 둘 수 있는지는 phone.storable — 아니면 422(값 없이)."""
    if raw is None or not raw.strip():
        return None
    number = phone.normalize(raw)
    if number is None:
        raise ApiError(422, "invalid_phone", BAD_PHONE)
    if not phone.storable(number):
        raise ApiError(422, "invalid_phone", NOT_STORABLE)
    return number


def check_channels(number: str | None, sent: dict[str, bool], renumbered: bool) -> dict[str, bool]:
    """can_sms·can_kakao·can_call 의 새 값(바꿀 칸만). sent = 요청이 보낸 칸. 참으로 보냈는데 그 칸의 phone 함수(번호)가
    거짓이면 422. 번호가 새로 정해지면(만들기·번호 바뀜) 보내지 않은 칸은 그 함수의 값. 번호가 없으면 모두 거짓."""
    out: dict[str, bool] = {}
    for column, (predicate, why) in NUMBER_CHANNELS.items():
        possible = getattr(phone, predicate)(number)
        if sent.get(column) and not possible:
            raise ApiError(422, "channel_not_possible", why)
        if column in sent:
            out[column] = sent[column]
        elif renumbered:
            out[column] = possible
    return out


def check_hours(given: HoursIn | None) -> dict | None:
    """근무시간 입력 → hours_json. None 은 프로젝트 기본. 규칙은 모듈 머리 글(시작 == 끝은 받지 않음)."""
    if given is None:
        return None
    days = given.days
    if not days or len(set(days)) != len(days) or any(day < 0 or day > 6 for day in days):
        raise ApiError(422, "invalid_hours", BAD_DAYS)
    if not (_HHMM.fullmatch(given.start) and _HHMM.fullmatch(given.end)):
        raise ApiError(422, "invalid_hours", BAD_TIME)
    if given.start == given.end:
        raise ApiError(422, "invalid_hours", SAME_TIME)
    return {"days": sorted(days), "start": given.start, "end": given.end}


def _free_bad(char: str) -> bool:
    return ord(char) in _FREE_HIDDEN or (unicodedata.category(char) == "Cc" and char not in "\n\t")


def check_texts(values: dict) -> None:
    """이름·담당·공종(한 줄 글)과 메모·까닭(자유 글)의 글자 검사(모듈 머리 글). 걸리면 422 invalid_text, 값은 싣지 않는다."""
    for field, value in values.items():
        if not isinstance(value, str):
            continue
        if field in LINE_FIELDS and any(unicodedata.category(char) in _LINE_BAD for char in value):
            raise ApiError(422, "invalid_text", LINE_TEXT, detail={"field": field})
        if field in FREE_FIELDS and any(_free_bad(char) for char in value):
            raise ApiError(422, "invalid_text", FREE_TEXT, detail={"field": field})


def check_voice(voice_mode: str, voice_id: str | None) -> None:
    if voice_mode == "manual" and not voice_id:
        raise ApiError(422, "invalid_voice", NO_VOICE)
    if voice_id is not None and not _VOICE_ID.fullmatch(voice_id):
        raise ApiError(422, "invalid_voice", VOICE_SHAPE)


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
    """저장 꼴 → 010-0000-0199 · 1588-0199. 앞 조각은 phone.mask 의 첫 조각(앞자리, 대표번호는 앞 4자리), 끝은 4자리,
    그 사이가 가운데. 나눌 수 없으면 저장된 그대로. 대표번호(8자리)는 가린 꼴과 상관없이 앞 4 · 뒤 4."""
    if number is None:
        return None
    if phone.kind(number) == "rep":
        return f"{number[:4]}-{number[4:]}"
    head, sep, _ = phone.mask(number).partition("-")
    if not sep or not number.startswith(head) or len(number) < len(head) + 4:
        return number
    return "-".join(part for part in (head, number[len(head):-4], number[-4:]) if part)


def _shows_do_not_contact(session: Session, row: Contact) -> bool:
    """이 연락처의 표시 또는 그 번호의 수신 거부(store.outreach.is_do_not_contact)."""
    return bool(row.do_not_contact) or (row.phone is not None and outreach.is_do_not_contact(session, row.phone))


def _mark(session: Session, number: str | None, reason: str | None) -> None:
    """번호 기록을 남긴다(번호가 없거나 정리되지 않으면 — 예전 입력 — 넘어간다. purge_schedule 과 같은 규칙)."""
    if number and phone.normalize(number) is not None:
        outreach.mark_do_not_contact(session, number, reason=reason or "")


def _settle_do_not_contact(session: Session, row: Contact, old: str | None, shown: bool, wanted: bool | None) -> None:
    """요청을 줄에 옮긴 뒤(row.phone 은 새 번호) 수신 거부를 번호 기록으로 맞춘다 — 번호가 걸리면 늘 번호 기록이 있다.
    shown = 요청 전에 보이던 값, wanted = 요청의 do_not_contact(보내지 않았으면 None). 관리자 확인은 부른 쪽이 먼저 한다.
    - 끄기(wanted False 이고 보이던 것): 옛 번호의 기록·표시를 모든 곳에서 지우고 이 줄 표시·까닭을 지운다.
    - 번호를 바꾸거나 뺌: 보이던(또는 이번에 켠) 수신 거부는 옛 번호의 기록으로 남긴다. 이번에 켜지 않았으면 이 줄 표시는
      내린다 — 새 번호로 따라가지 않는다(옛 번호는 기록으로 막힌 채).
    - 그 뒤 이 줄에 표시가 있고 번호가 있으면 그 번호의 기록을 남긴다(번호 없이 막아 둔 사람에게 번호가 들어온 때 포함)."""
    if wanted is False and shown:
        if old:
            outreach.clear_do_not_contact(session, old)
        row.do_not_contact, row.dnc_reason = False, None
        return
    if old is not None and row.phone != old:
        if shown or wanted:
            _mark(session, old, row.dnc_reason)
        if not wanted:
            row.do_not_contact, row.dnc_reason = False, None
    if wanted:
        row.do_not_contact = True
    if row.do_not_contact:
        _mark(session, row.phone, row.dnc_reason)


def _company_out(row: ContactCompany) -> CompanyOut:
    return CompanyOut(id=row.id, name=row.name, trade=row.trade, note=row.note, hidden=row.hidden)


def _brief(row: Contact, unread: dict[int, int], last: dict[int, str], do_not_contact: bool) -> PersonBrief:
    return PersonBrief(
        id=row.id, name=row.name, role_title=row.role_title, company_id=row.company_id,
        phone_masked=phone.mask(row.phone), has_phone=bool(row.phone), phone_kind=phone.kind(row.phone),
        channels=[channel for channel, flag in _CHANNELS if getattr(row, flag)], unread=unread.get(row.id, 0),
        do_not_contact=do_not_contact, phone_invalid=row.phone_invalid, last_line=last.get(row.id),
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
        **_brief(row, unread, last, _shows_do_not_contact(session, row)).model_dump(),
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
    listed = contacts.listed(session, schedule_id, include_hidden=include_hidden)
    refused = outreach.do_not_contact_numbers(session, [p.phone for _, people in listed for p in people if p.phone])
    groups = [
        CompanyGroup(**_company_out(company).model_dump(), people=[
            _brief(p, unread, last, p.do_not_contact or phone.normalize(p.phone) in refused) for p in people])
        for company, people in listed
    ]
    pending = session.scalar(select(func.count()).select_from(ContactProposal).where(
        ContactProposal.schedule_id == schedule_id, ContactProposal.status == "pending"))
    reports = session.scalar(select(func.count()).select_from(ContactReport).where(
        ContactReport.schedule_id == schedule_id, ContactReport.status == "open"))
    return AddressBookOut(companies=groups, proposals_pending=pending, reports_open=reports)


def create_company(session: Session, schedule_id: int, body: CompanyIn) -> CompanyOut:
    check_texts(body.model_dump())
    _schedule(session, schedule_id)
    row = ContactCompany(schedule_id=schedule_id, **body.model_dump())
    session.add(row)
    session.commit()
    return _company_out(row)


def patch_company(session: Session, schedule_id: int, company_id: int, body: CompanyPatch) -> CompanyOut:
    fields = body.model_dump(exclude_unset=True)
    check_texts(fields)
    row = _company(session, schedule_id, company_id)
    for column, value in fields.items():
        setattr(row, column, value)
    session.commit()
    return _company_out(row)


def create_person(session: Session, schedule_id: int, body: PersonIn) -> PersonDetail:
    """번호 종류로 채널을 정하고, 수신 거부로 만들면 그 번호에 mark_do_not_contact(_settle_do_not_contact)."""
    given = body.model_dump()
    check_texts(given)
    number, hours_json = check_phone(body.phone), check_hours(body.hours)
    channels = check_channels(number, {c: given[c] for c in NUMBER_CHANNELS if given[c] is not None}, renumbered=True)
    check_voice(body.voice_mode, body.voice_id)
    _company(session, schedule_id, body.company_id)
    row = Contact(schedule_id=schedule_id, phone=number, hours_json=hours_json, **channels,
                  **body.model_dump(exclude={"phone", "hours", "do_not_contact", *NUMBER_CHANNELS}))
    session.add(row)
    _settle_do_not_contact(session, row, None, False, body.do_not_contact)
    session.commit()
    return _detail(session, schedule_id, row)


def patch_person(
    session: Session, schedule_id: int, contact_id: int, body: PersonPatch, user: User
) -> PersonDetail:
    """보낸 칸만. 숨기기는 hidden. 검사(글자·번호·근무시간·채널·음성·협력사·수신 거부 풀기 권한)를 모두 마친 뒤에 고치고,
    수신 거부를 번호 기록으로 맞춘다(_settle_do_not_contact). 보이던 수신 거부를 끄는 것은 관리자만."""
    row = _person(session, schedule_id, contact_id)
    given = body.model_dump(exclude_unset=True)
    check_texts(given)
    old = row.phone
    number = check_phone(body.phone) if "phone" in given else old
    fields = {k: v for k, v in given.items() if k not in {"phone", "hours", "do_not_contact", *NUMBER_CHANNELS}}
    if "hours" in given:
        fields["hours_json"] = check_hours(body.hours)
    fields.update(check_channels(number, {c: given[c] for c in NUMBER_CHANNELS if c in given}, renumbered=number != old))
    if given.keys() & {"voice_mode", "voice_id"}:
        check_voice(fields.get("voice_mode", row.voice_mode), fields.get("voice_id", row.voice_id))
    if "company_id" in fields:
        _company(session, schedule_id, fields["company_id"])
    shown = _shows_do_not_contact(session, row)
    if body.do_not_contact is False and shown and user.role != "admin":
        raise ApiError(403, "admin_only", ADMIN_CLEARS)
    if number != old:
        fields.update(phone=number, phone_invalid=False)
    for column, value in fields.items():
        setattr(row, column, value)
    _settle_do_not_contact(session, row, old, shown, body.do_not_contact)
    session.commit()
    return _detail(session, schedule_id, row)


def person(session: Session, schedule_id: int, contact_id: int) -> PersonDetail:
    return _detail(session, schedule_id, _person(session, schedule_id, contact_id))


def reveal(session: Session, schedule_id: int, contact_id: int, user: User) -> RevealOut:
    """전체 번호를 보이는 단 한 곳. 사용자마다 10분에 30번까지(넘으면 429, 기록하지 않음). 볼 때마다 DB 에 한 줄
    (record_reveal — 번호 없이)과 로그 한 줄."""
    row = _person(session, schedule_id, contact_id)
    if not contact_reveals.record_reveal(session, schedule_id=schedule_id, contact_id=row.id, user_id=user.id,
                                         login_id=user.login_id, limit=REVEAL_LIMIT, window=REVEAL_WINDOW, at=_now()):
        session.rollback()  # 쓰기 잠금을 바로 놓는다
        raise ApiError(429, "too_many_reveals", TOO_MANY_REVEALS)
    session.commit()
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
