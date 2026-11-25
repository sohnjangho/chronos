"""개발 콘솔 — 관리 포인트(계획 5 Task 7): 설정(관리자만, 범위는 서버가 검사)·실행 추적 단계·사용량 수.

바깥 호출은 없다 — 근거 표·llm_calls·point_cards·point_quotes 줄을 손으로 만든다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.points import card, quotes
from app.store import settings as settings_store
from app.store.settings import points_config, sources_for
from app.store.tables import EvidenceSearch, LlmCall, Setting
from tests.programs.test_devconsole_api import T0, ctx_ev, end_ev, made_turn

URL = "/api/devconsole/points-config"
ALL = {"weather", "materials", "fx", "business"}


def get_cfg(client, admin) -> dict:
    r = client.get(URL, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def saved(session) -> dict[str, str]:
    session.expire_all()
    return {r.key: r.value for r in session.scalars(select(Setting))}


# ── 설정 ────────────────────────────────────────────────────────────


def test_defaults_and_rows(client, admin):
    body = get_cfg(client, admin)
    assert (body["points_tf_days"], body["points_window_weeks"], body["points_max_new"],
            body["points_forecast_reuse_hours"], body["accel_warn_ratio"]) == (3, 3, 5, 6, 0.5)
    assert set(body["points_sources"]["construction"]) == ALL
    assert set(body["points_sources"]["manufacturing"]) == {"materials", "fx", "business"}
    assert body["points_sources"]["_other"] == ["business"]
    assert body["points_sources"]["rnd"] == ["materials", "fx", "business", "regulation"]  # 11-25 기본값
    assert [d["id"] for d in body["domains"]] == ["construction", "manufacturing", "rnd", "_other"]
    assert [d["label"] for d in body["domains"]][-1] == "그 밖의 분야"
    assert body["bounds"]["points_tf_days"] == [0, 10] and body["bounds"]["accel_warn_ratio"] == [0.1, 1.0]


def test_save_roundtrip_reaches_the_engine_settings(client, admin, session):
    patch = {"points_tf_days": 5, "points_window_weeks": 4, "points_max_new": 2, "points_forecast_reuse_hours": 12,
             "accel_warn_ratio": 0.7,
             "points_sources": {"construction": ["weather", "fx"], "manufacturing": [], "_other": ["materials"]}}
    r = client.put(URL, headers=admin, json=patch)
    assert r.status_code == 200, r.text
    assert r.json()["points_tf_days"] == 5 and r.json()["points_sources"]["_other"] == ["materials"]
    session.expire_all()
    cfg = points_config(session)
    assert (cfg.tf_days, cfg.window_weeks, cfg.max_new, cfg.forecast_reuse_hours) == (5, 4, 2, 12)
    assert settings_store.accel_warn_ratio(session) == 0.7
    assert sources_for(session, "construction") == {"weather", "fx"}
    assert sources_for(session, "manufacturing") == set()
    assert sources_for(session, "software") == {"materials"}  # 그 밖의 분야
    assert get_cfg(client, admin)["accel_warn_ratio"] == 0.7


def test_partial_save_keeps_other_values(client, admin, session):
    assert client.put(URL, headers=admin, json={"points_window_weeks": 6}).status_code == 200
    body = get_cfg(client, admin)
    assert body["points_window_weeks"] == 6 and body["points_tf_days"] == 3
    assert set(body["points_sources"]["construction"]) == ALL


def test_saved_domain_outside_the_packs_gets_its_own_row(client, admin):
    client.put(URL, headers=admin, json={"points_sources": {"software": ["fx"]}})
    body = get_cfg(client, admin)
    assert [d["id"] for d in body["domains"]] == ["construction", "manufacturing", "rnd", "software", "_other"]
    assert body["points_sources"]["software"] == ["fx"]


@pytest.mark.parametrize("patch", [
    {"points_tf_days": -1}, {"points_tf_days": 11}, {"points_window_weeks": 0}, {"points_window_weeks": 9},
    {"points_max_new": 0}, {"points_max_new": 11}, {"points_forecast_reuse_hours": 0},
    {"points_forecast_reuse_hours": 49}, {"accel_warn_ratio": 0.05}, {"accel_warn_ratio": 1.5},
    {"points_tf_days": 2.5}, {"points_sources": {"construction": ["rain"]}},
    {"points_sources": {"": ["fx"]}}, {"points_sources": {"a b": ["fx"]}}, {"unknown": 1},
])
def test_out_of_bounds_is_rejected_and_nothing_is_saved(client, admin, session, patch):
    before = saved(session)
    good = {"points_max_new": 4} if "points_window_weeks" in patch else {"points_window_weeks": 5}
    r = client.put(URL, headers=admin, json={**good, **patch})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")
    assert saved(session) == before  # 함께 보낸 바른 값도 적지 않는다


def test_setter_checks_bounds_itself(session):
    before = saved(session)
    with pytest.raises(ValueError):
        settings_store.set_points_config(session, {"tf_days": 11})
    with pytest.raises(ValueError):
        settings_store.set_points_config(session, {"accel_warn_ratio": 0})
    with pytest.raises(ValueError):
        settings_store.set_points_config(session, {"tf_days": 4, "sources": {"construction": ["rain"]}})
    assert saved(session) == before


def test_admin_only(client, user, admin):
    for r in (client.get(URL, headers=user), client.put(URL, headers=user, json={"points_tf_days": 4}),
              client.get("/api/devconsole/points-runs", headers=user)):
        assert (r.status_code, r.json()["code"]) == (403, "admin_only")
    assert client.get(URL).status_code == 401
    assert get_cfg(client, admin)["points_tf_days"] == 3


# ── 사용량 수 ─────────────────────────────────────────────────────────


def test_usage_counts_premium_data_mcp_and_search_agent(client, admin, session):
    old = (datetime.now(UTC) - timedelta(days=20)).replace(tzinfo=None)
    session.add_all([
        EvidenceSearch(query="copper price", mode="knowledge", ok=True),
        EvidenceSearch(query="USD KRW exchange rate", mode="knowledge", ok=False),
        EvidenceSearch(query="copper price", mode="knowledge", ok=True, created_at=old),
        EvidenceSearch(query="business: 알루미늄 커튼월 공급 동향", mode="knowledge", ok=True),
        EvidenceSearch(query="web q", mode="web", ok=True),
    ])
    common = {"requested_model": "m", "latency_ms": 5, "input_tokens": 0, "output_tokens": 0}
    session.add_all([LlmCall(purpose="srch_agent", model="liner-search-agent", ok=True, **common),
                     LlmCall(purpose="srch_agent", model="liner-search-agent", ok=False, **common)])
    session.commit()
    c = client.get("/api/devconsole/usage", headers=admin).json()["counters"]
    assert c["knowledge"] == {"calls": 2, "failed": 1}
    assert c["mcp"] == {"calls": 1, "failed": 0}
    assert c["search_agent"] == {"calls": 2, "failed": 1}
    assert c["searches"] == {"calls": 1, "failed": 0}  # Liner 근거 검색은 그대로


# ── 실행 추적 「관리 포인트」 단계 ───────────────────────────────────────


def _point(aid: str, tf: int = 0) -> dict:
    return {"activity_id": aid, "name": f"작업 {aid}", "critical": tf == 0, "tf": tf, "es": "2027-03-03",
            "ef": "2027-03-05"}


def _risk(aid: str, kind: str, status: str = "ok") -> dict:
    return {"activity_id": aid, "kind": kind, "line": f"{kind} 줄", "evidence_id": None, "as_of": None,
            "source": None, "status": status, "why": ""}


def made_card(session, sid: int, *, changed: datetime, done: datetime | None, version: int = 2,
              what_if: bool = False) -> card.PointCard:
    points = [_point("A1"), _point("A2", 2), _point("A3", 1)]
    data = {"basis": {"tf_days": 3, "window_weeks": 3}, "new": [{**points[0], "became_critical": False}],
            "more": 1, "tightened": [{**points[1], "before_tf": 3}],
            "removed": [{"activity_id": "A9", "name": "작업 A9", "reason": "relief"}],
            "diff": {"added": [points[0]], "removed": ["A9"], "tightened": [["A2", 3, 2]], "became_critical": [],
                     "before_tf": {}},
            "trigger": card.version_trigger(version)}
    risks = [_risk("A1", "materials"), _risk("A1", "business"), _risk("A1", "weather", "skipped")]
    row = card.PointCard(schedule_id=sid, version=version, what_if=what_if, data_json=data, points_json=points,
                         risk_status=card.DONE if done else card.LOOKING, risks_json=risks if done else [],
                         generation=1, changed_at=changed, updated_at=done or changed, shown_generation=0)
    session.add(row)
    session.commit()
    return row


def add_quote(session, row: card.PointCard, kind: str, status: str) -> None:
    question = card.quote_question(row.points_json[0], kind, row.risks_json)
    session.add(quotes.PointQuote(schedule_id=row.schedule_id, version=row.version, activity_id="A1",
                                  kind=card.quote_kind(kind, question, what_if=row.what_if), status=status,
                                  quotes_json=[], updated_at=datetime.now(UTC)))
    session.commit()


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_turn_shows_the_points_stage_with_branch_counts_and_cost_kinds(client, admin, session, sid):
    row = made_card(session, sid, changed=at(1), done=at(6))
    session.add_all([
        EvidenceSearch(query="copper price", mode="knowledge", ok=True, created_at=at(4)),
        EvidenceSearch(query="USD KRW exchange rate", mode="knowledge", ok=False, created_at=at(4)),
        EvidenceSearch(query="business: 구리 커튼월 공급 동향", mode="knowledge", ok=True, created_at=at(5)),
        EvidenceSearch(query="관리 포인트 기후 서울 3월(지난 10년)", mode="weather", ok=True, created_at=at(5)),
        EvidenceSearch(query="copper price", mode="knowledge", ok=True, created_at=at(9)),  # 찾기가 끝난 뒤
        EvidenceSearch(query="서울 날씨", mode="weather", ok=True, created_at=at(5)),  # info.weather(대화 도구)
        EvidenceSearch(query="copper price", mode="knowledge", ok=True, created_at=at(5), chat_session_id=99),
    ])
    session.commit()
    add_quote(session, row, "materials", "ready")
    add_quote(session, row, "business", "failed")
    _, turn_id = made_turn(session, events=[ctx_ev(), end_ev(3)])
    body = client.get(f"/api/devconsole/turns/{turn_id}", headers=admin).json()
    [stage] = body["points"]
    assert (stage["schedule_id"], stage["version"], stage["what_if"]) == (sid, 2, False)
    assert stage["schedule_name"]
    assert stage["compute"] == {"points": 3, "new": 2, "tightened": 1, "removed": 1}
    assert stage["risk_status"] == "done"
    searches = {s["branch"]: s for s in stage["searches"]}
    assert (searches["knowledge"]["calls"], searches["knowledge"]["failed"]) == (2, 1)
    assert searches["business"]["calls"] == 1 and searches["weather"]["calls"] == 1
    assert searches["knowledge"]["cost_kind"] == "Search + Premium Data" and searches["knowledge"]["per_1k"] == 2
    assert searches["business"]["cost_kind"] == "MCP" and searches["business"]["per_1k"] == 2
    assert searches["weather"]["per_1k"] is None  # 기상청 — Liner 비용 아님
    agent = stage["search_agent"]
    assert (agent["calls"], agent["failed"], agent["pending"], agent["per_1k"]) == (2, 1, 0, 20)
    assert stage["skipped"] == 1
    assert stage["cost"] == pytest.approx(3 * 0.002 + 2 * 0.02)


def test_turn_without_a_change_in_its_window_has_no_points_stage(client, admin, session, sid):
    made_card(session, sid, changed=at(30), done=at(35))
    _, turn_id = made_turn(session, events=[ctx_ev(), end_ev(3)])
    assert client.get(f"/api/devconsole/turns/{turn_id}", headers=admin).json()["points"] == []


def test_points_runs_lists_version_changes_newest_first(client, admin, session, sid):
    made_card(session, sid, changed=at(1), done=at(2), version=2)
    made_card(session, sid, changed=at(10), done=None, version=3)
    made_card(session, sid, changed=at(20), done=at(21), version=3, what_if=True)
    runs = client.get("/api/devconsole/points-runs", headers=admin).json()
    assert [(r["version"], r["what_if"]) for r in runs] == [(3, True), (3, False), (2, False)]
    assert runs[1]["risk_status"] == "looking" and runs[1]["trigger"] == {"kind": "version", "from": 2, "to": 3}
    assert len(client.get("/api/devconsole/points-runs?limit=1", headers=admin).json()) == 1
