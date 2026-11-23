"""Task 60 — 음성 연결 진단(P5~P14). 대본대로 도는 가짜 SDK 를 `sdk=` 로 끼운다: 망·소리·실제 시간 없음(대본 시계).

가짜는 실제 SDK(clawops 0.78.0 `clawops.agent`)에서 진단이 쓰는 꼴만 흉내 낸다 — 맨 아래 시험이 그 꼴을 깔린 SDK 의 서명과
맞춰 본다(SDK 가 없으면 건너뜀). 값은 모두 가상이다. 가짜는 실제 SDK 처럼 계정·번호가 든 로그 줄과 예외 글을 남긴다.
끝나지 않는 것을 흉내 내는 곳(멈춘 연결·발신·끊기)은 가짜 스스로 실제 5초에서 끝나고, 대본 시계는 2만 번 넘게 돌지 않으며,
진단 한 번은 실제 30초 안에 끝나야 한다.
"""

import asyncio
import inspect
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict, replace
from functools import partial
from types import SimpleNamespace

import pytest

from app.notify import diagnostics
from app.notify import diagnostics_voice as dv
from app.notify.diagnostics import DEFAULT_BASE_URL, DiagnosticConn, DiagnosticStep
from app.notify.diagnostics_voice import VoiceBudget, VoiceDiag, run_voice_checks
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE, assert_clean

ACCOUNT = "AC00000000003c4d"
FROM = "07000000123"  # 에이전트에 묶을 번호(가상)
SMS_FROM = "010-0000-0177"  # 문자 발신번호(가상) — 음성 진단은 쓰지 않는다
TO = "01000000199"  # SENTINEL_PHONE 의 숫자
OTHER = "010-0000-0155"  # 허용 번호가 아닌 가상 번호
GOOGLE_KEY = "goog-test-key-QQQQ7777"
SPOKEN = f"네 제 번호는 {SENTINEL_PHONE} 입니다"  # 전사 글(가상) — 결과에 실리면 안 된다
CONN = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=SENTINEL_KEY, account_id=ACCOUNT, sender=SMS_FROM)
VOICE = VoiceDiag(provider="google", key=GOOGLE_KEY, model=None)
LEAKS = (SENTINEL_KEY, "ZZZZ9999", ACCOUNT, "3c4d", GOOGLE_KEY, "QQQQ7777", TO, "0199", FROM, "0155", "0177", "제 번호는")
SDK_LOG = logging.getLogger("clawops.agent")  # 실제 SDK 가 쓰는 로거 이름
ALL = (5, 6, 7, 8, 9, 10, 11, 12, 13, 14)
IDS = [f"P{n}" for n in ALL]
REAL_GUARD_S = 5.0  # 가짜의 「멈춤」이 스스로 끝나는 실제 시간
_NOT_FOR_PEOPLE = re.compile(r"[a-z]+_[a-z]|status=|HTTP |[A-Za-z]+(?:Error|Timeout|Exception)\b|None\b|\bcode\b")

# 통화 대본: (통화를 건 뒤 ms, 사건, 인자…)
GOOD_CALL = ((1000, "call_start"), (1400, "transcript", "assistant", "안녕하세요"), (3000, "transcript", "user", SPOKEN),
             (3500, "tool"), (4000, "transcript", "assistant", "진단을 마칩니다"), (6000, "call_end"))
TOOL_THEN_SILENCE = ((1000, "call_start"), (1400, "transcript", "assistant", "안녕하세요"), (3500, "tool"))
NEVER_ENDS = ((1000, "call_start"),)
INBOUND_TALK = ((500, "call_start"), (900, "transcript", "assistant", "안녕하세요"))


class World:
    """대본 시계. sleep 은 실제로 기다리지 않고 시계만 돌린 뒤, 그 사이에 올 사건을 차례로 낸다."""

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
        assert self.sleeps < 20_000, "진단이 끝나지 않습니다(대본 시계로 20000번 넘게 잠)"
        self.ms += round(seconds * 1000)
        await asyncio.sleep(0)
        for item in sorted(i for i in self.due if i[0] <= self.ms):
            if item in self.due:
                self.due.remove(item)
                await item[2]()

    @staticmethod
    async def hang() -> None:
        """끝나지 않는 SDK 호출 흉내. 진단이 취소하지 않아도 실제 5초 뒤에는 스스로 끝난다."""
        await asyncio.wait_for(asyncio.Event().wait(), REAL_GUARD_S)


class AgentAuthRejectedError(Exception):
    """실제 SDK 의 같은 이름 예외 꼴: `code`·`status`, 글에는 계정과 번호가 그대로 든다."""

    def __init__(self, code: object, status: int = 403) -> None:
        super().__init__(f"번호 {FROM} 는 계정 {ACCOUNT} 의 번호가 아닙니다 (키 {SENTINEL_KEY})")
        self.code, self.status = code, status


class AgentError(Exception):
    def __init__(self, status: int, code: object) -> None:
        super().__init__(f"발신 실패 ({status}): {TO} 로 걸 수 없습니다 {SENTINEL_KEY}")
        self.status, self.code = status, code


class _Done:
    def __await__(self):
        return
        yield


class FakeIncoming:
    def __init__(self, call_id: str, from_number: object, restricted: bool) -> None:
        self.call_id, self.from_number, self.to_number = call_id, from_number, FROM
        self.caller_id_restricted, self.forwarded_from = restricted, None
        self._reason: str | None = None

    @property
    def rejected(self) -> bool:
        return self._reason is not None

    def reject(self, reason: str = "rejected") -> _Done:
        self._reason = self._reason or reason
        return _Done()


class FakeCall:
    def __init__(self, agent: "FakeAgent", call_id: str, from_number: object, to_number: str, direction: str) -> None:
        self.agent, self.call_id, self.direction = agent, call_id, direction
        self.from_number, self.to_number = from_number, to_number
        self.status, self.ended_status = "queued", None
        self.started = self.over = False
        self.hangups = 0

    async def hangup(self) -> None:
        self.hangups += 1
        if self.agent.sdk.hangup == "hang":
            await World.hang()
        if self.agent.sdk.hangup == "works" and self.started and not self.over:  # 실제 SDK 도 받기 전에는 끊지 못한다
            await self.agent.emit(self, "call_end")


class FakeAgent:
    def __init__(self, sdk: "FakeSdk", *, api_key=None, account_id=None, base_url=None, from_, session=None,
                 session_factory=None, builtin_tools="all", recording=False, prewarm_enabled=True) -> None:
        self.sdk = sdk
        self.kw = {"api_key": api_key, "account_id": account_id, "base_url": base_url, "from_": from_,
                   "session": session, "session_factory": session_factory, "builtin_tools": builtin_tools,
                   "recording": recording, "prewarm_enabled": prewarm_enabled}
        self.handlers: dict[str, list] = {}
        self.tools: dict[str, object] = {}
        self.hook = None
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
        SDK_LOG.info(f"Control WS connected: wss://api.koreaaitel.com/v1/accounts/{ACCOUNT}/agent/listen?number={FROM}")
        self.sdk.marker_env.append(os.environ.get(dv.READY_ENV))
        outcome = self.sdk.connect
        if outcome == "hang":
            await World.hang()
        if isinstance(outcome, BaseException):
            SDK_LOG.error(f"Control WS 거절 — 재연결하지 않는다: {outcome}")
            raise outcome
        self.connected = True
        world = self.sdk.world
        for ms, number, *rest in self.sdk.inbound:
            world.at(world.ms + ms, partial(self.ring, number, bool(rest and rest[0])))

    async def call(self, to: str, *, timeout: int = 60, machine_detection=None) -> FakeCall:
        SDK_LOG.info(f"Outbound call initiated: {FROM} -> {to}")
        script = self.sdk.calls.pop(0) if self.sdk.calls else GOOD_CALL
        self.sdk.dialed.append((to, timeout))
        if script == "hang":
            await World.hang()
        if isinstance(script, BaseException):
            raise script
        self.kw["session_factory"]()  # 실제 SDK 의 팩토리 모드: 통화마다 세션 하나
        call = FakeCall(self, f"CA{len(self.calls):04d}", FROM, to, "outbound")
        self.calls.append(call)
        self.play(call, script)
        return call

    def play(self, call: FakeCall, script) -> None:
        world = self.sdk.world
        for ms, kind, *args in script:
            world.at(world.ms + ms, partial(self.step, call, kind, *args))

    async def step(self, call: FakeCall, kind: str, *args) -> None:
        if call.over:
            return
        if kind == "tool":
            self.sdk.tool_results.append(await self.tools["diag_fact"]())
        else:
            await self.emit(call, kind, *args)

    async def emit(self, call: FakeCall, event: str, *args) -> None:
        if event == "call_start":
            call.started = True
        if event in ("call_end", "call_failed"):
            call.over = True
            call.ended_status = call.status = args[0] if args else "completed"
        for fn in self.handlers.get(event, []):
            await fn(call, *args)

    async def ring(self, number: object, restricted: bool) -> None:
        """걸려 온 통화 하나. 실제 SDK 처럼 훅이 거절하지 않으면(예외를 던져도) 받는다."""
        SDK_LOG.info(f"Incoming call: {number} -> {FROM}")
        incoming = FakeIncoming(f"IN{len(self.sdk.incoming):04d}", number, restricted)
        self.sdk.incoming.append(incoming)
        if self.hook is not None:
            try:
                result = self.hook(incoming)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 — 실제 SDK 는 경고만 남기고 받는다
                self.sdk.hook_errors += 1
        if not incoming.rejected or self.sdk.ignores_reject:
            call = FakeCall(self, incoming.call_id, number, FROM, "inbound")
            self.calls.append(call)
            self.sdk.accepted.append(call)
            self.kw["session_factory"]()
            self.play(call, self.sdk.inbound_talk)

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.connected = False
        SDK_LOG.info("ClawOpsAgent disconnected")


class FakeSdk:
    """`sdk=` 자리에 끼우는 가짜. 속성 이름은 실제 `clawops.agent` 와 같다."""

    __version__ = "9.9.9"

    def __init__(self, world: World, *, connect="ok", calls=(), inbound=(), hangup="works",
                 inbound_talk=INBOUND_TALK, extra_missing=False, ignores_reject=False) -> None:
        self.world, self.connect, self.calls, self.inbound = world, connect, list(calls), list(inbound)
        self.hangup, self.inbound_talk, self.ignores_reject = hangup, inbound_talk, ignores_reject
        self.agents: list[FakeAgent] = []
        self.sessions: list[tuple[str, dict]] = []
        self.dialed: list[tuple[str, int]] = []
        self.incoming: list[FakeIncoming] = []
        self.accepted: list[FakeCall] = []
        self.tool_results: list[str] = []
        self.marker_env: list[str | None] = []
        self.hook_errors = 0
        self.BuiltinTool = SimpleNamespace(HANG_UP="hang_up", TRANSFER_CALL="transfer_call", ALL="all", NONE="none")
        sdk = self

        class GeminiRealtime:
            def __init__(self, *, api_key=None, system_prompt="", model="fake-live", voice="Kore", language="ko",
                         greeting=True, api_version=None) -> None:
                if extra_missing:
                    raise ImportError("google-genai is required for GeminiRealtime")
                sdk.sessions.append(("GeminiRealtime", {"api_key": api_key, "system_prompt": system_prompt,
                                                        "model": model, "language": language,
                                                        "api_version": api_version}))

        class OpenAIRealtime:
            def __init__(self, *, api_key=None, system_prompt="", model="fake-rt", voice="marin", language="ko",
                         greeting=True) -> None:
                sdk.sessions.append(("OpenAIRealtime", {"api_key": api_key, "system_prompt": system_prompt,
                                                        "model": model, "language": language}))

        self.GeminiRealtime, self.OpenAIRealtime = GeminiRealtime, OpenAIRealtime

    def ClawOpsAgent(self, **kw) -> FakeAgent:  # 실제 SDK 의 이름
        agent = FakeAgent(self, **kw)
        self.agents.append(agent)
        return agent

    @property
    def agent(self) -> FakeAgent:
        return self.agents[-1]


@pytest.fixture
def world() -> World:
    return World()


def dump(steps) -> str:
    rows = steps.values() if isinstance(steps, dict) else steps
    return json.dumps([asdict(s) for s in rows], ensure_ascii=False)


def checked(steps: list[DiagnosticStep]) -> dict[str, DiagnosticStep]:
    """모든 시험이 거치는 확인: 언제나 열 줄 · 사람이 읽는 글과 기계 낱말 · 건너뛴 줄은 ok 가 아님 · 새는 값 없음."""
    assert [s.id for s in steps] == IDS
    text = dump(steps)
    for leak in LEAKS:
        assert leak not in text, f"{leak} 가 진단 결과에 남았습니다"
    assert TO not in "".join(ch for ch in text if ch.isdigit())
    for s in steps:
        assert isinstance(s, DiagnosticStep) and s.label == dv.LABELS[s.id]
        assert re.search(r"[가-힣]", s.detail) and not _NOT_FOR_PEOPLE.search(s.detail), s.detail
        assert s.code and re.fullmatch(r"[a-z_]+", s.code), s.code
        assert not (s.skipped and s.ok) and (s.code == "ok") == s.ok
    return {s.id: s for s in steps}


async def run(world: World, sdk, *, conn=CONN, voice=VOICE, agent_number=FROM, **kw) -> dict[str, DiagnosticStep]:
    async with asyncio.timeout(30):  # 실제 시간 막이
        steps = await run_voice_checks(conn, voice, agent_number=agent_number, sdk=sdk, sleep=world.sleep,
                                       clock=world.clock, **kw)
    return checked(steps)


def codes(out: dict[str, DiagnosticStep], *ids: str) -> list[str]:
    return [out[i].code for i in ids]


# ── 계획의 여섯 ─────────────────────────────────────────────────────────────


async def test_missing_sdk_fails_p5_and_skips_rest(world, monkeypatch):
    for name in ("clawops", "clawops.agent", "koreaaitel"):
        monkeypatch.setitem(sys.modules, name, None)  # import 가 ImportError 로 끝난다(깔려 있어도)
    out = await run(world, None, steps=ALL, call_to=SENTINEL_PHONE)
    assert out["P5"].ok is False and out["P5"].skipped is False
    assert (out["P5"].code, out["P5"].detail) == ("sdk_not_installed", "음성 SDK 가 설치돼 있지 않습니다.")
    assert all(s.ok is False and s.skipped is True for k, s in out.items() if k != "P5")
    assert out["P9"].code == "skipped_no_sdk" and out["P6"].code == "skipped_not_connected"


async def test_real_calls_only_when_requested_with_number(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(5, 6, 7, 8, 10, 11), call_to=None)
    assert sdk.dialed == []
    assert out["P5"].ok and out["P11"].ok
    assert codes(out, "P6", "P7", "P8", "P10") == ["skipped_no_number"] * 4

    sdk = FakeSdk(world)
    out = await run(world, sdk, call_to=SENTINEL_PHONE)  # 기본 걸음(5·9·11)에는 거는 걸음이 없다
    assert sdk.dialed == [] and sdk.accepted == []
    assert [k for k, s in out.items() if s.code != "skipped_not_requested"] == ["P5", "P9", "P11"]

    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert sdk.dialed == [(TO, dv.RING_TIMEOUT_S)]  # 넘겨받은 그 번호로만, 한 통
    assert out["P6"].ok and out["P7"].ok and out["P8"].ok
    assert out["P5"].skipped and out["P5"].detail == diagnostics.NOT_REQUESTED


async def test_call_cap(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world)
    for _ in range(dv.MAX_CALLS):
        out = await run(world, sdk, steps=(6,), call_to=SENTINEL_PHONE, budget=budget)
        assert out["P6"].ok
    out = await run(world, sdk, steps=(6, 7, 8, 10), call_to=SENTINEL_PHONE, budget=budget)  # 4번째·5번째
    assert len(sdk.dialed) == dv.MAX_CALLS == 3
    assert out["P6"].ok is False and out["P6"].skipped is False and "통화 상한" in out["P6"].detail
    assert codes(out, "P6", "P7", "P8", "P10") == ["call_limit", "skipped_no_call", "skipped_no_call", "call_limit"]
    assert not out["P6"].maybe_sent and not budget.maybe_live
    assert budget.placed == 3  # 걸지 않은 것은 세지 않는다


async def test_caller_number_is_never_in_step_results(world):
    sdk = FakeSdk(world, inbound=[(2000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12, 13), call_to=SENTINEL_PHONE)
    assert out["P12"].ok and out["P13"].ok
    assert out["P13"].data == {"readable": True, "restricted": False}
    assert len(sdk.accepted) == 1 and sdk.accepted[0].hangups == 1  # 받은 통화는 진단이 끊는다


async def test_inbound_wait_times_out_as_fail_not_hang(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(12, 13, 14), call_to=SENTINEL_PHONE, wait_inbound_s=90)
    assert out["P12"].ok is False and out["P12"].skipped is False
    assert codes(out, "P12", "P13", "P14") == ["no_inbound", "skipped_no_inbound", "no_inbound"]
    assert "90초" in out["P12"].detail
    assert 180 <= world.clock() < 200  # 두 번의 기다림(90초씩)만큼만
    assert sdk.agent.disconnects == 1


def test_importing_module_does_not_import_sdk():
    code = ("import sys, app.notify.diagnostics_voice\n"
            "bad = [m for m in sys.modules if m.split('.')[0] in ('clawops', 'koreaaitel', 'aiohttp')]\n"
            "assert not bad, bad\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr[-800:]


# ── 걸음마다 ───────────────────────────────────────────────────────────────


async def test_default_steps_connect_bind_and_report_voices_unsupported(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk)
    assert out["P5"].ok and "9.9.9" in out["P5"].detail and out["P5"].data["sdk_version"] == "9.9.9"
    assert out["P5"].latency_ms is not None
    assert out["P11"].ok and out["P11"].data == {"method": "ClawOpsAgent(from_=…) + connect()"}
    assert out["P9"].skipped and out["P9"].code == "not_supported"
    assert out["P9"].detail == "음성 목록은 SDK 가 제공하지 않습니다 — 음성 이름은 설정에서 직접 고릅니다"
    assert any("Kore" in n for n in out["P9"].notes)
    agent = sdk.agent
    assert agent.kw["api_key"] == SENTINEL_KEY and agent.kw["account_id"] == ACCOUNT
    assert agent.kw["base_url"] == DEFAULT_BASE_URL
    assert agent.kw["from_"] == FROM  # 따로 받은 번호 — 문자 발신번호(conn.sender)가 아니다
    assert agent.kw["session"] is None and callable(agent.kw["session_factory"])
    assert agent.kw["builtin_tools"] == "none"  # 내장 도구를 모두 끈다 — 기본값에는 전환이 들어 있다
    assert agent.kw["recording"] is False
    assert {kw["api_version"] for kind, kw in sdk.sessions} == {"v1alpha"}  # 구글 Live 는 v1alpha 에만 있다(고침 2)
    assert agent.kw["prewarm_enabled"] is False  # 켜 두면 SDK 가 벨 동안 만든 첫 인사의 받아쓰기를 버린다
    assert agent.hook is not None and agent.disconnects == 1 and not agent.connected


async def test_steps_have_the_same_fields_as_the_rest_half(world):
    out = await run(world, FakeSdk(world), steps=ALL)
    rest = asdict(DiagnosticStep(id="P1", label="", ok=True, detail=""))
    for step in out.values():
        assert set(asdict(step)) == set(rest) | {"data"}
    assert set(diagnostics.LABELS).isdisjoint(dv.LABELS)


async def test_good_call_reports_latency_transcripts_and_tool(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and out["P6"].data == {"first_response_ms": 400, "cut": False}
    assert "400ms" in out["P6"].detail and not out["P6"].maybe_sent
    assert out["P7"].ok and out["P7"].data == {"events": 3, "roles": {"assistant": 2, "user": 1}}
    assert out["P8"].ok and out["P8"].data == {"tool_calls": 1}
    assert sdk.tool_results == [dv.DIAG_FACT]
    name, kw = sdk.sessions[-1]
    assert name == "GeminiRealtime" and kw["api_key"] == GOOGLE_KEY and kw["language"] == "ko"
    assert dv.FIRST_LINES["ko"] in kw["system_prompt"] and "diag_fact" in kw["system_prompt"]
    assert kw["model"] == "fake-live"  # 모델을 주지 않으면 SDK 기본값
    assert not any(ch.isdigit() for ch in kw["system_prompt"])  # 지시문에 번호가 없다
    assert sdk.agent.calls[0].hangups == 0  # 스스로 끝난 통화는 끊지 않는다


async def test_first_line_says_the_call_is_not_recorded(world):
    """진단은 녹음하지 않고(recording=False) 받아쓰기 글도 남기지 않는다 — 첫마디가 「기록됩니다」라고 하면 거짓이다."""
    assert dv.FIRST_LINES == {"ko": "안녕하세요, ChronOS 연결 진단 전화입니다. 이 통화는 녹음하지 않습니다.",
                              "en": "Hello, this is a ChronOS connection test call. This call is not recorded."}
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(6, 10), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and out["P10"].ok and sdk.agent.kw["recording"] is False
    prompts = [kw["system_prompt"] for _, kw in sdk.sessions]
    assert any(dv.FIRST_LINES["ko"] in p for p in prompts) and any(dv.FIRST_LINES["en"] in p for p in prompts)
    assert not any("기록됩니다" in p or "is recorded" in p for p in prompts)


async def test_call_is_hung_up_soon_after_the_tool_was_called(world):
    """내장 끊기 도구를 주지 않으므로 통화는 진단이 끊는다: 도구가 불리고 WRAP_UP_S 뒤."""
    sdk = FakeSdk(world, calls=[TOOL_THEN_SILENCE])
    out = await run(world, sdk, steps=(6, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and out["P6"].data["cut"] is False and out["P8"].ok
    assert sdk.agent.calls[0].hangups == 1
    assert 3.5 + dv.WRAP_UP_S <= world.clock() < 3.5 + dv.WRAP_UP_S + 2


async def test_voice_model_and_provider_are_passed_through(world):
    sdk = FakeSdk(world)
    voice = VoiceDiag(provider="openai", key=GOOGLE_KEY, model="some-model.v1")
    out = await run(world, sdk, voice=voice, steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P6"].ok
    assert {name for name, _ in sdk.sessions} == {"OpenAIRealtime"}
    assert sdk.sessions[-1][1]["model"] == "some-model.v1"


async def test_second_language_call(world):
    sdk = FakeSdk(world, calls=[GOOD_CALL, ((1000, "call_start"), (1300, "transcript", "assistant", "Hello"))])
    out = await run(world, sdk, steps=(6, 10), call_to=SENTINEL_PHONE, lang2="en")
    assert out["P6"].ok and out["P10"].ok and len(sdk.dialed) == 2
    assert out["P10"].data == {"first_response_ms": 300, "cut": False}
    kw = sdk.sessions[-1][1]
    assert kw["language"] == "en" and dv.FIRST_LINES["en"] in kw["system_prompt"]
    assert "diag_fact" not in kw["system_prompt"]
    assert sdk.agent.calls[1].hangups == 1  # 첫 응답을 본 뒤 진단이 끊는다


@pytest.mark.parametrize("lang2", ["ko", "xx", "", None, 7, "EN ", ["en"]])
async def test_unknown_second_language_is_skipped_without_a_call(world, lang2):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(10,), call_to=SENTINEL_PHONE, lang2=lang2)
    assert out["P10"].code == "skipped_no_language" and sdk.dialed == []


async def test_call_events_without_transcript_or_tool(world):
    sdk = FakeSdk(world, calls=[((1000, "call_start"), (5000, "call_end"))])
    out = await run(world, sdk, steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and out["P6"].data["first_response_ms"] is None
    assert codes(out, "P7", "P8") == ["no_transcript", "no_tool_call"]
    assert not out["P7"].skipped and not out["P8"].skipped


@pytest.mark.parametrize(("reason", "code", "text"), [
    ("no-answer", "no_answer", "받지 않았습니다"), ("busy", "busy", "통화 중"), ("rejected", "declined", "거절"),
    ("canceled", "canceled", "취소"), ("failed", "call_failed", "실패"),
    (f"blocked {SENTINEL_PHONE}", "call_failed", "실패"), (None, "call_failed", "실패")])
async def test_unanswered_call_is_a_fixed_korean_failure(world, reason, code, text):
    sdk = FakeSdk(world, calls=[((20_000, "call_failed", reason),)])
    out = await run(world, sdk, steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].code == code and not out["P6"].skipped and text in out["P6"].detail
    assert not out["P6"].maybe_sent  # 끝난 것이 확인됐다
    assert codes(out, "P7", "P8") == ["skipped_no_call"] * 2
    assert sdk.agent.calls[0].hangups == 0


@pytest.mark.parametrize(("status", "vendor", "code", "text"), [
    (422, "recipient_blocked", "bad_request", "수신 거부"), (401, None, "bad_key", "키"),
    (429, "", "rate_limited", "잦습니다")])
async def test_dial_refused_by_the_platform_is_a_clean_failure(world, status, vendor, code, text):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[AgentError(status, vendor)])
    out = await run(world, sdk, steps=(6, 7, 10), call_to=SENTINEL_PHONE, budget=budget)
    assert out["P6"].code == code and text in out["P6"].detail and "발신 요청을 받지 않았습니다" in out["P6"].detail
    assert not out["P6"].maybe_sent and not budget.maybe_live  # 걸리지 않았다
    assert any(f"HTTP {status}" in n for n in out["P6"].notes)  # 기계 글은 접는 줄에
    assert out["P7"].code == "skipped_no_call"
    assert out["P10"].ok  # 다음 통화는 따로 본다


@pytest.mark.parametrize("status", [500, 503, 201])
async def test_dial_error_with_a_non_4xx_status_is_of_unknown_outcome(world, status):
    """4xx 만 「걸리지 않음」. 5xx 는 통화를 만든 뒤 프록시가 낸 것일 수 있고, 201 인데 오류면(답을 읽지 못함) 통화는 만들어졌다."""
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[AgentError(status, f"x {SENTINEL_KEY}")])
    out = await run(world, sdk, steps=(6, 10), call_to=SENTINEL_PHONE, budget=budget)
    assert out["P6"].code == "unknown" and out["P6"].maybe_sent and budget.maybe_live
    assert any(f"HTTP {status}" in n for n in out["P6"].notes)
    assert out["P10"].code == "skipped_stopped"


async def test_dial_error_of_unknown_outcome_stops_and_flags(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[RuntimeError(f"boom {SENTINEL_KEY} {TO}")], inbound=[(1000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(6, 7, 10, 12), call_to=SENTINEL_PHONE, budget=budget)
    assert out["P6"].code == "unknown" and out["P6"].maybe_sent and "걸렸을 수도" in out["P6"].detail
    assert "예외: RuntimeError" in " ".join(out["P6"].notes)
    assert codes(out, "P7", "P10", "P12") == ["skipped_no_call", "skipped_stopped", "skipped_stopped"]
    assert len(sdk.dialed) == 1 and budget.maybe_live and sdk.accepted == []


# ── 상한과 끊기 ─────────────────────────────────────────────────────────────


async def test_call_that_never_ends_is_cut_at_60_seconds(world):
    sdk = FakeSdk(world, calls=[NEVER_ENDS])
    out = await run(world, sdk, steps=(6, 7), call_to=SENTINEL_PHONE)
    call = sdk.agent.calls[0]
    assert call.hangups == 1 and call.over
    assert out["P6"].ok and out["P6"].data["cut"] is True and "60초" in out["P6"].detail
    assert not out["P6"].maybe_sent
    assert 60 <= world.clock() < 62 and dv.CALL_CUT_S == 60
    assert dv.RING_TIMEOUT_S + dv.WRAP_UP_S < dv.CALL_CUT_S  # 벨 시간은 60초 안에 든다


@pytest.mark.parametrize("hangup", ["ignored", "hang"])
async def test_call_that_cannot_be_cut_stops_everything_after_it(world, hangup):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[NEVER_ENDS], hangup=hangup, inbound=[(1000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(6, 10, 12, 14), call_to=SENTINEL_PHONE, budget=budget)
    assert len(sdk.dialed) == 1
    assert out["P6"].ok is False and out["P6"].code == "cut_unconfirmed" and out["P6"].maybe_sent
    assert codes(out, "P10", "P12", "P14") == ["skipped_stopped"] * 3
    assert sdk.agent.disconnects == 1 and world.clock() < 80 and budget.maybe_live
    assert sdk.accepted == []  # 그 사이 걸려 온 통화는 받지 않는다


async def test_unanswered_call_without_any_event_is_given_up_at_60_seconds(world):
    sdk = FakeSdk(world, calls=[()])  # 사건이 하나도 오지 않는다(받지도 실패하지도 않음)
    out = await run(world, sdk, steps=(6, 7, 8, 10), call_to=SENTINEL_PHONE)
    assert out["P6"].code == "cut_unconfirmed" and out["P6"].maybe_sent
    assert codes(out, "P7", "P8") == ["skipped_no_call"] * 2 and out["P7"].maybe_sent and out["P8"].maybe_sent
    assert out["P10"].code == "skipped_stopped" and len(sdk.dialed) == 1 and sdk.agent.calls[0].hangups == 1


async def test_dial_that_hangs_times_out(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=["hang"])
    out = await run(world, sdk, steps=(6, 10), call_to=SENTINEL_PHONE, budget=budget)
    assert out["P6"].code == "dial_timeout" and out["P6"].maybe_sent and budget.maybe_live
    assert out["P10"].code == "skipped_stopped" and len(sdk.dialed) == 1  # 걸렸는지 알 수 없으므로 더 걸지 않는다
    assert world.clock() < 30


async def test_cancel_mid_call_hangs_up_and_disconnects(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[NEVER_ENDS])
    reached = asyncio.Event()

    async def mark() -> None:
        reached.set()

    world.at(5000, mark)
    task = asyncio.ensure_future(run(world, sdk, steps=(6,), call_to=SENTINEL_PHONE, budget=budget))
    await asyncio.wait_for(reached.wait(), 10)
    assert budget.maybe_live  # 통화가 살아 있는 동안
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    assert sdk.agent.calls[0].hangups == 1 and sdk.agent.disconnects == 1
    assert not budget.maybe_live  # 끊긴 것이 확인됐다
    assert dv.READY_ENV not in os.environ and SDK_LOG.filters == []


async def test_cancel_when_the_call_cannot_be_cut_leaves_the_flag(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world, calls=[NEVER_ENDS], hangup="ignored")
    reached = asyncio.Event()

    async def mark() -> None:
        reached.set()

    world.at(5000, mark)
    task = asyncio.ensure_future(run(world, sdk, steps=(6,), call_to=SENTINEL_PHONE, budget=budget))
    await asyncio.wait_for(reached.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    assert budget.maybe_live and sdk.agent.disconnects == 1


async def test_inbound_cap_is_two_per_budget(world):
    budget = VoiceBudget()
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE), (30_000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12, 14), call_to=SENTINEL_PHONE, budget=budget)
    assert out["P12"].ok and out["P14"].ok and budget.received == dv.MAX_INBOUND == 2
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12,), call_to=SENTINEL_PHONE, budget=budget)  # 세 번째
    assert out["P12"].code == "inbound_limit" and "받는 통화 상한" in out["P12"].detail and sdk.accepted == []


# ── 실제 행동을 켜는 값 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("steps", ["6", "5,6", "P6", ["6"], ["P6"], (True,), (6.0,), 6, None, (5, "6"), (4, 6), (6, 15),
                                   {6: True}.items()])
async def test_only_plain_integers_select_steps(world, steps):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=steps, call_to=SENTINEL_PHONE)
    assert sdk.agents == [] and sdk.dialed == [] and sdk.sessions == []  # SDK 를 건드리지 않는다
    assert all(s.code == "bad_steps" and not s.ok and not s.skipped for s in out.values())


async def test_no_steps_is_ten_skipped_rows(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(), call_to=SENTINEL_PHONE)
    assert all(s.code == "skipped_not_requested" for s in out.values()) and sdk.agents == []


@pytest.mark.parametrize("call_to", ["true", "false", "1", "", True, 1, 1000000199, 15880199, ["010-0000-0199"],
                                     "010-0000-019", "+1 202 555 0199", "060-700-0199"])
async def test_only_a_callable_number_string_enables_calls(world, call_to):
    sdk = FakeSdk(world, inbound=[(100, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(6, 7, 8, 10, 12, 13, 14), call_to=call_to)
    assert sdk.dialed == [] and sdk.accepted == []
    assert codes(out, "P6", "P7", "P8", "P10", "P12", "P13", "P14") == ["skipped_no_number"] * 7


@pytest.mark.parametrize("wait", ["90", True, 0, -5, 90.0, None])
async def test_bad_inbound_wait_does_not_open_a_window(world, wait):
    sdk = FakeSdk(world, inbound=[(100, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12, 14), call_to=SENTINEL_PHONE, wait_inbound_s=wait)
    assert codes(out, "P12", "P14") == ["bad_wait"] * 2 and not out["P12"].skipped and sdk.accepted == []


async def test_inbound_wait_is_capped(world):
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(12,), call_to=SENTINEL_PHONE, wait_inbound_s=100_000)
    assert world.clock() < dv.MAX_WAIT_INBOUND_S + 5 and "180초" in out["P12"].detail


@pytest.mark.parametrize("flag", [True, "false", "", None, 1, 0])
async def test_worker_connected_refuses_without_touching_the_sdk(world, flag):
    """control 연결은 번호당 하나 — 일꾼이 붙어 있다고 들으면(False 가 아닌 모든 값) 연결하지 않는다."""
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=ALL, call_to=SENTINEL_PHONE, worker_connected=flag)
    assert sdk.agents == [] and sdk.sessions == [] and sdk.dialed == []
    assert out["P5"].code == "worker_connected" and not out["P5"].skipped and "AI 전화" in out["P5"].detail
    assert all(out[i].code == "skipped_not_connected" for i in IDS if i not in ("P5", "P9"))

    out = await run(world, sdk, steps=(6,), call_to=SENTINEL_PHONE, worker_connected=flag)
    assert out["P6"].skipped and dv.WORKER_CONNECTED in out["P6"].detail  # P5 줄이 없으면 까닭을 그 줄에 적는다


# ── 받는 통화 ───────────────────────────────────────────────────────────────


async def test_second_inbound_call_is_rejected_before_answer(world):
    sdk = FakeSdk(world, inbound=[(2000, SENTINEL_PHONE), (40_000, "+82 10-0000-0199")])
    out = await run(world, sdk, steps=(12, 13, 14), call_to=SENTINEL_PHONE)
    assert out["P12"].ok and out["P13"].ok and out["P14"].ok
    assert out["P14"].data == {"method": "IncomingCall.reject", "reason": "rejected"}
    assert [i.rejected for i in sdk.incoming] == [False, True] and len(sdk.accepted) == 1


async def test_one_window_takes_one_call(world):
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE), (1500, SENTINEL_PHONE), (5000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12,), call_to=SENTINEL_PHONE)
    assert out["P12"].ok and len(sdk.accepted) == 1 and [i.rejected for i in sdk.incoming] == [False, True, True]


async def test_reject_alone_rejects_the_first_call(world):
    sdk = FakeSdk(world, inbound=[(2000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(14,), call_to=SENTINEL_PHONE)
    assert out["P14"].ok and sdk.accepted == [] and world.clock() < 10


async def test_stranger_is_never_answered(world):
    sdk = FakeSdk(world, inbound=[(1000, OTHER), (2000, OTHER), (3000, "1588-0155")])
    out = await run(world, sdk, steps=(12, 13), call_to=SENTINEL_PHONE, wait_inbound_s=30)
    assert sdk.accepted == [] and all(i.rejected for i in sdk.incoming)
    assert out["P12"].code == "not_allowed_caller" and "3통" in out["P12"].detail
    assert out["P13"].ok and out["P13"].data["readable"] is True


@pytest.mark.parametrize("number", ["", None, "anonymous", "0", 1000000199])
async def test_unreadable_caller_is_not_answered(world, number):
    sdk = FakeSdk(world, inbound=[(1000, number, True)])
    out = await run(world, sdk, steps=(12, 13), call_to=SENTINEL_PHONE, wait_inbound_s=30)
    assert sdk.accepted == [] and sdk.incoming[0].rejected and sdk.hook_errors == 0
    assert codes(out, "P12", "P13") == ["caller_unreadable"] * 2
    assert out["P13"].data == {"readable": False, "restricted": True}


async def test_inbound_outside_a_window_is_rejected(world):
    """거는 통화를 하는 동안, 그리고 받는 걸음을 고르지 않았을 때 걸려 온 통화는 받지 않는다(실제 SDK 는 훅이 없으면 받는다)."""
    sdk = FakeSdk(world, inbound=[(500, SENTINEL_PHONE), (2000, OTHER)])
    out = await run(world, sdk, steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and sdk.accepted == [] and [i.rejected for i in sdk.incoming] == [True, True]


async def test_hook_rejects_even_when_the_incoming_object_is_broken(world, monkeypatch):
    """실제 SDK 는 훅이 예외를 던지면 통화를 받는다 — 훅은 무엇이 틀려도 던지지 않고 거절한다."""

    class Broken(FakeIncoming):
        @property
        def from_number(self):
            raise RuntimeError(f"no number {SENTINEL_PHONE}")

        @from_number.setter
        def from_number(self, value):
            pass

    monkeypatch.setattr(sys.modules[__name__], "FakeIncoming", Broken)
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=(12,), call_to=SENTINEL_PHONE, wait_inbound_s=30)
    assert sdk.hook_errors == 0 and sdk.incoming[0].rejected and sdk.accepted == []
    assert out["P12"].code == "caller_unreadable"


async def test_hook_rejects_when_anything_else_about_the_call_is_broken(world, monkeypatch):
    class NoId(FakeIncoming):
        @property
        def call_id(self):
            raise RuntimeError(f"no id {SENTINEL_PHONE}")

        @call_id.setter
        def call_id(self, value):
            pass

    monkeypatch.setattr(sys.modules[__name__], "FakeIncoming", NoId)
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)])
    hooked: list[bool] = []

    async def ring(self, number, restricted):
        incoming = NoId("IN0", number, restricted)
        self.hook(incoming)  # 던지면 이 시험이 떨어진다
        hooked.append(incoming.rejected)

    monkeypatch.setattr(FakeAgent, "ring", ring)
    out = await run(world, sdk, steps=(12,), call_to=SENTINEL_PHONE, wait_inbound_s=10)
    assert hooked == [True] and not out["P12"].ok


async def test_reject_that_the_sdk_does_not_record_fails_p14(world, monkeypatch):
    class Deaf(FakeIncoming):
        def reject(self, reason: str = "rejected") -> _Done:  # 거절을 불러도 SDK 가 표시하지 않는다
            return _Done()

    monkeypatch.setattr(sys.modules[__name__], "FakeIncoming", Deaf)
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)], inbound_talk=((10_000, "call_start"),))
    out = await run(world, sdk, steps=(14,), call_to=SENTINEL_PHONE)
    assert out["P14"].code == "reject_not_applied" and not out["P14"].ok and world.clock() < 8


async def test_accepted_call_that_never_starts_fails(world):
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)], inbound_talk=())
    out = await run(world, sdk, steps=(12, 14), call_to=SENTINEL_PHONE)
    assert codes(out, "P12", "P14") == ["accepted_not_started", "skipped_stopped"]


async def test_rejected_call_that_still_starts_is_hung_up_and_fails(world):
    sdk = FakeSdk(world, inbound=[(1000, SENTINEL_PHONE)], ignores_reject=True)  # 거절했는데도 SDK 가 받는다
    out = await run(world, sdk, steps=(14,), call_to=SENTINEL_PHONE)
    assert out["P14"].code == "reject_not_applied" and not out["P14"].ok
    assert sdk.accepted[0].hangups == 1 and sdk.accepted[0].over  # 시작돼 버린 통화는 끊는다


async def test_call_that_starts_outside_a_window_is_hung_up(world):
    """SDK 가 거절을 듣지 않아 창 밖의 통화가 시작돼도(훅이 늦을 때의 실제 SDK) 곧바로 끊는다."""
    sdk = FakeSdk(world, calls=[NEVER_ENDS], inbound=[(2000, OTHER)], ignores_reject=True)
    out = await run(world, sdk, steps=(6,), call_to=SENTINEL_PHONE)
    assert out["P6"].ok and sdk.incoming[0].rejected
    assert sdk.accepted[0].hangups == 1 and sdk.accepted[0].over


# ── 연결 실패 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("vendor", "code", "text"), [
    ("api_key_invalid", "bad_key", "키를 받아들이지 않았습니다"), ("api_key_missing", "bad_key", "전달되지 않았습니다"),
    (None, "rejected", "연결을 거절"), (f"weird {SENTINEL_KEY}", "rejected", "연결을 거절"),
    ("개인 정보가 든 글", "rejected", "연결을 거절"), (["api_key_invalid"], "rejected", "연결을 거절")])
async def test_rejected_key_fails_p5_with_fixed_text(world, vendor, code, text, caplog):
    caplog.set_level(logging.DEBUG)
    sdk = FakeSdk(world, connect=AgentAuthRejectedError(vendor, 401))
    out = await run(world, sdk, steps=ALL, call_to=SENTINEL_PHONE)
    assert out["P5"].code == code and not out["P5"].skipped and text in out["P5"].detail
    assert any("AgentAuthRejectedError" in n and "HTTP 401" in n for n in out["P5"].notes)
    shown = vendor if vendor in ("api_key_invalid", "api_key_missing") else "-"  # 낱말 꼴이 아닌 코드는 남기지 않는다
    assert any(f"code={shown} " in n for n in out["P5"].notes)
    assert all(out[i].code == "skipped_not_connected" for i in IDS if i not in ("P5", "P9"))
    assert sdk.dialed == [] and sdk.agent.disconnects == 1
    assert_clean(caplog, ACCOUNT, GOOGLE_KEY, FROM)


@pytest.mark.parametrize("vendor", ["number_not_owned", "number_missing"])
async def test_rejected_number_fails_p11_not_the_connection(world, vendor):
    sdk = FakeSdk(world, connect=AgentAuthRejectedError(vendor))
    out = await run(world, sdk, steps=(5, 6, 11), call_to=SENTINEL_PHONE)
    assert out["P5"].ok and "닿았지만" in out["P5"].detail
    assert out["P11"].code == "bad_number" and not out["P11"].skipped and "AI 전화 번호" in out["P11"].detail
    assert out["P6"].code == "skipped_not_connected" and sdk.dialed == []


async def test_connect_that_hangs_times_out(world):
    sdk = FakeSdk(world, connect="hang")
    out = await run(world, sdk, steps=(5, 6, 11), call_to=SENTINEL_PHONE)
    assert codes(out, "P5", "P6", "P11") == ["timeout", "skipped_not_connected", "skipped_not_connected"]
    assert world.clock() < 30 and sdk.agent.disconnects == 1


async def test_connect_error_is_reported_by_type_only(world):
    sdk = FakeSdk(world, connect=OSError(f"cannot reach wss://x/{ACCOUNT}?number={FROM} key={SENTINEL_KEY}"))
    out = await run(world, sdk, steps=(5,))
    assert out["P5"].code == "network" and any("OSError" in n for n in out["P5"].notes)


async def test_missing_model_extra_fails_p5(world):
    sdk = FakeSdk(world, extra_missing=True)
    out = await run(world, sdk, steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P5"].code == "sdk_extra_missing" and sdk.agents == [] and out["P6"].skipped


async def test_sdk_with_another_shape_fails_p5_without_raising(world):
    out = await run(world, SimpleNamespace(__version__=f"1.0 {SENTINEL_KEY}"), steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P5"].code == "sdk_signature" and out["P6"].skipped


@pytest.mark.parametrize(("change", "code"), [
    ({"base_url": "http://api.koreaaitel.com"}, "bad_base_url"), ({"base_url": "https://127.0.0.1"}, "bad_base_url"),
    ({"base_url": f"https://u:{SENTINEL_KEY}@api.koreaaitel.com"}, "bad_base_url"),
    ({"key": "short"}, "bad_key"), ({"key": ""}, "bad_key"), ({"account_id": "AC1"}, "bad_account"),
    ({"key": None}, "bad_key")])
async def test_bad_connection_is_stopped_before_the_sdk(world, change, code):
    sdk = FakeSdk(world)
    out = await run(world, sdk, conn=replace(CONN, **change), steps=(5, 6, 11), call_to=SENTINEL_PHONE)
    assert out["P5"].code == code
    assert sdk.agents == [] and sdk.sessions == [] and out["P6"].skipped and out["P11"].skipped


@pytest.mark.parametrize("number", [None, "", "abc", "060-700-0199", 7000000123, 15880123, True])
async def test_agent_number_must_be_given_explicitly(world, number):
    """문자 발신번호(conn.sender)로 대신하지 않는다."""
    sdk = FakeSdk(world)
    out = await run(world, sdk, agent_number=number, steps=(5, 11))
    assert out["P5"].code == "no_agent_number" and sdk.agents == [] and out["P11"].skipped


async def test_host_that_resolves_inside_is_stopped(world, monkeypatch):
    monkeypatch.setattr(diagnostics, "RESOLVE", lambda host, port: ["10.0.0.7"])
    sdk = FakeSdk(world)
    out = await run(world, sdk, steps=(5,))
    assert out["P5"].code == "bad_base_url" and "내부망" in out["P5"].detail and sdk.agents == []

    def fails(host, port):
        raise OSError(f"no such host {SENTINEL_KEY}")

    monkeypatch.setattr(diagnostics, "RESOLVE", fails)
    out = await run(world, sdk, steps=(5,))
    assert out["P5"].code == "resolve_failed" and sdk.agents == []


@pytest.mark.parametrize("voice", [
    VoiceDiag(provider="azure", key=GOOGLE_KEY, model=None), VoiceDiag(provider="google", key="short", model=None),
    VoiceDiag(provider="google", key=None, model=None), VoiceDiag(provider="google", key=GOOGLE_KEY, model="bad model!"),
    VoiceDiag(provider="google", key=GOOGLE_KEY, model=7), VoiceDiag(provider=["google"], key=GOOGLE_KEY, model=None)])
async def test_bad_voice_settings_are_stopped_before_the_sdk(world, voice):
    sdk = FakeSdk(world)
    out = await run(world, sdk, voice=voice, steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P5"].code == "bad_voice" and sdk.agents == []


# ── 새지 않음 · 뒷정리 ────────────────────────────────────────────────────────


async def test_nothing_sensitive_in_results_or_logs_on_a_full_run(world, caplog):
    caplog.set_level(logging.DEBUG)
    sdk = FakeSdk(world, inbound=[(70_000, SENTINEL_PHONE), (71_000, OTHER), (110_000, SENTINEL_PHONE)])
    out = await run(world, sdk, steps=ALL, call_to=SENTINEL_PHONE)
    assert all(out[i].ok for i in IDS if i != "P9"), dump(out)
    assert len(sdk.dialed) == 2 and len(sdk.accepted) == 1
    assert len([r for r in caplog.records if r.name == "clawops.agent"]) >= 6  # 가짜 SDK 가 남긴 줄이 실제로 잡혔다
    assert_clean(caplog, ACCOUNT, GOOGLE_KEY, FROM, "0155")
    assert SDK_LOG.filters == []  # 끝나면 거르개를 뗀다


async def test_sdk_exception_logged_with_traceback_is_reduced_to_its_type(world, caplog):
    caplog.set_level(logging.DEBUG)

    class Loud(FakeSdk):
        def ClawOpsAgent(self, **kw):
            try:
                raise ValueError(f"bad {SENTINEL_KEY} {FROM} {ACCOUNT}")
            except ValueError:
                SDK_LOG.exception("에이전트를 만들지 못함 %s", SENTINEL_PHONE)
            return super().ClawOpsAgent(**kw)

    await run(world, Loud(world), steps=(5,))
    assert any("ValueError" in r.getMessage() for r in caplog.records)
    assert_clean(caplog, ACCOUNT, GOOGLE_KEY, FROM)


async def test_keys_are_registered_before_the_sdk_is_touched(world):
    from app.outreach import redact

    seen: list[tuple[str, ...]] = []

    class Peek(FakeSdk):
        def ClawOpsAgent(self, **kw):
            seen.append(redact.secrets())
            return super().ClawOpsAgent(**kw)

    await run(world, Peek(world), steps=(5,))
    assert {SENTINEL_KEY, ACCOUNT, GOOGLE_KEY} <= set(seen[0])


@pytest.mark.parametrize("before", [None, "/tmp/somewhere-else"])
async def test_ready_marker_is_off_during_the_run_and_restored_after(world, monkeypatch, before):
    if before is None:
        monkeypatch.delenv(dv.READY_ENV, raising=False)
    else:
        monkeypatch.setenv(dv.READY_ENV, before)
    sdk = FakeSdk(world)
    await run(world, sdk, steps=(5,))
    assert sdk.marker_env == [""] and os.environ.get(dv.READY_ENV) == before

    sdk = FakeSdk(world, connect=OSError("x"))
    await run(world, sdk, steps=(5,))
    assert sdk.marker_env == [""] and os.environ.get(dv.READY_ENV) == before


def test_values_do_not_show_in_repr():
    text = repr(VOICE) + repr(VoiceBudget())
    assert GOOGLE_KEY not in text and "QQQQ7777" not in text


async def test_unexpected_error_inside_a_step_is_a_failure_not_an_exception(world):
    class Boom(FakeSdk):
        def ClawOpsAgent(self, **kw):
            raise ValueError(f"bad {SENTINEL_KEY} {FROM}")

    out = await run(world, Boom(world), steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P5"].code == "unknown" and any("ValueError" in n for n in out["P5"].notes) and out["P6"].skipped


# ── 실제 SDK 와 맞는지(깔려 있을 때만) ──────────────────────────────────────────


async def test_real_sdk_is_never_loaded_in_tests(world, monkeypatch):
    monkeypatch.setenv(dv.READY_ENV, "")  # import 가 준비 표시 파일을 건드리지 않게
    pytest.importorskip("clawops.agent", exc_type=ImportError)
    out = await run(world, None, steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P5"].code == "sdk_blocked_in_tests" and out["P6"].skipped


def test_what_we_call_exists_in_the_installed_sdk(monkeypatch):
    """가짜가 받는 인자(= 진단이 넘기는 인자)와 부르는 이름이 깔린 SDK 의 서명에 있다. 에이전트를 만들거나 연결하지 않는다."""
    monkeypatch.setenv(dv.READY_ENV, "")
    real = pytest.importorskip("clawops.agent", exc_type=ImportError)
    builtin = pytest.importorskip("clawops.agent._builtin_tools", exc_type=ImportError)
    sdk = FakeSdk(World())

    def params(fn) -> set[str]:
        return set(inspect.signature(fn).parameters) - {"self", "sdk"}

    assert params(FakeAgent.__init__) <= params(real.ClawOpsAgent.__init__)
    assert params(FakeAgent.call) <= params(real.ClawOpsAgent.call)
    assert params(FakeAgent.tool) <= params(real.ClawOpsAgent.tool)
    for name in ("tool", "on", "on_incoming"):
        assert callable(getattr(real.ClawOpsAgent, name))
    for name in ("connect", "disconnect", "call"):
        assert inspect.iscoroutinefunction(getattr(real.ClawOpsAgent, name))
    assert inspect.iscoroutinefunction(real.CallSession.hangup) and params(real.CallSession.hangup) == set()
    assert params(sdk.GeminiRealtime.__init__) <= params(real.GeminiRealtime.__init__)
    assert params(sdk.OpenAIRealtime.__init__) <= params(real.OpenAIRealtime.__init__)
    assert real.BuiltinTool.NONE.value == sdk.BuiltinTool.NONE
    assert builtin.resolve_builtin_tools(real.BuiltinTool.NONE) == set()  # 내장 도구가 하나도 없다
    assert real.BuiltinTool.TRANSFER_CALL in builtin.resolve_builtin_tools(real.BuiltinTool.ALL)  # 기본값에는 전환이 있다
    incoming = real.IncomingCall(call_id="IN0", from_number="", to_number="")
    assert incoming.rejected is False and incoming.caller_id_restricted is False
    incoming.reject()
    assert incoming.rejected is True and incoming.reject_reason == "rejected"
    assert {"call_id", "direction"} <= params(real.CallSession.__init__)
    assert isinstance(__import__("clawops").__version__, str)
    assert {"clawops", "clawops.agent"} <= set(dv.SDK_LOGGERS) and dv.SDK_MODULE == "clawops.agent"
