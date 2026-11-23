"""개발 콘솔 API: 턴 목록·구조·추적 시간표·사용량, 관리자만."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.tools.generate as generate_tools
from app.agent import loop, turns
from app.agent.generation import LIMIT_REASON, REPEAT_REASON
from app.agent.trace import CONTEXT_PARTS
from app.llm.client import LlmClient
from app.store import chats
from app.store.messages import FIELD_READ_ONLY_MESSAGE
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


@pytest.mark.parametrize(
    "path",
    [
        "/api/devconsole/turns",
        "/api/devconsole/turns/1",
        "/api/devconsole/usage",
        "/api/devconsole/agent-config",
        "/api/devconsole/health",
    ],
)
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
                                "cost", "ok", "error", "input_text", "output_text", "parallel_group", "signals"}
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
                     EvidenceSearch(query="q", mode="weather", ok=False),  # 날씨 조회는 근거 검색 수에 들지 않는다
                     EvidenceSearch(query="q", mode="info", ok=False)])  # 정보 API 조회도
    session.commit()
    u = client.get("/api/devconsole/usage", headers=admin).json()  # 기본 14일, 모델별
    assert u["totals"]["calls"] == 1 and u["searches"] == {"calls": 2, "failed": 1}
    assert client.get("/api/devconsole/usage?days=30", headers=admin).json()["totals"]["calls"] == 2


def test_health_search_counts_leave_out_weather_and_info_api_calls(client, admin, session):
    session.add_all([EvidenceSearch(query="q", mode="web", ok=True), EvidenceSearch(query="q", mode="legal", ok=False),
                     EvidenceSearch(query="q", mode="weather", ok=False), EvidenceSearch(query="q", mode="info", ok=False),
                     EvidenceSearch(query="q", mode="info", ok=True)])
    session.commit()
    search = client.get("/api/devconsole/health", headers=admin).json()["search"]
    assert (search["calls_7d"], search["failed_7d"]) == (2, 1)


def test_usage_counters_separate_info_api_searches_reuses_vision_and_embedding(client, admin, session):
    old = (datetime.now(UTC) - timedelta(days=20)).replace(tzinfo=None)
    session.add_all([
        EvidenceSearch(query="q", mode="info", ok=True), EvidenceSearch(query="q", mode="info", ok=False),
        EvidenceSearch(query="q", mode="info", ok=True, created_at=old),
        EvidenceSearch(query="q", mode="weather", ok=True),
        EvidenceSearch(query="q", mode="web", ok=True), EvidenceSearch(query="q", mode="legal", ok=False),
        *[EvidenceSearch(query="q", mode="reuse", ok=True) for _ in range(3)],
        EvidenceSearch(query="q", mode="reuse", ok=True, created_at=old),
    ])
    common = {"requested_model": "m", "latency_ms": 5}
    session.add_all([
        LlmCall(purpose="vision", model="v", input_tokens=100, output_tokens=20, cost=0.01, ok=True, **common),
        LlmCall(purpose="vision", model="v", input_tokens=50, output_tokens=0, cost=None, ok=False, **common),
        LlmCall(purpose="vision", model="v", input_tokens=9, output_tokens=9, ok=True, created_at=old, **common),
        LlmCall(purpose="embedding", model="e", input_tokens=300, output_tokens=0, ok=True, **common),
        LlmCall(purpose="normal", model="m", input_tokens=1, output_tokens=1, ok=True, **common),
    ])
    session.commit()
    c = client.get("/api/devconsole/usage", headers=admin).json()["counters"]
    assert c == {
        "info_api": {"calls": 2, "failed": 1},
        "weather": {"calls": 1, "failed": 0},
        "searches": {"calls": 2, "failed": 1},
        "reuses": {"calls": 3},
        "vision": {"calls": 2, "input_tokens": 150, "output_tokens": 20, "cost": 0.01, "failed": 1},
        "embedding": {"calls": 1, "input_tokens": 300, "output_tokens": 0, "cost": None, "failed": 0},
    }


@pytest.mark.parametrize("query", ["days=0", "days=91", "group=team"])
def test_usage_rejects_bad_queries(client, admin, query):
    r = client.get(f"/api/devconsole/usage?{query}", headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")


def test_usage_when_nothing_happened(client, admin):
    u = client.get("/api/devconsole/usage", headers=admin).json()
    zero = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": None, "failed": 0}
    assert u == {"rows": [], "totals": zero, "cost_known": False, "searches": {"calls": 0, "failed": 0},
                 "counters": {"info_api": {"calls": 0, "failed": 0}, "weather": {"calls": 0, "failed": 0},
                              "searches": {"calls": 0, "failed": 0}, "reuses": {"calls": 0},
                              "vision": zero, "embedding": zero}}


def test_catalog_and_harness_block_simulation(client, admin):
    res = client.get("/api/devconsole/catalog", headers=admin)
    assert res.status_code == 200
    body = res.json()
    assert len(body["principles"]) >= 5
    rule_ids = [r["id"] for r in body["harness"]]
    assert "H-CPM-01" in rule_ids and "H-RES-01" in rule_ids and "H-LOOP-01" in rule_ids
    assert body["sources"]["system_chars"] > 100
    assert len(body["sources"]["guides"]) >= 10
    assert len(body["registry"]["tools"]) >= 15

    sim = client.post("/api/devconsole/harness/H-RES-01/test", headers=admin)
    assert sim.status_code == 200
    sim_body = sim.json()
    assert sim_body["rule_id"] == "H-RES-01" and sim_body["blocked"] is True
    assert sim_body["model_feedback"]["passed"] is False


def test_agent_config_roundtrip_and_turn_structure_sync(client, admin, user, finished_turn):
    r0 = client.get("/api/devconsole/agent-config", headers=admin)
    assert r0.status_code == 200
    assert r0.json() == {
        "approval_mode": "important",
        "max_steps": 12,
        "max_check_retries": 5,
        "tool_output_limit": 4000,
        "history_limit": 30,
        "enable_skill_match": True,
        "enable_self_reflection": True,
    }
    assert client.put("/api/devconsole/agent-config", headers=user, json={"max_steps": 8}).status_code == 403

    r1 = client.put(
        "/api/devconsole/agent-config",
        headers=admin,
        json={
            "approval_mode": "auto",
            "max_steps": 8,
            "max_check_retries": 3,
            "tool_output_limit": 6000,
            "history_limit": 20,
            "enable_skill_match": False,
            "enable_self_reflection": False,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["max_steps"] == 8 and r1.json()["enable_skill_match"] is False

    turn = get_turn(client, admin, finished_turn)
    assert turn["structure"]["limit"] == 8
    n = nodes(turn)
    assert n["check"]["detail"]["settings"] == "점검 한도 3회"
    assert n["approval"]["detail"]["settings"] == "승인 수준: 자동"

    cat = client.get("/api/devconsole/catalog", headers=admin).json()
    assert cat["agent_config"]["max_steps"] == 8
    lim_rule = next(r for r in cat["harness"] if r["id"] == "H-LIM-01")
    assert "8바퀴" in lim_rule["title"] and "3회" in lim_rule["title"]
    assert any("하네스 3회 · 루프 8바퀴" in p for p in cat["principles"])  # U7: 원칙 박스도 설정값
    assert len(cat["sources"]["pipeline_prompts"]) >= 5
    assert any(t["name"] == "schedule.read" and "calls" in t and t["enabled"] is True for t in cat["registry"]["tools"])


def test_live_harness_rules_execute_real_engines(client, admin):
    for rule_id in ("H-CPM-01", "H-RES-01", "H-CAL-01", "H-FIN-01", "H-APP-01", "H-IN-01"):
        r = client.post(f"/api/devconsole/harness/{rule_id}/test", headers=admin)
        assert r.status_code == 200, f"{rule_id}: {r.text}"
        body = r.json()
        assert body["engine"] == "live_harness"
        assert isinstance(body["elapsed_ms"], int) and body["elapsed_ms"] >= 0
        if rule_id in ("H-CPM-01", "H-RES-01", "H-CAL-01", "H-FIN-01"):
            assert body["model_feedback"]["passed"] is False
            assert len(body["model_feedback"]["violations"]) >= 1
        elif rule_id == "H-APP-01":
            assert body["model_feedback"]["needs_approval"] is True
        elif rule_id == "H-IN-01":
            assert body["model_feedback"]["truncated"] is True


def harness_test(client, admin, rule_id: str) -> dict:
    r = client.post(f"/api/devconsole/harness/{rule_id}/test", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_loop_harness_runs_the_real_agent_loop_in_a_throwaway_db(client, admin, session):
    body = harness_test(client, admin, "H-LOOP-01")
    assert body["engine"] == "live_harness" and body["blocked"] is True
    fb = body["model_feedback"]
    assert fb["tool"] == "schedule.read" and fb["ok"] is False and fb["step_status"] == "failed"
    assert fb["rollback_calls"] >= 1 and fb["db_rolled_back"] is True
    assert fb["error"] == "대상 일정이 없습니다."
    assert fb["reflection"] == "도구 `schedule.read` 실패 — 오류 원인을 확인해 인자를 고치거나 대안 도구를 사용하세요."
    session.expire_all()  # 운영 DB 에는 아무것도 남지 않는다(대화·실행·LLM 호출 모두 임시 DB)
    assert session.query(WorkflowRun).count() == 0 and session.query(LlmCall).count() == 0


def test_limit_harness_runs_the_real_agent_loop_until_the_configured_limit(client, admin, session):
    body = harness_test(client, admin, "H-LIM-01")
    assert body["engine"] == "live_harness" and body["blocked"] is True
    fb = body["model_feedback"]
    assert fb["limit"] == 12 and fb["llm_calls"] == 12 and fb["tool_steps"] == 12
    assert fb["status"] == "failed" and fb["error_code"] == "step_limit"
    assert fb["error"] == "단계 한도에 닿아 멈췄습니다."

    client.put("/api/devconsole/agent-config", headers=admin, json={"max_steps": 5})
    fb5 = harness_test(client, admin, "H-LIM-01")["model_feedback"]
    assert fb5["limit"] == 5 and fb5["llm_calls"] == 5 and fb5["error_code"] == "step_limit"
    session.expire_all()
    assert session.query(WorkflowRun).count() == 0 and session.query(LlmCall).count() == 0


def test_limit_harness_fails_when_the_step_guard_is_broken(client, admin, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(loop, "STEP_LIMIT", loop.DONE)  # 한도에 닿아도 실패로 멈추지 않는 루프
        body = harness_test(client, admin, "H-LIM-01")
    assert body["blocked"] is False
    assert body["model_feedback"]["error_code"] is None and body["model_feedback"]["status"] == "done"

    real_begin = loop._Turn.begin

    def begin_with_other_limit(self, *args, **kwargs):  # 설정과 다른 한도로 도는 루프(상수가 바뀐 경우)
        real_begin(self, *args, **kwargs)
        self.max_steps_cfg += 1

    monkeypatch.setattr(loop._Turn, "begin", begin_with_other_limit)
    body = harness_test(client, admin, "H-LIM-01")
    assert body["blocked"] is False
    assert body["model_feedback"]["limit"] == 12 and body["model_feedback"]["llm_calls"] == 13


def test_loop_harness_fails_when_the_rollback_or_reflection_is_removed(client, admin, monkeypatch):
    real_end_tool = loop._Turn.end_tool

    def end_tool_without_rollback(self, call):
        real = self.session.rollback
        self.session.rollback = lambda: None
        try:
            return real_end_tool(self, call)
        finally:
            self.session.rollback = real

    with monkeypatch.context() as m:
        m.setattr(loop._Turn, "end_tool", end_tool_without_rollback)
        body = harness_test(client, admin, "H-LOOP-01")
    assert body["blocked"] is False
    assert body["model_feedback"]["rollback_calls"] == 0 and body["model_feedback"]["db_rolled_back"] is False

    def end_tool_without_reflection(self, call):
        self.enable_self_reflection = False  # 설정은 켜져 있는데 주입하지 않는 루프
        return real_end_tool(self, call)

    monkeypatch.setattr(loop._Turn, "end_tool", end_tool_without_reflection)
    body = harness_test(client, admin, "H-LOOP-01")
    assert body["blocked"] is False and body["model_feedback"]["reflection"] is None


# ── 오늘(11-23) 더한 분기 신호: 기록된 단계·호출로만 켠다 ─────────────────────────


def signal_turn(session, steps: list[dict], *, text: str = "요청") -> int:
    names = [s["tool"] for s in steps]
    return made_turn(session, text=text, events=[ctx_ev(), llm_ev(1, calls_=names), llm_ev(3), end_ev(4)],
                     steps=steps, run_status="done")[1]


def tool_signals(body: dict) -> list[list[str]]:
    return [t.get("signals") for t in body["timeline"] if t["kind"] == "tool"]


def out(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def test_info_api_and_evidence_signals_come_from_the_recorded_step_output(client, admin, session):
    turn = signal_turn(session, [
        {"tool": "info.call", "output_json": out(ok=True, http_status=200, evidence_id=3, truncated=False, body="{}")},
        {"tool": "evidence.search", "output_json": out(search_id=9, used=0, limit=3, reused=True, results=[])},
        {"tool": "evidence.search", "output_json": out(search_id=10, used=1, limit=3, results=[])},
    ])
    body = get_turn(client, admin, turn)
    assert tool_signals(body) == [["info_used"], ["evidence_reused"], ["evidence_fresh"]]
    assert {"info_used", "evidence_reused", "evidence_fresh"} <= set(body["structure"]["edges_lit"])


def test_failed_info_calls_and_searches_light_nothing(client, admin, session):
    turn = signal_turn(session, [
        {"tool": "info.call", "status": "failed", "output_json": out(error="path 에 「..」는 쓸 수 없습니다")},
        {"tool": "evidence.search", "status": "failed", "output_json": out(error="근거 검색 실패")},
    ])
    body = get_turn(client, admin, turn)
    assert tool_signals(body) == [[], []] and body["structure"]["edges_lit"] == []


def test_import_confirmed_lights_only_for_the_button_sentence_of_that_file(client, admin, session):
    button = "네, 확인했으니 이 파일(#12)을 일정 초안으로 가져와 줘."
    step = {"tool": "schedule.import", "input_json": out(file_id=12, confirmed=True),
            "output_json": out(step="imported", draft={"draft_id": 4, "reason": None})}
    assert "import_confirmed" in get_turn(client, admin, signal_turn(session, [step], text=button))["structure"]["edges_lit"]
    other = get_turn(client, admin, signal_turn(session, [step], text="이 파일 가져와 줘"))
    assert "import_confirmed" not in other["structure"]["edges_lit"]  # 모델이 스스로 confirmed 를 넣은 것
    other_file = {**step, "input_json": out(file_id=13, confirmed=True)}
    assert tool_signals(get_turn(client, admin, signal_turn(session, [other_file], text=button))) == [[]]
    # 같은 턴의 두 번째 가져오기는 루프가 confirmed 를 채웠어도 거절됐다 — 거절만 보인다
    refused = {**step, "status": "failed", "output_json": out(error=loop.IMPORT_AGAIN.format("12"))}
    assert tool_signals(get_turn(client, admin, signal_turn(session, [step, refused], text=button))) == [
        ["import_confirmed"], ["import_refused"]]


def test_a_repeated_import_is_marked_refused_with_the_loops_reason(client, admin, session):
    why = loop.IMPORT_AGAIN.format("12")
    turn = signal_turn(session, [{"tool": "schedule.import", "status": "failed", "output_json": out(error=why)}])
    body = get_turn(client, admin, turn)
    tool = next(t for t in body["timeline"] if t["kind"] == "tool")
    assert (tool["signals"], tool["ok"], tool["error"]) == (["import_refused"], False, why)


def test_repair_stopped_lights_when_generation_stopped_on_repeated_violations(client, admin, session):
    repeat = out(ok=False, reason=REPEAT_REASON)
    turn = signal_turn(session, [
        {"tool": "generate.run", "output_json": repeat},
        {"tool": "schedule.import", "output_json": out(step="imported", draft={"draft_id": 1, "reason": REPEAT_REASON})},
        {"tool": "generate.run", "output_json": out(ok=False, reason=LIMIT_REASON)},
    ])
    body = get_turn(client, admin, turn)
    assert tool_signals(body) == [["repair_stopped"], ["repair_stopped"], []]
    assert "repair_stopped" in body["structure"]["edges_lit"]


def test_role_blocked_lights_when_a_tool_is_refused_by_the_role_rule(client, admin, session):
    turn = signal_turn(session, [
        {"tool": "out.submit_change", "status": "failed", "output_json": out(error=FIELD_READ_ONLY_MESSAGE)},
        {"tool": "calc.cpm", "status": "failed", "output_json": out(error="대상 일정이 없습니다.")},
    ])
    body = get_turn(client, admin, turn)
    assert tool_signals(body) == [["role_blocked"], []]
    assert "role_blocked" in body["structure"]["edges_lit"]


def test_vision_by_a_tool_lights_vision_tool_but_an_image_turn_does_not(client, admin, session):
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, calls_=["report.learn_template"]), llm_ev(3), end_ev(4)],
                           steps=[{"tool": "report.learn_template"}], run_status="done")
    session.add(LlmCall(chat_session_id=chat, purpose="vision", model="v", requested_model="v", latency_ms=5, ok=True,
                        created_at=T0 + timedelta(seconds=2)))
    session.commit()
    assert "vision_tool" in get_turn(client, admin, turn)["structure"]["edges_lit"]
    # 그림 턴: 루프 자신의 호출이 vision — 같은 수의 vision 호출 기록은 도구가 한 것이 아니다
    chat, turn = made_turn(session, events=[ctx_ev(), llm_ev(1, label="vision"), end_ev(2)])
    session.add(LlmCall(chat_session_id=chat, purpose="vision", model="v", requested_model="v", latency_ms=5, ok=True,
                        created_at=T0 + timedelta(seconds=1.5)))
    session.commit()
    lit = get_turn(client, admin, turn)["structure"]["edges_lit"]
    assert "vision_turn" in lit and "vision_tool" not in lit


# ── 시스템 진단: 정보 API 연결 · 근거 다시 쓰기 · 공휴일 표 · 그림 읽기 배정 ─────────────


def test_health_lists_info_api_connections_without_key_material(client, admin, session):
    from app.security.crypto import encrypt
    from app.store.tables import InfoConnection

    checked = datetime(2026, 11, 23, 3, 0)
    session.add_all([
        InfoConnection(name="공휴일 API", preset="generic", base_url="https://apis.data.go.kr/B090041/x?serviceKey=PASTED",
                       secret_ciphertext=encrypt("SECRETkey123"), secret_last4="y123", status="ok", checked_at=checked),
        InfoConnection(name="기상청", preset="kma", base_url="https://apis.data.go.kr/1360000",
                       secret_ciphertext=encrypt("KMAkey456"), secret_last4="y456", status="failed"),
    ])
    session.commit()
    r = client.get("/api/devconsole/health", headers=admin)
    info = r.json()["info_api"]
    assert info["status"] == "warn" and info["count"] == 2
    assert [(c["name"], c["kind"], c["status"]) for c in info["connections"]] == [
        ("공휴일 API", "generic", "ok"), ("기상청", "kma", "failed")]
    assert info["connections"][0]["checked_at"].startswith("2026-11-23T03:00") and info["connections"][1]["checked_at"] is None
    for leaked in ("SECRETkey123", "KMAkey456", "y123", "y456", "PASTED", "apis.data.go.kr"):
        assert leaked not in r.text


def test_health_without_info_connections_says_off(client, admin):
    info = client.get("/api/devconsole/health", headers=admin).json()["info_api"]
    assert (info["status"], info["count"], info["connections"]) == ("off", 0, [])


def test_health_counts_reusable_evidence_and_reuses_against_liner_searches(client, admin, session):
    from app.store.tables import EvidenceItem, EvidenceLink

    now = datetime.now(UTC).replace(tzinfo=None)
    web = EvidenceSearch(query="골조 공기", mode="web", ok=True)
    weather = EvidenceSearch(query="날씨", mode="weather", ok=True)
    session.add_all([web, weather])
    session.flush()

    def item(search, days=1, linked=True, retired=False):
        row = EvidenceItem(search_id=search.id, title="t", url="https://example.org", created_at=now - timedelta(days=days),
                           retired=retired)
        session.add(row)
        session.flush()
        if linked:
            session.add(EvidenceLink(evidence_id=row.id, schedule_id=1))

    item(web)  # 다시 쓸 수 있다
    item(web, linked=False)
    item(web, days=31)
    item(web, retired=True)
    item(weather)  # 날씨 결과는 다시 쓰지 않는다
    session.add_all([EvidenceSearch(query="q", mode="reuse", ok=True), EvidenceSearch(query="q", mode="reuse", ok=True),
                     EvidenceSearch(query="q", mode="reuse", ok=True, created_at=now - timedelta(days=10)),
                     EvidenceSearch(query="q", mode="legal", ok=False)])
    session.commit()
    reuse = client.get("/api/devconsole/health", headers=admin).json()["evidence_reuse"]
    assert reuse == {"reusable": 1, "reused_7d": 2, "searches_7d": 2, "days": 30}


def test_health_shows_holiday_years_and_the_vision_assignment(client, admin, session):
    from app.core.calendar import KOREA_HOLIDAYS

    h = client.get("/api/devconsole/health", headers=admin).json()
    years = sorted({d.year for d in KOREA_HOLIDAYS})
    assert h["holidays"]["years"] == years and h["holidays"]["counts"][str(years[0])] > 10
    assert (h["vision"]["status"], h["vision"]["connection_name"]) == ("warn", None)
    add_connection(session)
    v = client.get("/api/devconsole/health", headers=admin).json()["vision"]
    assert (v["status"], v["model"], v["connection_name"], v["stored"], v["key_ready"]) == (
        "ok", "liner-claude-router", "Liner 기본", False, True)


def test_sources_list_every_guide_and_prompt_file_as_it_is_on_disk(client, admin):
    """프롬프트·지식 탭은 손으로 쓴 목록이 아니다: 가이드·파이프라인 프롬프트 폴더를 그대로 읽는다(11-23 info.md 포함)."""
    from app.agent import context as agent_context

    sources = client.get("/api/devconsole/catalog", headers=admin).json()["sources"]
    on_disk = sorted(p.stem for p in agent_context.GUIDES_DIR.glob("*.md") if not p.name.startswith("_"))
    guides = {g["name"]: g for g in sources["guides"]}
    assert sorted(guides) == on_disk and "info" in guides
    assert "공공데이터" in guides["info"]["keywords"]
    assert guides["evidence"]["content"] == (agent_context.GUIDES_DIR / "evidence.md").read_text(encoding="utf-8").strip()
    prompts = {p["name"] for p in sources["pipeline_prompts"]}
    assert {"import_detect", "import_map", "extract", "repair"} <= prompts


# ── 도구 등록부: 쓰기 여부와 부를 수 있는 역할(서버가 막는 바로 그 줄) ────────────


EDITOR_TOOLS = {"schedule.create_project", "out.submit_change", "scenario.submit", "rules.propose",
                "schedule.record_actual",  # tests/security/test_roles.py EDIT_TOOLS 와 같다
                # 새 일정을 만드는 길(F4 재확인, test_roles.NEW_SCHEDULE_TOOLS)
                "generate.extract_conditions", "generate.run", "schedule.import"}
PARTLY_EDITOR_TOOLS = {"ask.questionnaire"}  # purpose generate 일 때만 막는다 — 현장 관리자도 부를 수 있다(일부 거절)


def registry_tools(client, admin) -> dict[str, dict]:
    return {t["name"]: t for t in client.get("/api/devconsole/catalog", headers=admin).json()["registry"]["tools"]}


def test_registry_lists_every_tool_with_its_write_kind_and_the_roles_the_server_allows(client, admin):
    tools = registry_tools(client, admin)
    assert {"info.list", "info.call", "files.set_axes", "field.list", "schedule.import"} <= set(tools)
    assert len(tools) >= 37
    assert {n for n, t in tools.items() if "field" not in t["roles"]} == EDITOR_TOOLS
    assert {n for n, t in tools.items() if t["field_limited"]} == PARTLY_EDITOR_TOOLS
    assert tools["ask.questionnaire"]["roles"] == ["admin", "user", "field"]
    assert all(t["roles"][:2] == ["admin", "user"] for t in tools.values())
    assert (tools["info.list"]["mutates"], tools["info.call"]["mutates"], tools["field.list"]["mutates"]) == (
        False, True, False)


def test_registry_roles_follow_the_tool_code_not_a_list(client, admin):
    from pydantic import BaseModel, ConfigDict

    from tests.tool_doubles import registered

    class In(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class Out(BaseModel):
        ok: bool

    def guarded(args: In, ctx) -> Out:
        ctx.require_editor()
        return Out(ok=True)

    def sometimes(args: In, ctx) -> Out:
        if args is not None:
            ctx.require_editor()
        return Out(ok=True)

    with registered("zz.guarded_spy", guarded, mutates=True), registered("zz.sometimes_spy", sometimes):
        tools = registry_tools(client, admin)
        assert (tools["zz.guarded_spy"]["roles"], tools["zz.guarded_spy"]["field_limited"]) == (["admin", "user"], False)
        assert (tools["zz.sometimes_spy"]["roles"], tools["zz.sometimes_spy"]["field_limited"]) == (
            ["admin", "user", "field"], True)


def test_health_stop_turn_and_tool_toggle_roundtrip(client, admin, user, session, finished_turn):
    del finished_turn
    h_res = client.get("/api/devconsole/health", headers=admin)
    assert h_res.status_code == 200, h_res.text
    h = h_res.json()
    assert h["llm"]["status"] in ("ok", "warn", "error")
    assert h["qdrant"]["status"] in ("ok", "off", "error")
    assert "schedules" in h["db"]["counts"]

    chat = chats.create_chat(session, user_id=_admin_id(session))
    chat.title = "긴 실행"
    session.commit()
    held = turns.claim(chat.id)
    try:
        h2 = client.get("/api/devconsole/health", headers=admin).json()
        assert any(t["chat_session_id"] == chat.id and t["title"] == "긴 실행" for t in h2["active_turns"])
        stop_res = client.post(f"/api/devconsole/turns/{chat.id}/stop", headers=admin)
        assert stop_res.status_code == 200 and stop_res.json()["stopped"] is True
        assert turns.stop_requested(chat.id) is True
    finally:
        turns.release(chat.id, held)

    assert client.put("/api/devconsole/tools/progress.read", headers=user, json={"enabled": False}).status_code == 403
    try:
        off_res = client.put("/api/devconsole/tools/progress.read", headers=admin, json={"enabled": False})
        assert off_res.status_code == 200 and off_res.json() == {"name": "progress.read", "enabled": False}
        cat_off = client.get("/api/devconsole/catalog", headers=admin).json()
        entry_off = next(t for t in cat_off["registry"]["tools"] if t["name"] == "progress.read")
        assert entry_off["enabled"] is False
    finally:
        on_res = client.put("/api/devconsole/tools/progress.read", headers=admin, json={"enabled": True})
        assert on_res.status_code == 200 and on_res.json() == {"name": "progress.read", "enabled": True}
