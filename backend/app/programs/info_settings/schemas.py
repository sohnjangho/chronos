from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

from app.llm.connections import normalize_base_url
from app.store.timeutil import as_utc

Preset = Literal["kma"]
BaseUrl = Annotated[str, AfterValidator(normalize_base_url)]
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class InfoConnectionCreate(BaseModel):
    name: Name
    preset: Preset
    base_url: BaseUrl | None = None
    secret: SecretStr  # 인코딩·디코딩 서비스키 어느 쪽이든


class InfoConnectionUpdate(BaseModel):
    name: Name | None = None
    base_url: BaseUrl | None = None
    secret: SecretStr | None = None


class InfoConnectionOut(BaseModel):
    """연결 한 줄. 키는 끝 4자리(secret_last4)만."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    preset: Preset
    base_url: str
    secret_last4: str
    status: Literal["ok", "failed", "unknown"]
    checked_at: UtcDatetime | None


class ServiceErrorOut(BaseModel):
    code: str
    message: str


class ServiceCheckOut(BaseModel):
    service: Literal["short_forecast", "asos"]
    label: str
    ok: bool
    latency_ms: int
    error: ServiceErrorOut | None


class InfoTestOut(BaseModel):
    """서비스마다 따로(키가 한 서비스에만 등록됐을 수 있다). summary 예: 「단기예보 OK · ASOS 일자료 등록 안 됨」."""

    ok: bool
    summary: str
    services: list[ServiceCheckOut]
