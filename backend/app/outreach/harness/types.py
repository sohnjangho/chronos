"""연락 하네스의 낱말(Task 64 — 여기서만 정의한다). 나가는 문·들어오는 문·도구 묶음·사건 기록·통로·글과 음성 세션이
모두 이것을 쓰고, 서로를 import 하지 않아도 같은 말을 한다. 표준 라이브러리만 쓴다(DB·제공사·LLM 없음).

전화번호는 어느 낱말에도 칸이 없다 — 번호는 줄(연락처·peer_number)에만 있고 코드가 붙인다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Medium = Literal["sms", "call"]  # 하네스가 보는 매체(카카오톡은 보내기만 하는 통로라 매체가 아니다)
CallerClass = Literal[
    "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked", "outside_test",
    "outbound",  # 우리가 먼저 건 통화의 상대
]


class NotReady(Exception):
    """쓸 것이 아직 없다(등록되지 않은 통로 등). 아무것도 보내지 않았다. 판정 코드 not_ready 에 맞는다."""


@dataclass(frozen=True)
class Actor:
    """보내기·걸기를 부른 쪽. system 은 일꾼(예약된 줄을 보낼 때)."""

    kind: Literal["user", "agent", "system"]
    user_id: int | None
    name: str
    role: str | None


@dataclass(frozen=True)
class Outcome:
    """문의 판정. code 는 이름표의 판정 코드, message 는 한국어, rule 은 걸린 차례(지나갔으면 None)."""

    code: str
    message: str
    rule: int | None = None
    scheduled_at: datetime | None = None


@dataclass(frozen=True)
class Candidate:
    """번호로 찾은 연락처 하나(그 일정·협력사와 함께)."""

    schedule_id: int
    contact_id: int
    company_id: int


@dataclass(frozen=True)
class Caller:
    """번호로 코드가 정한 상대. 등급은 말·글로 한 주장으로 바뀌지 않는다."""

    caller_class: CallerClass
    candidates: tuple[Candidate, ...]
    user_id: int | None  # internal 일 때 그 계정


@dataclass(frozen=True)
class Scope:
    """그 상대에게 도구가 보일 수 있는 범위. 도구는 불릴 때마다 이것만 보고, 모델이 준 인자로 넓히지 않는다.
    personal 은 「본인에게 온 요청」을 말해도 되는가, facts 는 일정 사실을 어디까지(all 전부 · trade 그 협력사·공종 · none 없음)."""

    caller_class: CallerClass
    schedule_ids: tuple[int, ...]
    contact_ids: tuple[int, ...]
    company_ids: tuple[int, ...]
    personal: bool
    facts: Literal["all", "trade", "none"]


@dataclass(frozen=True)
class Ref:
    """사건·답·보고가 붙는 줄(outreach_messages 또는 outreach_calls 의 id)."""

    kind: Literal["message", "call"]
    row_id: int


@dataclass(frozen=True)
class Delivered:
    """통로가 돌려준 결과. fail_text 는 한국어이고 번호·키가 없다."""

    ok: bool
    provider_id: str | None = None
    fail_code: str | None = None
    fail_text: str | None = None


@dataclass(frozen=True)
class ToolDef:
    """도구 하나의 정의. parameters 는 JSON Schema — 음성 세션과 글 세션이 같은 것을 받는다."""

    name: str
    description: str
    parameters: dict


class Channel(Protocol):
    """통로: 문자·카카오톡·통화가 하나씩 구현하고 registry 에 스스로 등록한다. 판정은 하지 않는다(문이 이미 했다).
    deliver 를 부르는 곳은 나가는 문 하나뿐이다."""

    name: str

    async def deliver(self, row_id: int) -> Delivered: ...
