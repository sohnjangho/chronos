"""비용 어림: 제공자가 usage.cost 를 주지 않으면(라우터 응답 등) 가격표로 어림해 기록하고 '추정' 표시를 남긴다."""

import httpx
import pytest

from app.llm.client import LlmFailed
from app.llm.connections import estimate_cost
from app.store.llm_usage import usage_since
from app.store.tables import LlmCall
from tests.llm_doubles import chat_body

HI = [{"role": "user", "content": "hi"}]


# ── 어림 계산 ───────────────────────────────────────────────────────


def test_served_model_price_is_used():
    # claude-sonnet-5.5: 입력 $2 · 출력 $10 / 1M 토큰
    assert estimate_cost("claude-sonnet-5.5", "liner-claude-router", 1_000_000, 100_000) == pytest.approx(3.0)


def test_router_with_unknown_served_model_is_none():
    assert estimate_cost("liner-claude-router", "liner-claude-router", 1000, 100) is None
    assert estimate_cost("모르는-모델", "liner-claude-router", 1000, 100) is None


def test_requested_direct_model_is_the_fallback():
    # 답한 모델 이름을 모를 때 요청한 모델이 단일 모델이면 그 가격(liner-mark → liner-mark-1.3: $1 · $5)
    assert estimate_cost("모르는-모델", "liner-mark", 1_000_000, 0) == pytest.approx(1.0)


def test_cached_input_tokens_use_the_cached_price():
    # claude-sonnet-5.5 캐시 입력 $0.10: 600K 보통 × $2 + 400K 캐시 × $0.10
    assert estimate_cost("claude-sonnet-5.5", "liner-claude-router", 1_000_000, 0, 400_000) == pytest.approx(1.24)


# ── 기록 ────────────────────────────────────────────────────────────


async def test_router_reply_without_cost_is_recorded_as_estimate(llm, session, liner):
    liner.push(chat_body("답", model="claude-sonnet-5.5", prompt_tokens=1000, completion_tokens=200, cost=None))
    r = await llm.chat("light", HI)  # liner-claude-router · cost
    assert r.usage.cost is None  # 제공자 값은 그대로(없음)
    row = session.query(LlmCall).one()
    assert row.cost == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1e6) and row.cost_estimated is True


async def test_cached_tokens_from_the_reply_are_priced_as_cached(llm, session, liner):
    body = chat_body("답", model="claude-sonnet-5.5", prompt_tokens=1000, completion_tokens=0, cost=None)
    body["usage"]["prompt_tokens_details"] = {"cached_tokens": 400}
    liner.push(body)
    await llm.chat("light", HI)
    assert session.query(LlmCall).one().cost == pytest.approx((600 * 2.0 + 400 * 0.10) / 1e6)


async def test_router_reply_with_unknown_model_keeps_null_cost(llm, session, liner):
    body = chat_body("답", cost=None)
    del body["model"]  # 답한 모델을 모른다 → 요청한 라우터뿐
    liner.push(body)
    await llm.chat("light", HI)
    row = session.query(LlmCall).one()
    assert row.cost is None and row.cost_estimated is False


async def test_provider_cost_wins_and_is_not_marked(llm, session, liner):
    liner.push(chat_body("답", model="claude-sonnet-5.5", prompt_tokens=1000, completion_tokens=200, cost=0.5))
    await llm.chat("light", HI)
    row = session.query(LlmCall).one()
    assert row.cost == 0.5 and row.cost_estimated is False


async def test_failed_call_has_no_estimate(llm, session, liner):
    liner.push(httpx.Response(500))
    with pytest.raises(LlmFailed):
        await llm.chat("light", HI)
    row = session.query(LlmCall).one()
    assert row.cost is None and row.cost_estimated is False


async def test_turn_usage_outside_devconsole_sums_only_reported_costs(llm, session, liner):
    # 대화·실행 기록의 비용(usage_since)은 알려 준 값만 — 어림은 개발 콘솔에서만 「추정」 표시와 함께 보인다
    liner.push(chat_body("a", model="claude-sonnet-5.5", cost=None), chat_body("b", cost=0.25))
    await llm.chat("light", HI, chat_session_id=7)
    await llm.chat("light", HI, chat_session_id=7)
    assert usage_since(session, 7, 0).cost == 0.25
