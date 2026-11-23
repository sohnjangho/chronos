"""음성 설정 API 의 요청·응답 꼴과 입력 검사(계획 4 Task 90 — voice.py 에서 옮김). 계약: task-90-contract.md."""

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
)

from app.errors import ApiError
from app.notify import diagnostics
from app.outreach import phone, redact
from app.outreach.voice.voices import SLOTS
from app.programs.notify_settings import service
from app.programs.notify_settings.schemas import StepOut, UtcDatetime

Provider = Literal["google", "openai", "dashboard"]
StepId = Literal["P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12", "P13", "P14"]
Part = Literal["connection", "call", "inbound"]
SLOT_FIELDS = tuple(SLOTS.values())
MAX_CHARS = {"secret": service.MAX_SECRET_CHARS, "model": 80, "agent_number": 40, **dict.fromkeys(SLOT_FIELDS, 100)}
MAX_LANGUAGES = 20
WAIT_MIN, WAIT_DEFAULT = 10, 90
INVALID_VOICE = "음성 이름은 영문으로 시작하고 영문·숫자·점(.)·줄표(-)·밑줄(_)만 쓸 수 있습니다."
_MODEL = re.compile(r"[A-Za-z0-9._\-]{1,80}")  # 진단 모듈이 받는 꼴과 같다
_VOICE = re.compile(r"[A-Za-z][A-Za-z0-9._\-]{0,99}")
_LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?")


# ── 요청·응답 꼴 ─────────────────────────────────────────────────────


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceUpdate(_In):
    """보낸 칸만 바꾼다. 번호·음성 칸은 null 도 「보냄」(비움) — model_fields_set 으로 가른다."""

    provider: Provider | None = None
    secret: SecretStr | None = None
    model: str | None = None
    agent_number: str | None = None
    voice_male_contact: str | None = None
    voice_female_contact: str | None = None
    voice_unknown: str | None = None
    voices_by_language: dict[str, Any] | None = None  # 안쪽은 손으로 검사한다(검증 오류에 열쇠가 되돌아가지 않게)


class VoiceDiagnoseIn(_In):
    """번호를 받는 칸이 없다 — 거는 번호는 저장된 첫 허용 번호뿐이다."""

    steps: Annotated[list[StepId], Field(min_length=1, max_length=10)] | None = None
    call: StrictBool = False
    inbound: StrictBool = False
    allow_numbers_version: str | None = None  # call·inbound 가 참이면 꼭
    confirm_recall: StrictBool = False
    wait_inbound_s: StrictInt = WAIT_DEFAULT


class KeyNotice(BaseModel):
    code: str
    message: str


class VoiceOut(BaseModel):
    connection_id: int
    provider: str
    has_secret: bool
    secret_last4: str
    model: str
    agent_number_masked: str | None
    agent_number_kind: str
    voice_male_contact: str | None
    voice_female_contact: str | None
    voice_unknown: str | None
    voices_by_language: dict[str, dict[str, str]]
    status: str
    checked_at: UtcDatetime | None
    sdk_installed: bool
    test_call_index: int | None
    key_notice: KeyNotice | None
    call_limits: dict[str, int]
    saved: bool  # 음성 설정 줄이 있는가(없으면 화면은 넣기 폼을, 있으면 카드를 보인다)
    model_effective: str  # 실제로 쓰는 모델(구글은 빈 값이면 기본 Live 모델, 다른 공급자는 빈 값 = SDK 기본 "")
    agent_number_effective_masked: str | None  # 실제로 쓰는 AI 전화 번호(가린 꼴) — 비었으면 알림 연결의 발신번호
    agent_number_source: Literal["voice", "connection"] | None


class VoiceModelsOut(BaseModel):
    models: list[str]
    default: str
    fallback: bool  # 구글에서 읽은 목록이 아니라 고정 목록(거절이면 빈 목록)
    refused: bool  # 구글이 이 키를 거절했다(400·401·403) — 진단·시험 전화는 걸기 전에 P5 key_refused 로 멈춘다
    reason: str | None  # fallback 의 까닭(쉬운 한국어)


class VoiceStepOut(StepOut):
    data: dict[str, Any] = Field(default_factory=dict)
    ran_at: UtcDatetime | None = None


class CallRecord(BaseModel):
    at: UtcDatetime
    by: str
    outcome: Literal["calling", "placed", "unknown", "not_placed"]


class VoiceDiagnosisOut(BaseModel):
    state: Literal["running", "done"]
    part: Part | None
    ran_at: UtcDatetime
    by: str | None
    steps: list[VoiceStepOut]
    called_real: bool
    call_unknown: bool
    calls: list[CallRecord]


# ── 설정: 검사 ───────────────────────────────────────────────────────


def _too_long(name: str, limit: int, unit: str = "자") -> ApiError:
    return ApiError(422, "too_long", f"{limit}{unit}까지 넣을 수 있습니다.", {"field": name, "max": limit})


def _voice_id(raw: object, name: str) -> str | None:
    """음성 이름 하나: 빈 값은 None(비움). 영문으로 시작하는 낱말 꼴만 — 번호처럼 보이는 것은 받지 않는다."""
    if not isinstance(raw, str | None):
        raise ApiError(422, "invalid_voice", INVALID_VOICE, {"field": name})
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > MAX_CHARS["voice_unknown"]:
        raise _too_long(name, MAX_CHARS["voice_unknown"])
    if not _VOICE.fullmatch(value) or redact.hide_phones(value) != value:
        raise ApiError(422, "invalid_voice", INVALID_VOICE, {"field": name})
    return value



def _by_language(raw: dict) -> dict[str, dict[str, str]]:
    name = "voices_by_language"
    if len(raw) > MAX_LANGUAGES:
        raise _too_long(name, MAX_LANGUAGES, "개")
    bad = ApiError(422, "invalid_language", "언어별 음성의 언어 코드나 칸 이름이 올바르지 않습니다.", {"field": name})
    out: dict[str, dict[str, str]] = {}
    for language, slots in raw.items():
        code = language.strip().lower()
        if not _LANGUAGE.fullmatch(code) or not isinstance(slots, dict) or not set(slots) <= set(SLOT_FIELDS):
            raise bad
        found = {slot: _voice_id(value, name) for slot, value in slots.items()}
        out[code] = {slot: value for slot, value in found.items() if value}
    return out


def _checked(data: VoiceUpdate) -> dict:
    """보낸 칸을 검사해 저장할 값으로 바꾼다 {칸: 값}. 틀리면 ApiError — 보낸 값은 싣지 않는다."""
    sent, values = data.model_fields_set, {}
    if data.provider is not None:
        values["provider"] = data.provider
    if data.secret is not None:
        key = data.secret.get_secret_value().strip()
        if len(key) > MAX_CHARS["secret"]:
            raise _too_long("secret", MAX_CHARS["secret"])
        if len(key) < diagnostics.MIN_SECRET or not key.isascii() or not key.isprintable() or " " in key:
            raise ApiError(422, "invalid_secret", "음성 모델 키는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.")
        values["secret"] = key
    if data.model is not None:
        model = data.model.strip()
        if len(model) > MAX_CHARS["model"]:
            raise _too_long("model", MAX_CHARS["model"])
        if model and (not _MODEL.fullmatch(model) or redact.hide_phones(model) != model):
            raise ApiError(422, "invalid_model", "모델 이름에는 영문·숫자·점(.)·줄표(-)·밑줄(_)만 쓸 수 있습니다.")
        values["model"] = model
    if "agent_number" in sent:
        raw = (data.agent_number or "").strip()
        if len(raw) > MAX_CHARS["agent_number"]:
            raise _too_long("agent_number", MAX_CHARS["agent_number"])
        number = phone.normalize(raw) if raw else None
        if raw and (number is None or not phone.can_call(number)):
            raise ApiError(422, "invalid_number", "번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.", {"field": "agent_number"})
        values["agent_number"] = number
    for slot in SLOT_FIELDS:
        if slot in sent:
            values[slot] = _voice_id(getattr(data, slot), slot)
    if data.voices_by_language is not None:
        values["voices_by_language"] = _by_language(data.voices_by_language)
    return values
