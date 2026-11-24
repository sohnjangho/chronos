"""연락 기록 읽기·쓰기(Task 61): 알림 연결과 그 한도, 메시지·통화 줄, 차지하기(claim), 셈, 보고, 사용량, 일정 지우기.

일정 id 를 받는 함수는 그 일정 것만 본다 — 다른 일정의 메시지·통화·연락처 id 는 없는 것과 같다(NotFound).
번호(number)를 받는 함수는 app.outreach.phone.normalize 로 정리해서 본다(정리되지 않으면 빈 결과).
쓰는 함수는 flush 까지만 하고 commit 은 부른 쪽이 한다. 시각은 DB 처럼 UTC 로 견준다. 「하루」는 서울 날짜다.
"""

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    and_,
    case,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.outreach.phone import normalize
from app.store import contacts
from app.store.schedules import NotFound
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    DoNotContactNumber,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
    UtcDateTime,
)
from app.store.timeutil import as_utc

__all__ = [
    "LIMIT_RANGES", "Limits", "NotFound", "add_report", "add_usage", "auto_replies", "claim", "clear_do_not_contact",
    "connection", "do_not_contact_numbers", "get_call", "get_message", "is_do_not_contact", "limits",
    "live_call", "mark_do_not_contact", "purge_schedule", "sent_count", "thread", "unknown_calls",
    "unknown_messages", "validate_limits",
]

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
SENT_MESSAGE = ("sending", "accepted", "delivered", "unconfirmed")  # 나갔거나 나가는 중인 메시지(상태 묶음)
SENT_CALL = ("queued", "dialing", "in_call", "completed", "no_answer", "busy", "failed")  # 줄에 넣은 뒤 상태 전부
LIVE_CALL = ("queued", "dialing", "in_call")
_ROWS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}
# 이 상태로 들어오면 「나가려고 차지했다」 — claim 이 claimed_at 을 찍는다(이미 이 안에서 옮기면 그대로 둔다)
_LEAVING: dict[str, tuple[str, ...]] = {"message": ("sending",), "call": LIVE_CALL}


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
    unknown_calls_hourly: int = 6  # 모르는 번호·번호 숨김 전화를 모두 합쳐 지난 한 시간에 응대하는 수(넘으면 거절)
    unknown_notice_total_daily: int = 10  # 모르는 번호 모두에게 하루에 만드는 고정 안내 수(넘으면 기록만)


_COUNT = (0, 10_000)
LIMIT_RANGES: dict[str, tuple[int, int]] = {  # 칸마다 받는 값(양 끝 포함). 설정 화면·콘솔의 입력 검사도 이것을 쓴다
    "daily_sms_total": _COUNT,
    "daily_calls_total": _COUNT,
    "per_contact_sms_daily": _COUNT,
    "per_contact_calls_daily": _COUNT,
    "max_call_seconds": (30, 7_200),
    "max_call_seconds_unknown": (1, 7_200),
    "auto_reply_hourly": _COUNT,
    "auto_reply_daily": _COUNT,
    "inbound_burst_count": (1, 10_000),
    "inbound_burst_minutes": (1, 1_440),
    "reply_grace_minutes": (0, 1_440),
    "unknown_notice_daily": _COUNT,
    "unknown_calls_hourly": (0, 1_000),
    "unknown_notice_total_daily": (0, 1_000),
}
_PAIRS = (  # (작은 쪽, 큰 쪽, 작은 쪽 칸의 오류 글)
    ("max_call_seconds_unknown", "max_call_seconds", "모르는 번호 통화 시간은 최대 통화 시간보다 길 수 없습니다."),
    ("auto_reply_hourly", "auto_reply_daily", "한 시간 자동 답 수는 하루 자동 답 수보다 많을 수 없습니다."),
    ("per_contact_sms_daily", "daily_sms_total", "한 사람 하루 문자 수는 하루 전체 문자 수보다 많을 수 없습니다."),
    ("per_contact_calls_daily", "daily_calls_total", "한 사람 하루 전화 수는 하루 전체 전화 수보다 많을 수 없습니다."),
)
_warned: set[str] = set()  # 틀린 한도 경고는 칸마다 프로세스에 한 번만


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, key)


def _field_error(key: str, value: object) -> str | None:
    if key not in LIMIT_RANGES:
        return "알 수 없는 한도입니다."
    if type(value) is not int:  # bool·실수·글·null 은 받지 않는다
        return "정수로 넣어 주세요."
    low, high = LIMIT_RANGES[key]
    return None if low <= value <= high else f"{low:,}~{high:,} 사이로 넣어 주세요."


def validate_limits(values: dict) -> dict[str, str]:
    """한도 입력 검사(설정 API·개발 콘솔): {칸: 한국어 오류}, 맞으면 {}. 오류 글에 넣은 값을 싣지 않는다.
    칸마다 LIMIT_RANGES(정수·범위)를 보고, 짝 규칙(모르는 번호 통화 ≤ 최대 통화, 한 시간 자동 답 ≤ 하루 자동 답,
    사람당 ≤ 하루 전체)을 본다. 짝의 한쪽이 빠졌으면 기본값으로 견주므로 저장할 전체 값({**저장된 값, **바꿀 값})을 넘긴다."""
    errors = {key: problem for key, value in values.items() if (problem := _field_error(key, value))}
    merged = asdict(Limits()) | {k: v for k, v in values.items() if k in LIMIT_RANGES and k not in errors}
    for small, big, message in _PAIRS:
        if small not in errors and big not in errors and merged[small] > merged[big]:
            errors[small] = message
    return errors


def limits(conn: NotifyConnection | None) -> Limits:
    """그 연결의 쓰이는 한도: limits_json 에 둔 값이 기본값을 덮는다. 없거나 틀린 값(정수가 아님·범위 밖)은 그 칸만
    기본값(경고는 칸 이름만, 칸마다 한 번). 모르는 번호 통화 시간은 최대 통화 시간을 넘지 않게 줄인다.
    연결이 없으면 모두 기본값. 한도는 이 함수로만 읽는다."""
    stored = conn.limits_json if conn is not None else None
    if stored is None:
        return Limits()
    if not isinstance(stored, dict):
        _warn_once("limits_json", "알림 연결 한도가 객체가 아니라 모두 기본값을 씁니다: %s")
        return Limits()
    good = {}
    for key in LIMIT_RANGES:
        if key not in stored:
            continue
        if _field_error(key, stored[key]) is None:
            good[key] = stored[key]
        else:
            _warn_once(key, "알림 연결 한도 값이 틀려 기본값을 씁니다: %s")
    result = Limits(**good)
    if result.max_call_seconds_unknown > result.max_call_seconds:
        result = replace(result, max_call_seconds_unknown=result.max_call_seconds)
    return result


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


def _unscheduled(session: Session, model, limit: int, before: int | None) -> list:
    stmt = select(model).where(model.schedule_id.is_(None))
    if before is not None:
        stmt = stmt.where(model.id < before)
    return list(session.scalars(stmt.order_by(model.id.desc()).limit(limit)))


def unknown_messages(session: Session, *, limit: int, before: int | None = None) -> list[OutreachMessage]:
    """어느 일정에도 들지 않은 메시지(주소록에 없는 번호와 주고받은 것), 새것부터(id 내림차순).
    before(메시지 id)를 주면 그보다 앞 것만. 「모르는 번호」 화면이 읽는다(번호는 부른 쪽이 가려서 내보낸다)."""
    return _unscheduled(session, OutreachMessage, limit, before)


def unknown_calls(session: Session, *, limit: int, before: int | None = None) -> list[OutreachCall]:
    """어느 일정에도 들지 않은 통화, 새것부터(id 내림차순). before(통화 id)를 주면 그보다 앞 것만."""
    return _unscheduled(session, OutreachCall, limit, before)


def unpaired_calls(session: Session, schedule_id: int, *, limit: int) -> list[OutreachCall]:
    """그 일정의 받은 통화 가운데 연락처 짝이 없고 번호가 있는 것(같은 번호가 그 일정 주소록에 둘 이상 — 대표번호),
    새것부터(id 내림차순). 「모르는 번호 · 대표번호」 화면이 그 일정을 열 때 읽는다(번호는 부른 쪽이 가려서 내보낸다)."""
    stmt = select(OutreachCall).where(OutreachCall.schedule_id == schedule_id, OutreachCall.contact_id.is_(None),
                                      OutreachCall.direction == "in", OutreachCall.peer_number.is_not(None))
    return list(session.scalars(stmt.order_by(OutreachCall.id.desc()).limit(limit)))


def claim(
    session: Session,
    kind: Literal["message", "call"],
    row_id: int,
    from_states: tuple[str, ...],
    to_state: str,
    *,
    now: datetime | None = None,
) -> bool:
    """줄의 상태가 from_states 가운데 하나일 때만 to_state 로 바꾼다(UPDATE … WHERE id=? AND status IN (…) 한 줄).
    바꾼 줄이 1이면 True — 두 곳이 같은 줄을 차지하려 해도 한 곳만 이긴다. commit 은 부른 쪽.

    부른 쪽은 **돌려받은 값만 믿는다**(미리 읽어 둔 줄의 상태로 판단하지 않는다). 이 세션에 올라 있던 그 줄의
    status·claimed_at 은 비워 두어 다음에 읽을 때 DB 의 참값을 본다. 다른 일꾼이 쓰기를 쥐고 있어 SQLite 가
    「database is locked」 이면 그쪽이 가진 것으로 보고 이 세션을 되돌린(rollback — 커밋 안 한 쓰기도 사라진다) 뒤
    False. 그 밖의 DB 오류는 그대로 올린다. **그러니 부를 때 같은 세션에 커밋 안 한 다른 쓰기를 쥐고 있지 않는다.**
    False 는 「다른 일꾼이 이겼다」와 「DB 가 바빴다」를 가르지 않는다 — 사람이 누른 보내기·걸기에서 False 를 받으면
    「이미 보냄」이 아니라 「다시 해 보세요」로 다룬다.
    줄은 나가려고 한 번만 차지한다. **`failed` 줄을 나가는 상태로 되돌리지 않는다**(False) — 다시 보내기·다시 걸기는 새 줄로
    만든다. 같은 줄을 다시 차지하면 claimed_at 이 옮겨 가 첫 시도가 그날 셈에서 빠지기 때문이다.
    나가는 상태(메시지 sending, 통화 queued·dialing·in_call)로 들어오면 claimed_at 을 now(없으면 지금)로 찍는다 —
    이미 그 안에서 옮기는 것(queued → dialing)은 처음 찍은 시각을 둔다. 하루 셈(sent_count)은 이 시각으로 한다.
    """
    model = _ROWS[kind]
    values: dict = {"status": to_state}
    if to_state in _LEAVING[kind]:
        stamp = literal(now or datetime.now(UTC), UtcDateTime())
        values["claimed_at"] = case((model.status.in_(_LEAVING[kind]), model.claimed_at), else_=stamp)
    stmt = update(model).where(model.id == row_id, model.status.in_(from_states)).values(**values)
    if to_state in _LEAVING[kind]:
        stmt = stmt.where(model.status != "failed")
    try:
        result = session.execute(stmt.execution_options(synchronize_session=False))
    except OperationalError as exc:
        if "locked" not in str(exc.orig):
            raise
        session.rollback()
        return False
    loaded = session.identity_map.get(session.identity_key(model, row_id))
    if loaded is not None:
        session.expire(loaded, ["status", "claimed_at"])
    return result.rowcount == 1


def purge_schedule(session: Session, schedule_id: int) -> None:
    """지우는 일정의 주소록과 연락 기록(협력사·연락처·연락처 제안·메시지·통화·보고)을 지운다 — 일정 id 가 다시 쓰여도
    새 일정에 나타나지 않게. 지우기 전에 수신 거부한 연락처의 번호를 번호 기준 수신 거부로 옮겨 둔다(번호 기준이라 남는다).
    저장된 번호가 정리되지 않으면(예전 입력) 그 번호는 옮기지 않고 넘어간다 — 지우기는 실패하지 않는다(번호는 기록하지 않음).
    일정 없는 줄·사용량·알림 연결·차단 목록은 남는다. commit 은 부른 쪽(일정 지우기와 한 트랜잭션).
    오늘 나간 줄도 함께 지워지므로 그날의 셈(sent_count)이 줄어든다 — 관리자만 하는 일이라 받아들인다."""
    refused = select(Contact.phone, Contact.dnc_reason).where(
        Contact.schedule_id == schedule_id, Contact.do_not_contact.is_(True), Contact.phone.is_not(None)
    )
    for number, reason in session.execute(refused).all():
        if normalize(number) is not None:
            mark_do_not_contact(session, number, reason=reason or "")
    for model in (ContactCompany, Contact, ContactProposal, OutreachMessage, OutreachCall, ContactReport):
        session.execute(delete(model).where(model.schedule_id == schedule_id))


# ── 수신 거부(번호 기준) ──────────────────────────────────────────────


def is_do_not_contact(session: Session, number: str) -> bool:
    """그 번호가 수신 거부인가 — 나가는 문·들어오는 문·도구는 이 함수로만 본다. 어느 일정이든 그 번호의 연락처(숨긴 사람도)에
    수신 거부 표시가 있거나 번호 기준 수신 거부(do_not_contact_numbers)가 있으면 참. 관리자 차단(blocked_numbers)은 따로다.
    번호는 phone.normalize 로 정리하고, 정리되지 않으면 거짓."""
    target = normalize(number)
    if target is None:
        return False
    flagged = select(Contact.id).where(Contact.phone == target, Contact.do_not_contact.is_(True)).limit(1)
    recorded = select(DoNotContactNumber.id).where(DoNotContactNumber.number == target)
    return session.scalar(flagged) is not None or session.scalar(recorded) is not None


def do_not_contact_numbers(session: Session, numbers: Iterable[str]) -> set[str]:
    """여러 번호를 한 번에(쿼리 둘) — is_do_not_contact 와 같은 규칙. 받은 번호를 정리하고(정리되지 않는 것은 뺀다) 그 가운데
    수신 거부인 것의 정리된 꼴. is_do_not_contact(s, n) == (normalize(n) in do_not_contact_numbers(s, [n]))."""
    targets = {target for number in numbers if (target := normalize(number)) is not None}
    if not targets:
        return set()
    flagged = select(Contact.phone).where(Contact.phone.in_(targets), Contact.do_not_contact.is_(True))
    recorded = select(DoNotContactNumber.number).where(DoNotContactNumber.number.in_(targets))
    return set(session.scalars(flagged)) | set(session.scalars(recorded))


def mark_do_not_contact(session: Session, number: str, *, reason: str) -> None:
    """번호 기준 수신 거부를 남긴다(이미 있으면 그대로 — 먼저 남긴 까닭을 둔다). 정리되지 않는 번호면 ValueError(글에 번호를
    싣지 않음). 두 요청이 같은 번호를 동시에 남겨도 오류가 아니다: 한 문장 INSERT … ON CONFLICT DO NOTHING(확인한 뒤 넣는
    사이가 없다. pysqlite 기본 설정에서는 SAVEPOINT 를 믿을 수 없어 쓰지 않는다). commit 은 부른 쪽."""
    target = normalize(number)
    if target is None:
        raise ValueError("번호 형식이 맞지 않습니다.")
    session.execute(
        sqlite_insert(DoNotContactNumber).values(number=target, reason=reason, created_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=[DoNotContactNumber.number])
    )


def clear_do_not_contact(session: Session, number: str) -> None:
    """그 번호의 수신 거부를 모든 곳에서 푼다: 번호 기준 줄을 지우고, 어느 일정이든 그 번호 연락처의 표시·까닭을 지운다.
    관리자 차단은 건드리지 않는다. 정리되지 않는 번호면 아무것도 하지 않는다. commit 은 부른 쪽."""
    target = normalize(number)
    if target is None:
        return
    session.execute(delete(DoNotContactNumber).where(DoNotContactNumber.number == target))
    session.execute(update(Contact).where(Contact.phone == target).values(do_not_contact=False, dnc_reason=None))


# ── 셈 ─────────────────────────────────────────────────────────────


def _naive_utc(dt: datetime) -> datetime:
    """DB 와 견줄 UTC(시간대 없음)."""
    return as_utc(dt).replace(tzinfo=None)


def _to_number(model: type[OutreachMessage] | type[OutreachCall], number: str) -> ColumnElement[bool]:
    """그 번호와 주고받은 줄: peer_number 가 그 번호이거나, 연락처(어느 일정이든)의 번호가 그 번호."""
    return or_(model.peer_number == number, model.contact_id.in_(select(Contact.id).where(Contact.phone == number)))


def sent_count(
    session: Session, channel: Literal["sms", "kakao", "call"], day_kst: date, *, number: str | None = None
) -> int:
    """그 서울 날짜에 우리가 내보낸 수. **셈 규칙은 하나**: 거는 쪽(direction out) 줄 가운데 나가려고 차지한 것
    (claim 이 claimed_at 을 찍은 것)을 claimed_at 의 서울 날짜로 센다. 그 뒤 실패·확인 필요가 되어도 세고, 나가기 전에
    막힌 것(시험 모드·근무시간·상한 …으로 차지하지 않은 것)은 세지 않는다. 'sms' 에는 문자로 대신 나간 카카오톡
    (fallback_sms)도 들고 'kakao' 에는 들지 않는다. number 를 주면 그 번호로 간 것만(정리되지 않는 번호면 0)."""
    start = _naive_utc(datetime.combine(day_kst, time(), tzinfo=KST))
    model = OutreachCall if channel == "call" else OutreachMessage
    stmt = select(func.count(model.id)).where(
        model.direction == "out", model.claimed_at >= start, model.claimed_at < start + timedelta(days=1)
    )
    if channel == "sms":
        fell_back = and_(OutreachMessage.channel == "kakao", OutreachMessage.fallback_sms.is_(True))
        stmt = stmt.where(or_(OutreachMessage.channel == "sms", fell_back))
    elif channel == "kakao":
        stmt = stmt.where(OutreachMessage.channel == "kakao", OutreachMessage.fallback_sms.is_(False))
    if number is not None:
        target = normalize(number)
        if target is None:
            return 0
        stmt = stmt.where(_to_number(model, target))
    return session.scalar(stmt) or 0


def auto_replies(session: Session, number: str, since: datetime) -> list[OutreachMessage]:
    """그 번호로 since 뒤에 나간 자동 답·고정 안내(kind auto_reply·notice), 차지한 차례대로. 「나갔다」는 sent_count 와
    같은 규칙(claimed_at 이 since 뒤). 정리되지 않는 번호면 []. 되풀이 상한과 「같은 글 두 번 금지」가 읽는다."""
    target = normalize(number)
    if target is None:
        return []
    stmt = select(OutreachMessage).where(
        OutreachMessage.direction == "out",
        OutreachMessage.kind.in_(("auto_reply", "notice")),
        OutreachMessage.claimed_at >= _naive_utc(since),
        _to_number(OutreachMessage, target),
    )
    return list(session.scalars(stmt.order_by(OutreachMessage.claimed_at, OutreachMessage.id)))


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
