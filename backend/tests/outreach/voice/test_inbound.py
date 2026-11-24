"""받는 통화 통로(Task 95). 음성은 가짜(SimulatedVoice 의 Ring · 가짜 SDK)뿐이다 — 실제 SDK·모델·망·시계가 없다.

받는 통화 한 통은 `sim.listen(번호, inbound.on_incoming)` 으로 직접 울리고, 통화 뒤 일(run_after)은 `settle()` 로 기다린다.
듣기 고리의 한 바퀴는 `inbound.sync()` 로 직접 돌린다(고리를 띄우지 않는다). SDK 어댑터의 듣기(kat_sdk.listen)는 Task 113 의
가짜 SDK 를 받는 통화까지 흉내 내게 늘린 것(ListenSdk)으로 본다 — 받기 전 훅을 실제 SDK 처럼 기다리고, 통화를 시작할 때
에이전트의 (빈) 도구 등록부로 세션을 덮는다.
"""

import ast
import asyncio
import inspect
import json
import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import func, select

import app
from app.llm.client import LlmClient
from app.outreach.harness import door, review, tools, toolsets
from app.outreach.voice import (
    after,
    call_run,
    inbound,
    instructions,
    kat_listen,
    kat_sdk,
    runner,
)
from app.outreach.voice import session as voice_session
from app.outreach.voice.session import CallSpec, Incoming, VoiceError
from app.outreach.voice.simulated import Hangup, Hold, Ring, Say, SimulatedVoice, Tool
from app.programs.notify_settings import voice as voice_settings_api
from app.security import crypto
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
    VoiceSettings,
)
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, reply
from tests.outreach.harness.test_door_class import account, second_schedule
from tests.outreach.harness.test_gate import WORK, connect, person
from tests.outreach.voice.test_backend_for import (
    ACCOUNT,
    GOOGLE_KEY,
    LEAKS,
    SAID,
    FakeAgent,
    FakeCall,
    FakeIncoming,
    FakeSdk,
    World,
    conn,
    kat,
    voice,
)
from tests.outreach.voice.test_runner import queued
from tests.outreach.voice.test_simulated import OUR_NUMBER, Rec, _spec
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, assert_clean

pytestmark = pytest.mark.usefixtures("time_guard")

AGENT_NUMBER = "07000000100"  # 가상 AI 전화 번호
OTHER_AGENT = "07000000111"
STRANGER = "01000000188"  # 주소록에 없는 가상 번호
AT = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)  # 한국 시각 금요일 10시
INBOUND = Path(app.__file__).parent / "outreach" / "voice" / "inbound.py"
SUMMARY = "박현장 공무가 자기 작업 날짜를 물어 답했습니다."
TALK = [Say("peer", "철근 작업 언제죠", t=2), Hangup("peer")]


# ── 도우미 ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_inbound(monkeypatch):
    """받는 통화의 메모리 상태는 시험마다 새것 · SDK 어댑터의 번호별 에이전트도."""
    monkeypatch.setattr(inbound, "_state", inbound._State())
    monkeypatch.setattr(kat_listen, "AGENTS", {})


@pytest.fixture
def world(session, sid):
    """기본 알림 연결(ok·시험 모드 끔·승인 받기·받는 범위 「주소록에 있는 번호만」) + 음성 설정 + 연락처 한 사람."""
    row = connect(session, inbound_mode="known")
    session.add(VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              voice_unknown="sim-n1", voice_male_contact="sim-f1", status="ok"))
    who = person(session, sid, gender="male", language="ko")
    session.commit()
    site = session.get(ScheduleRecord, sid).name
    return type("World", (), {"conn": row, "who": who, "sid": sid, "site": site})


async def settle() -> None:
    """통화 뒤 일·회신 문자 넣기(뒤에서 도는 일)를 기다린다."""
    for _ in range(20):
        pending = [task for task in inbound._state.follows if not task.done()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=5)


async def ring(*script, **options) -> SimulatedVoice:
    """가짜 음성으로 벨을 울린다(Ring + 받았을 때 돌 걸음들). 끝나면 통화 뒤 일까지 기다린다."""
    sim = SimulatedVoice(list(script), **options)
    with voice_session.pinned(sim):
        async with asyncio.timeout(10):
            await sim.listen(AGENT_NUMBER, inbound.on_incoming)
            await settle()
    return sim


def calls_in(session) -> list[OutreachCall]:
    session.expire_all()
    return list(session.scalars(select(OutreachCall).where(OutreachCall.direction == "in").order_by(OutreachCall.id)))


def rules(row: OutreachCall) -> list[tuple[str, str, str]]:
    return [(e["rule"], e["verdict"], e["detail"]) for e in row.harness_json]


def messages(session) -> list[OutreachMessage]:
    session.expire_all()
    return list(session.scalars(select(OutreachMessage).order_by(OutreachMessage.id)))


def busy_line(monkeypatch) -> None:
    """한 번에 한 통 — 다른 통화가 줄을 쥐고 있다(거는 일꾼의 통화 하나)."""
    monkeypatch.setitem(runner._state.live, 9999, object())


# ── 지시서의 열둘 ─────────────────────────────────────────────────────


async def test_inbound_uses_shared_door_and_toolbox(session, world, monkeypatch):
    tree = ast.parse(INBOUND.read_text(encoding="utf-8"))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "by_number" not in attributes and "resolve" not in attributes  # 번호로 사람을 찾는 것은 문만 한다
    admits, boxes = [], []
    real_admit, real_call = door.admit, tools.Toolbox.call

    def spy_admit(session_, medium, number, **kw):
        admits.append((medium, kw.get("live_calls")))
        return real_admit(session_, medium, number, **kw)

    async def spy_call(self, name, args):
        boxes.append((name, self.caller_class, self.medium))
        return await real_call(self, name, args)

    monkeypatch.setattr(door, "admit", spy_admit)
    monkeypatch.setattr(tools.Toolbox, "call", spy_call)
    sim = await ring(Ring(world.who.phone, AT), Say("peer", "철근 작업 언제죠", t=2),
                     Tool("schedule_fact", {"activity": "A"}), Hangup("peer"))
    assert admits == [("call", 0)]
    assert boxes == [("schedule_fact", "contact", "call")]
    assert sim.tool_results and calls_in(session)[0].status == "completed"


async def test_rejected_ring_is_not_answered_but_recorded(session, world):
    sim = await ring(Ring(STRANGER, AT), *TALK)  # 받는 범위가 「주소록에 있는 번호만」 — 모르는 번호
    assert sim.rejected and not sim.calls
    (row,) = calls_in(session)
    assert row.status == "rejected" and row.caller_class == "unknown" and row.direction == "in"
    assert row.schedule_id is None and row.contact_id is None and row.started_at is None
    assert rules(row) == [("admission", "blocked", "unknown_not_accepted")]
    assert runner.live() == 0


@pytest.mark.parametrize("setup,cls", [("contact", "contact"), ("unknown", "unknown"), ("internal", "internal"),
                                       ("dnc", "do_not_contact"), ("two", "contact_multi")])
async def test_tools_in_spec_are_exactly_the_class_set(session, world, setup, cls):
    number = world.who.phone
    if setup == "unknown":
        world.conn.inbound_mode, number = "all", STRANGER
    elif setup == "internal":
        account(session, "user", STRANGER)
        number = STRANGER
    elif setup == "dnc":
        world.who.do_not_contact = True
    elif setup == "two":
        person(session, second_schedule(session))
    session.commit()
    sim = await ring(Ring(number, AT), *TALK)
    (spec,) = [call.spec for call in sim.calls]
    wanted = toolsets.for_class(cls, "call")
    assert {tool.name for tool in spec.tools} == wanted and len(spec.tools) == len(wanted)
    assert spec.direction == "in" and spec.to_number is None and spec.from_number == AGENT_NUMBER
    assert spec.record_to is None  # 녹음은 끈다(진단과 같다)
    assert calls_in(session)[0].caller_class == cls


async def test_inbound_spec_and_events_have_no_caller_number(session, world, caplog):
    caplog.set_level(logging.DEBUG)
    sim = await ring(Ring(world.who.phone, AT), Say("peer", "작업 날짜요", t=2),
                     Tool("my_requests", {}), Hangup("peer"))
    (record,) = sim.calls
    texts = [repr(record.spec), record.spec.first_line, record.spec.instructions,
             *(text for _, text in sim.model_saw())]
    assert not sim.leaks()
    assert all(SENTINEL_DIGITS not in "".join(ch for ch in text if ch.isdigit()) for text in texts)
    (row,) = calls_in(session)
    trail = json.dumps(row.harness_json, ensure_ascii=False)
    assert SENTINEL_DIGITS not in "".join(ch for ch in trail if ch.isdigit())
    assert rules(row)[0] == ("admission", "allowed", "known_caller")
    assert row.contact_id == world.who.id and row.peer_number is None  # 한 사람이면 번호 칸은 비운다(연락처에서 읽는다)
    assert_clean(caplog, SENTINEL_KEY)


async def test_listen_only_when_mode_is_on_and_rebinds_on_change(session, world):
    world.conn.inbound_mode = "off"
    session.commit()
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        try:
            assert await inbound.sync() == "off" and sim.listens == [] and not inbound.listening()
            world.conn.inbound_mode = "known"
            session.commit()
            assert await inbound.sync() == "listening"
            await asyncio.sleep(0)
            assert sim.listens == [AGENT_NUMBER] and inbound.listening() and runner.holds_line()
            assert await inbound.sync() == "listening" and sim.listens == [AGENT_NUMBER]  # 바뀐 것이 없으면 그대로
            session.get(VoiceSettings, world.conn.id).agent_number = OTHER_AGENT
            session.commit()
            first = inbound._state.listen
            assert await inbound.sync() == "listening"
            await asyncio.sleep(0)
            assert first.cancelled() and sim.listens == [AGENT_NUMBER, OTHER_AGENT]
            world.conn.inbound_mode = "off"
            session.commit()
            assert await inbound.sync() == "off"
            await asyncio.sleep(0)
            assert sim.listening is None and not inbound.listening() and not runner.holds_line()
        finally:
            await inbound.stop()


async def test_busy_is_missed_and_drafts_reply_sms_for_known_contact(session, world, monkeypatch, fake_channel):
    busy_line(monkeypatch)
    sim = await ring(Ring(world.who.phone, AT), *TALK)
    assert sim.rejected and not sim.calls
    (row,) = calls_in(session)
    assert row.status == "missed" and row.caller_class == "contact" and row.contact_id == world.who.id
    assert rules(row) == [("admission", "noted", "line_busy")]
    (sms,) = messages(session)
    assert (sms.direction, sms.channel, sms.contact_id, sms.schedule_id) == ("out", "sms", world.who.id, world.sid)
    assert sms.body == inbound.MISSED_SMS and sms.origin == "agent" and sms.kind == "normal"
    # 문을 지났다(문자 권한이 「승인 받기」라 초안으로 남는다) — 곧바로 보내지 않는다
    assert sms.status == "draft" and ("permission", "blocked") in {(e["rule"], e["verdict"]) for e in sms.harness_json}
    assert fake_channel.delivered == []


async def test_busy_unknown_caller_gets_no_sms(session, world, monkeypatch):
    world.conn.inbound_mode = "all"
    session.commit()
    busy_line(monkeypatch)
    await ring(Ring(STRANGER, AT), *TALK)
    await ring(Ring(None, AT), *TALK)  # 번호 숨김
    rows = calls_in(session)
    assert [(r.status, r.caller_class) for r in rows] == [("missed", "unknown"), ("missed", "withheld")]
    assert messages(session) == []


async def test_unknown_call_has_no_project(session, world):
    world.conn.inbound_mode = "all"
    session.commit()
    sim = await ring(Ring(STRANGER, AT), *TALK)
    (row,) = calls_in(session)
    assert row.schedule_id is None and row.contact_id is None and row.caller_class == "unknown"
    assert row.status == "completed" and world.site not in sim.calls[0].spec.first_line


async def test_short_max_time_for_low_classes(session, world):
    world.conn.inbound_mode = "all"
    world.conn.limits_json = {"max_call_seconds": 240, "max_call_seconds_unknown": 90, "unknown_calls_hourly": 99}
    session.commit()
    seconds = []
    for number in (STRANGER, None, world.who.phone):
        sim = await ring(Ring(number, AT), *TALK)
        seconds += [call.spec.max_seconds for call in sim.calls]
    assert seconds == [90, 90, 240]
    world.who.do_not_contact = True
    session.commit()
    sim = await ring(Ring(world.who.phone, AT + timedelta(minutes=30)), *TALK)
    assert [call.spec.max_seconds for call in sim.calls] == [90]
    world.conn.limits_json = {}  # 기본은 120초
    session.commit()
    sim = await ring(Ring(STRANGER, AT + timedelta(hours=2)), *TALK)
    assert sim.calls[0].spec.max_seconds == 120


async def test_greeting_names_site_only_for_single_project_contact(session, world):
    world.conn.inbound_mode = "all"
    session.commit()
    sim = await ring(Ring(world.who.phone, AT), *TALK)
    one = sim.calls[0].spec
    assert one.first_line == f"안녕하세요, {world.site} 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?"
    assert f"현장: {world.site}" in one.instructions and "상대 이름(주소록): 박현장" in one.instructions
    assert one.voice_id == "sim-f1"  # 남성 연락처 → 그 성별의 칸(voices.pick — PM 이 반대 성별 음성을 넣어 둔다)
    sim = await ring(Ring(STRANGER, AT + timedelta(minutes=10)), *TALK)
    stranger = sim.calls[0].spec
    assert stranger.first_line == "안녕하세요, 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?"
    assert "현장:" not in stranger.instructions and "상대 이름" not in stranger.instructions
    assert stranger.voice_id == "sim-n1" and stranger.language == "ko"  # 모르면 기본(성별 모름) 음성·한국어
    person(session, second_schedule(session))
    session.commit()
    sim = await ring(Ring(world.who.phone, AT + timedelta(minutes=20)), *TALK)
    multi = sim.calls[0].spec
    assert world.site not in multi.first_line and "현장:" not in multi.instructions


async def test_after_inbound_runs_review_and_summary_only(session, world, monkeypatch):
    """끝난 받는 통화에는 뒤 확인과 요약 — 후속 줄(다시 걸기·회신 문자)은 만들지 않는다. 통화 뒤 일은 줄을 놓은 뒤에 돈다."""
    add_connection(session)
    llm = ScriptedLlm([reply(json.dumps({"summary_ko": SUMMARY, "result": "작업 날짜 안내"}, ensure_ascii=False))])
    monkeypatch.setattr(after, "client_for", lambda s: LlmClient(s, transport=llm.transport))
    checked, seen = [], []
    real_check, real_after = review.check, call_run.after_call

    def spy_check(session_, ref, **kw):
        checked.append((ref.kind, kw["caller_class"], kw["scope"].caller_class))
        return real_check(session_, ref, **kw)

    async def spy_after(call_id, box=None):
        seen.append((runner.live(), box is not None and box.caller_class))
        await real_after(call_id, box)

    monkeypatch.setattr(review, "check", spy_check)
    monkeypatch.setattr(call_run, "after_call", spy_after)
    await ring(Ring(world.who.phone, AT), Say("peer", "제 작업 날짜요", t=2), Tool("schedule_fact", {"activity": "A"}),
               Say("agent", "A 작업은 3월 1일 시작입니다", t=4), Hangup("peer"))
    (row,) = calls_in(session)
    assert row.status == "completed" and row.summary_ko == SUMMARY and row.result_proposed == "작업 날짜 안내"
    assert checked == [("call", "contact", "contact")] and seen == [(0, "contact")]
    assert session.scalar(select(func.count(OutreachCall.id))) == 1 and messages(session) == []
    kinds = {u.kind for u in session.scalars(select(OutreachUsage).where(OutreachUsage.ref_id == row.id))}
    assert kinds == {"voice_model", "summary"}


async def test_no_key_phone_or_account_in_logs(session, world, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    world.conn.inbound_mode = "all"
    session.commit()
    await ring(Ring(world.who.phone, AT), *TALK)
    await ring(Ring(STRANGER, AT), Say("peer", f"제 번호는 {SENTINEL_DIGITS}", t=1), Hangup("peer"))
    busy_line(monkeypatch)
    await ring(Ring(world.who.phone, AT + timedelta(minutes=5)), *TALK)
    assert [r.status for r in calls_in(session)] == ["completed", "completed", "missed"]
    assert_clean(caplog, SENTINEL_KEY, ACCOUNT, "acct-test")


# ── 한 번에 한 통 · 끝나지 못한 통화 ───────────────────────────────────


async def test_inbound_call_holds_the_one_line(session, world):
    """받는 통화가 도는 동안 거는 일꾼은 기다리고(WAITING), 그 사이 걸려 온 전화는 부재중이다. 끝나면 줄을 놓는다."""
    out = queued(session, world.who, claimed_at=WORK)
    sim = SimulatedVoice([Ring(world.who.phone, AT), Hold(), Hangup("peer"), Ring(STRANGER, AT)])
    with voice_session.pinned(sim):
        async with asyncio.timeout(10):
            listening = asyncio.ensure_future(sim.listen(AGENT_NUMBER, inbound.on_incoming))
            await sim.wait_held()
            assert runner.live() == 1 and runner.holds_line()
            assert await runner.run_one(out.id, now=WORK) == runner.WAITING
            assert await inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT)) is None
            sim.release()
            await listening
            await settle()
    rows = calls_in(session)
    assert [(r.status, r.caller_class) for r in rows][:2] == [("completed", "contact"), ("missed", "contact")]
    assert runner.live() == 0 and not runner.holds_line()


async def test_a_ring_while_the_outbound_worker_holds_the_line_is_missed(session, world, monkeypatch):
    """거는 일꾼이 줄을 쥔 동안(걸기 직전의 다시 보기 ~ 통화 뒤 일)은 통화 중과 같다 — 공용 에이전트에 두 통이 겹치지 않게."""
    monkeypatch.setattr(runner._state, "holding", 7)
    assert await inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT)) is None
    (row,) = calls_in(session)
    assert row.status == "missed" and rules(row) == [("admission", "noted", "line_busy")] and runner.live() == 0


async def test_ring_that_never_starts_is_closed_without_a_retry(session, world):
    """받기로 했는데 통화가 시작되지 않음(백엔드의 on_failed) → 부재중, 다시 걸기를 만들지 않는다. 백엔드 고장 → failed."""
    spec_run = await inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT))
    assert spec_run is not None
    spec, run = spec_run
    assert isinstance(spec, CallSpec) and runner.live() == 1
    await run.on_failed("no_answer", "not_started")
    await settle()
    (row,) = calls_in(session)
    assert row.status == "missed" and ("call_result", "noted", "no_answer") in rules(row)
    assert session.scalar(select(func.count(OutreachCall.id))) == 1 and runner.live() == 0
    async def dead():
        raise VoiceError("듣기가 끊김")

    inbound._state.listen = asyncio.ensure_future(dead())  # 백엔드가 고장 나 듣기가 끝남(끝 사건 없음)
    await asyncio.sleep(0)
    spec, run = await inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT + timedelta(minutes=9)))
    await settle()
    assert inbound._state.listen.exception() is not None
    last = calls_in(session)[-1]
    assert last.status == "failed" and ("call_result", "blocked", "backend_error") in rules(last)
    assert "delivery" not in {rule for rule, _, _ in rules(last)}  # 받는 통화는 「걸렸는지 모름」이 아니다


async def test_cancelled_decision_does_not_leave_a_ringing_row(session, world, monkeypatch):
    """백엔드가 판정을 기다리다 그만두면(시한 넘김) 받기로 적은 줄을 받지 못한 줄로 닫는다 — 줄을 쥐지 않는다."""
    real = inbound._decide

    def slow(*args):
        import time

        time.sleep(0.3)
        return real(*args)

    monkeypatch.setattr(inbound, "_decide", slow)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT)), 0.05)
    await asyncio.sleep(0.5)
    await settle()
    (row,) = calls_in(session)
    assert row.status == "missed" and runner.live() == 0


# ── 듣기 고리 ─────────────────────────────────────────────────────────


async def test_runner_start_and_stop_bring_up_the_listener(session, world):
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        runner.start.__wrapped__()
        try:
            for _ in range(50):
                await asyncio.sleep(0.01)
                if sim.listens:
                    break
            assert sim.listens == [AGENT_NUMBER] and runner.status()["listening"] is True
        finally:
            await runner.stop()
    assert not inbound.listening() and sim.listening is None and runner.status()["listening"] is False


async def test_listener_does_not_bind_while_the_line_is_held_or_diagnosing(session, world, monkeypatch):
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        monkeypatch.setattr(runner._state, "holding", 7)
        assert await inbound.sync() == "waiting" and sim.listens == []
        monkeypatch.setattr(runner._state, "holding", None)
        monkeypatch.setattr(runner, "_diagnosing", lambda: True)
        assert await inbound.sync() == "waiting" and sim.listens == []


async def test_listener_is_not_dropped_in_the_middle_of_a_call(session, world, monkeypatch):
    """받는 범위를 끄거나 번호를 바꿔도 통화 중이면 듣기(그 통화의 연결)를 풀지 않는다 — 끝난 뒤의 바퀴에서 푼다."""
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        try:
            assert await inbound.sync() == "listening"
            await asyncio.sleep(0)
            busy_line(monkeypatch)
            world.conn.inbound_mode = "off"
            session.commit()
            assert await inbound.sync() == "waiting" and inbound.listening()
            world.conn.inbound_mode = "known"
            session.get(VoiceSettings, world.conn.id).agent_number = OTHER_AGENT
            session.commit()
            assert await inbound.sync() == "waiting" and sim.listens == [AGENT_NUMBER]
            runner._state.live.pop(9999)
            assert await inbound.sync() == "listening"
            await asyncio.sleep(0)
            assert sim.listens == [AGENT_NUMBER, OTHER_AGENT]
        finally:
            await inbound.stop()


async def test_failed_listen_is_retried_a_bounded_number_of_times(session, world, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(inbound, "_clock", lambda: clock[0])

    class Broken(SimulatedVoice):
        async def listen(self, number, on_incoming):
            self.listens.append(number)
            raise VoiceError("붙지 못함")

    sim = Broken([])
    with voice_session.pinned(sim):
        for _ in range(inbound.MAX_FAILS + 3):
            await inbound.sync()
            await asyncio.sleep(0)
            clock[0] += inbound.RETRY_S + 1
        assert await inbound.sync() == "gave_up"
        assert len(sim.listens) == inbound.MAX_FAILS and inbound._state.last_error_kind == "VoiceError"


# ── SDK 어댑터의 듣기(공용 에이전트) ───────────────────────────────────


class Registry:
    """실제 SDK 의 공개 ToolRegistry 꼴 — 함수 이름으로 등록한다."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def register(self, fn=None, *, behavior=None, scheduling=None):
        self.tools[fn.__name__] = fn
        return fn


class ListenAgent(FakeAgent):
    """받는 통화까지 흉내: 훅은 실제 SDK 처럼 기다리고(5초), 받으면 팩토리의 세션에 에이전트의 등록부를 덮어 준다."""

    def __init__(self, sdk, **kw) -> None:
        super().__init__(sdk, **kw)
        self.connects = 0
        self.taken_over = False
        self.rejected: Exception | None = None
        self.sessions: dict[str, object] = {}

    async def connect(self) -> None:
        if self.rejected is not None:  # 실제 SDK: 거절된 에이전트의 connect 는 그 거절을 다시 던진다
            raise self.rejected
        if self.connected:  # 실제 SDK 도 이미 붙어 있으면 아무것도 하지 않는다
            return
        self.connects += 1
        await super().connect()
        self.sdk.most_connected = max(self.sdk.most_connected, sum(agent.connected for agent in self.sdk.agents))

    def _start(self, session) -> None:
        registry = Registry()
        registry.tools.update(self.tools)  # 실제 SDK: 통화를 시작할 때 에이전트 등록부를 떠서 세션에 넣는다
        session.set_tool_registry(registry)

    async def call(self, to, *, timeout=60, machine_detection=None):
        self.sdk.dialed.append((to, timeout))
        session = self.kw["session_factory"]()
        call = FakeCall(self, f"CA{len(self.calls):04d}")
        self.calls.append(call)
        self.sessions[call.call_id] = session
        self._start(session)
        world = self.sdk.world
        for ms, kind, *args in self.sdk.script:
            world.at(world.ms + ms, partial(self.step, call, kind, *args))
        return call

    async def step(self, call, kind, *args) -> None:
        if kind == "tool" and not call.over:  # 세션의 등록부에서 부른다(실제 SDK 의 세션처럼)
            name, given = args
            self.sdk.tool_tasks.append(asyncio.ensure_future(self.sessions[call.call_id].registry.tools[name](**given)))
            return
        await super().step(call, kind, *args)

    async def ring_in(self, number=SENTINEL_DIGITS, *, restricted=False, script=()):
        incoming = FakeIncoming(f"IN{len(self.sdk.incoming):04d}")
        incoming.from_number, incoming.caller_id_restricted = number, restricted
        self.sdk.incoming.append(incoming)
        result = self.hook(incoming)
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, 5)
        if incoming.rejected:
            return incoming
        session = self.kw["session_factory"]()
        call = FakeCall(self, incoming.call_id, "inbound")
        self.calls.append(call)
        self.sessions[call.call_id] = session
        self._start(session)
        world = self.sdk.world
        for ms, kind, *args in script:
            world.at(world.ms + ms, partial(self.step, call, kind, *args))
        return incoming


class ListenSdk(FakeSdk):
    def __init__(self, world, **kw) -> None:
        super().__init__(world, **kw)
        self.most_connected = 0  # 함께 붙어 있던 에이전트 수의 최댓값(번호당 하나여야 한다)
        self.ToolRegistry = Registry
        base = self.GeminiRealtime

        class GeminiRealtime(base):
            def set_tool_registry(self, registry) -> None:
                self.registry = registry

        self.GeminiRealtime = GeminiRealtime

    def ClawOpsAgent(self, **kw):
        agent = ListenAgent(self, **kw)
        self.agents.append(agent)
        return agent


INBOUND_TALK = ((500, "call_start"), (800, "transcript", "assistant", SAID), (1500, "transcript", "user", "작업 날짜요"),
                (2000, "tool", "end_call", {"reason": "done"}), (3000, "call_end"))


def in_spec(**over) -> CallSpec:
    names = toolsets.for_class("unknown", "call")
    return _spec("in", **{"tools": toolsets.tool_defs(names), "instructions": instructions.inbound("unknown", None, None,
                                                                                                   "ko"), **over})


async def until(world: World, ready, limit_ms: int = 60_000) -> None:
    start = world.ms
    while not ready():
        assert world.ms - start < limit_ms, "기다리던 일이 오지 않습니다"
        await world.sleep(0.1)


async def test_kat_listen_screens_before_answering_and_gives_the_call_only_its_tools():
    world = World()
    sdk = ListenSdk(world)
    backend = kat(world, sdk)
    seen, recs = [], []

    async def decide(incoming: Incoming):
        seen.append(incoming)
        if incoming.caller_number == STRANGER:
            return None
        rec = Rec()
        recs.append(rec)
        return in_spec(), rec

    task = asyncio.ensure_future(backend.listen(OUR_NUMBER, decide))
    try:
        await until(world, lambda: sdk.agents and sdk.agents[0].connected)
        agent = sdk.agent
        assert agent.hook_before_connect and agent.kw["builtin_tools"] == "none" and agent.kw["prewarm_enabled"] is False
        assert agent.kw["recording"] is False and agent.tools == {}  # 듣는 에이전트에는 도구가 없다 — 통화마다 세션에
        refused = await agent.ring_in(STRANGER)
        assert refused.rejected and len(agent.calls) == 0
        hidden = await agent.ring_in(SENTINEL_DIGITS, restricted=True, script=INBOUND_TALK)
        assert not hidden.rejected and seen[-1].caller_number is None and seen[-1].to_number == OUR_NUMBER  # 약속 6
        await until(world, lambda: recs[0].log and recs[0].log[-1][0] == "end")
        session = agent.sessions[hidden.call_id]
        assert set(session.registry.tools) == toolsets.for_class("unknown", "call")  # 에이전트의 빈 등록부로 덮이지 않았다
        kinds = [entry[0] for entry in recs[0].log]
        assert kinds[0] == "start" and "tool" in kinds and kinds[-1] == "end"
        _, kw = sdk.sessions[-1]
        assert kw["api_version"] == "v1alpha" and kw["system_prompt"].startswith(in_spec().instructions)
        assert kw["input_audio_transcription"] == {"language_codes": ["ko-KR"]}  # 받는 통화도 받아쓰기 언어를 분명히
        assert sdk.sessions[0][1]["input_audio_transcription"] == {"language_codes": ["ko-KR"]}  # 듣기 전 확인도 같은 꼴
        assert agent.disconnects == 0 and task.done() is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert sdk.agent.disconnects == 1 and kat_listen.AGENTS == {}


async def test_kat_placing_while_listening_shares_the_one_agent():
    """control 연결은 번호당 하나 — 듣는 동안 거는 통화는 같은 에이전트로 건다. 끝나도 듣는 연결은 그대로다."""
    world = World()
    sdk = ListenSdk(world, script=((1000, "call_start"), (1300, "transcript", "assistant", SAID),
                                   (2000, "tool", "record_answer", {"question": "q", "answer": "a", "quote": "a"}),
                                   (3000, "call_end")))
    listener = kat(world, sdk)
    answered = []

    async def decide(incoming: Incoming):
        rec = Rec()
        answered.append(rec)
        return in_spec(), rec

    task = asyncio.ensure_future(listener.listen(OUR_NUMBER, decide))
    try:
        await until(world, lambda: sdk.agents and sdk.agents[0].connected)
        out = Rec()
        async with asyncio.timeout(15):
            await kat(world, sdk).place(_spec(), out)  # 일꾼은 걸 때마다 새 KatVoice 를 얻는다
        assert len(sdk.agents) == 1 and sdk.agent.connects == 1 and sdk.agent.disconnects == 0
        assert out.log[0][0] == "start" and out.log[-1][0] == "end"
        session = sdk.agent.sessions["CA0000"]
        assert set(session.registry.tools) == {tool.name for tool in _spec().tools}
        returns = await sdk.tool_returns()
        assert returns and returns[0] != kat_sdk.TOOL_FAILED_REPLY
        incoming = await sdk.agent.ring_in(SENTINEL_DIGITS, script=INBOUND_TALK)  # 거는 통화 뒤에도 듣고 있다
        assert not incoming.rejected
        await until(world, lambda: answered and answered[0].log and answered[0].log[-1][0] == "end")
        assert sdk.agent.disconnects == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert sdk.agent.disconnects == 1


async def test_kat_listen_fails_closed():
    """판정이 늦음·예외 → 거절. 통화 중에 울린 전화는 받지 않고 부재중(on_failed busy). 다른 번호·거는 명세 → 듣지 않음."""
    world = World()
    sdk = ListenSdk(world)
    backend = kat(world, sdk)
    recs = []

    async def decide(incoming: Incoming):
        if incoming.caller_number == STRANGER:
            await asyncio.sleep(60)
        if incoming.caller_number == "01000000177":
            raise RuntimeError(f"판정 고장 {SENTINEL_DIGITS}")
        rec = Rec()
        recs.append(rec)
        return in_spec(), rec

    with pytest.raises(VoiceError):
        await backend.listen(OTHER_AGENT, decide)  # 이 백엔드의 번호가 아니다
    task = asyncio.ensure_future(backend.listen(OUR_NUMBER, decide))
    try:
        await until(world, lambda: sdk.agents and sdk.agents[0].connected)
        agent = sdk.agent
        slow = asyncio.ensure_future(agent.ring_in(STRANGER))
        await until(world, slow.done)
        assert slow.result().rejected
        assert (await agent.ring_in("01000000177")).rejected
        first = await agent.ring_in(SENTINEL_DIGITS, script=((500, "call_start"),))
        assert not first.rejected
        await until(world, lambda: recs and recs[0].log)
        second = await agent.ring_in(SENTINEL_DIGITS)
        assert second.rejected and recs[1].log == [("failed", "busy", "line_busy")]
        with pytest.raises(VoiceError):
            async with asyncio.timeout(5):
                await kat(world, sdk).listen(OUR_NUMBER, decide)  # 번호당 하나 — 둘째 듣기는 붙지 않는다
        assert len(sdk.agents) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_kat_missed_calls_reads_inbound_calls_by_rest():
    """앱이 꺼진 동안의 받는 통화: 공개 REST `calls.list(to=번호)` 에서 받는 통화 가운데 끝났는데 받지 않은 것만(시각 창 안)."""
    world = World()
    sdk = ListenSdk(world)
    since, until_at = AT - timedelta(hours=2), AT
    rows = [
        {"call_id": "CAin1", "status": "no-answer", "direction": "inbound", "from_": SENTINEL_DIGITS, "date_created": AT - timedelta(hours=1)},
        {"call_id": "CAin2", "status": "completed", "direction": "inbound", "from_": SENTINEL_DIGITS, "date_created": AT - timedelta(hours=1)},
        {"call_id": "CAout", "status": "no-answer", "direction": "outbound", "from_": OUR_NUMBER, "date_created": AT - timedelta(hours=1)},
        {"call_id": "CAold", "status": "failed", "direction": "inbound", "from_": SENTINEL_DIGITS, "date_created": AT - timedelta(hours=5)},
        {"call_id": "CAhid", "status": "canceled", "direction": "inbound", "from_": STRANGER, "date_created": AT - timedelta(minutes=30),
         "caller_id_restricted": True},
    ]
    asked = []

    class Page:
        def __init__(self, data, more) -> None:
            self.data, self.more = data, more

        def has_next_page(self) -> bool:
            return self.more

    class Calls:
        async def list(self, **kw):
            asked.append(kw)
            from types import SimpleNamespace

            data = [SimpleNamespace(**({"caller_id_restricted": False} | row)) for row in rows]
            return Page(data if kw.get("page", 0) == 0 else [], kw.get("page", 0) == 0)

    class Client:
        def __init__(self, **kw) -> None:
            self.calls = Calls()
            sdk.rest_clients.append(kw)

    sdk.AsyncClawOps = Client
    found = await kat(world, sdk).missed_calls(since, until_at)
    assert [(item.call_id, item.caller_number) for item in found] == [("CAin1", SENTINEL_DIGITS), ("CAhid", None)]
    assert asked[0]["to"] == OUR_NUMBER and sdk.rest_clients[0]["max_retries"] == 0
    assert len(asked) == 2  # 다음 쪽이 비면 멈춘다(쪽 수에도 끝이 있다)


async def test_backfill_records_missed_calls_once_and_texts_nobody(session, world, monkeypatch, fake_channel):
    """앱이 꺼진 동안의 전화(REST 에서 읽은 것)를 부재중으로 한 번만 — 문자는 만들지도 보내지도 않는다. 받는 범위가 「받지
    않음」이던 동안의 전화는 그 까닭으로, 진단이 돌던 동안의 전화(진단이 받거나 거절한 시험 전화)는 적지 않는다."""
    stamp = AT - timedelta(minutes=40)
    off_at, diag_at = AT - timedelta(minutes=30), AT - timedelta(minutes=20)

    class Backfilling(SimulatedVoice):
        async def missed_calls(self, since, until):
            return [kat_listen.Missed("CAin1", world.who.phone, stamp), kat_listen.Missed("CAin2", None, stamp),
                    kat_listen.Missed("CAoff", world.who.phone, off_at),
                    kat_listen.Missed("CAdiag", world.who.phone, diag_at + timedelta(seconds=5)),
                    kat_listen.Missed("CAreal", STRANGER, diag_at - timedelta(seconds=30))]

    sim = Backfilling([], hold_line=True)
    monkeypatch.setattr(inbound, "_now", lambda: AT)
    inbound._state.quiet.extend([["off", off_at - timedelta(minutes=1), off_at + timedelta(minutes=1)],
                                 ["diagnosis", diag_at - timedelta(minutes=1), diag_at,
                                  inbound._number_key(world.who.phone)]])  # 진단은 앞뒤로 넓혀 본다 — 진단이 건 번호만 뺀다
    with voice_session.pinned(sim):
        assert await inbound.backfill(sim) == 4
        assert await inbound.backfill(sim) == 0  # 이미 적은 통화
        await settle()
    rows = calls_in(session)
    assert [(r.status, r.caller_class, r.provider_call_id, r.fail_reason) for r in rows] == [
        ("missed", "contact", "CAin1", inbound.WHILE_OFF), ("missed", "withheld", "CAin2", inbound.WHILE_OFF),
        ("missed", "contact", "CAoff", inbound.SCOPE_OFF), ("missed", "unknown", "CAreal", inbound.DIAGNOSING)]
    assert all(("call_result", "noted", "no_answer") in rules(r) for r in rows)
    assert messages(session) == [] and fake_channel.delivered == []
    assert session.get(Contact, world.who.id).phone == world.who.phone


async def test_scope_off_and_diagnosis_open_quiet_spans(session, world):
    world.conn.inbound_mode = "off"
    session.commit()
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        try:
            assert await inbound.sync() == "off" and runner.status()["listen_reason"] == "off"
            assert [(span[0], span[2]) for span in inbound._state.quiet] == [("off", None)]
            world.conn.inbound_mode = "known"
            session.commit()
            assert await inbound.sync() == "listening" and runner.status()["listen_reason"] is None
            assert inbound._state.quiet[-1][2] is not None  # 받는 범위를 켜면 닫힌다
        finally:
            await inbound.stop()


async def test_missed_reply_is_dispatched_with_the_current_clock(session, world, monkeypatch):
    later = AT + timedelta(minutes=3)
    seen = []

    async def spy(kind, row_id, actor, *, now=None):
        seen.append((kind, actor, now))

    monkeypatch.setattr(inbound, "_now", lambda: later)
    monkeypatch.setattr(inbound.gate, "dispatch", spy)
    busy_line(monkeypatch)
    await ring(Ring(world.who.phone, AT), *TALK)
    assert seen == [("message", tools.AGENT, later)]  # 벨이 울린 때가 아니라 넣는 때


async def test_late_missed_reply_is_still_dispatched(session, world, monkeypatch, fake_channel):
    """판정이 늦어 백엔드가 그만둬도 부재중 회신 초안은 문에 넣는다(넣지 않은 초안으로 버려 두지 않는다)."""
    busy_line(monkeypatch)
    real = inbound._decide

    def slow(*args):
        import time

        time.sleep(0.3)
        return real(*args)

    monkeypatch.setattr(inbound, "_decide", slow)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT)), 0.05)
    await asyncio.sleep(0.5)
    await settle()
    (sms,) = messages(session)
    assert ("permission", "blocked") in {(e["rule"], e["verdict"]) for e in sms.harness_json}


async def test_a_second_simultaneous_ring_still_gets_its_row(session, world, monkeypatch):
    monkeypatch.setattr(inbound, "LOCK_WAIT_S", 0.05)
    inbound._state.lock = asyncio.Lock()
    await inbound._state.lock.acquire()  # 다른 벨을 판정하는 중
    try:
        assert await inbound.on_incoming(Incoming(world.who.phone, AGENT_NUMBER, AT)) is None
    finally:
        inbound._state.lock.release()
    (row,) = calls_in(session)
    assert row.status == "missed" and rules(row) == [("admission", "noted", "line_busy")] and runner.live() == 0


async def test_displaced_listener_does_not_reconnect_until_settings_change(session, world):
    class Displacing(SimulatedVoice):
        async def listen(self, number, on_incoming):
            self.listens.append(number)
            raise kat_listen.Displaced(kat_listen.TAKEN_OVER, "taken_over")

    sim = Displacing([])
    with voice_session.pinned(sim):
        assert await inbound.sync() == "listening"
        await asyncio.sleep(0)
        for _ in range(3):
            assert await inbound.sync() == "gave_up"
        assert sim.listens == [AGENT_NUMBER] and runner.status()["listen_reason"] == "taken_over"
        session.get(VoiceSettings, world.conn.id).agent_number = OTHER_AGENT  # 설정이 바뀌면 다시 붙어 본다
        session.commit()
        assert await inbound.sync() == "listening"
        await asyncio.sleep(0)
        assert sim.listens == [AGENT_NUMBER, OTHER_AGENT]


async def test_runner_puts_the_call_back_when_the_shared_line_is_busy(session, world, monkeypatch):
    """듣는 연결이 잠깐 바쁘면(LineBusy) 실패가 아니라 줄로 되돌린다(WAITING) — 계속 바쁘면 초안으로(걸지 않음)."""
    monkeypatch.setattr(runner, "LINE_BUSY_TRIES", 2)

    class Busy(SimulatedVoice):
        async def place(self, spec, handlers):
            self.dialed.append(spec.to_number)
            raise kat_listen.LineBusy(kat_listen.NOT_FREE)

    out = queued(session, world.who, claimed_at=WORK)
    sim = Busy([])
    with voice_session.pinned(sim):
        for _ in range(2):
            assert await runner.run_one(out.id, now=WORK) == runner.WAITING
            session.expire_all()
            assert session.get(OutreachCall, out.id).status == "queued" and runner.live() == 0
        assert await runner.run_one(out.id, now=WORK) == "draft"
    session.expire_all()
    row = session.get(OutreachCall, out.id)
    assert row.status == "draft" and row.fail_reason == runner.LINE_BUSY and row.claimed_at is None
    busy = [v for r, v, d in rules(row) if r == "recheck_before_dial" and d == "line_busy"]
    assert busy == ["noted", "blocked"]  # 기다림마다 한 번(처음) · 그만둘 때 한 번 — 바퀴마다가 아니다
    assert runner._state.busy_tries == {}
    assert ("call_result", "blocked", "backend_error") not in rules(row)


async def test_diagnosis_pauses_the_listener_and_it_comes_back(session, world, monkeypatch):
    """진단 동안 듣기를 멈춘다 — 진단이 붙기 전에 듣던 연결이 닫히고(두 연결이 함께 있지 않다), 끝나면 곧바로 다시 붙는다."""
    clock = World()
    sdk = ListenSdk(clock)
    backend = kat(clock, sdk)
    with voice_session.pinned(backend):
        try:
            assert await inbound.sync() == "listening"
            await until(clock, lambda: sdk.agents and sdk.agents[0].connected)
            assert runner.holds_line()
            async with inbound.paused("010-0000-0177"):
                assert inbound._state.quiet[-1][3] == inbound._number_key("01000000177")
                assert not inbound.listening() and kat_listen.AGENTS == {} and sdk.agents[0].disconnects == 1
                assert not runner.holds_line() and await inbound.sync() == "paused"
                probe = sdk.ClawOpsAgent(from_=OUR_NUMBER)  # 진단의 에이전트
                await probe.connect()
                await probe.disconnect()
            assert inbound.listening()
            await until(clock, lambda: len(sdk.agents) == 3 and sdk.agents[2].connected)
            assert sdk.most_connected == 1 and inbound._state.quiet[-1][0] == "diagnosis"
            busy_line(monkeypatch)  # 통화 중이면 멈추지 않는다(진단이 holds_line 을 보고 붙지 않는다)
            async with inbound.paused():
                assert inbound.listening() and runner.holds_line()
        finally:
            await inbound.stop()
    assert inspect.getsource(voice_settings_api.run).count("inbound.paused(prep.call_to)") == 1


@pytest.mark.parametrize("how", ["error", "cancel"])
async def test_paused_listener_comes_back_after_an_error_or_a_cancel(session, world, how):
    sim = SimulatedVoice([], hold_line=True)
    with voice_session.pinned(sim):
        try:
            assert await inbound.sync() == "listening"
            await asyncio.sleep(0)

            async def diagnose():
                async with inbound.paused(None):
                    assert not inbound.listening()
                    if how == "error":
                        raise RuntimeError("진단 고장")
                    await asyncio.sleep(60)  # 시간 넘김 — 바깥이 취소한다

            task = asyncio.ensure_future(diagnose())
            await asyncio.sleep(0.05)
            if how == "cancel":
                task.cancel()
            with pytest.raises(RuntimeError if how == "error" else asyncio.CancelledError):
                await task
            assert inbound.listening() and inbound._state.paused == 0 and sim.listens == [AGENT_NUMBER, AGENT_NUMBER]
            assert inbound._state.quiet[-1][2] is not None
        finally:
            await inbound.stop()


async def test_kat_shared_line_busy_is_not_placed_later():
    """듣는 연결이 잠깐 바쁘면 걸지 않고 LineBusy(나중에) — 실패로 적지 않는다. 연결 값(키·계정·주소·번호)이 같으면 음성 설정이
    바뀌어도 같은 연결로 건다."""
    world = World()
    sdk = ListenSdk(world, script=((1000, "call_start"), (1300, "transcript", "assistant", SAID), (3000, "call_end")))
    listener = kat(world, sdk)
    task = asyncio.ensure_future(listener.listen(OUR_NUMBER, lambda incoming: asyncio.sleep(0)))
    try:
        await until(world, lambda: sdk.agents and sdk.agents[0].connected)
        shared = kat_listen.AGENTS[OUR_NUMBER]
        other_key = kat(world, sdk, c=conn(secret_ciphertext=crypto.encrypt("kat-test-key-OTHER7777")))
        with pytest.raises(kat_listen.LineBusy):  # (a) 키가 바뀌었다 — 받는 쪽이 다시 붙기 전(10초 안)
            await other_key.place(_spec(), Rec())
        shared.connected = False
        with pytest.raises(kat_listen.LineBusy):  # (b) 듣기가 붙는 중
            await kat(world, sdk).place(_spec(), Rec())
        shared.connected, shared.line = True, object()
        with pytest.raises(kat_listen.LineBusy):  # (c) 받은 통화를 아직 닫는 중
            await kat(world, sdk).place(_spec(), Rec())
        shared.line = None
        first = asyncio.ensure_future(kat(world, sdk).place(_spec(), Rec()))
        await until(world, lambda: shared.line is not None)
        with pytest.raises(kat_listen.LineBusy):  # (d) 둘이 함께
            await kat(world, sdk).place(_spec(), Rec())
        await until(world, first.done)
        first.result()
        out = Rec()
        async with asyncio.timeout(15):  # 음성 모델만 바뀜 — 같은 연결로 건다
            await kat(world, sdk, v=voice(model="gemini-other-live")).place(_spec(), out)
        assert out.log[-1][0] == "end" and len(sdk.agents) == 1 and sdk.agent.disconnects == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    kat_listen.AGENTS[OUR_NUMBER] = kat_listen.BUSY  # 듣지 않을 때의 거는 통화가 쥐고 있다
    try:
        with pytest.raises(kat_listen.LineBusy):
            await kat(world, sdk).place(_spec(), Rec())
    finally:
        del kat_listen.AGENTS[OUR_NUMBER]


async def test_kat_listen_ends_for_good_when_displaced_or_rejected():
    world = World()
    sdk = ListenSdk(world)
    task = asyncio.ensure_future(kat(world, sdk).listen(OUR_NUMBER, lambda incoming: asyncio.sleep(0)))
    await until(world, lambda: sdk.agents and sdk.agents[0].connected)
    sdk.agent.taken_over = True
    await until(world, task.done)
    assert isinstance(task.exception(), kat_listen.Displaced) and task.exception().reason == "taken_over"
    assert sdk.agent.disconnects == 1 and kat_listen.AGENTS == {}

    class AgentAuthRejectedError(Exception):
        pass

    task = asyncio.ensure_future(kat(world, sdk).listen(OUR_NUMBER, lambda incoming: asyncio.sleep(0)))
    await until(world, lambda: len(sdk.agents) == 2 and sdk.agents[1].connected)
    sdk.agents[1].rejected = AgentAuthRejectedError("키 폐기")  # 실제 SDK: 다시 붙기가 거절되면 connect 가 그것을 던진다
    await until(world, task.done)
    assert isinstance(task.exception(), kat_listen.Displaced) and task.exception().reason == "auth_rejected"


async def test_kat_session_factory_serves_only_the_ticketed_call():
    """세션 표는 한 번만 — 훅이 늦어 SDK 가 받아 버린 통화(표 없음)는 다른 통화의 지시문·도구를 받지 못한다."""
    world = World()
    sdk = ListenSdk(world, script=((1000, "call_start"), (1300, "transcript", "assistant", SAID), (20000, "call_end")))
    task = asyncio.ensure_future(kat(world, sdk).listen(OUR_NUMBER, lambda incoming: asyncio.sleep(0)))
    try:
        await until(world, lambda: sdk.agents and sdk.agents[0].connected)
        with pytest.raises(VoiceError):
            sdk.agent.kw["session_factory"]()
        out = asyncio.ensure_future(kat(world, sdk).place(_spec(), Rec()))
        await until(world, lambda: "CA0000" in sdk.agent.sessions)  # 거는 통화가 제 세션을 열었다
        with pytest.raises(VoiceError):  # 그 통화 중에 SDK 가 받아 버린 다른 통화 — 거는 통화의 세션을 받지 못한다
            sdk.agent.kw["session_factory"]()
        await until(world, out.done)
        out.result()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_inbound_line_treats_an_openai_setup_error_as_a_session_failure():
    world = World()
    sdk = ListenSdk(world)
    shared = kat_listen._Agent(kat(world, sdk), sdk, sdk, OUR_NUMBER, None)
    line = kat_listen._InLine(shared, in_spec(), Rec(), "IN0001")
    record = logging.LogRecord("clawops.agent", logging.ERROR, __file__, 1, "OpenAI error: invalid session config", None,
                               None)
    line.saw(record)
    assert [name for name, *_ in line.events] == ["session_failed"]


def test_inbound_instructions_use_the_harness_paragraphs():
    from app.outreach.harness import rules_text

    text = instructions.inbound("contact", "가상 현장 010-0000-0199", "박현장", "ko")
    assert rules_text.scope_paragraph("contact") in text and all(line in text for line in rules_text.FIXED.values())
    assert "010-0000-0199" not in text and "contact" not in text
    with pytest.raises(ValueError):
        instructions.inbound("nobody", None, None, "ko")
    unknown = instructions.inbound("unknown", None, None, "ko")
    assert rules_text.scope_paragraph("unknown") in unknown and "현장:" not in unknown
    assert GOOGLE_KEY not in unknown and all(leak not in unknown for leak in LEAKS)
    assert conn() and voice()  # 같은 가짜 설정을 쓴다
