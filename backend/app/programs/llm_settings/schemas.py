from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

from app.llm.connections import normalize_base_url
from app.store.timeutil import as_utc

Provider = Literal["liner", "openai_compatible"]
Purpose = Literal["light", "normal", "hard", "longdoc"]
RoutingStrategy = Literal["cost", "balanced", "quality"]

BaseUrl = Annotated[str, AfterValidator(normalize_base_url)]
# SQLite 는 시간대를 지운다. 시간대 없는 값은 UTC 로 보고 붙여 내보낸다(+00:00 / Z).
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
# SecretStr: repr·검증 오류에 키가 드러나지 않는다. 문자 검증은 service 가 한다(invalid_secret).
Secret = SecretStr
Name = Annotated[str, Field(min_length=1, max_length=100)]


class ConnectionTestIn(BaseModel):
    provider: Provider
    base_url: BaseUrl | None = None
    secret: Secret


class ConnectionCreate(ConnectionTestIn):
    name: Name


class ConnectionUpdate(BaseModel):
    name: Name | None = None
    base_url: BaseUrl | None = None
    secret: Secret | None = None
    is_default: Literal[True] | None = None


class LlmErrorOut(BaseModel):
    code: str
    message: str


class ProbeOut(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str]
    error: LlmErrorOut | None


class ConnectionOut(BaseModel):
    """연결 한 줄. 키는 끝 4자리(secret_last4)만."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: Provider
    base_url: str
    secret_last4: str
    is_default: bool
    status: Literal["ok", "failed", "unknown"]
    model_count: int | None
    checked_at: UtcDatetime | None
    latency_ms: int | None


class ConnectionSaved(ConnectionOut):
    """저장 결과. 연결 시험이 실패했으면 error 에 설명이 있다."""

    error: LlmErrorOut | None = None


class ModelsOut(BaseModel):
    models: list[str]


class AssignmentIn(BaseModel):
    purpose: Purpose
    connection_id: int
    model: Annotated[str, Field(min_length=1, max_length=200)]
    routing_strategy: RoutingStrategy | None = None


class AssignmentOut(BaseModel):
    purpose: Purpose
    connection_id: int | None
    model: str
    routing_strategy: RoutingStrategy | None


class AssignmentsIn(BaseModel):
    items: list[AssignmentIn]


class AssignmentsOut(BaseModel):
    items: list[AssignmentOut]


class StatusOut(BaseModel):
    ready: bool
    default_connection: str | None
