"""통화 API 의 입력·출력. 응답에 전화번호 칸은 없다 — 연락처는 이름·담당·협력사만.

글(목적·물어볼 것·말하지 않을 것·확정한 결과)은 NFC 로 바꾼 뒤 앞뒤 빈칸을 지운다. 보이지 않는 제어·방향 글자 검사는
calls_service(422 invalid_text, 값은 싣지 않음). 모르는 칸은 422.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StrictInt, model_validator

from app.programs.outreach.schemas import (
    ActivityId,
    ActivityOut,
    Nfc,
    OutcomeOut,
    Strict,
)

PURPOSE_MAX = 500
LINE_MAX = 200  # 물어볼 것·말하지 않을 것 한 줄
LINES_MAX = 10
RESULT_MAX = 2000
Language = Literal["ko", "en", "zh", "vi"]  # 주소록 API 의 Language 와 같은 넷
Purpose = Annotated[str, Nfc, Field(min_length=1, max_length=PURPOSE_MAX)]
Line = Annotated[str, Nfc, Field(min_length=1, max_length=LINE_MAX)]
Lines = Annotated[list[Line], Field(max_length=LINES_MAX)]
VoiceId = Annotated[str, Field(min_length=1, max_length=100)]


class CallIn(Strict):
    """통화 초안(origin user). language 를 주지 않으면 연락처의 언어. voice_id 가 없으면 일꾼이 고른다."""

    contact_id: StrictInt
    purpose: Purpose
    questions: Lines = Field(default_factory=list)
    avoid: Lines = Field(default_factory=list)
    activity_id: ActivityId | None = None
    language: Language | None = None
    voice_id: VoiceId | None = None


class CallPatch(Strict):
    """초안만. 보낸 칸만 바꾼다 — null 로 비울 수 있는 것은 activity_id·voice_id 뿐."""

    purpose: Purpose | None = None
    questions: Lines | None = None
    avoid: Lines | None = None
    activity_id: ActivityId | None = None
    language: Language | None = None
    voice_id: VoiceId | None = None

    @model_validator(mode="after")
    def _required(self) -> "CallPatch":
        for name in self.model_fields_set - {"activity_id", "voice_id"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다.")
        return self


class ScheduleIn(Strict):
    at: AwareDatetime  # 시간대가 붙은 시각만(없으면 422)


class ConfirmIn(Strict):
    result: Annotated[str, Nfc, Field(min_length=1, max_length=RESULT_MAX)]


class CallContact(BaseModel):
    id: int
    name: str
    role_title: str
    company: str  # 협력사 이름


class AnswerOut(BaseModel):
    question: str
    answer: str
    quote: str
    quote_found: bool


class CallEventOut(BaseModel):
    rule: str
    verdict: str
    detail: str | None
    at: str | None


class CallOut(BaseModel):
    id: int
    direction: str
    caller_class: str | None
    contact: CallContact | None  # 주소록에 없는 번호의 받은 통화는 null
    origin: str
    origin_name: str
    send_mode: str | None
    approved_by: str | None
    status: str
    fail_reason: str | None
    purpose: str
    questions: list[str]
    avoid: list[str]
    language: str
    voice_id: str | None
    duration_s: int | None
    summary_ko: str
    result_proposed: str
    result_confirmed: str | None
    confirmed_by: str | None
    answers: list[AnswerOut]
    events: list[CallEventOut]
    has_recording: bool
    prev_call_id: int | None
    activity: ActivityOut | None
    scheduled_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class TranscriptLine(BaseModel):
    role: str  # agent | peer
    text: str
    t: float | None


class ReportOut(BaseModel):
    id: int
    kind: str
    text: str
    quote: str
    quote_found: bool
    status: str
    reviewed_by: str | None
    created_at: datetime


class CallDetail(CallOut):
    transcript: list[TranscriptLine]
    reports: list[ReportOut]  # 이 통화에서 받은 보고


class CallResult(BaseModel):
    call: CallOut
    outcome: OutcomeOut  # 문의 판정 그대로 — 근무시간 밖이면 scheduled_at 에 문이 제안한 다음 근무 시작(KST)
