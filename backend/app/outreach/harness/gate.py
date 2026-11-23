"""나가는 문(Task 65) — 보내기·걸기는 채널과 상관없이 이 함수 하나를 지난다. Channel.deliver 를 부르는 코드는 여기뿐이다.

차례(types.GATE_RULES): 0 앞 확인 → 1 시험 모드 → 2 차단·수신 거부 → 3 근무시간 → 4 상한 → 5 권한 → 6 중복 → 7 채널 고르기.
먼저 걸린 차례 하나만 알린다. dispatch 한 번마다 문 판정 사건이 꼭 하나 남는다(걸린 차례의 이름 blocked, 지나가면
channel_choice allowed). 그 앞에 노트(GATE_NOTES)가 있을 수 있고, 통로를 불렀으면 뒤에 delivery 가 따로 온다.
받는 사람이 아닌 줄(없는 줄·받은 줄)과 DB 를 얻지 못한 호출에는 사건을 남기지 않는다.

- 부른 쪽 세션을 받지 않는다 — 부른 쪽은 부르기 전에 자기 쓰기를 commit 해 둔다. 일정 id 도 받지 않으므로 API 는 먼저
  그 일정의 줄인지 확인한 뒤 부른다.
- 판정 한 묶음(상한 셈·같은 글 검사·차지하기)은 `BEGIN IMMEDIATE` 한 트랜잭션이다 — 두 호출이 같은 한 자리를 함께 지나가지
  못한다. 쓰기 잠금을 얻지 못하면(다른 쓰기가 놓지 않음) 보내지 않고 「잠시 뒤 다시」(duplicate)를 돌려준다. 통로를 부르기
  전에 commit 하고 세션을 닫는다(부르는 동안 연결도 쓰기 잠금도 쥐지 않는다).
- 줄은 draft·scheduled(통화는 blocked_hours 도)일 때만 받는다. 나가는 중인 줄(sending · queued·dialing·in_call)을 다시
  넣으면 duplicate(「이미 보냈습니다」라고 하지 않는다), 끝난 줄은 not_sendable — 둘 다 줄을 건드리지 않는다.
- 걸리면 줄은 초안으로 돌아가고 fail_reason 에 까닭, send_mode 는 비운다. 예외: 시험 모드 → blocked_test, 근무시간 →
  문자·카카오톡은 scheduled(누른 쪽의 send_mode 를 적어 둔다 — 일꾼이 때가 되면 그것으로 처음부터 다시 검사받는다),
  통화는 blocked_hours. 보낼 수 없는 사람(현장 관리자 등)이 누른 것은 줄을 건드리지 않는다.
- 통로 결과 셋은 판정 코드 셋이다: sent → accepted(통화 queued) · failed → failed · unsure → unsure(줄 unconfirmed,
  다시 보내지 않는다). 통로가 예외로 끝나거나 취소되면 unsure. 통화는 「확인 필요」가 없다 — 줄에 넣지 못했으면 failed.
- 상한 숫자는 모두 store.outreach.limits(conn) 에서 검사할 때마다 읽는다(여기 숫자 상수는 DUPLICATE_WINDOW_S 하나).
- 일꾼(system)은 줄에 적힌 send_mode 로만 보낸다 — **문을 거치지 않고 scheduled 줄을 만드는 코드는 send_mode 를 적어야
  한다**(비어 있으면 needs_approval).
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import db
from app.core.model import CalendarSpec
from app.outreach import hours, phone, redact
from app.outreach.harness import events, registry
from app.outreach.harness.types import (
    DELIVERY_VERDICT,
    GATE_RULES,
    Actor,
    Channel,
    Delivered,
    NotReady,
    Outcome,
    Ref,
)
from app.store import contacts, outreach
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    DoNotContactNumber,
    KakaoTemplate,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

DUPLICATE_WINDOW_S = 120  # 같은 번호·같은 채널·같은 글(통화는 같은 목적)의 다른 줄을 막는 시간
PRECHECK, TEST_MODE, BLOCKED_OR_DNC, WORKING_HOURS, LIMITS, PERMISSION, DUPLICATE, CHANNEL_CHOICE = GATE_RULES
BUSY = "이미 보내는 중이거나 잠시 뒤 다시 해 보세요"
UNSURE = "보냈는지 확인 필요"
NO_HOURS = "근무시간을 찾을 수 없습니다"

_Row = OutreachMessage | OutreachCall
_Mode = tuple[str | None, str | None]  # (send_mode, approved_by)
_MODELS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}
_OPEN = {"message": ("draft", "scheduled"), "call": ("draft", "scheduled", "blocked_hours")}  # 문이 받는 상태
_LEAVING = {"message": "sending", "call": "queued"}  # 지나간 줄이 차지하는 상태
_UNDER_WAY = {"message": ("sending",), "call": outreach.LIVE_CALL}
# 「같은 글 두 번」에 견주는 앞 줄의 상태: 나가는 중·나갔음·확인 필요. 가지 않았음이 확실한 것(failed, 통화의 no_answer·busy)은
# 뺀다 — 다시 보내기·다시 걸기는 새 줄이라 여기서 막으면 안 된다.
_MAY_HAVE_GONE = {"message": outreach.SENT_MESSAGE, "call": (*outreach.LIVE_CALL, "completed")}
_AUTO_KINDS = ("auto_reply", "notice")
_REASON_MAX = OutreachMessage.fail_reason.type.length
_SLOT = re.compile(r"#\{([^}]*)\}")  # 알림톡 문안의 빈 칸
_RETRY_COPIES = ("schedule_id", "contact_id", "peer_number", "caller_class", "purpose", "questions_json", "avoid_json",
                 "language", "voice_id", "origin", "origin_name", "purpose_key", "activity_id", "field_item_id",
                 "chat_session_id")


async def dispatch(kind: Literal["message", "call"], row_id: int, actor: Actor, *, now: datetime | None = None) -> Outcome:
    """그 줄(메시지·통화)을 내보낸다 — 모듈 머리 글의 차례대로 보고, 지나가면 통로를 한 번 부른다."""
    now = as_utc(now or datetime.now(UTC))
    with Session(db._engine) as session:
        try:
            session.execute(text("BEGIN IMMEDIATE"))
        except OperationalError as exc:
            if "locked" not in str(exc.orig):
                raise
            return Outcome("duplicate", BUSY, DUPLICATE)
        decided = _decide(session, kind, row_id, actor, now)
        session.commit()
    if isinstance(decided, Outcome):
        return decided
    stopped = None
    try:
        result = await decided.deliver(row_id)
    except asyncio.CancelledError as exc:  # 보내기 요청이 나갔을 수 있다 — 결과를 적고, 부른 쪽이 취소된 것이면 다시 올린다
        stopped = exc if asyncio.current_task().cancelling() else None
        result = Delivered("unsure", fail_text="보내는 중에 취소됐습니다")
    except Exception as exc:  # noqa: BLE001 — 통로가 무엇으로 끝났든 「나갔는지 모름」. 예외 글에는 번호·키가 있을 수 있다
        logger.warning("통로 호출이 예외로 끝났습니다: %s", type(exc).__name__)
        result = Delivered("unsure", fail_text="통로가 결과를 돌려주지 않았습니다")
    outcome = _settle(kind, row_id, result, now)
    if stopped is not None:
        raise stopped
    return outcome


def may_reach(session: Session, number: str) -> bool:
    """그 번호에 닿아도 되는가 — 차례 1·2(시험 모드·차단·수신 거부)만 본다. 통화 중 전환이 묻는다. 기본 연결이 없으면 거짓."""
    conn = outreach.connection(session)
    target = phone.normalize(number)
    return conn is not None and target is not None and _barred(session, conn, target) is None


def after_no_answer(call_id: int, *, now: datetime | None = None) -> int | None:
    """받지 않은 전화: 전화 권한이 위임이고 아직 쓰지 않았으면 **다음** 근무 시간대에 한 번 더 걸 새 줄(scheduled)을 만들고
    그 id 를 준다. 아니면 None. 새 줄은 때가 되면 dispatch 로 처음부터 다시 검사받는다."""
    now = as_utc(now or datetime.now(UTC))
    with Session(db._engine) as session:
        first = session.get(OutreachCall, call_id)
        conn = outreach.connection(session)
        if (first is None or first.direction != "out" or first.status != "no_answer" or first.auto_retry_used
                or conn is None or conn.agent_call != "delegate"):
            return None
        contact = session.get(Contact, first.contact_id) if first.contact_id is not None else None
        try:
            at = _next_window(contact.hours_json if contact else None, contacts.calendar_of(session, first.schedule_id), now)
        except hours.NoWorkingTime:
            return None
        once = update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.auto_retry_used.is_(False))
        if session.execute(once.values(auto_retry_used=True)).rowcount != 1:  # 다른 곳이 먼저 썼다
            session.rollback()
            return None
        retry = OutreachCall(**{name: getattr(first, name) for name in _RETRY_COPIES}, direction="out", status="scheduled",
                             scheduled_at=at, send_mode="delegated", retry_of=call_id, auto_retry_used=True)
        session.add(retry)
        session.flush()
        retry_id = retry.id
        events.record(session, Ref("call", call_id), "no_answer_retry", "noted", "다음 근무 시간대에 한 번 더 겁니다", now=now)
        session.commit()
        return retry_id


# ── 판정(한 트랜잭션) ────────────────────────────────────────────────


def _decide(session: Session, kind: str, row_id: int, actor: Actor, now: datetime) -> Outcome | Channel:
    """차례 0~7. 걸리면 줄·사건을 적고 판정을, 지나가면 줄을 차지하고 부를 통로를 돌려준다. commit 은 부른 쪽."""
    model = _MODELS.get(kind)
    row = session.get(model, row_id) if model is not None else None
    if row is None or row.direction != "out":
        return Outcome("not_sendable", "보낼 수 있는 줄이 아닙니다", PRECHECK)
    ref = Ref(kind, row_id)
    notes: list[tuple[str, str]] = []  # (GATE_NOTES 이름, 까닭 글) — 판정 사건 앞에 남긴다

    def stop(outcome: Outcome, status: str | None = "draft", mode: _Mode = (None, None)) -> Outcome:
        """걸렸다: 줄을 그 상태로 돌리고(None 이면 건드리지 않음) 노트와 판정 사건을 남긴다."""
        if status is not None:
            row.status, row.scheduled_at = status, outcome.scheduled_at if status == "scheduled" else None
            row.fail_reason = None if status == "scheduled" else outcome.message
            row.send_mode, row.approved_by = mode
        for note, why in notes:
            events.record(session, ref, note, "noted", why, now=now)
        events.record(session, ref, GATE_RULES[outcome.rule], "blocked", outcome.message, now=now)
        return outcome

    # 0 앞 확인
    if row.status in _UNDER_WAY[kind]:
        return stop(Outcome("duplicate", BUSY, DUPLICATE), None)
    if row.status not in _OPEN[kind]:
        return stop(Outcome("not_sendable", "이미 처리된 줄입니다. 다시 보내려면 새로 만들어 주세요", PRECHECK), None)
    if not (actor.kind == "system" or (actor.kind in ("user", "agent") and actor.role in ("user", "admin"))):
        return stop(Outcome("not_sendable", "보내거나 걸 수 있는 권한이 없습니다", PRECHECK), None)
    conn = outreach.connection(session)
    if conn is None or conn.status != "ok":
        return stop(Outcome("not_ready", "알림 연결이 준비되지 않았습니다. 설정에서 연결을 확인해 주세요", PRECHECK))
    contact = session.get(Contact, row.contact_id) if row.contact_id is not None else None
    if row.contact_id is not None and (contact is None or contact.schedule_id != row.schedule_id):
        return stop(Outcome("not_sendable", "이 일정의 연락처가 아닙니다", PRECHECK))
    number = phone.normalize(contact.phone if contact is not None else row.peer_number)
    if number is None or (contact is not None and contact.phone_invalid):
        return stop(Outcome("not_sendable", "받는 번호가 없거나 맞지 않습니다", PRECHECK))
    lane, body = ("call", "") if kind == "call" else _lane(session, conn, row)
    wanted = {lane} if kind == "call" else {row.channel, lane}  # 카카오톡 줄이 문자로 나가면 둘 다 되어야 한다
    if not all(_can_take(contact, number, name) for name in wanted):
        return stop(Outcome("not_sendable", "이 번호로는 그 방법으로 연락할 수 없습니다", PRECHECK))
    if lane == "sms" and not body.strip():
        return stop(Outcome("not_sendable", "보낼 글이 없습니다", PRECHECK))
    channel = _channel(lane)
    if channel is None:
        return stop(Outcome("not_ready", "보내는 통로가 아직 준비되지 않았습니다", PRECHECK))

    # 1 시험 모드 · 2 차단·수신 거부
    barred = _barred(session, conn, number)
    if (barred is not None and barred.code == "do_not_contact" and kind == "message" and row.kind == "dnc_confirm"
            and not _confirm_sent(session, number, row_id)):
        barred = None  # 수신 거부로 표시한 뒤의 확인 문자 한 번
    if barred is not None:
        return stop(barred, "blocked_test" if barred.rule == TEST_MODE else "draft")

    # 3 근무시간
    limits = outreach.limits(conn)
    mode = _mode(actor, row, conn, wanted)
    person_hours = contact.hours_json if contact is not None else None
    calendar = contacts.calendar_of(session, row.schedule_id)
    if not hours.is_working(person_hours, calendar, now):
        if kind == "message" and _within_grace(session, row, number, now, limits.reply_grace_minutes):
            notes.append(("reply_within_grace", "상대가 방금 보낸 문자의 답이라 근무시간 밖이어도 보냅니다"))
        else:
            try:
                start = hours.next_start(person_hours, calendar, now)
            except hours.NoWorkingTime:
                start = None
            if kind == "call":
                return stop(Outcome("blocked_hours", "근무시간 밖입니다" if start else NO_HOURS, WORKING_HOURS, start),
                            "blocked_hours")
            if start is None:
                return stop(Outcome("blocked_hours", NO_HOURS, WORKING_HOURS))
            return stop(Outcome("scheduled", "근무시간 밖이라 다음 근무 시작에 보냅니다", WORKING_HOURS, start), "scheduled",
                        mode or (None, None))

    # 4 상한 · 5 권한 · 6 중복
    over = _over_limit(session, row, lane, number, now, limits)
    if over is not None:
        return stop(over)
    if mode is None:
        return stop(Outcome("needs_approval", "사람의 승인이 필요합니다", PERMISSION))
    twin = _twin(session, row, lane, body, number, now)
    if twin is not None:
        return stop(twin)

    # 7 채널 고르기, 그리고 차지하기
    if kind == "message" and lane != row.channel:
        notes.append(("kakao_not_ready", "카카오톡 통로나 문안이 준비되지 않아 문자로 보냅니다"))
        row.channel, row.body, row.fallback_sms = lane, body, True
    row.send_mode, row.approved_by = mode
    row.fail_reason = None
    if not outreach.claim(session, kind, row_id, _OPEN[kind], _LEAVING[kind], now=now):
        session.rollback()  # 보내지 않는다 — 줄은 그대로
        notes.clear()
        return stop(Outcome("duplicate", BUSY, DUPLICATE), None)
    for note, why in notes:
        events.record(session, ref, note, "noted", why, now=now)
    events.record(session, ref, GATE_RULES[CHANNEL_CHOICE], "allowed", lane, now=now)
    return channel


def _channel(name: str) -> Channel | None:
    try:
        return registry.channel(name)
    except NotReady:
        return None


def _fill(template: str | None, values: dict) -> str | None:
    """빈 칸을 다 채운 글. 문안이 없거나 채우지 못한 칸이 있으면 None(반쯤 채운 글은 보내지 않는다)."""
    if not template or any(name not in values for name in _SLOT.findall(template)):
        return None
    return _SLOT.sub(lambda slot: str(values[slot.group(1)]), template)


def _lane(session: Session, conn: NotifyConnection, row: OutreachMessage) -> tuple[str, str]:
    """(나갈 통로, 보낼 글). 카카오톡 줄은 통로가 등록돼 있고 이 연결의 문안이 승인됐을 때만 카카오톡으로, 아니면 문자로 —
    글은 문안에 묶인 문자 글 → 채운 문안 → 줄에 적힌 글 가운데 먼저 되는 것."""
    if row.channel != "kakao":
        return row.channel, row.body
    template = session.get(KakaoTemplate, row.template_id) if row.template_id is not None else None
    if template is None or template.connection_id != conn.id:
        return "sms", row.body
    if template.status == "approved" and _channel("kakao") is not None:
        return "kakao", row.body
    values = row.template_vars_json or {}
    return "sms", _fill(template.fallback_body, values) or _fill(template.body, values) or row.body


def _can_take(contact: Contact | None, number: str, name: str) -> bool:
    """그 번호가 그 채널을 받을 수 있는가: 번호의 종류(문자·카카오톡은 휴대전화만) 그리고 연락처의 깃발."""
    able = phone.can_call(number) if name == "call" else phone.can_sms(number)
    return able and (contact is None or getattr(contact, f"can_{name}"))


def _to(model: type[OutreachMessage] | type[OutreachCall], number: str):
    """그 번호와 주고받은 줄(어느 일정이든): peer_number 가 그 번호이거나 연락처의 번호가 그 번호."""
    return or_(model.peer_number == number, model.contact_id.in_(select(Contact.id).where(Contact.phone == number)))


def _barred(session: Session, conn: NotifyConnection, number: str) -> Outcome | None:
    """차례 1·2 에 걸리면 그 판정. 수신 거부는 store.outreach.is_do_not_contact 의 답만 따른다."""
    if conn.test_mode and number not in {phone.normalize(allowed) for allowed in conn.allow_numbers_json or ()}:
        return Outcome("blocked_test", "시험 모드라 허용한 번호에만 연락합니다", TEST_MODE)
    if session.scalar(select(BlockedNumber.id).where(BlockedNumber.number == number)) is not None:
        return Outcome("blocked_number", "차단한 번호입니다", BLOCKED_OR_DNC)
    if outreach.is_do_not_contact(session, number):
        return Outcome("do_not_contact", "수신 거부한 번호입니다", BLOCKED_OR_DNC)
    return None


def _confirm_sent(session: Session, number: str, row_id: int) -> bool:
    """지금의 수신 거부 표시 뒤에 그 번호로 확인 문자(dnc_confirm)가 이미 나갔는가. 번호 기준 표시가 없으면(연락처 줄의 표시뿐)
    표시한 때를 모르므로 언제 나갔든 센다."""
    found = select(OutreachMessage.id).where(
        OutreachMessage.id != row_id, OutreachMessage.direction == "out", OutreachMessage.kind == "dnc_confirm",
        OutreachMessage.claimed_at.is_not(None), _to(OutreachMessage, number),
    )
    marked = session.scalar(select(DoNotContactNumber.created_at).where(DoNotContactNumber.number == number))
    if marked is not None:
        found = found.where(OutreachMessage.claimed_at >= marked)
    return session.scalar(found.limit(1)) is not None


def _within_grace(session: Session, row: OutreachMessage, number: str, now: datetime, minutes: int) -> bool:
    """답 유예: 이 글이 그 번호가 방금(유예 시간 안에) 보낸 받은 문자의 답인가. 보낸 때와 받은 때가 모두 그 안이어야 한다."""
    asked = session.get(OutreachMessage, row.reply_to_id) if row.reply_to_id is not None else None
    if asked is None or asked.direction != "in":
        return False
    sender = session.get(Contact, asked.contact_id) if asked.contact_id is not None else None
    if phone.normalize(sender.phone if sender is not None else asked.peer_number) != number:
        return False
    ages = [now - as_utc(at) for at in (asked.sent_at, asked.created_at) if at is not None]
    return bool(ages) and all(timedelta() <= age < timedelta(minutes=minutes) for age in ages)


def _mode(actor: Actor, row: _Row, conn: NotifyConnection, wanted: set[str]) -> _Mode | None:
    """차례 5: 이 줄을 보내는 방식 (send_mode, approved_by). 승인이 있어야 하면 None."""
    delegated = all(getattr(conn, f"agent_{name}") == "delegate" for name in wanted)
    if actor.kind == "user":
        return ("manual", None) if row.origin == "user" else ("approved", actor.name)
    if actor.kind == "agent":
        return ("delegated", None) if delegated else None
    # 일꾼: 줄에 적힌 방식 — 사람이 보냈거나 승인한 것은 그대로, 위임은 지금도 위임일 때만
    if row.send_mode in ("manual", "approved") or (row.send_mode == "delegated" and delegated):
        return row.send_mode, row.approved_by
    return None


def _over_limit(session: Session, row: _Row, lane: str, number: str, now: datetime, limits: outreach.Limits) -> Outcome | None:
    """차례 4. 차지한 순간부터 한 건으로 센다(store.outreach 의 셈). 문자·카카오톡은 함께 하루 문자 상한에 든다."""
    day = now.astimezone(hours.KST).date()
    channels = ("call",) if lane == "call" else ("sms", "kakao")
    total, each = ((limits.daily_calls_total, limits.per_contact_calls_daily) if lane == "call"
                   else (limits.daily_sms_total, limits.per_contact_sms_daily))
    if sum(outreach.sent_count(session, name, day) for name in channels) >= total:
        return Outcome("limit_daily", "오늘 보낼 수 있는 수를 모두 썼습니다", LIMITS)
    if lane != "call" and row.kind in _AUTO_KINDS:  # 자동 답은 사람당 상한이 아니라 자동 답 상한을 따른다
        today = outreach.auto_replies(session, number, datetime.combine(day, time(), tzinfo=hours.KST))
        this_hour = outreach.auto_replies(session, number, now - timedelta(hours=1))
        notices = sum(sent.kind == "notice" for sent in today)
        if (len(this_hour) >= limits.auto_reply_hourly or len(today) >= limits.auto_reply_daily
                or (row.kind == "notice" and notices >= limits.unknown_notice_daily)):
            return Outcome("limit_person", "이 번호에 자동으로 답할 수 있는 수를 모두 썼습니다", LIMITS)
    elif sum(outreach.sent_count(session, name, day, number=number) for name in channels) >= each:
        return Outcome("limit_person", "이 사람에게 오늘 연락할 수 있는 수를 모두 썼습니다", LIMITS)
    return None


def _twin(session: Session, row: _Row, lane: str, body: str, number: str, now: datetime) -> Outcome | None:
    """차례 6 가운데 「다른 줄」과 견주는 것(같은 줄을 두 번은 claim 이 막는다)."""
    since = now - timedelta(seconds=DUPLICATE_WINDOW_S)
    model = type(row)
    others = (model.id != row.id, model.direction == "out", _to(model, number))
    if lane == "call":
        live = select(model.id).where(model.id != row.id, model.status.in_(outreach.LIVE_CALL), _to(model, number))
        if (row.contact_id is not None and outreach.live_call(session, row.contact_id)) or session.scalar(live.limit(1)):
            return Outcome("duplicate", "그 번호와 통화가 진행 중이거나 걸 차례를 기다리고 있습니다", DUPLICATE)
        recent = and_(model.status.in_(_MAY_HAVE_GONE["call"]), model.claimed_at > since)
        same = select(model.id).where(*others, model.purpose_key == row.purpose_key, or_(model.status == "scheduled", recent))
        if row.purpose_key and session.scalar(same.limit(1)) is not None:  # 목적 손잡이가 빈 통화끼리는 견주지 않는다
            return Outcome("duplicate", "같은 목적의 전화를 방금 걸었거나 예약해 두었습니다", DUPLICATE)
        return None
    if row.kind == "auto_reply":  # 기계끼리 같은 말을 주고받지 않게
        today = datetime.combine(now.astimezone(hours.KST).date(), time(), tzinfo=hours.KST)
        sent = outreach.auto_replies(session, number, today)
        if sent and sent[-1].body.strip() == body.strip():
            return Outcome("duplicate", "그 번호에 마지막으로 나간 자동 답과 같은 글입니다", DUPLICATE)
    recent = select(model).where(*others, model.channel == lane, model.status.in_(_MAY_HAVE_GONE["message"]),
                                 model.claimed_at > since)
    if any(_text(other, other.body, lane) == _text(row, body, lane) for other in session.scalars(recent)):
        return Outcome("duplicate", "같은 글이 방금 나갔거나 나가는 중입니다", DUPLICATE)
    return None


def _text(row: OutreachMessage, body: str, lane: str) -> tuple:
    """「같은 글」의 열쇠: 앞뒤 공백을 정리한 글. 카카오톡은 글이 문안에서 나오므로 문안과 채울 값도 함께."""
    return (body.strip(), row.template_id, row.template_vars_json) if lane == "kakao" else (body.strip(),)


# ── 통로 결과 ────────────────────────────────────────────────────────


def _reason(told: str | None, fallback: str) -> str:
    """통로가 준 까닭에서 비밀·번호를 지운 글(fail_reason 칸 길이까지). 없거나 지우지 못하면 정해 둔 글."""
    try:
        cleaned = redact.scrub(told, redact.secrets()).strip() if told else ""
    except Exception:  # noqa: BLE001 — 지우기가 무엇으로 실패하든 원문을 남기지 않는다
        cleaned = ""
    return cleaned[:_REASON_MAX] or fallback


def _settle(kind: str, row_id: int, result: Delivered, now: datetime) -> Outcome:
    """통로가 돌려준 것을 새 세션에서 줄에 적고 delivery 사건을 남긴다."""
    state = result.state if kind == "message" or result.ok else "failed"  # 통화는 줄에 넣지 못했으면 실패
    with Session(db._engine) as session:
        row = session.get(_MODELS[kind], row_id)
        if state == "sent":
            detail = "통로가 받았습니다"
            outcome = Outcome("accepted", "보냈습니다") if kind == "message" else Outcome("queued", "전화를 걸 차례에 넣었습니다")
            if kind == "message":
                row.status, row.provider_message_id, row.sent_at = "accepted", result.provider_id, now
        elif state == "failed":
            detail = _reason(result.fail_text, "보내지 못했습니다")
            outcome = Outcome("failed", detail)
            row.status, row.fail_reason = "failed", detail
        else:
            detail = _reason(result.fail_text, UNSURE)
            outcome = Outcome("unsure", UNSURE)
            row.status, row.fail_reason = "unconfirmed", detail
        events.record(session, Ref(kind, row_id), "delivery", DELIVERY_VERDICT[state], detail, now=now)
        session.commit()
    return outcome


def _next_window(person_hours: dict | None, calendar: CalendarSpec, now: datetime) -> datetime:
    """지금의 근무 시간대가 아닌 그다음 근무 시작(받지 않은 사람에게 같은 시간대에 곧바로 다시 걸지 않는다).
    지금 근무 중이면 이 시간대가 끝나는 때를 한 시간씩 짚어 찾는다(시간대 하나는 하루를 넘지 않는다)."""
    probe = now
    for _ in range(24):
        if not hours.is_working(person_hours, calendar, probe):
            break
        probe += timedelta(hours=1)
    return hours.next_start(person_hours, calendar, probe)
