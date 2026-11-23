"""근거 API(GET /api/evidence)와 조건 API 의 출처(evidence). 근거는 도구로 찾고 붙인다(가짜 Liner)."""

import dataclasses

import pytest
from sqlalchemy import select

from app.harness.conditions import Condition
from app.llm import search
from app.store import chats
from app.store.tables import EvidenceItem, ScheduleDraft, User
from app.tools.context import ToolContext
from app.tools.registry import call
from tests.llm_doubles import add_connection
from tests.schedules import sample, store
from tests.search_doubles import hit, mock, web_body

FINISH_BY = Condition("in.finish_by", "input", "finish_by", {"date": "2027-12-31"}, "준공 2027.12.31 이전", "프롬프트")
CRANE = Condition("in.crane", "input", "resource_cap", {"resource_id": "crane", "capacity": 1}, "타워크레인 1대", "프롬프트")


@pytest.fixture
def sid(session) -> int:
    return store(session, sample(), conditions=[FINISH_BY.to_dict(), CRANE.to_dict()])


@pytest.fixture
def events() -> list:
    return []


@pytest.fixture
def ctx_sid(client, session, sid, events, monkeypatch) -> ToolContext:
    """관리자·일정 sid 의 도구 문맥. Liner 연결과 가짜 검색(근거 두 줄)이 있다."""
    add_connection(session)
    monkeypatch.setattr(search, "TRANSPORT", mock(200, web_body(hit(), hit("양생 기준", "https://example.com/b"))))
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    return ToolContext(session=session, user=admin, schedule_id=sid, emit=events.append)


async def _search(ctx: ToolContext, query: str = "골조 공기") -> list[int]:
    r = await call("evidence.search", {"query": query}, ctx)
    assert r.ok, r.error
    ctx.session.commit()  # 루프가 도구 뒤에 commit 한다
    return [x["evidence_id"] for x in r.output["results"]]


async def _attach(ctx: ToolContext, **args) -> None:
    r = await call("evidence.attach", args, ctx)
    assert r.ok, r.error
    ctx.session.commit()


def _conditions(client, headers, sid) -> dict[str, dict]:
    j = client.get(f"/api/schedules/{sid}/conditions", headers=headers).json()
    return {c["id"]: c for layer in j["layers"].values() for c in layer}


def test_evidence_list_needs_exactly_one_filter(client, admin):
    assert client.get("/api/evidence", headers=admin).status_code == 422
    r = client.get("/api/evidence?schedule_id=1&chat_session_id=1", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert r.json()["message"] == "schedule_id 와 chat_session_id 가운데 하나만 주세요."


def test_evidence_needs_login(client):
    assert client.get("/api/evidence?schedule_id=1").status_code == 401


async def test_attach_and_condition_links(client, admin, ctx_sid, sid):
    ids = await _search(ctx_sid)
    await _attach(ctx_sid, schedule_id=sid, items=[{"evidence_id": ids[0], "condition_id": "in.finish_by"}])
    rows = _conditions(client, admin, sid)
    assert rows["in.finish_by"]["evidence"][0]["url"] == "https://example.com/a"
    assert rows["in.finish_by"]["evidence"] == [{"id": ids[0], "title": "골조 공기 기준", "url": "https://example.com/a"}]
    assert rows["in.crane"]["evidence"] == [] and rows["base.no_cycle"]["evidence"] == []


async def test_preview_conditions_keep_their_sources(client, admin, ctx_sid, sid):
    ids = await _search(ctx_sid)
    await _attach(ctx_sid, schedule_id=sid, items=[{"evidence_id": ids[1], "condition_id": "in.crane"}])
    body = {"base_version": 1, "changes": [{"id": "in.crane", "params": {"capacity": 2}}]}
    j = client.post(f"/api/schedules/{sid}/conditions/preview", json=body, headers=admin).json()
    crane = next(c for c in j["conditions"]["layers"]["input"] if c["id"] == "in.crane")
    assert crane["evidence"] == [{"id": ids[1], "title": "양생 기준", "url": "https://example.com/b"}]


async def test_schedule_list_includes_the_draft_it_was_made_from(client, admin, ctx_sid, session, sid):
    ids = await _search(ctx_sid, "철근콘크리트 층당 골조 공기")
    used = ScheduleDraft(domain="construction", level="L3", schedule_json={}, report_json={}, schedule_id=sid)
    other = ScheduleDraft(domain="construction", level="L3", schedule_json={}, report_json={})
    session.add_all([used, other])
    session.commit()
    await _attach(ctx_sid, draft_id=used.id, items=[
        {"evidence_id": ids[0], "assumption_label": "층당 골조 기간"}, {"evidence_id": ids[1], "condition_id": "in.crane"}])
    await _attach(ctx_sid, draft_id=other.id, items=[{"evidence_id": ids[1], "assumption_label": "다른 초안"}])
    r = client.get(f"/api/evidence?schedule_id={sid}", headers=admin)
    assert r.status_code == 200
    assert r.json() == [
        {"id": ids[0], "title": "골조 공기 기준", "url": "https://example.com/a", "hostname": "example.com",
         "description": "층당 8~12일", "date": "2026-03-01", "mode": "web", "query": "철근콘크리트 층당 골조 공기",
         "links": [{"condition_id": None, "assumption_label": "층당 골조 기간"}]},
        {"id": ids[1], "title": "양생 기준", "url": "https://example.com/b", "hostname": "example.com",
         "description": "층당 8~12일", "date": "2026-03-01", "mode": "web", "query": "철근콘크리트 층당 골조 공기",
         "links": [{"condition_id": "in.crane", "assumption_label": None}]},
    ]
    # 초안의 조건 링크도 그 초안으로 만든 일정의 조건 화면에 보인다
    assert _conditions(client, admin, sid)["in.crane"]["evidence"][0]["id"] == ids[1]


async def test_chat_list_is_only_for_its_owner(client, admin, user, ctx_sid, session):
    chat = chats.create_chat(session, user_id=ctx_sid.user.id)
    ids = await _search(dataclasses.replace(ctx_sid, chat_session_id=chat.id))
    await _search(ctx_sid, "대화 밖")  # 다른 대화(없음)의 검색은 빠진다
    j = client.get(f"/api/evidence?chat_session_id={chat.id}", headers=admin).json()
    assert [(x["id"], x["query"], x["links"]) for x in j] == [(ids[0], "골조 공기", []), (ids[1], "골조 공기", [])]
    r = client.get(f"/api/evidence?chat_session_id={chat.id}", headers=user)
    assert r.status_code == 404 and r.json()["message"] == "대화를 찾을 수 없습니다."


def test_unknown_schedule_or_chat_is_404(client, admin):
    r = client.get("/api/evidence?schedule_id=99", headers=admin)
    assert r.status_code == 404 and r.json()["message"] == "일정을 찾을 수 없습니다."
    assert client.get("/api/evidence?chat_session_id=99", headers=admin).status_code == 404


# ── 다시 쓰지 않기(설계 2026-11-23): POST /api/evidence/{id}/retire · /restore ─────────────


async def test_retire_and_restore(client, user, ctx_sid, session, sid):
    ids = await _search(ctx_sid)
    await _attach(ctx_sid, schedule_id=sid, items=[{"evidence_id": ids[0], "condition_id": "in.finish_by"}])
    r = client.post(f"/api/evidence/{ids[0]}/retire", headers=user)  # 로그인한 누구나
    assert r.status_code == 200 and r.json() == {"id": ids[0], "retired": True}
    session.expire_all()
    assert session.get(EvidenceItem, ids[0]).retired is True
    # 이미 붙은 곳에는 그대로 보인다
    assert [x["id"] for x in client.get(f"/api/evidence?schedule_id={sid}", headers=user).json()] == [ids[0]]
    assert _conditions(client, user, sid)["in.finish_by"]["evidence"][0]["id"] == ids[0]
    r = client.post(f"/api/evidence/{ids[0]}/restore", headers=user)
    assert r.status_code == 200 and r.json() == {"id": ids[0], "retired": False}
    session.expire_all()
    assert session.get(EvidenceItem, ids[0]).retired is False


@pytest.mark.parametrize("action", ["retire", "restore"])
def test_retire_unknown_evidence_is_404(client, admin, action):
    r = client.post(f"/api/evidence/99/{action}", headers=admin)
    assert r.status_code == 404 and r.json()["message"] == "근거를 찾을 수 없습니다."


@pytest.mark.parametrize("action", ["retire", "restore"])
def test_retire_needs_login(client, action):
    assert client.post(f"/api/evidence/1/{action}").status_code == 401
