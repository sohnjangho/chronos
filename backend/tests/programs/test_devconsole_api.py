"""개발 콘솔 API: 턴 목록·구조·추적 시간표·사용량, 관리자만."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.tools.generate as generate_tools
from app.agent import loop, turns
from app.agent.trace import CONTEXT_PARTS
from app.llm.client import LlmClient
from app.store import chats
from app.store.settings import set_approval_mode
from app.store.tables import (
    ChatMessage,
    EvidenceSearch,
    LlmCall,
    TraceEvent,
    User,
    WorkflowRun,
    WorkflowStep,
)
from tests.gen_doubles import SCHED_OK, START_FACT, WBS_OK, script
from tests.llm_doubles import FakeLiner, add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

SEOUL = ZoneInfo("Asia/Seoul")
T0 = datetime(2027, 3, 1, 9, 0, 0)  # 손으로 만든 턴의 시작(UTC, 시간대 없이 저장)
NODE_KEYS = ["request", "context", "skill", "plan", "judge", "tool", "check", "approval", "respond"]


@pytest.fixture
def scripted(session, monkeypatch) -> ScriptedLlm:
    """루프가 쓰는 LLM 을 대본 가짜로 바꾼다(기본 연결 하나)."""
    add_connection(session)
    llm = ScriptedLlm()
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    return llm


def say(client, headers, chat_id: int, text: str, ui: dict | None = None) -> None:
    """대화 API 로 턴 하나를 끝까지 돌린다."""
    body = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": text, "ui": ui or {}}, headers=headers)
    assert body.status_code == 200 and "event: done" in body.text


def turn_ids(session, chat_id: int) -> list[int]:
    session.expire_all()
    query = select(ChatMessage.id).where(ChatMessage.session_id == chat_id, ChatMessage.role == "user")
    return list(session.scalars(query.order_by(ChatMessage.id)))


@pytest.fixture
def chat_id(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


@pytest.fixture
def finished_turn(client, admin, scripted, chat_id, sid, session) -> int:
    """schedule.read 한 번 뒤 답한 턴."""
    scripted.push(calls("schedule.read", {}), reply("두 개입니다"))
    say(client, admin, chat_id, "몇 개야?", {"program": "schedule", "schedule_id": sid})
    return turn_ids(session, chat_id)[-1]


def get_turn(client, admin, turn_id: int) -> dict:
    r = client.get(f"/api/devconsole/turns/{turn_id}", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def nodes(body: dict) -> dict[str, dict]:
    return {x["key"]: x for x in body["structure"]["nodes"]}


def _admin_id(session) -> int:
    return session.scalars(select(User).where(User.login_id == "admin")).one().id


def made_turn(session, *, text: str = "요청", events: list[dict], steps: list[dict] = (), owner: int | None = None,
              run_status: str = "running") -> tuple[int, int]:
    """손으로 만든 턴: (대화 id, 턴 id). events 는 TraceEvent 칸(seq 는 차례대로), steps 는 WorkflowStep 칸."""
    chat = chats.create_chat(session, user_id=owner or _admin_id(session))
    message = chats.add_message(session, chat.id, "user", {"kind": "text", "text": text})
    session.flush()
    run_id = None
    if steps:
        run = WorkflowRun(chat_session_id=chat.id, title=text, request=text, status=run_status, started_at=T0)
        session.add(run)
        session.flush()
        run_id = run.id
        for n, step in enumerate(steps, 1):
            session.add(WorkflowStep(run_id=run_id, n=n, **{"status": "done", "ms": 10, **step}))
    for seq, ev in enumerate(events, 1):
        session.add(TraceEvent(chat_session_id=chat.id, turn_id=message.id, run_id=run_id, seq=seq, **ev))
    session.commit()
    return chat.id, message.id


def ctx_ev(**kw) -> dict:
    parts = [{"name": n, "chars": 100} for n in CONTEXT_PARTS]
    body = json.dumps({"parts": parts, "history_count": 1, "tool_count": 9}, ensure_ascii=False)
    return {"kind": "context", "label": "컨텍스트 조립", "started_at": T0, "ms": 5, "input_text": body, **kw}


def llm_ev(at: float, ms: int | None = 500, calls_: list[str] = (), **kw) -> dict:
    out = json.dumps({"text": "", "tool_calls": [{"id": f"c{i}", "name": n, "arguments": "{}"}
                                                  for i, n in enumerate(calls_)]}, ensure_ascii=False)
    return {"kind": "llm", "label": "normal", "started_at": T0 + timedelta(seconds=at), "ms": ms, "model": "m",
            "input_tokens": 100, "output_tokens": 10, "input_text": "[]", "output_text": out if ms else "", **kw}


def end_ev(at: float, status: str = "done") -> dict:
    return {"kind": "end", "label": status, "started_at": T0 + timedelta(seconds=at), "ms": int(at * 1000),
            "ok": status == "done", "output_text": "끝"}


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_admin_only(client, user):
    assert client.get("/api/devconsole/turns", headers=user).json()["code"] == "admin_only"


@pytest.mark.parametrize("path", ["/api/devconsole/turns", "/api/devconsole/turns/1", "/api/devconsole/usage"])
def test_every_route_is_admin_only(client, user, path):
    r = client.get(path, headers=user)
    assert (r.status_code, r.json()["code"]) == (403, "admin_only")
    assert client.get(path).status_code == 401


def test_turn_structure(client, admin, finished_turn):
    s = get_turn(client, admin, finished_turn)["structure"]
    n = {x["key"]: x for x in s["nodes"]}
    assert [x["key"] for x in s["nodes"]] == NODE_KEYS
    assert (n["skill"]["state"], n["plan"]["state"], n["judge"]["count"], n["tool"]["count"], n["check"]["state"],
            n["respond"]["state"]) == ("skipped", "past", 1, 1, "todo", "past")
    assert (s["loop_count"], s["limit"]) == (2, 12)


def test_running_turn_marks_now(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["harness.check"])],
                           steps=[{"tool": "harness.check", "status": "running", "ms": None}])
    held = turns.claim(chat)
    try:
        body = get_turn(client, admin, turn)
    finally:
        turns.release(chat, held)
    n = nodes(body)
    assert (n["check"]["state"], n["judge"]["state"], n["respond"]["state"]) == ("now", "todo", "todo")
    assert (n["plan"]["state"], n["tool"]["state"]) == ("past", "todo") and body["turn"]["status"] == "running"


def test_context_parts(client, admin, finished_turn):
    parts = nodes(get_turn(client, admin, finished_turn))["context"]["detail"]["in"]["parts"]
    assert [p["name"] for p in parts] == list(CONTEXT_PARTS)


def add_calls(session, rows, *, chat_session_id=None, at=None) -> None:
    for model, input_tokens, output_tokens, cost, ok in rows:
        session.add(LlmCall(chat_session_id=chat_session_id, purpose="normal", model=model, requested_model=model,
                            input_tokens=input_tokens, output_tokens=output_tokens, cost=cost, latency_ms=10, ok=ok,
                            **({"created_at": at} if at else {})))
    session.commit()


def test_usage_by_model(client, admin, session):
    add_calls(session, [("claude-sonnet-5.5", 100, 20, None, True), ("claude-sonnet-5.5", 50, 10, None, True),
                        ("liner-mark-1.3", 30, 5, None, False)])
    u = client.get("/api/devconsole/usage?group=model", headers=admin).json()
    assert u["rows"] == [
        {"key": "claude-sonnet-5.5", "calls": 2, "input_tokens": 150, "output_tokens": 30, "cost": None, "failed": 0},
        {"key": "liner-mark-1.3", "calls": 1, "input_tokens": 30, "output_tokens": 5, "cost": None, "failed": 1},
    ]
    assert u["cost_known"] is False
    assert u["totals"] == {"calls": 3, "input_tokens": 180, "output_tokens": 35, "cost": None, "failed": 1}


def test_usage_by_user_labels_calls_outside_chat(client, admin, session):
    chat = chats.create_chat(session, user_id=_admin_id(session))
    add_calls(session, [("m", 1, 1, None, True)], chat_session_id=chat.id)
    add_calls(session, [("m", 2, 2, None, True), ("m", 3, 3, None, True)])
    rows = client.get("/api/devconsole/usage?group=user", headers=admin).json()["rows"]
    assert [(r["key"], r["calls"]) for r in rows] == [("대화 밖", 2), ("관리자", 1)]


# ── 턴 목록 ─────────────────────────────────────────────────────────


def test_turn_list_row(client, admin, finished_turn, chat_id):
    rows = client.get("/api/devconsole/turns", headers=admin).json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"turn_id", "chat_session_id", "user_name", "request", "started_at", "status", "llm_calls",
                        "tool_calls", "tokens", "cost", "ms"}
    assert (row["turn_id"], row["chat_session_id"], row["user_name"], row["request"], row["status"]) == (
        finished_turn, chat_id, "관리자", "몇 개야?", "done")
    # 가짜 답마다 12/5 토큰, 비용 0.04
    assert (row["llm_calls"], row["tool_calls"], row["tokens"]) == (2, 1, 34)
    assert row["cost"] == pytest.approx(0.08) and row["ms"] >= 0 and row["started_at"].endswith("Z")


def test_turns_are_newest_first_with_a_limit_and_a_short_request(client, admin, scripted, chat_id, session):
    scripted.push(reply("하나"), reply("둘"))
    say(client, admin, chat_id, "첫째")
    say(client, admin, chat_id, "가" * 80)
    first, second = turn_ids(session, chat_id)
    rows = client.get("/api/devconsole/turns", headers=admin).json()
    assert [r["turn_id"] for r in rows] == [second, first] and rows[0]["request"] == "가" * 60
    assert [r["turn_id"] for r in client.get("/api/devconsole/turns?limit=1", headers=admin).json()] == [second]
    assert rows[1]["tool_calls"] == 0 and rows[1]["llm_calls"] == 1


def test_unfinished_turn_is_running_only_while_its_chat_runs(client, admin, session):
    chat, old = made_turn(session, events=[ctx_ev(), llm_ev(1, ms=None)])
    status = lambda: {r["turn_id"]: r["status"] for r in client.get("/api/devconsole/turns", headers=admin).json()}
    assert status()[old] == "stopped"  # 끝 사건이 없고 돌고 있지도 않다(서버가 다시 떴다)
    newer = chats.add_message(session, chat, "user", {"kind": "text", "text": "다음"})
    session.flush()
    session.add(TraceEvent(chat_session_id=chat, turn_id=newer.id, seq=1, **ctx_ev()))
    session.commit()
    held = turns.claim(chat)
    try:
        now = status()
    finally:
        turns.release(chat, held)
    assert (now[old], now[newer.id]) == ("stopped", "running")  # 도는 것은 그 대화의 마지막 턴뿐


def test_limit_is_bounded(client, admin):
    assert client.get("/api/devconsole/turns?limit=0", headers=admin).json()["code"] == "invalid_request"
    assert client.get("/api/devconsole/turns?limit=201", headers=admin).status_code == 422


def test_unknown_turn_is_404(client, admin):
    r = client.get("/api/devconsole/turns/999", headers=admin)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


# ── 구조 ────────────────────────────────────────────────────────────


def test_node_labels_and_detail_shape(client, admin, finished_turn):
    body = get_turn(client, admin, finished_turn)
    labels = [x["label"] for x in body["structure"]["nodes"]]
    assert labels == ["요청 받기", "컨텍스트 조립", "스킬 찾기", "워크플로우 짜기", "판단 (모델)", "도구 실행",
                      "조건 점검", "승인 판단", "응답·기록"]
    n = nodes(body)
    assert all(set(x["detail"]) == {"in", "out", "ms", "model", "settings"} for x in n.values())
    assert n["skill"]["detail"]["in"] == "일치하는 스킬 없음" and n["skill"]["count"] == 0
    assert (n["request"]["state"], n["request"]["detail"]["in"]) == ("past", "몇 개야?")
    assert n["plan"]["detail"]["model"] == "claude-opus-5.5" and n["tool"]["detail"]["model"] is None
    assert n["tool"]["detail"]["in"] == [{"n": 1, "tool": "schedule.read", "input": "{}"}]
    assert n["tool"]["detail"]["out"][0]["status"] == "done"
    assert n["respond"]["detail"]["out"] == "두 개입니다" and body["turn"]["turn_id"] == finished_turn


def test_context_parts_estimate_tokens_from_the_first_call(client, admin, finished_turn):
    parts = nodes(get_turn(client, admin, finished_turn))["context"]["detail"]["in"]["parts"]
    assert set(parts[0]) == {"name", "chars", "tokens", "share"}
    total = sum(p["chars"] for p in parts)
    assert all(p["tokens"] == round(12 * p["chars"] / total) for p in parts)  # 첫 호출 입력 12토큰
    assert sum(p["share"] for p in parts) == pytest.approx(100, abs=0.5)


def test_settings_of_check_and_approval(client, admin, finished_turn, session):
    n = nodes(get_turn(client, admin, finished_turn))
    assert (n["check"]["detail"]["settings"], n["approval"]["detail"]["settings"]) == (
        "점검 한도 5회", "승인 수준: 중요한 것만")
    set_approval_mode(session, "all")
    assert nodes(get_turn(client, admin, finished_turn))["approval"]["detail"]["settings"] == "승인 수준: 모두 승인"


def test_steps_go_to_check_approval_and_tool_cells(client, admin, session):
    names = ["generate.run", "harness.check", "out.submit_change", "scenario.submit", "rules.propose", "calc.cpm"]
    _, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=names), llm_ev(5), end_ev(6)],
                        steps=[{"tool": t} for t in names], run_status="done")
    n = nodes(get_turn(client, admin, turn))
    assert (n["check"]["count"], n["approval"]["count"], n["tool"]["count"]) == (2, 3, 1)
    assert (n["check"]["state"], n["approval"]["state"], n["tool"]["state"]) == ("past", "past", "past")
    assert n["check"]["detail"]["ms"] == 20


def test_running_turn_without_an_open_event_lights_judge(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["calc.cpm"])], steps=[{"tool": "calc.cpm"}])
    held = turns.claim(chat)
    try:
        n = nodes(get_turn(client, admin, turn))
    finally:
        turns.release(chat, held)
    assert (n["judge"]["state"], n["tool"]["state"], n["plan"]["state"]) == ("now", "past", "past")


def test_running_first_call_lights_plan(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, ms=None)])
    held = turns.claim(chat)
    try:
        n = nodes(get_turn(client, admin, turn))
    finally:
        turns.release(chat, held)
    assert (n["plan"]["state"], n["judge"]["state"], n["context"]["state"]) == ("now", "todo", "past")


# ── 시간표 ──────────────────────────────────────────────────────────


def test_timeline_puts_steps_and_inner_calls_in_time_order(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["generate.run", "calc.cpm"]), llm_ev(3),
                                            end_ev(4)],
                           steps=[{"tool": "generate.run", "ms": 100}, {"tool": "calc.cpm", "ms": 200}],
                           run_status="done")
    inner = {"requested_model": "h", "input_tokens": 40, "output_tokens": 4, "latency_ms": 50, "ok": True}
    session.add(LlmCall(chat_session_id=chat, purpose="hard", model="h", created_at=T0 + timedelta(seconds=1.6),
                        **inner))  # generate.run(1.5초~1.6초) 안에서 1.55초에 시작
    session.add(LlmCall(chat_session_id=chat, purpose="normal", model="m", created_at=T0 + timedelta(seconds=1.5),
                        **inner))  # 루프 자신의 호출(llm 사건)은 다시 넣지 않는다
    session.add(LlmCall(chat_session_id=chat, purpose="hard", model="h", created_at=T0 + timedelta(seconds=9),
                        **inner))  # 턴 밖
    session.add(LlmCall(chat_session_id=None, purpose="hard", model="h", created_at=T0 + timedelta(seconds=2),
                        **inner))  # 다른 대화
    session.commit()
    timeline = get_turn(client, admin, turn)["timeline"]
    assert [(t["seq"], t["kind"], t["label"]) for t in timeline] == [
        (1, "context", "컨텍스트 조립"), (2, "llm", "모델 호출 (normal)"), (3, "tool", "generate.run"),
        (4, "inner_llm", "도구 안 모델 호출 (hard)"), (5, "tool", "calc.cpm"), (6, "llm", "모델 호출 (normal)"),
    ]
    assert set(timeline[0]) == {"seq", "kind", "label", "started_at", "ms", "model", "input_tokens", "output_tokens",
                                "cost", "ok", "error", "input_text", "output_text", "parallel_group"}
    tool1, inner_call, tool2 = timeline[2], timeline[3], timeline[4]
    assert tool1["started_at"] == "2027-03-01T09:00:01.500000Z" and tool2["started_at"] == "2027-03-01T09:00:01.600000Z"
    assert inner_call["started_at"] == "2027-03-01T09:00:01.550000Z" and inner_call["ms"] == 50
    assert (inner_call["model"], inner_call["input_tokens"], inner_call["parallel_group"]) == ("h", 40, None)
    assert tool1["parallel_group"] == tool2["parallel_group"] == 2  # 같은 답(llm 사건 seq 2)이 함께 부른 도구
    assert timeline[1]["parallel_group"] is None


def test_generation_turn_shows_its_inner_calls_inside_the_step(client, admin, scripted, chat_id, session,
                                                               monkeypatch):
    gen = FakeLiner()
    script(gen, WBS_OK, SCHED_OK)
    monkeypatch.setattr(generate_tools, "client_for", lambda ctx: LlmClient(ctx.session, transport=gen.transport))
    args = {"domain": "construction", "level": "L3", "request": "5층 사무동", "facts": [START_FACT]}
    scripted.push(calls("generate.run", args), reply("끝"))
    say(client, admin, chat_id, "일정 만들어 줘")
    body = get_turn(client, admin, turn_ids(session, chat_id)[-1])
    assert [t["kind"] for t in body["timeline"]] == ["context", "llm", "tool", "inner_llm", "inner_llm", "llm"]
    assert [t["label"] for t in body["timeline"]][3] == "도구 안 모델 호출 (hard)"
    assert (nodes(body)["check"]["count"], nodes(body)["check"]["state"]) == (1, "past")
    assert (body["turn"]["llm_calls"], body["turn"]["tokens"]) == (4, 68)  # 루프 2번 + 도구 안 2번, 12/5 토큰씩


def test_steps_after_an_unreadable_reply_have_no_group_and_follow_the_previous_step(client, admin, session):
    """답 1(도구 둘)이 잘려 읽을 수 없고 답 2 가 도구 하나: 셋 모두 짝 없이 답 1 뒤에 차례로."""
    cut = llm_ev(1, calls_=["generate.run", "harness.check"])
    cut["output_text"] = cut["output_text"][:40] + "\n(뒤는 생략)"
    _, turn = made_turn(session, events=[ctx_ev(), cut, llm_ev(3, calls_=["calc.cpm"]), llm_ev(5), end_ev(6)],
                        steps=[{"tool": "generate.run", "ms": 100}, {"tool": "harness.check", "ms": 200},
                               {"tool": "calc.cpm", "ms": 300}], run_status="done")
    tools = [t for t in get_turn(client, admin, turn)["timeline"] if t["kind"] == "tool"]
    assert [(t["label"], t["parallel_group"], t["started_at"]) for t in tools] == [
        ("generate.run", None, "2027-03-01T09:00:01.500000Z"),
        ("harness.check", None, "2027-03-01T09:00:01.600000Z"),
        ("calc.cpm", None, "2027-03-01T09:00:01.800000Z"),
    ]


def test_turn_list_skips_big_text_columns_and_reads_inner_calls_once(client, admin, session):
    from sqlalchemy import event

    for _ in range(3):
        made_turn(session, events=[ctx_ev(), llm_ev(1), end_ev(2)])
    statements: list[str] = []
    engine = session.get_bind()
    listen = lambda conn, cursor, statement, *rest: statements.append(statement)
    event.listen(engine, "before_cursor_execute", listen)
    try:
        assert len(client.get("/api/devconsole/turns", headers=admin).json()) == 3
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    assert not [s for s in statements if "trace_events.input_text" in s or "trace_events.output_text" in s]
    assert len([s for s in statements if "FROM llm_calls" in s]) == 1


def test_turn_totals_count_inner_calls(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["generate.run"], cost=0.5), llm_ev(3),
                                            end_ev(4)], steps=[{"tool": "generate.run"}], run_status="done")
    session.add(LlmCall(chat_session_id=chat, purpose="hard", model="h", requested_model="h", input_tokens=40,
                        output_tokens=4, cost=None, latency_ms=50, ok=True, created_at=T0 + timedelta(seconds=2)))
    session.commit()
    row = get_turn(client, admin, turn)["turn"]
    assert (row["llm_calls"], row["tool_calls"], row["tokens"], row["cost"], row["ms"]) == (3, 1, 264, 0.5, 4000)


def test_failed_step_shows_its_error_in_the_timeline(client, admin, session):
    _, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["calc.cpm"]), llm_ev(3), end_ev(4)],
                        steps=[{"tool": "calc.cpm", "status": "failed", "output_json": '{"error": "없음"}'}],
                        run_status="done")
    tool = next(t for t in get_turn(client, admin, turn)["timeline"] if t["kind"] == "tool")
    assert (tool["ok"], tool["error"], tool["output_text"]) == (False, "없음", '{"error": "없음"}')


# ── 사용량 ──────────────────────────────────────────────────────────


def test_usage_by_day_is_in_date_order_in_seoul_days(client, admin, session):
    today = datetime.now(UTC).replace(hour=20, minute=0, second=0, microsecond=0)  # 서울로는 다음 날 새벽
    days = [today - timedelta(days=2), today - timedelta(days=5), today - timedelta(days=2)]
    for at in days:
        add_calls(session, [("m", 1, 1, None, True)], at=at.replace(tzinfo=None))
    rows = client.get("/api/devconsole/usage?group=day&days=14", headers=admin).json()["rows"]
    key = lambda at: at.astimezone(SEOUL).date().isoformat()
    assert [(r["key"], r["calls"]) for r in rows] == [(key(days[1]), 1), (key(days[0]), 2)]


def test_usage_by_purpose_and_known_cost(client, admin, session):
    add_calls(session, [("m", 1, 1, 0.25, True), ("m", 1, 1, None, True)])
    session.add(LlmCall(purpose="hard", model="m", requested_model="m", latency_ms=1, ok=True, cost=0.5))
    session.commit()
    u = client.get("/api/devconsole/usage?group=purpose", headers=admin).json()
    assert [(r["key"], r["calls"], r["cost"]) for r in u["rows"]] == [("normal", 2, 0.25), ("hard", 1, 0.5)]
    assert u["cost_known"] is True and u["totals"]["cost"] == pytest.approx(0.75)


def test_usage_window_and_searches(client, admin, session):
    old = (datetime.now(UTC) - timedelta(days=20)).replace(tzinfo=None)
    add_calls(session, [("m", 1, 1, None, True)], at=old)
    add_calls(session, [("m", 1, 1, None, True)])
    session.add_all([EvidenceSearch(query="q", mode="web", ok=True), EvidenceSearch(query="q", mode="web", ok=False),
                     EvidenceSearch(query="q", mode="web", ok=True, created_at=old),
                     EvidenceSearch(query="q", mode="weather", ok=False)])  # 날씨 조회는 근거 검색 수에 들지 않는다
    session.commit()
    u = client.get("/api/devconsole/usage", headers=admin).json()  # 기본 14일, 모델별
    assert u["totals"]["calls"] == 1 and u["searches"] == {"calls": 2, "failed": 1}
    assert client.get("/api/devconsole/usage?days=30", headers=admin).json()["totals"]["calls"] == 2


@pytest.mark.parametrize("query", ["days=0", "days=91", "group=team"])
def test_usage_rejects_bad_queries(client, admin, query):
    r = client.get(f"/api/devconsole/usage?{query}", headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")


def test_usage_when_nothing_happened(client, admin):
    u = client.get("/api/devconsole/usage", headers=admin).json()
    assert u == {"rows": [], "totals": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": None, "failed": 0},
                 "cost_known": False, "searches": {"calls": 0, "failed": 0}}
