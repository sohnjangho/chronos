"""주소록 API 의 입력·출력. 응답의 번호는 가린 꼴(phone_masked)만 — 전체 번호는 RevealOut 한 곳뿐이다.

번호(phone)와 근무시간(hours)의 값 검사는 여기서 하지 않고 service 가 한 곳에서 한다(한국어 까닭으로 422, 값은 싣지 않음):
번호가 받는 번호인지는 app.outreach.phone.normalize 가 정하고, 근무시간 규칙은 service.check_hours 에 있다.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Gender = Literal["male", "female", "unknown"]
Language = Literal["ko", "en", "zh", "vi"]  # 계획 Task 100 languages.SUPPORTED 와 같은 넷(그 모듈이 생기면 그것으로)
VoiceMode = Literal["auto", "manual"]  # auto = 연락처 성별로 음성을 고름, manual = voice_id
Channel = Literal["sms", "kakao", "call"]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Short = Annotated[str, Field(max_length=100)]
Note = Annotated[str, Field(max_length=2000)]
Reason = Annotated[str, Field(max_length=200)]
PhoneText = Annotated[str, Field(max_length=40)]  # 넘으면 검증 오류(값은 싣지 않는다 — app.errors)
PERSON_CLEARABLE = {"phone", "hours", "voice_id", "dnc_reason"}  # PATCH 로 null 을 보내 비울 수 있는 칸


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _no_null(model: BaseModel, clearable: set[str]) -> None:
    for name in model.model_fields_set - clearable:
        if getattr(model, name) is None:
            raise ValueError(f"{name} 은(는) 비울 수 없습니다.")


class HoursIn(Strict):
    """{"days": [0..6](월=0), "start": "HH:MM", "end": "HH:MM"}. 값 검사는 service.check_hours."""

    days: list[StrictInt]
    start: str
    end: str


class CompanyIn(Strict):
    name: Name
    trade: Short = ""  # 공종
    note: Note = ""


class CompanyPatch(Strict):
    """보낸 칸만 바꾼다. 숨기기는 hidden: true."""

    name: Name | None = None
    trade: Short | None = None
    note: Note | None = None
    hidden: bool | None = None

    @model_validator(mode="after")
    def _required(self) -> "CompanyPatch":
        _no_null(self, set())
        return self


class PersonIn(Strict):
    """hours 가 null 이면 프로젝트 달력의 기본 근무시간. phone 이 null·빈 글이면 번호 없음.
    can_sms·can_call 을 보내지 않으면(null) 번호 종류가 정한다(phone.can_sms·phone.can_call). 참으로 보냈는데 그 번호로
    안 되면 422 channel_not_possible."""

    name: Name
    role_title: Short = ""  # 담당
    company_id: int
    phone: PhoneText | None = None
    can_sms: bool | None = None
    can_kakao: bool = True
    can_call: bool | None = None
    hours: HoursIn | None = None
    gender: Gender = "unknown"
    language: Language = "ko"
    voice_mode: VoiceMode = "auto"
    voice_id: Short | None = None
    do_not_contact: bool = False
    dnc_reason: Reason | None = None
    note: Note = ""


class PersonPatch(Strict):
    """보낸 칸만 바꾼다. null 로 비울 수 있는 칸은 PERSON_CLEARABLE 뿐. 숨기기는 hidden: true."""

    name: Name | None = None
    role_title: Short | None = None
    company_id: int | None = None
    phone: PhoneText | None = None
    can_sms: bool | None = None
    can_kakao: bool | None = None
    can_call: bool | None = None
    hours: HoursIn | None = None
    gender: Gender | None = None
    language: Language | None = None
    voice_mode: VoiceMode | None = None
    voice_id: Short | None = None
    do_not_contact: bool | None = None
    dnc_reason: Reason | None = None
    note: Note | None = None
    hidden: bool | None = None

    @model_validator(mode="after")
    def _required(self) -> "PersonPatch":
        _no_null(self, PERSON_CLEARABLE)
        return self


class CompanyOut(BaseModel):
    id: int
    name: str
    trade: str
    note: str
    hidden: bool


class HoursOut(BaseModel):
    days: list[int]
    start: str
    end: str


class ActivityRef(BaseModel):
    id: str
    name: str


class PersonBrief(BaseModel):
    """주소록 한 줄. last_line 은 마지막 메시지(번호를 가린 뒤) 앞 30자, 메시지가 없으면 null."""

    id: int
    name: str
    role_title: str
    company_id: int
    phone_masked: str  # 010-****-0199, 번호가 없으면 「번호 없음」
    has_phone: bool
    phone_kind: str | None  # phone.kind: mobile | landline | internet | rep | safe | tollfree | premium, 번호 없으면 null
    channels: list[Channel]  # 받을 수 있다고 둔 것(can_*)
    unread: int  # 읽지 않은 받은 메시지
    do_not_contact: bool  # 번호 기준(store.outreach.is_do_not_contact) 또는 이 연락처의 표시
    phone_invalid: bool
    last_line: str | None
    hidden: bool


class PersonDetail(PersonBrief):
    hours: HoursOut | None  # null = 프로젝트 기본(달력의 근무일 08:00~18:00)
    working_now: bool
    hours_label: str  # 「근무 중 · 18:00 까지」 / 「근무 밖 · 월 08:00 부터」 / 「근무시간 없음」
    gender: Gender
    language: str
    voice_mode: VoiceMode
    voice_id: str | None
    dnc_reason: str | None
    note: str
    linked_activities: list[ActivityRef]


class CompanyGroup(CompanyOut):
    people: list[PersonBrief]


class AddressBookOut(BaseModel):
    companies: list[CompanyGroup]
    proposals_pending: int  # 이 일정의 확인할 연락처 제안
    reports_open: int  # 이 일정의 확인하지 않은 보고


class RevealOut(BaseModel):
    phone: str | None  # 010-0000-0199. 번호가 없으면 null


class ReadOut(BaseModel):
    read: int  # 이번에 읽음으로 바꾼 받은 메시지 수
