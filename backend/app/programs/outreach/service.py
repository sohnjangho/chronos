"""메시지 API(계획 4 Task 73): 한 사람과의 대화 읽기, 초안 쓰기·고치기·지우기, 보내기·예약, 예약 취소, 다시 보내기.

- **보내기는 나가는 문 하나**: 이 모듈은 통로를 부르지 않는다. 자기 쓰기를 commit 한 뒤 `gate.dispatch("message", id, actor)`
  를 부르고, 문이 준 판정(code·message·scheduled_at)을 그대로 돌려준다 — 막힌 것도 결과라 늘 200. `unsure` 는 「보냈는지
  확인 필요」(줄 unconfirmed)로 두고 다시 보내지 않는다. 문의 `duplicate`(차지하지 못함 — 「잠시 뒤 다시」)도 그대로.
- **격리**: 문은 일정 id 를 받지 않으므로 줄을 건드리는 길은 모두 먼저 `store.outreach.get_message(일정, id)` 로 그 일정의
  줄인지 본다(아니면 404, 문을 부르지 않음). 본문의 연락처·작업·현장 항목·승인 건도 그 일정 것이어야 한다(아니면 같은 404).
- **Actor 는 로그인한 사람에게서만**: `Actor("user", user.id, user.name, user.role)`. 에이전트·일꾼 Actor 는 만들지 않는다.
- **다시 보내기는 새 줄**: failed·unconfirmed 줄만, 같은 연락처·채널·글의 새 초안(옛 줄은 그대로). 보내지는 않는다.
- **에이전트 초안을 사람이 고치거나 보내면** kind auto_reply·notice 는 normal 로 바뀐다(문은 사람이 보낸 자동 답을 거절한다).
  origin·origin_name 은 그대로 남고, approved_by 는 문이 보낼 때 누른 사람의 이름으로 적는다(send_mode approved).
- 상태를 바꾸는 쓰기(고치기·지우기·취소)는 `UPDATE/DELETE … WHERE status = …` 한 문장이다 — 그 사이 문이나 일꾼이 줄을
  가져갔으면 아무것도 바꾸지 않고 409.
- 번호: 응답에 번호 칸이 없다(연락처는 가린 꼴). 받은 글(상대가 쓴 것)은 hide_phones 를 거쳐 보인다. 사람·에이전트가 쓴 글은
  저장된 그대로. 오류 글에는 받은 값을 싣지 않는다.
"""

import unicodedata
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import drafting, phone
from app.outreach.harness import gate
from app.outreach.harness import registry as channels
from app.outreach.harness.types import Actor, Outcome
from app.outreach.redact import hide_phones
from app.programs.outreach.schemas import (
    BODY_MAX,
    ActivityOut,
    AgentDraftIn,
    BatchOut,
    ChatOut,
    ContactBrief,
    EventOut,
    MessageIn,
    MessageOut,
    MessagePatch,
    MessageResult,
    OutcomeOut,
    ResendOut,
    ThreadOut,
)
from app.store import contacts, outreach
from app.store.schedules import NotFound, load
from app.store.tables import Approval, ChatSession, FieldItem, User
from app.store.tables_outreach import Contact, KakaoTemplate, OutreachMessage
from app.store.timeutil import as_utc

PERSON_NOT_FOUND = "연락처를 찾을 수 없습니다."
MESSAGE_NOT_FOUND = "메시지를 찾을 수 없습니다."
ACTIVITY_NOT_FOUND = "작업을 찾을 수 없습니다."
FIELD_ITEM_NOT_FOUND = "현장 항목을 찾을 수 없습니다."
APPROVAL_NOT_FOUND = "승인 건을 찾을 수 없습니다."
TEMPLATE_NOT_FOUND = "알림톡 문안을 찾을 수 없습니다."
BAD_TEXT = "문자 글에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다."
NOT_DRAFT = "초안만 고치거나 지울 수 있습니다."
NOT_SCHEDULED = "예약된 메시지가 아닙니다."
USE_RESEND = "이미 처리된 메시지입니다. 다시 보내려면 [다시 보내기]를 눌러 주세요."
DONE = "이미 처리된 메시지입니다."
NOT_RESENDABLE = "실패했거나 확인이 필요한 메시지만 다시 보낼 수 있습니다."
MAY_HAVE_GONE = "이미 나갔을 수 있습니다"
# 에이전트 초안(대화 에이전트 도구와 [에이전트에게 초안 맡기기]가 같이 쓴다 — create_agent_draft)
AGENT_NAME = "에이전트"
DO_NOT_CONTACT = "이 사람은 수신 거부라 연락 초안을 만들 수 없습니다."
NO_NUMBER = "이 연락처에는 쓸 수 있는 전화번호가 없어 초안을 만들 수 없습니다. 번호는 사람이 연락처 창에서 넣습니다."
KAKAO_LOCKED = "카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다 — 문자로 초안을 만드세요."
NO_SMS = "이 연락처는 문자를 받을 수 없습니다(휴대전화 번호가 아니거나 문자 받기가 꺼져 있음)."
NO_KAKAO = "이 연락처는 카카오톡 받기가 꺼져 있습니다 — 문자로 초안을 만드세요."
BAD_LENGTH = f"글은 1~{BODY_MAX}자여야 합니다."
DRAFT_FAILED = "초안을 만들지 못했습니다 — 잠시 뒤 다시 눌러 주세요."
LLM_NOT_READY = "LLM 연결이 필요합니다. 설정에서 연결해 주세요."  # 대화 에이전트(agent.loop.NOT_READY)와 같은 글
DRAFT_BUSY = "이 사람의 초안을 이미 만드는 중입니다. 끝난 뒤 다시 눌러 주세요."
SENDABLE = ("draft", "scheduled", "sending")  # 문에 넘기는 상태(sending 은 문이 「잠시 뒤 다시」로 답한다)
RESENDABLE = ("failed", "unconfirmed")
AUTO_KINDS = ("auto_reply", "notice")  # 사람이 고치거나 보내면 normal 이 된다
KIND_OPEN = ("draft", "scheduled")  # 종류를 바꿔도 되는 상태(나가는 중인 줄은 그대로)
LAST_LINE_CHARS = 30  # 주소록 API 의 last_line 과 같은 길이
# 글에서 막는 보이지 않는 글자(주소록 메모와 같은 규칙): 줄 바꿈·탭 밖의 제어 글자, 글 방향 글자 전부, 줄·문단 구분, 폭 없는 빈칸
_HIDDEN = (frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))
           | {0x200E, 0x200F, 0x061C, 0x2028, 0x2029, 0x200B})
_CHANNELS = (("sms", "can_sms"), ("kakao", "can_kakao"), ("call", "can_call"))


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(user: User) -> Actor:
    """누른 사람. 요청의 값이 아니라 로그인한 세션의 사용자에게서만 만든다."""
    return Actor("user", user.id, user.name, user.role)


# ── 찾기·검사 ────────────────────────────────────────────────────────────────


def _contact(session: Session, schedule_id: int, contact_id: int) -> Contact:
    try:
        return contacts.get_contact(session, schedule_id, contact_id)
    except contacts.NotFound:
        raise ApiError(404, "not_found", PERSON_NOT_FOUND) from None


def _message(session: Session, schedule_id: int, message_id: int) -> OutreachMessage:
    try:
        return outreach.get_message(session, schedule_id, message_id)
    except outreach.NotFound:
        raise ApiError(404, "not_found", MESSAGE_NOT_FOUND) from None


def _bad_char(char: str) -> bool:
    return ord(char) in _HIDDEN or (unicodedata.category(char) == "Cc" and char not in "\n\t")


def check_body(*texts: str | None, field: str = "body") -> None:
    """보낼 글(본문·문안 값)에 보이지 않는 글자가 있으면 422 invalid_text. 값은 싣지 않는다."""
    if any(text and any(_bad_char(char) for char in text) for text in texts):
        raise ApiError(422, "invalid_text", BAD_TEXT, detail={"field": field})


def _activity_names(session: Session, schedule_id: int) -> dict[str, str]:
    try:
        schedule, _, _ = load(session, schedule_id)
    except NotFound:
        return {}
    return {a.id: a.name for a in schedule.activities}


def _check_links(session: Session, schedule_id: int, *, activity_id: str | None = None, field_item_id: int | None = None,
                 approval_id: int | None = None, template_id: int | None = None) -> None:
    """본문의 연결 id 는 그 일정 것이어야 한다(문안은 연결마다라 있는지만). 아니면 없는 것과 같은 404."""
    if activity_id is not None and activity_id not in _activity_names(session, schedule_id):
        raise ApiError(404, "not_found", ACTIVITY_NOT_FOUND)
    item = session.get(FieldItem, field_item_id) if field_item_id is not None else None
    if field_item_id is not None and (item is None or item.schedule_id != schedule_id):
        raise ApiError(404, "not_found", FIELD_ITEM_NOT_FOUND)
    approval = session.get(Approval, approval_id) if approval_id is not None else None
    if approval_id is not None and (approval is None or approval.schedule_id != schedule_id):
        raise ApiError(404, "not_found", APPROVAL_NOT_FOUND)
    if template_id is not None and session.get(KakaoTemplate, template_id) is None:
        raise ApiError(404, "not_found", TEMPLATE_NOT_FOUND)


# ── 응답 만들기 ──────────────────────────────────────────────────────────────


def _brief(session: Session, schedule_id: int, row: Contact) -> ContactBrief:
    """주소록 API 의 PersonBrief 와 같은 값(읽지 않은 받은 수, 마지막 줄은 번호를 가린 뒤 30자, 수신 거부는 번호 기준도)."""
    mine = (OutreachMessage.schedule_id == schedule_id, OutreachMessage.contact_id == row.id)
    unread = session.scalar(select(func.count()).select_from(OutreachMessage).where(
        *mine, OutreachMessage.direction == "in", OutreachMessage.read_at.is_(None)))
    last = session.scalar(select(OutreachMessage.body).where(*mine).order_by(OutreachMessage.id.desc()).limit(1))
    refused = bool(row.do_not_contact) or (row.phone is not None and outreach.is_do_not_contact(session, row.phone))
    return ContactBrief(
        id=row.id, name=row.name, role_title=row.role_title, company_id=row.company_id,
        phone_masked=phone.mask(row.phone), has_phone=bool(row.phone), phone_kind=phone.kind(row.phone),
        channels=[name for name, flag in _CHANNELS if getattr(row, flag)], unread=unread or 0,
        do_not_contact=refused, phone_invalid=row.phone_invalid,
        last_line=None if last is None else hide_phones(last)[:LAST_LINE_CHARS], hidden=row.hidden,
    )


def _events(log: object) -> list[EventOut]:
    """그 줄의 하네스 사건(harness_json — 남길 때 이미 번호·비밀을 지웠다)에서 rule·verdict·detail 만."""
    if not isinstance(log, list):
        return []
    return [EventOut(rule=str(e.get("rule")), verdict=str(e.get("verdict")), detail=e.get("detail"))
            for e in log if isinstance(e, dict)]


def _batches(session: Session, schedule_id: int, ids: set[int]) -> dict[int, BatchOut]:
    out = {}
    for batch_id in ids:
        sent = select(OutreachMessage.id).where(OutreachMessage.schedule_id == schedule_id,
                                                OutreachMessage.batch_id == batch_id, OutreachMessage.direction == "out")
        total = session.scalar(select(func.count()).select_from(sent.subquery()))
        replied = session.scalar(select(func.count(func.distinct(OutreachMessage.contact_id))).where(
            OutreachMessage.schedule_id == schedule_id, OutreachMessage.direction == "in",
            OutreachMessage.reply_to_id.in_(sent)))
        out[batch_id] = BatchOut(id=batch_id, total=total or 0, replied=replied or 0)
    return out


def _out(session: Session, schedule_id: int, rows: list[OutreachMessage], user: User) -> list[MessageOut]:
    """메시지 줄들 → MessageOut. 작업 이름·대화 제목·묶음 셈은 한 번에 읽는다."""
    names = _activity_names(session, schedule_id) if any(r.activity_id for r in rows) else {}
    chat_ids = {r.chat_session_id for r in rows if r.chat_session_id is not None}
    chats = {c.id: c for c in session.scalars(select(ChatSession).where(ChatSession.id.in_(chat_ids)))} if chat_ids else {}
    batches = _batches(session, schedule_id, {r.batch_id for r in rows if r.batch_id is not None})
    out = []
    for row in rows:
        inbound = row.direction == "in"  # 상대가 쓴 글은 번호를 가려 보인다
        chat = chats.get(row.chat_session_id) if row.chat_session_id is not None else None
        out.append(MessageOut(
            id=row.id, direction=row.direction, channel=row.channel, kind=row.kind,
            body=hide_phones(row.body) if inbound else row.body,
            body_ko=hide_phones(row.body_ko) if inbound and row.body_ko else row.body_ko,
            has_media=row.has_media, origin=row.origin, origin_name=row.origin_name, send_mode=row.send_mode,
            approved_by=row.approved_by, status=row.status, fail_reason=row.fail_reason, fallback_sms=row.fallback_sms,
            template_id=row.template_id, reply_to_id=row.reply_to_id,
            activity=ActivityOut(id=row.activity_id, name=names.get(row.activity_id)) if row.activity_id else None,
            field_item_id=row.field_item_id, approval_id=row.approval_id,
            chat=None if row.chat_session_id is None else ChatOut(
                id=row.chat_session_id, title=chat.title if chat is not None and chat.user_id == user.id else ""),
            batch=batches.get(row.batch_id) if row.batch_id is not None else None,
            events=_events(row.harness_json),
            scheduled_at=_utc(row.scheduled_at), sent_at=_utc(row.sent_at), delivered_at=_utc(row.delivered_at),
            created_at=as_utc(row.created_at),
        ))
    return out


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else as_utc(value)


def _one(session: Session, schedule_id: int, row: OutreachMessage, user: User) -> MessageOut:
    session.refresh(row)
    return _out(session, schedule_id, [row], user)[0]


def _outcome(outcome: Outcome) -> OutcomeOut:
    return OutcomeOut(code=outcome.code, message=outcome.message, scheduled_at=outcome.scheduled_at)


# ── 길 ───────────────────────────────────────────────────────────────────────


def thread(session: Session, schedule_id: int, contact_id: int, before: int | None, limit: int,
           user: User) -> ThreadOut:
    """그 사람과 주고받은 메시지 가운데 가장 최근 limit 개(오래된 것부터). has_more 는 limit+1 로 읽어 판단한다."""
    person = _contact(session, schedule_id, contact_id)
    rows = outreach.thread(session, schedule_id, contact_id, before=before, limit=limit + 1)
    has_more = len(rows) > limit
    rows = rows[1:] if has_more else rows
    return ThreadOut(contact=_brief(session, schedule_id, person), messages=_out(session, schedule_id, rows, user),
                     has_more=has_more)


async def create(session: Session, schedule_id: int, body: MessageIn, user: User) -> MessageResult:
    """초안을 만들고(origin user, 중복 방지 키는 새로), send 면 commit 한 뒤 나가는 문에 넣는다."""
    _contact(session, schedule_id, body.contact_id)
    check_body(body.body, *(body.template_vars or {}).values())
    _check_links(session, schedule_id, activity_id=body.activity_id, field_item_id=body.field_item_id,
                 approval_id=body.approval_id, template_id=body.template_id)
    row = OutreachMessage(
        schedule_id=schedule_id, contact_id=body.contact_id, direction="out", channel=body.channel, kind="normal",
        body=body.body, template_id=body.template_id, template_vars_json=body.template_vars or {}, origin="user",
        origin_name=user.name, status="draft", activity_id=body.activity_id, field_item_id=body.field_item_id,
        approval_id=body.approval_id,
    )
    session.add(row)
    session.commit()
    if not body.send:
        return MessageResult(message=_one(session, schedule_id, row, user), outcome=None)
    return await _dispatch(session, schedule_id, row, user)


async def send(session: Session, schedule_id: int, message_id: int, user: User) -> MessageResult:
    """그 줄을 나가는 문에 넣는다. 끝난 줄(실패·확인 필요·접수 …)은 409 not_sendable — 다시 보내기는 resend 로 새 줄."""
    row = _message(session, schedule_id, message_id)
    if row.direction != "out" or row.status not in SENDABLE:
        raise ApiError(409, "not_sendable", USE_RESEND if row.status in RESENDABLE else DONE)
    # 사람이 보내는 자동 답 초안은 사람이 승인한 보통 글이 된다(origin 은 그대로). 아직 초안·예약일 때만 — 문이나 일꾼이
    # 이미 가져간 줄(sending)의 종류는 건드리지 않는다(자동 답 상한·같은 자동 답 검사가 그 종류로 센다)
    session.execute(update(OutreachMessage).where(
        OutreachMessage.id == row.id, OutreachMessage.status.in_(KIND_OPEN), OutreachMessage.kind.in_(AUTO_KINDS),
    ).values(kind="normal"))
    session.commit()
    return await _dispatch(session, schedule_id, row, user)


async def _dispatch(session: Session, schedule_id: int, row: OutreachMessage, user: User) -> MessageResult:
    """자기 쓰기를 commit 해 둔 뒤 부른다(문은 자기 세션으로 읽고 쓴다). 문은 모듈 속성으로 부른다."""
    outcome = await gate.dispatch("message", row.id, _actor(user), now=_now())
    session.expire_all()
    return MessageResult(message=_one(session, schedule_id, row, user), outcome=_outcome(outcome))


def patch(session: Session, schedule_id: int, message_id: int, body: MessagePatch, user: User) -> MessageOut:
    """초안만: 본문·채널·작업. 에이전트 초안의 자동 답 종류는 normal 로(origin 그대로)."""
    row = _message(session, schedule_id, message_id)
    values = body.model_dump(exclude_unset=True)
    check_body(values.get("body"))
    if values.get("activity_id") is not None:
        _check_links(session, schedule_id, activity_id=values["activity_id"])
    if row.kind in AUTO_KINDS:
        values["kind"] = "normal"
    if values:
        changed = session.execute(update(OutreachMessage).where(
            OutreachMessage.id == row.id, OutreachMessage.status == "draft").values(**values)).rowcount
    else:
        changed = int(row.status == "draft")
    if changed != 1:
        session.rollback()
        raise ApiError(409, "not_draft", NOT_DRAFT)
    session.commit()
    return _one(session, schedule_id, row, user)


def remove(session: Session, schedule_id: int, message_id: int) -> None:
    """초안만 지운다. 그 밖은 409 not_draft."""
    row = _message(session, schedule_id, message_id)
    gone = session.execute(delete(OutreachMessage).where(
        OutreachMessage.id == row.id, OutreachMessage.status == "draft")).rowcount
    if gone != 1:
        session.rollback()
        raise ApiError(409, "not_draft", NOT_DRAFT)
    session.commit()


def cancel(session: Session, schedule_id: int, message_id: int, user: User) -> MessageOut:
    """예약 → 초안: 예약 시각·보내는 방식·승인한 사람을 비운다(문이 초안으로 돌린 줄과 같은 꼴 — 지난 승인이 남지 않게).
    그 사이 일꾼이 가져갔거나 예약이 아니면 409 not_scheduled."""
    row = _message(session, schedule_id, message_id)
    changed = session.execute(update(OutreachMessage).where(
        OutreachMessage.id == row.id, OutreachMessage.status == "scheduled",
    ).values(status="draft", scheduled_at=None, send_mode=None, approved_by=None)).rowcount
    if changed != 1:
        session.rollback()
        raise ApiError(409, "not_scheduled", NOT_SCHEDULED)
    session.commit()
    return _one(session, schedule_id, row, user)


def resend(session: Session, schedule_id: int, message_id: int, user: User) -> ResendOut:
    """실패·확인 필요 줄 → 같은 연락처·채널·글의 새 초안(옛 줄은 그대로). 보내지는 않는다 — 사람이 [보내기]를 누른다.
    확인 필요였던 줄은 「이미 나갔을 수 있습니다」를 함께 준다(같은 글 시간 창 안이면 문이 그 보내기를 막는다)."""
    old = _message(session, schedule_id, message_id)
    if old.direction != "out" or old.status not in RESENDABLE:
        raise ApiError(409, "not_resendable", NOT_RESENDABLE)
    warning = MAY_HAVE_GONE if old.status == "unconfirmed" else None
    row = OutreachMessage(
        schedule_id=schedule_id, contact_id=old.contact_id, peer_number=old.peer_number, direction="out",
        channel=old.channel, kind="dnc_confirm" if old.kind == "dnc_confirm" else "normal", body=old.body,
        template_id=old.template_id, template_vars_json=dict(old.template_vars_json or {}), origin="user",
        origin_name=user.name, status="draft", reply_to_id=old.reply_to_id, activity_id=old.activity_id,
        field_item_id=old.field_item_id, approval_id=old.approval_id,
    )
    session.add(row)
    session.commit()
    return ResendOut(message=_one(session, schedule_id, row, user), warning=warning)


# ── 에이전트 초안 ─────────────────────────────────────────────────────────────

_drafting: set[tuple[int, int]] = set()  # 지금 초안을 만드는 (일정, 연락처) — 도는 동안 또 누르면 거절(이 프로세스 안)


def check_agent_draft(session: Session, schedule_id: int, contact_id: int, channel: str) -> Contact:
    """에이전트 초안을 만들 수 있는 사람·채널인지. 이 차례로 거절(줄을 만들지 않음, 글에 번호·까닭 없음):
    그 일정 연락처가 아님 404 → 수신 거부(줄 표시 또는 번호 기준) 409 do_not_contact → 쓸 번호 없음 409 no_number →
    카카오톡 통로가 등록돼 있지 않음 409 channel_locked → 문자를 받을 수 없음(깃발 꺼짐·휴대전화 아님 — 카카오톡도 문이
    문자로 바꿔 보낼 수 있어야 함) 409 no_sms → 카카오톡 받기 꺼짐 409 no_kakao."""
    who = _contact(session, schedule_id, contact_id)
    if who.do_not_contact or (who.phone is not None and outreach.is_do_not_contact(session, who.phone)):
        raise ApiError(409, "do_not_contact", DO_NOT_CONTACT)
    number = phone.normalize(who.phone)
    if number is None or who.phone_invalid:
        raise ApiError(409, "no_number", NO_NUMBER)
    kakao = channel == "kakao"
    if kakao and "kakao" not in channels.registered():
        raise ApiError(409, "channel_locked", KAKAO_LOCKED)
    if not (who.can_sms and phone.can_sms(number)):
        raise ApiError(409, "no_sms", NO_SMS)
    if kakao and not who.can_kakao:
        raise ApiError(409, "no_kakao", NO_KAKAO)
    return who


def _check_text(body: object, body_ko: object) -> None:
    """초안 글: body 는 1~BODY_MAX 자 글, body_ko 는 None 이거나 같은 꼴(앞뒤 빈칸을 지운 길이), 보이지 않는 글자 없음."""
    for text in (body,) if body_ko is None else (body, body_ko):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= BODY_MAX:
            raise ApiError(422, "invalid_text", BAD_LENGTH, detail={"field": "body"})
    check_body(body, body_ko)


def create_agent_draft(session: Session, schedule_id: int, *, contact_id: int, channel: str, body: str,
                       body_ko: str | None = None, activity_id: str | None = None, template_id: int | None = None,
                       template_vars: dict[str, str] | None = None,
                       chat_session_id: int | None = None) -> OutreachMessage:
    """에이전트가 쓴 초안 줄 하나(보내지 않음). 대화 에이전트 도구(Task 80)와 [에이전트에게 초안 맡기기]가 같이 쓴다.
    check_agent_draft → 글(_check_text·check_body, 문안 값 포함) → 연결 id(작업·문안 — create 와 같은 404) 를 본 뒤
    origin "agent"·origin_name AGENT_NAME·status draft·kind normal·direction out 으로 만든다. send_mode·approved_by·
    peer_number 는 비운다(문이 보낼 때 정한다). flush 까지만 — commit 은 부른 쪽."""
    check_agent_draft(session, schedule_id, contact_id, channel)
    _check_text(body, body_ko)
    check_body(*(template_vars or {}).values())
    _check_links(session, schedule_id, activity_id=activity_id, template_id=template_id)
    row = OutreachMessage(
        schedule_id=schedule_id, contact_id=contact_id, direction="out", channel=channel, kind="normal", body=body,
        body_ko=body_ko, template_id=template_id, template_vars_json=dict(template_vars or {}), origin="agent",
        origin_name=AGENT_NAME, status="draft", activity_id=activity_id, chat_session_id=chat_session_id,
    )
    session.add(row)
    session.flush()
    return row


async def agent_draft(session: Session, schedule_id: int, body: AgentDraftIn, user: User) -> MessageOut:
    """[에이전트에게 초안 맡기기]: 거절할 것은 모델을 부르기 전에 거절하고(쓰기 없음), 모델을 한 번 불러 초안 글을 얻은 뒤
    그때의 상태로 다시 확인해 에이전트 초안 줄을 만든다. 같은 사람의 초안을 만드는 중이면 409 draft_busy. 모델 실패·쓸 수
    없는 답은 503 draft_failed(「잠시 뒤 다시」), LLM 연결이 없으면 503 llm_not_ready, 줄 없음. 그 사이 지워진 연락처는 404.
    보내지 않는다."""
    check_agent_draft(session, schedule_id, body.contact_id, body.channel)
    check_body(body.hint, field="hint")
    _check_links(session, schedule_id, activity_id=body.activity_id)
    key = (schedule_id, body.contact_id)
    if key in _drafting:
        raise ApiError(409, "draft_busy", DRAFT_BUSY)
    _drafting.add(key)
    try:
        try:
            drafted = await drafting.draft_message(session, schedule_id, body.contact_id, body.channel,
                                                   activity_id=body.activity_id, hint=body.hint)
            _check_text(drafted.body, drafted.body_ko)
        except contacts.NotFound:  # 확인한 뒤 그 사이 지워짐 — 없는 연락처와 같은 404
            raise ApiError(404, "not_found", PERSON_NOT_FOUND) from None
        except drafting.DraftNotReady:
            raise ApiError(503, "llm_not_ready", LLM_NOT_READY) from None
        except (drafting.DraftFailed, ApiError):
            raise ApiError(503, "draft_failed", DRAFT_FAILED) from None
        session.expire_all()  # 모델을 부르는 동안 바뀐 것(수신 거부·번호·작업)을 다시 읽는다
        row = create_agent_draft(session, schedule_id, contact_id=body.contact_id, channel=body.channel,
                                 body=drafted.body, body_ko=drafted.body_ko, activity_id=body.activity_id)
        session.commit()
    finally:
        _drafting.discard(key)
    return _one(session, schedule_id, row, user)
