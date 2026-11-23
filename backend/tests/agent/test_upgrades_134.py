"""에이전트 고도화 #1(스킬 저장·재실행), #3(동적 가이드·대화 압축), #4(자가 점검·자가 수정) 시험."""

import json

import pytest
from sqlalchemy import select

from app.agent import context
from app.agent.context import UiContext, build_context
from app.agent.loop import run_turn
from app.llm.client import LlmClient
from app.programs.devconsole import service as devconsole_service
from app.store import chats, skills
from app.store.tables import TraceEvent, User, WorkflowRun
from app.tools import registry
from tests.llm_doubles import FakeLiner, add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply
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
    add_connection(session)

    async def go(llm: FakeLiner, text: str, *, ui: UiContext = NO_UI, max_steps: int = 12):
        client = LlmClient(session, transport=llm.transport)
        return [e async for e in run_turn(session, admin_user, chat_id, text, ui, llm=client, max_steps=max_steps)]

    return go


# ── #1. 워크플로우 → 스킬 저장 및 재실행 ──────────────────────────────


async def test_skill_save_match_replay_and_devconsole(run, session, admin_user):
    # 1) 워크플로우 실행 1회 생성
    await run(ScriptedLlm([calls("schedule.read", {}), reply("읽었습니다")]), "골조 지연 만회 분석해 줘")
    wf_run = session.scalars(select(WorkflowRun)).one()

    # 2) 스킬로 저장
    saved = skills.create_from_run(
        session,
        run_id=wf_run.id,
        user_id=admin_user.id,
        name="골조 지연 만회",
        triggers=["골조", "지연", "만회"],
    )
    assert saved.use_count == 0
    assert saved.steps_json[0]["tool"] == "schedule.read"

    # 3) 유사 요청 시 자동 매칭 + notice + 시스템 프롬프트 주입 + DevConsole skill_matched
    # (A6: 기준 3점, 흔한 말 「지연」은 점수에 들지 않는다 — 원래 요청과 거의 같은 말이어야 붙는다)
    llm2 = ScriptedLlm([calls("schedule.read", {}), reply("스킬대로 확인했습니다")])
    events = await run(llm2, "골조 지연 만회 분석 다시 해 줘")

    notices = [e.data["text"] for e in events if e.type == "notice"]
    assert any("골조 지연 만회" in m for m in notices)
    sys_msg = llm2.bodies[0]["messages"][0]["content"]
    assert "## 매칭된 스킬: 골조 지연 만회" in sys_msg

    session.refresh(saved)
    assert saved.use_count == 1

    # DevConsole 턴 뷰에서 skill 노드가 past + edges_lit 에 skill_matched 포함
    skill_ev = session.scalars(
        select(TraceEvent).where(TraceEvent.kind == "skill").order_by(TraceEvent.id.desc())
    ).first()
    assert skill_ev is not None and "골조 지연 만회" in skill_ev.label
    view = devconsole_service.get_turn(session, skill_ev.turn_id)
    skill_node = next(n for n in view.structure.nodes if n.key == "skill")
    assert skill_node.state == "past" and skill_node.count == 1
    assert "skill_matched" in view.structure.edges_lit


# ── #3. 동적 가이드 선택 + 오래된 대화 압축 ───────────────────────────


def test_dynamic_guide_selection_shrinks_prompt():
    all_guides = context.select_guides("안녕", NO_UI, has_files=False)
    delay_guides = context.select_guides("골조가 4일 밀렸어", NO_UI, has_files=False)
    assert delay_guides == ["delay"]
    assert len(delay_guides) < len(all_guides)
    assert len(context.system_prompt(delay_guides)) < len(context.system_prompt(all_guides))


def test_history_compaction_summarizes_older_messages(session, admin_user, chat_id):
    for i in range(36):
        role = "user" if i % 2 == 0 else "assistant"
        chats.add_message(session, chat_id, role, {"kind": "text", "text": f"이전대화{i:02d}"})
    session.commit()
    msgs = build_context(session, admin_user, chat_id, NO_UI)
    sys_text = msgs[0]["content"]
    assert "## 이전 대화 요약" in sys_text
    assert "이전대화00" in sys_text
    assert len(msgs) == 1 + 30


# ── #4. 도구 실패 자가 점검 + DevConsole self_corrected ───────────────


async def test_self_reflection_and_self_corrected_signal(run, session):
    # 첫 호출 schedule.read 는 대상 일정 없어 실패 → 두 번째 호출 ok_tool 로 성공
    def ok_tool(args: Empty, ctx) -> Empty:
        return Empty()

    with registered("ok_tool", ok_tool):
        llm = ScriptedLlm([
            calls("schedule.read", {}, call_id="c1"),
            calls("ok_tool", {}, call_id="c2"),
            reply("대안으로 확인했습니다"),
        ])
        await run(llm, "일정 확인")

    tool_msgs = [m for m in llm.bodies[1]["messages"] if m["role"] == "tool"]
    err_obj = json.loads(tool_msgs[0]["content"])
    assert "error" in err_obj and "reflection" in err_obj

    last_ev = session.scalars(select(TraceEvent).order_by(TraceEvent.id.desc())).first()
    view = devconsole_service.get_turn(session, last_ev.turn_id)
    assert "self_corrected" in view.structure.edges_lit
