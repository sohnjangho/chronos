"""info.weather: 지난 n년 그 달 통계(코드 계산)·3일 예보·근거 보관·요청당 3번·실패 안내.

기상청은 부르지 않는다(app.info.kma.TRANSPORT 를 가짜로 바꿔 끼운다). 값은 모두 가상이다.
"""

import asyncio
import dataclasses
import json
from datetime import datetime

import pytest

from app.info import kma
from app.security.crypto import encrypt
from app.store import chats
from app.store.evidence import searches_since
from app.store.tables import EvidenceItem, EvidenceSearch, InfoConnection
from app.tools.data import weather
from app.tools.registry import call, list_tools
from tests.kma_doubles import (
    KEY,
    KEY_ENCODED,
    KmaMock,
    asos_day,
    fcst,
    gateway_body,
    ok_body,
)

NOT_REGISTERED = "이 서비스키는 해당 기상청 서비스에 등록되지 않았습니다(공공데이터포털에서 활용신청을 확인해 주세요)."
FALLBACK = "근거 없이 분야 기본값을 쓰고 '근거 없음, 분야 기본값'이라고 적으세요. 날씨 값을 지어내지 마세요."
NOW = datetime(2026, 11, 20, 21, 15, tzinfo=kma.KST)

YEARS = {  # 손 계산: 2024 평균 2.0·최저 -0.667·영하 2·비 1·최대 5 / 2025 평균 0.6·최저 -2.0·영하 1·비 1·최대 12
    "2024": [asos_day("2024-12-01", "1.0", "-2.0", ""), asos_day("2024-12-02", "3.0", "1.0", "5.0"),
             asos_day("2024-12-03", "", "-1.0", "0.5")],
    "2025": [asos_day("2025-12-01", "-1.0", "-4.0", "12.0"), asos_day("2025-12-02", "2.2", "0.0", "")],
}


def _asos_by_year(request):
    return 200, ok_body(YEARS.get(request.url.params["startDt"][:4], []))


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(weather, "_now", lambda: NOW)


@pytest.fixture
def kma_conn(session):
    conn = InfoConnection(name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL, secret_ciphertext=encrypt(KEY),
                          secret_last4=KEY[-4:], status="ok")
    session.add(conn)
    session.commit()
    return conn


@pytest.fixture
def use(monkeypatch, kma_conn):
    def install(mock: KmaMock) -> KmaMock:
        monkeypatch.setattr(kma, "TRANSPORT", mock)
        return mock

    return install


@pytest.fixture
def ctx_chat(session, ctx):
    chat = chats.create_chat(session, user_id=ctx.user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "겨울 골조 일정을 봐 줘"})
    session.commit()
    return dataclasses.replace(ctx, chat_session_id=chat.id)


def test_tool_is_registered():
    spec = {t.name: t for t in list_tools()}["info.weather"]
    assert spec.mutates and "가정" in spec.description and "3번" in spec.description


async def test_history_stats_are_computed_by_code(use, ctx):
    mock = use(KmaMock(asos=_asos_by_year))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 2}, ctx)
    assert r.ok, r.error
    assert r.output["stats"] == {"tavg": 1.3, "tmin_avg": -1.3, "freezing_days": 1.5, "rain_days": 1.0,
                                 "max_rain_mm": 8.5}
    assert r.output["period"] == "2024~2025년 12월" and r.output["days"] == []
    assert (r.output["years_used"], r.output["missing_years"]) == (2, [])
    asked = [(q.url.params["startDt"], q.url.params["endDt"], q.url.params["stnIds"]) for q in mock.requests]
    assert asked == [("20251201", "20251231", "108"), ("20241201", "20241231", "108")]  # 최근 해부터


@pytest.mark.parametrize(("month", "first", "last"), [(11, "2016", "2025"), (10, "2017", "2026"), (2, "2017", "2026")])
async def test_history_uses_only_finished_months(use, ctx, month, first, last):
    mock = use(KmaMock(asos=_asos_by_year))
    await call("info.weather", {"place": "서울", "kind": "history", "month": month}, ctx)
    starts = sorted(q.url.params["startDt"][:4] for q in mock.requests)
    assert len(starts) == 10 and (starts[0], starts[-1]) == (first, last)  # 이번 달(11월)은 아직 끝나지 않았다


async def test_unknown_place_is_refused(use, ctx):
    mock = use(KmaMock())
    r = await call("info.weather", {"place": "아틀란티스", "kind": "forecast"}, ctx)
    assert not r.ok and r.error == "모르는 위치입니다: 아틀란티스 — 가까운 시·도 이름을 알려 주세요"
    assert mock.requests == []


async def test_place_names_with_suffix_are_found(use, ctx):
    mock = use(KmaMock(fcst=(200, ok_body([]))))
    r = await call("info.weather", {"place": "부산광역시", "kind": "forecast"}, ctx)
    assert r.ok, r.error
    assert (mock.requests[0].url.params["nx"], mock.requests[0].url.params["ny"]) == ("98", "76")


async def test_history_needs_a_month(use, ctx):
    r = await call("info.weather", {"place": "서울", "kind": "history"}, ctx)
    assert not r.ok and "month" in r.error


async def test_weather_saved_as_evidence_with_source(use, ctx, events, session):
    use(KmaMock(asos=_asos_by_year))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 2}, ctx)
    assert r.ok, r.error
    item = session.get(EvidenceItem, r.output["evidence_id"])
    row = session.get(EvidenceSearch, item.search_id)
    assert (row.mode, row.ok, row.result_count) == ("weather", True, 1)
    assert "기상청 ASOS 일자료 · 공공데이터포털" in item.title and item.hostname == "data.go.kr"
    assert "2024~2025년 12월" in item.description and "영하" in item.description
    assert r.output["source"] == "기상청 ASOS 일자료 · 공공데이터포털"
    card = events[-1]
    assert card.type == "card" and card.data["kind"] == "evidence" and card.data["mode"] == "weather"
    assert card.data["results"][0]["evidence_id"] == item.id
    for secret in (KEY, KEY_ENCODED):
        assert secret not in json.dumps(r.output, ensure_ascii=False) and secret not in item.description


async def test_forecast_three_days_and_missing_is_dash(use, ctx, session):
    items = [fcst("20261120", "2200", "POP", "30"),
             fcst("20261121", "0600", "TMN", "-5.0"), fcst("20261121", "1500", "TMX", "3.0"),
             fcst("20261121", "0900", "POP", "20"), fcst("20261122", "1500", "TMX", "6.0"),
             fcst("20261123", "0600", "TMN", "-2.0")]
    use(KmaMock(fcst=(200, ok_body(items))))
    r = await call("info.weather", {"place": "서울", "kind": "forecast"}, ctx)
    assert r.ok, r.error
    days = r.output["days"]
    assert [(d["date"], d["tmin"], d["tmax"], d["pop"]) for d in days] == [
        ("2026-11-20", None, None, 30), ("2026-11-21", -5.0, 3.0, 20), ("2026-11-22", None, 6.0, None)]
    assert days[0]["text"] == "11-20 최저 — · 최고 — · 강수확률 30%"
    assert days[1]["text"] == "11-21 최저 -5.0℃ · 최고 3.0℃ · 강수확률 20%"
    item = session.get(EvidenceItem, r.output["evidence_id"])
    assert r.output["source"] == "기상청 단기예보 · 공공데이터포털" and r.output["source"] in item.title
    assert "2026-11-20 20시 발표" in item.description and r.output["stats"] is None


async def test_unregistered_asos_falls_back_to_field_defaults(use, ctx, session):
    use(KmaMock(asos=(403, gateway_body("30"))))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 1}, ctx)
    assert not r.ok and r.error == f"{NOT_REGISTERED} {FALLBACK}"
    row = session.query(EvidenceSearch).one()
    assert (row.mode, row.ok, row.error_code) == ("weather", False, "not_registered")


async def test_no_connection_says_where_to_set_it(monkeypatch, ctx):
    monkeypatch.setattr(kma, "TRANSPORT", KmaMock())
    r = await call("info.weather", {"place": "서울", "kind": "forecast"}, ctx)
    assert not r.ok and "정보 API 연결" in r.error and r.error.endswith(FALLBACK)


async def test_three_per_request_counted_apart_from_evidence_search(use, ctx_chat, session):
    mock = use(KmaMock(fcst=(200, ok_body([]))))
    used = [(await call("info.weather", {"place": "서울", "kind": "forecast"}, ctx_chat)).output["used"]
            for _ in range(3)]
    assert used == [1, 2, 3]
    r = await call("info.weather", {"place": "서울", "kind": "forecast"}, ctx_chat)
    assert not r.ok and r.error == "이번 요청에서 날씨 조회를 3번 했습니다. 받은 값이나 분야 기본값을 쓰세요."
    assert len(mock.requests) == 3
    assert searches_since(session, ctx_chat.chat_session_id, None) == 0  # 근거 검색 한도에는 들지 않는다


async def test_history_without_any_data_falls_back(use, ctx, session):
    use(KmaMock(asos=(200, {"response": {"header": {"resultCode": "03", "resultMsg": "NO_DATA"}}})))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 2}, ctx)
    assert not r.ok and r.error == f"그 기간의 관측 자료가 없습니다. {FALLBACK}"
    assert session.query(EvidenceSearch).one().error_code == "no_data"


THREE_YEARS = YEARS | {"2023": [asos_day("2023-12-01", "0.0", "-1.0", "2.0")]}


def _flaky(request):
    """2022 는 서버 오류, 2021 은 자료 없음, 2023~2025 는 자료."""
    year = request.url.params["startDt"][:4]
    if year == "2022":
        return 500, {}
    return 200, ok_body(THREE_YEARS.get(year, []))


async def test_period_counts_only_years_with_data_and_skips_a_failing_year(use, ctx, session):
    use(KmaMock(asos=_flaky))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 5}, ctx)
    assert r.ok, r.error
    assert (r.output["period"], r.output["years_used"], r.output["missing_years"]) == (
        "2023~2025년 12월", 3, [2021, 2022])
    item = session.get(EvidenceItem, r.output["evidence_id"])
    assert "2023~2025년 12월" in item.description and "빠진 해 2021·2022" in item.description


async def test_fewer_than_three_years_fails(use, ctx):
    use(KmaMock(asos=_asos_by_year))  # 2024·2025 만 자료
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 10}, ctx)
    assert not r.ok
    assert r.error == f"자료가 있는 해가 2년뿐이라 통계를 내지 않습니다(3년 이상 필요). {FALLBACK}"


async def test_account_errors_stop_at_the_first_year(use, ctx):
    mock = use(KmaMock(asos=(403, gateway_body("22"))))
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12}, ctx)
    assert not r.ok and r.error.startswith(kma.FAILED_MESSAGES["rate_limited"]) and len(mock.requests) == 1


async def test_history_has_an_overall_time_limit(monkeypatch, kma_conn, ctx):
    async def slow_2022(conn, stn, start, end):
        if start.year == 2022:
            await asyncio.sleep(10)
        return [kma.DayObs(start, 1.0, -1.0, 0.0)]

    monkeypatch.setattr(kma, "asos_daily", slow_2022)
    monkeypatch.setattr(weather, "HISTORY_TIMEOUT_S", 0.2)
    r = await call("info.weather", {"place": "서울", "kind": "history", "month": 12, "years": 5}, ctx)
    assert r.ok, r.error
    assert (r.output["period"], r.output["missing_years"]) == ("2023~2025년 12월", [2021, 2022])


def _conn(session, key: str, status: str) -> None:
    session.add(InfoConnection(name=key[:4], preset="kma", base_url=kma.DEFAULT_BASE_URL,
                               secret_ciphertext=encrypt(key), secret_last4=key[-4:], status=status))
    session.commit()


@pytest.mark.parametrize(("rows", "chosen"), [
    ([("OKOLDkey0000", "ok"), ("FAILEDkey111", "failed"), ("NEWESTkey222", "unknown")], "OKOLDkey0000"),
    ([("FAILEDkey111", "failed"), ("NEWESTkey222", "unknown")], "NEWESTkey222"),
])
async def test_connection_prefers_ok_then_newest(monkeypatch, session, ctx, rows, chosen):
    mock = KmaMock(fcst=(200, ok_body([])))
    monkeypatch.setattr(kma, "TRANSPORT", mock)
    for key, status in rows:
        _conn(session, key, status)
    assert (await call("info.weather", {"place": "서울", "kind": "forecast"}, ctx)).ok
    assert f"serviceKey={chosen}&" in mock.requests[0].url.query.decode()


@pytest.mark.parametrize("name", ["광주시", "광주 시"])
async def test_gwangju_si_alone_is_ambiguous(use, ctx, name):
    mock = use(KmaMock())
    r = await call("info.weather", {"place": name, "kind": "forecast"}, ctx)
    assert not r.ok and r.error == "광주광역시인지 경기 광주시인지 알려 주세요" and mock.requests == []


async def test_gwangju_metropolitan_is_found(use, ctx):
    mock = use(KmaMock(fcst=(200, ok_body([]))))
    assert (await call("info.weather", {"place": "광주광역시", "kind": "forecast"}, ctx)).ok
    assert mock.requests[0].url.params["nx"] == "58"
