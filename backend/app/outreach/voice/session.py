"""음성 통화 인터페이스(Task 87). 통화 일꾼(88·95)은 이것만 보고, 가짜 통화(simulated)와 SDK 어댑터(kat_sdk — 113)가 구현한다.
구현이 지키는 약속은 tests/outreach/voice/test_simulated.py 의 VoiceBackendContract 가 시험한다(어댑터도 그것을 물려받는다).

약속(SDK 가 그렇게 돌지 않는 것은 어댑터가 맞춘다 — ★ 는 SDK 의 기본 동작과 **반대**인 것):

1. **말은 「하게 한다」이고, 실제로 나간 말은 받아쓰기로 돌아온다.** SDK 에는 「이 문장을 그대로 말하라」가 없다(모델이 말한다).
   `CallSpec.first_line` 과 `CallControl.say(text)` 는 백엔드에게 그 말을 하게 하는 것이고, 모델이 실제로 한 말은
   `on_transcript("agent", …)` 로 온다. 기록·뒤 확인은 돌아온 말을 쓴다.
2. **첫 발화가 먼저다.** `on_start` 뒤의 첫 사건은 늘 `on_transcript("agent", 실제 첫 발화, t)` 이다 — 그보다 먼저 온 상대 말·도구
   호출은 백엔드가 첫 발화 뒤로 미룬다. `OPENING_WITHIN_S` 안에 첫 발화가 없으면 빈 글 `""` 을 첫 발화로 준다. 일꾼은 그 첫
   사건에서 `greeting.discloses(spec.language, text)` 로 AI 임·기록됨을 밝혔는지 보고, 아니면 그 자리에서 `say`/`hangup` 한다
   (PM 규칙: 통화는 늘 밝히는 말로 연다). 그때까지 상대 말·도구는 손잡이에 오지 않았다.
3. **받아쓰기는 온전한 한 발화다.** SDK 는 조각으로 준다 — 조각마다 가리면 번호가 조각 사이에 걸쳐 새므로 백엔드가 이어서 한
   발화로 준다. `t` 는 통화가 시작된 뒤 흐른 초.
4. **전환은 코드가 건다.** `transfer(number) -> bool` 은 「시작됐는가」다. 시작되면 AI 쪽 통화는 거기서 끝나고, 담당자가 받았는지는
   끝난 까닭(`END_TRANSFER` / `END_TRANSFER_FAILED`)으로 온다. 시작하지 못하면 False 이고 통화가 이어진다. **번호는 코드에서만
   온다**(id 를 받는 도구가 줄에서 읽어 붙인다) — 모델이 준 글을 번호로 쓰지 않는다. ★ SDK 의 내장 도구는 NONE 으로 둔다
   (기본값은 모델이 번호를 넣어 거는 `transfer_call` 을 켠다).
5. ★ **받기 전 판정은 닫힌 쪽으로 실패한다.** `listen` 의 `on_incoming` 이 예외를 내거나 `DECIDE_WITHIN_S` 안에 답하지 못하면
   그 전화를 **거절한다**(SDK 는 반대로 받는다 — 어댑터가 SDK 의 시한보다 먼저 스스로 거절해야 한다). None 도 거절.
6. **번호를 숨긴 전화는 번호가 없다.** 번호 표시 제한 깃발이 서 있으면 망이 번호를 넘겨줘도 `Incoming.caller_number` 는 None.
7. **도구 결과는 JSON 으로 바뀌는 dict** 다(아니면 TypeError — 통화를 잇지 않는다). 손잡이가 예외를 내면 통화를 끝내고 그 예외가
   `place`/`listen` 밖으로 나온다. 예외 글은 모델에게도 SDK 로그에도 가지 않는다 — 모델에게는 `TOOL_FAILED_REPLY` 만 간다.
8. **끝은 꼭 한 번.** 받은 통화는 `on_start` → … → `on_end(END_REASONS 하나, 초)`, 받지 않은 통화는 `on_failed(FAIL_CODES 하나,
   번호 없는 글)` 하나뿐(on_start·on_end 없음). 백엔드가 고장 나면 끝 손잡이 없이 `VoiceError`(일꾼이 `backend_error` 로 닫는다).
   끝난 뒤의 `CallControl` 은 아무 일도 하지 않는다(예외도 없다). 연결이 끊기거나 다른 접속에 밀려나면 `END_LOST` 다 — 백엔드는
   스스로 다시 붙지 않는다(다시 붙기는 일꾼이 횟수를 정해 한다).
9. **시간은 일꾼이 잰다.** 백엔드는 `on_tick(지난 초, 침묵 초)` 만 주고 최대 시간·침묵으로 끊지 않는다. 침묵은 어느 쪽이든 마지막
   말 뒤 흐른 시간이고, 같은 시각이면 시계 알림이 말보다 먼저다.
10. **번호는 글에 없다.** `first_line`·`instructions` 에 번호처럼 보이는 것이 있으면 CallSpec 을 만들 수 없다. `to_number`·
    `from_number` 는 백엔드만 읽고, repr 에도 오류 글에도 나오지 않는다.

동시 통화 한도는 여기 두지 않는다 — `app.outreach.harness.door.MAX_LIVE_CALLS` 하나를 일꾼이 쓴다.
"""

import json
import os
import re
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, get_args

from app.outreach import redact
from app.outreach.harness.registry import SANDBOX_ENV
from app.outreach.harness.types import NotReady, ToolDef

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

Direction = Literal["out", "in"]
Role = Literal["agent", "peer"]
FailCode = Literal["no_answer", "busy", "failed"]
Gender = Literal["male", "female", "unknown"]

FAIL_CODES: tuple[str, ...] = get_args(FailCode)  # on_failed 의 code — harness.types.CALL_RESULTS 의 낱말
END_PEER = "peer"  # 상대가 끊음
END_AGENT = "agent"  # 우리 쪽이 끊음(모델의 end_call·코드의 hangup·사람이 화면에서)
END_TRANSFER = "transfer"  # 담당자에게 넘겼고 담당자가 받음
END_TRANSFER_FAILED = "transfer_failed"  # 넘기기 시작했는데 담당자가 받지 않음
END_LOST = "lost"  # 연결이 끊김·다른 접속에 밀려남
END_REASONS: tuple[str, ...] = (END_PEER, END_AGENT, END_TRANSFER, END_TRANSFER_FAILED, END_LOST)
DECIDE_WITHIN_S = 3  # 받기 전 판정 시한(초). SDK 의 시한(5초)보다 짧아야 우리가 먼저 거절한다
OPENING_WITHIN_S = 5  # 받은 뒤 이 안에 첫 발화가 없으면 빈 첫 발화를 준다(약속 2)
TOOL_FAILED_REPLY = '{"ok": false, "error": "unavailable"}'  # 손잡이가 실패했을 때 모델이 받는 단 하나의 글(약속 7)

_NOT_DIGIT = re.compile(r"[^0-9０-９]")
_FULL_WIDTH = str.maketrans({chr(0xFF10 + i): str(i) for i in range(10)})
# 대표번호(15xx·16xx·18xx-xxxx): redact 는 자유 글에서 시각 범위와 모양이 같아 남기지만, 모델에게 줄 글에서는 막는다.
_SHORT_CODE = re.compile(r"(?<![0-9-])1[568][0-9]{2}\s?[-‐‑‒–—−.]\s?[0-9]{4}(?![0-9-])")
_OWN_MIN = 7  # 이보다 짧은 번호는 글 속 숫자와 우연히 겹칠 수 있어 견주지 않는다


class VoiceError(Exception):
    """음성 백엔드가 일을 하지 못했다(연결·SDK·모델 고장). 글에 번호가 없다."""


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digits(text: str) -> str:
    return _NOT_DIGIT.sub("", text).translate(_FULL_WIDTH)


def has_phone(text: str, *numbers: str | None) -> bool:
    """글에 번호처럼 보이는 것이 있는가 — redact 가 가릴 꼴, 대표번호, 그리고 numbers(이 통화의 번호)가 어떤 띄어쓰기로든."""
    if redact.hide_phones(text) != text or _SHORT_CODE.search(text.translate(_FULL_WIDTH)):
        return True
    digits = _digits(text)
    for number in numbers:
        own = _digits(number or "")
        if len(own) >= _OWN_MIN and (own in digits or (own.startswith("0") and own[1:] in digits)):
            return True
    return False


@dataclass(frozen=True)
class CallSpec:
    """통화 한 통의 명세. 일꾼이 만들고 백엔드가 읽는다. 값은 만들 때 검사한다(오류 글에 받은 값을 싣지 않는다).

    to_number — 걸 번호(받는 통화는 None). from_number — 우리 번호. 둘은 백엔드만 읽는다.
    first_line — 백엔드가 맨 먼저 하게 할 말(greeting 이 지은 것). instructions — 음성 모델의 지시문. 둘에는 번호가 없다.
    tools — 하네스 도구 정의(harness.types.ToolDef 그대로, 이름이 겹치지 않게). max_seconds — 일꾼이 지킬 최대 통화 시간.
    record_to — 녹음을 둘 폴더(없으면 녹음하지 않음). vocabulary — 받아쓰기 낱말(현장·작업 이름 — site_name.vocabulary). 번호처럼 보이는 낱말은 빼고 둔다(통화는 막지 않는다).
    """

    direction: Direction
    to_number: str | None
    from_number: str
    language: str
    voice_id: str | None
    first_line: str
    instructions: str
    tools: tuple[ToolDef, ...]
    max_seconds: int
    record_to: Path | None
    vocabulary: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check(self.direction in get_args(Direction), "CallSpec.direction 은 out·in 가운데 하나입니다")
        if self.direction == "out":
            _check(_text(self.to_number), "거는 통화에는 걸 번호(to_number)가 있어야 합니다")
        else:
            _check(self.to_number is None, "받는 통화에는 걸 번호(to_number)가 없습니다")
        _check(_text(self.from_number), "CallSpec.from_number 가 비었습니다")
        _check(_text(self.language), "CallSpec.language 가 비었습니다")
        _check(self.voice_id is None or _text(self.voice_id), "CallSpec.voice_id 는 음성 id 나 None 입니다")
        _check(_text(self.first_line), "CallSpec.first_line 이 비었습니다")
        _check(_text(self.instructions), "CallSpec.instructions 가 비었습니다")
        _check(type(self.max_seconds) is int and self.max_seconds > 0, "CallSpec.max_seconds 는 0보다 큰 정수(초)입니다")
        _check(self.record_to is None or isinstance(self.record_to, Path), "CallSpec.record_to 는 Path 나 None 입니다")
        _check(isinstance(self.tools, list | tuple), "CallSpec.tools 는 ToolDef 의 묶음입니다")
        tools = tuple(self.tools)
        _check(all(isinstance(tool, ToolDef) for tool in tools), "CallSpec.tools 는 ToolDef 만 받습니다")
        _check(len({tool.name for tool in tools}) == len(tools), "CallSpec.tools 에 같은 이름의 도구가 두 번 있습니다")
        _check(isinstance(self.vocabulary, list | tuple) and all(isinstance(word, str) for word in self.vocabulary),
               "CallSpec.vocabulary 는 글의 묶음입니다")
        for text in (self.first_line, self.instructions):
            _check(not has_phone(text, self.to_number, self.from_number),
                   "음성 모델에게 줄 글에 전화번호처럼 보이는 것이 있습니다")
        object.__setattr__(self, "tools", tools)
        # 받아쓰기 낱말은 덤이라 통화를 막지 않는다: 번호처럼 보이는 낱말(이 통화의 번호 포함)은 빼기만 한다
        kept = tuple(word for word in self.vocabulary if not has_phone(word, self.to_number, self.from_number))
        object.__setattr__(self, "vocabulary", kept)

    def __repr__(self) -> str:
        return (f"CallSpec(direction={self.direction!r}, language={self.language!r}, voice_id={self.voice_id!r}, "
                f"tools={[tool.name for tool in self.tools]}, max_seconds={self.max_seconds}, "
                f"record={self.record_to is not None})")


@dataclass(frozen=True)
class Incoming:
    """걸려 온 전화(받기 전). caller_number 는 건 번호 — 번호를 숨겼으면 None(빈 글이 아니다). at 은 시간대가 있는 시각."""

    caller_number: str | None
    to_number: str
    at: datetime

    def __post_init__(self) -> None:
        _check(self.caller_number is None or _text(self.caller_number), "숨긴 번호는 None 으로 둡니다")
        _check(_text(self.to_number), "Incoming.to_number 가 비었습니다")
        _check(isinstance(self.at, datetime) and self.at.tzinfo is not None, "Incoming.at 은 시간대가 있는 시각입니다")

    def __repr__(self) -> str:
        return f"Incoming(caller={'withheld' if self.caller_number is None else 'shown'}, at={self.at.isoformat()})"


@dataclass(frozen=True)
class VoiceInfo:
    """고를 수 있는 음성 하나."""

    id: str
    name: str
    gender: Gender

    def __post_init__(self) -> None:
        _check(_text(self.id) and _text(self.name), "VoiceInfo 의 id·name 이 비었습니다")
        _check(self.gender in get_args(Gender), "VoiceInfo.gender 는 male·female·unknown 가운데 하나입니다")


class CallControl(Protocol):
    """통화 중에 코드가 하는 일. 끝난 통화에서는 아무 일도 하지 않는다(예외 없음, transfer 는 False)."""

    async def say(self, text: str) -> None:
        """백엔드가 그 말을 하게 한다. 실제로 나간 말은 on_transcript("agent", …) 로 온다."""

    async def hangup(self) -> None:
        """통화를 끊는다 — on_end(END_AGENT, …) 가 한 번 온다. 손잡이 밖에서(사람이 화면에서) 불러도 된다."""

    async def transfer(self, number: str) -> bool:
        """그 번호로 넘기기 시작한다. 시작됐으면 True(AI 쪽 통화는 끝나고 결과는 끝난 까닭으로), 못 했으면 False(통화가 이어짐).
        number 는 코드가 줄에서 읽은 번호만 — 모델이 준 글을 넣지 않는다."""


class CallHandlers(Protocol):
    """통화가 부르는 손잡이. 한 통화의 손잡이는 차례대로 하나씩 불린다. 예외를 내면 통화가 끝나고 그 예외가 밖으로 나온다."""

    async def on_start(self, control: CallControl) -> None:
        """상대가 받았다(받는 통화는 우리가 받았다). 이 뒤의 첫 사건은 실제 첫 발화다."""

    async def on_transcript(self, role: Role, text: str, t: float) -> None:
        """온전한 한 발화. agent 는 실제로 나간 말(모델의 말·say 로 시킨 말), peer 는 상대 말. t 는 통화가 시작된 뒤의 초."""

    async def on_tool(self, name: str, args: dict) -> dict:
        """모델이 도구를 불렀다. 돌려준 dict(JSON 으로 바뀌어야 한다)가 모델에게 간다."""

    async def on_tick(self, elapsed: float, silent_for: float) -> None:
        """시계 알림: 통화가 시작된 뒤의 초, 마지막 말(어느 쪽이든) 뒤의 초."""

    async def on_end(self, reason: str, seconds: int) -> None:
        """받았던 통화가 끝났다. reason 은 END_REASONS 하나."""

    async def on_failed(self, code: FailCode, detail: str) -> None:
        """받지 않은 통화. code 는 FAIL_CODES 하나, detail 은 번호 없는 짧은 글."""


class VoiceBackend(Protocol):
    """음성 백엔드. 모듈 머리 글의 약속을 지킨다."""

    async def check(self) -> tuple[bool, str]:
        """쓸 수 있는가와 그 까닭(한국어, 번호·키 없음)."""

    async def place(self, spec: CallSpec, handlers: CallHandlers) -> None:
        """건다. 통화가 끝날 때까지 돌아오지 않는다. 받는 통화의 명세를 주면 ValueError(걸지 않는다)."""

    async def listen(
        self, number: str, on_incoming: Callable[[Incoming], Awaitable[tuple[CallSpec, CallHandlers] | None]]
    ) -> None:
        """그 번호로 오는 전화를 기다린다(취소될 때까지). 전화마다 on_incoming 을 불러 None·예외·시한 넘김이면 받지 않고
        거절하고, (명세, 손잡이)면 받아서 통화를 돌린다. 거는 통화의 명세를 돌려주면 거절하고 ValueError."""

    async def voices(self, language: str) -> list[VoiceInfo]:
        """그 언어로 고를 수 있는 음성."""

    async def sample(self, voice_id: str, language: str, text: str) -> bytes:
        """그 음성으로 그 글을 읽은 소리."""


def tool_reply(result: object) -> str:
    """도구 결과를 모델에게 줄 글(JSON)로. dict 가 아니거나 JSON 으로 바꿀 수 없으면 TypeError(받은 값은 싣지 않는다)."""
    if not isinstance(result, dict):
        raise TypeError("도구 결과는 dict 여야 합니다")
    try:
        return json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise TypeError("도구 결과를 JSON 으로 바꿀 수 없습니다") from None


_PINNED: list[VoiceBackend] = []


def backend_for(session: "Session | None") -> VoiceBackend:
    """쓸 음성 백엔드 — 시험·모래상자가 끼운 것(pinned)이 있으면 그것. 통화 일꾼·API 가 백엔드를 얻는 한 곳이다.
    아니면 기본 알림 연결의 voice_settings 를 읽어 공급자가 google·openai 이고 SDK 가 깔렸고 설정이 다 갖춰졌으면 SDK 어댑터
    (kat_sdk.KatVoice — Task 113), 그 밖(세션 없음·설정 없음·dashboard 방식·덜 된 설정)은 NotReady(아무것도 걸지 않는다).
    어댑터는 여기서만 불러온다(그 모듈도 SDK 는 함수 안에서만 불러온다)."""
    if _PINNED:
        return _PINNED[-1]
    if session is None:
        raise NotReady("음성 통화 백엔드가 아직 준비되지 않았습니다")
    from app.outreach.voice import kat_sdk

    return kat_sdk.for_session(session)


def _may_pin() -> bool:
    return "pytest" in sys.modules or os.environ.get(SANDBOX_ENV) == "1"


@contextmanager
def pinned(backend: VoiceBackend) -> Iterator[None]:
    """이 블록 동안 backend_for 가 backend 를 돌려준다(겹치면 나중 것). 나갈 때 이 층만 걷는다.
    프로세스 전체에 걸리므로 통로 등록부와 같은 규칙이다: 시험(pytest)이나 모래상자 프로세스(CHRONOS_HARNESS_SANDBOX=1)가
    아니면 RuntimeError — 서버에서 가짜 통화를 끼우면 진짜 예약 통화가 가짜로 가서 「통화됨」으로 적힌다."""
    if not _may_pin():
        raise RuntimeError(f"음성 백엔드 끼우기는 시험이나 모래상자 프로세스({SANDBOX_ENV}=1)에서만 씁니다")
    _PINNED.append(backend)
    try:
        yield
    finally:
        for index in range(len(_PINNED) - 1, -1, -1):
            if _PINNED[index] is backend:
                del _PINNED[index]
                break
