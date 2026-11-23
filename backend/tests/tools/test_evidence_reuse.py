"""근거 다시 쓰기(설계 2026-11-23): evidence.search 가 Liner 보다 먼저 저장된 근거를 찾는다.

다시 쓰는 근거 = 같은 mode(web·scholar·legal·business)로 찾았고, 붙은 곳(evidence_links)이 있고, 30일 안이고,
「다시 쓰지 않기」가 아닌 것. Liner 는 부르지 않는다(app.llm.search.TRANSPORT 를 가짜로 바꿔 끼우고 요청 수를 센다).
사람·현장은 모두 가상이다.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.agent import context
from app.llm import search
from app.llm.search import SearchHit
from app.store import chats, evidence_reuse
from app.store import settings as settings_store
from app.store.evidence import WEATHER_MODE, link, record_search, searches_since
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch, ScheduleDraft
from app.tools.registry import ToolResult, call
from tests.llm_doubles import add_connection
from tests.search_doubles import hit, mock, mock_json, route, web_body

SEOUL = ZoneInfo("Asia/Seoul")
QUERY = "철근콘크리트 층당 골조 공기"
SAVED = hit("철근콘크리트 골조 공기 기준", "https://example.com/a", description="층당 골조 8~12일")
HINT = "저장된 근거입니다. 질문에 맞지 않으면 fresh 를 true 로 다시 부르세요."
LIMIT_MESSAGE = "이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."
REUSE_LIMIT_MESSAGE = "이번 요청에서 저장된 근거를 5번 꺼냈습니다. 이미 받은 근거를 쓰세요."


@pytest.fixture
def web(monkeypatch, session):
    """찾으면 근거 한 줄(철근콘크리트 골조 공기 기준)이 오는 가짜 Liner. requests 로 부른 수를 센다."""
    add_connection(session)
    t = mock(200, web_body(SAVED))
    monkeypatch.setattr(search, "TRANSPORT", t)
    return t


@pytest.fixture
def liner_routes(monkeypatch, session):
    """분야 검색(MCP)은 늘 실패(500)하고 웹 검색은 근거 한 줄을 주는 가짜 Liner. (mcp, web)."""
    add_connection(session)
    mcp, web = mock_json(call=500), mock(200, web_body(SAVED))
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    return mcp, web


@pytest.fixture
def ctx_chat(ctx, session):
    chat = chats.create_chat(session, user_id=ctx.user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "5층 사무동 일정을 만들어 줘"})
    session.commit()
    return dataclasses.replace(ctx, chat_session_id=chat.id)


async def _saved(ctx, *, mode: str = "web", linked: bool = True) -> int:
    """가짜 Liner 로 한 번 찾고 첫 근거를 가정에 붙여 둔다(루프처럼 commit). 그 evidence_id."""
    r = await call("evidence.search", {"query": QUERY, "mode": mode}, ctx)
    assert r.ok and r.output["reused"] is False, r.error
    evidence_id = r.output["results"][0]["evidence_id"]
    if linked:
        link(ctx.session, evidence_ids=[evidence_id], draft_id=1, assumption_label="층당 골조 기간")
    ctx.session.commit()
    return evidence_id


def _aged(session, evidence_id: int, days: int) -> datetime:
    at = datetime.now(UTC) - timedelta(days=days)
    session.get(EvidenceItem, evidence_id).created_at = at
    session.commit()
    return at


async def test_related_saved_evidence_is_reused_without_calling_liner(ctx, events, session, web):
    evidence_id = await _saved(ctx)
    r = await call("evidence.search", {"query": "층당 골조 공기 철근콘크리트"}, ctx)
    assert r.ok, r.error
    assert len(web.requests) == 1  # 저장된 근거를 썼다 — Liner 는 처음 한 번만
    today = datetime.now(SEOUL).date().isoformat()
    assert r.output["reused"] is True and r.output["hint"] == HINT
    [item] = r.output["results"]
    assert (item["evidence_id"], item["title"], item["searched_at"], item["age_days"], item["mode"], item["found_by"]) == (
        evidence_id, "철근콘크리트 골조 공기 기준", today, 0, "web", QUERY)
    assert events[-1].data == {
        "kind": "evidence", "search_id": r.output["search_id"], "query": "층당 골조 공기 철근콘크리트", "mode": "web",
        "reused": True, "results": [{"evidence_id": evidence_id, "title": "철근콘크리트 골조 공기 기준",
                                     "url": "https://example.com/a", "hostname": "example.com",
                                     "date": "2026-03-01", "searched_at": today, "mode": "web"}]}
    row = session.get(EvidenceSearch, r.output["search_id"])
    assert (row.mode, row.ok, row.result_count) == ("reuse", True, 1)  # 다시 쓰기 표시가 있는 줄
    assert session.query(EvidenceItem).count() == 1  # 근거를 새로 만들지 않는다


# 맞는 낱말 없음 · 일부만 맞음(낱말은 모두 맞아야 한다) · 낱말 하나뿐
@pytest.mark.parametrize("query", ["타워크레인 임대료 시세", "철근 공급업체 납기", "골조 양생", "골조 공기 타워크레인 임대료 시세",
                                   "철골 층당 골조 공기", "터널 골조 공기", "공기", "골조"])
async def test_unrelated_query_falls_through_to_liner(ctx, session, web, query):
    await _saved(ctx)
    r = await call("evidence.search", {"query": query}, ctx)
    assert r.ok and r.output["reused"] is False and r.output["hint"] is None
    assert len(web.requests) == 2


async def test_a_normal_search_keeps_its_fields_and_says_not_reused(ctx, events, session, web):
    r = await call("evidence.search", {"query": QUERY}, ctx)
    today = datetime.now(SEOUL).date().isoformat()
    assert r.output == {"search_id": 1, "used": 1, "limit": 3, "reused": False, "hint": None, "note": None, "omitted": 0,
                        "descriptions_cut": False, "results": [{
        "evidence_id": 1, "title": "철근콘크리트 골조 공기 기준", "url": "https://example.com/a",
        "hostname": "example.com", "description": "층당 골조 8~12일", "date": "2026-03-01", "authors": [],
        "journal": None, "searched_at": today, "age_days": 0}]}  # mode·found_by 는 다시 쓴 결과에만
    assert list(r.output) == ["search_id", "used", "limit", "reused", "hint", "note", "omitted", "descriptions_cut",
                              "results"]  # 잘려도 앞 칸은 남게
    assert "reused" not in events[-1].data  # 새로 찾은 카드는 그대로


@pytest.mark.parametrize("days,reused", [(29, True), (31, False)])
async def test_only_evidence_found_within_30_days_is_reused(ctx, session, web, days, reused):
    evidence_id = await _saved(ctx)
    at = _aged(session, evidence_id, days)
    r = await call("evidence.search", {"query": QUERY}, ctx)
    assert r.ok and r.output["reused"] is reused
    if reused:
        assert r.output["results"][0]["age_days"] == days
        assert r.output["results"][0]["searched_at"] == at.astimezone(SEOUL).date().isoformat()
    else:
        assert len(web.requests) == 2 and session.get(EvidenceItem, evidence_id) is not None  # 지우지 않는다


async def test_unlinked_evidence_is_not_reused(ctx, session, web):
    await _saved(ctx, linked=False)
    r = await call("evidence.search", {"query": QUERY}, ctx)
    assert r.output["reused"] is False and len(web.requests) == 2


async def test_retired_evidence_is_not_reused_until_restored(ctx, session, web):
    evidence_id = await _saved(ctx)
    assert evidence_reuse.set_retired(session, evidence_id, True)
    session.commit()
    assert (await call("evidence.search", {"query": QUERY}, ctx)).output["reused"] is False
    session.commit()
    assert evidence_reuse.set_retired(session, evidence_id, False)
    session.commit()
    r = await call("evidence.search", {"query": QUERY}, ctx)
    assert r.output["reused"] is True and r.output["results"][0]["evidence_id"] == evidence_id
    assert not evidence_reuse.set_retired(session, 99, True)  # 없는 근거


async def test_fresh_searches_liner_again(ctx, session, web):
    evidence_id = await _saved(ctx)
    r = await call("evidence.search", {"query": QUERY, "fresh": True}, ctx)
    assert r.ok and r.output["reused"] is False and len(web.requests) == 2
    # A7: 새로 찾은 결과가 같은 주소면 새 줄을 넣지 않고 그 근거 번호를 그대로 돌려준다(붙은 곳도 그대로)
    assert session.query(EvidenceItem).count() == 1 and r.output["results"][0]["evidence_id"] == evidence_id


async def test_any_reusable_mode_serves_any_other_and_says_its_own_mode(ctx, events, session, web):
    await _saved(ctx, mode="scholar")
    r = await call("evidence.search", {"query": QUERY, "mode": "legal"}, ctx)
    assert r.output["reused"] is True and len(web.requests) == 1
    assert r.output["results"][0]["mode"] == "scholar"
    assert events[-1].data["mode"] == "legal" and events[-1].data["results"][0]["mode"] == "scholar"


async def test_web_fallback_of_a_failed_legal_search_is_found_by_legal_later(ctx, session, liner_routes):
    mcp, web = liner_routes
    r = await call("evidence.search", {"query": QUERY, "mode": "legal"}, ctx)
    assert r.ok and r.output["note"] == "분야 검색 실패 → 웹 검색"
    link(session, evidence_ids=[r.output["results"][0]["evidence_id"]], draft_id=1, assumption_label="층당 골조 기간")
    session.commit()
    r = await call("evidence.search", {"query": QUERY, "mode": "legal"}, ctx)
    assert r.output["reused"] is True and r.output["results"][0]["mode"] == "web"
    assert len(mcp.bodies("tools/call")) == 1 and len(web.requests) == 1


async def test_weather_and_info_rows_are_never_reused(ctx, session, web):
    found = SearchHit(title=QUERY, url="https://example.com/w", hostname="example.com", description=QUERY, date=None)
    for mode in (WEATHER_MODE, "info"):
        _, [item] = record_search(session, chat_session_id=None, query=QUERY, mode=mode, ok=True, error_code=None,
                                  latency_ms=0, hits=[found])
        link(session, evidence_ids=[item.id], draft_id=1, assumption_label="동절기")
        session.commit()
        assert evidence_reuse.find(session, QUERY, 5) == []
    r = await call("evidence.search", {"query": QUERY}, ctx)
    assert r.output["reused"] is False and len(web.requests) == 1


async def test_reuse_is_outside_the_limit_of_three_and_has_its_own_cap(ctx_chat, session, web):
    await _saved(ctx_chat)
    for used in (2, 3):
        r = await call("evidence.search", {"query": QUERY, "fresh": True}, ctx_chat)
        assert r.ok and r.output["used"] == used
        session.commit()
    for _ in range(5):  # Liner 3번을 다 써도 저장된 근거는 꺼낸다
        r = await call("evidence.search", {"query": QUERY}, ctx_chat)
        assert r.ok and r.output["reused"] is True and r.output["used"] == 3 and r.output["limit"] == 3
        session.commit()
    r = await call("evidence.search", {"query": QUERY}, ctx_chat)
    assert not r.ok and r.error == REUSE_LIMIT_MESSAGE
    r = await call("evidence.search", {"query": QUERY, "fresh": True}, ctx_chat)
    assert not r.ok and r.error == LIMIT_MESSAGE
    assert len(web.requests) == 3
    assert searches_since(session, ctx_chat.chat_session_id, None) == 3  # 다시 쓰기 줄은 검색 수에 들지 않는다


async def test_a_new_user_message_resets_the_reuse_cap(ctx_chat, session, web):
    await _saved(ctx_chat)
    for _ in range(5):
        assert (await call("evidence.search", {"query": QUERY}, ctx_chat)).output["reused"] is True
        session.commit()
    chats.add_message(session, ctx_chat.chat_session_id, "user", {"kind": "text", "text": "다른 것도 봐 줘"})
    session.commit()
    assert (await call("evidence.search", {"query": QUERY}, ctx_chat)).output["reused"] is True


async def test_reused_evidence_keeps_its_id_and_links_without_duplicates(ctx, session, web):
    evidence_id = await _saved(ctx)
    r = await call("evidence.search", {"query": QUERY}, ctx)
    assert r.output["results"][0]["evidence_id"] == evidence_id
    session.commit()
    draft = ScheduleDraft(domain="construction", level="L3", schedule_json={}, report_json={})
    session.add(draft)
    session.commit()
    args = {"draft_id": draft.id, "items": [{"evidence_id": evidence_id, "assumption_label": "골조 공기(새 초안)"}]}
    assert (await call("evidence.attach", args, ctx)).output == {"linked": 1}
    session.commit()
    assert (await call("evidence.attach", args, ctx)).output == {"linked": 0}
    assert session.query(EvidenceItem).count() == 1
    assert session.query(EvidenceLink).filter(EvidenceLink.assumption_label == "골조 공기(새 초안)").count() == 1


async def test_reuse_rows_stay_out_of_usage_and_health_counts(client, admin, ctx, session, web):
    await _saved(ctx)
    for _ in range(2):
        assert (await call("evidence.search", {"query": QUERY}, ctx)).output["reused"] is True
        session.commit()
    assert session.query(EvidenceSearch).count() == 3
    assert client.get("/api/devconsole/usage", headers=admin).json()["searches"] == {"calls": 1, "failed": 0}
    health = client.get("/api/devconsole/health", headers=admin).json()["search"]
    assert (health["calls_7d"], health["failed_7d"]) == (1, 0)


def test_guides_say_when_to_reuse_and_when_to_ask_the_info_apis():
    guide = (context.GUIDES_DIR / "evidence.md").read_text(encoding="utf-8")
    for words in ("evidence__search", "info__weather", "info__call", "공휴일", "특보", "reused", "fresh: true"):
        assert words in guide, words
    info = (context.GUIDES_DIR / "info.md").read_text(encoding="utf-8")
    assert "evidence__search" in info


# 「철근 콘크리트」처럼 띄어 쓰거나 조사가 붙어도 같은 근거를 찾는다
@pytest.mark.parametrize("query", ["철근 콘크리트 골조 공기", "철근콘크리트의 층당 골조 공기"])
async def test_spacing_and_particles_still_reuse(ctx, session, web, query):
    evidence_id = await _saved(ctx)
    r = await call("evidence.search", {"query": query}, ctx)
    assert r.output["reused"] is True and r.output["results"][0]["evidence_id"] == evidence_id


LAW_URL = "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=" + "%EA%B1%B4%EC%B6%95" * 20
LONG = [hit("건축법 시행령 제14조 착공신고 처리 기한 " * 2, f"{LAW_URL}&n={n}", hostname="www.law.go.kr",
            description="가" * 300) for n in range(5)]


@pytest.mark.parametrize("reuse", [False, True])
async def test_long_results_fit_the_tool_result_limit(ctx, session, monkeypatch, reuse):
    add_connection(session)
    monkeypatch.setattr(search, "TRANSPORT", mock(200, web_body(*LONG)))
    query = "건축법 착공신고 처리 기한"
    r = await call("evidence.search", {"query": query}, ctx)
    if reuse:
        link(session, evidence_ids=[x["evidence_id"] for x in r.output["results"]], draft_id=1, assumption_label="a")
        session.commit()
        r = await call("evidence.search", {"query": query}, ctx)
    assert r.output["reused"] is reuse
    text = context.result_text(ToolResult(ok=True, output=r.output, error=None, ms=0))
    assert len(text) < context.RESULT_LIMIT - 200 and not text.endswith(context.CUT_NOTE)
    assert len(r.output["results"]) == 5 and all(x["url"].startswith(LAW_URL) for x in r.output["results"])
    assert (r.output["descriptions_cut"], r.output["omitted"]) == (True, 0)  # 줄였다고 알린다
    assert session.get(EvidenceSearch, r.output["search_id"]).result_count == 5


async def test_the_size_budget_follows_the_tool_output_limit_setting(ctx, session, monkeypatch):
    add_connection(session)
    monkeypatch.setattr(search, "TRANSPORT", mock(200, web_body(*LONG)))
    query = "건축법 착공신고 처리 기한"
    r = await call("evidence.search", {"query": query}, ctx)
    link(session, evidence_ids=[x["evidence_id"] for x in r.output["results"]], draft_id=1, assumption_label="a")
    settings_store.set_agent_config(session, {"tool_output_limit": 2000})
    session.commit()
    r = await call("evidence.search", {"query": query}, ctx)
    text = context.result_text(ToolResult(ok=True, output=r.output, error=None, ms=0), limit=2000)
    assert r.output["reused"] is True and not text.endswith(context.CUT_NOTE)
    assert r.output["omitted"] == 5 - len(r.output["results"]) > 0
    assert session.get(EvidenceSearch, r.output["search_id"]).result_count == len(r.output["results"])  # 돌려준 수


def test_results_that_cannot_fit_even_without_descriptions_drop_from_the_end():
    from app.tools.data import search_evidence as tool

    huge = tool.HitOut(evidence_id=1, title="가" * 300, url="https://example.com/" + "a" * 980, hostname="example.com",
                       description="나" * 300, date=None, authors=[], journal=None, searched_at="2026-11-20",
                       age_days=3, mode="web", found_by="다" * 300)
    out = tool._fit(tool.SearchOut(search_id=1, used=0, limit=3, reused=True, hint=HINT,
                                   results=[huge.model_copy(update={"evidence_id": n}) for n in range(5)]))
    assert tool._size(out) <= tool.RESULT_BUDGET and [r.evidence_id for r in out.results] == [0]  # 한 줄이 약 1,950자
    assert out.results[0].url == huge.url and out.reused is True
    assert (out.omitted, out.descriptions_cut) == (4, True)
