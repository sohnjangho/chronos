"""연락 기록 읽기·쓰기(Task 61): 알림 연결과 그 한도, 메시지·통화 줄, 차지하기(claim), 셈, 보고, 사용량.

일정 id 를 받는 함수는 그 일정 것만 본다 — 다른 일정의 메시지·통화·연락처 id 는 없는 것과 같다(NotFound).
번호(number)는 app.outreach.phone.normalize 한 꼴. 쓰는 함수는 flush 까지만 하고 commit 은 부른 쪽이 한다.
시각은 DB 처럼 UTC 로 견준다(시간대 없는 값은 UTC 로 본다). 「하루」는 서울 날짜다.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import Session

from app.store import contacts
from app.store.schedules import NotFound
from app.store.tables_outreach import (
    Contact,
    ContactReport,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
)
from app.store.timeutil import as_utc

__all__ = [
    "LIMIT_RANGES", "Limits", "NotFound", "add_report", "add_usage", "auto_replies", "claim", "connection",
    "get_call", "get_message", "limits", "live_call", "sent_count", "thread",
]

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
SENT_MESSAGE = ("sending", "accepted", "delivered", "unconfirmed")  # 나갔거나 나가는 중인 메시지
SENT_CALL = ("queued", "dialing", "in_call", "completed", "no_answer", "busy", "failed")  # 줄에 넣은 뒤 상태 전부
LIVE_CALL = ("queued", "dialing", "in_call")
_ROWS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}


# ── 알림 연결과 한도 ────────────────────────────────────────────────


@dataclass(frozen=True)
class Limits:
    """알림 연결 한 줄의 한도(PM 11-23: 설정·개발 콘솔에서 바꾼다 — 상수로 쓰지 않는다). 모두 정수."""

    daily_sms_total: int = 50  # 하루 문자(모든 사람)
    daily_calls_total: int = 10  # 하루 거는 전화
    per_contact_sms_daily: int = 5  # 한 사람에게 하루 문자
    per_contact_calls_daily: int = 2  # 한 사람에게 하루 전화
    max_call_seconds: int = 300  # 통화 한 통의 최대 길이
    max_call_seconds_unknown: int = 120  # 모르는 번호·번호 숨김·수신 거부 등급의 받는 통화
    auto_reply_hourly: int = 5  # 한 번호에 자동 답, 지난 한 시간
    auto_reply_daily: int = 20  # 한 번호에 자동 답, 오늘
    inbound_burst_count: int = 5  # 잦은 전화: inbound_burst_minutes 안에 이만큼 걸려 오면 거절
    inbound_burst_minutes: int = 10
    reply_grace_minutes: int = 30  # 상대가 먼저 보낸 뒤 이 시간 안의 답은 근무시간 밖이어도 보낸다
    unknown_notice_daily: int = 1  # 모르는 번호에 고정 안내, 하루


_COUNT = (0, 10_000)
_CALL_SECONDS = (1, 7_200)
LIMIT_RANGES: dict[str, tuple[int, int]] = {  # 칸마다 받는 값(양 끝 포함). 설정 화면·콘솔의 입력 검사도 이것을 쓴다
    "daily_sms_total": _COUNT,
    "daily_calls_total": _COUNT,
    "per_contact_sms_daily": _COUNT,
    "per_contact_calls_daily": _COUNT,
    "max_call_seconds": _CALL_SECONDS,
    "max_call_seconds_unknown": _CALL_SECONDS,
    "auto_reply_hourly": _COUNT,
    "auto_reply_daily": _COUNT,
    "inbound_burst_count": _COUNT,
    "inbound_burst_minutes": (1, 1_440),
    "reply_grace_minutes": (0, 1_440),
    "unknown_notice_daily": _COUNT,
}


def limits(conn: NotifyConnection | None) -> Limits:
    """그 연결의 쓰이는 한도: limits_json 에 둔 값이 기본값을 덮는다. 없거나 틀린 값(정수가 아님·범위 밖)은 그 칸만
    기본값(기록에는 칸 이름만). 연결이 없으면 모두 기본값. 한도는 이 함수로만 읽는다."""
    stored = conn.limits_json if conn is not None else None
    if stored is None:
        return Limits()
    if not isinstance(stored, dict):
        logger.warning("알림 연결 한도가 객체가 아니라 모두 기본값을 씁니다")
        return Limits()
    good = {}
    for key, (low, high) in LIMIT_RANGES.items():
        if key not in stored:
            continue
        value = stored[key]
        if type(value) is int and low <= value <= high:  # bool·실수·글은 받지 않는다
            good[key] = value
        else:
            logger.warning("알림 연결 한도 값이 틀려 기본값을 씁니다: %s", key)
    return Limits(**good)


def connection(session: Session) -> NotifyConnection | None:
    """기본 연결(is_default). 없으면 None."""
    stmt = select(NotifyConnection).where(NotifyConnection.is_default).order_by(NotifyConnection.id).limit(1)
    return session.scalar(stmt)


# ── 메시지·통화 줄 ─────────────────────────────────────────────────


def get_message(session: Session, schedule_id: int, message_id: int) -> OutreachMessage:
    """그 일정의 메시지. 없거나 다른 일정(또는 일정 없는 줄)이면 NotFound."""
    row = session.get(OutreachMessage, message_id)
    if row is None or schedule_id is None or row.schedule_id != schedule_id:
        raise NotFound(message_id)
    return row


def get_call(session: Session, schedule_id: int, call_id: int) -> OutreachCall:
    """그 일정의 통화. 없거나 다른 일정(또는 일정 없는 줄)이면 NotFound."""
    row = session.get(OutreachCall, call_id)
    if row is None or schedule_id is None or row.schedule_id != schedule_id:
        raise NotFound(call_id)
    return row


def thread(
    session: Session, schedule_id: int, contact_id: int, *, before: int | None = None, limit: int = 50
) -> list[OutreachMessage]:
    """그 일정·그 연락처와 주고받은 메시지 가운데 가장 최근 limit 개를 오래된 것부터(id 순).
    before(메시지 id)를 주면 그보다 앞 것만 — 앞 쪽 넘기기. 연락처가 그 일정 것이 아니면 NotFound."""
    contacts.get_contact(session, schedule_id, contact_id)
    stmt = select(OutreachMessage).where(
        OutreachMessage.schedule_id == schedule_id, OutreachMessage.contact_id == contact_id
    )
    if before is not None:
        stmt = stmt.where(OutreachMessage.id < before)
    rows = list(session.scalars(stmt.order_by(OutreachMessage.id.desc()).limit(limit)))
    return rows[::-1]


def claim(
    session: Session, kind: Literal["message", "call"], row_id: int, from_states: tuple[str, ...], to_state: str
) -> bool:
    """줄의 상태가 from_states 가운데 하나일 때만 to_state 로 바꾼다(UPDATE … WHERE id=? AND status IN (…) 한 줄).
    바꾼 줄이 1이면 True — 두 곳이 같은 줄을 차지하려 해도 한 곳만 이긴다. commit 은 부른 쪽."""
    model = _ROWS[kind]
    result = session.execute(
        update(model).where(model.id == row_id, model.status.in_(from_states)).values(status=to_state)
    )
    return result.rowcount == 1


# ── 셈 ─────────────────────────────────────────────────────────────


def _naive_utc(dt: datetime) -> datetime:
    """DB 와 견줄 UTC(시간대 없음)."""
    return as_utc(dt).replace(tzinfo=None)


def _message_time() -> ColumnElement[datetime]:
    """메시지가 나간 때: 보낸 시각, 아직 없으면(보내는 중·확인 필요) 예약 시각, 그것도 없으면 만든 시각."""
    return func.coalesce(OutreachMessage.sent_at, OutreachMessage.scheduled_at, OutreachMessage.created_at)


def _call_time() -> ColumnElement[datetime]:
    return func.coalesce(OutreachCall.started_at, OutreachCall.scheduled_at, OutreachCall.created_at)


def _to_number(model: type[OutreachMessage] | type[OutreachCall], number: str) -> ColumnElement[bool]:
    """그 번호와 주고받은 줄: peer_number 가 그 번호이거나, 연락처(어느 일정이든)의 번호가 그 번호."""
    return or_(model.peer_number == number, model.contact_id.in_(select(Contact.id).where(Contact.phone == number)))


def sent_count(
    session: Session, channel: Literal["sms", "kakao", "call"], day_kst: date, *, number: str | None = None
) -> int:
    """그 서울 날짜에 우리가 내보낸 수. 'sms'·'kakao' 는 그 채널 메시지 가운데 sending·accepted·delivered·unconfirmed,
    'call' 은 거는 통화 가운데 queued 뒤 상태 전부. number 를 주면 그 번호로 간 것만."""
    start = _naive_utc(datetime.combine(day_kst, time(), tzinfo=KST))
    end = start + timedelta(days=1)
    if channel == "call":
        when = _call_time()
        stmt = select(func.count(OutreachCall.id)).where(
            OutreachCall.direction == "out", OutreachCall.status.in_(SENT_CALL), when >= start, when < end
        )
        model = OutreachCall
    else:
        when = _message_time()
        stmt = select(func.count(OutreachMessage.id)).where(
            OutreachMessage.direction == "out",
            OutreachMessage.channel == channel,
            OutreachMessage.status.in_(SENT_MESSAGE),
            when >= start,
            when < end,
        )
        model = OutreachMessage
    if number is not None:
        stmt = stmt.where(_to_number(model, number))
    return session.scalar(stmt) or 0


def auto_replies(session: Session, number: str, since: datetime) -> list[OutreachMessage]:
    """그 번호로 since 뒤에 나간(sending·accepted·delivered·unconfirmed) 자동 답·고정 안내(kind auto_reply·notice),
    오래된 것부터. 되풀이 상한과 「같은 글 두 번 금지」가 읽는다."""
    when = _message_time()
    stmt = select(OutreachMessage).where(
        OutreachMessage.direction == "out",
        OutreachMessage.kind.in_(("auto_reply", "notice")),
        OutreachMessage.status.in_(SENT_MESSAGE),
        when >= _naive_utc(since),
        _to_number(OutreachMessage, number),
    )
    return list(session.scalars(stmt.order_by(when, OutreachMessage.id)))


def live_call(session: Session, contact_id: int) -> bool:
    """그 연락처와 진행 중인 통화(queued·dialing·in_call, 거는 것·받는 것)가 있는가."""
    stmt = select(OutreachCall.id).where(OutreachCall.contact_id == contact_id, OutreachCall.status.in_(LIVE_CALL))
    return session.scalar(stmt.limit(1)) is not None


# ── 보고·사용량 ─────────────────────────────────────────────────────


def add_report(session: Session, **fields) -> ContactReport:
    """contact_reports 한 줄(칸 이름 그대로 받는다). flush 해서 id 가 있는 줄을 돌려준다."""
    row = ContactReport(**fields)
    session.add(row)
    session.flush()
    return row


def add_usage(
    session: Session,
    kind: str,
    *,
    ref: tuple[str, int] | None = None,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    seconds: int | None = None,
    cost: float | None = None,
) -> None:
    """outreach_usage 한 줄. ref = ('message' | 'call', id). cost 는 모델·제공사가 알려 준 값만(없으면 None)."""
    ref_kind, ref_id = ref if ref is not None else (None, None)
    session.add(OutreachUsage(kind=kind, ref_kind=ref_kind, ref_id=ref_id, model=model, input_tokens=input_tokens,
                              output_tokens=output_tokens, seconds=seconds, cost=cost))
    session.flush()
