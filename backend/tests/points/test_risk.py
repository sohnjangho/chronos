"""관리 포인트 바깥 위험(app.points.risk): 분야별 갈래·LLM(light) 고르기·날씨(기상청)·자재·환율(Premium Data)·업체(MCP)·
재사용 시간·근거 표. 가짜 Liner·가짜 기상청·가짜 MCP·가짜 LLM 만 쓴다(네트워크 없음). 값은 모두 가상 또는 실측 표본을 줄인 것.
"""

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.model import Resource
from app.core.points import Point
from app.info import kma
from app.llm import search
from app.points import risk
from app.points.risk import Risk
from app.security.crypto import encrypt
from app.store.tables import (
    EvidenceItem,
    EvidenceSearch,
    InfoConnection,
    ProjectProfile,
    ScheduleRecord,
    Setting,
)
from app.tools.data import weather
from tests import kma_doubles
from tests.kma_doubles import KmaMock, asos_day, fcst, ok_body
from tests.llm_doubles import KEY, FakeLiner, add_connection, chat_body
from tests.schedules import make, store, task
from tests.search_doubles import hit, mock_json, route

SAMPLE = json.loads((Path(__file__).parent.parent / "fixtures" / "liner_knowledge_real_sample.json").read_text())
NOW = datetime(2026, 11, 24, 17, 30, tzinfo=kma.KST)
SOON = Point("A", "3층 슬래브 타설", True, 0, date(2026, 11, 25), date(2026, 11, 26))
LATER = Point("A", "3층 슬래브 타설", True, 0, date(2026, 12, 10), date(2026, 12, 14))
ALL = {"weather_sensitive": True, "materials": ["aluminum", "copper"], "imported": True, "supplier": "한빛창호",
       "why": "실외 타설이고 알루미늄 창호를 들여온다"}
NOTHING = {"weather_sensitive": False, "materials": [], "imported": False, "supplier": None, "why": "실내 작업"}
NO_DATA = "바깥 자료 없음"


class Web(httpx.MockTransport):
    """가짜 Liner Search: 질의 → 응답 본문(없으면 knowledge 없는 응답)."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.answers = {SAMPLE[k]["query"]: SAMPLE[k]["body"] for k in ("copper", "aluminum", "iron ore")}
        self.answers["USD KRW exchange rate"] = SAMPLE["usd_krw"]["body"]
        self.answers.update(answers or {})
        super().__init__(self._handle)

    def queries(self) -> list[str]:
        return [json.loads(r.content)["query"] for r in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.answers.get(json.loads(request.content)["query"], SAMPLE["rebar_none"]["body"])
        if isinstance(body, int):
            return httpx.Response(body, json={})
        return httpx.Response(200, json=body)


def _forecast_rows():
    base = ("20261124", "1700")
    return [fcst("20261124", "1800", "POP", "10", base), fcst("20261125", "0900", "POP", "60", base),
            fcst("20261125", "1500", "POP", "40", base), fcst("20261126", "0900", "POP", "30", base),
            fcst("20261127", "0900", "POP", "90", base)]


YEARS = {"2023": [asos_day("2023-12-01", "1.0", "-1.0", "3.0"), asos_day("2023-12-02", "1.0", "-1.0", "2.0")],
         "2024": [asos_day("2024-12-01", "1.0", "-1.0", "1.5"), asos_day("2024-12-02", "1.0", "-1.0", "")],
         "2025": [asos_day("2025-12-01", "1.0", "-1.0", "4.0"), asos_day("2025-12-02", "1.0", "-1.0", "9.0"),
                  asos_day("2025-12-03", "1.0", "-1.0", "0.2")]}  # 1mm 이상 강수 2·1·2일 → 평균 1.7


class Fakes:
    def __init__(self, liner: FakeLiner, web: Web, mcp, kma_mock: KmaMock) -> None:
        self.liner, self.web, self.mcp, self.kma = liner, web, mcp, kma_mock

    def classify(self, *answers: dict) -> None:
        self.liner.push(*(chat_body(json.dumps(a, ensure_ascii=False)) for a in answers))

    def calls(self) -> tuple[int, int, int]:
        """(Liner Search, MCP tools/call, 기상청) 부른 수."""
        return len(self.web.requests), len(self.mcp.bodies("tools/call")), len(self.kma.requests)


@pytest.fixture
def fakes(session, monkeypatch) -> Fakes:
    add_connection(session)
    session.add(InfoConnection(name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL,
                               secret_ciphertext=encrypt(kma_doubles.KEY), secret_last4="==", status="ok"))
    session.commit()
    liner, web = FakeLiner(), Web()
    mcp = mock_json([hit("한빛창호, 알루미늄 창호 납기 2주 늦어져", "https://news.example.com/n1",
                         hostname="news.example.com", date="2026-11-20")])
    kma_mock = KmaMock(asos=lambda r: (200, ok_body(YEARS.get(r.url.params["startDt"][:4], []))),
                       fcst=(200, ok_body(_forecast_rows())))
    monkeypatch.setattr(risk, "LLM_TRANSPORT", liner.transport)
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    monkeypatch.setattr(kma, "TRANSPORT", kma_mock)
    monkeypatch.setattr(weather, "_now", lambda: NOW)
    return Fakes(liner, web, mcp, kma_mock)


def _schedule(session, *, domain: str = "construction", address: str | None = "서울특별시 강남구 테헤란로 1") -> int:
    s = make([task("A", 3, name="3층 슬래브 타설", resources=("crane", "hb", "dr")), task("B", 2, name="창호 설치")],
             resources=[Resource("crane", "타워크레인", "대", 1), Resource("hb", "한빛창호", "팀", 1),
                        Resource("dr", "다른창호", "팀", 1)])
    sid = store(session, s)
    session.execute(update(ScheduleRecord).where(ScheduleRecord.id == sid).values(domain=domain))
    if address is not None:
        session.add(ProjectProfile(schedule_id=sid, site_address=address))
    session.commit()
    return sid


def _hours_ago(hours: int) -> datetime:
    return (datetime.now(UTC) - timedelta(hours=hours)).replace(tzinfo=None)  # DB 는 시간대 없는 UTC


def _by_kind(risks: list[Risk]) -> dict[str, list[Risk]]:
    out: dict[str, list[Risk]] = {}
    for r in risks:
        out.setdefault(r.kind, []).append(r)
    return out


# ── 분야별 갈래 · LLM 고르기 ─────────────────────────────────────────────

async def test_construction_looks_at_all_four(session, fakes):
    sid = _schedule(session)
    fakes.classify(ALL)
    risks = await risk.look(session, sid, 1, [SOON])
    assert [r.kind for r in risks] == ["weather", "materials", "materials", "fx", "business"]
    assert {r.status for r in risks} == {"ok"}
    assert all(r.activity_id == "A" and r.why == ALL["why"] for r in risks)


async def test_off_sources_are_not_called(session, fakes):
    sid = _schedule(session, domain="manufacturing")  # 날씨 끔
    fakes.classify(ALL)
    risks = await risk.look(session, sid, 1, [SOON])
    assert "weather" not in _by_kind(risks) and len(fakes.kma.requests) == 0
    other = _schedule(session, domain="software")  # 업체만
    fakes.classify({**ALL, "supplier": "다른창호"})  # 같은 업체면 6시간 재사용이라 부르지 않는다
    before = fakes.calls()
    risks = await risk.look(session, other, 1, [SOON])
    assert [r.kind for r in risks] == ["business"]
    assert fakes.calls()[0] == before[0] and fakes.calls()[2] == before[2]  # Search·기상청 0번 더
    assert fakes.calls()[1] == before[1] + 1


async def test_no_sources_means_no_llm_call(session, fakes):
    sid = _schedule(session, domain="software")
    session.add(Setting(key="points_sources", value=json.dumps({"software": []})))
    session.commit()
    assert await risk.look(session, sid, 1, [SOON]) == []
    assert fakes.liner.requests == [] and fakes.calls() == (0, 0, 0)


async def test_llm_sees_only_name_wbs_resources_domain(session, fakes):
    sid = _schedule(session)
    fakes.classify(NOTHING)
    await risk.look(session, sid, 1, [SOON])
    body = fakes.liner.last_body
    sent = json.dumps(body["messages"], ensure_ascii=False)
    assert "3층 슬래브 타설" in sent and "골조" in sent and "타워크레인" in sent and "construction" in sent
    assert "2026" not in sent and "11-25" not in sent and "테헤란로" not in sent and "서울" not in sent
    assert body["response_format"]["json_schema"]["schema"]["properties"]["materials"]["items"]["enum"] == [
        "copper", "aluminum", "iron ore"]


async def test_nothing_chosen_means_no_lookups(session, fakes):
    sid = _schedule(session)
    fakes.classify(NOTHING)
    assert await risk.look(session, sid, 1, [SOON]) == []
    assert fakes.calls() == (0, 0, 0)


async def test_off_list_answers_are_dropped(session, fakes):
    sid = _schedule(session)
    fakes.classify({"weather_sensitive": "yes", "materials": ["aluminum", "steel rebar", "Copper", "aluminum", 3],
                    "imported": 1, "supplier": "  ", "why": "첫 줄\n둘째 줄", "extra": "더"})
    risks = await risk.look(session, sid, 1, [SOON])
    assert [(r.kind, r.line.split(" ")[0]) for r in risks] == [("materials", "알루미늄")]
    assert risks[0].why == "첫 줄"
    assert fakes.web.queries() == ["aluminum price"]


@pytest.mark.parametrize("reply", [chat_body("JSON 아님"), chat_body(json.dumps(["목록"])), httpx.Response(500)])
async def test_unusable_llm_reply_gives_nothing(session, fakes, reply):
    sid = _schedule(session)
    fakes.liner.push(reply)
    assert await risk.look(session, sid, 1, [SOON]) == []
    assert fakes.calls() == (0, 0, 0)


@pytest.mark.parametrize("supplier,why,kept", [
    ("한빛창호", "3층 타설에 한빛창호 창호가 든다", ("한빛창호", "3층 타설에 한빛창호 창호가 든다")),  # 글에 있는 이름·숫자
    ("대한알루미늄", "강수확률 70% 라서", (None, "")),  # 본 글에 없는 업체·숫자는 버린다
])
async def test_supplier_and_why_must_come_from_what_llm_saw(session, fakes, supplier, why, kept):
    sid = _schedule(session)
    fakes.classify({**NOTHING, "weather_sensitive": True, "supplier": supplier, "why": why})
    risks = await risk.look(session, sid, 1, [SOON])
    assert risks[0].why == kept[1]
    assert [r.kind for r in risks] == (["weather", "business"] if kept[0] else ["weather"])
    assert [c["params"]["arguments"]["query"].split(" ")[0] for c in fakes.mcp.bodies("tools/call")] == (
        [kept[0]] if kept[0] else [])


async def test_only_first_max_new_points(session, fakes):
    sid = _schedule(session)
    session.add(Setting(key="points_max_new", value="2"))
    session.commit()
    pts = [SOON, Point("B", "창호 설치", False, 2, date(2026, 11, 26), date(2026, 11, 27)),
           Point("C", "도장", False, 3, date(2026, 11, 27), date(2026, 11, 28))]
    fakes.classify(NOTHING, NOTHING, NOTHING)
    await risk.look(session, sid, 1, pts)
    assert len(fakes.liner.requests) == 2


# ── 날씨(기상청) ────────────────────────────────────────────────────────

async def test_weather_forecast_when_es_within_three_days(session, fakes):
    sid = _schedule(session)
    fakes.classify({**NOTHING, "weather_sensitive": True})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert (r.kind, r.status) == ("weather", "ok")
    assert r.line == "11-25~11-26 강수확률 최고 60% · 기상청 · 11-24 17시 발표"
    assert r.as_of == "2026-11-24 17시 발표" and r.source == weather.FCST_SOURCE
    assert fakes.kma.of("VilageFcst") and not fakes.kma.of("AsosDaly")
    assert fakes.kma.of("VilageFcst")[0].url.params["nx"] == "60"  # 서울 격자


async def test_weather_history_when_es_later(session, fakes):
    sid = _schedule(session)
    fakes.classify({**NOTHING, "weather_sensitive": True})
    [r] = await risk.look(session, sid, 1, [LATER])
    assert r.line == "12월 지난 3년 강수일 평균 1.7일 · 기상청"
    assert r.status == "ok" and r.as_of == "2023~2025년 12월" and r.source == weather.ASOS_SOURCE
    assert not fakes.kma.of("VilageFcst") and fakes.kma.of("AsosDaly")[0].url.params["stnIds"] == "108"


@pytest.mark.parametrize("address,line", [(None, "현장 주소가 없어 날씨를 보지 않음"),
                                          ("   ", "현장 주소가 없어 날씨를 보지 않음"),
                                          ("화성 기지 1호", "지점을 몰라 날씨를 보지 않음")])
async def test_weather_skipped_without_place_others_go_on(session, fakes, address, line):
    sid = _schedule(session, address=address)
    fakes.classify(ALL)
    risks = await risk.look(session, sid, 1, [SOON])
    w = _by_kind(risks)["weather"]
    assert [(x.status, x.line, x.evidence_id) for x in w] == [("skipped", line, None)]
    assert len(fakes.kma.requests) == 0
    assert {r.status for r in risks if r.kind != "weather"} == {"ok"}


async def test_weather_place_from_province_and_city(session, fakes):
    sid = _schedule(session, address="경기도 이천시 부발읍 1")
    fakes.classify({**NOTHING, "weather_sensitive": True})
    await risk.look(session, sid, 1, [SOON])
    assert fakes.kma.of("VilageFcst")[0].url.params["nx"] == "68"  # 수원(경기)이 아니라 이천


async def test_weather_without_forecast_values_is_none(session, fakes):
    fakes.kma.fcst = (200, ok_body([]))
    sid = _schedule(session)
    fakes.classify({**NOTHING, "weather_sensitive": True})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert (r.status, r.evidence_id) == ("none", None) and NO_DATA in r.line and not re.search(r"\d", r.line)


async def test_weather_kma_failure_is_none(session, fakes):
    fakes.kma.fcst = (200, kma_doubles.gateway_body("30"))
    sid = _schedule(session)
    fakes.classify({**NOTHING, "weather_sensitive": True})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert r.status == "none" and NO_DATA in r.line


# ── 자재·환율(Premium Data) ─────────────────────────────────────────────

async def test_materials_trend_line(session, fakes):
    sid = _schedule(session)
    fakes.classify({**NOTHING, "materials": ["aluminum"]})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert r.line == "알루미늄 3개월 -8.6% · The World Bank · 2024-08"  # 표본 4줄: 2565 → 2344
    assert (r.status, r.source, r.as_of) == ("ok", "The World Bank", "2024-08")
    sent = json.loads(fakes.web.requests[0].content)
    assert sent == {"query": "aluminum price", "max_results": 3, "include_knowledge": True}


async def test_materials_without_knowledge_is_none(session, fakes):
    fakes.web.answers["copper price"] = SAMPLE["rebar_none"]["body"]
    broken = json.loads(json.dumps(SAMPLE["iron ore"]["body"]))
    broken["knowledge"][0]["rows"][-1][1] = "N/A"
    fakes.web.answers["iron ore price"] = broken
    sid = _schedule(session)
    fakes.classify({**NOTHING, "materials": ["copper", "iron ore"]})
    risks = await risk.look(session, sid, 1, [SOON])
    assert [(r.status, r.line, r.evidence_id) for r in risks] == [
        ("none", f"구리 · {NO_DATA}", None), ("none", f"철광석 · {NO_DATA}", None)]


async def test_materials_liner_failure_is_none(session, fakes):
    fakes.web.answers["copper price"] = 402
    sid = _schedule(session)
    fakes.classify({**NOTHING, "materials": ["copper"]})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert (r.status, r.line) == ("none", f"구리 · {NO_DATA}")


@pytest.mark.parametrize("sample", ["usd_krw", "krw_usd"])
async def test_fx_line_in_krw_per_usd(session, fakes, sample):
    fakes.web.answers["USD KRW exchange rate"] = SAMPLE[sample]["body"]
    sid = _schedule(session)
    fakes.classify({**NOTHING, "imported": True})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert r.line == "원·달러 1,344원 · Xignite · 11-24 15:39 기준"  # 06:39 UTC = 15:39 KST, 0.000743785 → 1/x
    assert (r.status, r.source, r.as_of) == ("ok", "Xignite", "2026-11-24 15:39")


async def test_fx_without_table_is_none(session, fakes):
    fakes.web.answers["USD KRW exchange rate"] = SAMPLE["copper"]["body"]  # 환율 표가 아님
    sid = _schedule(session)
    fakes.classify({**NOTHING, "imported": True})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert (r.status, r.line) == ("none", f"원·달러 · {NO_DATA}")


# ── 업체(MCP) ──────────────────────────────────────────────────────────

async def test_business_first_result_line(session, fakes):
    sid = _schedule(session)
    fakes.classify({**NOTHING, "supplier": "한빛창호"})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert r.line == "한빛창호, 알루미늄 창호 납기 2주 늦어져 · news.example.com"
    assert (r.status, r.source, r.as_of) == ("ok", "news.example.com", "2026-11-20")
    call = fakes.mcp.bodies("tools/call")[0]["params"]
    assert call["name"] == "search_business" and "한빛창호" in call["arguments"]["query"]


async def test_business_no_result_is_none(session, fakes):
    fakes.mcp.call = {"result": {"content": [{"type": "text", "text": json.dumps({"results": [], "totalCount": 0})}],
                                 "isError": False}}
    sid = _schedule(session)
    fakes.classify({**NOTHING, "supplier": "한빛창호"})
    [r] = await risk.look(session, sid, 1, [SOON])
    assert (r.status, r.line, r.evidence_id) == ("none", f"한빛창호 · {NO_DATA}", None)


# ── 근거 표 · 재사용 ─────────────────────────────────────────────────────

async def test_results_are_kept_as_evidence_with_sources(session, fakes):
    sid = _schedule(session)
    fakes.classify(ALL)
    risks = await risk.look(session, sid, 1, [SOON])
    session.commit()
    for r in risks:
        item = session.get(EvidenceItem, r.evidence_id)
        found = session.get(EvidenceSearch, item.search_id)
        assert item.extra_json["risk"] == {"line": r.line, "as_of": r.as_of, "source": r.source}
        assert found.ok and found.chat_session_id is None
        assert found.mode == ("weather" if r.kind == "weather" else "knowledge")
    metal = session.get(EvidenceItem, _by_kind(risks)["materials"][0].evidence_id)
    assert "The World Bank" in metal.title and "Aluminum Price" in metal.title
    assert session.get(EvidenceItem, _by_kind(risks)["business"][0].evidence_id).url == "https://news.example.com/n1"


async def test_same_lookup_reused_within_hours_then_called_again(session, fakes):
    sid = _schedule(session)
    fakes.classify(ALL, ALL, ALL)
    first = await risk.look(session, sid, 1, [SOON])
    session.commit()
    calls = fakes.calls()
    again = await risk.look(session, sid, 1, [SOON])
    assert fakes.calls() == calls  # 6시간 안: Search·MCP·기상청을 다시 부르지 않는다
    assert [(r.line, r.evidence_id, r.status) for r in again] == [(r.line, r.evidence_id, r.status) for r in first]
    session.execute(update(EvidenceSearch).values(created_at=_hours_ago(7)))
    session.commit()
    await risk.look(session, sid, 1, [SOON])
    assert fakes.calls() == tuple(2 * n for n in calls)


async def test_reuse_window_follows_setting(session, fakes):
    sid = _schedule(session)
    session.add(Setting(key="points_forecast_reuse_hours", value="1"))
    session.commit()
    fakes.classify({**NOTHING, "materials": ["copper"]}, {**NOTHING, "materials": ["copper"]})
    await risk.look(session, sid, 1, [SOON])
    session.commit()
    session.execute(update(EvidenceSearch).values(created_at=_hours_ago(2)))
    session.commit()
    await risk.look(session, sid, 1, [SOON])
    assert fakes.web.queries() == ["copper price", "copper price"]


async def test_none_result_reused_too_but_failure_is_not(session, fakes):
    fakes.web.answers["copper price"] = SAMPLE["rebar_none"]["body"]
    fakes.web.answers["iron ore price"] = 500
    sid = _schedule(session)
    pick = {**NOTHING, "materials": ["copper", "iron ore"]}
    fakes.classify(pick, pick)
    await risk.look(session, sid, 1, [SOON])
    session.commit()
    risks = await risk.look(session, sid, 1, [SOON])
    assert fakes.web.queries() == ["copper price", "iron ore price", "iron ore price"]
    assert [r.status for r in risks] == ["none", "none"]
    failed = session.scalars(select(EvidenceSearch).where(EvidenceSearch.ok.is_(False))).all()
    assert [f.error_code for f in failed] == ["server_error", "server_error"]


async def test_retired_evidence_is_not_reused(session, fakes):
    sid = _schedule(session)
    pick = {**NOTHING, "materials": ["copper"]}
    fakes.classify(pick, pick)
    [r] = await risk.look(session, sid, 1, [SOON])
    session.commit()
    session.get(EvidenceItem, r.evidence_id).retired = True
    session.commit()
    await risk.look(session, sid, 1, [SOON])
    assert fakes.web.queries() == ["copper price", "copper price"]


async def test_same_query_twice_in_one_look_is_called_once(session, fakes):
    sid = _schedule(session)
    pick = {**NOTHING, "materials": ["copper"]}
    fakes.classify(pick, pick)
    other = Point("B", "창호 설치", False, 2, date(2026, 11, 26), date(2026, 11, 27))
    risks = await risk.look(session, sid, 1, [SOON, other])
    assert fakes.web.queries() == ["copper price"]
    assert [r.activity_id for r in risks] == ["A", "B"] and risks[0].evidence_id == risks[1].evidence_id is not None


async def test_no_write_lock_held_while_waiting_on_sources(session, fakes):
    """바깥 응답을 기다리는 동안 다른 세션이 쓸 수 있다(look 이 쓰기 잠금을 쥐고 있지 않다)."""
    engine = session.get_bind()
    wrote: list[int] = []

    def other_session_writes() -> None:
        with Session(engine) as other:
            other.add(Setting(key=f"probe_{len(wrote)}", value="x"))
            other.commit()  # 잠금을 쥔 쪽이 있으면 database is locked
        wrote.append(1)

    for t in (fakes.web, fakes.mcp, fakes.kma):
        real = t.handle_request

        def handle(request, real=real):
            other_session_writes()
            return real(request)

        t.handle_request = handle
    sid = _schedule(session)
    fakes.classify(ALL)
    risks = await risk.look(session, sid, 1, [SOON])
    assert len(wrote) >= 5 and {r.status for r in risks} == {"ok"}  # 기상청 1 + Search 3 + MCP(세션 열기 포함)
    session.commit()
    assert session.scalar(select(func.count()).select_from(EvidenceSearch)) == 5


async def test_keys_never_logged(session, fakes, caplog):
    fakes.web.answers["copper price"] = 401
    fakes.kma.fcst = (200, kma_doubles.gateway_body("30"))
    sid = _schedule(session)
    fakes.classify(ALL)
    caplog.set_level(logging.DEBUG)
    await risk.look(session, sid, 1, [SOON])
    assert KEY not in caplog.text and kma_doubles.KEY not in caplog.text and kma_doubles.KEY_ENCODED not in caplog.text
