"""에이전트 루프: 도구 호출 왕복·사건 차례·워크플로우 기록·멈춤·대화 기록 창·사용량."""

import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel
from sqlalchemy import select

import app.tools.generate as generate_tools
from app.agent import context, loop, turns
from app.agent.context import UiContext, build_context
from app.agent.events import AgentEvent, json_safe
from app.agent.loop import run_turn
from app.agent.workflow_log import WorkflowLog
from app.llm.client import LlmClient
from app.store import chats
from app.store import questionnaires as qstore
from app.store.questionnaires import Question
from app.store.tables import (
    ChatMessage,
    LlmCall,
    QuestionnaireRecord,
    User,
    WorkflowRun,
    WorkflowStep,
)
from app.tools import registry
from tests.gen_doubles import SCHED_OK, START_FACT, WBS_OK, script
from tests.llm_doubles import FakeLiner, add_connection
from tests.loop_doubles import FAIL, ScriptedLlm, calls, raw_call, reply
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
        "run_id": run_id, "n": 1, "call_id": "call_1", "tool": "schedule.read", "program": "schedule",
        "arguments": "{}",
    }
    assert end["ok"] is True and end["error"] is None and end["tool"] == "schedule.read" and end["ms"] >= 0
    assert (end["run_id"], end["n"], end["call_id"]) == (run_id, 1, "call_1")
    step = {"n": 1, "tool": "schedule.read", "program": "schedule"}
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
    assert (step.n, step.tool, step.program, step.status) == (1, "schedule.read", "schedule", "done")
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
    assert json.loads(tool_messages[1]["content"]) == {"error": "대상 일정이 없습니다."}
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
    assert "오늘: 2026-11-20 (금) (Asia/Seoul)" in text
    assert "연·월·일이 모두 적힌 날짜만" in text and "2027-11-30로 가정" in text and "YYYY-MM-DD" in text
    assert "정밀도 5단계:" in text and "분야: 건설 (construction)" in text and "construction(건설)" in text
    assert "generate.extract_conditions" in text and "ask.questionnaire" in text and "generate.run" in text
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
    def broken(self, step, result):
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
    args = {"purpose": "generate", "title": "일정 질문", "questions": [_question(x) for x in ("a", "b", "c")]}
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
