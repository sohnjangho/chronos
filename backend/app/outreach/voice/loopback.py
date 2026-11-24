"""음성 되돌이 시험(전화망 없음): 우리 AI 전화(쪽 A)와 상대 역 Gemini Live 세션(쪽 B)을 한 프로세스 안에서 이어 통화 한 통을 돌린다.
실제 전화는 걸지 않는다 — 바꾸는 것은 전화망(한국AI통신 에이전트) 하나뿐이고, 그 밖은 실제 통화와 같은 길이다.

- **쪽 A = 실제 통화 그대로**: 음성 SDK 어댑터(kat_sdk.KatVoice — 거는 통화 `place`, 받는 통화 `kat_listen.listen`)에 SDK 대신
  `_LoopSdk` 를 끼운다. 세션은 어댑터가 실제 통화처럼 짓는다(지시문 + 고정 첫마디 · 음성 · v1alpha · 받아쓰기 언어·낱말 ·
  모델 effective_model). 손잡이는 call_run.CallRun, 도구는 하네스 Toolbox(실제 DB 에 적힌다), 통화 뒤는 call_run.run_after
  (after.finish — 뒤 확인·요약·보고). 거는 통화는 초안(draft) 줄에서 명세를 runner._spec 으로 짓는다(걸기 직전 다시 보기의
  전화망 규칙 — 시험 모드·근무시간 — 은 전화망이 없으므로 건너뛴다). 받는 통화는 건 번호로 inbound.on_incoming(들어오는 문의
  판정 — 등급·범위·도구 묶음)을 그대로 부른다.
- **쪽 B = 상대 역**: 따로 연 Gemini Live 세션(인물 지시문 — 기본은 loopback_persona_kim.md, A 와 다른 음성). 도구는 SDK 내장
  hang_up 하나(상대가 끊기). 받는 통화에서는 B 가 먼저 말한다(전화를 건 쪽).
- **소리 잇기**: 두 세션 모두 전화처럼 G.711 μ-law 8kHz 20ms 쪽(160바이트)을 주고받는다(SDK 세션이 Live 의 24kHz 출력을 μ-law 로,
  μ-law 입력을 16kHz 로 바꾼다). 다리(_Bridge)가 20ms 마다 한 쪽씩 실제 시간으로 흘리고, 말이 없으면 무음 쪽을 보낸다. 끼어들기
  (barge-in)면 그쪽 줄을 비운다. 끝: A 의 끊기(end_call → control.hangup) · B 의 hang_up · 침묵(SILENCE_S) · 최대 시간(MAX_S).
- **남기는 것**(`--out-dir`, 없으면 <자료 폴더>/loopback/<시각>-<방향>): 쪽마다 Live 출력 그대로(24kHz 16비트 PCM — 다시 뽑지 않음)
  `a_agent.wav`·`b_counterpart.wav`·`mix.wav`, 차례별 시각·글 `turns.json`(앞 무음은 자르고 둘 다 말이 없는 틈은 MAX_GAP_S 까지
  줄인다 — 세 파일과 같은 시간축), 결과 `result.json`(두 쪽 받아쓰기 · 통화 줄 · 답 · 요약 · 보고 · 사용량), A 지시문
  `instructions_a.txt`(번호·키 가림). 화면에도 요약을 찍는다.
- **표시**: 통화 줄의 origin_name 을 MARK(「시험 통화 — 전화망 없음」), provider_call_id 를 `loopback-…` 로 — 앱에서 보이고 찾을 수 있다.
- **안전**: CHRONOS_DATA_DIR 가 없거나 실서버 자료 폴더면 돌지 않는다(refuse_live). 전화망 SDK 는 끼우지 않는다(_LoopSdk 에는 걸
  길이 없다 — call 은 B 세션을 열 뿐). 통로(문자·카카오·통화)가 하나라도 등록돼 있으면 돌지 않는다(도구가 만든 후속 줄은 초안·
  준비 안 됨으로 남는다). 키·번호는 찍지 않고, 음성 모델 키는 그 자료 폴더 DB 의 음성 설정에서 읽는다(Settings.secret_key 로 푼다).
- SDK 는 import 하지 않는다: 어댑터의 `kat_sdk._load()` 로 받는다(시험에서는 그 함수가 막는다 — 시험은 가짜를 넘긴다).
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
import wave
from array import array
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select, update

from app.db import get_session, init_db
from app.outreach import phone, redact
from app.outreach.harness import door, registry
from app.outreach.harness.tools import Toolbox
from app.outreach.harness.types import Ref
from app.outreach.voice import call_run, greeting, inbound, kat_sdk, numbers, runner
from app.outreach.voice.call_run import CallRun
from app.security import crypto
from app.store import outreach
from app.store.tables_outreach import (
    Contact,
    ContactReport,
    OutreachCall,
    OutreachMessage,
    VoiceSettings,
)

logger = logging.getLogger(__name__)

MARK = "시험 통화 — 전화망 없음"  # 통화 줄의 origin_name
CALL_PREFIX = "loopback-"  # 통화 줄의 provider_call_id 머리
FRAME = 160  # μ-law 8kHz 20ms 한 쪽(전화와 같은 크기)
TICK_S = 0.02
SILENCE = b"\xff" * FRAME  # μ-law 무음
PCM_RATE = 24000  # Live 출력(16비트 모노)
PCM_TICK = PCM_RATE * 2 // 50  # 20ms 의 24kHz PCM 바이트(960)
MAX_S = 240.0  # 통화 최대 시간(기본 4분)
SILENCE_S = 30.0  # 두 쪽 다 이만큼 말이 없으면 끝
DRAIN_S = 5.0  # 끊기 전에 보낸 소리가 다 나가기를 기다리는 끝(SDK 의 끊기와 같다)
FIRST_TURN_S = 8.0  # 받는 통화: B 의 첫 말이 끝나기를 기다리는 끝(어댑터의 START_WAIT_S 15초 안)
RUN_GAP = 20  # 이만큼(쪽 수 — 0.4초) 말이 끊기면 다른 차례
STALE_RAW = 5  # 줄이 이만큼 비어 있으면 남은 24kHz 조각(μ-law 나머지)을 버린다
MAX_GAP_S, LEAD_S, TAIL_S = 1.2, 0.2, 0.5  # 녹음의 틈 상한 · 앞 · 뒤 남김
AFTER_S = call_run.AFTER_WAIT_S + 30  # 받는 통화의 통화 뒤 일을 기다리는 끝
PEER_VOICES = ("Charon", "Puck")  # B 의 음성(A 와 같으면 다음 것)
SDK_DEFAULT_VOICE = "Kore"  # A 의 음성이 없을 때 SDK 가 쓰는 것
DEFAULT_PERSONA = Path(__file__).with_name("loopback_persona_kim.md")
REPO = Path(__file__).resolve().parents[4]
LIVE_DIRS = (REPO / "data", Path.home() / "projects" / "chronos" / "data")  # 실서버 자료 폴더(돌지 않는다)
LOOP_BASE_URL = "https://loopback.invalid"  # 어댑터 검사용 — 이 주소로는 아무것도 나가지 않는다(_LoopSdk 에 망이 없다)
LOOP_KEY, LOOP_ACCOUNT = "loopback-no-telephony-key", "loopback-no-telephony"
MODES = {"out": "이번 통화: 상대가 건 전화를 당신이 받았습니다.", "in": "이번 통화: 당신이 전화를 걸었습니다."}
PRICE_HINTS = ("단가", "금액", "얼마")


class Refused(Exception):
    """시험을 돌리지 않는다(까닭은 한국어, 번호·키 없음)."""


def refuse_live(env: dict | None = None) -> Path:
    """CHRONOS_DATA_DIR 가 없거나 실서버 자료 폴더(LIVE_DIRS)면 Refused. 아니면 그 폴더(절대 경로)."""
    raw = (os.environ if env is None else env).get("CHRONOS_DATA_DIR", "").strip()
    if not raw:
        raise Refused("CHRONOS_DATA_DIR 를 시험용 자료 폴더로 정해 주세요 — 실서버 자료에서는 돌지 않습니다")
    path = Path(raw).expanduser().resolve()
    if any(path == live.resolve() for live in LIVE_DIRS):
        raise Refused("실서버 자료 폴더에서는 되돌이 시험을 돌리지 않습니다 — 복사본 자료 폴더를 쓰세요")
    return path


def _db():
    return contextmanager(get_session)()


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


# ── 다리: 두 쪽의 소리를 20ms 마다 ─────────────────────────────────────


@dataclass
class _Side:
    """한 쪽(A 우리 · B 상대). queue 는 보낼 μ-law 쪽, raw 는 아직 줄에 오르지 않은 Live 출력(24kHz), played 는 쪽 번호 → 그때 나간
    24kHz 조각. spoken 은 (쪽 번호, 그 쪽이 한 말의 받아쓰기 조각)."""

    name: str
    queue: deque = field(default_factory=deque)
    raw: bytearray = field(default_factory=bytearray)
    played: dict = field(default_factory=dict)
    spoken: list = field(default_factory=list)
    usage: list = field(default_factory=list)
    session: object = None
    call: object = None
    idle: int = 0

    async def send(self, ulaw: bytes) -> None:
        for at in range(0, len(ulaw), FRAME):
            self.queue.append(bytes(ulaw[at:at + FRAME]).ljust(FRAME, b"\xff"))

    async def clear(self) -> None:
        self.queue.clear()
        self.raw.clear()

    def tap(self, pcm: bytes) -> None:
        self.raw += pcm

    def take(self) -> bytes:
        chunk = bytes(self.raw[:PCM_TICK])
        del self.raw[:PCM_TICK]
        return chunk.ljust(PCM_TICK, b"\x00")


class _Bridge:
    def __init__(self, *, max_s: float = MAX_S, silence_s: float = SILENCE_S, tick_s: float = TICK_S) -> None:
        self.a, self.b = _Side("A"), _Side("B")
        self.max_s, self.silence_s, self.tick_s = max_s, silence_s, tick_s
        self.tick = 0
        self.last_voice = 0
        self.done = asyncio.Event()
        self.reason: str | None = None
        self.error: str | None = None
        self.fed = {"A": 0, "B": 0}  # 상대에게 실제 말(무음 아님)을 넘긴 쪽 수

    def wire(self, side: _Side, session: object, call: object) -> None:
        side.session, side.call = session, call
        call.bind_transport(send_audio=side.send, send_clear=side.clear, hangup=partial(self.hangup, side))
        session.loop_tap = side.tap
        session.loop_usage = side.usage.append
        call.on("transcript", partial(self._said, side))

    async def _said(self, side: _Side, _call: object, role: str, text: str) -> None:
        if role == "assistant" and isinstance(text, str) and text:
            side.spoken.append((self.tick + max(0, len(side.queue) - 1), text))

    async def hangup(self, side: _Side) -> None:
        """SDK 의 끊기와 같다: 보낸 소리가 다 나가기를(DRAIN_S 까지) 기다린 뒤 끝낸다."""
        await self.drained(side, DRAIN_S)
        self.finish("agent_hangup" if side is self.a else "peer_hangup")

    def finish(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self.done.set()

    async def drained(self, side: _Side, limit: float) -> None:
        loop = asyncio.get_running_loop()
        until = loop.time() + limit
        while side.queue and not self.done.is_set() and loop.time() < until:
            await asyncio.sleep(self.tick_s)

    async def first_turn(self, side: _Side, limit: float) -> None:
        """그 쪽의 첫 말이 줄에 올라 다 나갈 때까지(limit 초까지)."""
        loop = asyncio.get_running_loop()
        until = loop.time() + limit
        while loop.time() < until and not self.done.is_set():
            if side.played and not side.queue and self.tick - max(side.played) >= RUN_GAP // 2:
                return
            await asyncio.sleep(self.tick_s)

    async def pump(self) -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        while not self.done.is_set():
            for side, other in ((self.a, self.b), (self.b, self.a)):
                if side.queue:
                    frame = side.queue.popleft()
                    side.played[self.tick] = side.take()
                    side.idle, self.last_voice = 0, self.tick
                    self.fed[side.name] += 1
                else:
                    frame = SILENCE
                    side.idle += 1
                    if side.idle >= STALE_RAW:
                        side.raw.clear()
                if other.session is not None:
                    try:
                        await other.session.feed_audio(frame, int(self.tick * self.tick_s * 1000))
                    except Exception as exc:  # noqa: BLE001 — 한 쪽 넣기가 실패해도 다리는 끝까지(끝은 아래 상한)
                        logger.warning("되돌이: 소리를 넘기지 못했습니다 (%s)", _kind(exc))
            self.tick += 1
            if self.tick * self.tick_s >= self.max_s:
                self.finish("max_duration")
            elif (self.tick - self.last_voice) * self.tick_s >= self.silence_s:
                self.finish("silence")
            delay = start + self.tick * self.tick_s - loop.time()
            await asyncio.sleep(max(0.0, delay))


# ── 가짜 전화망(음성 SDK 의 에이전트 자리) ─────────────────────────────


class _Ring:
    """걸려 온 전화(SDK IncomingCall 의 꼴 — 어댑터가 읽는 칸만)."""

    def __init__(self, call_id: str, from_number: str, to_number: str) -> None:
        self.call_id, self.from_number, self.to_number = call_id, from_number, to_number
        self.caller_id_restricted, self.forwarded_from, self.reason = False, None, None

    @property
    def rejected(self) -> bool:
        return self.reason is not None

    def reject(self, reason: str = "rejected"):
        self.reason = self.reason or reason
        return _Done()


class _Done:
    def __await__(self):
        return
        yield


class _LoopAgent:
    """ClawOpsAgent 자리. 연결·걸기가 망으로 나가지 않는다 — call 은 B 세션과 이은 통화를 연다."""

    def __init__(self, loop: "_LoopSdk", **kw) -> None:
        self.loop, self.kw = loop, kw
        self.factory = kw["session_factory"]
        self.registry = loop.real.ToolRegistry()
        self.handlers: dict[str, list] = {}
        self.hook = None
        self.connected = self.taken_over = False

    def tool(self, fn=None, *, behavior=None, scheduling=None):
        self.registry.register(fn)
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
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    def _session(self, call_id: str, direction: str, from_number: str, to_number: str) -> object:
        call = self.loop.real.CallSession(call_id=call_id, from_number=from_number, to_number=to_number,
                                          account_id=LOOP_ACCOUNT, direction=direction)
        for event, handlers in self.handlers.items():
            for handler in handlers:
                call.on(event, handler)
        return call

    async def call(self, to: str, *, timeout: int = 60, machine_detection=None) -> object:
        call = self._session(CALL_PREFIX + uuid.uuid4().hex[:12], "outbound", self.kw["from_"], to)
        self.loop.start(self, call, peer_first=False)
        return call

    async def ring(self, caller: str) -> bool:
        """그 번호에서 걸려 온 전화 하나. 훅이 거절하지 않으면 받아 이은 통화를 연다. 받았으면 True."""
        incoming = _Ring(CALL_PREFIX + uuid.uuid4().hex[:12], caller, self.kw["from_"])
        await self.hook(incoming)
        if incoming.rejected:
            return False
        self.loop.start(self, self._session(incoming.call_id, "inbound", caller, self.kw["from_"]), peer_first=True)
        return True


class _NoRest:
    """REST 자리(끝이 확인되지 않은 통화를 끝낼 때만) — 아무 데도 가지 않는다."""

    def __init__(self, **kw) -> None:
        self.calls = self

    async def update(self, call_id: str, *, status: str = "completed") -> dict:
        return {"callId": call_id, "status": status}


def tapped(base: type) -> type:
    """실제 SDK 세션에 귀를 단 것: Live 출력(24kHz)을 μ-law 로 바꾸기 전에 loop_tap 으로, 사용량(usage_metadata)을 loop_usage 로.
    나머지는 SDK 그대로."""

    class Tapped(base):
        loop_tap: Callable | None = None
        loop_usage: Callable | None = None
        loop_prompt: str = ""

        def __init__(self, *args, **kw) -> None:
            super().__init__(*args, **kw)
            self.loop_prompt = kw.get("system_prompt", "")
            self.loop_voice = kw.get("voice") or SDK_DEFAULT_VOICE

        async def _handle_audio_data(self, audio_data: bytes) -> None:
            if self.loop_tap is not None and self._call is not None:
                self.loop_tap(bytes(audio_data))
            await super()._handle_audio_data(audio_data)

        async def _handle_response(self, response, *, stale: bool = False) -> None:
            usage = getattr(response, "usage_metadata", None)
            if usage is not None and self.loop_usage is not None:
                self.loop_usage(_usage(usage))
            await super()._handle_response(response, stale=stale)

    return Tapped


def _usage(usage: object) -> dict:
    out = {name: getattr(usage, name, None) for name in ("prompt_token_count", "response_token_count", "total_token_count")}
    for name in ("prompt_tokens_details", "response_tokens_details"):
        details = getattr(usage, name, None) or []
        out[name] = {str(getattr(d, "modality", "?")).split(".")[-1]: getattr(d, "token_count", 0) for d in details}
    return out


class _LoopSdk:
    """어댑터가 `sdk=` 로 받는 SDK 자리. real 은 실제 `clawops.agent`(또는 시험의 가짜) — 세션·도구 등록부·통화 객체만 빌린다.
    peer 는 B 세션의 kwargs(만들 때마다 같은 것)."""

    def __init__(self, real: object, bridge: _Bridge, peer: dict, *, live: type | None = None) -> None:
        self.real, self.bridge, self.peer = real, bridge, peer
        self.GeminiRealtime = live if live is not None else tapped(real.GeminiRealtime)
        self.ToolRegistry, self.BuiltinTool = real.ToolRegistry, real.BuiltinTool
        self.AsyncClawOps = _NoRest
        self.agents: list[_LoopAgent] = []
        self.task: asyncio.Task | None = None
        self.sessions: list[object] = []

    def ClawOpsAgent(self, **kw) -> _LoopAgent:  # 실제 SDK 의 이름
        agent = _LoopAgent(self, **kw)
        self.agents.append(agent)
        return agent

    def start(self, agent: _LoopAgent, call: object, *, peer_first: bool) -> None:
        if self.task is not None:
            raise RuntimeError("되돌이 시험은 통화 한 통만 돈다")
        self.task = asyncio.ensure_future(self._talk(agent, call, peer_first))

    async def _talk(self, agent: _LoopAgent, call: object, peer_first: bool) -> None:
        """실제 SDK 의 통화 시작과 같은 차례: 세션(팩토리) → 도구 등록부 사본 → call_start → session.start → … → stop → call_end."""
        bridge, mine, peer, pump, lost = self.bridge, None, None, None, False
        try:
            peer = self.GeminiRealtime(**self.peer)  # B: 인물 지시문 · 다른 음성 · 도구는 끊기 하나
            peer.set_tool_registry(self.ToolRegistry())
            peer.set_builtin_tools({self.BuiltinTool.HANG_UP})
            peer_call = self.real.CallSession(call_id=call.call_id + "-peer", from_number="peer", to_number="peer",
                                              account_id=LOOP_ACCOUNT, direction="inbound")
            mine = agent.factory()  # 어댑터가 지은 실제 통화의 세션(지시문·음성·받아쓰기 설정)
            mine.set_tool_registry(agent.registry.fork())  # SDK 처럼 에이전트 등록부의 사본(받는 통화는 어댑터가 막아 둠)
            mine.set_builtin_tools(set())
            self.sessions = [mine, peer]
            bridge.wire(bridge.a, mine, call)
            bridge.wire(bridge.b, peer, peer_call)
            pump = asyncio.ensure_future(bridge.pump())
            await peer.start(peer_call)
            if peer_first:
                await bridge.first_turn(bridge.b, FIRST_TURN_S)
            await call._emit("call_start")
            try:
                await mine.start(call)
            except Exception as exc:  # noqa: BLE001 — 세션을 열지 못함: 실제 SDK 처럼 끝 사건 대신 세션 잃음
                lost, bridge.error = True, _kind(exc)
                bridge.finish("session_failed")
                await call._emit("session_lost", "start_failed")
            await bridge.done.wait()
        except Exception as exc:  # noqa: BLE001
            bridge.error = bridge.error or _kind(exc)
            bridge.finish("error")
            lost = True
            with contextlib.suppress(Exception):
                await call._emit("session_lost", "loopback_error")
        finally:
            bridge.finish(bridge.reason or "stopped")
            if pump is not None:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pump
            await asyncio.gather(*(_stop(s) for s in (mine, peer) if s is not None))
            if not lost:
                with contextlib.suppress(Exception):
                    await call._emit("call_end")


async def _stop(session: object) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(session.stop(), 5)


# ── 통화 한 통 ─────────────────────────────────────────────────────────


@dataclass
class Options:
    persona: str
    peer_voice: str | None = None
    max_s: float = MAX_S
    silence_s: float = SILENCE_S
    tick_s: float = TICK_S


@dataclass
class Outcome:
    call_id: int | None
    bridge: _Bridge
    instructions: str = ""
    voices: tuple[str, str] = ("", "")
    note: str = ""


def _peer_kwargs(settings: VoiceSettings, voice_key: str, persona: str, mode: str, voice: str) -> dict:
    return {"api_key": voice_key, "system_prompt": f"{persona}\n\n{MODES[mode]}", "language": "ko",
            "model": numbers.effective_model(settings.provider, settings.model), "voice": voice,
            "greeting": mode == "in", "api_version": numbers.GOOGLE_LIVE_API_VERSION,
            "input_audio_transcription": numbers.google_transcription("ko")}


def _peer_voice(chosen: str | None, ours: str | None) -> str:
    if chosen:
        return chosen
    mine = ours or SDK_DEFAULT_VOICE
    return next(v for v in PEER_VOICES if v != mine)


def _kat(conn: object, settings: VoiceSettings, sdk: _LoopSdk) -> kat_sdk.KatVoice:
    """어댑터 그대로 — 전화망 칸만 되돌이 값(키·계정·주소). 시험 모드·허용 번호·AI 전화 번호·음성 설정은 실제 값."""
    loop_conn = SimpleNamespace(base_url=LOOP_BASE_URL, secret_ciphertext=crypto.encrypt(LOOP_KEY), account_id=LOOP_ACCOUNT,
                                allow_numbers_json=conn.allow_numbers_json, test_mode=conn.test_mode,
                                sender_number=conn.sender_number)
    return kat_sdk.KatVoice(loop_conn, settings, sdk=sdk, resolve=lambda host, port: ["1.1.1.1"])  # 이름 풀이만 대신 — 나가는 것 없음


def _settings(session) -> tuple[object, VoiceSettings, str]:
    conn = outreach.connection(session)
    settings = session.get(VoiceSettings, conn.id) if conn is not None else None
    if settings is None or settings.provider != "google" or not settings.secret_ciphertext:
        raise Refused("이 자료 폴더에 구글 음성 설정(키)이 없습니다 — 음성 설정을 먼저 넣어 주세요")
    try:
        key = crypto.decrypt(settings.secret_ciphertext)
    except crypto.SecretUnreadable:
        raise Refused("저장된 음성 모델 키를 이 비밀 값으로 풀 수 없습니다") from None
    redact.add_secrets(key)
    session.expunge(settings)
    session.expunge(conn)
    return conn, settings, key


def _mark(call_id: int, call_tag: str) -> None:
    with _db() as session:
        session.execute(update(OutreachCall).where(OutreachCall.id == call_id)
                        .values(origin_name=MARK, provider_call_id=call_tag).execution_options(synchronize_session=False))
        session.commit()


CHANNEL_MODULES = "app.outreach.channels."  # 통로 모듈(불리면 스스로 등록한다 — registry 머리 글)


def _guard(modules: object = None) -> None:
    """보내는 통로가 이 프로세스에 있으면 돌지 않는다 — 도구가 만든 후속 줄(문자·통화)은 통로가 없어 초안·준비 안 됨으로 남는다."""
    loaded = sys.modules if modules is None else modules
    if registry._CHANNELS or any(name.startswith(CHANNEL_MODULES) for name in loaded):
        raise Refused("이 프로세스에 보내는 통로가 있어 돌지 않습니다(문자·전화가 나갈 수 있음)")


def _real_sdk() -> object:
    return kat_sdk._load()


async def outbound(call_id: int, opts: Options, *, real: object | None = None, live: type | None = None,
                   now: datetime | None = None) -> Outcome:
    """초안(또는 줄에 든) 거는 통화 한 줄을 되돌이로 건다 — 명세·범위·도구·손잡이·통화 뒤는 실제 통화와 같다."""
    _guard()
    base = now or datetime.now(UTC)
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        if row is None or row.direction != "out" or row.status not in ("draft", "queued"):
            raise Refused("초안이나 줄에 든 거는 통화 줄이 아닙니다")
        contact = session.get(Contact, row.contact_id) if row.contact_id is not None else None
        number = phone.normalize(contact.phone) if contact is not None and contact.phone else None
        if number is None:
            raise Refused("그 통화의 연락처 번호가 없거나 맞지 않습니다")
        conn, settings, key = _settings(session)
        agent_number = phone.normalize(numbers.effective_agent_number(conn, settings))
        if agent_number is None:
            raise Refused("AI 전화 번호가 없습니다")
        spec = runner._spec(session, row, contact, number, agent_number, settings, conn)
        scope = door.outbound_scope(session, row.schedule_id, contact.id)
        model = numbers.effective_model(settings.provider, settings.model)
        if not outreach.claim(session, "call", call_id, ("draft", "queued"), "dialing", now=base):
            raise Refused("통화 줄을 차지하지 못했습니다")
        session.commit()
    bridge = _Bridge(max_s=opts.max_s, silence_s=opts.silence_s, tick_s=opts.tick_s)
    voice = _peer_voice(opts.peer_voice, spec.voice_id)
    sdk = _LoopSdk(real if real is not None else _real_sdk(), bridge,
                   _peer_kwargs(settings, key, opts.persona, "out", voice), live=live)
    run = CallRun(call_id, spec, base, model)
    run.box = Toolbox(scope, "call", Ref("call", call_id), names=runner._NAMES, caller_class="outbound", clock=run.at)
    tag_task = asyncio.ensure_future(_tag_when_dialed(sdk, call_id))
    try:
        await runner._place(_kat(conn, settings, sdk), spec, run)
    except Exception as exc:  # noqa: BLE001 — 일꾼과 같다: 이 통화만 고장으로 닫는다
        bridge.error = bridge.error or _kind(exc)
        await run.broke()
    else:
        if not run.ended:
            await run.broke()
    finally:
        tag_task.cancel()
    if sdk.task is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(sdk.task), 15)
    _mark(call_id, _tag(sdk))
    await call_run.run_after(run)
    return Outcome(call_id, bridge, _prompt(sdk), (_voice_of(sdk), voice))


async def _tag_when_dialed(sdk: _LoopSdk, call_id: int) -> None:
    """통화가 열리면 곧바로 줄에 표시한다(통화 중에도 앱에서 시험 통화로 보이게)."""
    while sdk.task is None:
        await asyncio.sleep(0.05)
    await asyncio.to_thread(_mark, call_id, _tag(sdk))


def _tag(sdk: _LoopSdk) -> str:
    return getattr(sdk.bridge.a.call, "call_id", None) or CALL_PREFIX + "unstarted"


def _prompt(sdk: _LoopSdk) -> str:
    return getattr(sdk.sessions[0], "loop_prompt", "") if sdk.sessions else ""


def _voice_of(sdk: _LoopSdk) -> str:
    return getattr(sdk.sessions[0], "loop_voice", "") if sdk.sessions else ""


async def incoming(caller_contact_id: int, opts: Options, *, real: object | None = None,
                   live: type | None = None) -> Outcome:
    """그 연락처가 우리 AI 전화 번호로 건 통화 한 통 — 받기 판정·명세·손잡이·통화 뒤는 실제 받는 통화(inbound) 그대로."""
    _guard()
    with _db() as session:
        contact = session.get(Contact, caller_contact_id)
        caller = phone.normalize(contact.phone) if contact is not None and contact.phone else None
        if caller is None:
            raise Refused("건 사람의 연락처 번호가 없거나 맞지 않습니다")
        conn, settings, key = _settings(session)
        if conn.inbound_mode not in ("known", "all"):
            raise Refused("받는 범위가 「받지 않음」입니다 — 시험 자료의 알림 연결에서 받는 범위를 켜 주세요")
        agent_number = phone.normalize(numbers.effective_agent_number(conn, settings))
        if agent_number is None:
            raise Refused("AI 전화 번호가 없습니다")
        ours = settings.voice_unknown
    bridge = _Bridge(max_s=opts.max_s, silence_s=opts.silence_s, tick_s=opts.tick_s)
    voice = _peer_voice(opts.peer_voice, ours)
    sdk = _LoopSdk(real if real is not None else _real_sdk(), bridge,
                   _peer_kwargs(settings, key, opts.persona, "in", voice), live=live)
    taken: dict = {}

    async def on_ring(ring):
        answer = await inbound.on_incoming(ring)
        if answer is not None:
            taken["id"] = answer[1].call_id
        return answer

    kat = _kat(conn, settings, sdk)
    listening = asyncio.ensure_future(kat.listen(agent_number, on_ring))
    try:
        for _ in range(100):
            if sdk.agents and sdk.agents[-1].connected:
                break
            if listening.done():
                listening.result()
            await asyncio.sleep(0.05)
        else:
            raise Refused("되돌이 듣기가 붙지 않았습니다")
        if not await sdk.agents[-1].ring(caller):
            return Outcome(taken.get("id"), bridge, note="받기 판정이 받지 않았습니다(줄은 남았습니다)")
        await asyncio.to_thread(_mark, taken["id"], _tag(sdk))
        await asyncio.wait_for(asyncio.shield(sdk.task), opts.max_s + 60)
        follows = list(inbound._state.follows)  # 통화 뒤 일(inbound._follow → run_after)까지 기다린다
        if follows:
            await asyncio.wait_for(asyncio.gather(*follows, return_exceptions=True), AFTER_S)
    finally:
        listening.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await listening
    return Outcome(taken.get("id"), bridge, _prompt(sdk), (_voice_of(sdk), voice))


# ── 녹음 · 차례 · 결과 ─────────────────────────────────────────────────


def runs_of(ticks: list[int], gap: int = RUN_GAP) -> list[tuple[int, int]]:
    """말한 쪽 번호들 → 차례(처음, 끝 다음) — gap 쪽 넘게 끊기면 다른 차례."""
    out: list[list[int]] = []
    for tick in sorted(ticks):
        if out and tick - out[-1][1] <= gap:
            out[-1][1] = tick + 1
        else:
            out.append([tick, tick + 1])
    return [(start, end) for start, end in out]


def keep_spans(active: list[tuple[int, int]], *, max_gap: int, lead: int, tail: int) -> list[tuple[int, int]]:
    """남길 구간(쪽 번호): 앞 무음은 lead 만, 말 사이 틈은 max_gap 까지, 뒤는 tail 만. active 는 겹쳐도 된다."""
    merged: list[list[int]] = []
    for start, end in sorted(active):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if not merged:
        return []
    spans = [[max(0, merged[0][0] - lead), merged[0][1]]]
    for start, end in merged[1:]:
        gap = start - spans[-1][1]
        if gap > max_gap:
            spans[-1][1] += max_gap // 2
            spans.append([start - (max_gap - max_gap // 2), end])
        else:
            spans[-1][1] = end
    spans[-1][1] += tail
    return [(start, end) for start, end in spans]


def remap(tick: float, spans: list[tuple[int, int]]) -> float:
    """원래 시간축의 쪽 번호 → 줄인 시간축의 쪽 번호(남기지 않은 틈에 든 것은 다음 구간의 처음으로)."""
    done = 0
    for start, end in spans:
        if tick < start:
            return float(done)
        if tick <= end:
            return done + (tick - start)
        done += end - start
    return float(done)


def turns(bridge: _Bridge, spans: list[tuple[int, int]]) -> list[dict]:
    out = []
    for side in (bridge.a, bridge.b):
        found = runs_of(list(side.played))
        texts = [[] for _ in found]
        for anchor, text in side.spoken:
            index = next((i for i, (s, e) in enumerate(found) if anchor < e + RUN_GAP), len(found) - 1)
            if index >= 0:
                texts[index].append(text)
        for (start, end), parts in zip(found, texts, strict=True):
            out.append({"side": side.name, "who": "우리 AI" if side is bridge.a else "상대 역",
                        "start": round(remap(start, spans) * bridge.tick_s, 2),
                        "end": round(remap(end, spans) * bridge.tick_s, 2),
                        "text": redact.hide_phones(" ".join("".join(parts).split()))})
    return sorted(out, key=lambda t: (t["start"], t["side"]))


_QUIET = array("h", bytes(PCM_TICK))


def _track(side: _Side, spans: list[tuple[int, int]]) -> array:
    samples = PCM_TICK // 2
    out = array("h")
    for start, end in spans:
        for tick in range(start, end):
            chunk = side.played.get(tick)
            if chunk is None:
                out.extend(_QUIET)
            else:
                part = array("h")
                part.frombytes(chunk)
                if sys.byteorder != "little":
                    part.byteswap()
                out.extend(part[:samples])
    return out


def _write_wav(path: Path, samples: array) -> None:
    data = array("h", samples)
    if sys.byteorder != "little":
        data.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PCM_RATE)
        w.writeframes(data.tobytes())


def write_audio(bridge: _Bridge, out: Path) -> tuple[list[dict], dict]:
    """세 WAV 와 turns.json. (차례, 파일 정보)."""
    ticks_per_s = round(1 / bridge.tick_s)
    active = runs_of(list(bridge.a.played)) + runs_of(list(bridge.b.played))
    spans = keep_spans(active, max_gap=round(MAX_GAP_S * ticks_per_s), lead=round(LEAD_S * ticks_per_s),
                       tail=round(TAIL_S * ticks_per_s))
    a, b = _track(bridge.a, spans), _track(bridge.b, spans)
    mixed = array("h", (max(-32768, min(32767, x + y)) for x, y in zip(a, b, strict=True)))
    files = {"a_agent.wav": a, "b_counterpart.wav": b, "mix.wav": mixed}
    for name, samples in files.items():
        _write_wav(out / name, samples)
    found = turns(bridge, spans)
    (out / "turns.json").write_text(json.dumps({"rate": PCM_RATE, "seconds": round(len(a) / PCM_RATE, 2), "turns": found},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    return found, {"files": sorted([*files, "turns.json"]), "seconds": round(len(a) / PCM_RATE, 2),
                   "trimmed_from_s": round(bridge.tick * bridge.tick_s, 2)}


def _row(call_id: int) -> dict:
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        reports = session.scalars(select(ContactReport).where(ContactReport.call_id == call_id)).all()
        return {
            "id": row.id, "direction": row.direction, "status": row.status, "origin_name": row.origin_name,
            "provider_call_id": row.provider_call_id, "duration_s": row.duration_s, "fail_reason": row.fail_reason,
            "caller_class": row.caller_class, "language": row.language, "purpose": row.purpose, "questions": row.questions_json,
            "avoid": row.avoid_json, "transcript": row.transcript_json, "answers": row.answers_json,
            "summary_ko": row.summary_ko, "result_proposed": row.result_proposed,
            "events": [{k: e.get(k) for k in ("rule", "verdict", "detail")} for e in (row.harness_json or [])],
            "reports": [{"kind": r.kind, "text": r.text} for r in reports],
        }


def _messages() -> int:
    with _db() as session:
        return session.scalar(select(func.count()).select_from(OutreachMessage)) or 0


def _checks(row: dict, mode: str) -> dict:
    lines = row.get("transcript") or []
    agent = [line["text"] for line in lines if line.get("role") == "agent"]
    peer = [line["text"] for line in lines if line.get("role") == "peer"]
    first = agent[0] if agent else ""
    language = row.get("language") or "ko"
    priced = any(any(h in text for h in PRICE_HINTS) for text in peer)
    return {
        "first_line_discloses": greeting.discloses(language, first),  # 일꾼이 보는 것과 같은 검사
        "answers": len(row.get("answers") or []),
        "opt_out_marked": any(e["rule"] == "tool:mark_do_not_contact" for e in row["events"]),
        "peer_asked_price": priced,
        "agent_lines": len(agent), "peer_lines": len(peer),
        "reports": len(row.get("reports") or []), "summary": bool(row.get("summary_ko")),
        "mode": mode,
    }


def save(outcome: Outcome, mode: str, out: Path, opts: Options, messages_before: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bridge = outcome.bridge
    found, audio = write_audio(bridge, out)
    secrets = redact.secrets()
    (out / "instructions_a.txt").write_text(redact.hide_phones(redact.scrub(outcome.instructions, list(secrets))),
                                            encoding="utf-8")
    row = _row(outcome.call_id) if outcome.call_id is not None else None
    usage = {side.name: side.usage for side in (bridge.a, bridge.b)}
    result = {
        "mode": mode, "mark": MARK, "ended_by": bridge.reason, "error": bridge.error, "note": outcome.note,
        "voices": {"A": outcome.voices[0], "B": outcome.voices[1]}, "audio": audio,
        "fed_frames": bridge.fed, "turns": found, "call": row, "checks": _checks(row, mode) if row else None,
        "new_messages": _messages() - messages_before,
        "usage_totals": {name: _totals(items) for name, items in usage.items()},
        "persona_chars": len(opts.persona),
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result


def _totals(items: list[dict]) -> dict:
    """Live 의 usage_metadata(메시지마다 온 것)를 더한 값 — 쪽마다 모달리티별."""
    total: dict = {"total_token_count": 0, "prompt": {}, "response": {}}
    for item in items:
        total["total_token_count"] += item.get("total_token_count") or 0
        for key, name in (("prompt_tokens_details", "prompt"), ("response_tokens_details", "response")):
            for modality, count in (item.get(key) or {}).items():
                total[name][modality] = total[name].get(modality, 0) + (count or 0)
    return total


def show(result: dict, out: Path) -> None:
    print(f"되돌이 시험({result['mode']}) — {MARK} · 끝난 까닭 {result['ended_by']}"
          + (f" · 오류 {result['error']}" if result["error"] else ""))
    for turn in result["turns"]:
        print(f"  [{turn['start']:6.2f}–{turn['end']:6.2f}] {turn['side']} {turn['text']}")
    row = result["call"]
    if row:
        print(f"통화 줄 {row['id']}: {row['status']} · {row['duration_s']}초 · 답 {len(row['answers'] or [])} · "
              f"보고 {len(row['reports'])}")
        for answer in row["answers"] or []:
            print(f"  답: {answer.get('question')} → {answer.get('answer')} (근거 {answer.get('quote')!r})")
        print(f"  요약: {row['summary_ko']}")
        print(f"  결과 제안: {row['result_proposed']}")
        for report in row["reports"]:
            print(f"  보고[{report['kind']}]: {report['text']}")
    print(f"확인: {json.dumps(result['checks'], ensure_ascii=False)}")
    print(f"새 문자 줄: {result['new_messages']} · 파일: {out}")


# ── 명령줄 ─────────────────────────────────────────────────────────────


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.outreach.voice.loopback",
                                     description="Gemini Live 두 세션으로 거는·받는 통화 시험(전화망 없음)")
    parser.add_argument("mode", choices=("out", "in"), help="out: 초안 통화를 건다 · in: 연락처가 걸어 온다")
    parser.add_argument("--call-id", type=int, help="out: 걸 통화 초안 줄 id")
    parser.add_argument("--caller-contact", type=int, help="in: 걸어 오는 연락처 id")
    parser.add_argument("--persona", type=Path, default=DEFAULT_PERSONA, help="상대 역 지시문 파일")
    parser.add_argument("--peer-voice", help="상대 역 음성(없으면 우리 음성과 다른 것)")
    parser.add_argument("--max-seconds", type=float, default=MAX_S)
    parser.add_argument("--silence", type=float, default=SILENCE_S)
    parser.add_argument("--out-dir", type=Path, help="결과 폴더(없으면 <자료 폴더>/loopback/<시각>-<방향>)")
    args = parser.parse_args(argv)
    if (args.mode == "out") != (args.call_id is not None) or (args.mode == "in") != (args.caller_contact is not None):
        parser.error("out 은 --call-id, in 은 --caller-contact 를 씁니다")
    return args


async def _main(args: argparse.Namespace, data: Path) -> dict:
    opts = Options(args.persona.read_text(encoding="utf-8"), args.peer_voice, args.max_seconds, args.silence)
    before = _messages()
    if args.mode == "out":
        outcome = await outbound(args.call_id, opts)
    else:
        outcome = await incoming(args.caller_contact, opts)
    out = args.out_dir or data / "loopback" / f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{args.mode}"
    result = save(outcome, args.mode, out, opts, before)
    show(result, out)
    return result


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    try:
        data = refuse_live()
    except Refused as why:
        print(f"돌지 않습니다: {why}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    try:
        asyncio.run(_main(args, data))
    except Refused as why:
        print(f"돌지 않습니다: {why}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
