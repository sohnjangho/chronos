"""서버 끝에서 끝까지(묶음 2): 지연 → 영향 → 만회안 → 승인 → 공정률·개발 콘솔·생산 간트.

씨앗 `python -m app.seed demo`(사무동·공장 두 일정)와 앱 안 가짜 LLM(`app.llm.fake`, CHRONOS_FAKE_LLM=1)의
묶음 2 대본으로 돈다 — 화면 시험 `frontend/e2e/bundle2.spec.ts` 와 같은 대본이다.

로그인 → 대화 "지상 골조가 비 때문에 3일 늦어졌어"(ui: 스케줄·사무동·A1210 고름) → schedule.find → delay.record
→ delay_impact 카드·지연 기록 1건(열림, 준공 영향 > 0) → 대화 "만회 계획 만들어 줘" → shorten.make
→ shorten_options 카드(도달한 안 ≥ 1, 위반 0) → 추천 복사본 submit → 승인 → 새 버전·지연 reflected·복사본 applied
→ 공정률 준공 차이 → 개발 콘솔 두 턴(첫 턴 도구 칸 ≥ 2) → 공장 일정은 자원 묶음 간트.

PM 규칙: 지연을 기록해도 버전·Plan·지금 준공은 그대로다(지연 기록의 with_open 이 늦어진 준공). 만회안 승인처럼
계획을 바꾸는 승인은 Plan 을 그 승인 때의 예측으로 고정한다(Task 16e). 그래서 만회의 뜻은
"승인 뒤 지금 준공 ≤ 지연 전 Plan 준공 < 지연을 넣은 준공(with_open)" 이고, 승인 직후 준공 차이는 0 이다.
"""

import json

import pytest

from app.llm import fake
from app.seed import FACTORY, OFFICE, seed_demo
from tests.llm_doubles import add_connection

DELAY_TEXT = "지상 골조가 비 때문에 3일 늦어졌어"
RECOVERY_TEXT = "만회 계획 만들어 줘"
FRAME = "A1210"  # 1층 철근 배근 — 지상 골조의 첫 작업(자원 맞춘 일정에서 3일 늦으면 준공도 늦는다)


@pytest.fixture
def demo(session, monkeypatch) -> dict[str, int]:
    """씨앗 두 일정 + 가짜 LLM(앱의 기본 transport) + 기본 연결 한 줄."""
    monkeypatch.setenv(fake.ENV, "1")
    add_connection(session)
    office, factory = seed_demo(session)
    return {"office": office, "factory": factory}


def _events(body: str) -> list[tuple[str, dict]]:
    """SSE 본문 → [(event, data)]. ping 주석은 건너뛴다."""
    out = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        event, data = block.split("\n")
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def _ok(r, status: int = 200) -> dict | list:
    assert r.status_code == status, r.text
    return r.json()


def _login(client) -> dict[str, str]:
    token = _ok(client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"}))["token"]
    return {"Authorization": f"Bearer {token}"}


def _say(client, h, chat_id: int, text: str, ui: dict) -> list[tuple[str, dict]]:
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": text, "ui": ui}, headers=h)
    assert r.status_code == 200, r.text
    events = _events(r.text)
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "error"], events
    return events


def _card(events, kind: str) -> dict:
    return next(d for name, d in events if name == "card" and d.get("kind") == kind)


def _windows(events) -> list[dict]:
    return [d for name, d in events if name == "open_window"]


def _record_delay(client, h, sid: int, chat_id: int) -> dict:
    ui = {"program": "schedule-table", "schedule_id": sid, "selected_activity": FRAME}
    events = _say(client, h, chat_id, DELAY_TEXT, ui)
    card = _card(events, "delay_impact")
    assert (card["schedule_id"], card["activity_id"], card["days"], card["status"]) == (sid, FRAME, 3, "open")
    assert card["impact"]["finish_delta"] > 0  # 준공 영향(코드 계산)
    assert {"program": "delays", "params": {"id": str(sid), "event": str(card["event_id"])}} in _windows(events)
    return card


def _make_recovery(client, h, sid: int, chat_id: int) -> dict:
    events = _say(client, h, chat_id, RECOVERY_TEXT, {"program": "delays", "schedule_id": sid})
    card = _card(events, "shorten_options")
    reached = [o for o in card["options"] if o["reached"]]
    assert reached and all(o["violations"] == 0 for o in card["options"])
    best = next(o for o in card["options"] if o["recommended"])
    assert best["scenario_id"] == card["recommended_scenario_id"] and best["reached"]
    assert card["base"].startswith("s:")  # 열린 지연을 넣은 지연 반영안이 기준
    opened = [w for w in _windows(events) if w["program"] == "compare"]
    assert opened and opened[0]["params"]["other"] == f"s:{best['scenario_id']}"
    return best


def _approve_recovery(client, h, sid: int, scenario_id: int) -> None:
    sent = _ok(client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={}, headers=h))
    assert (sent["applied"], sent["status"]) == (False, "submitted")  # 일정 변경은 승인함에서 기다린다
    decided = _ok(client.post(f"/api/approvals/{sent['approval_id']}/decide",
                              json={"decision": "approve", "note": ""}, headers=h))
    assert decided["status"] == "approved"


def _check_devconsole(client, h) -> None:
    turns = _ok(client.get("/api/devconsole/turns", headers=h))
    assert len(turns) == 2 and all(t["status"] == "done" for t in turns)
    first = min(turns, key=lambda t: t["turn_id"])
    assert first["request"].startswith(DELAY_TEXT[:20])
    nodes = {n["key"]: n for n in _ok(client.get(f"/api/devconsole/turns/{first['turn_id']}", headers=h))["structure"]["nodes"]}
    assert nodes["tool"]["count"] >= 2  # schedule.find → delay.record
    tools = [step["tool"] for step in nodes["tool"]["detail"]["in"]]
    assert tools == ["schedule.find", "delay.record"]


def test_delay_to_recovery_to_approval_then_progress_devconsole_and_factory_gantt(client, demo):
    h = _login(client)
    sid = demo["office"]
    schedules = {s["name"]: s["id"] for s in _ok(client.get("/api/schedules", headers=h))}
    assert schedules == {OFFICE: sid, FACTORY: demo["factory"]}
    before_version = _ok(client.get(f"/api/schedules/{sid}", headers=h))["version"]
    chat_id = _ok(client.post("/api/chat/sessions", json={}, headers=h))["id"]

    card = _record_delay(client, h, sid, chat_id)
    delays_before = _ok(client.get(f"/api/schedules/{sid}/delays", headers=h))
    assert [(e["id"], e["status"]) for e in delays_before["events"]] == [(card["event_id"], "open")]
    late = delays_before["finish"]
    assert late["with_open"] > late["current"] > late["plan"]  # 지연을 넣으면 준공이 더 늦어진다(기록은 일정을 안 바꿈)
    assert _ok(client.get(f"/api/schedules/{sid}", headers=h))["version"] == before_version
    progress_before = _ok(client.get(f"/api/schedules/{sid}/progress", headers=h))
    assert progress_before["cpm"]["finish_variance"]["current"] == late["current"]

    best = _make_recovery(client, h, sid, chat_id)
    _approve_recovery(client, h, sid, best["scenario_id"])

    event = _ok(client.get(f"/api/schedules/{sid}/delays", headers=h))["events"][0]
    scenario = _ok(client.get(f"/api/schedules/{sid}/scenarios/{best['scenario_id']}", headers=h))
    versions = _ok(client.get(f"/api/schedules/{sid}/versions", headers=h))
    assert event["status"] == "reflected" and scenario["status"] == "applied" and versions[0]["n"] == before_version + 1
    progress_after = _ok(client.get(f"/api/schedules/{sid}/progress", headers=h))
    after = progress_after["cpm"]["finish_variance"]
    assert after["current"] == best["finish"]  # 승인한 안의 준공이 지금 준공
    # 끝 단언(지시서의 `after.days <= before.days`): 승인은 Plan 을 그때의 예측으로 고정하므로 승인 직후 차이는 0
    # (씨앗 기준 8일 → 0일). 만회 자체는 준공 날짜로 본다.
    assert after["days"] == 0 and after["plan"] == after["current"]
    before = progress_before["cpm"]["finish_variance"]
    assert after["current"] <= before["plan"] < late["with_open"]  # 만회: 지연을 넣은 준공에서 지연 전 Plan 준공까지 당겼다
    assert after["plan"] < before["plan"]  # 계획 변경 승인은 Plan 도 옮긴다(지연 기록은 안 옮김)

    _check_devconsole(client, h)
    factory = _ok(client.get(f"/api/schedules/{demo['factory']}", headers=h))
    assert factory["display"]["gantt_group_by"] == "resource"
