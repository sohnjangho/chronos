"""음성 되돌이 시험(app.outreach.voice.loopback) — 가짜 세션만, 망·SDK·모델 없음.

다리가 소리를 두 쪽으로 넘기는지, 끝(끊기·상대 끊기·침묵·최대 시간), 쪽 A 의 도구가 하네스 Toolbox 로 DB 에 적히는지, 통화 뒤 일이
불리는지, 줄에 「시험 통화 — 전화망 없음」 표시가 붙는지, 실서버 자료 폴더를 거절하는지 본다. 쪽 A 는 실제 어댑터(kat_sdk ·
kat_listen)를 지나고, 바뀌는 것은 세션(FakeLive)과 SDK 의 통화·등록부 객체뿐이다.
"""

import asyncio
import json
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from sqlalchemy import select

from app.outreach.harness import registry
from app.outreach.voice import call_run, loopback
from app.security import crypto
from app.store.tables_outreach import (
    ContactReport,
    NotifyConnection,
    OutreachCall,
    VoiceSettings,
)
from tests.outreach.harness.test_gate import call, connect, person
from tests.outreach_doubles import SENTINEL_KEY

pytestmark = pytest.mark.usefixtures("time_guard")

AGENT_NUMBER = "07000000100"
PERSONA = "상대 역 시험 인물입니다."
FRAMES = 12  # 한 번 말할 때 보내는 쪽 수
FAST = 0.002  # 시험의 쪽 간격(실제는 0.02초)


# ── 가짜 SDK 조각(세션·통화·도구 등록부) ─────────────────────────────


class FakeRegistry:
    def __init__(self) -> None:
        self._tools: dict = {}

    def register(self, fn=None, **kw):
        self._tools[fn.__name__] = fn
        return fn

    def fork(self) -> "FakeRegistry":
        copy = FakeRegistry()
        copy._tools = dict(self._tools)
        return copy

    async def call(self, name: str, arguments: dict) -> str:
        return await self._tools[name](**arguments)


class FakeCall:
    """SDK CallSession 의 꼴(다리·어댑터가 쓰는 칸만)."""

    def __init__(self, *, call_id, from_number, to_number, account_id, direction) -> None:
        self.call_id, self.direction, self.from_number, self.to_number = call_id, direction, from_number, to_number
        self.handlers: dict = {}
        self.send = self.clear = self.hang = None

    def on(self, event, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    async def _emit(self, event, *args) -> None:
        for handler in self.handlers.get(event, []):
            await handler(self, *args)

    def bind_transport(self, *, send_audio, send_clear, hangup, **kw) -> None:
        self.send, self.clear, self.hang = send_audio, send_clear, hangup

    async def send_audio(self, audio: bytes) -> None:
        await self.send(audio)

    async def hangup(self) -> None:
        await self.hang()


class FakeLive:
    """Gemini Live 세션 흉내. 시스템 지시문이 PERSONA 로 시작하면 상대 역(B), 아니면 우리 쪽(A — 어댑터가 지은 세션).
    plan 은 시험마다 바꾸는 대본 이름."""

    plan = "normal"
    made: ClassVar[list] = []
    loop_tap = loop_usage = None

    def __init__(self, **kw) -> None:
        self.kw, self.peer = kw, kw.get("system_prompt", "").startswith(PERSONA)
        self.loop_prompt, self.loop_voice = kw.get("system_prompt", ""), kw.get("voice") or "Kore"
        self.heard, self.tools, self.builtin, self.task, self.call = 0, None, None, None, None
        self.ear = asyncio.Event()
        FakeLive.made.append(self)

    def set_tool_registry(self, registry) -> None:
        self.tools = registry

    def set_builtin_tools(self, tools) -> None:
        self.builtin = tools

    async def start(self, call) -> None:
        self.call = call
        self.task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def feed_audio(self, frame: bytes, ts: int) -> None:
        if frame != loopback.SILENCE:
            self.heard += 1
            if self.heard >= FRAMES // 2:
                self.ear.set()

    async def say(self, text: str) -> None:
        await self.call._emit("transcript", "assistant", text)
        self.loop_tap(b"\x01\x00" * (loopback.PCM_TICK // 2) * FRAMES)
        await self.call.send_audio(b"\x10" * loopback.FRAME * FRAMES)
        self.loop_usage({"total_token_count": 10, "prompt_tokens_details": {"AUDIO": 4}, "response_tokens_details": {}})

    async def listen(self, text: str) -> None:
        await self.ear.wait()
        self.ear.clear()
        self.heard = 0
        await self.call._emit("transcript", "user", text)

    async def _run(self) -> None:
        if self.peer:
            if self.kw.get("greeting"):  # 받는 통화: 상대가 먼저
                await self.say("여보세요, 김 과장인데요")
            await self.ear.wait()
            self.ear.clear()
            if FakeLive.plan == "silent":
                return
            await asyncio.sleep(0.3)
            await self.say("네 김 과장입니다. 다음 주부터 2교대 가능합니다")
            if FakeLive.plan == "peer_hangs_up":
                await asyncio.sleep(0.3)
                await self.call.hangup()
            return
        first = self.loop_prompt.rsplit("「", 1)[-1].rstrip("」")  # 어댑터가 붙인 고정 첫마디
        await self.say(first)
        await self.listen("네 김 과장입니다. 다음 주부터 2교대 가능합니다")
        if FakeLive.plan in ("silent", "peer_hangs_up"):
            await asyncio.sleep(60)
        if self.kw.get("greeting", True) and "confirm_person" in self.tools._tools:
            await self.tools.call("confirm_person", {"is_person": True})
            await self.tools.call("record_answer", {"question": "2교대 가능 여부", "answer": "다음 주부터 가능",
                                                    "quote": "다음 주부터 2교대 가능합니다"})
        else:
            await self.tools.call("report_from_contact", {"kind": "delay", "text": "자재 반입 이틀 늦어짐",
                                                          "quote": "다음 주부터 2교대 가능합니다"})
        await asyncio.sleep(2.5)  # 어댑터가 발화를 맺는 틈(FRAGMENT_GAP_S)
        await self.say("감사합니다. 통화를 마치겠습니다")
        await asyncio.sleep(1.5)
        await self.tools.call("end_call", {"reason": "done"})


REAL = SimpleNamespace(ToolRegistry=FakeRegistry, CallSession=FakeCall,
                       BuiltinTool=SimpleNamespace(HANG_UP="hang_up", NONE="none", TRANSFER_CALL="transfer_call", ALL="all"),
                       GeminiRealtime=FakeLive)


@pytest.fixture
def world(session, sid, monkeypatch):
    FakeLive.made, FakeLive.plan = [], "normal"
    monkeypatch.setattr(loopback, "_guard", lambda modules=None: None)  # 다른 시험이 통로 모듈을 불러 두었을 수 있다
    after: list = []

    async def hook(call_id, box=None):
        after.append((call_id, box))

    monkeypatch.setattr(call_run, "after_call", hook)
    conn = connect(session, inbound_mode="known")
    session.add(VoiceSettings(connection_id=conn.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              status="ok"))
    who = person(session, sid, name="김 과장")
    session.commit()
    return SimpleNamespace(conn=conn, who=who, sid=sid, after=after)


def _opts(**over) -> loopback.Options:
    return loopback.Options(PERSONA, **({"max_s": 15.0, "silence_s": 12.0, "tick_s": FAST} | over))


def _draft(session, who) -> OutreachCall:
    row = call(session, who, status="draft", questions_json=["2교대 가능 여부"], avoid_json=["금액 · 다른 업체"])
    session.commit()
    return row


def _reread(session, row_id) -> OutreachCall:
    session.expire_all()
    return session.get(OutreachCall, row_id)


# ── 거는 통화 ─────────────────────────────────────────────────────────


async def test_outbound_bridges_both_ways_runs_the_toolbox_and_the_after_call(session, world, tmp_path):
    row = _draft(session, world.who)

    outcome = await loopback.outbound(row.id, _opts(), real=REAL, live=FakeLive)

    a = [s for s in FakeLive.made if not s.peer and s.call is not None][-1]  # 다리가 쓴 우리 세션(어댑터의 팩토리)
    b = [s for s in FakeLive.made if s.peer][-1]  # 상대 역 세션
    assert outcome.bridge.fed["A"] >= FRAMES and outcome.bridge.fed["B"] >= FRAMES  # 소리가 두 쪽으로 갔다
    assert outcome.bridge.reason == "agent_hangup"  # end_call → control.hangup → SDK 통화 끊기
    got = _reread(session, row.id)
    assert got.status == "completed"
    assert got.origin_name == loopback.MARK and got.provider_call_id.startswith(loopback.CALL_PREFIX)
    assert [a["answer"] for a in got.answers_json] == ["다음 주부터 가능"]  # 도구가 하네스 Toolbox 로 DB 에
    roles = [line["role"] for line in got.transcript_json]
    assert roles[0] == "agent" and "peer" in roles
    assert world.after == [(row.id, world.after[0][1])] and world.after[0][1] is not None  # 통화 뒤 일(도구 상자와 함께)
    # 상대 역은 다른 음성·인물 지시문·끊기 도구 하나, 우리 쪽은 어댑터가 지은 지시문(말하지 않을 것 포함)
    assert b.loop_voice != a.loop_voice and b.builtin == {"hang_up"}
    assert "말하지 않을 것:" in a.loop_prompt and "금액 · 다른 업체" in a.loop_prompt
    assert a.kw["api_version"] == "v1alpha" and a.kw["input_audio_transcription"]["language_codes"] == ["ko-KR"]

    result = loopback.save(outcome, "out", tmp_path, _opts(), 0)
    assert result["checks"]["first_line_discloses"] and result["checks"]["answers"] == 1
    turns = json.loads((tmp_path / "turns.json").read_text(encoding="utf-8"))["turns"]
    assert {t["side"] for t in turns} == {"A", "B"} and all(t["end"] > t["start"] for t in turns)
    assert any("2교대" in t["text"] for t in turns if t["side"] == "B")
    for name in ("a_agent.wav", "b_counterpart.wav", "mix.wav"):
        with wave.open(str(tmp_path / name)) as w:
            assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (24000, 2, 1) and w.getnframes() > 0
    assert "금액 · 다른 업체" in (tmp_path / "instructions_a.txt").read_text(encoding="utf-8")


async def test_peer_hang_up_ends_the_call_as_the_peer(session, world):
    FakeLive.plan = "peer_hangs_up"
    row = _draft(session, world.who)
    outcome = await loopback.outbound(row.id, _opts(), real=REAL, live=FakeLive)
    assert outcome.bridge.reason == "peer_hangup"
    assert _reread(session, row.id).status == "completed"


async def test_silence_stops_the_call(session, world):
    FakeLive.plan = "silent"
    row = _draft(session, world.who)
    outcome = await loopback.outbound(row.id, _opts(silence_s=1.5), real=REAL, live=FakeLive)
    assert outcome.bridge.reason == "silence"
    assert _reread(session, row.id).status == "completed"


async def test_max_duration_stops_the_call(session, world):
    FakeLive.plan = "silent"
    row = _draft(session, world.who)
    outcome = await loopback.outbound(row.id, _opts(max_s=1.0), real=REAL, live=FakeLive)
    assert outcome.bridge.reason == "max_duration"


async def test_only_a_draft_or_queued_outbound_row_is_used(session, world):
    row = call(session, world.who, status="completed")
    session.commit()
    with pytest.raises(loopback.Refused):
        await loopback.outbound(row.id, _opts(), real=REAL, live=FakeLive)


# ── 받는 통화 ─────────────────────────────────────────────────────────


async def test_inbound_goes_through_the_door_and_the_caller_speaks_first(session, world):
    outcome = await loopback.incoming(world.who.id, _opts(), real=REAL, live=FakeLive)

    got = _reread(session, outcome.call_id)
    assert got.direction == "in" and got.caller_class == "contact" and got.status == "completed"
    assert got.origin_name == loopback.MARK
    first_b = min(t for t in outcome.bridge.b.played)
    first_a = min(t for t in outcome.bridge.a.played)
    assert first_b < first_a  # 건 쪽(B)이 먼저 말했다
    reports = session.scalars(select(ContactReport).where(ContactReport.call_id == got.id)).all()
    assert reports  # report_from_contact 가 Toolbox 로 「확인할 보고」를 남겼다
    assert [call_id for call_id, _ in world.after] == [got.id]


async def test_inbound_refuses_when_the_inbound_scope_is_off(session, world):
    conn = session.get(NotifyConnection, world.conn.id)
    conn.inbound_mode = "off"
    session.commit()
    with pytest.raises(loopback.Refused):
        await loopback.incoming(world.who.id, _opts(), real=REAL, live=FakeLive)


# ── 안전 · 녹음 시간축 ───────────────────────────────────────────────


@pytest.mark.parametrize("value", ["", "   "])
def test_refuses_without_a_data_dir(value):
    with pytest.raises(loopback.Refused):
        loopback.refuse_live({"CHRONOS_DATA_DIR": value})


def test_refuses_the_live_data_dir():
    for live in loopback.LIVE_DIRS:
        with pytest.raises(loopback.Refused):
            loopback.refuse_live({"CHRONOS_DATA_DIR": str(live)})
        with pytest.raises(loopback.Refused):
            loopback.refuse_live({"CHRONOS_DATA_DIR": str(live / ".." / live.name)})


def test_a_copy_data_dir_is_allowed(tmp_path):
    assert loopback.refuse_live({"CHRONOS_DATA_DIR": str(tmp_path)}) == Path(tmp_path).resolve()


def test_cli_refuses_the_live_data_dir_before_touching_anything(monkeypatch, capsys):
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(loopback.LIVE_DIRS[0]))
    monkeypatch.setattr(loopback, "init_db", lambda: pytest.fail("DB 를 열면 안 된다"))
    assert loopback.main(["out", "--call-id", "1"]) == 2
    assert "실서버" in capsys.readouterr().err


def test_guard_refuses_when_a_sending_channel_is_loaded(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})  # 다른 시험이 등록해 둔 통로는 빼고 본다
    with pytest.raises(loopback.Refused):
        loopback._guard({"app.outreach.channels.sms": object()})
    loopback._guard({"app.outreach.voice.runner": object()})
    monkeypatch.setattr(registry, "_CHANNELS", {"sms": object()})
    with pytest.raises(loopback.Refused):
        loopback._guard({})


def test_gaps_are_capped_and_leading_silence_trimmed():
    spans = loopback.keep_spans([(100, 150), (400, 450)], max_gap=60, lead=10, tail=25)
    assert spans == [(90, 180), (370, 475)]  # 앞은 10쪽만, 250쪽 틈은 60쪽으로, 뒤는 25쪽
    assert loopback.remap(100, spans) == 10 and loopback.remap(400, spans) == 10 + 50 + 60
    assert loopback.runs_of([1, 2, 3, 30, 31], gap=20) == [(1, 4), (30, 32)]
