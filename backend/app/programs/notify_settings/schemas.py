"""알림 연결 API 의 요청·응답 꼴. 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

요청 본문은 모르는 칸을 받지 않는다(PATCH 가 상한을 받지 않게). 참/거짓·순번은 엄격하게(「"true"」·「"1"」 거절).
키·Account ID 는 SecretStr — repr·검증 오류에 드러나지 않는다. 번호는 응답에 가린 꼴로만 나간다.
글 길이·빈 이름은 여기서 막지 않고 service.check_lengths 가 칸을 알려 주는 422 로 막는다(계약 V5).
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


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionTestIn(_In):
    base_url: str | None = None
    secret: SecretStr
    account_id: SecretStr


class ConnectionCreate(ConnectionTestIn):
    name: str


class ConnectionUpdate(_In):
    """보낸 칸만 바꾼다(kakao_channel·handoff_number 는 null 도 「보냄」 — model_fields_set 으로 가른다)."""

    name: str | None = None
    base_url: str | None = None
    secret: SecretStr | None = None
    account_id: SecretStr | None = None
    sender_index: StrictInt | None = None
    kakao_channel: str | None = None
    test_mode: StrictBool | None = None
    allow_numbers_add: list[str] | None = None
    allow_numbers_remove: list[StrictInt] | None = None
    allow_numbers_version: str | None = None
    agent_sms: Agent | None = None
    agent_kakao: Agent | None = None
    agent_call: Agent | None = None
    inbound_mode: InboundMode | None = None
    handoff_number: str | None = None
    is_default: Literal[True] | None = None


class ErrorOut(BaseModel):
    code: str
    message: str


class SenderOut(BaseModel):
    index: int
    number_masked: str
    kind: str
    label: str  # 「발신번호 {index+1}」 — 끝 4자리가 같은 두 번호도 가른다


class ProbeOut(BaseModel):
    ok: bool
    latency_ms: int | None
    senders: list[SenderOut]
    error: ErrorOut | None


class AllowNumberOut(BaseModel):
    index: int
    number_masked: str
    kind: str  # 알 수 없으면 ""
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
    senders: list[SenderOut]
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
    used_today: UsedToday | None  # 기본 연결이 아니면 null
    check_summary: str  # 연결 테스트 결과 한 줄(저장된 확인 결과·오늘 사용량만으로 — service.check_summary)


class ConnectionSaved(ConnectionOut):
    error: ErrorOut | None = None


class LimitsOut(BaseModel):
    values: dict[str, int]
    defaults: dict[str, int]
    ranges: dict[str, list[int]]


class DiagnoseIn(_In):
    steps: Annotated[list[StepId], Field(min_length=1, max_length=4)] | None = None
    send: StrictBool = False
    allow_numbers_version: str | None = None  # send 가 참이면 꼭 — 확인한 목록 그대로일 때만 보낸다
    confirm_resend: StrictBool = False  # 앞선 시험 문자의 결과를 모를 때 그래도 다시 보낸다


class StepOut(BaseModel):
    id: str
    label: str
    ok: bool
    skipped: bool
    detail: str
    latency_ms: int | None
    notes: list[str]
    code: str = ""  # 이 칸이 생기기 전에 저장된 진단은 빈 값
    maybe_sent: bool = False
    pending: bool = False


class SendRecord(BaseModel):
    at: UtcDatetime
    by: str
    outcome: Literal["sending", "accepted", "unknown", "not_sent"]


class DiagnosisOut(BaseModel):
    state: Literal["sending", "done"]
    ran_at: UtcDatetime
    by: str | None
    steps: list[StepOut]
    sent_real: bool
    sent_unknown: bool
    sends: list[SendRecord]


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
    number: str | None = None
    peer_key: Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")] | None = None
    reason: str = ""


class BlockedOut(BaseModel):
    id: int
    number_masked: str
    reason: str
    created_by: str
    created_at: UtcDatetime
