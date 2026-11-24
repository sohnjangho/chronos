"""Task 113 — 음성 SDK 어댑터(kat_sdk.KatVoice)와 backend_for. 실제 SDK 는 불러오지도 만들지도 않는다 — 가짜 SDK 를 `sdk=` 로
끼우고(속성 이름은 실제 `clawops.agent` 와 같다), 시계는 대본 시계다(망·소리·실제 기다림 없음).

가짜는 진단 시험(tests/notify/test_diagnostics_voice.py)의 가짜와 같은 꼴이다: 실제 SDK 처럼 사건 손잡이를 `(call, *args)` 로 부르고,
계정·번호가 든 로그 줄과 예외 글을 남긴다. 도구는 실제 SDK 처럼 다른 태스크에서 부른다. 끝나지 않는 것을 흉내 내는 곳은 가짜
스스로 실제 5초에서 끝나고, 대본 시계는 2만 번 넘게 돌지 않으며, 시험 하나는 실제 20초(time_guard) 안에 끝난다.
"""

import asyncio
import inspect
import json
import logging
import subprocess
import sys
import textwrap
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.outreach import redact
from app.outreach.harness.types import NotReady
from app.outreach.voice import call_run, kat_sdk, numbers
from app.outreach.voice import session as voice_session
from app.outreach.voice.session import (
    END_AGENT,
    END_LOST,
    END_PEER,
    END_TRANSFER,
    END_TRANSFER_FAILED,
    OPENING_WITHIN_S,
    TOOL_FAILED_REPLY,
    VoiceError,
)
from app.outreach.voice.simulated import SimulatedVoice
from app.security import crypto
from app.store.tables_outreach import VoiceSettings
from tests.outreach.harness.test_gate import connect
from tests.outreach.voice.test_simulated import (
    FIRST,
    OUR_NUMBER,
    STAFF_NUMBER,
    Rec,
    _spec,
)
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)

pytestmark = pytest.mark.usefixtures("time_guard")

BACKEND = Path(__file__).resolve().parents[3]
ACCOUNT = "AC00000000003c4d"
GOOGLE_KEY = "goog-test-key-QQQQ7777"
SDK_LOG = logging.getLogger("clawops.agent")
REAL_GUARD_S = 5.0
LEAKS = (SENTINEL_KEY, ACCOUNT, GOOGLE_KEY, "QQQQ7777", "ZZZZ9999")
OPENING = ("안녕하세요, 가상 물류센터 일정 담당", " ChronOS AI 비서입니다. 이 통화는 기록됩니다.")
SAID = "안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다."
ANSWER = {"question": "3층 타설 날짜", "answer": "월요일", "quote": "월요일입니다"}

# 통화 대본: (건 뒤 ms, 사건, 인자…). 사건 이름은 실제 SDK 의 것 + 가짜만의 "tool"·"session_failed_log".
GOOD = ((1000, "call_start"), (1100, "transcript", "user", "여보세요"),
        (1300, "transcript", "assistant", OPENING[0]), (1500, "transcript", "assistant", OPENING[1]),
        (3000, "transcript", "user", "네 맞습니다"), (3500, "tool", "record_answer", ANSWER),
        (4000, "transcript", "assistant", "감사합니다"), (6000, "call_end"))
TALK = ((1000, "call_start"), (1300, "transcript", "assistant", SAID))


# ── 대본 시계와 가짜 SDK ──────────────────────────────────────────────────


class World:
    """sleep 은 실제로 기다리지 않고 시계만 돌린 뒤, 그 사이에 올 사건을 차례로 낸다."""

    def __init__(self) -> None:
        self.ms = 0
        self.due: list[tuple[int, int, object]] = []
        self.sleeps = 0

    def clock(self) -> float:
        return self.ms / 1000

    def at(self, ms: int, fn) -> None:
        self.due.append((ms, len(self.due), fn))

    async def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        assert self.sleeps < 20_000, "어댑터가 끝나지 않습니다(대본 시계로 20000번 넘게 잠)"
        self.ms += round(seconds * 1000)
        await asyncio.sleep(0)
        for item in sorted(i for i in self.due if i[0] <= self.ms):
            if item in self.due:
                self.due.remove(item)
                await item[2]()
        await asyncio.sleep(0)

    @staticmethod
    async def hang() -> None:
        """끝나지 않는 SDK 호출 흉내 — 어댑터가 취소하지 않아도 실제 5초 뒤에는 스스로 끝난다."""
        await asyncio.wait_for(asyncio.Event().wait(), REAL_GUARD_S)


class AgentError(Exception):
    """실제 SDK 의 예외 꼴: `code`·`status`, 글에는 계정·번호·키가 그대로 든다."""

    def __init__(self, status: object, code: object = "bad") -> None:
        super().__init__(f"발신 실패 ({status}): {SENTINEL_DIGITS} 계정 {ACCOUNT} 키 {SENTINEL_KEY}")
        self.status, self.code = status, code


class LiveError(Exception):
    """Gemini Live 연결이 404 로 끝난 예외 흉내."""

    status_code = 404


class _Done:
    """실제 SDK 의 reject() 가 돌려주는 꼴 — 부르는 순간 정해지고 await 는 형식만."""

    def __await__(self):
        return
        yield


class FakeIncoming:
    def __init__(self, call_id: str) -> None:
        self.call_id, self.from_number, self.to_number = call_id, SENTINEL_DIGITS, OUR_NUMBER
        self.caller_id_restricted, self.forwarded_from, self.reason = False, None, None

    @property
    def rejected(self) -> bool:
        return self.reason is not None

    def reject(self, reason: str = "rejected"):
        self.reason = self.reason or reason
        return _Done()


class FakeCall:
    def __init__(self, agent: "FakeAgent", call_id: str, direction: str = "outbound") -> None:
        self.agent, self.call_id, self.direction = agent, call_id, direction
        self.from_number, self.to_number = OUR_NUMBER, SENTINEL_DIGITS
        self.started = self.over = False
        self.hangups = 0
        self.transfers: list[str] = []

    async def hangup(self) -> None:
        self.hangups += 1
        mode = self.agent.sdk.hangup
        if mode == "hang":
            await World.hang()
        if mode == "slow":  # 실제 SDK 의 graceful_close: 보낸 소리가 다 나갈 때까지(mark) 5초까지 기다린 뒤 닫는다
            done, world = asyncio.Event(), self.agent.sdk.world

            async def played() -> None:
                done.set()

            world.at(world.ms + 6000, played)
            await asyncio.wait_for(done.wait(), REAL_GUARD_S)
        if mode in ("works", "slow") and self.started and not self.over:  # 실제 SDK 도 받기 전에는 끊지 못한다
            await self.agent.emit(self, "call_end")

    async def transfer(self, to: str, **kw) -> dict:
        """실제 SDK 처럼 전환 통화가 끝날 때까지 기다렸다가 결과를 준다. AI 쪽 통화는 그 전에 끝난다(terminate)."""
        self.transfers.append(to)
        outcome, world = self.agent.sdk.transfer, self.agent.sdk.world
        if outcome == "refused":
            raise RuntimeError(f"transfer not available {to}")
        if outcome == "bridging":  # 넘기는 중 — 결과도 AI 쪽 끝도 아직 없다
            await World.hang()
        world.at(world.ms + 1000, partial(self.agent.emit, self, "call_end"))
        done = asyncio.Event()

        async def settle() -> None:
            done.set()

        world.at(world.ms + 3000, settle)
        await asyncio.wait_for(done.wait(), REAL_GUARD_S)
        return {"status": "completed" if outcome == "answered" else "no-answer"}


class FakeAgent:
    def __init__(self, sdk: "FakeSdk", **kw) -> None:
        self.sdk, self.kw = sdk, kw
        self.handlers: dict[str, list] = {}
        self.tools: dict[str, object] = {}
        self.hook = None
        self.hook_before_connect = False
        self.connected = False
        self.disconnects = 0
        self.calls: list[FakeCall] = []

    def tool(self, fn=None, *, behavior=None, scheduling=None):
        self.tools[fn.__name__] = fn
        return fn

    def on(self, event: str):
        def decorator(fn):
            self.handlers.setdefault(event, []).append(fn)
            return fn
        return decorator

    def on_incoming(self, fn):
        self.hook = fn
        return fn

    async def connect(self) -> None:
        SDK_LOG.info(f"Control WS connected: wss://kat.invalid/v1/accounts/{ACCOUNT}/agent/listen?number={OUR_NUMBER}")
        self.hook_before_connect = self.hook is not None
        if self.sdk.connect == "hang":
            await World.hang()
        if isinstance(self.sdk.connect, BaseException):
            raise self.sdk.connect
        self.connected = True
        for ms in self.sdk.strangers:  # 우리가 거는 동안 걸려 온 전화
            self.sdk.world.at(self.sdk.world.ms + ms, self.ring)

    async def call(self, to: str, *, timeout: int = 60, machine_detection=None) -> FakeCall:
        SDK_LOG.info(f"Outbound call initiated: {OUR_NUMBER} -> {to}")
        self.sdk.dialed.append((to, timeout))
        script = self.sdk.script
        if script == "hang":
            await World.hang()
        if isinstance(script, BaseException):
            raise script
        self.kw["session_factory"]()  # 실제 SDK 의 팩토리 모드: 통화마다 세션 하나
        call = FakeCall(self, f"{self.sdk.call_prefix}{len(self.calls):04d}")
        self.calls.append(call)
        world = self.sdk.world
        for ms, kind, *args in script:
            world.at(world.ms + ms, partial(self.step, call, kind, *args))
        return call

    async def step(self, call: FakeCall, kind: str, *args) -> None:
        if call.over:
            return
        if kind == "tool":  # 실제 SDK 는 도구를 받기 루프의 태스크에서 부른다
            name, given = args
            SDK_LOG.info(f"Tool call: {name}({given})")
            self.sdk.tool_tasks.append(asyncio.ensure_future(self.tools[name](**given)))
        elif kind == "session_failed_log":  # 실제 SDK 의 _safe_start_call_session 이 남기는 줄(끝 사건은 오지 않는다)
            try:
                raise LiveError(f"HTTP 404 for model, caller {SENTINEL_PHONE}")
            except LiveError:
                # 앱의 로그 거르개는 줄을 만들 때 번호처럼 보이는 것을 가린다 — 통화 id 도 가려진 채로 올 수 있다
                SDK_LOG.error("Session start failed for %s: %s", redact.hide_phones(call.call_id), "HTTP 404",
                              exc_info=True)
        else:
            await self.emit(call, kind, *args)

    async def emit(self, call: FakeCall, event: str, *args) -> None:
        if event == "call_start":
            call.started = True
        if event in ("call_end", "call_failed"):
            if call.over:
                return
            call.over = True
        for fn in self.handlers.get(event, []):
            await fn(call, *args)

    async def ring(self) -> None:
        """걸려 온 전화 하나. 실제 SDK 처럼 훅이 거절하지 않으면(예외를 던져도) 받는다."""
        incoming = FakeIncoming(f"IN{len(self.sdk.incoming):04d}")
        self.sdk.incoming.append(incoming)
        try:
            self.hook(incoming)
        except Exception:  # noqa: BLE001, S110 — 실제 SDK 는 경고만 남기고 받는다
            pass
        if not incoming.rejected or self.sdk.ignores_reject:
            call = FakeCall(self, incoming.call_id, "inbound")
            self.calls.append(call)
            await self.emit(call, "call_start")

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.connected = False


class FakeSdk:
    """`sdk=` 자리에 끼우는 가짜. 속성 이름은 실제 `clawops.agent` 와 같다."""

    def __init__(self, world: World, script=GOOD, *, connect="ok", hangup="works", transfer="answered", strangers=(),
                 ignores_reject=False, extra_missing=False, call_prefix="CA", rest="works") -> None:
        self.world, self.script, self.connect, self.hangup, self.transfer = world, script, connect, hangup, transfer
        self.call_prefix, self.rest = call_prefix, rest
        self.rest_ends: list[tuple[str, str]] = []  # REST calls.update(call_id, status) — 끝이 확인되지 않은 통화를 끝냄
        self.rest_clients: list[dict] = []
        self.strangers, self.ignores_reject = tuple(strangers), ignores_reject
        self.agents: list[FakeAgent] = []
        self.sessions: list[tuple[str, dict]] = []
        self.dialed: list[tuple[str, int]] = []
        self.incoming: list[FakeIncoming] = []
        self.tool_tasks: list[asyncio.Task] = []
        self.BuiltinTool = SimpleNamespace(TRANSFER_CALL="transfer_call", ALL="all", NONE="none")
        sdk = self

        class GeminiRealtime:
            def __init__(self, *, api_key=None, system_prompt="", model="sdk-default-model", voice="Kore",
                         language="ko", greeting=True, api_version=None, input_audio_transcription=None) -> None:
                if extra_missing:
                    raise ImportError("google-genai is required for GeminiRealtime")
                sdk.sessions.append(("GeminiRealtime", {"api_key": api_key, "system_prompt": system_prompt,
                                                        "model": model, "language": language, "voice": voice,
                                                        "api_version": api_version,
                                                        "input_audio_transcription": input_audio_transcription}))

        class OpenAIRealtime:
            def __init__(self, *, api_key=None, system_prompt="", model="sdk-default-rt", voice="marin",
                         language="ko", greeting=True) -> None:
                sdk.sessions.append(("OpenAIRealtime", {"api_key": api_key, "system_prompt": system_prompt,
                                                        "model": model, "language": language, "voice": voice}))

        self.GeminiRealtime, self.OpenAIRealtime = GeminiRealtime, OpenAIRealtime

        class AsyncClawOps:  # 실제 `clawops.AsyncClawOps` 의 꼴 — calls.update 만
            def __init__(self, **kw) -> None:
                sdk.rest_clients.append(kw)
                self.calls = self

            async def update(self, call_id: str, *, status: str = "completed") -> dict:
                sdk.rest_ends.append((call_id, status))
                if sdk.rest == "fails":
                    raise AgentError(None)
                return {"callId": call_id, "status": status}

        self.AsyncClawOps = AsyncClawOps

    def ClawOpsAgent(self, **kw) -> FakeAgent:  # 실제 SDK 의 이름
        agent = FakeAgent(self, **kw)
        self.agents.append(agent)
        return agent

    @property
    def agent(self) -> FakeAgent:
        return self.agents[-1]

    @property
    def call(self) -> FakeCall:
        return self.agent.calls[0]

    async def tool_returns(self) -> list:
        return [json.loads(r) if r != TOOL_FAILED_REPLY else r for r in await asyncio.gather(*self.tool_tasks)]


def conn(**over) -> SimpleNamespace:
    values = {"id": 1, "base_url": "https://kat.invalid/", "secret_ciphertext": crypto.encrypt(SENTINEL_KEY),
              "account_id": ACCOUNT, "sender_number": "07000000000", "test_mode": True,
              "allow_numbers_json": [SENTINEL_PHONE, STAFF_NUMBER]}
    return SimpleNamespace(**(values | over))


def voice(**over) -> SimpleNamespace:
    values = {"provider": "google", "secret_ciphertext": crypto.encrypt(GOOGLE_KEY), "model": "",
              "agent_number": OUR_NUMBER}
    return SimpleNamespace(**(values | over))


def kat(world: World, sdk: FakeSdk | None, *, c=None, v=None) -> kat_sdk.KatVoice:
    return kat_sdk.KatVoice(c or conn(), v or voice(), sdk=sdk, sleep=world.sleep, clock=world.clock)


async def place(backend, spec=None, rec=None) -> Rec:
    rec = rec or Rec()
    async with asyncio.timeout(15):  # 실제 시간 막이
        await backend.place(spec or _spec(), rec)
    return rec


@pytest.fixture
def world() -> World:
    return World()


def no_leaks(caplog, *texts: object) -> None:
    assert_clean(caplog, *LEAKS)
    for text in texts:
        assert not any(leak in str(text) for leak in LEAKS)
        assert SENTINEL_DIGITS not in "".join(ch for ch in str(text) if ch.isdigit())


# ── 지시서의 다섯 ─────────────────────────────────────────────────────────


def test_backend_for_picks_by_provider_and_not_ready_without_settings(session):
    with pytest.raises(NotReady):
        voice_session.backend_for(None)
    with pytest.raises(NotReady):  # 알림 연결도 음성 설정도 없다
        voice_session.backend_for(session)
    row = connect(session, secret_ciphertext=crypto.encrypt(SENTINEL_KEY), account_id=ACCOUNT)
    with pytest.raises(NotReady):  # 음성 설정이 없다
        voice_session.backend_for(session)
    settings = VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(GOOGLE_KEY),
                             secret_last4="7777", model="", agent_number=OUR_NUMBER, voices_by_language_json={})
    session.add(settings)
    session.commit()
    picked = voice_session.backend_for(session)
    assert isinstance(picked, kat_sdk.KatVoice) and picked.model == numbers.DEFAULT_LIVE_MODEL
    assert SENTINEL_KEY not in repr(picked) and GOOGLE_KEY not in repr(picked)
    settings.provider, settings.model = "openai", "gpt-realtime-test"
    session.commit()
    assert isinstance(voice_session.backend_for(session), kat_sdk.KatVoice)
    for provider in ("dashboard", "other"):  # 대시보드 방식(Task 94)은 아직 없다
        settings.provider = provider
        session.commit()
        with pytest.raises(NotReady) as caught:
            voice_session.backend_for(session)
        assert "대시보드" in str(caught.value)
    settings.provider, settings.secret_ciphertext = "google", None  # 설정이 덜 됨 — 걸지 않는다
    session.commit()
    with pytest.raises(NotReady) as caught:
        voice_session.backend_for(session)
    assert "음성 모델 키" in str(caught.value)
    sim = SimulatedVoice([])
    with voice_session.pinned(sim):  # 시험이 끼운 것이 먼저다
        assert voice_session.backend_for(session) is sim


async def test_missing_sdk_reports_not_installed(world, session, monkeypatch):
    for name in ("clawops", "clawops.agent", "koreaaitel"):
        monkeypatch.setitem(sys.modules, name, None)  # import 가 ImportError 로 끝난다(깔려 있어도)
    backend = kat(world, None)
    assert await backend.check() == (False, "음성 SDK 가 설치돼 있지 않습니다")
    rec = Rec()
    with pytest.raises(VoiceError) as caught:
        await place(backend, rec=rec)
    assert "설치돼 있지 않습니다" in str(caught.value) and rec.log == []
    row = connect(session, secret_ciphertext=crypto.encrypt(SENTINEL_KEY), account_id=ACCOUNT)
    session.add(VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(GOOGLE_KEY),
                              secret_last4="7777", model="", agent_number=OUR_NUMBER, voices_by_language_json={}))
    session.commit()
    with pytest.raises(NotReady):
        voice_session.backend_for(session)


async def test_handlers_get_start_transcript_tool_end_in_order(world, caplog):
    caplog.set_level(logging.DEBUG)
    sdk = FakeSdk(world)
    rec = await place(kat(world, sdk))
    assert [e[:3] if e[0] == "transcript" else e[:2] for e in rec.quiet()] == [
        ("start",),
        ("transcript", "agent", SAID),  # 첫 발화가 먼저 — 그 전에 온 상대 말은 뒤로 미뤘다. 조각은 한 발화로 이었다
        ("transcript", "peer", "여보세요"),
        ("transcript", "peer", "네 맞습니다"),
        ("tool", "record_answer"),
        ("transcript", "agent", "감사합니다"),
        ("end", END_PEER),
    ]
    assert rec.of("tool")[0][2] == ANSWER and rec.log[-1] == ("end", END_PEER, 5)
    assert [round(e[3], 1) for e in rec.of("transcript")] == [0.3, 0.1, 2.0, 3.0]  # t 는 받은 뒤의 초
    assert await sdk.tool_returns() == [{"ok": True}]
    ticks = rec.of("tick")
    assert [e[1] for e in ticks] == [1.0, 2.0, 3.0, 4.0, 5.0] and ticks[-1][2] == pytest.approx(2.0)
    # 진단에서 실제로 돈 꼴 그대로: 키·계정·주소·번호, 내장 도구 없음, 녹음 끔, 훅은 연결 전에, 벨 20초
    agent = sdk.agent
    assert agent.kw["api_key"] == SENTINEL_KEY and agent.kw["account_id"] == ACCOUNT
    assert agent.kw["base_url"] == "https://kat.invalid" and agent.kw["from_"] == OUR_NUMBER
    assert agent.kw["builtin_tools"] == "none" and agent.kw["recording"] is False and agent.hook_before_connect
    assert agent.kw["prewarm_enabled"] is False  # 켜 두면 SDK 가 벨 동안 만든 첫 인사의 받아쓰기를 버린다(_BufferingCall)
    assert sdk.rest_ends == []  # 끝이 확인된 통화는 REST 로 끝내지 않는다
    assert set(agent.handlers) == {"call_start", "call_end", "call_failed", "transcript", "session_lost"}
    assert sdk.dialed == [(SENTINEL_DIGITS, 20)] and agent.disconnects == 1 and sdk.call.hangups == 0
    # 모델은 언제나 effective_model — SDK 기본값으로 두지 않는다. 지시문 + 고정 첫마디
    kind, kw = sdk.sessions[-1]
    assert kind == "GeminiRealtime" and kw["model"] == numbers.DEFAULT_LIVE_MODEL and kw["api_key"] == GOOGLE_KEY
    assert kw["language"] == "ko" and kw["voice"] == "sim-f1"  # 명세의 음성(Task 99 — 고른 음성이 세션에)
    assert kw["api_version"] == numbers.GOOGLE_LIVE_API_VERSION  # 기본(v1beta)에는 Live 모델이 없다(11-24 실측)
    assert kw["system_prompt"].startswith(_spec().instructions) and f"「{FIRST}」" in kw["system_prompt"]
    no_leaks(caplog, rec.log)


async def test_transfer_and_hangup_map_to_control(world, caplog):
    async def hang_on_answer(control, name, args):
        await control.hangup()

    sdk = FakeSdk(world)
    rec = await place(kat(world, sdk), rec=Rec(on_tool=hang_on_answer))
    assert sdk.call.hangups == 1 and rec.log[-1][:2] == ("end", END_AGENT)
    assert ("agent", "감사합니다") not in rec.spoken()  # 끊은 뒤의 말은 오지 않는다

    for outcome, started, reason in (("answered", True, END_TRANSFER), ("no_answer", True, END_TRANSFER_FAILED),
                                     ("refused", False, END_PEER)):
        seen: list[bool] = []

        async def hand_off(control, name, args, seen=seen):
            seen.append(await control.transfer(STAFF_NUMBER))
            return {"ok": seen[-1]}

        sdk = FakeSdk(world, transfer=outcome)
        rec = await place(kat(world, sdk), rec=Rec(on_tool=hand_off))
        assert seen == [started] and sdk.call.transfers == [STAFF_NUMBER]
        assert rec.log[-1][:2] == ("end", reason), outcome
        assert len([e for e in rec.log if e[0] in ("end", "failed")]) == 1
    # 시험 모드: 허용 번호가 아닌 곳으로는 넘기지 않는다(SDK 를 부르지 않음)
    seen = []

    async def hand_off_elsewhere(control, name, args):
        seen.append(await control.transfer("01000000155"))
        return {"ok": seen[-1]}

    sdk = FakeSdk(world)
    await place(kat(world, sdk, c=conn(allow_numbers_json=[SENTINEL_PHONE])), rec=Rec(on_tool=hand_off_elsewhere))
    assert seen == [False] and sdk.call.transfers == []
    no_leaks(caplog)


def test_importing_app_does_not_import_sdk():
    code = textwrap.dedent("""
        import sys
        import app.main
        from app.outreach.voice import kat_sdk, session
        bad = ("clawops", "koreaaitel")
        print("LOADED", sorted(n for n in sys.modules if any(n == b or n.startswith(b + ".") for b in bad)))
    """)
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120,
                          check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "LOADED []"


# ── 끝: 결과 모름·세션 실패는 「통화됨」이 아니다 ──────────────────────────────


@pytest.mark.parametrize("last", [(3000, "session_failed_log"), (3000, "session_lost", "go_away_failed"),
                                  (3000, "call_failed", "failed")])
async def test_answered_then_session_failed_is_lost_and_never_completed(world, caplog, last):
    """받은 뒤 AI 음성 모델 세션이 실패하면 END_LOST(일꾼은 failed 「확인 필요」로 적는다). 실제 SDK 는 세션 시작이 실패하면
    call_end 를 보내지 않는다 — 어댑터는 그 SDK 로그 줄을 보고 곧바로 끝내고, 끝 사건을 기다리지 않는다."""
    sdk = FakeSdk(world, (*TALK, last))
    rec = await place(kat(world, sdk))
    assert rec.log[-1][:2] == ("end", END_LOST) and len([e for e in rec.log if e[0] == "end"]) == 1
    assert world.ms < 3000 + 2000 and sdk.agent.disconnects == 1
    no_leaks(caplog)


async def test_session_failure_before_answer_handlers_is_a_backend_error(world, caplog):
    sdk = FakeSdk(world, ((1000, "session_failed_log"),))
    rec = Rec()
    with pytest.raises(VoiceError) as caught:
        await place(kat(world, sdk), rec=rec)
    assert rec.log == [] and world.ms < 2000
    no_leaks(caplog, caught.value, repr(caught.value))


@pytest.mark.parametrize("reason,code", [("no-answer", "no_answer"), ("busy", "busy"), ("rejected", "busy"),
                                         ("canceled", "failed"), ("failed", "failed"), ("weird value!", "failed")])
async def test_unanswered_call_maps_to_fail_codes(world, reason, code):
    sdk = FakeSdk(world, ((21000, "call_failed", reason),))
    rec = await place(kat(world, sdk))
    assert rec.kinds() == ["failed"] and rec.log[0][1] == code
    assert SENTINEL_DIGITS not in "".join(ch for ch in rec.log[0][2] if ch.isdigit())


async def test_dial_refused_by_the_platform_is_not_placed(world, caplog):
    sdk = FakeSdk(world, AgentError(422, "recipient_blocked"))
    rec = await place(kat(world, sdk))
    assert rec.log == [("failed", "failed", "dial_refused")] and sdk.agent.disconnects == 1
    no_leaks(caplog, rec.log)


@pytest.mark.parametrize("script", [AgentError(None), "hang", AgentError(503), AgentError(500), AgentError(201)])
async def test_dial_with_unknown_outcome_is_a_backend_error(world, caplog, script):
    """발신 요청의 결과를 모르면(상태 없는 예외·끝나지 않음) 걸렸을 수 있다 — VoiceError(일꾼이 「걸렸는지 확인 필요」로 적음)."""
    sdk = FakeSdk(world, script)
    with pytest.raises(VoiceError) as caught:
        await place(kat(world, sdk))
    assert sdk.agent.disconnects == 1
    no_leaks(caplog, caught.value, repr(caught.value), caught.value.__cause__, caught.value.__context__)


@pytest.mark.parametrize("outcome", [AgentError(403, "api_key_invalid"), "hang"])
async def test_connect_failure_is_not_placed(world, caplog, outcome):
    sdk = FakeSdk(world, connect=outcome)
    rec = await place(kat(world, sdk))
    assert rec.log == [("failed", "failed", "connect_failed")] and sdk.dialed == [] and sdk.agent.disconnects == 1
    no_leaks(caplog, rec.log)


async def test_no_answer_event_is_bounded(world):
    sdk = FakeSdk(world, ())  # 걸었는데 받았다·안 받았다는 사건이 오지 않는다
    with pytest.raises(VoiceError):
        await place(kat(world, sdk))
    assert world.ms <= (kat_sdk.ANSWER_WAIT_S + 1) * 1000


async def test_hangup_without_end_event_is_a_backend_error_before_the_runner_gives_up(world):
    async def hang_up(control, role, text, t):
        if role == "agent":
            await control.hangup()

    sdk = FakeSdk(world, TALK, hangup="ignored")
    rec = Rec(on_transcript=hang_up)
    with pytest.raises(VoiceError):
        await place(kat(world, sdk), rec=rec)
    assert sdk.call.hangups == 1 and [e for e in rec.log if e[0] == "end"] == []
    assert kat_sdk.SDK_HANGUP_S < kat_sdk.END_GRACE_S < call_run.HANGUP_WAIT_S  # SDK 의 끊기(mark 5초)보다 길고 일꾼보다 먼저
    assert sdk.rest_ends == [("CA0000", "completed")]  # 끝이 확인되지 않아 REST 로 끝낸다(결과는 그래도 「확인 필요」)
    hung_at = 1200 + 3300  # 받은 때 + 첫 발화가 끝났다고 본 때(조각 뒤 OPENING_GAP_S)
    assert world.ms <= hung_at + (kat_sdk.END_GRACE_S + 1) * 1000


async def test_cancel_hangs_up_and_disconnects(world):
    sdk = FakeSdk(world, TALK)
    backend = kat(world, sdk)
    task = asyncio.ensure_future(backend.place(_spec(), Rec()))
    async with asyncio.timeout(10):
        while not (sdk.agents and sdk.agent.calls and sdk.call.started):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        while not sdk.agent.disconnects:
            await asyncio.sleep(0)
    assert sdk.call.hangups == 1 and sdk.agent.disconnects == 1


async def test_handler_error_ends_the_call_and_the_model_gets_only_the_fixed_reply(world, caplog):
    async def broken(control, name, args):
        raise RuntimeError(f"저장 실패 {SENTINEL_PHONE}")

    sdk = FakeSdk(world)
    rec = Rec(on_tool=broken)
    with pytest.raises(RuntimeError, match="저장 실패"):
        await place(kat(world, sdk), rec=rec)
    assert await sdk.tool_returns() == [TOOL_FAILED_REPLY]
    assert sdk.call.hangups == 1 and sdk.agent.disconnects == 1 and [e for e in rec.log if e[0] == "end"] == []


async def test_tool_result_must_be_a_json_dict(world):
    async def bad(control, name, args):
        return ["not", "a", "dict"]

    sdk = FakeSdk(world)
    with pytest.raises(TypeError):
        await place(kat(world, sdk), rec=Rec(on_tool=bad))
    assert await sdk.tool_returns() == [TOOL_FAILED_REPLY]


async def test_opening_that_never_comes_is_an_empty_first_utterance(world):
    script = ((1000, "call_start"), (1500, "transcript", "user", "여보세요?"), (9000, "call_end"))
    rec = await place(kat(world, FakeSdk(world, script)))
    spoken = [e for e in rec.quiet() if e[0] == "transcript"]
    assert spoken[0][1:3] == ("agent", "") and spoken[0][3] == pytest.approx(OPENING_WITHIN_S, abs=0.3)
    assert spoken[1][1:3] == ("peer", "여보세요?") and rec.log[-1][:2] == ("end", END_PEER)


async def test_peer_talking_over_the_greeting_does_not_split_it(world):
    """받자마자 「여보세요」가 인사 위에 겹쳐도 첫 발화는 한 덩어리다 — 일꾼은 첫 발화 하나로 AI·기록 안내를 본다."""
    script = ((1000, "call_start"), (1300, "transcript", "assistant", OPENING[0]),
              (1400, "transcript", "user", "여보세요"), (1700, "transcript", "assistant", OPENING[1]),
              (3000, "transcript", "user", "네"), (8000, "call_end"))
    rec = await place(kat(world, FakeSdk(world, script)))
    assert rec.spoken() == [("agent", SAID), ("peer", "여보세요"), ("peer", "네")]


async def test_control_is_harmless_after_the_call_is_over(world):
    sdk = FakeSdk(world)
    rec = await place(kat(world, sdk))
    before = list(rec.log)
    await rec.control.hangup()
    assert await rec.control.transfer(STAFF_NUMBER) is False
    await rec.control.say("들리시나요")
    assert rec.log == before and sdk.call.hangups == 0 and sdk.call.transfers == []


async def test_openai_session_gets_no_google_api_version(world):
    sdk = FakeSdk(world)
    await place(kat(world, sdk, v=voice(provider="openai", model="gpt-realtime-test")))
    kind, kw = sdk.sessions[-1]
    assert kind == "OpenAIRealtime" and kw["model"] == "gpt-realtime-test" and "api_version" not in kw


async def test_say_is_not_available_and_does_nothing(world):
    async def say(control):
        await control.say("이 말은 SDK 로 시킬 수 없다")

    rec = await place(kat(world, FakeSdk(world)), rec=Rec(on_start=say))
    assert rec.log[-1][:2] == ("end", END_PEER) and "이 말은" not in json.dumps(rec.log, ensure_ascii=False)


async def test_inbound_call_while_placing_is_rejected_and_a_started_one_is_hung_up(world):
    sdk = FakeSdk(world, strangers=(1200, 1400))
    await place(kat(world, sdk))
    assert [i.reason for i in sdk.incoming] == ["rejected", "rejected"]
    sdk = FakeSdk(world, strangers=(1200,), ignores_reject=True)  # SDK 가 그래도 받아 시작된 통화
    rec = await place(kat(world, sdk))
    stranger = sdk.agent.calls[1]
    assert stranger.direction == "inbound" and stranger.hangups == 1 and rec.log[-1][:2] == ("end", END_PEER)


async def test_tools_are_registered_from_the_harness_definitions(world):
    sdk = FakeSdk(world)
    await place(kat(world, sdk))
    tools = sdk.agent.tools
    assert set(tools) == {t.name for t in _spec().tools}
    record = tools["record_answer"]
    assert list(inspect.signature(record).parameters) == ["question", "answer"]
    assert record.__annotations__ == {"question": str, "answer": str} and "질문의 답을 적는다" in record.__doc__


# ── 걸기 전 검사 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("c,v,why", [
    ({"secret_ciphertext": "not-a-cipher"}, {}, "API 키"),
    ({"account_id": ""}, {}, "Account ID"),
    ({"base_url": "https://kat.invalid/?x=1"}, {}, "주소"),
    ({}, {"secret_ciphertext": None}, "음성 모델 키"),
    ({}, {"provider": "dashboard"}, "공급자"),
    ({}, {"provider": "openai", "model": ""}, "음성 모델"),
    ({}, {"model": "bad model!"}, "음성 모델"),
    ({"sender_number": None}, {"agent_number": None}, "AI 전화 번호"),
])
async def test_check_gives_plain_reasons_and_place_refuses(world, c, v, why):
    sdk = FakeSdk(world)
    backend = kat(world, sdk, c=conn(**c), v=voice(**v))
    ok, text = await backend.check()
    assert ok is False and why in text and not any(leak in text for leak in LEAKS)
    with pytest.raises(VoiceError):
        await place(backend)
    assert sdk.agents == []


async def test_check_is_ok_with_complete_settings_and_never_raises(world, monkeypatch):
    backend = kat(world, FakeSdk(world))
    assert await backend.check() == (True, kat_sdk.READY)
    monkeypatch.setattr(kat_sdk.KatVoice, "problem", lambda self: 1 / 0)
    ok, text = await backend.check()
    assert ok is False and text


async def test_refuses_to_place_when_sdk_logs_are_not_covered(world, monkeypatch):
    monkeypatch.setattr(redact, "covers", lambda name: name != "livekit")
    sdk = FakeSdk(world)
    backend = kat(world, sdk)
    ok, text = await backend.check()
    assert ok is False and "가리개" in text
    with pytest.raises(VoiceError):
        await place(backend)
    assert sdk.agents == []


async def test_test_mode_refuses_a_number_that_is_not_allowed(world):
    sdk = FakeSdk(world)
    with pytest.raises(VoiceError):
        await place(kat(world, sdk, c=conn(allow_numbers_json=[STAFF_NUMBER])))
    assert sdk.agents == [] and sdk.dialed == []


async def test_inbound_specs_and_extra_missing(world):
    sdk = FakeSdk(world)
    with pytest.raises(ValueError):
        await place(kat(world, sdk), spec=_spec("in"))
    sdk = FakeSdk(world, extra_missing=True)
    with pytest.raises(VoiceError):
        await place(kat(world, sdk))
    assert sdk.dialed == []


async def test_keys_go_to_the_log_filter_when_the_adapter_is_made(world):
    redact.forget_secrets()
    kat(world, FakeSdk(world))
    text = redact.scrub(f"키 {SENTINEL_KEY} {GOOGLE_KEY} {ACCOUNT}", [])
    assert not any(leak in text for leak in (SENTINEL_KEY, GOOGLE_KEY, ACCOUNT))


async def test_real_sdk_is_never_used_in_tests(world, monkeypatch):
    """`sdk=` 없이 부르면 pytest 안에서는 실제 SDK 를 쓰지 않는다(망으로 나가지 않게 — 둘째 겹)."""
    backend = kat(world, None)
    rec = Rec()
    with pytest.raises(VoiceError) as caught:
        await place(backend, rec=rec)
    assert rec.log == [] and "시험" in str(caught.value)


async def test_voices_and_sample_say_the_sdk_has_none(world):
    backend = kat(world, FakeSdk(world))
    assert await backend.voices("ko") == []
    with pytest.raises(VoiceError):
        await backend.sample("Kore", "ko", "안녕하세요")


# ── 일꾼과 함께: 실제 runner·CallRun 으로 끝까지 ──────────────────────────────


@pytest.mark.parametrize("script,status", [(GOOD, "completed"), ((*TALK, (3000, "session_failed_log")), "failed")])
async def test_runner_with_the_adapter_never_records_a_failed_session_as_completed(session, sid, world, caplog,
                                                                                script, status):
    from app.outreach.voice import call_run, runner
    from tests.outreach.harness.test_gate import WORK, person
    from tests.outreach.voice.test_runner import queued, reread

    row = connect(session, secret_ciphertext=crypto.encrypt(SENTINEL_KEY), account_id=ACCOUNT)
    settings = VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(GOOGLE_KEY),
                             secret_last4="7777", model="", agent_number=OUR_NUMBER, voices_by_language_json={},
                             status="ok")
    session.add(settings)
    who = person(session, sid)
    session.commit()
    call = queued(session, who)
    sdk = FakeSdk(world, script)
    with voice_session.pinned(kat_sdk.KatVoice(row, settings, sdk=sdk, sleep=world.sleep, clock=world.clock)):
        async with asyncio.timeout(15):
            assert await runner.run_one(call.id, now=WORK) == status
    done = reread(session, call)
    assert done.status == status and sdk.dialed == [(SENTINEL_DIGITS, 20)] and sdk.agent.disconnects == 1
    if status == "failed":
        assert done.fail_reason == call_run.LOST
    else:
        assert [line["role"] for line in done.transcript_json] == ["agent", "peer", "peer", "agent"]
    no_leaks(caplog)


# ── 고침 1: 끝이 확인되지 않은 통화는 REST 로 끝낸다 · 끊기는 SDK 의 기다림보다 길게 · 상한은 받은 때부터 ─────────


async def test_slow_sdk_hangup_still_ends_the_call(world):
    """실제 SDK 의 끊기는 보낸 소리가 다 나갈 때까지 5초까지 기다린다 — 6초 걸려도 끊기를 자르지 않고 끝 사건을 받는다."""
    async def hang_up(control, role, text, t):
        if role == "agent":
            await control.hangup()

    sdk = FakeSdk(world, TALK, hangup="slow")
    rec = await place(kat(world, sdk), rec=Rec(on_transcript=hang_up))
    assert rec.log[-1][:2] == ("end", END_AGENT) and sdk.call.hangups == 1 and sdk.rest_ends == []


async def test_cancel_while_ringing_ends_the_call_by_rest_once(world, caplog):
    sdk = FakeSdk(world, ())  # 벨이 울리는 중
    task = asyncio.ensure_future(kat(world, sdk).place(_spec(), Rec()))
    async with asyncio.timeout(10):
        while not (sdk.agents and sdk.agent.calls):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        while not sdk.agent.disconnects:
            await asyncio.sleep(0)
    assert sdk.rest_ends == [("CA0000", "completed")] and sdk.call.hangups == 0  # 받기 전 끊기는 SDK 가 무시한다
    kw = sdk.rest_clients[0]
    assert kw["api_key"] == SENTINEL_KEY and kw["account_id"] == ACCOUNT and kw["base_url"] == "https://kat.invalid"
    assert kw["max_retries"] == 0 and kw["http_client"].trust_env is False
    no_leaks(caplog)


async def test_session_failure_with_a_masked_call_id_is_lost_and_ended_by_rest(world, caplog):
    """세션 실패 줄의 통화 id 는 앱 거르개가 가린 채 올 수 있다(번호처럼 보이는 숫자). 실제 SDK 는 그 뒤 끝 사건을 보내지 않고
    끊기도 듣지 않는다 — END_LOST 를 주고 REST 로 끝낸다."""
    prefix = f"CA{SENTINEL_DIGITS}_"
    assert redact.hide_phones(f"{prefix}0000") != f"{prefix}0000"
    sdk = FakeSdk(world, (*TALK, (3000, "session_failed_log")), hangup="ignored", call_prefix=prefix)
    rec = await place(kat(world, sdk))
    assert rec.log[-1][:2] == ("end", END_LOST) and world.ms < 3000 + 12000
    assert sdk.rest_ends == [(f"{prefix}0000", "completed")]
    no_leaks(caplog)


async def test_rest_end_failure_is_swallowed_and_logged_by_type_only(world, caplog):
    caplog.set_level(logging.WARNING, logger="app.outreach.voice.kat_sdk")
    sdk = FakeSdk(world, (*TALK, (3000, "session_failed_log")), hangup="ignored", rest="fails")
    rec = await place(kat(world, sdk))
    assert rec.log[-1][:2] == ("end", END_LOST) and len(sdk.rest_ends) == 1
    assert any("AgentError" in r.getMessage() for r in caplog.records if r.name == "app.outreach.voice.kat_sdk")
    no_leaks(caplog)


async def test_whole_call_limit_starts_at_answer(world):
    """벨이 오래 울린 통화도 받은 때부터 max_seconds + 여유까지는 끊지 않는다(연결·발신·벨 시간을 셈에서 뺀다)."""
    sdk = FakeSdk(world, ((35000, "call_start"), (35300, "transcript", "assistant", SAID)))
    with pytest.raises(VoiceError):
        await place(kat(world, sdk), spec=_spec(max_seconds=60))
    answered_s = 35.2  # 건 때(0.2초) + 벨 35초
    assert world.ms / 1000 == pytest.approx(answered_s + 60 + kat_sdk.OVERALL_MARGIN_S, abs=1.0)
    assert sdk.call.hangups == 1 and sdk.rest_ends == []  # 상한에 끊었고 끝이 확인됐다 — REST 는 쓰지 않는다


def test_runner_status_reads_the_voice_settings(session):
    from app.outreach.voice import runner

    assert runner.status()["backend"] == "not_ready"  # 설정이 없다
    row = connect(session, secret_ciphertext=crypto.encrypt(SENTINEL_KEY), account_id=ACCOUNT)
    session.add(VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(GOOGLE_KEY),
                              secret_last4="7777", model="", agent_number=OUR_NUMBER, voices_by_language_json={}))
    session.commit()
    assert runner.status()["backend"] == "ok"


async def test_close_while_transferring_does_not_end_the_call_by_rest(world):
    """넘기는 중이면(담당자와 이어지는 중일 수 있다) 닫을 때 끊지도 REST 로 끝내지도 않는다(고침 3)."""
    async def hand_off(control, name, args):
        return {"ok": await control.transfer(STAFF_NUMBER)}

    sdk = FakeSdk(world, (*TALK, (3500, "tool", "record_answer", ANSWER)), transfer="bridging")  # 끝 사건 없음
    task = asyncio.ensure_future(kat(world, sdk).place(_spec(), Rec(on_tool=hand_off)))
    async with asyncio.timeout(10):
        while not (sdk.agents and sdk.agent.calls and sdk.call.transfers and world.ms > 3700 + 2500):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        while not sdk.agent.disconnects:
            await asyncio.sleep(0)
    assert sdk.rest_ends == [] and sdk.call.hangups == 0


def test_shutdown_waits_long_enough_for_the_sdk_hangup():
    from app.outreach.voice import runner

    assert runner.STOP_WAIT_S > kat_sdk.SDK_HANGUP_S + 2  # 끊기(소리를 마저 보냄 5초 + 여유) + SDK 종료 프레임(2초)
