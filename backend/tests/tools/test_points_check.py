"""points.check(계획 5 Task 5): 지금 포인트·마지막 차이·바깥 위험·근거 문장 상태, 바뀌었으면 카드. 날짜·여유는 저장한 엔진 값."""

from dataclasses import replace
from datetime import date

from app.agent import context
from app.core.model import Relation
from app.points import card, quotes, risk
from app.points.risk import Risk
from app.store import delays as delays_store
from app.store import points as points_store
from app.store.versions import save_new_version
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task


def _base():
    return make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])


def _c(od: int):
    return replace(_base(), activities=tuple(replace(a, od=od) if a.id == "C" else a for a in _base().activities))


def _save(session, sid, schedule, base: int) -> int:
    return save_new_version(session, sid, schedule, [], by_kind="user", by_name="손장호", note="고침", changes=[],
                            base_version=base, plan_change=False)


def test_spec_is_read_only_and_registered():
    spec = {t.name: t for t in list_tools()}["points.check"]
    assert spec.mutates is False and spec.program is None and "what_if" in spec.description


def test_system_prompt_asks_to_check_points_after_changes():
    prompt = context.system_prompt()
    assert "변동을 반영한 뒤에는 관리 포인트를 확인하고, 바뀌었으면 카드를 낸다" in prompt
    assert "points__check" in prompt


async def test_first_version_gives_points_without_card(ctx, session, events):
    sid = store(session, _base())
    r = await call("points.check", {}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    assert r.output["diff"] is None and r.output["card"] is False and events == []
    assert [p["activity_id"] for p in r.output["points"]] == ["A", "B"]


async def test_changed_points_emit_the_card_with_engine_values(ctx, session, events, monkeypatch):
    sid = store(session, _base())
    n = _save(session, sid, _c(4), 1)

    async def look(s, schedule_id, version, points):
        return [Risk("C", "materials", "구리 3개월 +2.0% · The World Bank · 2026-10", 1, "2026-10", "The World Bank",
                     "ok", "")]

    monkeypatch.setattr(risk, "look", look)
    await card.look_now(sid, n, False)
    quotes._save((sid, n, "C", "materials"), "failed", [], "timeout")
    r = await call("points.check", {}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    out = r.output
    stored = points_store.get(session, sid, n)
    assert out["points"] == [{"activity_id": p.activity_id, "name": p.name, "critical": p.critical, "tf": p.tf,
                              "es": p.es.isoformat(), "ef": p.ef.isoformat()} for p in stored]
    assert out["diff"]["added"][0]["activity_id"] == "C" and out["diff"]["before_tf"] == {"C": 4}
    assert out["card"] is True and out["risk_status"] == "done"
    assert out["quotes"] == {"C/materials": {"status": "failed", "message": "근거 문장을 찾지 못했습니다",
                                             "error_code": "timeout", "quotes": []}}
    (event,) = events
    assert event.type == "card" and event.data["kind"] == "points_changed" and event.data["version"] == n
    assert event.data["new"][0]["risks"][0]["quote"]["status"] == "failed"


async def test_unchanged_version_gives_no_card(ctx, session, events):
    sid = store(session, _base())
    _save(session, sid, _base(), 1)
    r = await call("points.check", {}, replace(ctx, schedule_id=sid))
    assert r.ok and r.output["card"] is False and events == []
    assert r.output["note"] == "관리 포인트는 바뀌지 않았습니다(카드 없음)."


async def test_what_if_after_a_delay_emits_a_what_if_card_and_launches(ctx, session, events):
    sid = store(session, make([task("A", 3), task("B", 2), task("C", 3)], [Relation("A", "B")]))  # C 여유 2
    delays_store.create(session, schedule_id=sid, activity_id="C", start_date=date(2027, 3, 1), days=3, cause="자재 늦음",
                        responsibility="undecided", daily_cost=None, evidence="", source="user", created_by="손장호")
    session.commit()
    r = await call("points.check", {"what_if": True}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    assert r.output["what_if"] is True and r.output["risk_status"] == "looking"
    assert card.launched == [(sid, 1, True)]
    (event,) = events
    assert event.data["what_if"] is True and event.data["risk_message"] == "바깥 위험 찾는 중"
    assert [(p["activity_id"], p["became_critical"], p["tf"]) for p in event.data["new"]] == [("C", True, 0)]
    again = await call("points.check", {"what_if": True}, replace(ctx, schedule_id=sid))
    assert again.ok and card.launched == [(sid, 1, True)]  # 같은 가정 — 다시 찾지 않는다


async def test_needs_a_schedule(ctx):
    r = await call("points.check", {}, ctx)
    assert r.ok is False
