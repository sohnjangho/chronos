"""가짜 통화(Task 87): 대본대로 「상대와 음성 모델」이 움직이는 VoiceBackend. 실제 통화·소리·네트워크·SDK 가 없다.
통화 통로의 시험(88·89·95·97), 개발 콘솔의 격자, 상황 대본이 쓴다 — 그래서 app 코드에 둔다. 끼우는 곳은 session.pinned 하나
(시험·모래상자 프로세스에서만 열린다).

대본은 걸음의 목록이고, 끝 걸음에서 한 통이 끝난다(한 대본에 여러 통을 이어 적을 수 있다 — segments).
- 거는 통화 한 통: `NoAnswer()` | `Busy()` | `Failed(detail)` 하나(받지 않은 통화), 또는 통화 걸음들 + 끝(`Hangup(by)` · `Lost()` ·
  `Crash()`). `place` 를 부를 때마다 다음 거는 통화 묶음을 쓴다. 남은 묶음이 없으면 ScriptExhausted(건 번호는 dialed 에 남는다).
- 받는 통화 한 통: `Ring(caller_number, at)` + (받았을 때 돌) 통화 걸음들 + 끝. `listen` 이 남은 벨을 차례로 울린다.
- 통화 걸음: `Opening(text)`(모델이 실제로 한 첫 발화 — 없으면 spec.first_line 그대로. 빈 글은 첫 발화가 없었음) ·
  `Say(role, text, t)`(모델·상대의 말, t 는 통화가 시작된 뒤의 초 — 없으면 지금) · `Tool(name, args)`(모델의 도구 호출) ·
  `Silence(seconds)` · `Transfer(outcome)`(다음 control.transfer 의 결과: answered · no_answer · refused — 없으면 refused) ·
  `Hold()`(release() 나 control.hangup() 까지 멈춤).
- 대본은 만들 때 검사하고(틀리면 ValueError — 몇 번째 걸음인지 말하고, 받은 값은 싣지 않는다) 깊이 복사해 둔다.

시계는 걸음이 민다: 실제 시계·난수·잠들기를 쓰지 않아 같은 대본은 늘 같은 사건을 낸다. `tick`(초)마다 on_tick 이 오고, 같은
시각이면 시계 알림이 말보다 먼저다. 가짜는 최대 통화 시간·침묵을 대신 지키지 않는다(일꾼의 몫 — 넘겼는지는 calls[n].overran).

달아나지 않게 묶어 둔 것: 대본 길이 MAX_STEPS · 통화 한 통의 대본 시계 CLOCK_CEILING_S · 통화 한 통의 손잡이 호출 수
max_events(넘으면 VoiceError — 손잡이가 say 를 되풀이해 부르는 꼴) · 소리 샘플 길이 SAMPLE_MAX_CHARS. 실제 시간을 기다리는 곳은
셋뿐이고 모두 asyncio.wait_for 로 끝이 있다: 받기 전 판정(decide_within), Hold 와 hold_line(HOLD_LIMIT_S — 넘으면 VoiceError).

남기는 것: calls(통화마다: spec · said · tool_results · ended · failed · transferred_to · seconds · overran · broke) ·
said(코드가 say 로 시킨 말) · tool_results · ended · failed · dialed · transfers · transferred_to · rejected · screen_errors ·
listens · samples · live · peak_live · unused(쓰지 않은 통화 묶음). model_saw() 는 음성 모델에게 준 글 전부(첫마디·지시문·도구
정의·도구 결과·say 로 시킨 말 — 상대 말과 번호는 주지 않는다), leaks() 는 그 가운데 번호처럼 보이는 것이 든 글의 이름표.
"""

import asyncio
import copy
import json
import math
import re
import wave
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO

from app.outreach.voice.session import (
    DECIDE_WITHIN_S,
    END_AGENT,
    END_LOST,
    END_PEER,
    END_TRANSFER,
    END_TRANSFER_FAILED,
    TOOL_FAILED_REPLY,
    CallHandlers,
    CallSpec,
    Incoming,
    VoiceError,
    VoiceInfo,
    has_phone,
    tool_reply,
)

MAX_STEPS = 2000  # 대본 하나의 걸음 수
CLOCK_CEILING_S = 7200.0  # 통화 한 통의 대본 시계(초)
MAX_EVENTS = 10_000  # 통화 한 통에서 손잡이를 부르는 수
HOLD_LIMIT_S = 10.0  # Hold·hold_line 이 실제로 기다리는 끝(초)
SAMPLE_RATE = 8000
SAMPLE_MAX_CHARS = 100  # 샘플 길이는 글자마다 0.1초, 이만큼까지
RING_AT = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)  # Ring 에 시각을 적지 않았을 때(시계를 읽지 않는다)
TRANSFER_OUTCOMES = ("answered", "no_answer", "refused")
BREAKABLE = ("check", "voices", "sample")
SIM_VOICES: tuple[VoiceInfo, ...] = (  # 가상 음성 — 실제 제공사 음성 이름이 아니다
    VoiceInfo("sim-f1", "가상 여성 1", "female"),
    VoiceInfo("sim-m1", "가상 남성 1", "male"),
    VoiceInfo("sim-n1", "가상 중성 1", "unknown"),
)
_CODE = re.compile(r"[a-z_]+")


@dataclass(frozen=True)
class Say:
    role: str  # agent(모델) | peer(상대)
    text: str
    t: float | None = None


@dataclass(frozen=True)
class Opening:
    text: str


@dataclass(frozen=True)
class Tool:
    name: str
    args: dict


@dataclass(frozen=True)
class Silence:
    seconds: float


@dataclass(frozen=True)
class Hangup:
    by: str  # peer | agent(모델이 끝냄)


@dataclass(frozen=True)
class Lost:
    pass


@dataclass(frozen=True)
class NoAnswer:
    pass


@dataclass(frozen=True)
class Busy:
    pass


@dataclass(frozen=True)
class Failed:
    detail: str = "failed"  # 정해 둔 코드(소문자·밑줄) — 번호가 들어갈 수 없다


@dataclass(frozen=True)
class Crash:
    pass


@dataclass(frozen=True)
class Hold:
    pass


@dataclass(frozen=True)
class Transfer:
    outcome: str


@dataclass(frozen=True)
class Ring:
    caller_number: str | None  # 번호를 숨긴 전화는 None
    at: datetime | None = None

    def __repr__(self) -> str:
        return f"Ring(caller={'withheld' if self.caller_number is None else 'shown'})"


Step = Say | Opening | Tool | Silence | Hangup | Lost | NoAnswer | Busy | Failed | Crash | Hold | Transfer | Ring
_UNANSWERED = (NoAnswer, Busy, Failed)
_ENDS = (Hangup, Lost, Crash, *_UNANSWERED)


class ScriptExhausted(VoiceError):
    """대본에 없는 통화가 걸렸다(또는 받은 통화의 대본이 없다) — 숨기지 않고 드러낸다."""


@dataclass(frozen=True)
class ToolResult:
    """모델이 부른 도구 하나와 모델에게 돌아간 결과. offered 는 그 통화가 받은 도구 이름이었는가."""

    name: str
    args: dict
    result: dict
    offered: bool


@dataclass
class CallRecord:
    """통화 한 통에 남은 것."""

    number: int
    spec: CallSpec
    said: list[str] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    seen: list[tuple[str, str]] = field(default_factory=list)  # 모델에게 준 글(이름표, 글) — 준 차례대로
    ended: tuple[str, int] | None = None
    failed: tuple[str, str] | None = None
    transferred_to: str | None = None
    seconds: float = 0.0
    broke: bool = False  # 끝 손잡이 없이 예외로 끝남

    @property
    def overran(self) -> bool:
        return self.seconds > self.spec.max_seconds


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _step_problem(step: object) -> str | None:
    """걸음 하나가 틀렸으면 그 까닭(받은 값은 싣지 않는다)."""
    match step:
        case Say():
            if step.role not in ("agent", "peer"):
                return "Say 의 역할은 agent·peer 가운데 하나입니다"
            if not isinstance(step.text, str) or not step.text.strip():
                return "Say 의 말이 비었습니다"
            if step.t is not None and not (_number(step.t) and step.t >= 0):
                return "Say 의 시각은 0 이상의 초입니다"
        case Opening():
            if not isinstance(step.text, str):
                return "Opening 의 말은 글입니다"
        case Tool():
            if not isinstance(step.name, str) or not step.name.strip():
                return "Tool 의 이름이 비었습니다"
            if not isinstance(step.args, dict):
                return "Tool 의 인자는 dict 입니다"
        case Silence():
            if not (_number(step.seconds) and step.seconds > 0):
                return "Silence 는 0보다 큰 초입니다"
        case Hangup():
            if step.by not in ("peer", "agent"):
                return "Hangup 은 peer·agent 가운데 하나가 끊습니다"
        case Failed():
            if not isinstance(step.detail, str) or not _CODE.fullmatch(step.detail):
                return "Failed 의 까닭은 정해 둔 코드(소문자·밑줄)입니다"
        case Transfer():
            if step.outcome not in TRANSFER_OUTCOMES:
                return "Transfer 의 결과는 answered·no_answer·refused 가운데 하나입니다"
        case Ring():
            if step.caller_number is not None and not (isinstance(step.caller_number, str) and step.caller_number.strip()):
                return "Ring 의 숨긴 번호는 None 으로 둡니다"
            if step.at is not None and not (isinstance(step.at, datetime) and step.at.tzinfo is not None):
                return "Ring 의 시각에는 시간대가 있어야 합니다"
        case Lost() | NoAnswer() | Busy() | Crash() | Hold():
            pass
        case _:
            return "걸음이 아닌 것이 있습니다"
    return None


def segments(script: Sequence[Step]) -> list[list[Step]]:
    """대본을 통화 한 통씩으로 나눈다(검사도 한다 — 틀리면 ValueError). 받는 통화 묶음은 Ring 으로 시작한다.
    어댑터의 시험(Task 113)도 이것으로 같은 대본을 가짜 SDK 의 사건으로 바꾼다."""
    steps = list(script)
    if len(steps) > MAX_STEPS:
        raise ValueError(f"대본이 너무 깁니다(걸음 {MAX_STEPS}개까지)")
    parts: list[list[Step]] = []
    current: list[Step] | None = None
    clock = 0.0
    for index, step in enumerate(steps, 1):
        where = f"대본 {index}번째 걸음"
        problem = _step_problem(step)
        if problem:
            raise ValueError(f"{where}: {problem}")
        if isinstance(step, Ring):
            if current is not None:
                if len(current) != 1 or not isinstance(current[0], Ring):
                    raise ValueError(f"{where}: 통화가 끝나기 전에 벨이 울릴 수 없습니다")
                parts.append(current)  # 받지 않을 벨(통화 걸음 없음)
            current, clock = [step], 0.0
            continue
        if current is None:
            current, clock = [], 0.0
        if isinstance(step, _UNANSWERED) and current:
            raise ValueError(f"{where}: 받지 않음·통화 중·실패는 거는 통화의 첫 걸음에만 옵니다")
        if isinstance(step, Opening) and any(not isinstance(earlier, Ring) for earlier in current):
            raise ValueError(f"{where}: Opening 은 통화의 첫 걸음입니다")
        if isinstance(step, Say) and step.t is not None:
            if step.t < clock:
                raise ValueError(f"{where}: 시각이 앞 걸음보다 이릅니다")
            clock = float(step.t)
        elif isinstance(step, Silence):
            clock += step.seconds
        if clock > CLOCK_CEILING_S:
            raise ValueError(f"{where}: 통화 한 통의 대본 시계는 {CLOCK_CEILING_S:.0f}초까지입니다")
        current.append(step)
        if isinstance(step, _ENDS):
            parts.append(current)
            current = None
    if current is not None:
        if len(current) != 1 or not isinstance(current[0], Ring):
            raise ValueError(f"대본 {len(steps)}번째 걸음 뒤에 통화가 끝나지 않습니다(끝 걸음이 없음)")
        parts.append(current)
    return parts


class _Call:
    """돌고 있는 통화 한 통 — 손잡이에게는 CallControl 이다."""

    def __init__(self, sim: "SimulatedVoice", record: CallRecord, handlers: CallHandlers, steps: list[Step]) -> None:
        self._sim, self._record, self._handlers, self._steps = sim, record, handlers, steps
        self.clock = 0.0
        self.over = False
        self._last_spoke = 0.0
        self._next_tick = 1
        self._reason: str | None = None
        self._transfer_outcome = "refused"
        self._events = 0
        self._tool_calls = 0
        self.hold: asyncio.Event | None = None

    @property
    def _open(self) -> bool:
        return self._reason is None and not self.over

    def _label(self, what: str) -> str:
        return f"call {self._record.number} {what}"

    def _count(self) -> None:
        self._events += 1
        if self._events > self._sim.max_events:
            raise VoiceError("가짜 통화가 손잡이를 부른 수가 상한을 넘었습니다(손잡이나 대본이 끝나지 않는 꼴)")

    # ── CallControl ────────────────────────────────────────────────────────────────────────────────
    async def say(self, text: str) -> None:
        if not self._open:
            return
        self._record.said.append(text)
        self._record.seen.append((self._label(f"say {len(self._record.said)}"), text))
        await self._spoke("agent", text)

    async def hangup(self) -> None:
        if self._open:
            self._end(END_AGENT)

    async def transfer(self, number: str) -> bool:
        if not self._open:
            return False
        outcome = self._transfer_outcome
        self._sim.transfers.append((number, outcome))
        if outcome == "refused":
            return False
        self._record.transferred_to = number
        self._end(END_TRANSFER if outcome == "answered" else END_TRANSFER_FAILED)
        return True

    # ── 대본 돌리기 ─────────────────────────────────────────────────────────────────────────────────
    def _end(self, reason: str) -> None:
        self._reason = reason
        if self.hold is not None:
            self.hold.set()

    async def _spoke(self, role: str, text: str) -> None:
        self._count()
        self._last_spoke = self.clock
        await self._handlers.on_transcript(role, text, self.clock)

    async def _advance(self, to: float) -> None:
        """시계를 to 까지 민다 — 그 사이의 시계 알림을 차례로 준다(끊기면 거기서 멈춘다)."""
        while self._reason is None:
            at = self._next_tick * self._sim.tick
            if at > to:
                self.clock = to
                return
            self._next_tick += 1
            self.clock = at
            self._count()
            await self._handlers.on_tick(at, at - self._last_spoke)

    async def _tool(self, step: Tool) -> None:
        self._count()
        self._tool_calls += 1
        label = self._label(f"result {self._tool_calls} {step.name}")
        try:
            reply = tool_reply(await self._handlers.on_tool(step.name, copy.deepcopy(step.args)))
        except Exception:
            self._record.seen.append((label, TOOL_FAILED_REPLY))  # 예외 글은 모델에게 가지 않는다
            raise
        self._record.seen.append((label, reply))
        offered = step.name in {tool.name for tool in self._record.spec.tools}
        self._record.tool_results.append(ToolResult(step.name, copy.deepcopy(step.args), json.loads(reply), offered))

    async def _park(self) -> None:
        self.hold = asyncio.Event()
        self._sim._parked.append(self)
        self._sim._someone_parked.set()
        try:
            await asyncio.wait_for(self.hold.wait(), HOLD_LIMIT_S)
        except TimeoutError:
            raise VoiceError("Hold 걸음을 놓아주지 않았습니다(release 나 hangup 이 없음)") from None
        finally:
            self._sim._parked.remove(self)
            if not self._sim._parked:
                self._sim._someone_parked.clear()
            self.hold = None

    async def run(self) -> None:
        spec, steps = self._record.spec, self._steps
        self._record.seen += [(self._label("first_line"), spec.first_line), (self._label("instructions"), spec.instructions)]
        self._record.seen += [
            (self._label(f"tool {tool.name}"), json.dumps(
                {"name": tool.name, "description": tool.description, "parameters": tool.json_schema()},
                ensure_ascii=False))
            for tool in spec.tools
        ]
        self._count()
        await self._handlers.on_start(self)
        opening = spec.first_line
        if steps and isinstance(steps[0], Opening):
            opening, steps = steps[0].text, steps[1:]
        if self._reason is None:
            await self._spoke("agent", opening)
        for step in steps:
            if self._reason is not None:
                break
            match step:
                case Say():
                    if step.t is not None:
                        await self._advance(step.t)
                    if self._reason is None:
                        await self._spoke(step.role, step.text)
                case Silence():
                    await self._advance(self.clock + step.seconds)
                case Tool():
                    await self._tool(step)
                case Transfer():
                    self._transfer_outcome = step.outcome
                case Hold():
                    await self._park()
                case Hangup():
                    self._reason = END_PEER if step.by == "peer" else END_AGENT
                case Lost():
                    self._reason = END_LOST
                case Crash():
                    raise VoiceError("가짜 통화 백엔드가 고장 났습니다(대본)")
        if self._reason is None:
            raise ScriptExhausted("받은 통화의 대본이 없습니다")
        self._record.ended = (self._reason, int(self.clock))
        await self._handlers.on_end(*self._record.ended)


class SimulatedVoice:
    """대본으로 도는 VoiceBackend(모듈 머리 글)."""

    def __init__(
        self,
        script: Sequence[Step],
        *,
        tick: float = 1.0,
        decide_within: float = DECIDE_WITHIN_S,
        hold_line: bool = False,
        catalogue: Mapping[str, Sequence[VoiceInfo]] | None = None,
        broken: Sequence[str] = (),
        max_events: int = MAX_EVENTS,
    ) -> None:
        if not (_number(tick) and tick > 0):
            raise ValueError("tick 은 0보다 큰 초입니다")
        if not (_number(decide_within) and decide_within > 0):
            raise ValueError("decide_within 은 0보다 큰 초입니다")
        if type(max_events) is not int or not 0 < max_events <= MAX_EVENTS:
            raise ValueError(f"max_events 는 1~{MAX_EVENTS} 의 정수입니다")
        if not set(broken) <= set(BREAKABLE):
            raise ValueError(f"broken 은 {BREAKABLE} 가운데서만 고릅니다")
        parts = segments(copy.deepcopy(list(script)))
        self._outbound = deque(part for part in parts if not isinstance(part[0], Ring))
        self._inbound = deque(part for part in parts if isinstance(part[0], Ring))
        self.tick, self.max_events = tick, max_events
        self._decide_within, self._hold_line = decide_within, hold_line
        self._catalogue = None if catalogue is None else {key: tuple(value) for key, value in catalogue.items()}
        self._broken = frozenset(broken)
        self._parked: list[_Call] = []
        self._someone_parked = asyncio.Event()
        self.calls: list[CallRecord] = []
        self.dialed: list[str] = []
        self.transfers: list[tuple[str, str]] = []  # (번호, 결과) — 시작하지 못한 것(refused)도
        self.rejected: list[Incoming] = []
        self.screen_errors: list[str] = []  # 받기 전 판정이 낸 예외의 종류 이름만(글은 두지 않는다)
        self.listens: list[str] = []
        self.listening: str | None = None
        self.samples: list[tuple[str, str, str]] = []
        self.live = 0
        self.peak_live = 0

    def __repr__(self) -> str:
        return f"SimulatedVoice(calls={len(self.calls)}, unused={self.unused}, live={self.live})"

    # ── 남긴 것 ─────────────────────────────────────────────────────────────────────────────────────
    @property
    def unused(self) -> int:
        """아직 쓰지 않은 통화 묶음 수."""
        return len(self._outbound) + len(self._inbound)

    @property
    def said(self) -> list[str]:
        return [text for call in self.calls for text in call.said]

    @property
    def tool_results(self) -> list[ToolResult]:
        return [result for call in self.calls for result in call.tool_results]

    @property
    def ended(self) -> list[tuple[str, int]]:
        return [call.ended for call in self.calls if call.ended is not None]

    @property
    def failed(self) -> list[tuple[str, str]]:
        return [call.failed for call in self.calls if call.failed is not None]

    @property
    def transferred_to(self) -> str | None:
        """마지막으로 넘기기를 시작한 번호(없으면 None)."""
        started = [call.transferred_to for call in self.calls if call.transferred_to is not None]
        return started[-1] if started else None

    def model_saw(self) -> list[tuple[str, str]]:
        """음성 모델에게 준 글 전부 — (이름표, 글), 통화 차례·준 차례대로."""
        return [pair for call in self.calls for pair in call.seen]

    def leaks(self) -> list[str]:
        """model_saw 가운데 번호처럼 보이는 것(그 통화의 번호 포함)이 든 글의 이름표."""
        return [label for call in self.calls for label, text in call.seen
                if has_phone(text, call.spec.to_number, call.spec.from_number)]

    # ── 멈춘 통화 ───────────────────────────────────────────────────────────────────────────────────
    async def wait_held(self) -> None:
        """어느 통화가 Hold 에 멈출 때까지 기다린다(HOLD_LIMIT_S 까지)."""
        try:
            await asyncio.wait_for(self._someone_parked.wait(), HOLD_LIMIT_S)
        except TimeoutError:
            raise VoiceError("Hold 에 멈춘 통화가 없습니다") from None

    def release(self) -> None:
        """Hold 에 멈춘 통화를 모두 잇는다."""
        for call in list(self._parked):
            if call.hold is not None:
                call.hold.set()

    # ── VoiceBackend ───────────────────────────────────────────────────────────────────────────────
    async def check(self) -> tuple[bool, str]:
        if "check" in self._broken:
            return False, "가짜 통화 백엔드가 꺼져 있습니다(대본)"
        return True, "가짜 통화 백엔드"

    async def place(self, spec: CallSpec, handlers: CallHandlers) -> None:
        if spec.direction != "out":
            raise ValueError("place 는 거는 통화의 명세만 받습니다")
        self.dialed.append(spec.to_number)
        if not self._outbound:
            raise ScriptExhausted("대본에 없는 통화가 걸렸습니다(거는 통화의 대본이 남아 있지 않음)")
        await self._run(spec, handlers, self._outbound.popleft())

    async def listen(
        self, number: str, on_incoming: Callable[[Incoming], Awaitable[tuple[CallSpec, CallHandlers] | None]]
    ) -> None:
        """남은 벨을 차례로 울리고 돌아온다. hold_line=True 면 실제 백엔드처럼 취소될 때까지 붙들고 있다(HOLD_LIMIT_S 까지)."""
        self.listens.append(number)
        self.listening = number
        try:
            while self._inbound:
                steps = self._inbound.popleft()
                ring = steps[0]
                incoming = Incoming(caller_number=ring.caller_number, to_number=number, at=ring.at or RING_AT)
                try:
                    answer = await asyncio.wait_for(on_incoming(incoming), self._decide_within)
                except Exception as exc:  # noqa: BLE001 — 판정이 실패하거나 늦으면 받지 않는다(닫힌 쪽으로)
                    self.screen_errors.append(type(exc).__name__)
                    self.rejected.append(incoming)
                    continue
                if answer is None:
                    self.rejected.append(incoming)
                    continue
                try:
                    spec, handlers = answer
                    usable = isinstance(spec, CallSpec) and spec.direction == "in"
                except (TypeError, ValueError):
                    usable = False
                if not usable:
                    self.rejected.append(incoming)
                    raise ValueError("받는 통화에는 (받는 통화의 명세, 손잡이)를 돌려줘야 합니다")
                await self._run(spec, handlers, steps[1:])
            if self._hold_line:
                try:
                    await asyncio.wait_for(asyncio.Event().wait(), HOLD_LIMIT_S)
                except TimeoutError:
                    raise VoiceError("붙들어 둔 listen 을 취소하지 않았습니다") from None
        finally:
            self.listening = None

    async def voices(self, language: str) -> list[VoiceInfo]:
        self._fail_if_broken("voices")
        return list(self._voices(language))

    async def sample(self, voice_id: str, language: str, text: str) -> bytes:
        """무음 WAV — 들을 수 있는 꼴만 갖춘다. 길이는 글 길이를 따른다(SAMPLE_MAX_CHARS 까지)."""
        self._fail_if_broken("sample")
        if voice_id not in {voice.id for voice in self._voices(language)}:
            raise VoiceError("그 언어에 없는 음성입니다")
        self.samples.append((voice_id, language, text))
        frames = SAMPLE_RATE // 10 * max(1, min(len(text), SAMPLE_MAX_CHARS))
        buffer = BytesIO()
        with wave.open(buffer, "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(SAMPLE_RATE)
            sound.writeframes(bytes(2 * frames))
        return buffer.getvalue()

    # ── 안쪽 ───────────────────────────────────────────────────────────────────────────────────────
    def _voices(self, language: str) -> tuple[VoiceInfo, ...]:
        return SIM_VOICES if self._catalogue is None else self._catalogue.get(language, ())

    def _fail_if_broken(self, what: str) -> None:
        if what in self._broken:
            raise VoiceError("가짜 통화 백엔드가 꺼져 있습니다(대본)")

    async def _run(self, spec: CallSpec, handlers: CallHandlers, steps: list[Step]) -> None:
        record = CallRecord(number=len(self.calls) + 1, spec=spec)
        self.calls.append(record)
        call = _Call(self, record, handlers, steps)
        self.live += 1
        self.peak_live = max(self.peak_live, self.live)
        try:
            first = steps[0] if steps else None
            if isinstance(first, Crash):  # 받기도 전에 고장
                raise VoiceError("가짜 통화 백엔드가 고장 났습니다(대본)")
            if isinstance(first, _UNANSWERED):
                code = {NoAnswer: "no_answer", Busy: "busy", Failed: "failed"}[type(first)]
                record.failed = (code, first.detail if isinstance(first, Failed) else code)
                await handlers.on_failed(*record.failed)
                return
            await call.run()
        except BaseException:
            record.broke = True
            raise
        finally:
            call.over = True
            record.seconds = call.clock
            self.live -= 1
