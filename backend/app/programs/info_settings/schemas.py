from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

from app.info.generic import KEY_NAME_PATTERN
from app.llm.connections import normalize_base_url
from app.store.timeutil import as_utc

Preset = Literal["kma", "generic"]
KeyIn = Literal["query", "header"]
BaseUrl = Annotated[str, AfterValidator(normalize_base_url)]
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Description = Annotated[str, Field(max_length=500)]
Usage = Annotated[str, Field(max_length=4000)]
KeyName = Annotated[str, Field(pattern=KEY_NAME_PATTERN)]
TestPath = Annotated[str, Field(max_length=500)]


class InfoConnectionCreate(BaseModel):
    """범용(generic)은 base_url·description 이 꼭 있어야 한다(서비스가 422 로 거절)."""

    name: Name
    preset: Preset
    base_url: BaseUrl | None = None
    secret: SecretStr  # 인코딩·디코딩 서비스키 어느 쪽이든
    description: Description = ""
    usage: Usage = ""
    key_in: KeyIn = "query"
    key_name: KeyName = "serviceKey"
    test_path: TestPath = ""


class InfoConnectionUpdate(BaseModel):
    name: Name | None = None
    base_url: BaseUrl | None = None
    secret: SecretStr | None = None
    description: Description | None = None
    usage: Usage | None = None
    key_in: KeyIn | None = None
    key_name: KeyName | None = None
    test_path: TestPath | None = None


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
    description: str
    usage: str
    key_in: KeyIn
    key_name: str
    test_path: str


class ServiceErrorOut(BaseModel):
    code: str
    message: str


class ServiceCheckOut(BaseModel):
    service: Literal["short_forecast", "asos", "generic"]
    label: str
    ok: bool
    latency_ms: int
    error: ServiceErrorOut | None


class InfoTestOut(BaseModel):
    """서비스마다 따로(키가 한 서비스에만 등록됐을 수 있다). summary 예: 「단기예보 OK · ASOS 일자료 등록 안 됨」.

    범용은 서비스 한 줄(service "generic", label = 연결 이름)과 HTTP 상태·응답 앞 300자(키 지움)를 더한다.
    """

    ok: bool
    summary: str
    services: list[ServiceCheckOut]
    http_status: int | None = None
    sample: str | None = None


class TemplateOut(BaseModel):
    """빠른 채움 한 줄(app/info/templates.yaml)."""

    id: str
    label: str
    base_url: str
    key_in: KeyIn
    key_name: str
    description: str
    usage: str
    test_path: str
    docs_url: str
