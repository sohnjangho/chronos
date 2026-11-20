"""info.weather — 기상청 공공데이터로 그 위치의 지난 n년 그 달 통계(history) 또는 3일 예보(forecast)를 근거로 남긴다.

- 위치는 app.info.places 표에 있는 이름만. 값(통계)은 이 코드가 일자료에서 계산한다(LLM 이 계산하지 않는다).
- 결과는 근거(evidence_searches mode "weather" + evidence_items 한 줄)로 넣고 evidence_id 를 돌려준다. 카드는 근거 카드.
- 한 요청(그 대화의 마지막 사용자 메시지 뒤)에 LIMIT 번까지(실패 포함). 근거 검색(evidence.search)과 따로 센다.
- 실패 줄은 따로 연 짧은 세션에 바로 저장한다(루프가 rollback 해도 한도에 들게). 키는 출력·카드·기록에 없다.
"""

import calendar
import logging
import time
from datetime import date, datetime
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.info import kma, places
from app.info.kma import DayFcst, DayObs, KmaConn, KmaFailed
from app.llm.search import SearchHit
from app.security.crypto import SecretUnreadable, decrypt
from app.store.evidence import (
    WEATHER_MODE,
    last_user_message_at,
    record_search,
    searches_since,
)
from app.store.tables import EvidenceSearch, InfoConnection
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

logger = logging.getLogger(__name__)

LIMIT = 3
LIMIT_MESSAGE = "이번 요청에서 날씨 조회를 3번 했습니다. 받은 값이나 분야 기본값을 쓰세요."
FALLBACK = "근거 없이 분야 기본값을 쓰고 '근거 없음, 분야 기본값'이라고 적으세요. 날씨 값을 지어내지 마세요."
NO_CONNECTION = "날씨를 보려면 설정의 정보 API 연결에 기상청(공공데이터포털) 서비스키를 넣어 주세요."
UNREADABLE_KEY = "저장된 서비스키를 읽을 수 없습니다. 설정에서 키를 다시 넣어 주세요."
NO_DATA = "그 기간의 관측 자료가 없습니다."
ASOS_SOURCE = "기상청 ASOS 일자료 · 공공데이터포털"
FCST_SOURCE = "기상청 단기예보 · 공공데이터포털"
PORTAL_URL, PORTAL_HOST = "https://www.data.go.kr", "data.go.kr"
FORECAST_DAYS = 3
RAIN_DAY_MM = 1.0
DASH = "—"


class WeatherIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place: str = Field(min_length=1, max_length=30, description="시·도 또는 큰 도시 이름(예: 서울, 부산, 경기)")
    kind: Literal["history", "forecast"] = Field(description="history = 지난 n년 그 달 통계, forecast = 3일 예보")
    month: int | None = Field(default=None, ge=1, le=12, description="history 의 달(1~12). forecast 에는 쓰지 않는다")
    years: int = Field(default=10, ge=1, le=10, description="history 로 볼 햇수(끝난 달만, 최근부터)")


class StatsOut(BaseModel):
    """해 평균(그 달 값을 해마다 구해 평균). 자료가 없는 값은 None."""

    tavg: float | None  # 평균기온 ℃
    tmin_avg: float | None  # 평균 최저기온 ℃
    freezing_days: float | None  # 최저기온 0℃ 미만인 날 수
    rain_days: float  # 1mm 이상 강수 날 수
    max_rain_mm: float  # 하루 최대 강수(해마다 최댓값)


class DayOut(BaseModel):
    date: str
    tmin: float | None
    tmax: float | None
    pop: int | None
    text: str  # 없는 값은 「—」


class WeatherOut(BaseModel):
    place: str
    kind: str
    period: str  # 기준 기간 글
    source: str
    evidence_id: int
    used: int
    limit: int
    stats: StatsOut | None = None
    days: list[DayOut] = []


class _NoData(Exception):
    """그 기간의 관측 자료가 하나도 없다."""


def _now() -> datetime:
    return datetime.now(kma.KST)


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def history_stats(by_year: list[list[DayObs]]) -> StatsOut:
    """해마다 그 달 값을 구하고 해 평균을 낸다. 자료가 없는 해는 뺀다(by_year 가 비지 않았다고 본다)."""
    tavg, tmin, freezing, rain_days, max_rain = [], [], [], [], []
    for days in by_year:
        avgs = [d.tavg for d in days if d.tavg is not None]
        mins = [d.tmin for d in days if d.tmin is not None]
        if avgs:
            tavg.append(mean(avgs))
        if mins:
            tmin.append(mean(mins))
            freezing.append(sum(1 for m in mins if m < 0))
        rain_days.append(sum(1 for d in days if d.rain_mm >= RAIN_DAY_MM))
        max_rain.append(max(d.rain_mm for d in days))
    return StatsOut(tavg=_r(_avg(tavg)), tmin_avg=_r(_avg(tmin)), freezing_days=_r(_avg(freezing)),
                    rain_days=_r(mean(rain_days)), max_rain_mm=_r(mean(max_rain)))


def _years(month: int, count: int, today: date) -> list[int]:
    """끝난 달만: 이번 달이나 그 뒤 달이면 작년부터 거슬러 센다(오래된 해부터)."""
    last = today.year if month < today.month else today.year - 1
    return list(range(last - count + 1, last + 1))


def _deg(value: float | None) -> str:
    return DASH if value is None else f"{value:.1f}℃"


def _day_out(day: DayFcst) -> DayOut:
    pop = DASH if day.pop is None else f"{day.pop}%"
    text = f"{day.date:%m-%d} 최저 {_deg(day.tmin)} · 최고 {_deg(day.tmax)} · 강수확률 {pop}"
    return DayOut(date=day.date.isoformat(), tmin=day.tmin, tmax=day.tmax, pop=day.pop, text=text)


def _stats_text(place: places.Place, period: str, years: int, s: StatsOut) -> str:
    return (f"{place.name}(ASOS {place.stn}) {period}, 자료 있는 해 {years}년의 해 평균: 평균기온 {_deg(s.tavg)} · "
            f"평균 최저기온 {_deg(s.tmin_avg)} · 영하(최저 0℃ 미만) {DASH if s.freezing_days is None else s.freezing_days}일 · "
            f"1mm 이상 강수 {s.rain_days}일 · 하루 최대 강수 {s.max_rain_mm}mm(해마다 최댓값의 평균). 출처: {ASOS_SOURCE}")


def _conn(session: Session) -> KmaConn:
    with session.no_autoflush:
        row = session.scalars(select(InfoConnection).where(InfoConnection.preset == "kma")
                              .order_by(InfoConnection.id)).first()
    if row is None:
        raise ToolError(f"{NO_CONNECTION} {FALLBACK}")
    try:
        return KmaConn(row.base_url, decrypt(row.secret_ciphertext))
    except SecretUnreadable:
        raise ToolError(f"{UNREADABLE_KEY} {FALLBACK}") from None


def _record_failure(ctx: ToolContext, query: str, code: str, latency_ms: int) -> None:
    try:
        with Session(ctx.session.get_bind(EvidenceSearch)) as recorder:
            record_search(recorder, chat_session_id=ctx.chat_session_id, query=query, mode=WEATHER_MODE, ok=False,
                          error_code=code, latency_ms=latency_ms, hits=[])
            recorder.commit()
    except Exception as exc:  # noqa: BLE001 — 예외 글에 SQL 과 값이 있을 수 있어 종류만 남긴다
        logger.warning("날씨 조회 실패 기록 저장 실패 (%s)", type(exc).__name__)


async def _history(conn: KmaConn, place: places.Place, month: int, count: int) -> tuple[str, str, StatsOut]:
    years = _years(month, count, _now().date())
    by_year = []
    for year in years:
        days = await kma.asos_daily(conn, place.stn, date(year, month, 1),
                                    date(year, month, calendar.monthrange(year, month)[1]))
        if days:
            by_year.append(days)
    if not by_year:
        raise _NoData
    period = f"{years[0]}~{years[-1]}년 {month}월" if len(years) > 1 else f"{years[0]}년 {month}월"
    stats = history_stats(by_year)
    return period, _stats_text(place, period, len(by_year), stats), stats


async def _forecast(conn: KmaConn, place: places.Place) -> tuple[str, str, list[DayOut]]:
    now = _now()
    base_date, base_time = kma.base_datetime(now)
    found = await kma.short_forecast(conn, place.nx, place.ny, now=now)
    days = [_day_out(d) for d in found if d.date >= now.date()][:FORECAST_DAYS]
    issued = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]} {base_time[:2]}시 발표"
    lines = " / ".join(d.text for d in days) or "받은 예보 없음"
    return issued, f"{place.name}(격자 {place.nx}·{place.ny}) {issued}, 하루별: {lines}. 출처: {FCST_SOURCE}", days


def _card(search_id: int, query: str, evidence_id: int, title: str) -> AgentEvent:
    return AgentEvent("card", {"kind": "evidence", "search_id": search_id, "query": query, "mode": WEATHER_MODE,
                               "results": [{"evidence_id": evidence_id, "title": title, "url": PORTAL_URL,
                                            "hostname": PORTAL_HOST, "date": None}]})


@tool(
    "info.weather",
    "기상청 공공데이터로 위치(시·도·큰 도시 이름)의 날씨 근거를 찾아 보관한다. kind history = 지난 years 년 그 달(month) "
    "통계(평균기온·평균 최저기온·영하 일수·1mm 이상 강수 일수·하루 최대 강수, 해 평균 — 코드가 계산), forecast = 오늘부터 "
    "3일 하루별 최저·최고·강수확률(없는 값은 —). 숫자는 가정(예: 동절기 양생·우천 작업 중지 일수)의 근거로만 쓰고 일정 "
    "날짜를 직접 정하지 않는다. 결과의 evidence_id 를 가정의 evidence_ids 에 넣는다. 한 요청에 3번까지(실패 포함, 근거 "
    "검색과 따로 셈). 실패하면 분야 기본값을 쓰고 '근거 없음, 분야 기본값'이라고 적는다.",
    mutates=True,
)
async def weather(args: WeatherIn, ctx: ToolContext) -> WeatherOut:
    place = places.find(args.place)
    if place is None:
        raise ToolError(f"모르는 위치입니다: {args.place} — 가까운 시·도 이름을 알려 주세요")
    if args.kind == "history" and args.month is None:
        raise ToolError("history 에는 month(1~12)가 필요합니다.")
    used = 0
    if ctx.chat_session_id is not None:
        since = last_user_message_at(ctx.session, ctx.chat_session_id)
        used = searches_since(ctx.session, ctx.chat_session_id, since, weather=True)
    if used >= LIMIT:
        raise ToolError(LIMIT_MESSAGE)
    query = (f"{place.name} {args.month}월 날씨(지난 {args.years}년)" if args.kind == "history"
             else f"{place.name} 3일 예보")
    start = time.perf_counter()
    try:
        conn = _conn(ctx.session)
        if args.kind == "history":
            period, text, stats = await _history(conn, place, args.month, args.years)
            source, days = ASOS_SOURCE, []
        else:
            (period, text, days), source, stats = await _forecast(conn, place), FCST_SOURCE, None
    except KmaFailed as e:
        _record_failure(ctx, query, e.code, int((time.perf_counter() - start) * 1000))
        raise ToolError(f"{e.message} {FALLBACK}") from None
    except _NoData:
        _record_failure(ctx, query, "no_data", int((time.perf_counter() - start) * 1000))
        raise ToolError(f"{NO_DATA} {FALLBACK}") from None
    except ToolError:  # 연결 없음·키를 읽을 수 없음(보내지 않았다)
        _record_failure(ctx, query, "not_ready", int((time.perf_counter() - start) * 1000))
        raise
    title = f"{place.name} {'기후 ' if stats else '예보 '}{period} — {source}"
    hit = SearchHit(title=title, url=PORTAL_URL, hostname=PORTAL_HOST, description=text, date=None)
    search_id, items = record_search(ctx.session, chat_session_id=ctx.chat_session_id, query=query, mode=WEATHER_MODE,
                                     ok=True, error_code=None, latency_ms=int((time.perf_counter() - start) * 1000),
                                     hits=[hit])
    ctx.emit(_card(search_id, query, items[0].id, title))
    return WeatherOut(place=place.name, kind=args.kind, period=period, source=source, evidence_id=items[0].id,
                      used=used + 1, limit=LIMIT, stats=stats, days=days)
