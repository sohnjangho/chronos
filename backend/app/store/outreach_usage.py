"""연락 사용량 요약(Task 112 — 읽기만): 나간 문자·카카오톡·자동 답·통화 수, 통화 시간, 모델·음성 사용량, 알려 준 요금.

창은 서울 날짜로 오늘을 끝으로 한 `days` 일(첫날 서울 자정부터 내일 서울 자정 전까지).
나간 것은 store.outreach 의 셈 규칙 하나를 따른다: 거는 쪽(direction out) 줄 가운데 나가려고 차지한 것(claim 이 찍은
claimed_at)을 claimed_at 의 서울 날짜로 센다 — 그 뒤 실패·확인 필요가 되어도 세고, 차지하지 않은 줄(초안·시험 모드·
근무시간 …)은 세지 않는다. 그래서 하루 창의 sms·kakao·calls_placed 는 store.outreach.sent_count 와 같다.
받는 통화(direction in)는 차지하지 않으므로 줄이 생긴 때(created_at)로 창에 넣는다.
요금은 알려 준 값의 합뿐이다 — 하나도 없으면 None(계산하거나 어림해 채우지 않는다).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.store.outreach import KST
from app.store.tables_outreach import OutreachCall, OutreachMessage, OutreachUsage
from app.store.timeutil import as_utc

__all__ = ["KindUsage", "UsageSummary", "summary"]

AUTO_REPLY_KINDS = ("auto_reply", "notice")  # store.outreach.auto_replies 가 세는 종류와 같다
ANSWERED_IN = ("in_call", "completed")  # 받는 통화 가운데 받은 것(통화하는 중·통화됨)
REJECTED_IN = ("rejected",)  # 받는 통화 가운데 받지 않고 거절한 것(받을 수 없었던 missed 는 들지 않음)


@dataclass(frozen=True)
class KindUsage:
    """outreach_usage 한 종류의 합. seconds 는 알려 준 초의 합(없으면 0), cost 는 알려 준 요금의 합(없으면 None)."""

    count: int
    input_tokens: int
    output_tokens: int
    seconds: int
    cost: float | None


@dataclass(frozen=True)
class UsageSummary:
    """sms = 문자로 나간 것 전부(문자로 대신 나간 카카오톡 포함 — 하루 상한이 세는 수), long = 그 가운데 장문.
    kakao = 대신 나가지 않은 카카오톡. auto_replies = 나간 자동 답·고정 안내. call_seconds = 건 통화와 받은 통화의
    duration_s 합. calls_answered·calls_rejected = 받는 통화 가운데 받은 것·거절한 것. by_kind = outreach_usage 종류별
    (있는 종류만). provider_cost = 제공사가 메시지·통화 줄에 알려 준 요금의 합(없으면 None — 모델 요금은 by_kind 에)."""

    sms: int
    long: int
    kakao: int
    auto_replies: int
    call_seconds: int
    calls_placed: int
    calls_answered: int
    calls_rejected: int
    by_kind: dict[str, KindUsage]
    provider_cost: float | None
    fallback_sms: int = 0  # sms 가운데 카카오톡 요청이 문자로 대신 나간 것(Task 111)
    kakao_not_ready: int = 0  # 그 가운데 하네스 사건 kakao_not_ready 가 남은 것


def _window(days: int, now: datetime | None) -> tuple[datetime, datetime]:
    """[첫날 서울 자정, 내일 서울 자정) 을 DB 와 견줄 UTC(시간대 없음)로."""
    if days < 1:
        raise ValueError("days 는 1 이상이어야 합니다.")
    today: date = (now or datetime.now(KST)).astimezone(KST).date()
    start = datetime.combine(today - timedelta(days=days - 1), time(), tzinfo=KST)
    end = datetime.combine(today + timedelta(days=1), time(), tzinfo=KST)
    return as_utc(start).replace(tzinfo=None), as_utc(end).replace(tzinfo=None)


def _sent(model: type[OutreachMessage] | type[OutreachCall], start: datetime, end: datetime) -> ColumnElement[bool]:
    """셈 규칙 하나(store.outreach.sent_count 와 같음): 거는 쪽이고 claimed_at 이 창 안."""
    return and_(model.direction == "out", model.claimed_at >= start, model.claimed_at < end)


def _received(model: type[OutreachMessage] | type[OutreachCall], start: datetime, end: datetime) -> ColumnElement[bool]:
    return and_(model.direction == "in", model.created_at >= start, model.created_at < end)


def summary(session: Session, *, days: int, now: datetime | None = None) -> UsageSummary:
    """서울 날짜로 오늘을 끝으로 한 days 일의 사용량. now 는 시험이 「오늘」을 정할 때만(없으면 지금)."""
    start, end = _window(days, now)
    m = OutreachMessage
    as_sms = or_(m.channel == "sms", and_(m.channel == "kakao", m.fallback_sms.is_(True)))
    sent_m = _sent(m, start, end)
    sms, long, kakao, auto = session.execute(
        select(
            func.count(m.id).filter(as_sms),
            func.count(m.id).filter(as_sms, m.length_kind == "long"),
            func.count(m.id).filter(m.channel == "kakao", m.fallback_sms.is_(False)),
            func.count(m.id).filter(m.kind.in_(AUTO_REPLY_KINDS)),
        ).where(sent_m)
    ).one()

    instead = session.scalars(select(m.harness_json).where(sent_m, m.channel == "kakao", m.fallback_sms.is_(True))).all()
    not_ready = sum(1 for log in instead if isinstance(log, list)
                    and any(isinstance(e, dict) and e.get("rule") == "kakao_not_ready" for e in log))

    c = OutreachCall
    sent_c, received_c = _sent(c, start, end), _received(c, start, end)
    placed, answered, rejected = session.execute(
        select(
            func.count(c.id).filter(sent_c),
            func.count(c.id).filter(received_c, c.status.in_(ANSWERED_IN)),
            func.count(c.id).filter(received_c, c.status.in_(REJECTED_IN)),
        )
    ).one()
    seconds = session.scalar(select(func.sum(c.duration_s)).where(or_(sent_c, received_c))) or 0

    # 요금: 알려 준 값만 더한다(SUM 은 NULL 을 건너뛰고, 알려 준 값이 하나도 없으면 NULL)
    reported = [
        session.scalar(select(func.sum(m.provider_cost)).where(or_(sent_m, _received(m, start, end)))),
        session.scalar(select(func.sum(c.provider_cost)).where(or_(sent_c, received_c))),
    ]
    known = [value for value in reported if value is not None]

    u = OutreachUsage
    rows = session.execute(
        select(
            u.kind,
            func.count(u.id),
            func.coalesce(func.sum(u.input_tokens), 0),
            func.coalesce(func.sum(u.output_tokens), 0),
            func.coalesce(func.sum(u.seconds), 0),
            func.sum(u.cost),
        )
        .where(u.at >= start, u.at < end)
        .group_by(u.kind)
        .order_by(u.kind)
    ).all()
    by_kind = {kind: KindUsage(count, tokens_in, tokens_out, secs, cost)
               for kind, count, tokens_in, tokens_out, secs, cost in rows}

    return UsageSummary(
        sms=sms, long=long, kakao=kakao, auto_replies=auto, call_seconds=seconds, calls_placed=placed,
        calls_answered=answered, calls_rejected=rejected, by_kind=by_kind,
        provider_cost=sum(known) if known else None, fallback_sms=len(instead), kakao_not_ready=not_ready,
    )
