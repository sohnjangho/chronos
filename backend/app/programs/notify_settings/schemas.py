"""알림 연결 API 의 요청·응답 꼴. 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

요청 본문은 모르는 칸을 받지 않는다(PATCH 가 상한을 받지 않게). 참/거짓·순번은 엄격하게(「"true"」·「"1"」 거절).
키는 SecretStr — repr·검증 오류에 드러나지 않는다. 번호는 응답에 가린 꼴로만 나간다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
)

from app.store.timeutil import as_utc

Agent = Literal["approve", "delegate"]
InboundMode = Literal["off", "known", "all"]
StepId = Literal["P1", "P2", "P3", "P4"]
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Text100 = Annotated[str, Field(max_length=100)]
Text500 = Annotated[str, Field(max_length=500)]
NumberText = Annotated[str, Field(max_length=40)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionTestIn(_In):
    base_url: Text500 | None = None
    secret: SecretStr
    account_id: Text100


class ConnectionCreate(ConnectionTestIn):
    name: Name


class ConnectionUpdate(_In):
    """보낸 칸만 바꾼다(kakao_channel·handoff_number 는 null 도 「보냄」 — model_fields_set 으로 가른다)."""

    name: Name | None = None
    base_url: Text500 | None = None
    secret: SecretStr | None = None
    account_id: Text100 | None = None
    sender_index: StrictInt | None = None
    kakao_channel: Text100 | None = None
    test_mode: StrictBool | None = None
    allow_numbers_add: Annotated[list[NumberText], Field(max_length=50)] | None = None
    allow_numbers_remove: Annotated[list[StrictInt], Field(max_length=50)] | None = None
    allow_numbers_version: Text100 | None = None
    agent_sms: Agent | None = None
    agent_kakao: Agent | None = None
    agent_call: Agent | None = None
    inbound_mode: InboundMode | None = None
    handoff_number: NumberText | None = None
    is_default: Literal[True] | None = None


class ErrorOut(BaseModel):
    code: str
    message: str


class ProbeOut(BaseModel):
    ok: bool
    latency_ms: int | None
    senders: list[str]  # 가린 꼴
    error: ErrorOut | None


class AllowNumberOut(BaseModel):
    index: int
    number_masked: str
    kind: str
    can_test_sms: bool


class UsedToday(BaseModel):
    sms: int
    call: int


class ConnectionOut(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    secret_last4: str
    account_id_masked: str
    sender_number_masked: str | None
    sender_index: int | None
    senders: list[str]
    kakao_channel: str | None
    test_mode: bool
    allow_numbers: list[AllowNumberOut]
    allow_numbers_version: str
    test_sms_index: int | None
    limits: dict[str, int]
    agent_sms: str
    agent_kakao: str
    agent_call: str
    inbound_mode: str
    handoff_number_masked: str | None
    is_default: bool
    status: str
    checked_at: UtcDatetime | None
    latency_ms: int | None
    used_today: UsedToday


class ConnectionSaved(ConnectionOut):
    error: ErrorOut | None = None


class LimitsOut(BaseModel):
    values: dict[str, int]
    defaults: dict[str, int]
    ranges: dict[str, list[int]]


class DiagnoseIn(_In):
    steps: Annotated[list[StepId], Field(min_length=1, max_length=4)] | None = None
    send: StrictBool = False


class StepOut(BaseModel):
    id: str
    label: str
    ok: bool
    skipped: bool
    detail: str
    latency_ms: int | None
    notes: list[str]


class DiagnosisOut(BaseModel):
    ran_at: UtcDatetime
    steps: list[StepOut]
    sent_real: bool
    sent_unknown: bool


class AgentOut(BaseModel):
    sms: str
    kakao: str
    call: str


class StatusOut(BaseModel):
    ready: bool
    test_mode: bool
    allow_count: int
    agent: AgentOut
    inbound_mode: str
    kakao_ready: bool


class BlockIn(_In):
    number: NumberText | None = None
    peer_key: Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")] | None = None
    reason: Annotated[str, Field(max_length=200)] = ""


class BlockedOut(BaseModel):
    id: int
    number_masked: str
    reason: str
    created_by: str
    created_at: UtcDatetime
