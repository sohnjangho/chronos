"""하루 LLM 비용 상한: 끔·아래·닿음·넘음, 서울 자정 경계, 추정 비용 포함, 환경 변수 우선, 부르기 전에 막기."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.llm import daily_cap, embeddings, search, search_agent, visualization
from app.llm.client import LlmFailed
from app.store import settings as settings_store
from app.store.tables import LlmCall

SEOUL = ZoneInfo("Asia/Seoul")
HI = [{"role": "user", "content": "hi"}]
MESSAGE_10 = "오늘 LLM 비용 상한($10.00)에 닿아 내일 다시 쓸 수 있습니다. 관리자가 개발 콘솔 → 설정에서 상한을 바꿀 수 있습니다."


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(daily_cap.ENV, raising=False)


def _spend(session, cost, *, at=None, estimated=False, purpose="normal"):
    session.add(LlmCall(purpose=purpose, model="m", requested_model="m", routing_strategy=None, cost=cost,
                        cost_estimated=estimated, latency_ms=1, ok=True,
                        created_at=at or datetime.now(UTC)))
    session.commit()


# ── 상한 읽기 · 쓴 돈 ───────────────────────────────────────────────


def test_off_by_default(session):
    assert daily_cap.cap(session) == (None, False)
    _spend(session, 1000.0)
    daily_cap.check(session)  # 끔 — 막지 않는다


def test_setting_round_trip_and_clear(session):
    settings_store.set_llm_daily_usd(session, 10.0)
    assert daily_cap.cap(session) == (10.0, False)
    settings_store.set_llm_daily_usd(session, None)
    assert daily_cap.cap(session) == (None, False)


def test_env_wins_over_setting(session, monkeypatch):
    settings_store.set_llm_daily_usd(session, 10.0)
    monkeypatch.setenv(daily_cap.ENV, "3.5")
    assert daily_cap.cap(session) == (3.5, True)


@pytest.mark.parametrize("raw", ["", "abc", "0", "-1", "nan", "inf"])
def test_bad_or_zero_env_is_ignored(session, monkeypatch, raw):
    monkeypatch.setenv(daily_cap.ENV, raw)
    assert daily_cap.cap(session) == (None, False)


def test_under_cap_passes(session):
    settings_store.set_llm_daily_usd(session, 10.0)
    _spend(session, 9.99)
    daily_cap.check(session)


@pytest.mark.parametrize("spent", [10.0, 12.5])
def test_at_or_over_cap_raises_typed_error_with_korean_message(session, spent):
    settings_store.set_llm_daily_usd(session, 10.0)
    _spend(session, spent)
    with pytest.raises(daily_cap.DailyCapReached) as e:
        daily_cap.check(session)
    assert e.value.code == "daily_cap" and e.value.message == MESSAGE_10 and e.value.cap == 10.0


def test_estimated_costs_and_every_recorded_purpose_count(session):
    _spend(session, 0.5, estimated=True)
    _spend(session, 0.25, purpose="embedding")
    _spend(session, 0.02, purpose="srch_agent")
    _spend(session, None)  # 비용 없는 줄(실패 등)은 0
    assert daily_cap.spent_today(session) == pytest.approx(0.77)


def test_today_is_seoul_date_reset_at_midnight(session):
    now = datetime(2026, 11, 25, 0, 30, tzinfo=SEOUL)
    _spend(session, 5.0, at=datetime(2026, 11, 24, 23, 59, 59, tzinfo=SEOUL).astimezone(UTC))  # 어제
    _spend(session, 1.0, at=datetime(2026, 11, 25, 0, 0, 0, tzinfo=SEOUL).astimezone(UTC))  # 오늘 자정
    _spend(session, 7.0, at=datetime(2026, 11, 26, 0, 0, 0, tzinfo=SEOUL).astimezone(UTC))  # 내일
    assert daily_cap.spent_today(session, now) == 1.0
    assert daily_cap.spent_today(session, datetime(2026, 11, 24, 23, 0, tzinfo=SEOUL)) == 5.0
    settings_store.set_llm_daily_usd(session, 5.0)
    daily_cap.check(session, now)  # 어제 5달러는 자정에 0 으로 돌아갔다
    with pytest.raises(daily_cap.DailyCapReached):
        daily_cap.check(session, datetime(2026, 11, 24, 23, 0, tzinfo=SEOUL))


def test_status_for_the_screen(session, monkeypatch):
    _spend(session, 1.5)
    assert daily_cap.status(session) == {"cap_usd": None, "fixed_by_env": False, "spent_today_usd": 1.5}
    monkeypatch.setenv(daily_cap.ENV, "10")
    assert daily_cap.status(session) == {"cap_usd": 10.0, "fixed_by_env": True, "spent_today_usd": 1.5}


# ── 부르기 전에 막는다(보내지 않음 · 기록 없음) ───────────────────


@pytest.fixture
def capped(session, connection):
    settings_store.set_llm_daily_usd(session, 10.0)
    _spend(session, 10.0)
    return session


def _calls(session) -> int:
    session.expire_all()
    return session.query(LlmCall).count()


async def test_chat_is_not_sent_when_capped(capped, llm, liner):
    with pytest.raises(LlmFailed) as e:
        await llm.chat("normal", HI)
    assert (e.value.error.code, e.value.error.message) == ("daily_cap", MESSAGE_10)
    assert liner.requests == [] and _calls(capped) == 1


async def test_chat_still_works_when_cap_is_off(session, llm, liner):
    _spend(session, 1000.0)
    await llm.chat("normal", HI)
    assert len(liner.requests) == 1


async def test_chat_under_cap_is_sent_and_may_overshoot(session, llm, liner):
    settings_store.set_llm_daily_usd(session, 10.0)
    _spend(session, 9.99)
    await llm.chat("normal", HI)  # 0.04 — 한 번은 상한을 조금 넘을 수 있다
    assert daily_cap.spent_today(session) == pytest.approx(10.03)
    with pytest.raises(LlmFailed):
        await llm.chat("normal", HI)
    assert len(liner.requests) == 1


class _Never(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise AssertionError("상한에 닿았으면 보내지 않아야 한다")


async def test_embeddings_search_agent_search_and_visual_are_blocked(capped, monkeypatch):
    monkeypatch.setattr(embeddings, "TRANSPORT", _Never())
    monkeypatch.setattr(search, "TRANSPORT", _Never())
    monkeypatch.setattr(search_agent, "TRANSPORT", _Never())
    monkeypatch.setattr(visualization, "TRANSPORT", _Never())
    with pytest.raises(embeddings.EmbedFailed) as e1:
        await embeddings.embed(capped, ["a"])
    with pytest.raises(search.SearchFailed) as e2:
        await search.liner_search(capped, "q")
    with pytest.raises(search.SearchFailed) as e3:
        await search.liner_knowledge(capped, "q")
    from app.llm import mcp_client
    with pytest.raises(search.SearchFailed) as e4:
        await mcp_client.field_search(capped, "q", "business")
    with pytest.raises(search_agent.SearchAgentFailed) as e5:
        await search_agent.ask(capped, "q")
    with pytest.raises(visualization.VisualFailed) as e6:
        await visualization.liner_visualize(capped, "q")
    for e in (e1, e2, e3, e4, e5):
        assert (e.value.code, e.value.message) == ("daily_cap", MESSAGE_10)
    assert e6.value.code == "daily_cap" and "daily_cap" in visualization._NO_RETRY
    assert _calls(capped) == 1
