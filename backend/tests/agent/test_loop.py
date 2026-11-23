"""에이전트 루프: 도구 호출 왕복·사건 차례·워크플로우 기록·멈춤·대화 기록 창·사용량."""

import asyncio
import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select

import app.tools.generate as generate_tools
from app.agent import context, loop, turns
from app.agent.context import UiContext, build_context
from app.agent.events import AgentEvent, json_safe, to_sse
from app.agent.generation import generate
from app.agent.loop import run_turn
from app.agent.workflow_log import WorkflowLog
from app.llm.client import LlmClient
from app.store import chats
from app.store import questionnaires as qstore
from app.store.files import raw_path
from app.store.messages import FIELD_READ_ONLY_MESSAGE
from app.store.questionnaires import Question
from app.store.tables import (
    ChatMessage,
    FileRow,
    LlmCall,
    QuestionnaireRecord,
    ScheduleDraft,
    TraceEvent,
    User,
    WorkflowRun,
    WorkflowStep,
)
from app.tools import registry
from app.tools.context import ToolContext, ToolError
from tests.gen_doubles import (
    FINISH_BY,
    SCHED_LATE_BY_3,
    SCHED_OK,
    START_FACT,
    WBS_OK,
    script,
)
from tests.llm_doubles import FakeLiner, add_connection, chat_body
from tests.loop_doubles import FAIL, ScriptedLlm, calls, raw_call, reply
from tests.tool_doubles import Empty, SpyIn, registered

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
    """run(대본 LLM, 글, ui=…, max_steps=…) → 턴의 사건 목록. 기본 연결이 있다."""
    add_connection(session)

    async def go(llm: ScriptedLlm, text, *, ui=NO_UI, max_steps=12, **kw):
        client = LlmClient(session, transport=llm.transport)
        turn = run_turn(session, admin_user, chat_id, text, ui, llm=client, max_steps=max_steps, **kw)
        return [e async for e in turn]

    return go


@pytest.fixture
def run_no_llm(session, admin_user, chat_id):
    """LLM 연결이 하나도 없는 턴."""

    async def go(text):
        client = LlmClient(session, transport=ScriptedLlm().transport)
        return [e async for e in run_turn(session, admin_user, chat_id, text, NO_UI, llm=client)]

    return go


@pytest.fixture
def spy_llm() -> ScriptedLlm:
    return ScriptedLlm([reply("네")])


def types(events: list[AgentEvent]) -> list[str]:
    return [e.type for e in events]


def stored(session, chat_id) -> list[tuple[str, dict]]:
    session.expire_all()
    rows = session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id))
    return [(m.role, m.content_json) for m in rows]


# ── 지시서 시험 ─────────────────────────────────────────────────────


async def test_plain_answer(run):
    ev = await run(ScriptedLlm([reply("안녕하세요")]), "안녕")
    assert [e.type for e in ev] == ["text", "usage", "done"]


async def test_tool_call_roundtrip_is_logged(run, session):
    ev = await run(ScriptedLlm([calls("schedule.read", {}), reply("62개입니다")]), "액티비티 몇 개야?")
    assert [e.type for e in ev if e.type.startswith("tool")] == ["tool_start", "tool_end"]
    assert session.query(WorkflowStep).one().tool == "schedule.read"


async def test_step_limit_stops(run, session):
    llm = ScriptedLlm([calls("schedule.read", {})] * 20)
    ev = await run(llm, "x", max_steps=3)
    assert ev[-2].data["code"] == "step_limit" and ev[-1].type == "done"
    assert ev[-2].data["message"] == "단계 한도에 닿아 멈췄습니다."
    assert len(llm.requests) == 3 and session.query(WorkflowStep).count() == 3
    assert session.query(WorkflowRun).one().status == "failed"


async def test_llm_not_ready_points_to_settings(run_no_llm, session, chat_id):  # Review Focus 2
    ev = await run_no_llm("x")
    assert ev[0].type == "error" and ev[0].data["action"]["open"] == "settings"
    assert types(ev) == ["error", "done"]
    assert ev[0].data == {
        "code": "llm_not_ready",
        "message": "LLM 연결이 필요합니다. 설정에서 연결해 주세요.",
        "action": {"open": "settings", "params": {"section": "llm"}},
    }
    assert stored(session, chat_id) == [("user", {"kind": "text", "text": "x"})]  # 대화는 남는다


async def test_llm_fails_midway_keeps_conversation(run, session, chat_id):  # Review Focus 2
    ev = await run(ScriptedLlm([calls("schedule.read", {}), FAIL("timeout")]), "x")
    assert ev[-2].type == "error" and session.query(WorkflowRun).one().status == "failed"
    assert ev[-2].data == {"code": "llm_failed", "message": "응답이 너무 늦습니다.", "reason": "timeout"}
    assert [role for role, _ in stored(session, chat_id)] == ["user", "assistant", "tool"]


async def test_ui_context_reaches_prompt(run, spy_llm, sid):
    await run(spy_llm, "이거 당겨 줘", ui=UiContext("schedule", sid, "A2020"))
    assert "A2020" in spy_llm.last_messages_text


# ── 사건 차례·워크플로우 기록(R13) ───────────────────────────────────


async def test_tool_turn_event_order(run, sid):
    llm = ScriptedLlm([calls("schedule.read", {}, text="일정을 읽겠습니다."), reply("두 개입니다.")])
    ev = await run(llm, "몇 개야?", ui=UiContext("schedule", sid, None))
    assert types(ev) == [
        "text", "workflow", "tool_start", "tool_end", "workflow", "text", "workflow", "usage", "done",
    ]
    start, end = ev[2].data, ev[3].data
    run_id = ev[1].data["run_id"]
    assert start == {
        "run_id": run_id, "n": 1, "call_id": "call_1", "tool": "schedule.read", "program": "schedule-table",
        "arguments": "{}",
    }
    assert end["ok"] is True and end["error"] is None and end["tool"] == "schedule.read" and end["ms"] >= 0
    assert (end["run_id"], end["n"], end["call_id"]) == (run_id, 1, "call_1")
    step = {"n": 1, "tool": "schedule.read", "program": "schedule-table"}
    assert ev[1].data == {"run_id": run_id, "status": "running", "steps": [{**step, "status": "running"}]}
    assert ev[4].data == {"run_id": run_id, "status": "running", "steps": [{**step, "status": "done"}]}
    assert ev[6].data == {"run_id": run_id, "status": "done", "steps": [{**step, "status": "done"}]}
    assert ev[0].data == {"text": "일정을 읽겠습니다."} and ev[5].data == {"text": "두 개입니다."}


async def test_no_run_row_for_a_pure_text_answer(run, session):
    await run(ScriptedLlm([reply("안녕하세요")]), "안녕")
    assert session.query(WorkflowRun).count() == 0 and session.query(WorkflowStep).count() == 0


async def test_step_records_why_program_model_tokens_cost_and_ms(run, session, sid):
    why = "일정을 먼저 읽겠습니다. " + "가" * 300
    first = calls("schedule.read", {}, text=why, model="m-1", prompt_tokens=7, completion_tokens=3, cost=0.01)
    await run(ScriptedLlm([first, reply("끝")]), "몇 개야?", ui=UiContext("schedule", sid, None))
    step = session.query(WorkflowStep).one()
    assert (step.n, step.tool, step.program, step.status) == (1, "schedule.read", "schedule-table", "done")
    assert step.why == why.strip()[:200] and len(step.why) == 200
    assert (step.model, step.tokens, step.cost) == ("m-1", 10, 0.01) and step.ms >= 0
    assert json.loads(step.input_json) == {} and json.loads(step.output_json)["activity_count"] == 2
    run_row = session.query(WorkflowRun).one()
    assert (run_row.title, run_row.request, run_row.status) == ("몇 개야?", "몇 개야?", "done")
    assert run_row.ended_at is not None and run_row.started_at is not None


async def test_failed_tool_step_keeps_the_error(run, session):
    await run(ScriptedLlm([calls("schedule.read", {}), reply("일정이 없네요")]), "x")
    step = session.query(WorkflowStep).one()
    assert step.status == "failed" and json.loads(step.output_json) == {"error": "대상 일정이 없습니다."}


async def test_run_title_is_the_request_cut_at_40(run, session):
    text = "가" * 60
    await run(ScriptedLlm([calls("schedule.read", {}), reply("끝")]), text)
    assert session.query(WorkflowRun).one().title == "가" * 40


# ── 트랜잭션(R2) ────────────────────────────────────────────────────


async def test_no_write_is_pending_or_locked_during_llm_calls(run, session):
    path = session.get_bind().url.database
    seen: list = []

    def probe(_body):
        seen.append(bool(session.new or session.dirty or session.deleted))
        con = sqlite3.connect(path, timeout=0)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.rollback()
            seen.append("free")
        except sqlite3.OperationalError:
            seen.append("locked")
        finally:
            con.close()

    def writer(args: Empty, ctx) -> Empty:  # 쓰고 flush 만 하는 도구
        ctx.session.add(User(login_id="w", name="w", role="user", password_hash="x"))
        ctx.session.flush()
        return Empty()

    with registered("writer", writer):
        await run(ScriptedLlm([calls("writer", {}), reply("끝")], on_request=probe), "써 줘")
    assert seen == [False, "free", False, "free"]
    assert session.query(LlmCall).count() == 2  # 사용량 기록 세션도 막히지 않았다
    assert session.scalar(select(User).where(User.login_id == "w")) is not None  # 도구의 쓰기는 저장됐다


async def test_failed_tool_writes_are_rolled_back(run, session):
    def half(args: Empty, ctx) -> Empty:
        ctx.session.add(User(login_id="half", name="h", role="user", password_hash="x"))
        ctx.session.flush()
        raise RuntimeError("boom")

    with registered("half", half):
        await run(ScriptedLlm([calls("half", {}), reply("끝")]), "x")
    session.expire_all()
    assert session.scalar(select(User).where(User.login_id == "half")) is None


# ── 대화 기록 재구성(R3·R11) ────────────────────────────────────────


def _assistant_arguments(body: dict) -> str:
    assistant = next(m for m in body["messages"] if m.get("tool_calls"))
    return assistant["tool_calls"][0]["function"]["arguments"]


@pytest.mark.parametrize(
    "raw, sent",
    [("{oops", "{oops"), (..., "{}"), (None, "{}"), (5, "5"), ("null", "{}"), ('{"a": 1}', '{"a": 1}')],
    ids=["broken", "missing", "json_null", "number", "null_text", "object"],
)
async def test_history_tool_arguments_use_raw_text_and_never_null(run, raw, sent):
    llm = ScriptedLlm([raw_call("schedule.read", raw), reply("끝")])
    await run(llm, "x")
    assert _assistant_arguments(llm.bodies[1]) == sent


class BigOut(BaseModel):
    text: str


async def test_tool_results_go_back_as_json_text_cut_at_4000(run, session, chat_id):
    def big(args: Empty, ctx) -> BigOut:
        return BigOut(text="가" * 5000)

    with registered("big", big):
        llm = ScriptedLlm([calls("big", {}), calls("schedule.read", {}, call_id="call_2"), reply("끝")])
        await run(llm, "x")
    tool_messages = [m for m in llm.bodies[2]["messages"] if m["role"] == "tool"]
    full = json.dumps({"text": "가" * 5000}, ensure_ascii=False)
    assert tool_messages[0] == {"role": "tool", "tool_call_id": "call_1", "content": full[:4000] + "\n(뒤는 생략)"}
    err_payload = json.loads(tool_messages[1]["content"])
    assert err_payload["error"] == "대상 일정이 없습니다." and "reflection" in err_payload
    assert stored(session, chat_id)[2][1]["content"] == full[:4000] + "\n(뒤는 생략)"


async def test_model_sees_only_the_last_30_messages(run, session, chat_id):
    for i in range(40):
        chats.add_message(session, chat_id, "user" if i % 2 == 0 else "assistant", {"kind": "text", "text": f"말{i:03d}"})
    session.commit()
    llm = ScriptedLlm([reply("네")])
    await run(llm, "마지막")
    texts = [m["content"] for m in llm.bodies[0]["messages"][1:]]
    assert len(texts) == 30 and texts[0] == "말011" and texts[-1] == "마지막"
    assert llm.bodies[0]["messages"][0]["role"] == "system"


def test_history_drops_orphan_tool_results_and_fills_missing_ones(session, admin_user, chat_id):
    add = lambda role, content: chats.add_message(session, chat_id, role, content)
    add("tool", {"kind": "tool_result", "tool_call_id": "old", "name": "x", "ok": True, "content": "{}"})
    add("user", {"kind": "text", "text": "둘 다 읽어 줘"})
    add("assistant", {"kind": "tool_calls", "text": "", "tool_calls": [
        {"id": "c1", "name": "schedule.read", "arguments": "{}"},
        {"id": "c2", "name": "calc.cpm", "arguments": "{}"},
    ]})
    add("tool", {"kind": "tool_result", "tool_call_id": "c1", "name": "schedule.read", "ok": True, "content": "{}"})
    add("user", {"kind": "text", "text": "다시"})
    session.commit()
    messages = build_context(session, admin_user, chat_id, NO_UI)[1:]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool", "user"]
    assert messages[1]["content"] is None
    assert messages[1]["tool_calls"][1] == {
        "id": "c2", "type": "function", "function": {"name": "calc.cpm", "arguments": "{}"},
    }
    assert messages[3]["tool_call_id"] == "c2" and "실행하지 않았습니다" in messages[3]["content"]


def test_context_has_rules_levels_domain_schedule_and_condition_counts(
    session, admin_user, chat_id, sid, monkeypatch
):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    system = build_context(session, admin_user, chat_id, UiContext("schedule", sid, "A"))[0]
    assert system["role"] == "system"
    text = system["content"]
    assert "날짜를 계산하지 말고 도구 결과의 날짜만 말한다" in text
    # I6: 날짜는 코드가 만든 날짜 도우미에서 옮겨 쓴다(모델이 날짜를 만들지 않는다)
    assert "## 날짜 도우미" in text and "- 오늘: 2026-11-20 (금)" in text and "- 올해: 2026년 · 내년: 2027년" in text
    assert "날짜 도우미에 보이는 날짜나 사용자가 연·월·일을 모두 적은 날짜만" in text
    assert "값을 짐작하지 말고 질문으로 묻는다" in text and "2027-11-30로 가정" not in text
    assert "정밀도 5단계:" in text and "분야: 건설 (construction)" in text and "construction(건설)" in text
    # m10: 도구 이름은 모델이 보는 꼴(__) 그대로
    for name in ("generate__extract_conditions", "ask__questionnaire", "ask__fill_answers", "generate__run"):
        assert name in text
    assert "generate.run" not in text and "ask.questionnaire" not in text
    assert "열린 프로그램: schedule" in text and "#1 시험 일정" in text and "준공 2027-03-05" in text
    assert "액티비티 2개" in text and "조건 0개" in text
    assert "고른 액티비티: A 작업 A" in text and "시작 2027-03-01" in text


def test_context_condition_counts_by_layer(session, admin_user, chat_id):
    from tests import schedules

    conds = [
        {"id": "base.no_cycle", "layer": "base", "kind": "no_cycle", "params": {}, "text": "고리 없음", "source": "기본 규칙"},
        {"id": "in.finish_by", "layer": "input", "kind": "finish_by", "params": {"date": "2027-12-31"},
         "text": "준공", "source": "프롬프트"},
        {"id": "d.t", "layer": "domain", "kind": "text_only", "params": {}, "text": "글", "source": "분야 규칙",
         "enabled": False},
    ]
    sid = schedules.store(session, schedules.sample(), conds)
    text = build_context(session, admin_user, chat_id, UiContext(None, sid, None))[0]["content"]
    assert "조건 3개 (기본 1 · 분야 1 · 내 규칙 0 · 입력 1) · 꺼짐 1개 · 자동 점검 안 됨 1개" in text


def test_context_says_when_the_schedule_cannot_be_read(session, admin_user, chat_id):
    text = build_context(session, admin_user, chat_id, UiContext(None, 999, "A2020"))[0]["content"]
    assert "#999 일정을 읽을 수 없습니다: 일정을 찾을 수 없습니다." in text and "고른 액티비티: A2020" in text


# ── 사용량(R12) ─────────────────────────────────────────────────────


async def test_usage_sums_the_turn(run, session):
    first = calls("schedule.read", {}, prompt_tokens=100, completion_tokens=10, cost=0.5)
    ev = await run(ScriptedLlm([first, reply("끝", prompt_tokens=200, completion_tokens=20, cost=0.25)]), "x")
    usage = next(e for e in ev if e.type == "usage").data
    assert usage == {"input_tokens": 300, "output_tokens": 30, "cost": 0.75, "calls": 2}
    row = session.query(WorkflowRun).one()
    assert (row.tokens, row.cost) == (330, 0.75)


async def test_usage_cost_is_null_when_no_reply_reports_it(run):
    ev = await run(ScriptedLlm([reply("끝", cost=None)]), "x")
    assert next(e for e in ev if e.type == "usage").data["cost"] is None


# ── 멈춤(R10) ───────────────────────────────────────────────────────


async def test_stop_flag_ends_the_turn_between_steps(run, session, chat_id):
    def stopper(args: Empty, ctx) -> Empty:
        turns.request_stop(chat_id)
        return Empty()

    claim = turns.claim(chat_id)
    try:
        with registered("stopper", stopper):
            llm = ScriptedLlm([calls("stopper", {}), calls("stopper", {}), reply("끝")])
            ev = await run(llm, "x")
    finally:
        turns.release(chat_id, claim)
    assert ev[-2].data == {"code": "stopped", "message": "중단했습니다."} and ev[-1].type == "done"
    assert len(llm.requests) == 1 and session.query(WorkflowRun).one().status == "stopped"
    assert [e.data["status"] for e in ev if e.type == "workflow"][-1] == "stopped"


async def test_closing_the_stream_mid_turn_stops_the_run(session, admin_user, chat_id):
    add_connection(session)
    llm = ScriptedLlm([calls("schedule.read", {}), reply("끝")])
    agen = run_turn(session, admin_user, chat_id, "x", NO_UI, llm=LlmClient(session, transport=llm.transport))
    async for ev in agen:
        if ev.type == "tool_start":
            break
    await agen.aclose()
    session.expire_all()
    row, step = session.query(WorkflowRun).one(), session.query(WorkflowStep).one()
    assert (row.status, step.status) == ("stopped", "stopped") and row.ended_at is not None


async def test_cancel_during_an_llm_call_stops_the_run(session, admin_user, chat_id):
    add_connection(session)
    llm = ScriptedLlm([calls("schedule.read", {}), reply("끝")])
    llm.on_request = lambda _body: setattr(llm, "delay_s", 5) if llm.bodies else None  # 둘째 호출만 늦다
    seen: list[str] = []

    async def consume():
        client = LlmClient(session, transport=llm.transport)
        async for ev in run_turn(session, admin_user, chat_id, "x", NO_UI, llm=client):
            seen.append(ev.type)

    task = asyncio.create_task(consume())

    async def second_call_started():
        while len(llm.bodies) < 2:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(second_call_started(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    session.expire_all()
    assert session.query(WorkflowRun).one().status == "stopped" and "done" not in seen


async def test_unexpected_error_ends_with_internal_error(run, session, monkeypatch, caplog):
    def broken(self, *args):
        word = "chat"
        raise RuntimeError(f"secret-{word}-text")  # 코드 줄(추적에 보임)에 글이 그대로 있지 않게

    monkeypatch.setattr(WorkflowLog, "step_finished", broken)
    ev = await run(ScriptedLlm([calls("schedule.read", {}), reply("끝")]), "x")
    assert ev[-2].data == {"code": "internal_error", "message": "처리 중 문제가 생겼습니다."} and ev[-1].type == "done"
    session.expire_all()
    assert session.query(WorkflowRun).one().status == "failed"
    assert "RuntimeError" in caplog.text and "broken" in caplog.text  # 종류와 위치만
    assert "secret-chat-text" not in caplog.text  # 예외 글(SQL 값·대화 글일 수 있음)은 남기지 않는다


# ── 도구가 내는 사건(바로 흘려보냄)·질문지·생성 결과 ──────────────────


async def test_tool_events_reach_the_stream_while_the_tool_runs(session, admin_user, chat_id):
    add_connection(session)
    gate = asyncio.Event()

    async def slow(args: Empty, ctx) -> Empty:
        ctx.emit(AgentEvent("card", {"kind": "progress"}))
        await gate.wait()
        return Empty()

    async def consume(agen) -> list[str]:
        seen = []
        async for ev in agen:
            seen.append(ev.type)
            if ev.type == "card":
                gate.set()  # 도구가 끝나기 전에 카드를 받았다
        return seen

    with registered("slow", slow):
        llm = ScriptedLlm([calls("slow", {}), reply("끝")])
        agen = run_turn(session, admin_user, chat_id, "x", NO_UI, llm=LlmClient(session, transport=llm.transport))
        seen = await asyncio.wait_for(consume(agen), 3)
    assert seen.index("tool_start") < seen.index("card") < seen.index("tool_end")


def _question(qid: str) -> dict:
    return {"id": qid, "group": "범위", "question": f"{qid} 는?", "assumption": f"{qid} 가정"}


async def test_questionnaire_tool_gets_the_chat_session_id(run, session, chat_id):
    args = {"purpose": "generate", "domain": "construction", "title": "일정 질문", "questions": [_question(x) for x in ("a", "b", "c")]}
    ev = await run(ScriptedLlm([calls("ask.questionnaire", args), reply("질문지에 답해 주세요.")]), "일정 만들어 줘")
    qid = next(e.data["id"] for e in ev if e.type == "questionnaire")
    assert session.get(QuestionnaireRecord, qid).chat_session_id == chat_id
    assert {"program": "questionnaire", "params": {"id": str(qid)}} in [e.data for e in ev if e.type == "open_window"]


async def test_questionnaire_submission_starts_a_turn_with_answers_and_assumptions(run, session, chat_id):
    questions = [
        Question(id="floors", group="범위", question="지상 몇 층인가요?", assumption="5층으로 가정합니다.",
                 options=[{"value": "5", "label": "5층"}, {"value": "10", "label": "10층"}]),
        Question(id="finish", group="날짜", question="준공 목표일은?", assumption="18개월 뒤로 가정합니다."),
    ]
    qid = qstore.create(session, purpose="generate", title="질문", questions=questions, prefilled=[],
                        domain="construction", level="L3", chat_session_id=chat_id)
    qstore.answer(session, qid, "floors", "10")
    qstore.submit(session, qid)
    llm = ScriptedLlm([reply("조건을 다시 뽑겠습니다.")])
    await run(llm, None, questionnaire_id=qid)
    role, content = stored(session, chat_id)[0]
    assert role == "user" and content == {
        "kind": "questionnaire_submitted", "questionnaire_id": qid,
        "answers": [{"question_id": "floors", "question": "지상 몇 층인가요?", "value": "10", "label": "10층"}],
        "assumed": [{"question_id": "finish", "question": "준공 목표일은?", "assumption": "18개월 뒤로 가정합니다."}],
    }
    user_text = llm.last_body["messages"][-1]["content"]
    assert "질문지 제출됨" in user_text and "- 지상 몇 층인가요?: 10층" in user_text
    assert "- 준공 목표일은?: 18개월 뒤로 가정합니다." in user_text
    session.expire_all()
    assert chats.get_chat(session, chat_id).title == "질문지 답"


async def test_generation_cards_stream_live_and_the_result_card_is_not_repeated(run, session, monkeypatch):
    gen = FakeLiner()
    script(gen, WBS_OK, SCHED_OK)
    monkeypatch.setattr(generate_tools, "client_for", lambda ctx: LlmClient(ctx.session, transport=gen.transport))
    args = {"domain": "construction", "level": "L3", "request": "5층 사무동", "facts": [START_FACT]}
    ev = await run(ScriptedLlm([calls("generate.run", args), reply("초안을 만들었습니다.")]), "일정 만들어 줘")
    names = types(ev)
    cards = [(i, e.data) for i, e in enumerate(ev) if e.type == "card"]
    stages = [i for i, data in cards if data["kind"] == "generation"]
    results = [(i, data) for i, data in cards if data["kind"] == "generation_result"]
    assert len(results) == 1  # 도구가 낸 카드 하나뿐(루프는 다시 만들지 않는다)
    (result, card), = results
    assert names.index("tool_start") < stages[0] < result < names.index("tool_end")
    assert card["ok"] is True and card["finish"] == "2027-04-05" and card["activity_count"] == 4
    assert len(gen.requests) == 2  # 도구 안의 LLM 호출은 도구의 가짜 Liner 로 갔다
    assert session.query(WorkflowStep).one().status == "done"


async def test_schedule_from_ui_is_remembered_by_the_session(run, session, chat_id, sid):
    llm = ScriptedLlm([reply("네"), calls("schedule.read", {}), reply("두 개")])
    await run(llm, "a", ui=UiContext("schedule", sid, None))
    await run(llm, "b")  # ui 에 일정이 없어도 대화의 일정을 쓴다
    session.expire_all()
    assert chats.get_chat(session, chat_id).schedule_id == sid
    assert session.query(WorkflowStep).one().status == "done"


def test_today_is_seoul_time(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 20, 15, 30, tzinfo=UTC).astimezone(tz)  # 서울은 이미 21일 0시 30분

    monkeypatch.setattr(context, "datetime", Clock)
    assert context.today() == date(2026, 11, 21) and context.today_text(date(2026, 11, 21)) == "2026-11-21 (토)"


def test_json_safe_replaces_lone_surrogates_everywhere():
    value = {"a\ud800": ["x\udfff", {"k": "ok"}], "n": 1, "f": None}
    assert json_safe(value) == {"a?": ["x?", {"k": "ok"}], "n": 1, "f": None}
    json.dumps(json_safe(value), ensure_ascii=False).encode("utf-8")


def test_default_llm_uses_the_session(session):
    assert isinstance(loop.default_llm(session), LlmClient)


# ══ Fix round 1 ════════════════════════════════════════════════════


def _lock_state(path: str) -> str:
    """다른 연결이 바로 쓰기를 잡을 수 있으면 "free"."""
    con = sqlite3.connect(path, timeout=0)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        return "free"
    except sqlite3.OperationalError:
        return "locked"
    finally:
        con.close()


def _gen_client(monkeypatch, gen: FakeLiner) -> None:
    monkeypatch.setattr(generate_tools, "client_for", lambda ctx: LlmClient(ctx.session, transport=gen.transport))


GEN_ARGS = {"domain": "construction", "level": "L3", "request": "5층 사무동", "facts": [START_FACT]}


# ── I1: 도구 안에서 부른 LLM 도 턴 사용량에 ──


async def test_usage_counts_llm_calls_made_inside_tools(run, session, monkeypatch):
    gen = FakeLiner()
    script(gen, WBS_OK, SCHED_OK)
    _gen_client(monkeypatch, gen)
    ev = await run(ScriptedLlm([calls("generate.run", GEN_ARGS), reply("끝")]), "일정 만들어 줘")
    usage = next(e for e in ev if e.type == "usage").data
    # 루프 2번 + 도구 안(WBS·초안) 2번. 가짜 답마다 12/5 토큰, 0.04
    assert usage == {"input_tokens": 48, "output_tokens": 20, "cost": pytest.approx(0.16), "calls": 4}
    row = session.query(WorkflowRun).one()
    assert row.tokens == 68 and row.cost == pytest.approx(0.16)


async def test_usage_leaves_out_earlier_turns_and_other_chats(run, session, admin_user):
    other = chats.create_chat(session, user_id=admin_user.id).id
    session.add(LlmCall(chat_session_id=other, purpose="normal", model="m", requested_model="m",
                        input_tokens=999, output_tokens=0, latency_ms=1, ok=True))
    session.commit()
    await run(ScriptedLlm([reply("하나")]), "a")
    ev = await run(ScriptedLlm([reply("둘", prompt_tokens=1, completion_tokens=2, cost=0.5)]), "b")
    assert next(e for e in ev if e.type == "usage").data == {
        "input_tokens": 1, "output_tokens": 2, "cost": 0.5, "calls": 1,
    }


async def test_failed_llm_call_counts_as_a_call(run):
    ev = await run(ScriptedLlm([calls("schedule.read", {}), FAIL("timeout")]), "x")
    assert next(e for e in ev if e.type == "usage").data == {
        "input_tokens": 12, "output_tokens": 5, "cost": 0.04, "calls": 2,
    }


# ── I2: 카드·질문지·승인 사건은 event 메시지로 저장 ──


async def test_tool_events_are_saved_as_event_messages_outside_the_model_history(run, session, chat_id):
    def emitter(args: Empty, ctx) -> Empty:
        ctx.emit(AgentEvent("card", {"kind": "progress-card", "n": 1}))
        ctx.emit(AgentEvent("questionnaire", {"id": 5}))
        ctx.emit(AgentEvent("open_window", {"program": "x", "params": {}}))  # 저장하지 않는다
        ctx.emit(AgentEvent("approval", {"id": 9}))
        return Empty()

    with registered("emitter", emitter):
        llm = ScriptedLlm([calls("emitter", {}), reply("끝"), reply("다음")])
        await run(llm, "x")
        await run(llm, "y")
    rows = stored(session, chat_id)
    assert [r for r, _ in rows] == [
        "user", "assistant", "event", "event", "event", "tool", "assistant", "user", "assistant",
    ]
    assert [c for r, c in rows if r == "event"] == [
        {"type": "card", "data": {"kind": "progress-card", "n": 1}},
        {"type": "questionnaire", "data": {"id": 5}},
        {"type": "approval", "data": {"id": 9}},
    ]
    for body in llm.bodies[1:]:  # 같은 턴의 다음 요청과 다음 턴의 요청 모두(지시문에는 공정률 프로그램 id "progress" 가 있다)
        assert "progress-card" not in json.dumps(body["messages"], ensure_ascii=False)
    assert [m["role"] for m in llm.bodies[2]["messages"][1:]] == ["user", "assistant", "tool", "assistant", "user"]


async def test_event_messages_do_not_use_up_the_history_window(run, session, chat_id):
    for i in range(29):
        chats.add_message(session, chat_id, "user" if i % 2 == 0 else "assistant", {"kind": "text", "text": f"말{i:03d}"})
    for _ in range(10):
        chats.add_message(session, chat_id, "event", {"type": "card", "data": {"kind": "x"}})
    session.commit()
    llm = ScriptedLlm([reply("네")])
    await run(llm, "마지막")
    texts = [m["content"] for m in llm.bodies[0]["messages"][1:]]
    assert len(texts) == 30 and texts[0] == "말000" and texts[-1] == "마지막"


async def test_events_are_written_after_the_tool_not_while_it_waits_on_the_llm(run, session):
    path = session.get_bind().url.database
    seen: list[str] = []
    inner = ScriptedLlm([reply("안쪽")], on_request=lambda _b: seen.append(_lock_state(path)))

    async def talker(args: Empty, ctx) -> Empty:
        ctx.emit(AgentEvent("card", {"kind": "progress"}))
        await asyncio.sleep(0.05)  # 루프가 사건을 받아 갈 틈(이때 쓰면 아래 LLM 호출 동안 잠금이 남는다)
        client = LlmClient(ctx.session, transport=inner.transport)
        await client.chat("light", [{"role": "user", "content": "x"}], chat_session_id=ctx.chat_session_id)
        return Empty()

    with registered("talker", talker):
        await run(ScriptedLlm([calls("talker", {}), reply("끝")]), "x")
    assert seen == ["free"]
    assert session.query(ChatMessage).filter(ChatMessage.role == "event").count() == 1


def test_history_skips_event_rows_between_a_call_and_its_result(session, admin_user, chat_id):
    add = lambda role, content: chats.add_message(session, chat_id, role, content)
    add("user", {"kind": "text", "text": "읽어 줘"})
    add("assistant", {"kind": "tool_calls", "text": "", "tool_calls": [{"id": "c1", "name": "schedule.read", "arguments": "{}"}]})
    add("event", {"type": "card", "data": {"kind": "x"}})
    add("tool", {"kind": "tool_result", "tool_call_id": "c1", "name": "schedule.read", "ok": True, "content": "{}"})
    session.commit()
    messages = build_context(session, admin_user, chat_id, NO_UI)[1:]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    assert messages[2]["content"] == "{}"  # 진짜 결과가 짝으로 남았다(채운 결과가 아님)


# ── I3: generate.run 안에서도 멈춤 ──


async def test_stop_during_generate_run_stops_before_its_next_llm_call(run, session, chat_id, monkeypatch):
    gen = ScriptedLlm()
    gen.on_request = lambda _b: turns.request_stop(chat_id) if len(gen.bodies) == 1 else None  # 둘째(초안) 요청 중
    script(gen, WBS_OK, SCHED_LATE_BY_3, SCHED_OK)
    _gen_client(monkeypatch, gen)
    llm = ScriptedLlm([calls("generate.run", {**GEN_ARGS, "conditions": [FINISH_BY.to_dict()]}), reply("끝")])
    claim = turns.claim(chat_id)
    try:
        ev = await run(llm, "일정 만들어 줘")
    finally:
        turns.release(chat_id, claim)
    assert len(gen.requests) == 2 and len(llm.requests) == 1  # 고침 요청도, 루프의 다음 요청도 없다
    assert ev[-2].data["code"] == "stopped" and ev[-1].type == "done"
    session.expire_all()
    step, row = session.query(WorkflowStep).one(), session.query(WorkflowRun).one()
    assert (step.status, row.status) == ("stopped", "stopped")
    out = json.loads(step.output_json)
    assert out["ok"] is False and isinstance(out["draft_id"], int)  # 1회차 초안(가장 나은 안)은 저장했다
    assert out["reason"] == "중단해서 지금까지 가장 나은 초안(1회차, 위반 1)을 저장했습니다."
    assert session.query(ScheduleDraft).count() == 1


async def test_generation_stopped_before_its_first_call_saves_nothing(session, admin_user):
    add_connection(session)
    gen = FakeLiner()
    ctx = ToolContext(session=session, user=admin_user, schedule_id=None, emit=lambda e: None,
                      stop_requested=lambda: True)
    r = await generate(ctx, LlmClient(session, transport=gen.transport), domain="construction", level="L3",
                       request="5층 사무동", facts=[START_FACT])
    assert (r.ok, r.draft_id, r.schedule, r.reason) == (False, None, None, "중단했습니다.")
    assert gen.requests == [] and session.query(ScheduleDraft).count() == 0


def test_tool_context_never_stops_by_default(session):
    assert ToolContext(session=session, user=None, schedule_id=None, emit=lambda e: None).stop_requested() is False


# ── I5: 턴을 시작하다 실패해도 error·done 으로 끝남 ──


async def test_unreadable_schedule_summary_does_not_break_the_turn(run, monkeypatch, sid, spy_llm):
    def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(context, "view_data", boom)
    ev = await run(spy_llm, "x", ui=UiContext("schedule", sid, None))
    assert types(ev) == ["text", "usage", "done"]
    assert f"- 대상 일정: #{sid} 일정을 읽을 수 없습니다." in spy_llm.last_messages_text


async def test_failure_while_starting_the_turn_ends_with_error_and_done(run, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(loop, "build_context", boom)
    llm = ScriptedLlm([reply("안 불림")])
    ev = await run(llm, "x")
    assert types(ev) == ["error", "done"] and ev[0].data["code"] == "internal_error" and llm.requests == []


# ── I6: 날짜 도우미(코드가 계산) ──


@pytest.mark.parametrize(
    "text, expected",
    [
        ("11월 30일 준공", [("11월 30일", date(2026, 11, 30))]),
        ("1월 10일 착공", [("1월 10일", date(2027, 1, 10))]),
        ("11월 20일", [("11월 20일", date(2026, 11, 20))]),  # 오늘은 아직 지나지 않았다
        ("2028년 3월 2일", [("2028년 3월 2일", date(2028, 3, 2))]),
        ("내년 11월 30일", [("내년 11월 30일", date(2027, 11, 30))]),
        ("올해 12월 1일", [("올해 12월 1일", date(2026, 12, 1))]),
        ("2월 29일", [("2월 29일", date(2028, 2, 29))]),  # 다음 윤년
        ("2월 30일", [("2월 30일", None)]),  # 없는 날
        ("12 월 1 일, 12월 1일", [("12 월 1 일", date(2026, 12, 1)), ("12월 1일", date(2026, 12, 1))]),
        ("내년 3월, 다음 달 초", []),  # 일이 없는 날짜는 계산하지 않는다
    ],
)
def test_month_days_resolve_to_the_nearest_future_date(text, expected):
    assert context.month_days(text, date(2026, 11, 20)) == expected


def test_date_helper_lines_in_the_context(session, admin_user, chat_id, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    chats.add_message(session, chat_id, "user", {"kind": "text", "text": "11월 30일 준공, 1월 10일 착공, 2월 30일"})
    session.commit()
    text = build_context(session, admin_user, chat_id, NO_UI)[0]["content"]
    assert "- '11월 30일' → 2026-11-30 (월)" in text and "- '1월 10일' → 2027-01-10 (일)" in text
    assert "- '2월 30일' → 없는 날짜입니다" in text


def test_date_helper_reads_the_request_and_the_answers_on_resume(session, admin_user, chat_id, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    chats.add_message(session, chat_id, "user", {"kind": "text", "text": "11월 30일 준공"})
    chats.add_message(session, chat_id, "assistant", {"kind": "text", "text": "질문지에 답해 주세요."})
    chats.add_message(session, chat_id, "user", {
        "kind": "questionnaire_submitted", "questionnaire_id": 1,
        "answers": [{"question_id": "s", "question": "착공일은?", "value": "12월 1일", "label": "12월 1일"}],
        "assumed": [],
    })
    session.commit()
    text = build_context(session, admin_user, chat_id, NO_UI)[0]["content"]
    assert "- '11월 30일' → 2026-11-30 (월)" in text and "- '12월 1일' → 2026-12-01 (화)" in text


# ── m1: 기다리는 동안 ping ──


async def test_pings_while_waiting_for_the_llm_and_a_tool(run, monkeypatch):
    monkeypatch.setattr(loop, "PING_INTERVAL_S", 0.05)

    async def slow(args: Empty, ctx) -> Empty:
        await asyncio.sleep(0.3)
        return Empty()

    with registered("slow", slow):
        llm = ScriptedLlm([calls("slow", {}), reply("끝")])
        llm.delay_s = 0.3
        ev = await run(llm, "x")
    names = types(ev)
    assert "ping" in names[: names.index("tool_start")]  # LLM 을 기다리는 동안
    assert "ping" in names[names.index("tool_start"): names.index("tool_end")]  # 도구를 기다리는 동안
    assert [n for n in names if n != "ping"] == [
        "workflow", "tool_start", "tool_end", "workflow", "text", "workflow", "usage", "done",
    ]


def test_ping_is_an_sse_comment():
    assert to_sse(AgentEvent("ping", {})) == ": ping\n\n"


# ── m3: 글을 저장한 뒤에 text 사건 ──


async def test_assistant_text_is_saved_before_its_text_event(session, admin_user, chat_id):
    add_connection(session)
    llm = ScriptedLlm([calls("schedule.read", {}, text="읽겠습니다."), reply("끝입니다.")])
    agen = run_turn(session, admin_user, chat_id, "x", NO_UI, llm=LlmClient(session, transport=llm.transport))
    seen = []
    async for ev in agen:
        if ev.type == "text":
            last = [c for r, c in stored(session, chat_id) if r == "assistant"][-1]
            seen.append(last["text"])
    assert seen == ["읽겠습니다.", "끝입니다."]


# ── m9: JSON 이 아닌 값도 글로 ──


def test_to_sse_turns_non_json_values_into_text():
    assert to_sse(AgentEvent("card", {"d": date(2027, 3, 1)})) == 'event: card\ndata: {"d": "2027-03-01"}\n\n'


# ── 답 잘림(finish_reason "length") ──


@pytest.mark.parametrize(
    ("text", "finish", "shown"),
    [
        ("긴 설명의 앞부분", "length", "긴 설명의 앞부분 (답이 길어 잘렸습니다)"),
        ("", "length", "(답이 길어 잘렸습니다)"),  # 글 없이 잘려도 알린다
        ("다 쓴 답", "stop", "다 쓴 답"),
    ],
)
async def test_text_answer_cut_by_length_says_so(run, session, chat_id, text, finish, shown):
    ev = await run(ScriptedLlm([reply(text, finish_reason=finish)]), "길게 설명해 줘")
    assert [e.data["text"] for e in ev if e.type == "text"] == [shown]
    assert stored(session, chat_id)[-1] == ("assistant", {"kind": "text", "text": shown})  # 저장한 글도 같다
    assert session.query(LlmCall).one().finish_reason == finish


async def test_waiting_workflow_resumes_across_questionnaire_turns(run, session, chat_id):
    ask_args = {
        "purpose": "generate",
        "title": "R&D 주제 확인",
        "questions": [
            {
                "id": "q_topic",
                "group": "주제",
                "question": "어떤 연구개발 과제인가요?",
                "assumption": "차세대 배터리 소재 개발",
            }
        ],
    }
    ev1 = await run(ScriptedLlm([calls("ask.questionnaire", ask_args), reply("주제를 알려 주세요.")]), "R&D 일정 만들어 줘")
    wf_ev1 = [e.data for e in ev1 if e.type == "workflow"][-1]
    wf = session.query(WorkflowRun).one()
    assert wf.status == "waiting" and wf.ended_at is None
    assert wf_ev1["run_id"] == wf.id and wf_ev1["status"] == "waiting"
    assert [(s["n"], s["tool"], s["status"]) for s in wf_ev1["steps"]] == [(1, "ask.questionnaire", "done")]
    tokens_after_turn1 = wf.tokens

    ev2 = await run(
        ScriptedLlm([calls("ask.questionnaire", {**ask_args, "domain": "rnd", "round": 2}), reply("세부 일정을 확인해 주세요.")]),
        "차세대 전고체 배터리 개발입니다",
    )
    wf_ev2 = [e.data for e in ev2 if e.type == "workflow"][-1]
    session.expire_all()
    runs = session.scalars(select(WorkflowRun).where(WorkflowRun.chat_session_id == chat_id)).all()
    assert len(runs) == 1 and runs[0].id == wf.id
    assert runs[0].status == "waiting" and runs[0].ended_at is None
    assert runs[0].tokens >= tokens_after_turn1
    assert wf_ev2["status"] == "waiting" and [s["n"] for s in wf_ev2["steps"]] == [1, 2]

    ev3 = await run(ScriptedLlm([calls("schedule.read", {}), reply("생성을 완료했습니다.")]), "진행해 주세요")
    wf_ev3 = [e.data for e in ev3 if e.type == "workflow"][-1]
    session.expire_all()
    wf_final = session.get(WorkflowRun, wf.id)
    assert wf_final.status == "done" and wf_final.ended_at is not None
    assert wf_ev3["run_id"] == wf.id and wf_ev3["status"] == "done"
    assert [(s["n"], s["tool"]) for s in wf_ev3["steps"]] == [
        (1, "ask.questionnaire"),
        (2, "ask.questionnaire"),
        (3, "schedule.read"),
    ]


# ══ 11-23 시나리오 재검증: 공정표 가져오기 단추(I1)·카드 중복(I2) ═══════════════

# 빈 칸 없는 가상 공정표 — 열 대응(columns)을 넘기면 가져오기에 LLM 이 들지 않는다.
IMPORT_CSV = (
    "ID,작업,기간,선행,시작,종료\n"
    "S,착공,0,,2027-03-02,\n"
    "A,가설 울타리,5,S,2027-03-02,2027-03-06\n"
    "B,터파기,4,A,,\n"
    "F,준공,0,B,,\n"
)
IMPORT_COLUMNS = {
    "id_col": "ID", "name_col": "작업", "wbs_col": None, "duration_col": "기간", "pred_col": "선행",
    "start_col": "시작", "finish_col": "종료", "resource_col": None, "start_constraint": False,
    "finish_constraint": False,
}


def _put_csv(session, text: str) -> int:
    """표 파일 한 줄과 원본을 바로 넣는다(파일 작업 없이)."""
    data = text.encode()
    sha = hashlib.sha256(data).hexdigest()
    raw_path(sha).parent.mkdir(parents=True, exist_ok=True)
    raw_path(sha).write_bytes(data)
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    row = FileRow(sha256=sha, name="가상_공정표.csv", ext="csv", kind="table", size=len(data), status="extracted",
                  uploaded_by=admin.id)
    session.add(row)
    session.commit()
    return row.id


def _button_text(fid: int) -> str:
    """대화 카드 [일정 초안으로 가져오기]가 보내는 글(frontend ScheduleFileCard.tsx)."""
    return f"네, 확인했으니 이 파일(#{fid})을 일정 초안으로 가져와 줘."


def _tool_ends(ev: list[AgentEvent]) -> list[tuple[str, bool]]:
    return [(e.data["tool"], e.data["ok"]) for e in ev if e.type == "tool_end"]


async def test_import_button_imports_even_when_the_model_drops_confirmed(run, session, monkeypatch):
    """I1: 단추가 보낸 글이면 모델이 confirmed 를 빼도 루프가 가져오기로 부른다. 분야·정밀도가 없으면 도구가
    되묻고(실패), 고쳐 부르면 가져온다 — 초안·승인 건은 하나."""
    gen = FakeLiner()
    _gen_client(monkeypatch, gen)
    fid = _put_csv(session, IMPORT_CSV)
    importing = {"file_id": fid, "sheet": None, "domain": "construction", "level": "L2", "columns": IMPORT_COLUMNS}
    llm = ScriptedLlm([
        calls("schedule.import", {"file_id": fid, "sheet": None}),  # confirmed 를 뺐다(run 24 의 인자)
        calls("schedule.import", importing, call_id="call_2"),  # 분야·정밀도를 넣었지만 confirmed 는 여전히 없다
        reply("승인함에서 승인을 기다립니다."),
    ])
    ev = await run(llm, _button_text(fid))
    assert _tool_ends(ev) == [("schedule.import", False), ("schedule.import", True)]
    assert "분야(domain)" in next(e.data["error"] for e in ev if e.type == "tool_end")
    assert len(session.scalars(select(ScheduleDraft)).all()) == 1 and gen.requests == []
    cards = [e.data["kind"] for e in ev if e.type == "card"]
    assert "schedule_file" not in cards and cards.count("generation_result") == 1
    assert [e.type for e in ev].count("approval") == 1
    steps = session.scalars(select(WorkflowStep).order_by(WorkflowStep.n)).all()
    assert all(json.loads(s.input_json)["confirmed"] is True for s in steps)  # 기록에도 실제로 부른 인자


async def test_import_button_runs_the_import_only_once_per_turn(run, session, monkeypatch):
    """I1: 한 턴에 같은 파일을 다시 가져오려 하면 실행하지 않고 실패 결과(초안·승인 건이 하나 더 생기지 않는다)."""
    _gen_client(monkeypatch, FakeLiner())
    fid = _put_csv(session, IMPORT_CSV)
    importing = {"file_id": fid, "domain": "construction", "level": "L2", "columns": IMPORT_COLUMNS}
    llm = ScriptedLlm([
        calls("schedule.import", importing),
        calls("schedule.import", importing, call_id="call_2"),
        calls("schedule.import", {**importing, "confirmed": True, "level": "L3"}, call_id="call_3"),
        reply("승인함에서 승인을 기다립니다."),
    ])
    ev = await run(llm, _button_text(fid))
    assert _tool_ends(ev) == [("schedule.import", True), ("schedule.import", False), ("schedule.import", False)]
    assert len(session.scalars(select(ScheduleDraft)).all()) == 1
    assert [e.type for e in ev].count("approval") == 1
    last_tool = json.loads(llm.last_body["messages"][-1]["content"])
    assert "이미 가져왔습니다" in last_tool["reflection"] and "인자를 고치" not in last_tool["reflection"]


@pytest.mark.parametrize(("output", "says", "never"), [
    ({"step": "drafted", "draft": {"draft_id": 7}}, "이미 가져왔습니다", None),
    ({"step": "asked", "draft": None, "questionnaire": {"id": 3}}, "질문지", "가져왔습니다"),
    ({"step": "drafted", "draft": {"draft_id": None}}, "초안을 만들지 못했습니다", "가져왔습니다"),
])
def test_repeat_import_refusal_says_what_really_happened(session, admin_user, chat_id, output, says, never):
    """I1(리뷰): 「이미 가져왔습니다」는 초안을 정말 만들었을 때만. 질문지만 열었거나 초안이 없으면 그대로 말한다."""
    turn = loop._Turn(session, admin_user, chat_id, NO_UI, None)
    args = {"file_id": 5, "confirmed": True, "domain": "construction", "level": "L2"}
    call = loop._Call("c1", "schedule.import", args, json.dumps(args))
    turn.note_import(call, registry.ToolResult(ok=True, output=output, error=None, ms=1))
    why = turn._import_again(call)
    assert why is not None and says in why
    if never:
        assert never not in why


async def test_repeated_check_in_a_turn_shows_one_card_and_never_imports(run, session, monkeypatch):
    """I2: 단추 글이 아닌 턴에서 확인을 되풀이하면 두 번째부터는 실행하지 않는다 — 카드 하나, 판단 LLM 두 번(첫 확인)뿐,
    가져오지 않는다(confirmed 를 채우지 않는다). 되돌려 주는 글은 「다시 부르지 말라」이고 「인자를 고치라」가 아니다."""
    gen = FakeLiner()
    gen.push(chat_body(json.dumps({"is_schedule": True, "reason": "공정표"})),
             chat_body(json.dumps({**IMPORT_COLUMNS, "blanks": "estimate", "questions": [], "reason": "빈 칸 없음"})))
    _gen_client(monkeypatch, gen)
    fid = _put_csv(session, IMPORT_CSV)
    llm = ScriptedLlm([
        calls("schedule.import", {"file_id": fid}),
        calls("schedule.import", {"file_id": fid}, call_id="call_2"),
        reply("액티비티 4개인 공정표입니다. [일정 초안으로 가져오기]를 누르거나 가져오라고 하시면 가져옵니다."),
    ])
    ev = await run(llm, "첨부한 공정표를 새 일정 초안으로 가져와 줘")
    assert _tool_ends(ev) == [("schedule.import", True), ("schedule.import", False)]
    assert [e.data["kind"] for e in ev if e.type == "card"] == ["schedule_file"]
    assert len(gen.requests) == 2 and session.scalars(select(ScheduleDraft)).all() == []
    last_tool = json.loads(llm.last_body["messages"][-1]["content"])
    assert "이미 확인" in last_tool["reflection"] and "인자를 고치" not in last_tool["reflection"]


async def test_import_button_fills_what_the_check_step_found(run, session, monkeypatch):
    """I1(재확인): 단추 턴에 모델이 confirmed=true 만 넣고 분야·정밀도·열 대응을 빼도, 이 대화의 확인 카드 값
    (열 대응·시트·카드에 보인 기본 분야·정밀도)으로 채워 한 번에 가져온다 — 실패 호출이 없다."""
    gen = FakeLiner()
    gen.push(chat_body(json.dumps({"is_schedule": True, "reason": "공정표"})),
             chat_body(json.dumps({**IMPORT_COLUMNS, "blanks": "estimate", "questions": [], "reason": "빈 칸 없음"})))
    _gen_client(monkeypatch, gen)
    fid = _put_csv(session, IMPORT_CSV)
    await run(ScriptedLlm([calls("schedule.import", {"file_id": fid}), reply("공정표입니다.")]), "첨부한 공정표를 확인해 줘.")
    llm = ScriptedLlm([
        calls("schedule.import", {"file_id": fid, "sheet": None, "confirmed": True}),  # run 43 의 인자
        reply("승인함에서 승인을 기다립니다."),
    ])
    ev = await run(llm, _button_text(fid))
    assert _tool_ends(ev) == [("schedule.import", True)]
    assert len(session.scalars(select(ScheduleDraft)).all()) == 1 and len(gen.requests) == 2  # 판단은 확인 때 두 번뿐
    assert [e.type for e in ev].count("approval") == 1
    step = session.scalars(select(WorkflowStep).order_by(WorkflowStep.id.desc())).first()
    args = json.loads(step.input_json)  # 기록에도 실제로 부른 인자
    assert (args["confirmed"], args["domain"], args["level"], args["columns"]) == (True, "general", "L1", IMPORT_COLUMNS)


async def test_an_import_waiting_in_the_approval_box_leaves_the_run_waiting(run, session, monkeypatch):
    """재확인 2(#49): 가져오기가 초안을 승인함에 냈고 승인을 기다리면 실행은 「완료」가 아니라 승인 대기(waiting)다 —
    생성 흐름(out.submit_change)과 같다."""
    _gen_client(monkeypatch, FakeLiner())
    fid = _put_csv(session, IMPORT_CSV)
    importing = {"file_id": fid, "confirmed": True, "domain": "construction", "level": "L2", "columns": IMPORT_COLUMNS}
    ev = await run(ScriptedLlm([calls("schedule.import", importing), reply("승인함에서 승인을 기다립니다.")]), _button_text(fid))
    assert [e.type for e in ev].count("approval") == 1
    assert session.scalars(select(WorkflowRun)).one().status == "waiting"
    assert [e.data for e in ev if e.type == "workflow"][-1]["status"] == "waiting"


async def test_import_button_keeps_what_the_model_did_give(run, session, monkeypatch):
    """I1(재확인): 모델이 넣은 값은 그대로 두고 빠진 칸만 채운다."""
    gen = FakeLiner()
    gen.push(chat_body(json.dumps({"is_schedule": True, "reason": "공정표"})),
             chat_body(json.dumps({**IMPORT_COLUMNS, "blanks": "estimate", "questions": [], "reason": "빈 칸 없음"})))
    _gen_client(monkeypatch, gen)
    fid = _put_csv(session, IMPORT_CSV)
    await run(ScriptedLlm([calls("schedule.import", {"file_id": fid}), reply("공정표입니다.")]), "첨부한 공정표를 확인해 줘.")
    llm = ScriptedLlm([calls("schedule.import", {"file_id": fid, "domain": "construction"}), reply("끝")])
    ev = await run(llm, _button_text(fid))
    assert _tool_ends(ev) == [("schedule.import", True)]
    step = session.scalars(select(WorkflowStep).order_by(WorkflowStep.id.desc())).first()
    args = json.loads(step.input_json)
    assert (args["domain"], args["level"], args["columns"]) == ("construction", "L1", IMPORT_COLUMNS)


# ── 같은 호출이 같은 까닭으로 되풀이해 실패하면 세 번째는 실행하지 않는다(I1 재확인) ──


@pytest.fixture
def failing_tool():
    """도구 'stubborn' {n}: 부를 때마다 센다. n 이 0 이면 늘 같은 까닭으로 실패, -1 이면 역할 거절(현장 관리자), 아니면 성공."""
    seen: list[int] = []

    def stubborn(args: SpyIn, ctx) -> Empty:
        seen.append(args.n)
        if args.n == 0:
            raise ToolError("n 이 0 이면 안 됩니다.")
        if args.n == -1:
            raise ToolError(FIELD_READ_ONLY_MESSAGE)
        return Empty()

    with registered("stubborn", stubborn):
        yield seen


async def test_third_identical_failing_call_is_not_run(run, session, failing_tool):
    llm = ScriptedLlm([
        calls("stubborn", {"n": 0}),
        calls("stubborn", {"n": 0}, call_id="call_2"),
        calls("stubborn", {"n": 0}, call_id="call_3"),
        reply("멈춥니다."),
    ])
    ev = await run(llm, "해 줘")
    assert failing_tool == [0, 0]  # 세 번째는 실행하지 않았다
    assert _tool_ends(ev) == [("stubborn", False)] * 3
    third = json.loads(llm.bodies[3]["messages"][-1]["content"])
    assert "n 이 0 이면 안 됩니다." in third["error"] and "인자를 바꿔" in third["error"]
    assert third["reflection"] == third["error"]
    assert ev[-1].type == "done" and not any(e.type == "error" for e in ev)


async def test_a_refused_call_asked_again_ends_the_turn_without_asking_the_model_again(run, session, failing_tool):
    """I1(재확인 리뷰): 같은 실패 호출을 14번 되풀이하는 모델 — 실패 둘·거절 하나 뒤, 거절한 호출이 또 오면 모델을 더 부르지
    않고 턴을 끝낸다(LLM 4번). 끝 까닭은 단계 한도가 아니라 되풀이 실패(repeated_failure), 사용자에게는 코드가 쓴 글."""
    llm = ScriptedLlm([calls("stubborn", {"n": 0}, call_id=f"c{i}") for i in range(14)] + [reply("안 불림")])
    ev = await run(llm, "해 줘")
    assert len(llm.requests) == 4
    assert failing_tool == [0, 0]
    assert _tool_ends(ev) == [("stubborn", False)] * 3
    err = next(e.data for e in ev if e.type == "error")
    assert (err["code"], err["tool"]) == ("repeated_failure", "stubborn")
    assert err["message"] == "「stubborn」 — 같은 요청이 같은 까닭으로 거듭 실패해 멈췄습니다. 까닭: n 이 0 이면 안 됩니다."
    assert ev[-1].type == "done" and not any(e.type == "text" for e in ev)
    run_row = session.scalars(select(WorkflowRun)).one()
    assert run_row.status == "failed"
    end = session.scalars(select(TraceEvent).where(TraceEvent.kind == "end")).one()
    assert (end.label, end.error) == ("failed", err["message"])


async def test_repeated_role_refusals_say_the_account_cannot_do_it(run, session, failing_tool):
    """I1(재확인 리뷰): 두 번의 실패가 역할 거절이면 「인자를 바꾸라」고 하지 않고 이 계정으로는 할 수 없다고 한다."""
    llm = ScriptedLlm([calls("stubborn", {"n": -1}, call_id=f"c{i}") for i in range(5)] + [reply("안 불림")])
    ev = await run(llm, "새 프로젝트 하나 만들어 줘")
    assert len(llm.requests) == 4 and failing_tool == [-1, -1]
    third = json.loads(llm.bodies[3]["messages"][-1]["content"])
    assert "인자를 바꿔" not in third["error"] and "이 계정으로는 할 수 없" in third["error"]
    err = next(e.data for e in ev if e.type == "error")
    assert err["code"] == "repeated_failure" and "인자" not in err["message"]
    assert err["message"] == f"「stubborn」 — 이 계정으로는 할 수 없는 요청이라 거듭 거절되어 멈췄습니다. 까닭: {FIELD_READ_ONLY_MESSAGE}"


async def test_a_call_with_changed_arguments_still_runs(run, session, failing_tool):
    llm = ScriptedLlm([
        calls("stubborn", {"n": 0}),
        calls("stubborn", {"n": 0}, call_id="call_2"),
        calls("stubborn", {"n": 1}, call_id="call_3"),
        reply("됐습니다."),
    ])
    ev = await run(llm, "해 줘")
    assert failing_tool == [0, 0, 1]
    assert _tool_ends(ev) == [("stubborn", False), ("stubborn", False), ("stubborn", True)]


async def test_repeated_failures_are_counted_per_turn(run, session, failing_tool):
    await run(ScriptedLlm([calls("stubborn", {"n": 0}), calls("stubborn", {"n": 0}, call_id="c2"), reply("x")]), "1")
    await run(ScriptedLlm([calls("stubborn", {"n": 0}), reply("y")]), "2")
    assert failing_tool == [0, 0, 0]  # 다음 턴의 첫 호출은 실행한다


CARD_TSX = Path(__file__).resolve().parents[3] / "frontend/src/programs/chat/cards/ScheduleFileCard.tsx"


@pytest.mark.skipif(not CARD_TSX.exists(), reason="frontend 폴더가 없는 환경")
def test_the_card_button_sends_the_text_the_loop_recognizes():
    """I1: 카드 단추가 보내는 글(ScheduleFileCard.tsx)과 루프가 알아보는 글(IMPORT_BUTTON)이 같다."""
    sent = re.search(r"send\(`([^`]+)`\)", CARD_TSX.read_text(encoding="utf-8")).group(1)
    assert loop.IMPORT_BUTTON.fullmatch(sent.replace("${fileId}", "7")).group(1) == "7"
    assert loop.IMPORT_BUTTON.fullmatch("이 파일로 일정 초안을 만들어 줘(#7)") is None
