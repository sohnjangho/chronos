"""관리 포인트 바깥 위험(계획 5 B): 새 포인트마다 분야(schedule.domain)에 켜진 갈래만 찾아 한 줄씩 낸다.

- 무엇을 찾을지는 LLM(light)이 액티비티 이름·WBS·자원·분야만 보고 고른다(weather_sensitive · materials · imported ·
  trade · why). 날짜·주소는 보이지 않는다. 답은 엄격히 읽고 목록 밖·모양이 틀린 값은 버린다.
- 날씨 = 기상청(info.weather 안의 조회 함수): ES 가 오늘부터 3일 안이면 단기예보, 뒤면 ES 달의 지난 n년 통계.
  프로젝트 주소(프로젝트 관리)가 없거나 기상청 지점을 모르면 skipped. 자재·환율 = Liner Search `include_knowledge: true`
  (Premium Data — The World Bank 월별 금속, Xignite 환율). 업체 = Liner MCP `search_business` 첫 줄을 자재·공종 낱말
  (「알루미늄 커튼월 공급 동향」 — 공종은 TRADES 에서만, 금속은 TRADE_METAL 로 맞을 때만)으로 찾고 6개월 안의 글만 쓴다 — 회사·사람 이름은 질의에 넣지 않는다(씨앗 협력사는 가상이라 비슷한 이름의 실제 회사
  소식이 붙는다. 실제 회사라는 표시가 연락처에 생기기 전까지는 이름을 쓰지 않는다).
- 숫자는 받은 표에서 코드가 읽고 계산한다. 없거나 숫자가 아니면 status none 「… · 바깥 자료 없음」(숫자 없음).
- 결과는 근거 표에 출처와 함께 남긴다(날씨 mode weather, 나머지 mode knowledge, 대화 없음). 같은 질의를
  points_forecast_reuse_hours 시간 안에 했으면(성공만) 다시 부르지 않고 그 줄을 쓴다 — 30일 같은 주소 규칙은 쓰지 않는다.
- 부른 쪽은 look 앞뒤로 commit 한다. look 은 LLM·바깥 호출을 모두 끝낸 뒤 맨 끝에 근거 줄을 한꺼번에 넣고 flush 만 한다
  (바깥 응답·llm_calls 기록을 기다리는 동안 쓰기 잠금을 쥐지 않는다). 한 look 안의 같은 질의는 한 번만 부른다.
  키는 기록·결과 어디에도 없다(실패는 종류만 남긴다).
"""

import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.model import Schedule
from app.core.points import Point
from app.info import kma, places
from app.llm import knowledge, mcp_client
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.llm.search import SearchFailed, SearchHit, SearchNotReady, liner_knowledge
from app.store.evidence import KNOWLEDGE_MODE, WEATHER_MODE, recent, record_search
from app.store.schedules import load
from app.store.settings import points_config, sources_for
from app.store.tables import EvidenceItem, ProjectProfile, ScheduleRecord
from app.store.tables_outreach import Contact, ContactCompany
from app.tools.context import ToolError
from app.tools.data import weather

logger = logging.getLogger(__name__)

# 시험이 가짜 LLM transport 를 끼운다. None 이면 LlmClient 의 기본(CHRONOS_FAKE_LLM=1 이면 가짜 Liner).
LLM_TRANSPORT: httpx.AsyncBaseTransport | None = None

Kind = Literal["weather", "materials", "fx", "business"]
Status = Literal["ok", "none", "skipped"]
MATERIALS = ("copper", "aluminum", "iron ore")  # 0단계 실측으로 Premium Data 에 있는 금속(The World Bank)
MATERIAL_NAMES = {"copper": "구리", "aluminum": "알루미늄", "iron ore": "철광석"}
NO_DATA = "바깥 자료 없음"
NO_ADDRESS = "프로젝트 주소가 없어 날씨를 보지 않음"
NO_STATION = "지점을 몰라 날씨를 보지 않음"
FX_QUERY = "USD KRW exchange rate"
FX_LABEL = "원·달러"
TREND_MONTHS = 3
HISTORY_YEARS = 10
LLM_TIMEOUT_S = 30.0
KNOWLEDGE_URL, KNOWLEDGE_HOST = "https://liner.com", "liner.com"  # Premium Data 표에는 링크가 없다
_WHY = 120
# 업체 갈래의 공종 낱말(정해진 낱말만 — LLM 의 trade 는 이 목록에 맞춰 보는 힌트일 뿐). 건설·제조 둘 다.
TRADES = ("커튼월", "창호", "외장 패널", "철골", "철근", "골조", "콘크리트", "레미콘", "방수", "단열", "전기", "설비", "배관",
          "승강기", "도장", "조립", "가공", "부품", "금형", "포장", "용접", "사출", "도금", "주조")
TRADE_METAL = {"커튼월": "aluminum", "창호": "aluminum", "외장 패널": "aluminum", "철골": "iron ore", "철근": "iron ore",
               "전기": "copper", "배관": "copper"}  # 공종 → 질의 앞에 붙일 금속(LLM 이 그 금속을 골랐을 때만)
BUSINESS_RESULTS = 5
BUSINESS_RECENT_DAYS = 183  # 업체 갈래는 6개월 안의 글만
BLOG_HOSTS = ("tistory.com", "brunch.co.kr", "velog.io", "medium.com", "post.naver.com", "egloos.com", "wordpress.com")
_COMPANY_MARKS = re.compile(r"\(주\)|㈜|주식회사|\s+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PAIR = re.compile(r"\(([A-Z]{3})\)\s*to\s.*\(([A-Z]{3})\)")

SYSTEM = (
    "건설·제조 일정의 액티비티 하나를 보고, 일정에 영향을 줄 바깥 자료 중 무엇을 볼지만 고른다. 판단·숫자는 쓰지 않는다.\n"
    "- weather_sensitive: 실외 작업이거나 비·눈·바람·추위에 멈추는 작업(타설·골조·외벽·방수·토공·양중 등)이면 true.\n"
    "- materials: 이 작업에 많이 드는 금속만, 목록 copper·aluminum·iron ore 에서(철근·철골은 iron ore). 없으면 [].\n"
    "- imported: 자재·장비를 외국에서 들여올 가능성이 크면 true(환율을 본다).\n"
    f"- trade: 공급 소식을 볼 공종 낱말 하나, 목록 {'·'.join(TRADES)} 에서만(이름·WBS 에 그 낱말이 있을 때). "
    "회사 이름은 안 된다. 공급 걱정이 없으면 null.\n"
    "- why: 고른 까닭 한 줄(한국어)."
)


@dataclass(frozen=True)
class Risk:
    activity_id: str
    kind: Kind
    line: str
    evidence_id: int | None
    as_of: str | None
    source: str | None
    status: Status
    why: str = ""  # LLM 이 고른 까닭 한 줄(카드에 보인다)


@dataclass(frozen=True)
class _Pick:
    weather_sensitive: bool
    materials: tuple[str, ...]
    imported: bool
    supplier: str | None = None  # 늘 None — 업체 이름은 쓰지 않는다(옛 칸, 부르는 쪽 시험이 이 이름으로 만든다)
    why: str = ""
    trade: str | None = None  # 업체 갈래의 공종 낱말(TRADES 의 것, 이름·WBS 에 있음, 아는 회사·사람 이름과 겹치지 않음)
    trade_asked: bool = False  # LLM 이 공종을 냈으나 받지 않았다(그 포인트 업체 줄은 none)


@dataclass(frozen=True)
class _Found:
    """찾은 것 하나. hit 이 있으면 ok(근거 줄로 남긴다), 없으면 none."""

    line: str
    as_of: str | None = None
    source: str | None = None
    hit: SearchHit | None = None


class _Failed(Exception):
    """보냈지만 실패(근거 표에 실패 한 줄)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NotSent(Exception):
    """부를 수 없다(연결 없음 등). 보내지 않았다."""


def _schema() -> dict:
    props = {"weather_sensitive": {"type": "boolean"},
             "materials": {"type": "array", "items": {"type": "string", "enum": list(MATERIALS)}},
             "imported": {"type": "boolean"}, "trade": {"type": ["string", "null"]}, "why": {"type": "string"}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _checked(parsed: object, seen: str, trade_from: str) -> _Pick | None:
    """엄격히 읽는다: 객체가 아니면 None. bool 이 아닌 값은 False, 목록 밖 자재는 버림. trade 는 이름·WBS 글(trade_from)에
    그대로 있을 때만, why 는 LLM 이 본 글(seen — 이름·WBS·자원)에 없는 숫자가 있으면 버린다(지어낸 낱말·숫자를 싣지 않는다)."""
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get("materials")
    materials = tuple(dict.fromkeys(m for m in raw if isinstance(m, str) and m in MATERIALS)) if isinstance(
        raw, list) else ()
    hint = parsed.get("trade")
    asked = isinstance(hint, str) and bool(hint.strip())
    trade = next((t for t in TRADES if asked and _norm(t) == _norm(hint)), None)
    if trade is not None and _norm(trade) not in _norm(trade_from):
        trade = None
    why = parsed.get("why")
    why = why.strip().splitlines()[0].strip()[:_WHY] if isinstance(why, str) and why.strip() else ""
    if any(n not in set(_NUMBER.findall(seen)) for n in _NUMBER.findall(why)):
        why = ""
    return _Pick(weather_sensitive=parsed.get("weather_sensitive") is True, materials=materials,
                 imported=parsed.get("imported") is True, why=why, trade=trade, trade_asked=asked and trade is None)


def _brief(schedule: Schedule | None, point: Point, domain: str) -> dict:
    """LLM 이 보는 것: 이름·WBS·자원·분야만(날짜·주소 없음)."""
    act = next((a for a in schedule.activities if a.id == point.activity_id), None) if schedule else None
    if act is None or schedule is None:
        return {"name": point.name, "wbs": "", "resources": [], "domain": domain}
    wbs = next((w.name for w in schedule.wbs if w.code == act.wbs), "")
    names = {r.id: r.name for r in schedule.resources}
    return {"name": act.name, "wbs": f"{act.wbs} {wbs}".strip(), "resources": [names.get(r, r) for r in act.resources],
            "domain": domain}


async def _pick(session: Session, brief: dict) -> _Pick | None:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}]
    try:
        reply = await LlmClient(session, transport=LLM_TRANSPORT).chat("light", messages, json_schema=_schema(),
                                                                        timeout_s=LLM_TIMEOUT_S)
    except (LlmNotReady, LlmFailed) as exc:
        logger.warning("관리 포인트 자료 고르기 실패 (%s)", type(exc).__name__)
        return None
    seen = " ".join([brief["name"], brief["wbs"], *brief["resources"]])
    pick = _checked(reply.parsed, seen, " ".join([brief["name"], brief["wbs"]]))
    if pick is None:
        logger.warning("관리 포인트 자료 고르기 실패 (모양이 틀린 답)")
    return pick


def _known_names(session: Session, schedule_id: int, schedule: Schedule | None) -> list[str]:
    """질의에 넣지 않을 이름: 그 일정의 자원·협력사·연락처 사람 이름(가상일 수 있다)."""
    names = [r.name for r in schedule.resources] if schedule is not None else []
    names += session.scalars(select(ContactCompany.name).where(ContactCompany.schedule_id == schedule_id)).all()
    names += session.scalars(select(Contact.name).where(Contact.schedule_id == schedule_id)).all()
    return [n for n in map(_norm, names) if len(n) >= 2]


def _norm(text: str) -> str:
    """견주기용: 「(주)」·「㈜」·「주식회사」·빈칸을 빼고 대소문자를 맞춘다."""
    return _COMPANY_MARKS.sub("", text).casefold()


def _without_names(pick: _Pick | None, names: list[str], brief: dict) -> _Pick | None:
    """둘째 지킴: trade 는 이름·WBS 글에서 아는 이름을 지운 나머지에 있어야 하고 아는 이름을 품지 않아야 한다."""
    if pick is None or pick.trade is None:
        return pick
    t, rest = _norm(pick.trade), _norm(f"{brief['name']} {brief['wbs']}")
    for n in sorted(names, key=len, reverse=True):
        rest = rest.replace(n, "|")
    return pick if t in rest and not any(n in t for n in names) else replace(pick, trade=None, trade_asked=True)


def _place(address: str) -> places.Place | None:
    """주소 앞 두 낱말(시·도, 시·군)로 지점을 찾는다. 더 좁은 것(뒤 낱말)을 먼저, 둘로 읽히는 이름은 쓰지 않는다."""
    found = None
    for word in address.split()[:2]:
        if places.ambiguous(word) is None and (p := places.find(word)) is not None:
            found = p
    return found


# ── 한 갈래씩 찾기(근거 표 기록 없음) ───────────────────────────────────


async def _forecast(session: Session, place: places.Place, point: Point, today: date) -> _Found:
    conn = weather._conn(session)
    issued, text, days = await weather._forecast(conn, place)
    start = max(point.es, today)
    inside = [d for d in days if start <= date.fromisoformat(d.date) <= point.ef and d.pop is not None]
    if not inside:
        return _Found(f"날씨 · {NO_DATA}")
    a, b = date.fromisoformat(inside[0].date), date.fromisoformat(inside[-1].date)
    span = f"{a:%m-%d}" if a == b else f"{a:%m-%d}~{b:%m-%d}"
    pop = max(d.pop for d in inside)
    title = f"{place.name} 예보 {issued} — {weather.FCST_SOURCE}"
    return _Found(f"{span} 강수확률 최고 {pop}% · 기상청 · {issued[5:]}", issued, weather.FCST_SOURCE,
                  SearchHit(title, weather.PORTAL_URL, weather.PORTAL_HOST, text, None))


async def _history(session: Session, place: places.Place, month: int) -> _Found:
    conn = weather._conn(session)
    got = await weather._history(conn, place, month, HISTORY_YEARS)
    title = f"{place.name} 기후 {got.period} — {weather.ASOS_SOURCE}"
    return _Found(f"{month}월 지난 {len(got.used)}년 강수일 평균 {got.stats.rain_days}일 · 기상청", got.period,
                  weather.ASOS_SOURCE, SearchHit(title, weather.PORTAL_URL, weather.PORTAL_HOST, got.text, None))


async def _weather_lookup(session: Session, place: places.Place, point: Point, today: date) -> _Found:
    try:
        if (point.es - today).days < weather.FORECAST_DAYS:
            return await _forecast(session, place, point, today)
        return await _history(session, place, point.es.month)
    except ToolError:  # 기상청 연결 없음·키를 읽을 수 없음
        raise _NotSent from None
    except kma.KmaFailed as e:
        raise _Failed(e.code) from None
    except weather._TooFew:
        raise _Failed("too_few_years") from None
    except weather._NoData:
        raise _Failed("no_data") from None


async def _knowledge(session: Session, query: str) -> list[knowledge.KnowledgeTable]:
    try:
        return knowledge.read(await liner_knowledge(session, query))
    except SearchNotReady:
        raise _NotSent from None
    except SearchFailed as e:
        raise _Failed(e.code) from None


def _table_hit(table: knowledge.KnowledgeTable, line: str) -> SearchHit:
    title = f"{table.title} — {table.source or '출처 미상'} (Liner Premium Data)"
    return SearchHit(title[:300], KNOWLEDGE_URL, KNOWLEDGE_HOST, line, table.as_of)


async def _material(session: Session, commodity: str) -> _Found:
    label = MATERIAL_NAMES[commodity]
    for table in await _knowledge(session, f"{commodity} price"):
        if commodity not in table.title.lower():
            continue
        moved = knowledge.trend(table, TREND_MONTHS)
        if moved is None:
            break
        month = knowledge.sorted_rows(table)[-1][0][:7]
        source = table.source or "출처 미상"
        line = f"{label} {TREND_MONTHS}개월 {moved[2]:+.1f}% · {source} · {month}"
        return _Found(line, month, table.source, _table_hit(table, line))
    return _Found(f"{label} · {NO_DATA}")


def _krw_per_usd(table: knowledge.KnowledgeTable) -> tuple[float, datetime] | None:
    pair = _PAIR.search(table.title)
    if pair is None or set(pair.groups()) != {"USD", "KRW"}:
        return None
    rows = knowledge.sorted_rows(table)
    if not rows or len(rows[-1]) < 2:
        return None
    try:
        value, when = float(rows[-1][1]), datetime.fromisoformat(rows[-1][0])
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0 or when.tzinfo is None:
        return None
    return (value if pair.group(1) == "USD" else 1 / value), when.astimezone(kma.KST)


async def _fx(session: Session) -> _Found:
    for table in await _knowledge(session, FX_QUERY):
        if (got := _krw_per_usd(table)) is None:
            continue
        rate, when = got
        source = table.source or "출처 미상"
        line = f"{FX_LABEL} {round(rate):,}원 · {source} · {when:%m-%d %H:%M} 기준"
        return _Found(line, f"{when:%Y-%m-%d %H:%M}", table.source, _table_hit(table, line))
    return _Found(f"{FX_LABEL} · {NO_DATA}")


def _published(value: str | None) -> date | None:
    """결과의 date 칸(「2026-11-20」·「2026-11-20T…」·「2026.11.20」) → 날짜. 읽지 못하면 None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10].replace(".", "-"))
    except ValueError:
        return None


def _host_rank(host: str) -> int:
    """간단한 호스트 규칙: 공공·기관(.go.kr·.or.kr·.gov·.org)·뉴스(호스트에 news) 0, 블로그·카페·글 모음 2, 그 밖 1."""
    host = host.lower()
    if host.endswith((".go.kr", ".or.kr", ".gov", ".org")) or "news" in host:
        return 0
    if "blog" in host or "cafe." in host or host.endswith(BLOG_HOSTS):
        return 2
    return 1


async def _business(session: Session, label: str) -> _Found:
    """label = 자재·공종 낱말(회사 이름 없음). 줄은 「{label} · {출처 제목} · {호스트}」 — 회사 이름은 출처 제목에 있을 때만.

    결과 가운데 날짜가 있고 오늘부터 BUSINESS_RECENT_DAYS 안인 것만 쓴다(날짜 없음·오래된 글은 버림). 여럿이면 _host_rank 가
    낮은 것(뉴스·기관 먼저, 블로그 나중), 같으면 받은 차례. 남는 것이 없으면 none.
    """
    try:
        result = await mcp_client.field_search(session, label, "business", max_results=BUSINESS_RESULTS)
    except SearchNotReady:
        raise _NotSent from None
    except SearchFailed as e:
        raise _Failed(e.code) from None
    today = weather._now().date()
    fresh = [h for h in result.hits
             if (d := _published(h.date)) is not None and 0 <= (today - d).days <= BUSINESS_RECENT_DAYS]
    if not fresh:
        return _Found(f"{label} · {NO_DATA}")
    first = min(fresh, key=lambda h: _host_rank(h.hostname))  # min 은 같은 값이면 앞의 것
    return _Found(f"{label} · {first.title} · {first.hostname}", first.date, first.hostname, first)


# ── 재사용·기록 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Job:
    activity_id: str
    kind: Kind
    mode: str
    query: str
    none_line: str
    run: Callable[[], Awaitable[_Found]]
    why: str


def _risk(job: _Job, found: _Found, evidence_id: int | None) -> Risk:
    ok = found.hit is not None
    return Risk(job.activity_id, job.kind, found.line if ok else job.none_line, evidence_id if ok else None,
                found.as_of if ok else None, found.source if ok else None, "ok" if ok else "none", job.why)


def _reused(job: _Job, items: list[EvidenceItem]) -> Risk:
    for item in items:
        saved = (item.extra_json or {}).get("risk")
        if isinstance(saved, dict) and isinstance(saved.get("line"), str):
            return Risk(job.activity_id, job.kind, saved["line"], item.id, saved.get("as_of"), saved.get("source"),
                        "ok", job.why)
    return _risk(job, _Found(job.none_line), None)


def _record(session: Session, job: _Job, *, ok: bool, code: str | None, ms: int, found: _Found | None) -> int | None:
    hits = [found.hit] if found is not None and found.hit is not None else []
    _, items = record_search(session, chat_session_id=None, query=job.query, mode=job.mode, ok=ok, error_code=code,
                             latency_ms=ms, hits=hits)
    if not items:
        return None
    items[0].extra_json = {**(items[0].extra_json or {}),
                           "risk": {"line": found.line, "as_of": found.as_of, "source": found.source}}
    session.flush()
    return items[0].id


@dataclass(frozen=True)
class _Fetched:
    """한 질의를 부른 결과. found 가 있으면 성공(hit 이 없으면 자료 없음), 없으면 code 가 있을 때 보낸 뒤 실패, 둘 다 없으면 보내지 않음."""

    found: _Found | None
    code: str | None
    ms: int


async def _fetch(job: _Job) -> _Fetched:
    start = time.perf_counter()
    try:
        found = await job.run()
    except _NotSent:
        return _Fetched(None, None, 0)
    except _Failed as e:
        return _Fetched(None, e.code, int((time.perf_counter() - start) * 1000))
    return _Fetched(found, None, int((time.perf_counter() - start) * 1000))


def _jobs(session: Session, point: Point, pick: _Pick, on: set[str], address: str, today: date) -> list[_Job | Risk]:
    out: list[_Job | Risk] = []
    if "weather" in on and pick.weather_sensitive:
        place = _place(address) if address.strip() else None
        if not address.strip() or place is None:
            out.append(Risk(point.activity_id, "weather", NO_ADDRESS if not address.strip() else NO_STATION, None,
                            None, None, "skipped", pick.why))
        elif (point.es - today).days < weather.FORECAST_DAYS:
            out.append(_Job(point.activity_id, "weather", WEATHER_MODE,
                            f"관리 포인트 예보 {place.name} {max(point.es, today)}~{point.ef}", f"날씨 · {NO_DATA}",
                            lambda p=place: _weather_lookup(session, p, point, today), pick.why))
        else:
            out.append(_Job(point.activity_id, "weather", WEATHER_MODE,
                            f"관리 포인트 기후 {place.name} {point.es.month}월(지난 {HISTORY_YEARS}년)",
                            f"날씨 · {NO_DATA}", lambda p=place: _weather_lookup(session, p, point, today), pick.why))
    if "materials" in on:
        for m in pick.materials:
            out.append(_Job(point.activity_id, "materials", KNOWLEDGE_MODE, f"{m} price",
                            f"{MATERIAL_NAMES[m]} · {NO_DATA}", lambda m=m: _material(session, m), pick.why))
    if "fx" in on and pick.imported:
        out.append(_Job(point.activity_id, "fx", KNOWLEDGE_MODE, FX_QUERY, f"{FX_LABEL} · {NO_DATA}",
                        lambda: _fx(session), pick.why))
    if "business" in on and pick.trade:
        metal = TRADE_METAL.get(pick.trade)
        prefix = f"{MATERIAL_NAMES[metal]} " if metal is not None and metal in pick.materials else ""
        label = f"{prefix}{pick.trade} 공급 동향"
        out.append(_Job(point.activity_id, "business", KNOWLEDGE_MODE, f"business: {label}", f"{label} · {NO_DATA}",
                        lambda q=label: _business(session, q), pick.why))
    elif "business" in on and pick.trade_asked:  # 정해진 공종 낱말에 맞지 않음 — 부르지 않는다
        out.append(Risk(point.activity_id, "business", f"공급 동향 · {NO_DATA}", None, None, None, "none", pick.why))
    return out


async def look(session: Session, schedule_id: int, version: int, points: Sequence[Point],
               outdoor: dict[str, bool] | None = None) -> list[Risk]:
    """새 포인트 앞에서 points_max_new 개만, 포인트 차례·갈래 차례(weather·materials·fx·business)로 위험 줄을 낸다.

    분야에 켜진 갈래가 없으면 LLM 도 부르지 않는다. 고르기가 실패한 포인트는 줄이 없다.
    outdoor 를 주면 고르기가 된 포인트마다 LLM 의 weather_sensitive(실외 작업인가)를 채운다(카드의 「실외 작업」).
    부르는 쪽(Task 5) 약속: look 앞에서 commit(쌓인 쓰기 없이 부른다), 뒤에서 commit. look 은 읽기·LLM·바깥 호출을
    모두 끝낸 뒤 맨 끝에 근거 줄을 한꺼번에 넣고 flush 만 한다 — 바깥 응답을 기다리는 동안 쓰기 잠금을 쥐지 않는다.
    """
    cfg = points_config(session)
    record = session.get(ScheduleRecord, schedule_id)
    domain = record.domain if record is not None else ""
    on = sources_for(session, domain)
    chosen = list(points)[:cfg.max_new]
    if not on or not chosen:
        return []
    try:
        schedule = load(session, schedule_id, version)[0]
    except LookupError:
        schedule = None
    profile = session.get(ProjectProfile, schedule_id)
    address = profile.site_address if profile is not None else ""
    briefs = [(p, _brief(schedule, p, domain)) for p in chosen]
    names = _known_names(session, schedule_id, schedule)
    picks = [(p, _without_names(await _pick(session, brief), names, brief)) for p, brief in briefs]
    if outdoor is not None:
        outdoor.update({p.activity_id: pick.weather_sensitive for p, pick in picks if pick is not None})
    today = weather._now().date()
    rows: list[_Job | Risk] = [j for point, pick in picks if pick is not None
                               for j in _jobs(session, point, pick, on, address, today)]
    reused: dict[tuple[str, str], list[EvidenceItem]] = {}
    fetched: dict[tuple[str, str], _Fetched] = {}  # 한 번 look 안의 같은 질의는 한 번만 부른다
    for job in rows:
        if isinstance(job, Risk) or (key := (job.mode, job.query)) in reused or key in fetched:
            continue
        if (items := recent(session, mode=job.mode, query=job.query, hours=cfg.forecast_reuse_hours)) is not None:
            reused[key] = items
        else:
            fetched[key] = await _fetch(job)
    ids: dict[tuple[str, str], int | None] = {}
    for job in rows:  # 쓰기는 여기서부터(바깥 호출이 다 끝난 뒤)
        if isinstance(job, Risk) or (key := (job.mode, job.query)) not in fetched or key in ids:
            continue
        got = fetched[key]
        if got.found is not None:
            ids[key] = _record(session, job, ok=True, code=None, ms=got.ms, found=got.found)
        elif got.code is not None:
            ids[key] = _record(session, job, ok=False, code=got.code, ms=got.ms, found=None)
    out: list[Risk] = []
    for job in rows:
        if isinstance(job, Risk):
            out.append(job)
        elif (key := (job.mode, job.query)) in reused:
            out.append(_reused(job, reused[key]))
        else:
            found = fetched[key].found or _Found(job.none_line)
            out.append(_risk(job, found, ids.get(key)))
    return out
