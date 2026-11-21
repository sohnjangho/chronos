"""실행 추적 기록(app.agent.trace): 루프가 턴마다 context·llm·end 사건을 남긴다."""

import json
import sqlite3

import httpx
import pytest
from sqlalchemy import select

from app.agent import context, trace, turns
from app.agent.context import UiContext, build_context
from app.agent.loop import run_turn
from app.agent.trace import (
    CONTEXT_PARTS,
    MESSAGE_LIMIT,
    TEXT_LIMIT,
    TraceLog,
    context_parts,
)
from app.llm.client import LlmClient
from app.store import chats
from app.store.tables import ChatMessage, TraceEvent, User, WorkflowRun
from app.tools import registry
from tests.llm_doubles import KEY, FakeLiner, add_connection, chat_body
from tests.loop_doubles import FAIL, ScriptedLlm, calls, reply
from tests.tool_doubles import Empty, registered

NO_UI = UiContext(None, None, None)


@pytest.fixture(autouse=True)
def all_tools():
    registry.load_all()


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def chat_id(session, admin_user) -> int:
    return chats.create_chat(session, user_id=admin_user.id).id


@pytest.fixture
def run(session, admin_user, chat_id):
    """run(가짜 LLM, 글, ui=…, max_steps=…) → 턴의 사건 목록. 기본 연결(키 KEY)이 있다."""
    add_connection(session)

    async def go(llm: FakeLiner, text, *, ui=NO_UI, max_steps=12):
        client = LlmClient(session, transport=llm.transport)
        return [e async for e in run_turn(session, admin_user, chat_id, text, ui, llm=client, max_steps=max_steps)]

    return go


def traced(session) -> list[TraceEvent]:
    session.expire_all()
    return session.query(TraceEvent).order_by(TraceEvent.turn_id, TraceEvent.seq).all()


# ── 지시서 시험 ─────────────────────────────────────────────────────


async def test_turn_writes_context_llm_and_end(run, session):
    await run(ScriptedLlm([calls("schedule.read", {}), reply("두 개입니다")]), "몇 개야?")
    ev = session.query(TraceEvent).order_by(TraceEvent.seq).all()
    assert [e.kind for e in ev] == ["context", "llm", "llm", "end"] and len({e.turn_id for e in ev}) == 1
    assert ev[1].model and ev[-1].label == "done"


async def test_llm_event_is_written_before_the_call(run, session):
    """호출 중에 다른 연결로 ms 가 없는 llm 사건이 보이고, 루프 세션에는 쓰지 않은 것이 없다."""
    path = session.get_bind().url.database
    seen: list = []

    def probe(_body):
        seen.append(bool(session.new or session.dirty or session.deleted))
        con = sqlite3.connect(path)
        try:
            seen.append(con.execute("SELECT kind, ms FROM trace_events ORDER BY seq").fetchall())
        finally:
            con.close()

    await run(ScriptedLlm([reply("네")], on_request=probe), "안녕")
    pending, rows = seen
    assert pending is False and [r[0] for r in rows] == ["context", "llm"] and rows[1][1] is None


async def test_trace_never_contains_the_key(run, session):  # Review Focus 4
    liner = FakeLiner()
    liner.push(chat_body("안녕하세요"))
    await run(liner, "안녕")
    liner.push(httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}}))
    await run(liner, "다시")
    events = traced(session)
    assert any(not e.ok for e in events if e.kind == "llm")  # 실패한 호출도 남았다
    for e in events:
        assert all(KEY not in (v or "") for v in (e.input_text, e.output_text, e.error, e.label, e.model))
    assert liner.requests[0].headers["authorization"] == f"Bearer {KEY}"  # 키는 머리글로만 갔다


# ── 사건 칸 ─────────────────────────────────────────────────────────


async def test_turn_id_is_the_user_message_id(run, session, chat_id):
    await run(ScriptedLlm([reply("네")]), "안녕")
    user_message = session.scalars(select(ChatMessage).where(ChatMessage.role == "user")).one()
    assert {e.turn_id for e in traced(session)} == {user_message.id}
    assert {e.chat_session_id for e in traced(session)} == {chat_id}
    assert [e.seq for e in traced(session)] == [1, 2, 3]


async def test_llm_event_keeps_model_tokens_cost_ms_and_the_reply(run, session):
    first = calls("schedule.read", {"x": 1}, text="읽겠습니다", model="m-1", prompt_tokens=7, completion_tokens=3,
                  cost=0.01)
    await run(ScriptedLlm([first, reply("끝", cost=None)]), "몇 개야?")
    llm1, llm2 = [e for e in traced(session) if e.kind == "llm"]
    assert (llm1.model, llm1.input_tokens, llm1.output_tokens, llm1.cost, llm1.ok) == ("m-1", 7, 3, 0.01, True)
    assert llm1.label == "normal" and llm1.ms is not None and llm1.ms >= 0 and llm1.error is None
    assert json.loads(llm1.output_text) == {
        "text": "읽겠습니다", "tool_calls": [{"id": "call_1", "name": "schedule.read", "arguments": '{"x": 1}'}],
    }
    assert json.loads(llm2.output_text) == {"text": "끝", "tool_calls": []} and llm2.cost is None
    sent = json.loads(llm1.input_text)
    assert [m["role"] for m in sent] == ["system", "user"] and sent[1]["content"] == "몇 개야?"
    assert [m["role"] for m in json.loads(llm2.input_text)] == ["system", "user", "assistant", "tool"]


async def test_failed_llm_call_is_kept_with_its_error(run, session):
    await run(ScriptedLlm([calls("schedule.read", {}), FAIL("timeout")]), "x")
    events = traced(session)
    failed = [e for e in events if e.kind == "llm"][-1]
    assert (failed.ok, failed.error, failed.output_text) == (False, "응답이 너무 늦습니다.", "")
    assert failed.ms is not None and failed.model is None
    end = events[-1]
    assert (end.kind, end.label, end.ok, end.error) == ("end", "failed", False, "응답이 너무 늦습니다.")


async def test_run_id_goes_on_every_event_of_the_turn(run, session):
    await run(ScriptedLlm([reply("안녕하세요")]), "안녕")
    await run(ScriptedLlm([calls("schedule.read", {}), reply("끝")]), "읽어 줘")
    first, second = sorted({e.turn_id for e in traced(session)})
    run_id = session.query(WorkflowRun).one().id
    assert {e.run_id for e in traced(session) if e.turn_id == first} == {None}  # 글만 답한 턴은 실행 기록이 없다
    assert {e.run_id for e in traced(session) if e.turn_id == second} == {run_id}


async def test_end_keeps_the_answer_and_the_turn_time(run, session):
    await run(ScriptedLlm([reply("안녕하세요")]), "안녕")
    end = traced(session)[-1]
    assert (end.kind, end.label, end.ok, end.error, end.output_text) == ("end", "done", True, None, "안녕하세요")
    assert end.ms is not None and end.ms >= 0


async def test_end_of_a_step_limit_turn(run, session):
    await run(ScriptedLlm([calls("schedule.read", {})] * 5), "x", max_steps=2)
    end = traced(session)[-1]
    assert (end.label, end.ok, end.error) == ("failed", False, "단계 한도에 닿아 멈췄습니다.")
    assert [e.kind for e in traced(session)] == ["context", "llm", "llm", "end"]


async def test_end_of_a_stopped_turn(run, session, chat_id):
    def stopper(args: Empty, ctx) -> Empty:
        turns.request_stop(chat_id)
        return Empty()

    held = turns.claim(chat_id)
    try:
        with registered("stopper", stopper):
            await run(ScriptedLlm([calls("stopper", {}), reply("안 불림")]), "x")
    finally:
        turns.release(chat_id, held)
    end = traced(session)[-1]
    assert (end.label, end.error) == ("stopped", "중단했습니다.")


async def test_turn_that_fails_to_start_still_ends(run, session, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr("app.agent.loop.build_context", boom)
    ev = await run(ScriptedLlm([reply("안 불림")]), "x")
    assert ev[0].data["code"] == "internal_error"
    assert [(e.kind, e.label) for e in traced(session)] == [("end", "failed")]


async def test_lone_surrogates_in_the_reply_are_stored_safely(run, session):
    escaped = json.dumps(chat_body("답\ud800")).encode()  # 응답 JSON 의 "\\ud800" → 짝 없는 서로게이트
    ev = await run(ScriptedLlm([httpx.Response(200, content=escaped)]), "안녕")
    assert [e.type for e in ev] == ["text", "usage", "done"]
    llm = next(e for e in traced(session) if e.kind == "llm")
    assert json.loads(llm.output_text)["text"] == "답?"


async def test_trace_failure_only_warns(run, session, monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("secret-text")

    monkeypatch.setattr(trace, "TraceEvent", broken)
    ev = await run(ScriptedLlm([calls("schedule.read", {}), reply("끝")]), "x")
    assert [e.type for e in ev][-3:] == ["workflow", "usage", "done"] and "error" not in [e.type for e in ev]
    assert session.query(TraceEvent).count() == 0
    assert "실행 추적을 남기지 못했습니다" in caplog.text and "secret-text" not in caplog.text


# ── 맥락 구성 ───────────────────────────────────────────────────────


async def test_context_event_lists_the_parts(run, session):
    await run(ScriptedLlm([reply("네")]), "안녕")
    ctx = traced(session)[0]
    body = json.loads(ctx.input_text)
    assert ctx.kind == "context" and ctx.label == "컨텍스트 조립" and ctx.ms is not None
    assert [p["name"] for p in body["parts"]] == list(CONTEXT_PARTS)
    assert body["history_count"] == 1 and body["tool_count"] == len(registry.as_llm_tools())
    assert all(p["chars"] > 0 for p in body["parts"] if p["name"] != "붙인 파일")


def test_context_parts_add_up_to_what_the_model_sees(session, admin_user, chat_id, sid):
    chats.add_message(session, chat_id, "user", {"kind": "text", "text": "11월 30일까지 당겨 줘"})
    session.commit()
    ui = UiContext("schedule", sid, "A")
    tools = registry.as_llm_tools()
    parts = {p["name"]: p["chars"] for p in context_parts(session, admin_user, chat_id, ui, tools)}
    messages = build_context(session, admin_user, chat_id, ui)
    system = messages[0]["content"]
    text_parts = ["지시문", "분야 지식", "정밀도", "지금 상황", "날짜 도우미"]
    assert sum(parts[n] for n in text_parts) == len(system) - 4  # 셋을 잇는 "\n\n" 두 개
    assert parts["지금 상황"] == len(context.situation(session, admin_user, ui))
    assert parts["대화"] == len(json.dumps(messages[1:], ensure_ascii=False))
    assert parts["도구 목록"] == len(json.dumps(tools, ensure_ascii=False))


# ── 글 자르기 ───────────────────────────────────────────────────────


def test_input_text_cuts_each_message_and_the_whole(session, chat_id):
    log = TraceLog(session, chat_id, 1)
    big = [{"role": "user", "content": "가" * 10_000} for _ in range(30)]
    ev = log.llm_start(big, "normal")
    assert len(ev.input_text) <= TEXT_LIMIT + len(context.CUT_NOTE)
    head = log.llm_start(big[:2], "normal")
    sent = json.loads(head.input_text)
    assert sent[0]["content"] == "가" * MESSAGE_LIMIT + context.CUT_NOTE


def test_tool_call_arguments_are_cut_too(session, chat_id):
    log = TraceLog(session, chat_id, 1)
    call = {"id": "c", "type": "function", "function": {"name": "schedule.read", "arguments": "x" * 9000}}
    ev = log.llm_start([{"role": "assistant", "content": None, "tool_calls": [call]}], "normal")
    sent = json.loads(ev.input_text)
    assert sent[0]["tool_calls"][0]["function"]["arguments"] == "x" * MESSAGE_LIMIT + context.CUT_NOTE


def test_llm_end_without_an_event_does_nothing(session, chat_id):
    TraceLog(session, chat_id, 1).llm_end(None, None, "x", 3)
    assert len(session.new) == 0


async def test_failure_while_counting_context_parts_only_warns(run, session, monkeypatch, caplog):
    def broken():
        raise RuntimeError("secret-text")

    monkeypatch.setattr(trace, "levels_prompt", broken)  # 추적만 쓰는 이름(맥락 조립은 그대로)
    ev = await run(ScriptedLlm([reply("네")]), "안녕")
    assert [e.type for e in ev] == ["text", "usage", "done"]
    ctx = traced(session)[0]
    assert ctx.kind == "context" and json.loads(ctx.input_text)["parts"] == []
    assert "실행 추적을 남기지 못했습니다: context_parts (RuntimeError)" in caplog.text
    assert "secret-text" not in caplog.text


# ── Fix round 1 ──


def test_reply_text_cuts_tool_arguments_and_stays_json():
    from app.llm.client import LlmReply, ToolCall, Usage

    calls_ = [ToolCall(id=f"c{i}", name="generate.run", arguments=None, raw_arguments="x" * 30_000) for i in range(3)]
    text = trace.reply_text(LlmReply(text="네", tool_calls=calls_, model="m", usage=Usage(1, 1, None)))
    body = json.loads(text)  # 60,000자를 넘지 않아 잘리지 않는다
    assert [c["arguments"] for c in body["tool_calls"]] == ["x" * MESSAGE_LIMIT + context.CUT_NOTE] * 3
