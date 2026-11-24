"""음성 SDK 어댑터의 받는 쪽(Task 95) — `KatVoice.listen`·듣는 동안의 `KatVoice.place`·`KatVoice.missed_calls` 의 몸통.
SDK 를 import 하지 않는다: SDK(또는 시험의 가짜)는 kat_sdk 가 불러와 넘긴다.

**control 연결은 번호당 하나다**(Task 113 고침 1 메모 — 둘째 접속이 붙으면 첫째가 밀려나고, 밀려난 쪽은 다시 붙지 않는다). 그래서:
- 번호 하나에 에이전트 하나(`AGENTS[번호]`). 듣기(listen)가 만들어 붙고, 듣는 동안 거는 통화(place)는 **같은 에이전트**로 건다
  (`agent.call` — 연결은 이미 있다). 거는 통화가 끝나도 연결은 그대로다. 듣지 않을 때의 거는 통화는 예전처럼 통화마다 에이전트를
  만들고 끝나면 끊되(kat_sdk), 그동안 `BUSY` 로 번호를 쥐어 듣기가 둘째 연결을 만들지 못하게 한다. 쓰는 쪽(듣기·거는 통화)을
  세어 마지막이 떠날 때만 연결을 닫는다.
- 통화는 한 번에 하나(`line`): SDK 의 사건·세션 팩토리·로그 줄은 지금의 줄로 보내고, 줄이 없을 때 시작된 통화는 곧바로 끊는다.
  통화 중에 울린 전화는 판정(on_incoming)을 받은 뒤에도 받지 않고 그 손잡이에 on_failed("busy") — 받는 쪽이 부재중으로 적는다.
- **도구는 통화마다**: 듣는 에이전트에는 도구를 등록하지 않고(에이전트 등록부는 모든 통화가 나눠 쓴다 — 지울 길이 없다), 세션마다
  SDK 의 공개 `ToolRegistry` 에 그 통화의 도구만 넣어 `set_tool_registry` 로 준다. SDK 는 통화를 시작할 때 에이전트 등록부의 사본으로
  세션의 등록부를 덮으므로(`_agent.py` `_start_call_session` → `_inject_session_deps`) 그 세션의 `set_tool_registry` 를 그 뒤로 막는다.
- 받기 전 훅은 비동기(SDK 는 5초까지 기다린다): 우리 시계로 DECIDE_WITHIN_S(3초) 안에 판정이 없거나·예외·None 이면 거절(SDK 의
  기본은 받기 — 닫힌 쪽으로 실패). 번호 표시 제한이면 Incoming.caller_number 는 None. 걸려 온 번호는 로그 거르개만 읽는다(최근 몇 개).
- 받은 뒤 START_WAIT_S 안에 통화가 시작되지 않으면(받는 사이 상대가 끊음 — SDK 는 아무 사건도 주지 않는다) on_failed("no_answer").
  세션을 열지 못하면 on_failed("failed"). 다른 접속에 밀려나면(`agent.taken_over`) 통화는 END_LOST, 듣기는 VoiceError 로 끝난다 —
  다시 붙기는 받는 쪽 고리가 정한다. 끝나거나 취소되면 연결을 닫는다(모든 상한은 kat_sdk 의 것 그대로).
- 앱이 꺼진 동안의 전화: SDK 의 공개 REST `AsyncClawOps(...).calls.list(to=번호, page, page_size)` 를 MAX_PAGES 쪽까지 읽어 받는
  통화 가운데 끝났는데 받지 않은 것(UNTAKEN)만 시각 창 안에서 돌려준다. 예외는 부른 쪽이 종류만 남긴다.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial

from app.notify import diagnostics
from app.notify.diagnostics_voice import (
    CONNECT_TIMEOUT_S,
    READY_ENV,
    REST_END_S,
    SDK_HANGUP_S,
    SDK_LOGGERS,
    SESSIONS,
)
from app.notify.voice_sdk_logs import _quiet_sdk, session_failure
from app.outreach import phone
from app.outreach.voice import numbers
from app.outreach.voice.kat_sdk import (
    ANSWER_WAIT_S,
    BAD_SHAPE,
    EVENTS,
    EXTRA_MISSING,
    NO_NUMBER,
    POLL_S,
    REST_MODULE,
    KatVoice,
    SimpleConn,
    _call_id,
    _Line,
    _load,
    _same_call,
    _sdk_tool,
)
from app.outreach.voice.session import (
    DECIDE_WITHIN_S,
    CallHandlers,
    CallSpec,
    Incoming,
    VoiceError,
)

AGENTS: dict[str, object] = {}  # 번호 → 그 번호의 에이전트(_Agent) 또는 BUSY
BUSY = object()  # 듣지 않을 때의 거는 통화가 제 에이전트로 그 번호를 쓰는 중
START_WAIT_S = 15.0  # 받은 뒤 통화가 시작되기를 기다리는 끝
HEARD_KEPT = 20  # 로그 거르개가 가릴 최근 걸려 온 번호 수
MAX_PAGES, PAGE_SIZE = 3, 100  # 앱이 꺼진 동안의 전화: 읽는 쪽 수 · 쪽마다 줄 수
UNTAKEN = frozenset({"no-answer", "busy", "rejected", "canceled", "failed"})  # 끝났는데 받지 않은 통화(completed 는 누가 받았다)
LINE_IN_USE = "그 번호의 음성 연결을 다른 통화가 쓰고 있어 지금은 들을 수 없습니다"
CONNECT_FAILED = "플랫폼에 연결하지 못해 걸려 오는 전화를 들을 수 없습니다"
TAKEN_OVER = "다른 접속이 이 번호의 음성 연결을 가져갔습니다"
BAD_ANSWER = "받는 통화에는 받는 통화의 명세를 돌려줘야 합니다"


@dataclass(frozen=True)
class Missed:
    """앱이 꺼진 동안 받지 못한 받는 통화 하나(REST 의 통화 목록에서). 번호를 숨겼으면 caller_number 는 None."""

    call_id: str
    caller_number: str | None = field(repr=False)
    at: datetime


@dataclass(frozen=True)
class _Stub:
    """아직 시작되지 않은 받는 통화의 자리(통화 id 만) — 닫을 때 REST 로 끝낼 수 있게."""

    call_id: str


def _keep(registry: object) -> None:
    """세션의 등록부를 SDK 가 덮지 않게 바꿔 끼우는 함수(아무것도 하지 않는다)."""


@contextmanager
def holding(number: str | None) -> Iterator[None]:
    """듣지 않을 때의 거는 통화가 제 에이전트로 그 번호를 쓰는 동안 — 듣기가 둘째 연결을 만들지 못하게."""
    mine = number is not None and number not in AGENTS
    if mine:
        AGENTS[number] = BUSY
    try:
        yield
    finally:
        if mine and AGENTS.get(number) is BUSY:
            del AGENTS[number]


class _Shared:
    """듣는 에이전트 위의 통화 한 통(_Line 에 섞어 쓴다): 에이전트를 새로 만들지 않고 닫지도 않으며, 도구는 세션마다 준다."""

    def __init__(self, shared: "_Agent", kat: KatVoice, spec: CallSpec, handlers: CallHandlers, target: str | None) -> None:
        super().__init__(kat, shared.sdk, shared.rest, spec, handlers, target)
        self.shared, self.owns_agent, self.agent = shared, False, shared.agent

    def build(self) -> None:
        self.agent = self.shared.agent  # 연결은 이미 있다(connect 는 붙어 있으면 아무것도 하지 않는다)

    def session(self) -> object:
        made = super().session()
        try:
            registry = self.sdk.ToolRegistry()
            for tool in self.spec.tools:
                registry.register(_sdk_tool(tool, self.tool))
            made.set_tool_registry(registry)
            made.set_tool_registry = _keep  # 통화를 시작할 때 SDK 가 에이전트의 (빈) 등록부로 덮지 않게
        except (AttributeError, TypeError, ValueError):
            raise VoiceError(BAD_SHAPE) from None
        return made

    async def timers(self, now: float) -> None:
        if getattr(self.agent, "taken_over", False) is True and not self.lost:  # 다른 접속에 밀려났다
            self.events.append(("session_lost", self.ours, (), now))
        await super().timers(now)


class _SharedOut(_Shared, _Line):
    """듣는 동안의 거는 통화."""


class _InLine(_Shared, _Line):
    """받은 통화 한 통 — 우리 통화는 받기 전 훅에서 받기로 한 통화 id 로 안다."""

    def __init__(self, shared: "_Agent", spec: CallSpec, handlers: CallHandlers, call_id: str) -> None:
        super().__init__(shared, shared.kat, spec, handlers, None)
        self.inbound_id = call_id
        self.dialed_at = self.clock() - ANSWER_WAIT_S + START_WAIT_S  # 시작 사건은 START_WAIT_S 만 기다린다

    def is_ours(self, sdk_call: object) -> bool:
        return sdk_call is not None and _call_id(sdk_call) == self.inbound_id

    def mine(self, sdk_call: object) -> bool:
        if not self.is_ours(sdk_call):
            return False
        if self.ours is None or isinstance(self.ours, _Stub):
            self.ours = sdk_call
        return True

    def saw(self, record: object) -> None:
        found = session_failure(record)
        if found is not None and _same_call(found[0], self.inbound_id):
            self.events.append(("session_failed", _Stub(self.inbound_id), (), self.clock()))

    async def handle(self, name: str, sdk_call: object, args: tuple, at: float) -> bool:
        if name in ("session_failed", "session_lost") and self.phase == "dialing" and self.mine(sdk_call):
            self.phase = "over"  # 손잡이가 받기 전(on_start 전)에 세션이 실패 — 받지 못한 통화
            await self.handlers.on_failed("failed", "session_failed")
            return True
        return await super().handle(name, sdk_call, args, at)

    async def close(self) -> None:
        if self.ours is None:
            self.ours = _Stub(self.inbound_id)  # 받았는데 시작되지 않은 통화도 끝이 확인되지 않으면 REST 로 끝낸다
        await super().close()


class _Agent:
    """번호 하나의 SDK 에이전트(모듈 머리 글). kat 은 듣기를 건 KatVoice(설정·시계), on_ring 은 받는 쪽의 on_incoming."""

    bounded = _Line.bounded  # 우리 시계로 limit 초까지만 기다린다(같은 몸통)

    def __init__(self, kat: KatVoice, sdk: object, rest: object, number: str,
                 on_ring: Callable[[Incoming], Awaitable[object]] | None) -> None:
        self.kat, self.sdk, self.rest, self.number, self.on_ring = kat, sdk, rest, number, on_ring
        self.setup, self.sleep, self.clock = kat._s, kat._sleep, kat._clock
        self.agent: object | None = None
        self.line: _Line | None = None
        self.users, self.connected, self.closing = 1, False, False
        self.error: BaseException | None = None
        self.heard: deque[str] = deque(maxlen=HEARD_KEPT)
        self.cutting: set[asyncio.Task] = set()

    def clean(self, text: object, limit: int = 300) -> str:
        s, line = self.setup, self.line
        found = [self.number, *self.heard, *(line.numbers if line is not None else ())]
        return diagnostics.scrub(text, secrets=[s.key, s.account_id, s.voice_key], numbers=found, limit=limit)

    def saw(self, record: object) -> None:
        line = self.line
        if line is not None:
            line.saw(record)

    def session(self) -> object:
        line = self.line
        if line is None:
            raise VoiceError(LINE_IN_USE)  # 받기로 하지 않은 통화 — SDK 가 그 통화의 세션을 열지 못한다
        return line.session()

    async def event(self, name: str, sdk_call: object, *args: object) -> None:
        line = self.line
        if line is not None:
            return await line.event(name, sdk_call, *args)
        if name == "call_start" and sdk_call is not None:  # 줄이 없는데 시작된 통화 — 곧바로 끊는다(기다리지 않는다)
            task = asyncio.ensure_future(self.cut(sdk_call))
            self.cutting.add(task)
            task.add_done_callback(self.cutting.discard)

    async def cut(self, sdk_call: object) -> None:
        try:
            await self.bounded(sdk_call.hangup(), SDK_HANGUP_S)
        except Exception:  # noqa: BLE001, S110
            pass

    # ── 받기 전 ──────────────────────────────────────────────────────

    async def screen(self, incoming: object) -> None:
        """`on_incoming` 훅(비동기): 받기로 하지 않으면 거절. 던지지 않는다(SDK 는 훅이 던지면 받는다)."""
        try:
            take = await self.decide(incoming)
        except Exception:  # noqa: BLE001 — 늦음·판정 예외: 거절
            take = False
        if not take:
            try:
                incoming.reject()
            except Exception:  # noqa: BLE001, S110
                pass

    async def decide(self, incoming: object) -> bool:
        if self.on_ring is None or self.closing or self.error is not None:
            return False
        raw = getattr(incoming, "from_number", None)
        raw = raw.strip() if isinstance(raw, str) else ""
        if raw:
            self.heard.append(raw)
        caller = None if getattr(incoming, "caller_id_restricted", None) is True or not raw else raw
        call_id = _call_id(incoming)
        answer = await self.bounded(self.on_ring(Incoming(caller, self.number, datetime.now(UTC))), DECIDE_WITHIN_S)
        if answer is None:
            return False
        try:
            spec, handlers = answer
        except (TypeError, ValueError):
            spec = handlers = None
        if not isinstance(spec, CallSpec) or spec.direction != "in":
            self.error = ValueError(BAD_ANSWER)  # 듣기가 ValueError 로 끝난다(약속)
            return False
        if self.line is not None or call_id is None or not self.connected:
            await handlers.on_failed("busy", "line_busy")  # 한 번에 한 통 — 받지 않는다
            return False
        self.line = _InLine(self, spec, handlers, call_id)
        return True

    # ── 연결 · 듣기 · 닫기 ────────────────────────────────────────────

    def build(self) -> None:
        sdk, s = self.sdk, self.setup
        try:
            kw = {"api_key": s.voice_key, "system_prompt": "", "language": "ko", "model": s.model}
            if s.provider == "google":
                kw["api_version"] = numbers.GOOGLE_LIVE_API_VERSION
            getattr(sdk, SESSIONS[s.provider])(**kw)  # 고른 모델의 묶음(extra)이 깔렸는지
            sdk.ToolRegistry  # noqa: B018 — 통화마다 줄 도구 등록부(공개 이름)가 있는지
            agent = sdk.ClawOpsAgent(api_key=s.key, account_id=s.account_id, base_url=s.base_url.rstrip("/"),
                                     from_=self.number, session_factory=self.session,
                                     builtin_tools=sdk.BuiltinTool.NONE, recording=False, prewarm_enabled=False)
            self.agent = agent
            agent.on_incoming(self.screen)  # 연결 전에 — 훅이 없으면 SDK 는 걸려 온 전화를 모두 받는다
            for name in EVENTS:
                agent.on(name)(partial(self.event, name))
        except ImportError:
            raise VoiceError(EXTRA_MISSING) from None
        except (AttributeError, TypeError, ValueError):
            raise VoiceError(BAD_SHAPE) from None

    async def serve(self) -> None:
        """붙어서 취소될 때까지 듣는다. 받은 통화는 이 고리가 돌린다(거는 통화는 place 가 돌린다)."""
        self.build()
        try:
            await self.bounded(self.agent.connect(), CONNECT_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — SDK 예외 글은 버린다
            raise VoiceError(CONNECT_FAILED) from None
        self.connected = True
        while True:
            if self.error is not None:
                raise self.error
            if getattr(self.agent, "taken_over", False) is True:
                raise VoiceError(TAKEN_OVER)
            line = self.line
            if isinstance(line, _InLine):
                try:
                    await line.pump()
                except VoiceError:
                    if line.phase != "dialing":
                        raise
                    line.phase = "over"  # 받았는데 시작 사건이 오지 않았다(받는 사이 상대가 끊음)
                    await line.handlers.on_failed("no_answer", "not_started")
                finally:
                    await asyncio.shield(line.close())
                    if self.line is line:
                        self.line = None
                continue
            await self.sleep(POLL_S)

    async def release(self) -> None:
        """쓰는 쪽 하나가 떠난다 — 마지막이면 번호를 놓고 연결을 닫는다."""
        self.users -= 1
        if self.users > 0:
            return
        if AGENTS.get(self.number) is self:
            del AGENTS[self.number]
        self.connected = False
        if self.agent is not None:
            try:
                await self.bounded(self.agent.disconnect(), SDK_HANGUP_S)
            except Exception:  # noqa: BLE001, S110
                pass


async def listen(kat: KatVoice, number: str, on_incoming: Callable[[Incoming], Awaitable[object]]) -> None:
    """KatVoice.listen 의 몸통(모듈 머리 글). 그 백엔드의 AI 전화 번호만 듣는다. 번호당 하나 — 이미 쓰는 중이면 VoiceError."""
    problem = kat.problem()
    if problem is not None:
        raise VoiceError(problem)
    key = phone.normalize(number) if isinstance(number, str) else None
    if key is None or key != kat._s.agent_number:
        raise VoiceError(NO_NUMBER)
    if key in AGENTS:
        raise VoiceError(LINE_IN_USE)
    found = await diagnostics.resolve_problem(SimpleConn(kat._s.base_url), kat._resolve)
    if found:
        raise VoiceError(found)
    if key in AGENTS:
        raise VoiceError(LINE_IN_USE)
    sdk = kat._sdk if kat._sdk is not None else _load()
    rest = kat._sdk if kat._sdk is not None else _load(REST_MODULE)
    shared = _Agent(kat, sdk, rest, key, on_incoming)
    AGENTS[key] = shared
    with _quiet_sdk(shared.clean, SDK_LOGGERS, READY_ENV, watch=shared.saw):
        try:
            await shared.serve()
        finally:
            shared.closing, shared.on_ring = True, None
            await asyncio.shield(shared.release())


async def place(kat: KatVoice, spec: CallSpec, handlers: CallHandlers, target: str) -> None:
    """듣는 동안의 거는 통화: 그 번호의 에이전트로 건다(새 연결 없음). 다른 통화가 쓰는 중이면 걸지 않는다(on_failed)."""
    shared = AGENTS.get(kat._s.agent_number)
    if (not isinstance(shared, _Agent) or shared.setup != kat._s or shared.line is not None or not shared.connected
            or shared.closing):
        await handlers.on_failed("failed", "line_busy")
        return
    line = _SharedOut(shared, kat, spec, handlers, target)
    shared.users += 1
    shared.line = line
    with _quiet_sdk(line.clean, SDK_LOGGERS, READY_ENV):
        try:
            await line.run()
        finally:
            await asyncio.shield(line.close())
            if shared.line is line:
                shared.line = None
            await asyncio.shield(shared.release())


def _missed(call: object, since: datetime, until: datetime) -> Missed | None:
    if getattr(call, "direction", None) != "inbound" or getattr(call, "status", None) not in UNTAKEN:
        return None
    at, call_id = getattr(call, "date_created", None), _call_id(call)
    if not isinstance(at, datetime) or call_id is None:
        return None
    at = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    if not since < at < until:
        return None
    raw = getattr(call, "from_", None)
    raw = raw.strip() if isinstance(raw, str) else ""
    return Missed(call_id, None if getattr(call, "caller_id_restricted", None) is True or not raw else raw, at)


async def missed_calls(kat: KatVoice, since: datetime, until: datetime) -> list[Missed]:
    """KatVoice.missed_calls 의 몸통 — 그 번호로 온 받는 통화 가운데 끝났는데 받지 않은 것(since < 때 < until)."""
    s = kat._s
    if kat.problem() is not None:
        return []
    rest = kat._sdk if kat._sdk is not None else _load(REST_MODULE)
    http = diagnostics.make_client()
    found: list[Missed] = []
    try:
        client = rest.AsyncClawOps(api_key=s.key, account_id=s.account_id, base_url=s.base_url.rstrip("/"),
                                   max_retries=0, http_client=http)
        for page in range(MAX_PAGES):
            result = await asyncio.wait_for(client.calls.list(to=s.agent_number, page=page, page_size=PAGE_SIZE),
                                            REST_END_S)
            found += [item for call in getattr(result, "data", ()) if (item := _missed(call, since, until))]
            if not result.has_next_page():
                break
    finally:
        try:
            await http.aclose()
        except Exception:  # noqa: BLE001, S110
            pass
    return found
