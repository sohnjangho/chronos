"""근거 도구: evidence.search(검색·보관·카드·요청당 3번·실패 안내) · evidence.attach · generate.run 의 evidence_ids.

Liner 는 부르지 않는다(app.llm.search.TRANSPORT 를 가짜로 바꿔 끼운다). 사람·현장은 모두 가상이다.
"""

import dataclasses
import json
import logging

import pytest

import app.tools.generate as generate_tools
from app.agent import context
from app.domains.loader import load
from app.llm import search
from app.llm.client import LlmClient
from app.store import chats
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch, ScheduleDraft
from app.tools.registry import call, list_tools
from tests import schedules
from tests.gen_doubles import SCHED_OK, START_FACT, WBS_OK, script
from tests.llm_doubles import KEY, FakeLiner, add_connection
from tests.search_doubles import hit, mock, mock_json, route, web_body

LIMIT_MESSAGE = "이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."
FALLBACK = ("근거 없이 분야 기본값을 쓰고 '근거 검색 실패'라고 적으세요. 분야 기본값이 없는 항목은 값을 지어내지 말고 "
            "사용자에게 묻거나 '확인 필요'로 남기세요. 지어낸 값을 분야 기본값이라고 적지 마세요.")


@pytest.fixture
def liner_conn(session):
    return add_connection(session)


@pytest.fixture
def web(monkeypatch, liner_conn):
    """찾으면 근거 한 줄(골조 공기 기준)이 오는 가짜 Liner."""
    t = mock(200, web_body())
    monkeypatch.setattr(search, "TRANSPORT", t)
    return t


@pytest.fixture
def chat_id(session, ctx) -> int:
    chat = chats.create_chat(session, user_id=ctx.user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "5층 사무동 일정을 만들어 줘"})
    session.commit()
    return chat.id


@pytest.fixture
def ctx_chat(ctx, chat_id):
    return dataclasses.replace(ctx, chat_session_id=chat_id)


def test_tools_are_registered():
    specs = {t.name: t for t in list_tools()}
    for name in ("evidence.search", "evidence.attach"):
        assert specs[name].mutates and specs[name].program is None
    assert "evidence__attach" in specs["evidence.search"].description


async def test_key_never_logged_or_returned(session, liner_conn, caplog, ctx, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(search, "TRANSPORT", mock(401, {}))
    r = await call("evidence.search", {"query": "q"}, ctx)
    assert not r.ok and r.error == f"API 키가 맞지 않습니다. {FALLBACK}"
    assert KEY not in caplog.text and KEY not in json.dumps(dataclasses.asdict(r), ensure_ascii=False)
    assert KEY not in str(session.query(EvidenceSearch).one().__dict__)


async def test_tool_records_and_emits_card(ctx, events, session, web):
    r = await call("evidence.search", {"query": "철근콘크리트 층당 골조 공기"}, ctx)
    assert r.ok, r.error
    assert r.output["results"][0]["evidence_id"] == 1 and events[-1].data["kind"] == "evidence"
    assert session.query(EvidenceItem).count() == 1
    # 다시 쓰기 칸(reused·hint·searched_at·age_days·mode·found_by)은 test_evidence_reuse 가 본다. 있던 칸은 그대로다.
    out = {k: v for k, v in r.output.items() if k not in ("reused", "hint", "omitted", "descriptions_cut")}
    new = ("searched_at", "age_days", "mode", "found_by")
    out["results"] = [{k: v for k, v in x.items() if k not in new} for x in out["results"]]
    assert out == {"search_id": 1, "used": 1, "limit": 3, "results": [{
        "evidence_id": 1, "title": "골조 공기 기준", "url": "https://example.com/a", "hostname": "example.com",
        "description": "층당 8~12일", "date": "2026-03-01", "authors": [], "journal": None}], "note": None}
    assert events[-1].type == "card" and events[-1].data == {
        "kind": "evidence", "search_id": 1, "query": "철근콘크리트 층당 골조 공기", "mode": "web",
        "results": [{"evidence_id": 1, "title": "골조 공기 기준", "url": "https://example.com/a",
                     "hostname": "example.com", "date": "2026-03-01"}]}
    row = session.get(EvidenceSearch, 1)
    assert (row.query, row.mode, row.ok, row.error_code, row.result_count, row.chat_session_id) == (
        "철근콘크리트 층당 골조 공기", "web", True, None, 1, None)
    item = session.get(EvidenceItem, 1)
    assert (item.search_id, item.published, item.extra_json) == (1, "2026-03-01", {})


async def test_scholar_results_keep_authors_and_journal(ctx, session, liner_conn, monkeypatch):
    paper = hit("골조 공기 연구", "https://journal.example.org/p/1", authors=["김하늘", "이바다"],
                journal="가상 건설학회지", citationCount=12, description="가" * 500)
    monkeypatch.setattr(search, "TRANSPORT", mock(200, web_body(paper)))
    r = await call("evidence.search", {"query": "골조 공기", "mode": "scholar", "max_results": 2}, ctx)
    assert r.ok, r.error
    out = r.output["results"][0]
    assert out["authors"] == ["김하늘", "이바다"] and out["journal"] == "가상 건설학회지"
    assert out["description"] == "가" * 300  # 에이전트에게는 300자까지
    item = session.get(EvidenceItem, out["evidence_id"])
    assert item.description == "가" * 500 and item.extra_json == {
        "authors": ["김하늘", "이바다"], "journal": "가상 건설학회지", "citation_count": 12}
    assert json.loads(search.TRANSPORT.last.content) == {"query": "골조 공기", "max_results": 2}


async def test_three_searches_per_request(ctx_chat, session, web):
    used = []
    for _ in range(3):
        r = await call("evidence.search", {"query": "층당 골조 기간"}, ctx_chat)
        assert r.ok, r.error
        used.append(r.output["used"])
    assert used == [1, 2, 3]
    r = await call("evidence.search", {"query": "층당 골조 기간"}, ctx_chat)
    assert not r.ok and r.error == LIMIT_MESSAGE
    assert len(web.requests) == 3 and session.query(EvidenceSearch).count() == 3  # 넷째는 부르지도 남기지도 않는다


async def test_a_new_user_message_starts_a_new_count(ctx_chat, session, web, chat_id):
    for _ in range(3):
        assert (await call("evidence.search", {"query": "q"}, ctx_chat)).ok
    session.commit()  # 루프가 도구 뒤에 commit 한다
    chats.add_message(session, chat_id, "user", {"kind": "text", "text": "다시 해 줘"})
    session.commit()
    r = await call("evidence.search", {"query": "q"}, ctx_chat)
    assert r.ok and r.output["used"] == 1


async def test_failures_count_toward_the_limit(ctx_chat, session, liner_conn, monkeypatch):
    t = mock(402, {})
    monkeypatch.setattr(search, "TRANSPORT", t)
    for _ in range(3):
        r = await call("evidence.search", {"query": "q"}, ctx_chat)
        assert not r.ok and r.error.startswith("Liner 크레딧이 부족합니다.")
        session.rollback()  # 루프는 실패한 도구의 쓰기를 되돌린다
    r = await call("evidence.search", {"query": "q"}, ctx_chat)
    assert r.error == LIMIT_MESSAGE and len(t.requests) == 3


async def test_failure_tells_the_agent_to_fall_back(ctx, events, session, liner_conn, monkeypatch):
    monkeypatch.setattr(search, "TRANSPORT", mock(402, {}))
    r = await call("evidence.search", {"query": "층당 골조 기간"}, ctx)
    assert r.error.endswith("지어낸 값을 분야 기본값이라고 적지 마세요.") and "'확인 필요'" in r.error
    assert r.error == f"Liner 크레딧이 부족합니다. {FALLBACK}"
    row = session.query(EvidenceSearch).one()
    assert (row.ok, row.error_code, row.result_count, row.query) == (False, "no_credit", 0, "층당 골조 기간")
    assert events == [] and session.query(EvidenceItem).count() == 0


async def test_the_failure_row_survives_the_loop_rollback(ctx_chat, session, liner_conn, monkeypatch, chat_id):
    monkeypatch.setattr(search, "TRANSPORT", mock(429, {}))
    await call("evidence.search", {"query": "q"}, ctx_chat)
    session.rollback()
    row = session.query(EvidenceSearch).one()
    assert (row.ok, row.error_code, row.chat_session_id) == (False, "rate_limited", chat_id)


async def test_without_a_liner_connection_the_agent_falls_back(ctx, session):
    r = await call("evidence.search", {"query": "q"}, ctx)
    assert r.error == f"근거 검색에는 Liner 연결이 필요합니다. 설정에서 연결해 주세요. {FALLBACK}"
    assert (session.query(EvidenceSearch).one().error_code) == "not_ready"


@pytest.mark.parametrize("args", [
    {"query": ""}, {"query": "가" * 301}, {"query": "q", "mode": "news"}, {"query": "q", "max_results": 6},
    {"query": "q", "max_results": 0}, {"query": "q", "lang": "ko"},
])
async def test_search_input_limits(ctx, web, args):
    r = await call("evidence.search", args, ctx)
    assert not r.ok and r.error.startswith("입력 형식 오류") and web.requests == []


# ── evidence.attach ──────────────────────────────────────────────


@pytest.fixture
def found(ctx, session, liner_conn, monkeypatch) -> list[int]:
    """근거 두 줄을 찾아 둔다(evidence_id 1, 2)."""
    monkeypatch.setattr(search, "TRANSPORT", mock(200, web_body(hit(), hit("양생 기준", "https://example.com/b"))))

    async def run():
        r = await call("evidence.search", {"query": "골조"}, ctx)
        session.commit()
        return [x["evidence_id"] for x in r.output["results"]]

    return run


@pytest.fixture
def sid(session) -> int:
    return schedules.store(session, schedules.sample())


def _links(session) -> list[tuple]:
    rows = session.query(EvidenceLink).order_by(EvidenceLink.id)
    return [(x.evidence_id, x.schedule_id, x.draft_id, x.condition_id, x.assumption_label) for x in rows]


async def test_attach_to_a_schedule_and_a_draft(ctx, session, found, sid):
    ids = await found()
    draft = ScheduleDraft(domain="construction", level="L3", schedule_json={}, report_json={})
    session.add(draft)
    session.commit()
    r = await call("evidence.attach", {"schedule_id": sid, "items": [
        {"evidence_id": ids[0], "condition_id": "in.finish_by"}, {"evidence_id": ids[1], "assumption_label": "양생"}]}, ctx)
    assert r.ok and r.output == {"linked": 2}
    r = await call("evidence.attach", {"draft_id": draft.id, "items": [
        {"evidence_id": ids[0], "assumption_label": "층당 골조 기간"}]}, ctx)
    assert r.ok and r.output == {"linked": 1}
    assert _links(session) == [
        (1, sid, None, "in.finish_by", None), (2, sid, None, None, "양생"), (1, None, draft.id, None, "층당 골조 기간")]


async def test_attaching_the_same_link_again_adds_nothing(ctx, session, found, sid):
    ids = await found()
    args = {"schedule_id": sid, "items": [{"evidence_id": ids[0], "condition_id": "in.finish_by"}]}
    assert (await call("evidence.attach", args, ctx)).output == {"linked": 1}
    session.commit()
    assert (await call("evidence.attach", args, ctx)).output == {"linked": 0}
    assert len(_links(session)) == 1


@pytest.mark.parametrize("target", [{}, {"schedule_id": 1, "draft_id": 1}, {"schedule_id": None, "draft_id": None}])
async def test_attach_needs_exactly_one_target(ctx, session, found, target):
    ids = await found()
    r = await call("evidence.attach", {**target, "items": [{"evidence_id": ids[0], "condition_id": "in.x"}]}, ctx)
    assert not r.ok and r.error == "schedule_id 와 draft_id 가운데 하나만 주세요." and _links(session) == []


@pytest.mark.parametrize("item", [{}, {"condition_id": "in.x", "assumption_label": "양생"}])
async def test_each_item_backs_a_condition_or_an_assumption(ctx, session, found, sid, item):
    ids = await found()
    r = await call("evidence.attach", {"schedule_id": sid, "items": [{"evidence_id": ids[0], **item}]}, ctx)
    assert not r.ok and r.error == "항목마다 condition_id 와 assumption_label 가운데 하나만 주세요."


async def test_attach_unknown_evidence(ctx, session, found, sid):
    ids = await found()
    r = await call("evidence.attach", {"schedule_id": sid, "items": [
        {"evidence_id": ids[0], "condition_id": "in.a"}, {"evidence_id": 7, "condition_id": "in.b"}]}, ctx)
    assert not r.ok and r.error == "없는 근거입니다: 7" and _links(session) == []


async def test_attach_unknown_schedule_or_draft(ctx, session, found):
    ids = await found()
    items = [{"evidence_id": ids[0], "condition_id": "in.a"}]
    r = await call("evidence.attach", {"schedule_id": 99, "items": items}, ctx)
    assert r.error == "일정을 찾을 수 없습니다."
    r = await call("evidence.attach", {"draft_id": 98, "items": items}, ctx)
    assert r.error == "없는 초안입니다: 98"


@pytest.mark.parametrize("items", [[], [{"evidence_id": 1, "condition_id": "in.a"}] * 11])
async def test_attach_item_count(ctx, items, sid):
    r = await call("evidence.attach", {"schedule_id": sid, "items": items}, ctx)
    assert not r.ok and r.error.startswith("입력 형식 오류")


# ── generate.run 의 evidence_ids ─────────────────────────────────


async def test_generation_keeps_evidence_ids(ctx, session, events, liner_conn, monkeypatch):
    liner = FakeLiner()
    monkeypatch.setattr(generate_tools, "client_for", lambda c: LlmClient(c.session, transport=liner.transport))
    script(liner, WBS_OK, SCHED_OK)
    assumption = {"label": "층당 골조 기간", "value": "10일", "source": "근거 검색", "evidence_ids": [3]}
    r = await call("generate.run", {"domain": "construction", "level": "L3", "request": "5층 사무동",
                                    "facts": [START_FACT], "assumptions": [assumption]}, ctx)
    assert r.ok, r.error
    draft = session.get(ScheduleDraft, r.output["draft_id"])
    assert draft.assumptions_json[0]["evidence_ids"] == [3]
    assert r.output["assumptions"] == [assumption]
    card = next(e.data for e in events if e.type == "card" and e.data["kind"] == "generation_result")
    assert card["assumptions"] == [assumption]


async def test_facts_and_assumptions_without_evidence_still_work(ctx, session, liner_conn, monkeypatch):
    liner = FakeLiner()
    monkeypatch.setattr(generate_tools, "client_for", lambda c: LlmClient(c.session, transport=liner.transport))
    script(liner, WBS_OK, SCHED_OK)
    r = await call("generate.run", {"domain": "construction", "level": "L3", "request": "5층 사무동",
                                    "facts": [START_FACT], "assumptions": [{"label": "주 근무일", "value": "6일", "source": "가정"}]}, ctx)
    assert r.ok and r.output["assumptions"] == [{"label": "주 근무일", "value": "6일", "source": "가정", "evidence_ids": []}]


# ── 분야 검색(Task 27b): mode legal·business → Liner MCP ─────────────

FIELD_FALLBACK = "분야 검색 실패 → 웹 검색"


async def test_evidence_legal_mode_records_and_cards(ctx, events, session, liner_conn, monkeypatch):
    t = mock_json([hit("착공신고 처리 기한", "https://law.example/1", hostname="law.example")])
    monkeypatch.setattr(search, "TRANSPORT", t)
    r = await call("evidence.search", {"query": "건축물 착공신고 처리 기한", "mode": "legal"}, ctx)
    assert r.ok, r.error
    assert t.bodies("tools/call")[0]["params"] == {
        "name": "search_legal", "arguments": {"query": "건축물 착공신고 처리 기한", "limit": 5}}
    row = session.query(EvidenceSearch).one()
    assert (row.mode, row.ok, row.result_count, row.error_code) == ("legal", True, 1, None)
    assert session.query(EvidenceItem).one().url == "https://law.example/1"
    assert r.output["used"] == 1 and r.output["note"] is None
    assert r.output["results"][0]["title"] == "착공신고 처리 기한"
    assert events[-1].data == {"kind": "evidence", "search_id": 1, "query": "건축물 착공신고 처리 기한",
                               "mode": "legal", "results": [{"evidence_id": 1, "title": "착공신고 처리 기한",
                                                             "url": "https://law.example/1",
                                                             "hostname": "law.example", "date": "2026-03-01"}]}


async def test_business_mode_asks_search_business(ctx, events, session, liner_conn, monkeypatch):
    t = mock_json()
    monkeypatch.setattr(search, "TRANSPORT", t)
    r = await call("evidence.search", {"query": "철근 공급업체 납기", "mode": "business", "max_results": 2}, ctx)
    assert r.ok and events[-1].data["mode"] == "business"
    assert t.bodies("tools/call")[0]["params"]["name"] == "search_business"
    assert t.bodies("tools/call")[0]["params"]["arguments"]["limit"] == 2
    assert session.query(EvidenceSearch).one().mode == "business"


async def test_legal_failure_falls_back_to_web_once_and_counts(ctx_chat, events, session, liner_conn, monkeypatch):
    mcp, web = mock_json(call=500), mock(200, web_body())
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    r = await call("evidence.search", {"query": "착공신고 처리 기한", "mode": "legal"}, ctx_chat)
    assert r.ok, r.error
    assert len(mcp.bodies("tools/call")) == 1 and len(web.requests) == 1
    assert json.loads(web.last.content)["query"] == "착공신고 처리 기한"
    assert r.output["used"] == 2 and r.output["note"] == FIELD_FALLBACK
    assert events[-1].data["mode"] == "web" and events[-1].data["note"] == FIELD_FALLBACK
    session.commit()  # 루프가 성공한 도구의 쓰기를 commit 한다
    rows = [(s.mode, s.ok, s.error_code) for s in session.query(EvidenceSearch).order_by(EvidenceSearch.id)]
    assert rows == [("legal", False, "server_error"), ("web", True, None)]
    r = await call("evidence.search", {"query": "q"}, ctx_chat)
    assert r.ok and r.output["used"] == 3  # web·scholar 와 합산
    session.commit()
    r = await call("evidence.search", {"query": "q", "mode": "legal"}, ctx_chat)
    assert r.error == LIMIT_MESSAGE and len(mcp.bodies("tools/call")) == 1


async def test_no_fallback_when_the_limit_is_reached(ctx_chat, session, liner_conn, monkeypatch):
    mcp, web = mock_json(call=500), mock(200, web_body())
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    for _ in range(2):
        assert (await call("evidence.search", {"query": "q"}, ctx_chat)).ok
        session.commit()
    r = await call("evidence.search", {"query": "q", "mode": "legal"}, ctx_chat)
    assert r.error == f"검색 서버에 문제가 생겼습니다. {FALLBACK}"
    assert len(web.requests) == 2  # 셋째(분야 검색)가 한도의 끝이라 웹으로 다시 하지 않는다


async def test_fallback_web_failure_is_also_recorded(ctx, events, session, liner_conn, monkeypatch):
    mcp, web = mock_json(call=429), mock(402, {})
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    r = await call("evidence.search", {"query": "q", "mode": "business"}, ctx)
    assert r.error == f"{FIELD_FALLBACK}도 실패: Liner 크레딧이 부족합니다. {FALLBACK}"
    session.rollback()
    rows = [(s.mode, s.ok, s.error_code) for s in session.query(EvidenceSearch).order_by(EvidenceSearch.id)]
    assert rows == [("business", False, "rate_limited"), ("web", False, "no_credit")] and events == []


@pytest.mark.parametrize("status,message", [(401, "API 키가 맞지 않습니다."), (403, "API 키가 맞지 않습니다."),
                                            (402, "Liner 크레딧이 부족합니다.")])
async def test_account_errors_do_not_fall_back(ctx, events, session, liner_conn, monkeypatch, status, message):
    mcp, web = mock_json(call=status), mock(200, web_body())
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    r = await call("evidence.search", {"query": "q", "mode": "legal"}, ctx)
    assert r.error == f"{message} {FALLBACK}" and web.requests == [] and events == []
    assert [s.mode for s in session.query(EvidenceSearch)] == ["legal"]


async def test_field_search_without_a_connection_does_not_fall_back(ctx, session):
    r = await call("evidence.search", {"query": "q", "mode": "legal"}, ctx)
    assert r.error == f"근거 검색에는 Liner 연결이 필요합니다. 설정에서 연결해 주세요. {FALLBACK}"
    assert [(s.mode, s.error_code) for s in session.query(EvidenceSearch)] == [("legal", "not_ready")]


async def test_field_search_key_is_not_logged_or_returned(session, liner_conn, caplog, ctx, monkeypatch):
    caplog.set_level(logging.DEBUG)
    mcp, web = mock_json(init_status=401), mock(401, {})
    monkeypatch.setattr(search, "TRANSPORT", route(mcp, web))
    r = await call("evidence.search", {"query": "q", "mode": "legal"}, ctx)
    assert not r.ok and mcp.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert r.error == f"API 키가 맞지 않습니다. {FALLBACK}" and web.requests == []  # 같은 계정이라 대체하지 않는다
    assert KEY not in caplog.text and KEY not in json.dumps(dataclasses.asdict(r), ensure_ascii=False)
    assert all(KEY not in str(s.__dict__) for s in session.query(EvidenceSearch))


def test_guide_says_which_mode_to_use():
    text = (context.GUIDES_DIR / "evidence.md").read_text(encoding="utf-8")
    for words in ("인허가", "법정 기간", "작업 금지", "안전 규정", "legal", "공급업체", "리드타임", "business",
                  "scholar", "web", FIELD_FALLBACK, "'확인 필요'", "지어낸 값을 \"분야 기본값\"이라고 적지 않는다",
                  "hostname", "law.go.kr", "국가법령정보센터", "관보", "블로그", "참고로만"):
        assert words in text, words


def test_domain_packs_point_to_the_field_search():
    construction = {a.key: a for a in load("construction").assumption_defaults}
    assert "legal" in construction["legal_periods"].note and "인허가" in construction["legal_periods"].label
    assert "찾지 못하면 기간을 정하지 말고 사용자에게 묻거나 '확인 필요'로 남긴다(기본값 없음)." in (
        construction["legal_periods"].note)
    assert "근거 검색(legal)" in load("construction").prompt()
    assert "근거 검색(business)" in load("manufacturing").prompt()
