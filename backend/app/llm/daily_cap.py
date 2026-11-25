"""하루 LLM 비용 상한(PM 11-25): 「하루 LLM 비용 상한(USD)」. 기본은 끔(막지 않음).

- 상한: 환경 변수 CHRONOS_LLM_DAILY_USD(`chronos --llm-daily-usd 10` 이 이것을 넣는다)가 있으면 그 값(화면에서 못 바꿈),
  없으면 settings 표의 llm_daily_usd(개발 콘솔 → 하네스·에이전트 설정). 0 이하·숫자 아님·빈 값은 「없음」.
- 오늘 = 서울(Asia/Seoul — 이 서버의 지역 시간대) 날짜: 서울 자정부터 다음 자정 전까지. 자정에 0 에서 다시 센다.
  사용량 탭의 날짜 창(app.store.traces)과 같은 기준이다.
- 오늘 쓴 돈 = 오늘 llm_calls 에 적힌 cost 의 합(가격표로 어림한 「추정」 포함). 비용이 적히는 유료 호출: 채팅(모든 쓰임새) ·
  임베딩 · Search Agent(1회 $0.02). Liner Search·Premium Data·MCP·Visualization 은 비용을 적지 않아 합에는 없지만,
  상한에 닿으면 함께 막는다. 연락(outreach_usage — 음성 모델 등)은 Liner 가 아니라 세지도 막지도 않는다.
- 부르기 전에 check 한다. 쓴 돈 ≥ 상한이면 보내지 않고 DailyCapReached(다시 시도하지 않는다 · 아무것도 적지 않는다).
  이미 떠난 호출은 막지 않으므로 마지막 한 번(또는 동시에 떠난 몇 번)은 상한을 조금 넘을 수 있다.
"""

import logging
import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.store import settings as settings_store
from app.store.tables import LlmCall
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

ENV = "CHRONOS_LLM_DAILY_USD"
CODE = "daily_cap"
SEOUL = ZoneInfo("Asia/Seoul")


def message(cap: float) -> str:
    return (f"오늘 LLM 비용 상한(${cap:.2f})에 닿아 내일 다시 쓸 수 있습니다. "
            "관리자가 개발 콘솔 → 「하네스·차단 시험」 탭에서 상한을 바꿀 수 있습니다.")


class DailyCapReached(Exception):
    """오늘 쓴 돈이 상한에 닿아 부르지 않았다. message 는 화면·에이전트에 보일 한국어 설명."""

    code = CODE

    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.message = message(cap)
        super().__init__(self.message)


def parse(raw: str | None) -> float | None:
    """양의 유한한 숫자면 그 값, 아니면 None(없음)."""
    try:
        value = float(raw) if raw is not None and raw.strip() else None
    except ValueError:
        return None
    return value if value is not None and math.isfinite(value) and value > 0 else None


def env_cap() -> float | None:
    raw = os.environ.get(ENV)
    value = parse(raw)
    if value is None and raw is not None and raw.strip() and raw.strip() != "0":
        logger.warning("%s 값을 읽을 수 없어 무시합니다(양의 숫자여야 합니다).", ENV)
    return value


def cap(session: Session) -> tuple[float | None, bool]:
    """(상한, 환경 변수로 정했나). 상한 None = 없음."""
    value = env_cap()
    if value is not None:
        return value, True
    with session.no_autoflush:
        return settings_store.llm_daily_usd(session), False


def _naive_utc(dt: datetime) -> datetime:
    return as_utc(dt).replace(tzinfo=None)


def spent_today(session: Session, now: datetime | None = None) -> float:
    """now(기본: 지금)가 든 서울 날짜에 llm_calls 에 적힌 비용의 합(추정 포함)."""
    local = (now or datetime.now(SEOUL)).astimezone(SEOUL)
    start = datetime(local.year, local.month, local.day, tzinfo=SEOUL)
    end = start + timedelta(days=1)
    query = select(func.coalesce(func.sum(LlmCall.cost), 0.0)).where(
        LlmCall.created_at >= _naive_utc(start), LlmCall.created_at < _naive_utc(end))
    with session.no_autoflush:
        return float(session.scalar(query) or 0.0)


def check(session: Session, now: datetime | None = None) -> None:
    """유료 호출 바로 전에 부른다. 상한이 있고 오늘 쓴 돈 ≥ 상한이면 DailyCapReached. 세션은 읽기만 한다."""
    limit, _ = cap(session)
    if limit is not None and spent_today(session, now) >= limit:
        raise DailyCapReached(limit)


def status(session: Session) -> dict:
    """화면용: 상한(없으면 None) · 환경 변수로 정했나 · 오늘 쓴 돈."""
    limit, fixed = cap(session)
    return {"cap_usd": limit, "fixed_by_env": fixed, "spent_today_usd": spent_today(session)}
