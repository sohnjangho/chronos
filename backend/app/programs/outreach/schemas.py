"""메시지 API 의 입력·출력. 응답에 전화번호 칸은 없다 — 연락처는 가린 꼴(phone_masked)만.

본문(body)은 NFC 로 바꾼 뒤 앞뒤 빈칸을 지우고 1~1000자. 보이지 않는 제어·방향 글자 검사는 service.check_body
(422 invalid_text, 값은 싣지 않음). 모르는 칸은 422.
"""

import unicodedata
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

BODY_MAX = 1000  # 문자 본문 길이(글자 수 세기·나눔 안내는 화면 — Task 79)


def _nfc(value: object) -> object:
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value


Nfc = BeforeValidator(_nfc)
Channel = Literal["sms", "kakao"]  # 카카오톡은 잠겨 있다 — 문이 문자로 바꿔 보낸다
Body = Annotated[str, Nfc, Field(min_length=1, max_length=BODY_MAX)]
VarName = Annotated[str, Field(min_length=1, max_length=50)]
VarValue = Annotated[str, Nfc, Field(max_length=200)]
ActivityId = Annotated[str, Field(min_length=1, max_length=50)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MessageIn(Strict):
    """초안을 만든다(origin user). send 면 저장한 뒤 나가는 문에 넣는다."""

    contact_id: StrictInt
    channel: Channel
    body: Body
    template_id: StrictInt | None = None
    template_vars: Annotated[dict[VarName, VarValue], Field(max_length=20)] | None = None
    activity_id: ActivityId | None = None
    field_item_id: StrictInt | None = None
    approval_id: StrictInt | None = None
    send: bool = False


HINT_MAX = 500  # [에이전트에게 초안 맡기기]의 힌트 길이


class AgentDraftIn(Strict):
    """[에이전트에게 초안 맡기기]: 모델이 쓴 초안 줄(origin agent)을 만든다. 보내지 않는다."""

    contact_id: StrictInt
    channel: Channel
    activity_id: ActivityId | None = None
    hint: Annotated[str, Nfc, Field(max_length=HINT_MAX)] = ""


class MessagePatch(Strict):
    """초안만. 보낸 칸만 바꾼다 — null 로 비울 수 있는 것은 activity_id 뿐."""

    body: Body | None = None
    channel: Channel | None = None
    activity_id: ActivityId | None = None

    @model_validator(mode="after")
    def _required(self) -> "MessagePatch":
        for name in self.model_fields_set - {"activity_id"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다.")
        return self


class ActivityOut(BaseModel):
    id: str
    name: str | None  # 지금 버전에 그 작업이 없으면 null


class ChatOut(BaseModel):
    id: int
    title: str  # 그 대화를 만든 사람에게만 — 다른 사람에게는 빈 글(대화는 만든 사람만 본다)


class BatchOut(BaseModel):
    id: int
    total: int  # 그 묶음으로 나간 메시지 수
    replied: int  # 그 묶음 메시지에 reply_to_id 로 답한 사람 수


class EventOut(BaseModel):
    rule: str
    verdict: str
    detail: str | None


class MessageOut(BaseModel):
    id: int
    direction: str
    channel: str
    kind: str
    body: str
    body_ko: str | None
    has_media: bool
    origin: str
    origin_name: str
    send_mode: str | None
    approved_by: str | None
    status: str
    fail_reason: str | None
    fallback_sms: bool
    template_id: int | None
    reply_to_id: int | None
    activity: ActivityOut | None
    field_item_id: int | None
    approval_id: int | None
    chat: ChatOut | None
    batch: BatchOut | None
    events: list[EventOut]
    scheduled_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


class OutcomeOut(BaseModel):
    """나가는 문의 판정 그대로(code·message). scheduled_at 은 예약됐을 때 그 시각(KST)."""

    code: str
    message: str
    scheduled_at: datetime | None


class MessageResult(BaseModel):
    message: MessageOut
    outcome: OutcomeOut | None  # 보내지 않았으면 null


class ResendOut(BaseModel):
    message: MessageOut  # 같은 글의 새 초안
    warning: str | None  # 옛 줄이 「확인 필요」였으면 「이미 나갔을 수 있습니다」


class ContactBrief(BaseModel):
    """주소록 API(Task 72)의 PersonBrief 와 같은 칸 — 프로그램끼리 import 하지 않으므로 여기 다시 적는다."""

    id: int
    name: str
    role_title: str
    company_id: int
    phone_masked: str
    has_phone: bool
    phone_kind: str | None
    channels: list[str]
    unread: int
    do_not_contact: bool
    phone_invalid: bool
    last_line: str | None
    hidden: bool


class ThreadOut(BaseModel):
    contact: ContactBrief
    messages: list[MessageOut]  # 오래된 것부터
    has_more: bool  # 더 앞의 메시지가 있음(before = messages[0].id 로 더 읽음)
