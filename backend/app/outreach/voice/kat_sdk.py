"""음성 SDK 어댑터(계획 4 Task 113): `KatVoice` 는 한국AI통신 음성 SDK(배포 이름 koreaaitel, import 이름 clawops) 위의
`voice.session.VoiceBackend` 이다. 거는 통화 일꾼(runner)이 `session.backend_for(session)` 로 얻어 `check` → `place` 한다.

**SDK 를 부르는 꼴은 음성 진단(app.notify.diagnostics_voice — 2026-11-24 P0-V 에서 실제 통화로 P5·P11 이 돈 코드)을 그대로 옮겼다**:
`ClawOpsAgent(api_key, account_id, base_url, from_, session_factory, builtin_tools=BuiltinTool.NONE, recording=False,
prewarm_enabled=False)`(prewarm 은 고침 1 — 켜 두면 SDK 가 벨 동안 만든 첫 인사의 받아쓰기를 _BufferingCall 이 버린다) ·
`on_incoming`(연결 전에, 기본이 거절) · `on("call_start"|"call_end"|"call_failed"|"transcript")` · `tool(fn)` · `connect()` ·
`call(to, timeout=RING_TIMEOUT_S)` · `CallSession.hangup()`(받은 뒤에만) · `disconnect()` · 세션은 `GeminiRealtime`/`OpenAIRealtime`
`(api_key, system_prompt, language, model)` · 고정 첫마디는 지시문에 「한 글자도 바꾸지 않고 먼저 말합니다」 · SDK 로그 거르개와
준비 표시 끄기(`voice_sdk_logs._quiet_sdk`) · 세션을 열지 못한 통화는 SDK 로그 줄(`session_failure`)로 안다. 진단에 없던 것:
`on("session_lost")`(Gemini 재접속 포기 — SDK 가 끊으므로 call_end 가 와도 통화됨이 아니다) · `CallSession.transfer(to)` ·
끝이 확인되지 않은 통화를 끝내는 SDK 의 공개 REST `clawops.AsyncClawOps(...).calls.update(call_id, status="completed")`.

지키는 것(모듈 session.py 머리 글의 약속과 함께):
- SDK 는 이 파일의 함수 안에서만 불러온다. 시험(pytest)에서는 불러오지도 않는다 — 시험은 `sdk=` 에 가짜를 끼운다.
- 모델은 언제나 `numbers.effective_model(provider, model)` — 비면 걸지 않는다(SDK 기본 모델로 두지 않는다. 옛 기본은 404).
- 키·Account ID·음성 모델 키는 만들 때 `redact.add_secrets`. 걸기 전에 SDK 로거(COVERED)가 `redact.covers` 인지 보고 아니면 걸지 않는다.
  SDK 예외 글은 어디에도 싣지 않는다(종류와 짧은 낱말만). 받아쓰기 글은 손잡이에만 가고 로그에 남기지 않는다.
- control 연결은 번호당 하나: `place` 안에서만 붙고 끝나면(어떻게 끝나든) 끊는다. 음성 진단과의 배타는 일꾼이 한다
  (runner.run_one 이 줄을 쥐는 동안만 `place` 가 불리고, 진단은 `worker_connected → runner.holds_line` 을 본다).
- 시험 모드면 허용 번호에만 걸고 넘긴다(문이 이미 봤다 — 둘째 겹). 녹음은 끈다(진단과 같다. `record_to` 는 쓰지 않는다).
- 끝은 꼭 한 번, 그리고 늘 끝이 있다: 받기 전 사건이 ANSWER_WAIT_S 안에 오지 않음·끊었는데 END_GRACE_S 안에 끝나지 않음·
  통화 전체가 상한(받은 때부터)을 넘음 → VoiceError(일꾼이 「확인 필요」로 닫는다). 끝나거나 취소되면 살아 있는 통화를 끊고
  (SDK 의 끊기는 5초까지 소리를 마저 보낸다 — SDK_HANGUP_S 8초), 그래도 끝이 확인되지 않은 통화(벨이 울리는 중 포함)는 REST 로
  끝낸 뒤 연결을 닫는다(control 연결을 닫아도 미디어·모델 세션은 남는다).
- 발신 요청 오류는 4xx 만 「걸리지 않음」, 5xx·2xx·그 밖은 「걸렸는지 모름」.
- 받은 뒤 세션이 실패하면(SDK 로그 줄 · session_lost · 받은 뒤의 call_failed) END_LOST — 끝 사건을 기다리지 않는다.
- SDK 에 「이 말을 하라」가 없다: `CallControl.say` 는 아무것도 하지 않는다(모델은 지시문대로 말한다). 음성 목록·샘플도 없다.
"""

import asyncio
import importlib
import importlib.util
import inspect
import json
import logging
import math
import re
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial

from app.notify import diagnostics
from app.notify.diagnostics_voice import (
    CONNECT_TIMEOUT_S,
    DIAL_TIMEOUT_S,
    READY_ENV,
    RING_TIMEOUT_S,
    SDK_HANGUP_S,
    SDK_LOGGERS,
    SDK_MODULE,
    SESSIONS,
    end_by_rest,
)
from app.notify.voice_sdk_logs import _quiet_sdk, session_failure
from app.outreach import phone, redact
from app.outreach.harness.types import NotReady, ToolDef
from app.outreach.voice import numbers
from app.outreach.voice.session import (
    END_AGENT,
    END_LOST,
    END_PEER,
    END_TRANSFER,
    END_TRANSFER_FAILED,
    OPENING_WITHIN_S,
    TOOL_FAILED_REPLY,
    CallHandlers,
    CallSpec,
    Incoming,
    VoiceError,
    VoiceInfo,
    tool_reply,
)
from app.security import crypto
from app.store import outreach
from app.store.tables_outreach import VoiceSettings

REST_MODULE = "clawops"  # REST 클라이언트(AsyncClawOps) — 끝이 확인되지 않은 통화를 끝낼 때만
COVERED = ("clawops", "aiohttp", "google_genai", "google.genai", "websockets", "livekit")  # 가리개가 덮어야 걸 수 있다
EVENTS = ("call_start", "call_end", "call_failed", "transcript", "session_lost")
POLL_S = 0.1  # 사건·시계를 보는 간격
TICK_S = 1.0  # on_tick 간격
FRAGMENT_GAP_S = 1.2  # 받아쓰기 조각이 이만큼 끊기면 한 발화가 끝났다고 본다
OPENING_GAP_S = 2.0  # 첫 발화는 더 길게 기다린다 — 일꾼은 첫 발화 하나로 AI·기록 안내를 보므로 자르면 잘못 끊는다
ANSWER_WAIT_S = RING_TIMEOUT_S + 20  # 건 뒤 받았다·안 받았다는 사건을 기다리는 끝
END_GRACE_S = 11.0  # 끊기를 건 뒤 끝 사건을 기다리는 끝(끊기 8초 + SDK 의 종료 프레임 2초 + 여유) — call_run.HANGUP_WAIT_S 보다 짧게
OVERALL_MARGIN_S = 10  # 통화 전체 상한 = ANSWER_WAIT_S + max_seconds + 이만큼(일꾼의 실제 시간 상한 max_seconds+60 안)
TOOL_WAIT_S = 30.0  # SDK 의 도구 호출이 손잡이의 답을 기다리는 끝(실제 시간)
TRANSFER_START_S = 2.0  # 넘기기를 건 뒤 곧바로 실패하는지 보는 시간
TRANSFER_RESULT_S = 5.0  # AI 쪽 통화가 끝난 뒤 넘기기 결과를 기다리는 시간
TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}
UNANSWERED = {"no-answer": ("no_answer", "no_answer"), "busy": ("busy", "busy"), "rejected": ("busy", "declined"),
              "canceled": ("failed", "canceled"), "failed": ("failed", "failed")}
FIRST_RULE = {"ko": "통화가 연결되면 다음 문장을 한 글자도 바꾸지 않고 먼저 말합니다: 「{line}」",
              "en": 'When the call connects, first say exactly this sentence: "{line}"'}
_MODEL = re.compile(r"[A-Za-z0-9._\-]{1,80}")
_WORD = re.compile(r"[a-z_\-]{1,30}")
logger = logging.getLogger(__name__)

READY = "음성 SDK 로 걸 수 있습니다"
NOT_INSTALLED = "음성 SDK 가 설치돼 있지 않습니다"
BLOCKED_IN_TESTS = "시험에서는 실제 음성 SDK 를 쓰지 않습니다"
NO_SETTINGS = "AI 전화 음성 설정이 없어 음성 통화 백엔드가 준비되지 않았습니다"
NOT_SDK_PROVIDER = "이 음성 방식(대시보드)의 백엔드는 아직 준비되지 않았습니다"
LOGS_NOT_COVERED = "음성 SDK 로그 가리개가 준비되지 않았습니다"
NO_KEY = "알림 연결의 API 키를 읽을 수 없습니다"
NO_ACCOUNT = "알림 연결의 Account ID 가 없습니다"
NO_VOICE_KEY = "음성 모델 키가 없거나 읽을 수 없습니다"
BAD_PROVIDER = "음성 모델 공급자가 구글·OpenAI 가 아닙니다"
NO_MODEL = "음성 모델이 정해지지 않았습니다"
BAD_MODEL = "음성 모델 이름에 쓸 수 없는 글자가 있습니다"
NO_NUMBER = "AI 전화 번호가 없거나 걸 수 없는 번호입니다"
CHECK_FAILED = "음성 백엔드를 확인하지 못했습니다"
NOT_ALLOWED = "시험 모드라 허용한 번호에만 겁니다"
BAD_TARGET = "걸 번호가 맞지 않습니다"
EXTRA_MISSING = "고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다"
BAD_SHAPE = "설치된 음성 SDK 가 확인해 둔 판과 다릅니다"
DIAL_UNKNOWN = "발신 요청의 결과를 알 수 없습니다 — 전화가 걸렸는지 확인이 필요합니다"
NO_ANSWER_EVENT = "건 뒤 받았는지 알리는 사건이 오지 않았습니다"
SESSION_FAILED = "AI 음성 모델 세션을 열지 못했습니다"
CUT_UNCONFIRMED = "끊었지만 통화가 끝났는지 확인되지 않았습니다"
TOO_LONG = "통화가 정해진 시간 안에 끝나지 않았습니다"
NO_LISTEN = "받는 통화는 아직 이 백엔드에 없습니다"
NO_SAMPLE = "음성 샘플은 음성 SDK 가 제공하지 않습니다"

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


def _plain(ciphertext: object) -> str | None:
    if not isinstance(ciphertext, str) or not ciphertext:
        return None
    try:
        return crypto.decrypt(ciphertext)
    except Exception:  # noqa: BLE001 — 못 읽는 키는 없는 키다(글은 남기지 않는다)
        return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class _Setup:
    """만들 때 한 번 읽은 설정(DB 줄은 붙들지 않는다). 키·계정·번호는 repr 에 없다."""

    provider: str
    model: str | None
    base_url: str
    key: str | None = field(repr=False)
    account_id: str = field(repr=False)
    voice_key: str | None = field(repr=False)
    agent_number: str | None = field(repr=False)
    test_mode: bool = True
    allowed: frozenset[str] = field(default=frozenset(), repr=False)


def _setup(conn: object, voice: object) -> _Setup:
    provider = getattr(voice, "provider", None)
    provider = provider if isinstance(provider, str) else ""
    raw_model = getattr(voice, "model", None)
    stored = getattr(conn, "allow_numbers_json", None)
    allowed = {phone.normalize(n) for n in (stored if isinstance(stored, list) else ()) if isinstance(n, str)}
    return _Setup(provider=provider, model=numbers.effective_model(provider, raw_model if isinstance(raw_model, str) else ""),
                  base_url=_text(getattr(conn, "base_url", None)), key=_plain(getattr(conn, "secret_ciphertext", None)),
                  account_id=_text(getattr(conn, "account_id", None)),
                  voice_key=_plain(getattr(voice, "secret_ciphertext", None)),
                  agent_number=phone.normalize(numbers.effective_agent_number(conn, voice)),
                  test_mode=getattr(conn, "test_mode", True) is not False, allowed=frozenset(allowed - {None}))


def for_session(session: object) -> "KatVoice":
    """backend_for 의 몸통: 기본 알림 연결의 음성 설정이 구글·OpenAI 이고 다 갖춰졌으면 KatVoice, 아니면 NotReady(글에 번호·키 없음)."""
    conn = outreach.connection(session)
    settings = session.get(VoiceSettings, conn.id) if conn is not None else None
    if settings is None:
        raise NotReady(NO_SETTINGS)
    if settings.provider not in SESSIONS:
        raise NotReady(NOT_SDK_PROVIDER)  # dashboard(Task 94)는 아직 없다
    backend = KatVoice(conn, settings)
    problem = backend.problem()
    if problem is not None:
        raise NotReady(problem)
    return backend


def _sdk_tool(tool: ToolDef, call: Callable[[str, dict], Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """하네스 도구 하나를 SDK 의 `agent.tool` 이 받는 함수로: 이름 = 도구 이름, 설명 = 설명 + 인자 스키마(JSON — SDK 는 서명에서
    타입만 읽어 설명·enum 을 잃는다), 인자 = 스키마의 칸(타입 주석은 str·int·float·bool, 그 밖은 object 로 SDK 가 바꾸지 않게)."""
    schema = tool.json_schema()
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    params, notes = [], {}
    for name, spec in properties.items():
        if not name.isidentifier():
            raise ValueError("도구 인자 이름을 SDK 에 넘길 수 없습니다")
        notes[name] = TYPES.get(spec.get("type") if isinstance(spec, dict) else None, object)
        default = inspect.Parameter.empty if name in required else None
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default))

    async def handler(**kwargs: object) -> str:
        return await call(tool.name, kwargs)

    handler.__name__ = handler.__qualname__ = tool.name
    handler.__doc__ = f"{tool.description}\n인자: {json.dumps(properties, ensure_ascii=False)}"
    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = notes
    return handler


class KatVoice:
    """VoiceBackend(음성 SDK). `conn` 은 알림 연결 줄, `voice_settings` 는 그 연결의 음성 설정 줄 — 만들 때 값만 읽는다.
    `sdk`·`sleep`·`clock`·`resolve` 는 시험이 끼우는 자리(가짜 SDK·대본 시계·이름 풀이)."""

    def __init__(self, conn: object, voice_settings: object, *, sdk: object | None = None, sleep: Sleep = asyncio.sleep,
                 clock: Clock = time.monotonic, resolve: object = None) -> None:
        self._s = _setup(conn, voice_settings)
        self._sdk, self._sleep, self._clock, self._resolve = sdk, sleep, clock, resolve
        redact.add_secrets(self._s.key, self._s.account_id, self._s.voice_key)  # SDK 를 건드리기 전에 거르개에

    def __repr__(self) -> str:
        return f"KatVoice(provider={self._s.provider!r}, model={self._s.model!r})"

    @property
    def model(self) -> str | None:
        """SDK 에 넘길 모델(effective_model) — 사용량 기록과 같은 값."""
        return self._s.model

    def problem(self) -> str | None:
        """걸 수 없는 까닭(번호·키 없는 한국어) 또는 None. SDK 를 불러오지 않는다."""
        if self._sdk is None and not _installed():
            return NOT_INSTALLED
        if not all(redact.covers(name) for name in COVERED):
            return LOGS_NOT_COVERED
        s = self._s
        problem = diagnostics.base_url_problem(s.base_url)
        if problem:
            return problem
        if not s.key or len(s.key) < diagnostics.MIN_SECRET:
            return NO_KEY
        if len(s.account_id) < diagnostics.MIN_SECRET:
            return NO_ACCOUNT
        if s.provider not in SESSIONS:
            return BAD_PROVIDER
        if not s.voice_key or len(s.voice_key) < diagnostics.MIN_SECRET:
            return NO_VOICE_KEY
        if not s.model:
            return NO_MODEL
        if not _MODEL.fullmatch(s.model):
            return BAD_MODEL
        return None if s.agent_number is not None and phone.can_call(s.agent_number) else NO_NUMBER

    async def check(self) -> tuple[bool, str]:
        try:
            problem = self.problem()
        except Exception:  # noqa: BLE001 — check 는 던지지 않는다
            problem = CHECK_FAILED
        return (False, problem) if problem else (True, READY)

    async def place(self, spec: CallSpec, handlers: CallHandlers) -> None:
        if not isinstance(spec, CallSpec) or spec.direction != "out":
            raise ValueError("place 는 거는 통화의 명세만 받습니다")
        problem = self.problem()
        if problem is not None:
            raise VoiceError(problem)
        target = phone.normalize(spec.to_number)
        if target is None or not phone.can_call(target):
            raise VoiceError(BAD_TARGET)
        if self._s.test_mode and target not in self._s.allowed:
            raise VoiceError(NOT_ALLOWED)
        found = await diagnostics.resolve_problem(SimpleConn(self._s.base_url), self._resolve)
        if found:
            raise VoiceError(found)
        sdk = self._sdk if self._sdk is not None else _load()
        rest = self._sdk if self._sdk is not None else _load(REST_MODULE)
        line = _Line(self, sdk, rest, spec, handlers, target)
        with _quiet_sdk(line.clean, SDK_LOGGERS, READY_ENV, watch=line.saw):
            try:
                await line.run()
            finally:
                await asyncio.shield(line.close())

    async def listen(self, number: str, on_incoming: Callable[[Incoming], Awaitable[object]]) -> None:
        raise VoiceError(NO_LISTEN)  # 받는 통화는 Task 95

    async def voices(self, language: str) -> list[VoiceInfo]:
        return []  # SDK 에 음성 목록이 없다(P9). 음성은 세션 기본값(구글 Kore · OpenAI marin)

    async def sample(self, voice_id: str, language: str, text: str) -> bytes:
        raise VoiceError(NO_SAMPLE)


@dataclass(frozen=True)
class SimpleConn:
    """diagnostics.resolve_problem 이 읽는 꼴(`.base_url` 하나)."""

    base_url: str


def _installed() -> bool:
    try:
        return importlib.util.find_spec(SDK_MODULE.split(".")[0]) is not None
    except (ImportError, ValueError):
        return False


def _load(module: str = SDK_MODULE) -> object:
    """실제 SDK — 함수 안에서만, 시험에서는 불러오지도 않는다(둘째 겹: 시험이 망으로 나가지 않게)."""
    if not _installed():
        raise VoiceError(NOT_INSTALLED)
    if "pytest" in sys.modules:
        raise VoiceError(BLOCKED_IN_TESTS)
    try:
        return importlib.import_module(module)
    except ImportError:
        raise VoiceError(NOT_INSTALLED) from None


def _same_call(found: object, ours: str | None) -> bool:
    """SDK 로그 줄의 통화 id 가 우리 통화인가 — 앱의 로그 거르개가 줄을 만들 때 번호처럼 보이는 숫자를 가렸을 수 있어, 우리 id 에
    같은 가리기를 한 꼴과도 견준다."""
    if not isinstance(found, str) or not ours:
        return False
    return found in (ours, redact.hide_phones(ours), redact.scrub(ours, []))


def _call_id(obj: object) -> str | None:
    value = getattr(obj, "call_id", None)
    return value if isinstance(value, str) and value else None


@dataclass
class _Utterance:
    role: str  # agent | peer
    parts: list[str]
    t: float  # 첫 조각의 때(받은 뒤 초)
    last: float  # 마지막 조각의 때(시계)


class _Control:
    """손잡이에게 주는 CallControl. 끝난 통화에서는 아무 일도 하지 않는다."""

    def __init__(self, line: "_Line") -> None:
        self._line = line

    async def say(self, text: str) -> None:
        return None  # SDK 에 「이 말을 하라」가 없다 — 모델은 지시문대로 말한다(실제로 한 말은 받아쓰기로 온다)

    async def hangup(self) -> None:
        await self._line.hang_up()

    async def transfer(self, number: str) -> bool:
        return await self._line.transfer(number)


class _Line:
    """통화 한 통: 에이전트 하나 · 우리 통화 하나. SDK 의 사건은 줄(events)에만 넣고, 손잡이는 이 객체의 고리(pump)만 차례로 부른다."""

    def __init__(self, kat: KatVoice, sdk: object, rest: object, spec: CallSpec, handlers: CallHandlers,
                 target: str) -> None:
        self.kat, self.sdk, self.rest, self.spec, self.handlers, self.target = kat, sdk, rest, spec, handlers, target
        self.sleep, self.clock = kat._sleep, kat._clock
        s = kat._s
        self.secrets = [s.key, s.account_id, s.voice_key]
        self.numbers = [n for n in (spec.to_number, spec.from_number, target, s.agent_number) if isinstance(n, str)]
        self.control = _Control(self)
        self.events: deque = deque()
        self.agent: object | None = None
        self.ours: object | None = None  # 우리 통화의 SDK CallSession
        self.phase = "dialing"  # dialing → live → over
        self.dialed_at = self.started = 0.0
        self.deadline = math.inf  # 통화 전체 상한 — 받은 때부터(받기 전은 ANSWER_WAIT_S 가 묶는다)
        self.next_tick, self.last_spoke = 1, 0.0
        self.pending: _Utterance | None = None
        self.opening, self.held = True, []
        self.hung_at: float | None = None
        self.lost = self.ending = self.ended = False  # ended: SDK 가 우리 통화의 끝(call_end·call_failed)을 알렸다
        self.transferring: asyncio.Future | None = None
        self.futures: list[asyncio.Future] = []
        self.dialing: asyncio.Future | None = None  # agent.call — 돌아오는 순간 취소돼도 통화를 놓치지 않게

    def clean(self, text: object, limit: int = 300) -> str:
        return diagnostics.scrub(text, secrets=self.secrets, numbers=self.numbers, limit=limit)

    # ── SDK 쪽(던지지 않는다) ─────────────────────────────────────────────

    async def event(self, name: str, sdk_call: object, *args: object) -> None:
        try:
            self.events.append((name, sdk_call, args, self.clock()))
        except Exception:  # noqa: BLE001, S110 — SDK 의 사건 처리로 올리지 않는다
            pass

    def saw(self, record: object) -> None:
        """SDK 로그 가운데 AI 음성 모델 세션을 열지 못한 줄(통화 id 만 읽는다) — 실제 SDK 는 그 뒤 call_end 를 보내지 않는다."""
        found = session_failure(record)
        if found is not None and self.ours is not None and _same_call(found[0], _call_id(self.ours)):
            self.events.append(("session_failed", self.ours, (), self.clock()))

    def screen(self, incoming: object) -> None:
        """`on_incoming` 훅: 거는 동안 걸려 온 전화는 모두 받지 않는다(받는 통화는 Task 95). 기다리지 않고 던지지 않는다."""
        try:
            incoming.reject()
        except Exception:  # noqa: BLE001, S110
            pass

    async def tool(self, name: str, kwargs: dict) -> str:
        """SDK 의 도구 함수가 부른다: 고리가 손잡이(on_tool)를 부를 때까지 기다린다. 실패·끝·시간 넘김이면 고정 답만."""
        future = asyncio.get_running_loop().create_future()
        self.futures.append(future)
        self.events.append(("tool", None, (name, dict(kwargs), future), self.clock()))
        try:
            return await asyncio.wait_for(asyncio.shield(future), TOOL_WAIT_S)
        except Exception:  # noqa: BLE001 — 예외 글은 모델·SDK 로그로 가지 않는다
            return TOOL_FAILED_REPLY

    def session(self) -> object:
        """통화마다 세션 하나(SDK 의 session_factory). 지시문 + 고정 첫마디, 모델은 effective_model."""
        s, spec = self.kat._s, self.spec
        rule = FIRST_RULE.get(spec.language.split("-")[0].lower(), FIRST_RULE["en"]).format(line=spec.first_line)
        kw = {"api_key": s.voice_key, "system_prompt": f"{spec.instructions}\n\n{rule}", "language": spec.language,
              "model": s.model}
        if s.provider == "google":
            kw["api_version"] = numbers.GOOGLE_LIVE_API_VERSION  # Live 모델은 v1alpha 에만 있다(11-24 실측)
        return getattr(self.sdk, SESSIONS[s.provider])(**kw)

    async def bounded(self, awaitable: Awaitable, limit: float) -> object:
        """SDK 의 일을 우리 시계로 limit 초까지만 기다린다. 넘으면 취소하고 TimeoutError."""
        task = asyncio.ensure_future(awaitable)
        deadline = self.clock() + limit
        try:
            while not task.done():
                if self.clock() >= deadline:
                    raise TimeoutError
                await self.sleep(POLL_S)
        finally:
            if not task.done():
                task.cancel()
        if task.cancelled():
            raise TimeoutError
        return task.result()

    # ── 만들기 · 연결 · 걸기 ─────────────────────────────────────────────

    def build(self) -> None:
        sdk, s = self.sdk, self.kat._s
        try:
            self.session()  # 고른 모델의 묶음(extra)이 깔렸는지 — 통화에는 팩토리가 새로 만든 것을 쓴다
            agent = sdk.ClawOpsAgent(api_key=s.key, account_id=s.account_id, base_url=s.base_url.rstrip("/"),
                                     from_=self.spec.from_number, session_factory=self.session,
                                     builtin_tools=sdk.BuiltinTool.NONE, recording=False,
                                     prewarm_enabled=False)  # prewarm 은 벨 동안 만든 첫 인사의 받아쓰기를 버린다
            self.agent = agent
            agent.on_incoming(self.screen)  # 연결 전에 — 훅이 없으면 SDK 는 걸려 온 전화를 모두 받는다
            for name in EVENTS:
                agent.on(name)(partial(self.event, name))
            for tool in self.spec.tools:
                agent.tool(_sdk_tool(tool, self.tool))
        except ImportError:
            raise VoiceError(EXTRA_MISSING) from None
        except (AttributeError, TypeError, ValueError):
            raise VoiceError(BAD_SHAPE) from None

    async def run(self) -> None:
        self.build()
        try:
            await self.bounded(self.agent.connect(), CONNECT_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — 붙지 못했다: 걸지 않았다(SDK 예외 글은 버린다)
            await self.handlers.on_failed("failed", "connect_failed")
            return
        refused = unknown = False
        self.dialing = asyncio.ensure_future(self.agent.call(self.target, timeout=RING_TIMEOUT_S))
        try:
            sdk_call = await self.bounded(self.dialing, DIAL_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 — 예외는 붙들지 않는다(글에 번호·계정이 든다): 아래에서 우리 오류로
            status = getattr(e, "status", None)
            # 4xx 만 「플랫폼이 거절 — 걸리지 않음」. 5xx(통화를 만든 뒤 프록시가 낸 오류일 수 있다)·2xx(만들었는데 답을 못 읽음)는 모름
            refused = type(status) is int and 400 <= status < 500
            unknown = not refused  # 끝나지 않음·상태 없는 오류 — 걸렸을 수 있다
        if unknown:
            raise VoiceError(DIAL_UNKNOWN)
        if refused:
            await self.handlers.on_failed("failed", "dial_refused")
            return
        self.ours = self.ours or sdk_call
        self.dialed_at = self.clock()
        await self.pump()

    # ── 고리 ─────────────────────────────────────────────────────────

    async def pump(self) -> None:
        while True:
            while self.events:
                name, sdk_call, args, at = self.events.popleft()
                await self.ticks(at)
                if await self.handle(name, sdk_call, args, at):
                    return
            now = self.clock()
            await self.ticks(now)
            if self.phase == "live":
                await self.timers(now)
            if self.phase == "dialing" and now >= self.dialed_at + ANSWER_WAIT_S:
                raise VoiceError(NO_ANSWER_EVENT)
            if self.hung_at is not None and now >= self.hung_at + END_GRACE_S:
                raise VoiceError(CUT_UNCONFIRMED)
            if now >= self.deadline:
                raise VoiceError(TOO_LONG)
            await self.sleep(POLL_S)

    def mine(self, sdk_call: object) -> bool:
        if sdk_call is None or getattr(sdk_call, "direction", None) == "inbound":
            return False
        if self.ours is None and self.phase == "dialing":
            self.ours = sdk_call  # call() 이 돌아오기 전에 온 사건
        return self.is_ours(sdk_call)

    def is_ours(self, sdk_call: object) -> bool:
        if sdk_call is None or self.ours is None or getattr(sdk_call, "direction", None) == "inbound":
            return False
        return sdk_call is self.ours or (_call_id(sdk_call) is not None and _call_id(sdk_call) == _call_id(self.ours))

    def answered(self) -> bool:
        """받았는가 — 아직 읽지 않은 call_start 까지."""
        return self.phase == "live" or any(name == "call_start" and self.is_ours(sdk_call)
                                           for name, sdk_call, _, _ in self.events)

    def confirmed(self) -> bool:
        """SDK 가 우리 통화의 끝(call_end·call_failed)을 알렸는가 — 아직 읽지 않은 사건까지."""
        return self.ended or any(name in ("call_end", "call_failed") and self.is_ours(sdk_call)
                                 for name, sdk_call, _, _ in self.events)

    async def handle(self, name: str, sdk_call: object, args: tuple, at: float) -> bool:
        """사건 하나. 통화가 끝났으면 True."""
        if name == "tool":
            await self.tool_call(*args)
            return False
        if not self.mine(sdk_call):
            if name == "call_start" and sdk_call is not None:  # 거절했는데 시작된 남의 통화 — 곧바로 끊는다
                try:
                    await self.bounded(sdk_call.hangup(), SDK_HANGUP_S)
                except Exception:  # noqa: BLE001, S110
                    pass
            return False
        if name in ("call_end", "call_failed"):
            self.ended = True
        if name in ("session_failed", "session_lost") or (name == "call_failed" and self.phase == "live"):
            if self.phase == "dialing":
                raise VoiceError(SESSION_FAILED)  # 손잡이가 받기 전에 세션이 실패 — 끝 사건은 오지 않는다
            if self.transferring is not None and name == "call_failed":
                await self.finish(await self.end_reason(), at)
                return True
            self.lost = True
            if self.hung_at is None:
                self.hung_at = self.clock()
                try:
                    await self.bounded(self.ours.hangup(), SDK_HANGUP_S)
                except Exception:  # noqa: BLE001, S110 — 끝은 END_LOST 로 알린다
                    pass
            await self.finish(END_LOST, at)
            return True
        if name == "call_start" and self.phase == "dialing":
            self.phase, self.started, self.last_spoke = "live", at, 0.0
            self.deadline = at + self.spec.max_seconds + OVERALL_MARGIN_S  # 통화 전체 상한은 받은 때부터
            await self.handlers.on_start(self.control)
        elif name == "call_failed" or (name == "call_end" and self.phase == "dialing"):
            word = args[0] if args and isinstance(args[0], str) and _WORD.fullmatch(args[0]) else "failed"
            code, detail = UNANSWERED.get(word, ("failed", "failed"))
            self.phase = "over"
            await self.handlers.on_failed(code, detail)
            return True
        elif name == "call_end":
            await self.finish(await self.end_reason(), at)
            return True
        elif name == "transcript" and self.phase == "live" and len(args) >= 2:
            await self.fragment("agent" if args[0] == "assistant" else "peer", args[1], at)
        return False

    async def ticks(self, upto: float) -> None:
        """시계 알림 — 같은 때면 말보다 먼저. 끊기를 건 뒤로는 주지 않는다."""
        while self.phase == "live" and not self.ending and self.hung_at is None \
                and self.started + self.next_tick * TICK_S <= upto + 1e-9:
            at = self.next_tick * TICK_S
            self.next_tick += 1
            await self.handlers.on_tick(at, max(0.0, at - self.last_spoke))

    def gap(self) -> float:
        return OPENING_GAP_S if self.opening else FRAGMENT_GAP_S

    async def timers(self, now: float) -> None:
        if self.pending is not None and now - self.pending.last >= self.gap():
            await self.flush()
        if self.opening and self.pending is None and now - self.started >= OPENING_WITHIN_S:
            await self.handlers.on_transcript("agent", "", round(now - self.started, 3))
            await self.opened()

    # ── 받아쓰기: 조각을 이어 한 발화로, 첫 발화가 먼저 ─────────────────────────

    async def fragment(self, role: str, text: object, at: float) -> None:
        if not isinstance(text, str) or not text:
            return
        self.last_spoke = max(self.last_spoke, at - self.started)
        if self.opening and role == "peer":
            # 첫 발화가 끝나기 전의 상대 말은 뒤로(받자마자 「여보세요」가 인사 위에 겹쳐도 인사를 둘로 자르지 않는다)
            self.held.append(("frag", role, text, at))
            return
        if self.pending is not None and (self.pending.role != role or at - self.pending.last >= self.gap()):
            await self.flush()
        if self.pending is None:
            self.pending = _Utterance(role, [text], round(at - self.started, 3), at)
        else:
            self.pending.parts.append(text)
            self.pending.last = at

    async def flush(self) -> None:
        said, self.pending = self.pending, None
        if said is None:
            return
        text = " ".join("".join(said.parts).split())
        if text or (self.opening and said.role == "agent"):
            await self.handlers.on_transcript(said.role, text, said.t)
        if self.opening and said.role == "agent":
            await self.opened()

    async def opened(self) -> None:
        """첫 발화가 나갔다 — 미뤄 둔 상대 말(한 발화로)과 도구 호출을 차례로 준다."""
        self.opening, held, self.held = False, self.held, []
        for kind, *rest in held:
            if kind == "frag":
                await self.fragment(*rest)
            else:
                await self.flush()
                await self.tool_call(*rest)
        await self.flush()

    async def tool_call(self, name: str, kwargs: dict, future: asyncio.Future) -> None:
        if self.phase != "live" or self.ending:
            if not future.done():
                future.set_result(TOOL_FAILED_REPLY)
            return
        await self.flush()  # 도구 호출은 말을 끊는다(첫 발화도 여기서 끝날 수 있다)
        if self.opening:
            self.held.append(("tool", name, kwargs, future))
            return
        try:
            reply = tool_reply(await self.handlers.on_tool(name, kwargs))
        except BaseException:
            if not future.done():
                future.set_result(TOOL_FAILED_REPLY)  # 예외 글은 모델에게 가지 않는다
            raise
        if not future.done():
            future.set_result(reply)

    # ── 끝 ───────────────────────────────────────────────────────────

    async def finish(self, reason: str, at: float) -> None:
        self.ending = True
        await self.flush()
        if self.opening:  # 첫 발화 전에 끝났다 — 약속대로 빈 첫 발화부터
            await self.handlers.on_transcript("agent", "", round(at - self.started, 3))
            await self.opened()
        await self.flush()
        self.phase = "over"
        await self.handlers.on_end(reason, max(0, int(at - self.started)))

    async def end_reason(self) -> str:
        if self.lost:
            return END_LOST
        task = self.transferring
        if task is not None:
            until = self.clock() + TRANSFER_RESULT_S
            while not task.done() and self.clock() < until:
                await self.sleep(POLL_S)
            if not task.done():
                return END_TRANSFER  # 결과를 아직 모른다 — 넘기기가 시작돼 AI 쪽이 끝났다(확인되지 않음)
            if task.cancelled() or task.exception() is not None:
                return END_TRANSFER_FAILED
            result = task.result()
            return END_TRANSFER if isinstance(result, dict) and result.get("status") == "completed" else END_TRANSFER_FAILED
        return END_AGENT if self.hung_at is not None else END_PEER

    async def hang_up(self) -> None:
        if self.phase != "live" or self.ending or self.hung_at is not None or self.transferring is not None:
            return
        self.hung_at = self.clock()
        try:
            await self.bounded(self.ours.hangup(), SDK_HANGUP_S)
        except Exception:  # noqa: BLE001, S110 — 끝났는지는 끝 사건으로 본다(END_GRACE_S)
            pass

    async def transfer(self, number: str) -> bool:
        """넘기기를 시작한다 — 곧바로 실패하지 않으면 True(AI 쪽 통화는 서버가 끝낸다). 번호는 코드가 준 것만, 시험 모드면 허용 번호만."""
        if self.phase != "live" or self.ending or self.hung_at is not None or self.transferring is not None:
            return False
        to = phone.normalize(number) if isinstance(number, str) else None
        if to is None or not phone.can_call(to) or (self.kat._s.test_mode and to not in self.kat._s.allowed):
            return False
        task = asyncio.ensure_future(self.ours.transfer(to))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # 결과를 읽지 않은 예외 경고를 막는다
        until = self.clock() + TRANSFER_START_S
        while not task.done() and self.clock() < until:
            await self.sleep(POLL_S)
        if task.done() and (task.cancelled() or task.exception() is not None
                            or not (isinstance(task.result(), dict) and task.result().get("status") == "completed")):
            return False
        self.transferring = task
        return True

    async def close(self) -> None:
        """끝나거나 취소되면 꼭 거친다: 남은 도구 호출에 고정 답 · 끝이 확인되지 않은 우리 통화는 끊어 보고(받은 뒤만 — 받기 전
        끊기는 SDK 가 무시한다), 그래도 확인되지 않으면(벨이 울리는 중 포함) REST `calls.update(id, status="completed")` 로
        끝낸다 · 넘기기 대기를 접고 연결을 닫는다. 결과(일꾼이 적을 것)는 바꾸지 않는다 — 확인되지 않은 끝은 「확인 필요」 그대로."""
        for future in self.futures:
            if not future.done():
                future.set_result(TOOL_FAILED_REPLY)
        task = self.dialing
        if self.ours is None and task is not None and task.done() and not task.cancelled() and task.exception() is None:
            self.ours = task.result()  # 걸고 나서 바로 취소됐다 — 그 통화도 끝낸다
        # 넘기는 중이면(담당자와 이어지는 중일 수 있다) 끊지도 REST 로 끝내지도 않는다
        if self.ours is not None and not self.confirmed() and self.transferring is None:
            if self.answered() and self.hung_at is None:
                self.hung_at = self.clock()
                try:
                    await self.bounded(self.ours.hangup(), SDK_HANGUP_S)
                except Exception:  # noqa: BLE001, S110 — 끝났는지는 아래에서 본다
                    pass
                until = self.clock() + END_GRACE_S - SDK_HANGUP_S  # SDK 의 종료 프레임(2초)을 잠깐 기다린다
                while not self.confirmed() and self.clock() < until:
                    await self.sleep(POLL_S)
            if not self.confirmed():
                await self.end_by_rest()
        if self.transferring is not None and not self.transferring.done():
            self.transferring.cancel()
        if self.agent is not None:
            try:
                await self.bounded(self.agent.disconnect(), SDK_HANGUP_S)
            except Exception:  # noqa: BLE001, S110
                pass

    async def end_by_rest(self) -> None:
        """SDK 의 공개 REST(`AsyncClawOps.calls.update`)로 통화를 끝낸다 — 한 번, 상한 REST_END_S, 오류는 종류만 로그."""
        s = self.kat._s
        failure = await end_by_rest(self.rest, _call_id(self.ours), key=s.key or "", account_id=s.account_id,
                                    base_url=s.base_url, bounded=self.bounded)
        if failure:
            logger.warning("음성 통화: 끝이 확인되지 않은 통화를 끝내지 못했습니다 (%s)", failure)
