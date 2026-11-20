"""info.weather: 지난 n년 그 달 통계(코드 계산)·3일 예보·근거 보관·요청당 3번·실패 안내.

기상청은 부르지 않는다(app.info.kma.TRANSPORT 를 가짜로 바꿔 끼운다). 값은 모두 가상이다.
"""

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
    asked = [(q.url.params["startDt"], q.url.params["endDt"], q.url.params["stnIds"]) for q in mock.requests]
    assert asked == [("20241201", "20241231", "108"), ("20251201", "20251231", "108")]


@pytest.mark.parametrize(("month", "first", "last"), [(11, "2016", "2025"), (10, "2017", "2026"), (2, "2017", "2026")])
async def test_history_uses_only_finished_months(use, ctx, month, first, last):
    mock = use(KmaMock(asos=_asos_by_year))
    await call("info.weather", {"place": "서울", "kind": "history", "month": month}, ctx)
    starts = [q.url.params["startDt"][:4] for q in mock.requests]
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
