"""통화 통로와 거는 통화 일꾼(Task 88). 음성은 가짜(SimulatedVoice)뿐이고 시각은 정해 둔 값이다 — 실제 SDK·모델·망·시계가 없다.

통화 한 통은 `runner.run_one(call_id, now=…)` 로 직접 돌리고, 예약·줄의 흐름은 `runner.tick(now=…)` 한 바퀴씩 돌린다.
일꾼 고리(start)는 conftest 가 끈다 — 고리를 띄우는 시험은 끄는 설정을 보는 것 하나뿐이고, 그것도 고리를 돌리지 않는다.
"""

import ast
import asyncio
import importlib
import logging
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import app
from app.outreach import redact
from app.outreach.harness import gate, tools
from app.outreach.harness.toolsets import ALL
from app.outreach.harness.types import CALL_RESULTS, TOOL_REFUSALS, Actor, Delivered
from app.outreach.voice import call_run, instructions, numbers, runner
from app.outreach.voice import session as voice_session
from app.outreach.voice.simulated import (
    Busy,
    Crash,
    Hangup,
    Hold,
    NoAnswer,
    Opening,
    Say,
    Silence,
    SimulatedVoice,
    Tool,
)
from app.programs.notify_settings import voice as voice_settings_api
from app.security import crypto
from app.store import outreach
from app.store.tables_outreach import (
    DoNotContactNumber,
    OutreachCall,
    OutreachUsage,
    VoiceSettings,
)
from tests.outreach.harness.test_gate import (
    MONDAY,
    OFF,
    PHONE,
    WORK,
    call,
    connect,
    person,
)
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)

pytestmark = pytest.mark.usefixtures("time_guard")

AGENT_NUMBER = "07000000100"  # 가상 AI 전화 번호
USER = Actor("user", 1, "김공정", "user")
RUNNER_RULES = {"silence", "time_limit", "hangup_by_person", "recheck_before_dial", "call_result", "server_restart"}
VOICE = Path(app.__file__).parent / "outreach" / "voice"


# ── 도우미 ──────────────────────────────────────────────────────────


@pytest.fixture
def world(session, sid):
    """기본 알림 연결(ok·시험 모드 끔·승인 받기) + 음성 설정(가상 키·AI 전화 번호) + 연락처 한 사람."""
    conn = connect(session)
    session.add(VoiceSettings(connection_id=conn.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              status="ok"))
    who = person(session, sid)
    session.commit()
    return type("World", (), {"conn": conn, "who": who, "sid": sid})


def queued(session, who, **over) -> OutreachCall:
    """나가는 문이 지나보내 줄에 넣은 통화(queued) 한 줄."""
    row = call(session, who, **{"status": "queued", "claimed_at": WORK, "send_mode": "manual",
                                "questions_json": ["3층 타설 날짜"], **over})
    session.commit()
    return row


def reread(session, row) -> OutreachCall:
    session.expire_all()
    return session.get(OutreachCall, row.id)


def rules(session, row) -> list[tuple[str, str, str]]:
    return [(e["rule"], e["verdict"], e["detail"]) for e in reread(session, row).harness_json]


def own_rules(session, row) -> list[str]:
    return [rule for rule, _, _ in rules(session, row) if rule in RUNNER_RULES]


async def place(row, script, now=WORK, **options) -> SimulatedVoice:
    sim = SimulatedVoice(script, **options)
    with voice_session.pinned(sim):
        await runner.run_one(row.id, now=now)
    return sim


def plain_call():
    return [Say("peer", "네 맞습니다", t=2), Hangup("peer")]


# ── 도구는 하네스의 것 하나 ────────────────────────────────────────────


async def test_runner_uses_shared_toolbox(session, world, monkeypatch):
    seen = []
    real = tools.Toolbox.call

    async def spy(self, name, args):
        seen.append((type(self), name, self.caller_class, self.medium))
        return await real(self, name, args)

    monkeypatch.setattr(tools.Toolbox, "call", spy)
    row = queued(session, world.who)
    script = [Say("peer", "네 맞습니다", t=2),
              Tool("record_answer", {"question": "3층 타설 날짜", "answer": "다음 주 월요일", "quote": "월요일"}),
              Say("peer", "월요일입니다", t=4), Tool("no_such_tool", {}), Hangup("peer")]

    sim = await place(row, script)

    assert seen == [(tools.Toolbox, "record_answer", "outbound", "call"), (tools.Toolbox, "no_such_tool", "outbound", "call")]
    assert sim.tool_results[0].result == {"ok": True} and sim.tool_results[1].result == {"error": tools.ERR_TOOL}
    assert [t.name for t in sim.calls[0].spec.tools] == list(ALL)  # outbound·call 묶음 = 열 개 + end_call·confirm_person
    # voice/ 안에는 도구 구현이 없다(도구 이름의 함수·Toolbox 같은 클래스를 두지 않는다)
    for path in VOICE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.name.lstrip("_") for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}
        assert not names & set(ALL), path.name
        assert "Toolbox" not in {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}, path.name


# ── 모델에게 번호가 가지 않는다 ──────────────────────────────────────────


async def test_call_spec_text_has_no_number(session, world):
    row = queued(session, world.who, purpose="타설 확인 — 사무실 010-0000-0188 로도 연락 가능",
                 questions_json=["010 0000 0188 번호가 맞나요", "3층 타설 날짜"], avoid_json=["금액 이야기"])

    sim = await place(row, plain_call())

    spec = sim.calls[0].spec
    assert spec.to_number == SENTINEL_DIGITS and spec.from_number == AGENT_NUMBER  # 번호는 코드가 붙인다
    assert sim.leaks() == []
    for label, text in sim.model_saw():
        digits = "".join(ch for ch in text if ch.isdigit())
        assert SENTINEL_DIGITS[1:] not in digits and "0000188" not in digits, label
    assert "타설 확인" in spec.instructions and "3층 타설 날짜" in spec.instructions
    assert spec.max_seconds == outreach.limits(world.conn).max_call_seconds


async def test_spec_that_would_carry_the_callees_number_is_not_dialled(session, world):
    """가리개가 놓치는 꼴로 상대 번호가 목적에 들어 있으면 CallSpec 이 만들어지지 않는다 — 걸지 않고 초안으로."""
    row = queued(session, world.who, purpose="010 단지 0000동 0199호 확인")

    sim = await place(row, plain_call())

    assert sim.dialed == []
    back = reread(session, row)
    assert back.status == "draft" and back.fail_reason == runner.SPEC_REFUSED
    assert ("recheck_before_dial", "blocked", "precheck") in rules(session, row)


def test_instructions_have_the_shared_rules_and_the_call_lines_but_no_number():
    text = instructions.outbound("가람 현장", "박현장 010-0000-0199", "철근 반장", "가람철근", "타설 일정 확인",
                                 ["3층 타설 날짜", "연락처 010-0000-0199 맞나요"], ["금액"], "ko")
    from app.outreach.harness import rules_text

    for line in rules_text.FIXED.values():
        assert line in text
    assert rules_text.scope_paragraph("outbound") in text
    assert "end_call" in text and "voicemail" in text and "redirect" in text and "find_contact" in text
    assert not voice_session.has_phone(text, SENTINEL_PHONE)
    assert "3층 타설 날짜" in text and "금액" in text


# ── 받아쓰기 ────────────────────────────────────────────────────────


async def test_transcript_is_stored_with_numbers_hidden(session, world):
    row = queued(session, world.who)
    script = [Say("peer", f"네, 제 번호는 {SENTINEL_PHONE} 이에요", t=2), Say("agent", "알겠습니다", t=3), Hangup("peer")]

    await place(row, script)

    lines = reread(session, row).transcript_json
    assert [line["role"] for line in lines] == ["agent", "peer", "agent"]  # 우리 말과 상대 말을 가른다
    assert lines[0]["text"].startswith("안녕하세요") and lines[1]["t"] == 2
    assert redact.PHONE_MASK in lines[1]["text"]
    digits = "".join(ch for line in lines for ch in line["text"] if ch.isdigit())
    assert SENTINEL_DIGITS[1:] not in digits


async def test_opening_that_does_not_disclose_is_said_again_once(session, world):
    row = queued(session, world.who)

    sim = await place(row, [Opening("안녕하세요 박현장님"), Say("peer", "네", t=3), Hangup("peer")])

    assert sim.said == [sim.calls[0].spec.first_line]
    assert reread(session, row).status == "completed"


async def test_opening_that_denies_being_an_ai_ends_the_call(session, world, monkeypatch):
    """discloses 는 낱말만 본다 — 「AI 가 아니고 기록되지 않습니다」 같은 부정은 밝힌 것이 아니다. 다시 말하게 해도 같으면 끊는다."""
    row = queued(session, world.who)
    denial = "저는 AI 가 아니고 이 통화는 기록되지 않습니다"

    sim = SimulatedVoice([Opening(denial), Say("peer", "네", t=3), Hangup("peer")])
    original = sim.place

    async def place_once(spec, handlers):  # say 를 받아도 모델이 다시 부정한다
        class Wrap:
            def __getattr__(self, name):
                return getattr(handlers, name)

            async def on_transcript(self, role, text, t):
                await handlers.on_transcript(role, denial if role == "agent" else text, t)

        await original(spec, Wrap())

    sim.place = place_once
    finished = []
    monkeypatch.setattr(call_run, "after_call", lambda call_id: finished.append(call_id) or asyncio.sleep(0))
    with voice_session.pinned(sim):
        await runner.run_one(row.id, now=WORK)

    back = reread(session, row)
    # 밝히지 않은 통화는 「통화됨」이 아니다 — failed, 사용량·통화 뒤 일 없음
    assert sim.ended == [("agent", 0)] and (back.status, back.fail_reason) == ("failed", call_run.NOT_DISCLOSED)
    assert ("call_result", "blocked", "failed") in rules(session, row) and finished == []
    assert session.scalars(select(OutreachUsage).where(OutreachUsage.ref_id == row.id)).all() == []


# ── 상태 ────────────────────────────────────────────────────────────


async def test_states_dialing_in_call_completed(session, world):
    row = queued(session, world.who)
    seen = []

    class Peek(SimulatedVoice):
        async def place(self, spec, handlers):
            seen.append(reread(session, row).status)
            await super().place(spec, handlers)

    sim = Peek([Say("peer", "네", t=3), Hold(), Say("peer", "그럼요", t=40), Hangup("peer")])
    with voice_session.pinned(sim):
        task = asyncio.create_task(runner.run_one(row.id, now=WORK))
        await sim.wait_held()
        during = reread(session, row)
        assert (during.status, during.started_at is not None) == ("in_call", True)
        assert runner.live() == 1 and runner.status()["live"] == 1
        sim.release()
        assert await asyncio.wait_for(task, 5) == "completed"

    back = reread(session, row)
    assert seen == ["dialing"]
    assert (back.status, back.duration_s) == ("completed", 40)
    assert back.ended_at is not None and back.claimed_at is not None
    usage = session.scalars(select(OutreachUsage).where(OutreachUsage.ref_id == row.id)).all()
    assert [(u.kind, u.ref_kind, u.seconds, u.cost) for u in usage] == [("voice_model", "call", 40, None)]
    assert runner.live() == 0 and runner.status()["last_call_at"] is not None


async def test_after_call_hook_runs_once_per_finished_call(session, world, monkeypatch):
    finished = []

    async def hook(call_id):
        finished.append(call_id)

    monkeypatch.setattr(call_run, "after_call", hook)
    row = queued(session, world.who)
    await place(row, plain_call())
    assert finished == [row.id]


# ── 침묵 · 최대 시간 ────────────────────────────────────────────────────


async def test_silence_two_checks_then_end(session, world):
    row = queued(session, world.who)

    sim = await place(row, [Say("peer", "네", t=1), Silence(120), Hangup("peer")])

    assert sim.said.count("여보세요, 들리시나요?") == 2
    assert sim.said[-1] == "잘 들리지 않아 통화를 마치겠습니다"
    assert sim.ended == [("agent", 46)]  # 1초에 말하고 15초씩 세 번
    assert own_rules(session, row).count("silence") == 3
    assert reread(session, row).status == "completed"


async def test_peer_speech_resets_the_silence_count(session, world):
    row = queued(session, world.who)
    script = [Say("peer", "네", t=1), Silence(20), Say("peer", "여기 있어요", t=30), Silence(20),
              Say("peer", "네네", t=62), Hangup("peer")]

    sim = await place(row, script)

    # 16초·45초·60초에 확인 — 30초에 상대가 말해 셈이 다시 시작됐으므로 60초는 끊는 셋째가 아니라 둘째다
    assert sim.said.count("여보세요, 들리시나요?") == 3 and "잘 들리지 않아 통화를 마치겠습니다" not in sim.said
    assert sim.ended == [("peer", 62)]


async def test_max_time_wrap_up_then_hangup(session, world):
    world.conn.limits_json = {"max_call_seconds": 60}
    session.commit()
    row = queued(session, world.who)
    script = [Say("peer", f"말 {n}", t=n * 10) for n in range(1, 10)] + [Hangup("peer")]

    sim = await place(row, script)

    assert sim.said == ["시간이 다 되어 정리하겠습니다. 담당자가 다시 연락드리겠습니다"]
    assert sim.ended == [("agent", 60)] and sim.calls[0].overran is False
    assert own_rules(session, row).count("time_limit") == 2
    assert reread(session, row).duration_s == 60


async def test_model_turns_and_tool_calls_are_capped(session, world, monkeypatch):
    monkeypatch.setattr(call_run, "MAX_TOOL_CALLS", 3)
    monkeypatch.setattr(call_run, "MAX_TURNS", 6)
    row = queued(session, world.who)
    many_tools = [Tool("confirm_person", {"is_person": True}) for _ in range(5)]
    sim = await place(row, [Say("peer", "네", t=1), *many_tools, Hangup("peer")])
    assert [r.result for r in sim.tool_results] == [{"ok": True}] * 3 + [{"error": call_run.TOOL_CAP}]
    assert sim.ended[0][0] == "agent"

    row2 = queued(session, world.who)
    sim2 = await place(row2, [Say("peer", f"말 {n}", t=n) for n in range(1, 12)] + [Hangup("peer")])
    assert sim2.ended[0][0] == "agent" and len(reread(session, row2).transcript_json) == 6


# ── 받지 않음 · 다시 걸기 ─────────────────────────────────────────────────


async def test_no_answer_is_not_redialed_unless_delegated_once(session, world):
    row = queued(session, world.who)
    await place(row, [NoAnswer()])

    back = reread(session, row)
    assert back.status == "no_answer" and back.fail_reason == call_run.FAILED_TEXT["no_answer"]
    assert ("call_result", "noted", "no_answer") in rules(session, row)
    assert session.scalars(select(OutreachCall.id)).all() == [row.id]  # 승인 받기 — 다시 걸 줄이 없다

    world.conn.agent_call = "delegate"
    session.commit()
    second = queued(session, world.who)
    await place(second, [NoAnswer()])
    retry = session.scalars(select(OutreachCall).where(OutreachCall.retry_of == second.id)).all()
    assert len(retry) == 1 and retry[0].status == "scheduled" and retry[0].auto_retry_used

    await place(retry[0], [NoAnswer()])  # 줄에 넣지 않은 예약은 걸지 않는다(queued 가 아님)
    assert reread(session, retry[0]).status == "scheduled"


@pytest.mark.real_channel("call")
async def test_delegated_redial_happens_once_in_the_next_window(session, world):
    importlib.import_module("app.outreach.channels.voice")
    world.conn.agent_call = "delegate"
    session.commit()
    first = queued(session, world.who)
    sim = SimulatedVoice([NoAnswer(), NoAnswer()])
    with voice_session.pinned(sim):
        await runner.run_one(first.id, now=WORK)
        retry = session.scalars(select(OutreachCall).where(OutreachCall.retry_of == first.id)).one()
        assert retry.scheduled_at is not None

        early = await runner.tick(now=WORK + timedelta(hours=1))
        assert early["due"] == 0 and reread(session, retry).status == "scheduled"
        done = await runner.tick(now=MONDAY + timedelta(hours=1))

    assert done["due"] == 1 and done["placed"] == 1 and len(sim.dialed) == 2
    assert reread(session, retry).status == "no_answer"
    assert session.scalars(select(OutreachCall.id).where(OutreachCall.retry_of == retry.id)).all() == []  # 두 번째는 없다
    assert len(session.scalars(select(OutreachCall.id)).all()) == 2


@pytest.mark.real_channel("call")
async def test_redial_after_failure_is_a_new_row(session, world):
    importlib.import_module("app.outreach.channels.voice")
    row = queued(session, world.who)
    sim = SimulatedVoice([Busy(), Say("peer", "네", t=1), Hangup("peer")])
    with voice_session.pinned(sim):
        await runner.run_one(row.id, now=WORK)
        assert reread(session, row).status == "busy"

        again = await gate.dispatch("call", row.id, USER, now=WORK + timedelta(minutes=5))
        assert again.code == "not_sendable" and runner.enqueue(row.id) is True
        assert await runner.run_one(row.id, now=WORK) is None  # 끝난 줄을 다시 차지하지 않는다
        assert reread(session, row).status == "busy"

        fresh = call(session, world.who)
        session.commit()
        out = await gate.dispatch("call", fresh.id, USER, now=WORK + timedelta(minutes=5))
        assert out.code == "queued"
        result = await runner.tick(now=WORK + timedelta(minutes=5))

    assert result["placed"] == 1 and len(sim.dialed) == 2
    assert reread(session, fresh).status == "completed" and reread(session, row).status == "busy"


async def test_failed_and_busy_calls_are_closed_with_the_fixed_codes(session, world):
    rows = [queued(session, world.who) for _ in range(2)]
    sim = SimulatedVoice([Busy()])
    with voice_session.pinned(sim):
        await runner.run_one(rows[0].id, now=WORK)
    from app.outreach.voice.simulated import Failed
    sim2 = SimulatedVoice([Failed("rejected_by_network")])
    with voice_session.pinned(sim2):
        await runner.run_one(rows[1].id, now=WORK)
    assert reread(session, rows[0]).status == "busy" and reread(session, rows[1]).status == "failed"
    assert ("call_result", "noted", "busy") in rules(session, rows[0])
    assert ("call_result", "noted", "failed") in rules(session, rows[1])


# ── 걸기 직전에 다시 본다 ──────────────────────────────────────────────


@pytest.mark.parametrize("change, status, rule", [
    ("test_mode", "blocked_test", "test_mode"),
    ("dnc", "draft", "blocked_or_dnc"),
    ("hours", "blocked_hours", "working_hours"),
    ("phone_gone", "draft", "precheck"),
    ("no_connection", "draft", "precheck"),
])
async def test_recheck_before_dialing_blocks_when_test_mode_turned_on(session, world, change, status, rule):
    row = queued(session, world.who)
    now = WORK
    if change == "test_mode":
        world.conn.test_mode = True
    elif change == "dnc":
        session.add(DoNotContactNumber(number=PHONE, reason="시험"))
    elif change == "hours":
        now = OFF
    elif change == "phone_gone":
        world.who.phone = None
    else:
        world.conn.is_default = False
    session.commit()

    sim = await place(row, plain_call(), now=now)

    assert sim.dialed == [] and sim.calls == []
    back = reread(session, row)
    assert back.status == status and back.fail_reason
    assert rules(session, row)[-1] == ("recheck_before_dial", "blocked", rule)
    assert back.send_mode == "manual"  # send_mode 는 건드리지 않는다


async def test_recheck_passes_and_is_recorded_before_dialling(session, world):
    world.conn.test_mode = True
    world.conn.allow_numbers_json = [SENTINEL_PHONE]
    session.commit()
    row = queued(session, world.who)
    await place(row, plain_call())
    assert ("recheck_before_dial", "allowed", "ok") in rules(session, row)
    assert reread(session, row).status == "completed"


@pytest.mark.parametrize("missing", ["backend", "logs", "check", "agent_number", "key"])
async def test_not_ready_voice_leaves_a_draft_and_dials_nothing(session, world, monkeypatch, missing):
    row = queued(session, world.who)
    settings = session.get(VoiceSettings, world.conn.id)
    if missing == "logs":
        monkeypatch.setattr(redact, "covers", lambda name: name != "clawops")
    elif missing == "agent_number":  # AI 전화 번호도 발신번호도 없다
        settings.agent_number = None
        world.conn.sender_number = None
    elif missing == "key":
        settings.secret_ciphertext = "not-a-fernet-token"
    session.commit()

    sim = SimulatedVoice(plain_call(), broken=("check",) if missing == "check" else ())
    if missing == "backend":
        result = await runner.run_one(row.id, now=WORK)
    else:
        with voice_session.pinned(sim):
            result = await runner.run_one(row.id, now=WORK)

    back = reread(session, row)
    assert (result, back.status, sim.dialed) == ("draft", "draft", [])
    assert rules(session, row)[-1][:2] == ("recheck_before_dial", "blocked") and back.fail_reason


async def test_empty_agent_number_falls_back_to_the_sender_number_and_model_is_never_empty(session, world):
    settings = session.get(VoiceSettings, world.conn.id)
    settings.agent_number, settings.model = None, ""
    session.commit()
    row = queued(session, world.who)

    sim = await place(row, plain_call())

    assert sim.calls[0].spec.from_number == world.conn.sender_number
    usage = session.scalars(select(OutreachUsage).where(OutreachUsage.ref_id == row.id)).one()
    assert usage.model == numbers.DEFAULT_LIVE_MODEL == "gemini-3.8-live"


async def test_empty_model_of_another_provider_is_not_given_the_google_default(session, world):
    settings = session.get(VoiceSettings, world.conn.id)
    settings.provider, settings.model = "openai", ""
    session.commit()
    row = queued(session, world.who)
    await place(row, plain_call())
    assert session.scalars(select(OutreachUsage).where(OutreachUsage.ref_id == row.id)).one().model is None


async def test_answered_then_dropped_is_never_completed(session, world, monkeypatch):
    """받은 뒤 세션이 실패해 연결이 끊김(END_LOST) — 통화됨이 아니라 「확인 필요」 failed."""
    from app.outreach.voice.simulated import Lost

    finished = []
    monkeypatch.setattr(call_run, "after_call", lambda call_id: finished.append(call_id) or asyncio.sleep(0))
    row = queued(session, world.who)
    sim = await place(row, [Lost()])
    back = reread(session, row)
    assert sim.ended == [("lost", 0)] and (back.status, back.fail_reason) == ("failed", call_run.LOST)
    assert ("call_result", "blocked", "backend_error") in rules(session, row) and finished == []


async def test_backend_that_never_ends_is_bounded(session, world, monkeypatch):
    """받은 뒤 끝 사건(call_end)이 오지 않는 백엔드 — 실제 시간 상한에서 끊고 failed(완료가 아니다)."""
    monkeypatch.setattr(runner, "PLACE_GRACE_S", 0.3 - outreach.limits(world.conn).max_call_seconds)
    row = queued(session, world.who)

    began = time.monotonic()
    sim = await place(row, [Say("peer", "네", t=1), Hold(), Hangup("peer")])

    assert time.monotonic() - began < 3  # 일꾼의 상한(0.3초)에서 끊었다 — 가짜의 Hold 한도(10초)를 기다리지 않았다
    back = reread(session, row)
    assert (back.status, back.fail_reason) == ("failed", call_run.BROKE_DURING_CALL)
    assert sim.calls[0].broke and runner.live() == 0


async def test_voice_key_is_registered_before_the_backend_is_used(session, world):
    row = queued(session, world.who)
    registered = []

    class Peek(SimulatedVoice):
        async def check(self):
            registered.append(SENTINEL_KEY in redact.secrets())
            return await super().check()

    sim = Peek(plain_call())
    with voice_session.pinned(sim):
        await runner.run_one(row.id, now=WORK)
    assert registered == [True]


# ── 서버가 다시 뜸 ─────────────────────────────────────────────────────


async def test_restart_closes_live_calls(session, world):
    rows = {state: call(session, world.who, status=state, claimed_at=WORK) for state in
            ("queued", "dialing", "in_call", "completed", "no_answer")}
    session.commit()

    moved = runner.recover(now=WORK + timedelta(minutes=1))

    assert moved == 3
    got = {state: reread(session, row) for state, row in rows.items()}
    assert (got["dialing"].status, got["dialing"].fail_reason) == ("failed", "서버가 다시 시작돼 끊겼습니다")
    assert (got["in_call"].status, got["in_call"].fail_reason) == ("failed", "서버가 다시 시작돼 끊겼습니다")
    assert got["queued"].status == "draft" and got["queued"].fail_reason == runner.REQUEUED
    assert got["completed"].status == "completed" and got["no_answer"].status == "no_answer"
    for state in ("queued", "dialing", "in_call"):
        assert own_rules(session, rows[state]) == ["server_restart"]
    assert runner.recover(now=WORK + timedelta(minutes=2)) == 0  # 두 번 불러도 한 번


async def test_restart_leaves_rows_claimed_after_this_process_started(session, world):
    row = call(session, world.who, status="in_call", claimed_at=WORK + timedelta(minutes=5))
    session.commit()
    assert runner.recover(now=WORK + timedelta(minutes=6), before=WORK) == 0
    assert reread(session, row).status == "in_call"


# ── 사람이 끊음 · 한 번에 한 통 ─────────────────────────────────────────────


async def test_human_hangup_ends_call(session, world):
    row = queued(session, world.who)
    assert runner.hangup(row.id) is False  # 아직 통화가 아니다

    sim = SimulatedVoice([Say("peer", "네", t=2), Hold(), Say("peer", "안 끊겼네요", t=30), Hangup("peer")])
    with voice_session.pinned(sim):
        task = asyncio.create_task(runner.run_one(row.id, now=WORK))
        await sim.wait_held()
        assert runner.hangup(row.id) is True
        await asyncio.wait_for(task, 5)

    assert sim.ended == [("agent", 2)]
    assert ("hangup_by_person", "noted") in [(r, v) for r, v, _ in rules(session, row)]
    assert reread(session, row).status == "completed"
    assert runner.hangup(row.id) is False


async def test_one_call_at_a_time(session, world):
    first, second = queued(session, world.who), queued(session, world.who, purpose_key="another")
    sim = SimulatedVoice([Say("peer", "네", t=2), Hold(), Hangup("peer"), Say("peer", "네", t=2), Hangup("peer")])
    assert runner.MAX_LIVE == 1
    with voice_session.pinned(sim):
        task = asyncio.create_task(runner.run_one(first.id, now=WORK))
        await sim.wait_held()
        assert await runner.run_one(second.id, now=WORK) == "waiting"
        assert reread(session, second).status == "queued" and len(sim.dialed) == 1
        assert voice_settings_api.worker_connected(AGENT_NUMBER) is True  # 진단은 이 번호로 붙지 않는다
        sim.release()
        await asyncio.wait_for(task, 5)
        assert voice_settings_api.worker_connected(AGENT_NUMBER) is False
        assert await runner.run_one(second.id, now=WORK) == "completed"
    assert sim.peak_live == 1 and len(sim.dialed) == 2


async def test_no_call_while_a_voice_diagnosis_holds_the_line(session, world, monkeypatch):
    monkeypatch.setitem(voice_settings_api._VOICE_RUNNING, world.conn.id, {"part": "connect"})
    row = queued(session, world.who)
    sim = await place(row, plain_call())
    assert sim.dialed == [] and reread(session, row).status == "queued" and rules(session, row) == []
    assert runner.enqueue(row.id) is True
    result = await runner.tick(now=WORK)
    assert result["placed"] == 0 and list(runner._state.queue) == [row.id]  # 줄은 그대로 기다린다


# ── 고장 ────────────────────────────────────────────────────────────


async def test_backend_error_fails_only_that_call(session, world, caplog):
    caplog.set_level(logging.DEBUG)
    broken, mid, fine = queued(session, world.who), queued(session, world.who), queued(session, world.who)
    sim = SimulatedVoice([Crash(), Say("peer", f"번호 {SENTINEL_PHONE}", t=2), Crash(), Say("peer", "네", t=2),
                          Hangup("peer")])
    kinds = []
    with voice_session.pinned(sim):
        for row in (broken, mid, fine):
            await runner.run_one(row.id, now=WORK)
            kinds.append(runner.status()["last_error_kind"])

    first, second, third = (reread(session, r) for r in (broken, mid, fine))
    assert (first.status, first.fail_reason) == ("failed", call_run.UNKNOWN_IF_PLACED)  # 걸렸는지 모름 — 확인 필요
    assert (second.status, second.fail_reason) == ("failed", call_run.BROKE_DURING_CALL)
    assert third.status == "completed"
    for row in (broken, mid):
        assert ("call_result", "blocked", "backend_error") in rules(session, row)
    assert kinds == ["VoiceError", "VoiceError", None]
    assert_clean(caplog)


async def test_handler_bug_fails_the_call_and_logs_only_the_kind(session, world, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"bug {SENTINEL_PHONE} {SENTINEL_KEY}")

    monkeypatch.setattr(call_run, "_write_transcript", boom)
    row = queued(session, world.who)
    await place(row, plain_call())
    back = reread(session, row)
    assert back.status == "completed"  # 받아쓰기를 적지 못해도 통화는 이어지고 끝에 한꺼번에 적는다
    assert len(back.transcript_json) == 2
    assert_clean(caplog)


async def test_unknown_outcome_is_never_retried(session, world):
    world.conn.agent_call = "delegate"
    session.commit()
    row = queued(session, world.who)
    await place(row, [Crash()])
    assert reread(session, row).status == "failed"
    assert session.scalars(select(OutreachCall.id).where(OutreachCall.retry_of == row.id)).all() == []


# ── 사건 낱말 ─────────────────────────────────────────────────────────


async def test_call_events_use_the_fixed_vocabulary(session, world):
    world.conn.limits_json = {"max_call_seconds": 30}
    session.commit()
    scripts = [
        [Say("peer", "네", t=1), Silence(60), Hangup("peer")],
        [Say("peer", f"말 {n}", t=n * 5) for n in range(1, 9)] + [Hangup("peer")],
        [NoAnswer()], [Crash()],
        [Say("peer", "네", t=1), Tool("record_answer", {"question": "q", "answer": "a", "quote": "네"}),
         Tool("schedule_fact", {"activity": "타설"}), Hangup("peer")],
    ]
    rows = []
    for script in scripts:
        row = queued(session, world.who)
        rows.append(row)
        await place(row, script)
    world.conn.test_mode = True
    session.commit()
    blocked = queued(session, world.who)
    rows.append(blocked)
    await place(blocked, plain_call())

    seen = set()
    for row in rows:
        for rule, _, detail in rules(session, row):
            if rule.startswith("tool:") or rule in TOOL_REFUSALS or rule == "site_pinned":
                continue
            seen.add(rule)
            if rule == "call_result":
                assert detail in CALL_RESULTS
    assert seen <= RUNNER_RULES | {"delivery"}  # delivery 는 결과 모름을 문에 알리는 문의 낱말(고침 1)
    assert {"silence", "time_limit", "call_result", "recheck_before_dial"} <= seen


# ── 통로 ────────────────────────────────────────────────────────────


@pytest.mark.real_channel("call")
async def test_voice_channel_only_enqueues_and_registers_once(session, world):
    from app.outreach.harness import registry

    module = importlib.import_module("app.outreach.channels.voice")
    channel = module.CHANNEL
    assert channel.name == "call" and registry._CHANNELS["call"] is channel
    assert importlib.reload(module).CHANNEL is channel  # 다시 불러와도 같은 객체

    row = call(session, world.who)
    session.commit()
    out = await gate.dispatch("call", row.id, USER, now=WORK)

    assert out.code == "queued" and list(runner._state.queue) == [row.id]
    assert reread(session, row).status == "queued"  # 통로는 줄에 넣기만 — 아무것도 걸지 않았다


async def test_voice_channel_reports_failed_when_the_queue_refuses(session, world, monkeypatch):
    module = importlib.import_module("app.outreach.channels.voice")
    monkeypatch.setattr(runner, "QUEUE_MAX", 0)
    got = await module.VoiceChannel().deliver(123)
    assert got == Delivered("failed", fail_code="local_error")
    assert "local_error" in gate.FAIL_TEXT


async def test_queue_is_bounded_and_does_not_repeat():
    assert runner.enqueue(7) and runner.enqueue(7)
    assert list(runner._state.queue) == [7]
    for n in range(runner.QUEUE_MAX - 1):
        assert runner.enqueue(100 + n)
    assert runner.enqueue(999) is False


# ── 끄는 설정 · 상태 ──────────────────────────────────────────────────


@pytest.mark.parametrize("env", [{"CHRONOS_OUTREACH_WORKER": "off"}, {"CHRONOS_OUTREACH_WORKER": "0"},
                                 {"CHRONOS_HARNESS_SANDBOX": "1"}])
async def test_switch_keeps_the_runner_off(session, world, monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    row = queued(session, world.who)

    runner.start.__wrapped__()
    try:
        assert runner._state.task is None and runner.status()["running"] is False
        assert runner.status()["off_reason"] in ("disabled", "sandbox")
        assert runner.enqueue(row.id) is False  # 꺼진 일꾼은 줄을 받지 않는다(통로가 failed 를 돌려준다)
    finally:
        await runner.stop()
    assert reread(session, row).status == "queued" and rules(session, row) == []  # 아무것도 적지 않았다


async def test_start_and_stop_bring_the_loop_up_and_down_without_placing(session, world, monkeypatch):
    ran = []

    async def tick(now=None):
        ran.append(1)
        return {}

    monkeypatch.setattr(runner, "tick", tick)
    monkeypatch.setattr(runner, "recover", lambda now=None, *, before=None: 0)
    runner.start.__wrapped__()
    try:
        for _ in range(100):
            if ran:
                break
            await asyncio.sleep(0.01)
        assert runner.status()["running"] is True and ran
    finally:
        await runner.stop()
    assert runner.status()["running"] is False


def test_status_has_the_console_fields_and_no_number(world):
    state = runner.status()
    assert set(state) >= {"running", "live", "backend", "listening", "last_call_at", "last_error_kind"}
    assert state["backend"] in ("ok", "not_ready", "sdk_missing") and state["listening"] is False
    assert SENTINEL_DIGITS not in str(state)


# ── 고침 1 ──────────────────────────────────────────────────────────


def _no_hangup(sim):
    """끊기를 받아도 끝 사건을 주지 않는 백엔드(PM 실제 시험의 404 — 세션이 실패해 call_end 가 오지 않음)."""
    original = sim.place

    async def place(spec, handlers):
        class Deaf:
            def __init__(self, control):
                self._control = control

            def __getattr__(self, name):
                return getattr(self._control, name)

            async def hangup(self):
                return None

        class Wrap:
            def __getattr__(self, name):
                return getattr(handlers, name)

            async def on_start(self, control):
                await handlers.on_start(Deaf(control))

        await original(spec, Wrap())

    sim.place = place
    return sim


@pytest.mark.parametrize("how", ["crash_before_answer", "crash_during_call", "restart", "no_end_after_hangup"])
async def test_unknown_outcome_blocks_an_immediate_redial(session, world, fake_channel, monkeypatch, how):
    """결과를 모르는 통화(걸렸을 수 있음)는 문이 아는 꼴(delivery · unsure)로 닫는다 — 곧바로 같은 번호로 다시 걸지 못한다."""
    monkeypatch.setattr(call_run, "HANGUP_WAIT_S", 0.2)
    row = queued(session, world.who)
    if how == "restart":
        session.get(OutreachCall, row.id).status = "dialing"
        session.commit()
        runner.recover(now=WORK + timedelta(seconds=10))
    elif how == "no_end_after_hangup":
        sim = _no_hangup(SimulatedVoice([Say("peer", "네", t=1), Hold(), Hangup("peer")]))
        with voice_session.pinned(sim):
            task = asyncio.create_task(runner.run_one(row.id, now=WORK))
            await sim.wait_held()
            assert runner.hangup(row.id) is True
            await asyncio.wait_for(task, 5)
    else:
        script = [Crash()] if how == "crash_before_answer" else [Say("peer", "네", t=1), Crash()]
        await place(row, script)

    assert reread(session, row).status == "failed"
    assert ("delivery", "noted") in [(r, v) for r, v, _ in rules(session, row)]
    again = call(session, world.who)
    session.commit()
    out = await gate.dispatch("call", again.id, USER, now=WORK + timedelta(seconds=30))
    assert out.code == "duplicate" and "확인" in out.message and fake_channel.delivered == []


async def test_runner_hangup_waits_for_the_end_only_briefly(session, world, monkeypatch):
    """일꾼이 끊은 뒤에는 끝 사건을 HANGUP_WAIT_S 만 기다린다(max_call_seconds + 60초가 아니다)."""
    monkeypatch.setattr(call_run, "HANGUP_WAIT_S", 0.2)
    row = queued(session, world.who)
    sim = _no_hangup(SimulatedVoice([Say("peer", "네", t=1), Hold(), Hangup("peer")]))
    began = time.monotonic()
    with voice_session.pinned(sim):
        task = asyncio.create_task(runner.run_one(row.id, now=WORK))
        await sim.wait_held()
        runner.hangup(row.id)
        assert await asyncio.wait_for(task, 5) == "failed"
    assert time.monotonic() - began < 3 and runner.live() == 0
    assert reread(session, row).fail_reason == call_run.BROKE_DURING_CALL


@pytest.mark.parametrize("where", ["before_claim", "after_claim"])
async def test_exception_while_preparing_closes_the_row(session, world, monkeypatch, caplog, where):
    """다시 보기·명세·도구 상자를 만드는 중의 뜻밖의 예외 — 줄을 queued/dialing 에 두지 않고 failed(건 것 없음)로 닫는다."""
    caplog.set_level(logging.DEBUG)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"boom {SENTINEL_PHONE} {SENTINEL_KEY}")

    if where == "before_claim":
        monkeypatch.setattr(runner.voices, "pick", boom)
    else:
        monkeypatch.setattr(runner, "Toolbox", boom)
    row = queued(session, world.who)

    sim = await place(row, plain_call())

    back = reread(session, row)
    assert sim.dialed == [] and (back.status, back.fail_reason) == ("failed", runner.PREP_FAILED)
    assert ("delivery", "noted") not in [(r, v) for r, v, _ in rules(session, row)]  # 건 것이 없으니 문을 막지 않는다
    assert runner.live() == 0 and runner.holds_line() is False
    assert_clean(caplog)


async def test_calls_that_never_went_out_do_not_count_toward_the_daily_limit(session, world):
    world.conn.test_mode = True
    session.commit()
    rows = [queued(session, world.who) for _ in range(3)]
    for row in rows:
        await place(row, plain_call())
    day = WORK.astimezone(outreach.KST).date()
    assert [reread(session, r).status for r in rows] == ["blocked_test"] * 3
    assert all(reread(session, r).claimed_at is None for r in rows)
    assert outreach.sent_count(session, "call", day, number=PHONE) == 0
