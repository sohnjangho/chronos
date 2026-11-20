from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

from app.llm.connections import normalize_base_url
from app.store.timeutil import as_utc

Provider = Literal["liner", "openai_compatible"]
Purpose = Literal["light", "normal", "hard", "longdoc", "vision", "embedding"]
# 모델 목록 거르기: chat(대화)·vision(그림 읽기 — 대화용과 같은 목록)·embedding(/v1/embeddings 지원)
ModelsFor = Literal["chat", "vision", "embedding"]
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


class ModelPrice(BaseModel):
    """공개 가격(USD / 100만 토큰) 한 모델."""

    kind: Literal["model"]
    as_of: str
    input: float
    output: float
    cached_input: float


class RangePrice(BaseModel):
    """라우터: 고르는 모델들의 가장 싼 값 ~ 가장 비싼 값."""

    kind: Literal["range"]
    as_of: str
    input_min: float
    input_max: float
    output_min: float
    output_max: float


PriceOut = ModelPrice | RangePrice


class ModelOut(BaseModel):
    """모델 한 개: 업체(vendor = owned_by), 업체 이름, 문맥 길이, 대화용 여부, 참고 가격(없으면 null)."""

    id: str
    name: str
    vendor: str
    vendor_name: str
    context_length: int | None
    chat: bool
    price: PriceOut | None = None


class ProbeOut(BaseModel):
    ok: bool
    latency_ms: int
    models: list[ModelOut]
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
    # 대화용 모델 수. 표에 열이 없어 저장된 목록에서 센다(router 가 채운다).
    chat_model_count: int | None = None
    checked_at: UtcDatetime | None
    latency_ms: int | None


class ConnectionSaved(ConnectionOut):
    """저장 결과. 연결 시험이 실패했으면 error 에 설명이 있다."""

    error: LlmErrorOut | None = None


class ModelsOut(BaseModel):
    models: list[ModelOut]


class ConnectionModels(BaseModel):
    """한 연결의 모델 목록(거른 것). 주소·키는 담지 않는다."""

    connection_id: int
    name: str
    is_default: bool
    models: list[ModelOut]


class ModelsForOut(BaseModel):
    connections: list[ConnectionModels]


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


class ReindexOut(BaseModel):
    """임베딩 모델을 바꿔 시작한 다시 넣기 작업(reindex_jobs). 진행은 GET /api/files/reindex."""

    job_id: int
    total: int


class AssignmentsOut(BaseModel):
    items: list[AssignmentOut]
    reindex: ReindexOut | None = None  # PUT 이 임베딩 모델을 바꿨을 때만


class StatusOut(BaseModel):
    ready: bool
    default_connection: str | None
