"""한국AI통신 음성 연결 진단(계획 4 Task 60, 0단계 P5~P14). 설정 → 알림 연결 → AI 전화의 「음성 진단」이 부른다.

REST 반쪽(app.notify.diagnostics, P1~P4)과 같은 줄을 돌려준다(`VoiceStep` = `DiagnosticStep` + `data`). `run_voice_checks` 는
언제나 P5~P14 열 줄을 돌려준다(고르지 않은 걸음은 `skipped_not_requested`). `label`·`detail` 은 화면에 그대로 보이는 한국어 문장,
기계가 읽을 것은 `code`·`maybe_sent`·`data`·`notes`. 찍지 않고, 설정을 환경 변수에서 읽지 않고, 던지지 않는다(취소만 올린다).

- SDK 는 함수 안에서 불러온다(`load_sdk`) — 없으면 P5 가 `sdk_not_installed`, 뒤는 건너뜀. `sdk=` 는 시험이 대본 가짜를 끼우는
  자리(속성 이름은 `clawops.agent` 와 같다). 시험(pytest)에서는 실제 SDK 를 쓰지 않는다(`sdk_blocked_in_tests`).
- 걸음은 5~14 의 **정수 묶음**으로만 고른다. 글("6"·"P6")·참거짓·그 밖의 꼴이면 아무것도 하지 않는다(`bad_steps`).
- **실제로 거는 걸음(P6·P7·P8·P10)은 `steps` 에 있고 `call_to` 가 걸 수 있는 국내 번호 글일 때만**, 그 번호 하나로만 건다. SDK 의
  내장 도구(끊기·전환·키패드)는 모두 끈다 — 기본값에는 전환이 있어 모델이 다른 번호로 걸 수 있다. 통화는 진단이 끊는다:
  목표(도구 호출 / 첫 응답)를 본 뒤 `WRAP_UP_S`, 늦어도 건 뒤 `CALL_CUT_S`(60초 — 벨 시간 포함).
- 상한(`VoiceBudget`, 한 번 부를 때): 거는 통화 3통 · 받는 통화 2통(받기 1 + 거절 1).
- 건 통화의 결과를 모르면(발신 요청이 끝나지 않음·오류, 끊었는데 끝난 것이 확인되지 않음) 그 줄에 `maybe_sent`(전화가 걸렸을 수
  있다)가 서고, 그 뒤로는 걸지도 받지도 않고 연결을 닫는다. 도중에 끊기면(취소) 살아 있는 통화를 끊고 닫으며, 걸음이 돌아오지
  않으므로 부른 쪽은 넘겨 준 `VoiceBudget.maybe_live` 를 본다.
- 받는 통화(P12~P14)는 **건 번호가 `call_to` 와 같을 때만** 받거나(P12) 거절을 확인한다(P14). 다른 번호·읽을 수 없는 번호·창 밖의
  통화는 받기 전에 거절한다. 실제 SDK 는 훅이 없으면 모두 받고 훅이 던지거나 5초 안에 정하지 않으면 받으므로: 훅은 연결 전에
  걸고, 기다리지 않고(동기), 던지지 않고, 기본이 거절이다. 그래도 시작돼 버린 통화는 곧바로 끊는다.
- control 연결은 **번호당 하나**(또 붙으면 먼저 붙은 프로세스를 밀어낸다): 음성 일꾼이 그 번호로 붙어 있으면 부르는 쪽이
  `worker_connected=True` 를 넘기고, 진단은 SDK 를 건드리지 않고 `worker_connected` 로 끝난다. 에이전트에 묶을 번호
  (`agent_number` — 플랫폼에서 받은 070 번호)는 문자 발신번호(`conn.sender`)와 다를 수 있어 따로 받는다.
- 키(제공사 키·Account ID·음성 모델 키)는 SDK 를 건드리기 전에 `redact.add_secrets` 에 올린다. `detail`·`notes` 는 `diagnostics.scrub`
  을 거치고, 예외는 종류 이름과 SDK 가 준 짧은 코드만 `notes` 에(SDK 예외 글에는 계정·번호가 든다). 전사 글은 읽지 않고(수와
  역할만), 건 번호는 값 없이 읽혔는지(`data.readable`)만. 진단 동안 SDK 로거(`clawops.*` — INFO 로 건·받은 번호, 거절 때
  ERROR 로 계정·번호를 남긴다)의 줄도 같은 scrub 을 거치고, SDK 의 준비 표시 파일은 끈다(`CLAWOPS_READY_FILE=""`, 끝나면 되돌림).

code 낱말: `ok` · `skipped_*`(not_requested·no_sdk·not_connected·no_number·no_language·no_call·stopped·no_inbound) · `bad_steps` ·
`worker_connected` · `sdk_not_installed` · `sdk_blocked_in_tests` · `sdk_extra_missing` · `sdk_signature` · `bad_base_url` · `resolve_failed` ·
`bad_key` · `bad_account` · `no_agent_number` · `bad_voice` · `timeout` · `network` · `rejected` · `bad_number`(P11) · `call_limit` ·
`dial_timeout` · `cut_unconfirmed` · `no_answer` · `busy` · `declined` · `canceled` · `call_failed` · `no_transcript` · `no_tool_call` ·
`not_supported`(P9) · `bad_wait` · `inbound_limit` · `no_inbound` · `caller_unreadable` · `not_allowed_caller` · `accepted_not_started` ·
`reject_not_applied` · `unknown`, 발신 요청이 거절되면 REST 와 같은 `bad_request` · `rate_limited` · `server`.

확인한 것 — 깔린 패키지(`koreaaitel[agent,gemini]==0.78.0`, import 이름 `clawops`)의 서명·docstring·소스: `clawops.agent` 의
`ClawOpsAgent`(`connect`·`call`·`disconnect`·`on`·`tool`·`on_incoming`) · `CallSession.hangup`(받은 뒤에만 듣는다) · `IncomingCall` ·
`BuiltinTool` · `GeminiRealtime`·`OpenAIRealtime` · 오류의 `code`·`status`. 공개 문서(platform.koreaaitel.com/docs)는 voice-agent ·
getting-started · voice-agent/providers · call-blocking · call-failure-causes. 이름마다의 서명과 문서 자리는 작업 보고서
(task-60-report.md)에, 실제 계정으로만 알 수 있는 것은 코드에 `# P0 확인` 으로 적었다.
"""

import asyncio
import importlib
import inspect
import logging
import re
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial

from app.notify import diagnostics
from app.notify.diagnostics import NOT_REQUESTED, DiagnosticConn, DiagnosticStep, scrub
from app.notify.voice_sdk_logs import _quiet_sdk, session_failure
from app.outreach import phone, redact
from app.outreach.voice.numbers import GOOGLE_LIVE_API_VERSION

SDK_MODULE = "clawops.agent"  # 배포 이름은 koreaaitel, import 이름은 clawops
SDK_LOGGERS = ("clawops", "clawops.agent", "clawops.agent.pipeline", "clawops.agent.prewarm", "clawops.agent.livekit")
READY_ENV = "CLAWOPS_READY_FILE"  # SDK 의 준비 표시 파일 경로 — 빈 값이면 끈다
MAX_CALLS, MAX_INBOUND = 3, 2  # 한 번 부를 때 거는 통화 · 받는 통화(받기 1 + 거절 1)
CALL_CUT_S = 60  # 건 뒤(벨 시간 포함) 이만큼 지나면 우리가 끊는다
RING_TIMEOUT_S = 20  # 벨 울리는 시간. SDK 에는 아래 한계가 없다 — 사람이 받을 수 있는 가장 짧은 쪽으로(60초 안에 든다)
WRAP_UP_S = 8  # 목표(도구 호출·첫 응답)를 본 뒤 끊기까지 — 에이전트가 문장을 끝낼 시간
CONNECT_TIMEOUT_S, DIAL_TIMEOUT_S, HANGUP_TIMEOUT_S = 20, 15, 5  # SDK 의 연결·발신 요청·끊기를 기다리는 시간
END_GRACE_S = 5  # 끊은 뒤 끝났다는 사건을 기다리는 시간
SDK_HANGUP_S = 8.0  # SDK 의 끊기를 기다리는 끝 — 끊기는 보낸 소리가 다 나갈 때까지(mark) 5초까지 기다린다(자르지 않게, 어댑터와 같다)
REST_END_S = 10.0  # 끝이 확인되지 않은 통화를 REST(calls.update)로 끝내는 요청을 기다리는 끝(어댑터와 같다)
INBOUND_START_S, INBOUND_HOLD_S = 15, 20  # 받은 통화가 시작되기를 기다리는 시간 · 붙들고 있는 가장 긴 시간
REJECT_GRACE_S = 3  # 거절한 통화가 그래도 시작되는지 보는 시간
MAX_WAIT_INBOUND_S, TICK_S = 180, 0.1
STEPS = tuple(range(5, 15))
LINKED = frozenset(STEPS) - {9}  # 플랫폼 연결이 있어야 하는 걸음
SESSIONS = {"google": "GeminiRealtime", "openai": "OpenAIRealtime"}
LABELS = {"P5": "음성 SDK · 플랫폼 연결", "P6": "한국어 시험 통화", "P7": "통화 중 받아쓰기", "P8": "통화 중 도구 호출",
          "P9": "음성 목록 · 샘플", "P10": "둘째 언어 통화", "P11": "AI 전화 번호를 에이전트에 묶기",
          "P12": "걸려 온 통화 받기", "P13": "건 번호 읽기", "P14": "받지 않고 거절하기"}
FIRST_LINES = {"ko": "안녕하세요, ChronOS 연결 진단 전화입니다. 이 통화는 녹음하지 않습니다.",
               "en": "Hello, this is a ChronOS connection test call. This call is not recorded."}
DIAG_FACT = "진단 확인 문장입니다. 도구 호출이 정상입니다."
_KO = ("당신은 ChronOS 의 연결 진단 전화입니다. 통화가 연결되면 다음 문장을 한 글자도 바꾸지 않고 먼저 말합니다: 「{line}」 그다음 "
       "{then}「진단을 마칩니다. 감사합니다.」 라고 말합니다. 다른 이야기는 하지 않고, 무엇을 물어도 「연결 진단 전화라 답할 수 "
       "없습니다」 라고만 답합니다. 통화는 진단 프로그램이 끊습니다.")
_PROMPT_TOOL = _KO.replace("{then}", "상대가 무슨 말을 하든 도구 diag_fact 를 한 번만 부르고, 받은 문장을 그대로 읽어 준 뒤 ")
_PROMPT_PLAIN = {
    "ko": _KO.replace("{then}", ""),
    "en": ('You are the ChronOS connection test call. When the call connects, first say exactly this sentence: "{line}" '
           'Then say "The test is complete. Thank you." Do not talk about anything else; whatever you are asked, answer '
           'only "This is a connection test call, so I cannot answer." The test program ends the call.'),
}

BAD_STEPS = "진단할 걸음을 읽지 못해 아무것도 하지 않았습니다(프로그램 설정 문제입니다)."
WORKER_CONNECTED = ("AI 전화가 이 번호로 연결돼 있어 진단하지 않았습니다 — 진단이 연결하면 AI 전화의 연결이 끊깁니다. "
                    "AI 전화를 잠시 끈 뒤 다시 해 주세요.")
NOT_INSTALLED = "음성 SDK 가 설치돼 있지 않습니다."
BLOCKED_IN_TESTS = "시험에서는 실제 음성 SDK 를 쓰지 않습니다."
EXTRA_MISSING = "고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다."
BAD_SHAPE = "설치된 음성 SDK 가 확인해 둔 판과 달라 진단하지 못했습니다."
NO_AGENT_NUMBER = "AI 전화에 쓸 번호(플랫폼에서 받은 번호)가 없거나 전화를 걸 수 없는 번호입니다."
BAD_PROVIDER = "음성 모델 공급자를 읽지 못했습니다(구글 또는 OpenAI 여야 합니다)."
BAD_MODEL = "음성 모델 이름에 쓸 수 없는 글자가 있습니다."
CONNECT_TIMEOUT = "플랫폼 연결이 시간 안에 되지 않았습니다. 이 서버에서 밖으로 나가는 연결을 확인해 주세요."
NETWORK = "플랫폼에 연결하지 못했습니다."
REJECTED = "플랫폼이 연결을 거절했습니다. API 키와 AI 전화 번호를 확인해 주세요."
AUTH = {"api_key_invalid": diagnostics.MESSAGES["bad_key"], "api_key_missing": "API 키가 플랫폼에 전달되지 않았습니다."}
NUMBER = {"number_not_owned": "AI 전화 번호가 이 계정의 번호가 아닙니다(반납·회수됐거나 다른 계정의 번호).",
          "number_missing": "AI 전화 번호가 플랫폼에 전달되지 않았습니다."}
NO_SDK = "음성 SDK 가 없어 확인하지 않았습니다."
NOT_LINKED = "플랫폼에 연결되지 않아 확인하지 않았습니다."
NO_NUMBER = "허용 번호가 없어 전화를 걸거나 받지 않았습니다 — 허용 번호로만 걸고, 허용 번호에서 온 전화만 받습니다."
NO_LANG = "이 언어의 진단 첫마디가 없어 전화를 걸지 않았습니다."
NO_CALL = "통화가 연결되지 않아 확인하지 못했습니다."
CALL_LIMIT = f"통화 상한(한 번에 {MAX_CALLS}통)을 넘어 걸지 않았습니다."
INBOUND_LIMIT = f"받는 통화 상한(한 번에 {MAX_INBOUND}통)을 넘어 받지 않았습니다."
MAYBE_PLACED = "전화가 걸렸을 수도 있습니다. 다시 누르면 또 걸릴 수 있습니다."
DIAL_TIMEOUT = "발신 요청이 시간 안에 끝나지 않아 더 걸지 않았습니다."
DIAL_UNKNOWN = "발신 요청 중 오류가 나 더 걸지 않았습니다."
DIAL_REFUSED = "플랫폼이 발신 요청을 받지 않았습니다."
CUT_UNCONFIRMED = ("끊으려 했지만 통화가 끊겼는지 확인하지 못했습니다 — 휴대전화에서 직접 끊어 주세요. 연결을 닫고 더 걸거나 "
                   "받지 않았습니다.")
STOPPED = "앞 통화가 끝났는지 확인되지 않아 더 걸거나 받지 않았습니다."
BAD_WAIT = "기다릴 시간을 읽지 못해 걸려 오는 전화를 확인하지 않았습니다(프로그램 설정 문제입니다)."
NOT_SUPPORTED = "음성 목록은 SDK 가 제공하지 않습니다 — 음성 이름은 설정에서 직접 고릅니다"
NO_RESPONSE_TIME = "첫 응답 시간은 재지 못했습니다(받아쓰기가 오지 않음)"
CRASHED = "진단 중 오류가 나 이 걸음을 끝내지 못했습니다."
NO_MODEL = "AI 음성 모델에 연결하지 못했습니다"
NO_MODEL_HINT = {404: " 모델을 다시 골라 주세요.", 400: " 음성 모델 키를 확인해 주세요.", 401: " 음성 모델 키를 확인해 주세요.",
                 403: " 음성 모델 키를 확인해 주세요."}
NO_MODEL_SKIP = "AI 음성 모델에 연결되지 않아 확인하지 못했습니다."
REASONS = {"no-answer": ("no_answer", "전화를 받지 않았습니다."), "busy": ("busy", "통화 중이었습니다."),
           "rejected": ("declined", "상대가 전화를 거절했습니다."), "canceled": ("canceled", "전화가 취소됐습니다."),
           "failed": ("call_failed", "전화 연결에 실패했습니다.")}
ROLES = {"assistant": "에이전트", "user": "상대", "other": "그 밖"}
_WORD = re.compile(r"[A-Za-z0-9_\-]{1,40}")
_MODEL = re.compile(r"[A-Za-z0-9._\-]{1,80}")

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class VoiceDiag:
    """음성 모델 설정. 키는 이 값과 SDK 호출에만 있고 결과·repr 에는 없다."""

    provider: str  # "google"(GeminiRealtime) | "openai"(OpenAIRealtime)
    key: str = field(repr=False)
    model: str | None = None  # None 이면 SDK 기본값


@dataclass
class VoiceBudget:
    """한 번의 진단이 쓴 통화 수(상한 MAX_CALLS·MAX_INBOUND). 같은 것을 다시 넘기면 이어서 센다."""

    placed: int = 0
    received: int = 0
    maybe_live: bool = False  # 건 통화가 끝난 것이 확인되지 않았다(도중에 끊긴 진단은 이것을 본다 — 다시 걸지 말 것)

    def take_call(self) -> bool:
        ok = self.placed < MAX_CALLS
        self.placed += ok  # 걸려고 한 순간부터 한 통
        return ok

    def take_inbound(self, *, peek: bool = False) -> bool:
        ok = self.received < MAX_INBOUND
        self.received += ok and not peek
        return ok


@dataclass
class VoiceStep(DiagnosticStep):
    """REST 반쪽과 같은 줄 + `data`(참거짓·수·고정 낱말만 — 번호·키·전사 글은 넣지 않는다). `maybe_sent` 는 「전화가 걸렸을 수 있다」."""

    data: dict = field(default_factory=dict)


class _Fail(Exception):
    """걸음의 실패: code 는 기계가 읽는 낱말, detail 은 사람이 읽는 문장, note 는 접어 보일 기계 글."""

    def __init__(self, code: str, detail: str, note: str = "") -> None:
        super().__init__(code)
        self.code, self.detail, self.note = code, detail, note


def load_sdk() -> object:
    """음성 SDK(`clawops.agent`)를 불러온다 — 이 모듈을 불러올 때는 부르지 않는다. 없으면 `sdk_not_installed`, 시험에서는 쓰지 않는다."""
    try:
        sdk = importlib.import_module(SDK_MODULE)
    except ImportError:
        raise _Fail("sdk_not_installed", NOT_INSTALLED) from None
    if "pytest" in sys.modules:
        raise _Fail("sdk_blocked_in_tests", BLOCKED_IN_TESTS)
    return sdk


def _word(value: object, default: str) -> str:
    """SDK·플랫폼이 준 짧은 낱말(코드·상태)만 그대로, 아니면 default."""
    return value if isinstance(value, str) and _WORD.fullmatch(value) else default


def _sdk_error(e: Exception) -> tuple[str, object, str]:
    """SDK 예외에서 남길 것: (짧은 코드, HTTP 상태, 접어 보일 글). 예외 글은 버린다 — 계정·번호가 든다."""
    code, raw = _word(getattr(e, "code", None), ""), getattr(e, "status", None)
    raw = raw if type(raw) is int else None
    # 4xx 만 「플랫폼이 거절 — 걸리지 않음」. 5xx(통화를 만든 뒤 프록시가 낸 오류일 수 있다)·2xx(만들었는데 답을 못 읽음)는 모름
    status = raw if raw is not None and 400 <= raw < 500 else None
    return code, status, f"예외: {type(e).__name__} · code={code or '-'} · HTTP {raw or '-'}"


def _secret_problem(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return f"{name}가 비어 있습니다."
    if not value.isascii() or not value.isprintable():
        return f"{name}에 쓸 수 없는 글자가 있습니다."
    return f"{name}가 너무 짧습니다({diagnostics.MIN_SECRET}자 이상)." if len(value) < diagnostics.MIN_SECRET else ""


def _number(raw: object) -> str | None:
    """걸 수 있는 국내 번호 글이면 숫자만 남긴 꼴, 아니면 None. 글이 아닌 값(True·1·목록)은 번호가 아니다."""
    return phone.normalize(raw) if isinstance(raw, str) and phone.can_call(raw) else None


def _picked(steps: object) -> list[int] | None:
    ok = isinstance(steps, tuple | list | set | frozenset) and all(type(s) is int and s in STEPS for s in steps)
    return sorted(set(steps)) if ok else None


async def end_by_rest(rest: object, call_id: object, *, key: str, account_id: str, base_url: str,
                      bounded: Callable[[Awaitable, float], Awaitable[object]]) -> str:
    """끝이 확인되지 않은 통화를 SDK 의 공개 REST(`AsyncClawOps(...).calls.update(call_id, status="completed")`)로 끝낸다 — 한 번,
    REST_END_S, 프록시 환경을 믿지 않는 클라이언트, 다시 시도 없음. 던지지 않는다: 성공이면 "", 아니면 예외의 종류 이름(글은 버린다 —
    계정·번호가 든다). 진단(우리가 건 통화만)과 SDK 어댑터(kat_sdk)가 같이 쓴다. 결과(모름)는 부르는 쪽이 바꾸지 않는다."""
    if not isinstance(call_id, str) or not call_id:
        return "no_call_id"
    http = diagnostics.make_client()
    try:
        client = rest.AsyncClawOps(api_key=key, account_id=account_id, base_url=base_url.rstrip("/"), max_retries=0,
                                   http_client=http)
        await bounded(client.calls.update(call_id, status="completed"), REST_END_S)
        return ""
    except Exception as e:  # noqa: BLE001
        return type(e).__name__
    finally:
        try:
            await http.aclose()
        except Exception:  # noqa: BLE001, S110
            pass


def _call_id(obj: object) -> str:
    call_id = getattr(obj, "call_id", None)
    return call_id if isinstance(call_id, str) and call_id else f"?{id(obj)}"


class _Call:
    """통화 하나에서 본 것. 전사 글과 번호는 담지 않는다."""

    def __init__(self, at: float, *, wanted: bool) -> None:
        self.at, self.wanted = at, wanted  # 걸거나 걸려 온 때 · 우리가 걸었거나 받기로 한 통화인가
        self.session: object | None = None  # SDK 의 CallSession
        self.started: float | None = None
        self.first: float | None = None  # 에이전트의 첫 전사
        self.tool_at: float | None = None  # 도구가 처음 불린 때
        self.roles: Counter[str] = Counter()
        self.tools = 0
        self.ended = self.cut = self.hung = self.maybe = False  # 끝남 · 60초에 우리가 끊음 · 끊기를 불러 봄 · 결과를 모름
        self.failed = ""  # call_failed 의 사유 낱말
        self.rest_tried = False  # 끝이 확인되지 않아 REST 로 끝내 봤다(한 번만)
        self.error: _Fail | None = None  # 걸지 못한 까닭


class _Run:
    """진단 한 번: 에이전트 하나, 그 통화들, 걸음 결과."""

    def __init__(self, conn: DiagnosticConn, voice: VoiceDiag, agent_number: object, call_to: object, sleep: Sleep,
                 clock: Clock, budget: VoiceBudget, resolve: object) -> None:
        self.conn, self.voice, self.sleep, self.clock, self.budget, self.resolve = conn, voice, sleep, clock, budget, resolve
        self.to, self.number = _number(call_to), _number(agent_number)
        self.secrets = [getattr(conn, "key", None), getattr(conn, "account_id", None), getattr(voice, "key", None)]
        self.numbers = [n for n in (agent_number, call_to, getattr(conn, "sender", None), getattr(conn, "test_to", None))
                        if isinstance(n, str)]
        self.sdk = self.agent = None  # SDK(또는 가짜) · 만든 에이전트
        self.rest: object | None = None  # REST 클라이언트가 든 모듈(clawops — 가짜면 같은 객체)
        self.version, self.connect_ms = "?", None
        self.refused_number = False  # 연결이 번호 때문에 거절됐다(플랫폼까지는 갔다)
        self.spec = ("ko", "")  # 다음 통화의 (언어, 지시문) — 세션 팩토리가 읽는다
        self.calls: dict[str, _Call] = {}
        self.dials: list[_Call] = []
        self.live: _Call | None = None  # 지금 걸고 있는 통화
        self.dead = False  # 더 걸거나 받지 않는다
        self.gate: str | None = None  # 받는 창: None(모두 거절) | "accept" | "reject"
        self.caught: str | None = None  # 창에서 잡은(허용 번호의) 통화 id
        self.seen: Counter[str] = Counter()  # 창에서 본 통화: match · stranger · unreadable · over
        self.restricted = self.reject_seen = False  # 번호 표시 제한 · 거절을 부른 뒤 SDK 가 거절로 표시했는가
        self.no_model: dict[str, int | None] = {}  # AI 음성 모델 세션을 열지 못한 통화 id → HTTP 상태(SDK 로그 줄에서)
        self.out: dict[int, VoiceStep] = {}

    def saw(self, record: logging.LogRecord) -> None:
        """SDK 로그 가운데 AI 음성 모델 세션을 열지 못한 줄만 — 통화 id 와 HTTP 상태만 남긴다."""
        found = session_failure(record)
        if found is not None:
            self.no_model[found[0]] = found[1]

    def model_failed(self, call: _Call) -> str | None:
        """그 통화에서 SDK 가 AI 음성 모델 세션을 열지 못했으면 사람이 읽을 까닭(HTTP 상태만), 아니면 None."""
        if call.session is None or _call_id(call.session) not in self.no_model:
            return None
        status = self.no_model[_call_id(call.session)]
        return f"{NO_MODEL}(응답 코드 {status}).{NO_MODEL_HINT.get(status, '')}" if status else f"{NO_MODEL}."

    def clean(self, text: object, limit: int = 200) -> str:
        return scrub(text, secrets=self.secrets, numbers=self.numbers, limit=limit)

    def put(self, n: int, code: str, detail: str, *, ok: bool = False, skipped: bool = False, ms: int | None = None,
            notes: tuple[str, ...] | list[str] = (), data: dict | None = None, maybe: bool = False) -> None:
        text = self.clean(detail) + (f" {MAYBE_PLACED}" if maybe else "")
        self.out[n] = VoiceStep(id=f"P{n}", label=LABELS[f"P{n}"], ok=ok and not skipped, detail=text, latency_ms=ms,
                                skipped=skipped, notes=[self.clean(x, 500) for x in notes if x], code=code,
                                maybe_sent=maybe, data=data or {})

    def skip(self, n: int, code: str, detail: str, **kw: object) -> None:
        self.put(n, code, detail, skipped=True, **kw)

    async def bounded(self, awaitable: Awaitable, limit: float) -> object:
        """SDK 의 일을 우리 시계로 limit 초까지만 기다린다. 넘으면(또는 SDK 가 그만두면) 그 일을 취소하고 TimeoutError."""
        task = asyncio.ensure_future(awaitable)
        deadline = self.clock() + limit
        try:
            while not task.done():
                if self.clock() >= deadline:
                    raise TimeoutError
                await self.sleep(TICK_S)
        finally:
            if not task.done():
                task.cancel()
        if task.cancelled():
            raise TimeoutError
        return task.result()

    # ── P5·P11: 불러오기 → 검사 → 에이전트 → 연결 ──────────────────────────────

    def preflight(self) -> _Fail | None:
        conn, voice = self.conn, self.voice
        problem = diagnostics.base_url_problem(getattr(conn, "base_url", None))
        if problem:
            return _Fail("bad_base_url", problem)
        provider, model = getattr(voice, "provider", None), getattr(voice, "model", None)
        if not isinstance(provider, str) or provider not in SESSIONS:
            return _Fail("bad_voice", BAD_PROVIDER)
        if model is not None and not (isinstance(model, str) and _MODEL.fullmatch(model)):
            return _Fail("bad_voice", BAD_MODEL)
        for value, code, name in zip(self.secrets, ("bad_key", "bad_account", "bad_voice"),
                                     ("API 키", "Account ID", "음성 모델 키"), strict=True):
            problem = _secret_problem(value, name)
            if problem:
                return _Fail(code, problem)
        return None if self.number is not None else _Fail("no_agent_number", NO_AGENT_NUMBER)

    def prompt(self, lang: str, *, tool: bool) -> str:
        return (_PROMPT_TOOL if tool else _PROMPT_PLAIN[lang]).format(line=FIRST_LINES[lang])

    def session(self) -> object:
        """통화마다 세션 하나(SDK 의 session_factory). 지시문에는 고정 첫마디만 있고 번호·키가 없다."""
        lang, prompt = self.spec
        kw = {"api_key": self.voice.key, "system_prompt": prompt, "language": lang}
        if self.voice.model:
            kw["model"] = self.voice.model
        if self.voice.provider == "google":
            kw["api_version"] = GOOGLE_LIVE_API_VERSION  # Live 모델은 v1alpha 에만 있다(고침 2)
        return getattr(self.sdk, SESSIONS[self.voice.provider])(**kw)

    async def link(self, sdk: object | None, worker_connected: object) -> None:
        """실패하면 _Fail. 번호 때문에 거절된 것은 `refused_number` 가 선다(P5 는 닿았고 P11 이 실패)."""
        if worker_connected is not False:  # 참이 아닌 값(글·None)도 연결하지 않는 쪽으로
            raise _Fail("worker_connected", WORKER_CONNECTED)
        self.sdk = sdk if sdk is not None else load_sdk()
        self.rest = sdk if sdk is not None else sys.modules.get(SDK_MODULE.split(".")[0])  # load_sdk 가 이미 불러왔다
        version = getattr(self.sdk, "__version__", None) or getattr(sys.modules.get("clawops"), "__version__", None)
        self.version = version if isinstance(version, str) and _MODEL.fullmatch(version) else "?"
        found = self.preflight()
        if found is not None:
            raise found
        problem = await diagnostics.resolve_problem(self.conn, self.resolve)
        if problem:
            raise _Fail("resolve_failed" if problem == diagnostics.RESOLVE_FAILED else "bad_base_url", problem)
        try:
            self.spec = ("ko", self.prompt("ko", tool=True))
            self.session()  # 고른 모델의 묶음(extra)이 깔렸는지 — 통화에는 팩토리가 새로 만든 것을 쓴다
            agent = self.sdk.ClawOpsAgent(
                api_key=self.conn.key, account_id=self.conn.account_id, base_url=self.conn.base_url.rstrip("/"),
                from_=self.number, session_factory=self.session, builtin_tools=self.sdk.BuiltinTool.NONE,
                recording=False, prewarm_enabled=False)  # prewarm 은 첫 인사 받아쓰기를 버린다(_BufferingCall)
            self.agent = agent
            agent.on_incoming(self.screen)  # 연결 전에 건다 — 훅이 없으면 SDK 는 걸려 온 통화를 모두 받는다
            for name in ("call_start", "call_end", "call_failed", "transcript"):
                agent.on(name)(partial(self.event, name))
            agent.tool(self.diag_fact)
        except ImportError:
            raise _Fail("sdk_extra_missing", EXTRA_MISSING) from None
        except (AttributeError, TypeError) as e:
            raise _Fail("sdk_signature", BAD_SHAPE, f"예외: {type(e).__name__}") from None
        started = self.clock()
        try:
            await self.bounded(agent.connect(), CONNECT_TIMEOUT_S)
        except TimeoutError:
            raise _Fail("timeout", CONNECT_TIMEOUT) from None
        except Exception as e:  # noqa: BLE001
            code, _, note = _sdk_error(e)
            self.refused_number = code in NUMBER
            if code in NUMBER or code in AUTH:
                raise _Fail("bad_number" if code in NUMBER else "bad_key", (NUMBER | AUTH)[code], note) from None
            rejected = type(e).__name__ == "AgentAuthRejectedError"
            raise _Fail("rejected" if rejected else "network", REJECTED if rejected else NETWORK, note) from None
        self.connect_ms = round((self.clock() - started) * 1000)

    def report_link(self, fail: _Fail | None) -> None:
        data = {"sdk_version": self.version} if self.sdk is not None else {}
        if fail is None:
            self.put(5, "ok", f"음성 SDK {self.version} · 플랫폼에 연결됐습니다 · {self.connect_ms}ms", ok=True,
                     ms=self.connect_ms, data=data, notes=[f"import {SDK_MODULE} · 버전 {self.version}",
                                                           f"세션 {SESSIONS[self.voice.provider]} · connect() {self.connect_ms}ms"])
        elif self.refused_number:  # 플랫폼까지는 갔다 — 걸린 것은 번호(P11)
            self.put(5, "ok", f"음성 SDK {self.version} · 플랫폼에는 닿았지만 AI 전화 번호가 거절됐습니다"
                              "(「AI 전화 번호를 에이전트에 묶기」 줄을 보세요).", ok=True, notes=[fail.note], data=data)
        else:
            self.put(5, fail.code, fail.detail, notes=[fail.note], data=data)

    def report_bind(self, fail: _Fail | None, *, told: bool) -> None:
        if fail is None:
            # P0 확인: 연결될 때 플랫폼이 번호 소유를 본다. 걸려 온 통화가 실제로 이 에이전트로 오는지는 P12 가 본다.
            self.put(11, "ok", "AI 전화 번호가 에이전트에 묶였습니다. 걸려 오는 전화가 실제로 오는지는 「걸려 온 통화 받기」에서 "
                               "확인합니다.", ok=True, data={"method": "ClawOpsAgent(from_=…) + connect()"})
        elif self.refused_number:
            self.put(11, fail.code, fail.detail, notes=[fail.note])
        else:
            self.not_linked(11, fail, told=told)

    def not_linked(self, n: int, fail: _Fail, *, told: bool) -> None:
        # 까닭을 보일 P5 줄이 없으면(told False) 까닭 문장을 붙인다
        self.skip(n, "skipped_not_connected", NOT_LINKED if told else f"{NOT_LINKED} {fail.detail}",
                  notes=[f"연결 실패: {fail.code}"])

    def voices(self) -> None:
        if self.sdk is None:
            return self.skip(9, "skipped_no_sdk", NO_SDK)
        notes = []
        for name in SESSIONS.values():
            try:
                default = inspect.signature(getattr(self.sdk, name)).parameters["voice"].default
                notes.append(f"{name} 의 voice 기본값: {_word(default, '?')}")
            except Exception:  # noqa: BLE001, S110 — 없는 묶음·다른 서명은 적지 않는다
                pass
        return self.skip(9, "not_supported", NOT_SUPPORTED, notes=notes)

    def lookup(self, sdk_call: object) -> _Call:
        call_id = _call_id(sdk_call)
        call = self.calls.get(call_id)
        if call is None:
            live = self.live
            if live is not None and live.session is None and getattr(sdk_call, "direction", None) != "inbound":
                call = live  # 거는 중(call() 이 돌아오기 전)에 온 사건
            else:
                call = _Call(self.clock(), wanted=False)  # 받기로 한 적 없는 통화
            self.calls[call_id] = call
        if call.session is None:
            call.session = sdk_call
        return call

    async def event(self, name: str, sdk_call: object, *args: object) -> None:
        """SDK 의 통화 사건. 전사는 수와 역할만 세고 글(args[1])은 읽지 않는다. SDK 의 사건 처리로 던지지 않는다."""
        try:
            call = self.lookup(sdk_call)
            if name == "call_end":
                call.ended = True
            elif name == "call_failed":
                call.failed, call.ended = _word(args[0] if args else None, "failed"), True
            elif name == "transcript":
                role = args[0] if args and args[0] in ("user", "assistant") else "other"
                call.roles[role] += 1
                if role == "assistant" and call.first is None:
                    call.first = self.clock()
            elif name == "call_start":
                call.started = self.clock()
                if not call.wanted:  # 거절했거나 창 밖인데 시작됐다(SDK 는 훅이 늦으면 받는다) — 곧바로 끊는다
                    call.hung = True
                    await self.bounded(sdk_call.hangup(), SDK_HANGUP_S)
        except Exception:  # noqa: BLE001, S110
            pass

    async def diag_fact(self) -> str:
        """연결 진단용 문장 하나를 돌려준다. 인자는 없다."""
        call = self.live
        if call is not None:
            call.tools, call.tool_at = call.tools + 1, self.clock() if call.tool_at is None else call.tool_at
        return DIAG_FACT

    def admit(self, incoming: object) -> str:
        """걸려 온 통화의 판정: "accept" | "reject_caught"(P14 가 기다린 통화) | "reject"."""
        gate = self.gate
        if gate is None or self.dead:
            return "reject"
        try:
            raw = incoming.from_number
            number = phone.normalize(raw) if isinstance(raw, str) else None
            restricted = incoming.caller_id_restricted is True
        except Exception:  # noqa: BLE001
            number, restricted = None, False
        kind = ("unreadable" if number is None else "stranger" if number != self.to
                else "match" if self.budget.take_inbound() else "over")
        self.seen[kind] += 1
        if kind == "stranger":
            return "reject"
        self.restricted = restricted
        if kind != "match":
            return "reject"
        self.gate, self.caught = None, _call_id(incoming)  # 창마다 한 통
        self.calls[self.caught] = _Call(self.clock(), wanted=gate == "accept")
        return "accept" if gate == "accept" else "reject_caught"

    def screen(self, incoming: object) -> None:
        """`@agent.on_incoming` 훅 — 기본이 거절. 기다리지 않고(SDK 는 5초 뒤 받는다) 던지지 않는다(SDK 는 훅이 던지면 받는다)."""
        try:
            verdict = self.admit(incoming)
        except Exception:  # noqa: BLE001
            verdict = "reject"
        if verdict == "accept":
            return
        try:
            incoming.reject()  # 기본 사유 "rejected"(SIP 403)
            seen = incoming.rejected is True
        except Exception:  # noqa: BLE001
            seen = False
        if verdict == "reject_caught":
            self.reject_seen = seen

    # ── P6~P8·P10: 거는 통화 ──────────────────────────────────────────────────

    async def hang_up(self, call: _Call) -> None:
        """끊고, 끝났다는 사건을 잠깐 기다린다. 끝난 것이 확인되지 않으면 진단을 멈추고, **우리가 건 통화면**(받은 통화는 아니다)
        REST 로 끝낸다(벨이 울리는 중이면 SDK 의 끊기는 아무 일도 하지 않고, 연결을 닫아도 미디어·모델 세션은 남는다). 결과는 그대로
        「끝났는지 모름」이다."""
        if call.session is not None and not call.ended and not call.hung:
            call.hung = True
            try:
                await self.bounded(call.session.hangup(), SDK_HANGUP_S)
            except Exception:  # noqa: BLE001, S110 — 아래에서 끝났는지로 판단한다
                pass
        until = self.clock() + END_GRACE_S
        while not call.ended and self.clock() < until:
            await self.sleep(TICK_S)
        self.dead = self.dead or not call.ended
        if not call.ended and not call.rest_tried and call in self.dials and self.rest is not None:
            call.rest_tried = True
            await end_by_rest(self.rest, getattr(call.session, "call_id", None), key=self.conn.key,
                              account_id=self.conn.account_id, base_url=self.conn.base_url, bounded=self.bounded)

    async def watch(self, call: _Call, deadline: float, done: Callable[[], float | None]) -> None:
        """통화가 끝나거나, done() 이 준 때에서 WRAP_UP_S 가 지나거나, deadline 이 될 때까지 본 뒤 살아 있으면 끊는다."""
        while not call.ended and self.clock() < deadline:
            reached = done()
            if reached is not None and self.clock() >= reached + WRAP_UP_S:
                break
            await self.sleep(TICK_S)
        if not call.ended:
            call.cut = self.clock() >= deadline
            await self.hang_up(call)

    async def dial(self, lang: str, *, tool: bool) -> _Call:
        call = _Call(self.clock(), wanted=True)
        if not self.budget.take_call():
            call.error = _Fail("call_limit", CALL_LIMIT)
            return call
        self.dials.append(call)
        self.spec, self.live, self.budget.maybe_live = (lang, self.prompt(lang, tool=tool)), call, True
        try:
            # timeout 은 벨 울리는 시간. P0 확인: 받지 않으면 플랫폼이 그 시간에 call_failed(no-answer)를 보내는지.
            session = await self.bounded(self.agent.call(self.to, timeout=RING_TIMEOUT_S), DIAL_TIMEOUT_S)
            call.session = call.session or session
            self.calls.setdefault(_call_id(session), call)
            await self.watch(call, call.at + CALL_CUT_S, (lambda: call.tool_at) if tool else (lambda: call.first))
            call.maybe = not call.ended
        except TimeoutError:
            call.error, call.maybe, self.dead = _Fail("dial_timeout", DIAL_TIMEOUT), True, True
        except Exception as e:  # noqa: BLE001
            code, status, note = _sdk_error(e)
            if status is not None:  # 플랫폼이 답했다(201 아님) — 걸리지 않았다
                ours, text = diagnostics.http_failure(status, code)
                call.error, call.ended = _Fail(ours, f"{DIAL_REFUSED} {text}", note), True
            else:  # 요청이 나갔는지 모른다
                call.error, call.maybe, self.dead = _Fail("unknown", DIAL_UNKNOWN, note), True, True
        finally:
            self.live = None
        return call

    def response_ms(self, call: _Call) -> int | None:
        """받은 때부터 에이전트의 첫 전사까지. P0 확인: 전사가 소리와 같은 때에 오는지(미리 데워 둔 인사는 0 에 가깝다)."""
        if call.started is None or call.first is None:
            return None
        return max(0, round((call.first - call.started) * 1000))

    def report_call(self, n: int, call: _Call) -> None:
        if call.error is not None:
            return self.put(n, call.error.code, call.error.detail, notes=[call.error.note], maybe=call.maybe)
        if not call.ended:
            return self.put(n, "cut_unconfirmed", CUT_UNCONFIRMED, maybe=True)
        no_model = self.model_failed(call)
        if no_model is not None:
            status = self.no_model[_call_id(call.session)]
            return self.put(n, "model_connect_failed", no_model, data={"http_status": status})
        if call.started is None:
            code, text = REASONS.get(call.failed, REASONS["failed"])
            return self.put(n, code, text, notes=[f"call_failed: {call.failed or '-'}"])
        ms = self.response_ms(call)
        parts = ["통화가 연결됐습니다", f"첫 응답 {ms}ms" if ms is not None else NO_RESPONSE_TIME]
        if call.cut:
            parts.append(f"{CALL_CUT_S}초에 끊었습니다")
        return self.put(n, "ok", " · ".join(parts), ok=True, data={"first_response_ms": ms, "cut": call.cut})

    def report_in_call(self, n: int, call: _Call) -> None:
        """P7(전사 이벤트의 수와 역할) · P8(도구 호출 수)."""
        if call.error is not None or call.started is None:
            return self.skip(n, "skipped_no_call", NO_CALL, maybe=call.maybe)
        if self.model_failed(call) is not None:
            return self.skip(n, "skipped_no_model", NO_MODEL_SKIP)
        total = sum(call.roles.values())
        if n == 8 and call.tools:
            return self.put(8, "ok", f"통화 중 진단 도구가 {call.tools}번 불렸습니다.", ok=True, data={"tool_calls": call.tools})
        if n == 8:
            return self.put(8, "no_tool_call", "통화 중 진단 도구가 불리지 않았습니다.")
        if not total:
            return self.put(7, "no_transcript", "통화 중 받아쓰기가 오지 않았습니다.")
        tally = " · ".join(f"{ROLES[role]} {count}번" for role, count in sorted(call.roles.items()))
        return self.put(7, "ok", f"받아쓰기 {total}번 · {tally}", ok=True, data={"events": total, "roles": dict(call.roles)})

    def blocked(self, n: int) -> bool:  # 걸거나 받을 수 없으면 그 걸음을 건너뛴 줄로 남기고 True
        if self.to is None:
            self.skip(n, "skipped_no_number", NO_NUMBER)
        elif self.dead:
            self.skip(n, "skipped_stopped", STOPPED)
        return self.to is None or self.dead

    async def outbound(self, want: set[int], lang2: object) -> None:
        main = sorted(want & {6, 7, 8})
        if main and True not in [self.blocked(n) for n in main]:
            call = await self.dial("ko", tool=True)
            for n in main:
                (self.report_call if n == 6 else self.report_in_call)(n, call)
        if 10 not in want:
            return
        if not (isinstance(lang2, str) and lang2 != "ko" and lang2 in FIRST_LINES):
            self.skip(10, "skipped_no_language", NO_LANG,
                      notes=["쓸 수 있는 값: " + ", ".join(sorted(set(FIRST_LINES) - {"ko"}))])
        elif not self.blocked(10):
            self.report_call(10, await self.dial(lang2, tool=False))

    # ── P12~P14: 받는 통화 ────────────────────────────────────────────────────

    async def window(self, mode: str, seconds: int) -> _Call | None:
        """seconds 동안 허용 번호에서 걸려 오는 한 통을 기다린다(받거나 거절은 훅이 한다). 잡은 통화 또는 None."""
        self.caught, self.reject_seen, self.restricted = None, False, False
        self.seen.clear()
        if not self.budget.take_inbound(peek=True):
            self.seen["over"] += 1
            return None
        self.spec = ("ko", self.prompt("ko", tool=False))
        self.gate = mode
        deadline = self.clock() + seconds
        try:
            while self.gate is not None and self.clock() < deadline:
                await self.sleep(TICK_S)
        finally:
            self.gate = None
        return self.calls.get(self.caught) if self.caught else None

    def nothing_caught(self, n: int, seconds: int) -> None:
        if self.seen["over"]:
            self.put(n, "inbound_limit", INBOUND_LIMIT)
        elif self.seen["unreadable"]:
            self.put(n, "caller_unreadable", "건 번호를 읽을 수 없는 전화만 와서 받지 않았습니다.")
        elif self.seen["stranger"]:
            self.put(n, "not_allowed_caller",
                     f"허용 번호가 아닌 번호에서만 걸려 와 받지 않았습니다({self.seen['stranger']}통).")
        else:
            self.put(n, "no_inbound", f"{seconds}초 동안 걸려 온 전화가 없었습니다.")

    async def take(self, want: set[int], seconds: int) -> None:
        call = await self.window("accept", seconds)
        if call is not None:
            until = self.clock() + INBOUND_START_S
            while call.started is None and not call.ended and self.clock() < until:
                await self.sleep(TICK_S)
            if call.started is None:
                self.dead = True  # 받았는데 시작되지 않았다 — 끊을 손잡이가 없으니 연결을 닫는다
            else:
                await self.watch(call, call.started + INBOUND_HOLD_S, lambda: call.first)
        if 12 in want and call is None:
            self.nothing_caught(12, seconds)
        elif 12 in want and call.started is None:
            self.put(12, "accepted_not_started", "전화를 받았지만 통화가 시작되지 않았습니다.")
        elif 12 in want and not call.ended:
            self.put(12, "cut_unconfirmed", CUT_UNCONFIRMED)
        elif 12 in want:
            ms = self.response_ms(call)
            self.put(12, "ok", "걸려 온 전화 1통을 받았습니다 · " + (f"첫 응답 {ms}ms" if ms is not None else NO_RESPONSE_TIME),
                     ok=True, data={"first_response_ms": ms})
        if 13 in want and self.seen["match"]:
            self.put(13, "ok", "건 번호를 읽을 수 있습니다(번호는 남기지 않습니다).", ok=True,
                     data={"readable": True, "restricted": self.restricted})
        elif 13 in want and self.seen["unreadable"]:
            self.put(13, "caller_unreadable", "걸려 온 전화의 건 번호를 읽지 못했습니다.",
                     data={"readable": False, "restricted": self.restricted})
        elif 13 in want and self.seen["stranger"]:
            self.put(13, "ok", "건 번호를 읽을 수 있습니다(허용 번호가 아니어서 받지는 않았습니다).", ok=True,
                     data={"readable": True, "restricted": False})
        elif 13 in want:
            self.skip(13, "skipped_no_inbound", "걸려 온 전화가 없어 확인하지 못했습니다.")

    async def refuse(self, seconds: int) -> None:
        call = await self.window("reject", seconds)
        if call is None:
            return self.nothing_caught(14, seconds)
        until = self.clock() + REJECT_GRACE_S
        while call.started is None and self.clock() < until:
            await self.sleep(TICK_S)
        if call.started is not None:
            await self.hang_up(call)
            return self.put(14, "reject_not_applied", "거절했는데도 통화가 시작돼 끊었습니다.")
        if not self.reject_seen:
            return self.put(14, "reject_not_applied", "거절을 불렀지만 SDK 가 거절로 표시하지 않았습니다.")
        # P0 확인: 건 쪽 휴대전화에서 벨이 곧바로 끊기는지(SDK 문서: SIP 403, 과금 없음).
        return self.put(14, "ok", "받지 않고 거절했습니다.", ok=True, notes=["방법: IncomingCall.reject(reason='rejected')"],
                        data={"method": "IncomingCall.reject", "reason": "rejected"})

    async def inbound(self, want: set[int], wait: object) -> None:
        steps = sorted(want & {12, 13, 14})
        if not steps or True in [self.blocked(n) for n in steps]:
            return
        if type(wait) is not int or wait < 1:
            for n in steps:
                self.put(n, "bad_wait", BAD_WAIT)
            return
        seconds = min(wait, MAX_WAIT_INBOUND_S)
        if want & {12, 13}:
            await self.take(want, seconds)
        if 14 in want and not self.blocked(14):
            await self.refuse(seconds)

    async def go(self, want: set[int], sdk: object | None, lang2: object, wait: object, worker_connected: object) -> None:
        fail: _Fail | None = None
        try:
            if want & LINKED:
                await self.link(sdk, worker_connected)
            else:
                self.sdk = sdk if sdk is not None else load_sdk()
        except _Fail as e:
            fail = e
        except Exception as e:  # noqa: BLE001
            fail = _Fail("unknown", CRASHED, f"예외: {type(e).__name__}")
        told = 5 in want
        if 9 in want:
            self.voices()
        if told:
            self.report_link(fail)
        if 11 in want:
            self.report_bind(fail, told=told)
        if fail is not None:
            for n in sorted(want - {5, 9, 11}):
                self.not_linked(n, fail, told=told or (self.refused_number and 11 in want))
            return
        await self.outbound(want, lang2)
        await self.inbound(want, wait)

    async def close(self) -> None:
        """살아 있는 통화를 끊고 연결을 닫는다. 끝나거나 취소되면 꼭 거친다."""
        self.gate, self.dead = None, True
        for call in [*self.calls.values(), *([self.live] if self.live is not None else [])]:
            if call.session is not None and not call.ended and not call.hung:
                await self.hang_up(call)
        self.budget.maybe_live = any(not c.ended for c in self.dials)
        if self.agent is not None:
            try:
                await self.bounded(self.agent.disconnect(), HANGUP_TIMEOUT_S)
            except Exception:  # noqa: BLE001, S110
                pass


async def run_voice_checks(conn: DiagnosticConn, voice: VoiceDiag, *, agent_number: str | None = None,
                           steps: tuple[int, ...] = (5, 9, 11), call_to: str | None = None, lang2: str = "en",
                           wait_inbound_s: int = 90, worker_connected: bool = False, sdk: object | None = None,
                           sleep: Sleep = asyncio.sleep, clock: Clock = time.monotonic,
                           budget: VoiceBudget | None = None, resolve: object = None) -> list[DiagnosticStep]:
    """부르는 쪽이 쓰는 단 하나의 입구. 언제나 P5~P14 열 줄을 돌려준다 — 고르지 않은 걸음은 `skipped_not_requested`.

    `conn` 에서는 주소·키·Account ID 만 읽는다. `agent_number` 는 에이전트에 묶을 번호(플랫폼에서 받은 070 번호), `call_to` 는 걸어 볼
    단 하나의 번호(설정 API 가 첫 허용 번호를 넘긴다), `worker_connected` 는 음성 일꾼이 그 번호로 붙어 있는지. 기본 걸음(5·9·11)은
    걸지도 받지도 않는다. P6·P7·P8 이 한 통화, P10 이 한 통화, P12·P13 이 받는 한 통화, P14 가 거절하는 한 통화이고 P12 와 P14 는
    저마다 `wait_inbound_s`(최대 180초)까지 기다린다. `sdk`·`sleep`·`clock`·`resolve` 는 시험이 끼우는 자리, `budget` 은 이어서 센다.
    """
    picked = _picked(steps)
    if picked is None:
        return [VoiceStep(id=f"P{n}", label=LABELS[f"P{n}"], ok=False, detail=BAD_STEPS, code="bad_steps") for n in STEPS]
    budget = budget if isinstance(budget, VoiceBudget) else VoiceBudget()
    run = _Run(conn, voice, agent_number, call_to, sleep, clock, budget, resolve)
    crash = ""
    if picked:
        redact.add_secrets(*run.secrets)  # SDK 를 건드리기 전에 로그 거르개에 올린다
        with _quiet_sdk(run.clean, SDK_LOGGERS, READY_ENV, watch=run.saw):
            try:
                try:
                    await run.go(set(picked), sdk, lang2, wait_inbound_s, worker_connected)
                finally:
                    await asyncio.shield(run.close())
            except Exception as e:  # noqa: BLE001 — 진단은 던지지 않는다(취소는 BaseException 이라 그대로 올라간다)
                crash = type(e).__name__
    for n in STEPS:
        if n not in picked:
            run.skip(n, "skipped_not_requested", NOT_REQUESTED)
        elif n not in run.out:
            run.put(n, "unknown", CRASHED, notes=[f"예외: {crash or '-'}"])
    return [run.out[n] for n in STEPS]
