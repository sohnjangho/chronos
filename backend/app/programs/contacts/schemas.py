"""주소록 API 의 입력·출력. 응답의 번호는 가린 꼴(phone_masked)만 — 전체 번호는 RevealOut 한 곳뿐이다.

번호(phone)와 근무시간(hours)의 값 검사는 여기서 하지 않고 service 가 한 곳에서 한다(한국어 까닭으로 422, 값은 싣지 않음):
번호가 받는 번호인지는 app.outreach.phone.normalize 가 정하고, 근무시간 규칙은 service.check_hours 에 있다.
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


def _nfc(value: object) -> object:
    """글은 검사·길이 재기·저장 전에 NFC 로 — macOS(NFD)와 Windows(NFC)에서 친 같은 이름이 한 이름(찾기·신원 규칙)."""
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value


Nfc = BeforeValidator(_nfc)
Gender = Literal["male", "female", "unknown"]
Language = Literal["ko", "en", "zh", "vi"]  # 계획 Task 100 languages.SUPPORTED 와 같은 넷(그 모듈이 생기면 그것으로)
VoiceMode = Literal["auto", "manual"]  # auto = 연락처 성별로 음성을 고름, manual = voice_id
Channel = Literal["sms", "kakao", "call"]
# 관리자 등급(11-24): trade = 자기 협력사·공종의 일정만(기본), manager = 등록된 프로젝트의 모든 협력사 일정. 관리자만 정한다.
AccessLevel = Literal["trade", "manager"]
Name = Annotated[str, Nfc, Field(min_length=1, max_length=100)]
Short = Annotated[str, Nfc, Field(max_length=100)]
Note = Annotated[str, Nfc, Field(max_length=2000)]
Reason = Annotated[str, Nfc, Field(max_length=200)]
VoiceId = Annotated[str, Field(max_length=100)]  # 꼴(영문·숫자·._:-, 64자)은 service.check_voice — 422 invalid_voice
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
    can_sms·can_kakao·can_call 을 보내지 않으면(null) 번호 종류가 정한다(문자·카카오톡 phone.can_sms, 전화 phone.can_call).
    참으로 보냈는데 그 번호로 안 되면 422 channel_not_possible. 이름·담당·메모의 글자 검사는 service.check_texts."""

    name: Name
    role_title: Short = ""  # 담당
    company_id: int
    phone: PhoneText | None = None
    can_sms: bool | None = None
    can_kakao: bool | None = None
    can_call: bool | None = None
    hours: HoursIn | None = None
    gender: Gender = "unknown"
    language: Language = "ko"
    voice_mode: VoiceMode = "auto"
    voice_id: VoiceId | None = None
    do_not_contact: bool = False
    dnc_reason: Reason | None = None
    note: Note = ""
    access_level: AccessLevel = "trade"  # trade 가 아니면 관리자만(403 admin_only_level)


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
    voice_id: VoiceId | None = None
    do_not_contact: bool | None = None
    dnc_reason: Reason | None = None
    note: Note | None = None
    hidden: bool | None = None
    access_level: AccessLevel | None = None  # 바꾸는 것은 관리자만(403 admin_only_level)

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
    access_level: AccessLevel
    projects: int  # 이 사람이 등록된(숨기지 않은) 프로젝트 수 — 이 프로젝트 포함, 혼자면 1


class ProjectLink(BaseModel):
    """같은 사람의 한 프로젝트 줄(같은 person_key). 번호는 없다."""

    schedule_id: int
    name: str  # 프로젝트(일정) 이름
    contact_id: int
    company_id: int
    company_name: str
    current: bool  # 지금 연 줄


class PersonDetail(PersonBrief):
    hours: HoursOut | None  # null = 프로젝트 기본(달력의 근무일 08:00~18:00)
    working_now: bool
    hours_label: str  # 「근무 중 · 18:00 까지」 / 「근무 밖 · 월 08:00 부터」 / 「근무시간 없음」
    next_start: datetime | None  # 다음 근무 시작(KST, 근무 중이면 지금) — 근무시간을 찾지 못하면 null. 통화 예약이 쓴다(Task 92)
    gender: Gender
    language: str
    voice_mode: VoiceMode
    voice_id: str | None
    dnc_reason: str | None
    note: str
    linked_activities: list[ActivityRef]
    project_links: list[ProjectLink]  # 등록된 프로젝트(숨긴 줄은 빼고, 지금 연 줄은 늘), 일정 id 순


class ProjectChoice(BaseModel):
    """「참여 프로젝트」 고르기의 한 줄 — 이 사용자가 관리할 수 있는 프로젝트마다."""

    schedule_id: int
    name: str
    linked: bool  # 이 사람이 그 프로젝트에 (보이게) 등록됨
    current: bool
    contact_id: int | None
    company_id: int | None
    company_name: str | None


class ProjectAdd(Strict):
    """이 사람을 다른 프로젝트에 등록. company_id = 그 프로젝트의 협력사(새 줄이면 꼭). link_contact_id 를 주면 새 줄 대신
    그 프로젝트의 같은 번호 연락처를 같은 사람으로 잇는다(「같은 사람으로 연결」)."""

    schedule_id: int
    company_id: int | None = None
    role_title: Short | None = None
    link_contact_id: int | None = None


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


# ── CSV 가져오기·다른 프로젝트에서 복사(Task 76) ─────────────────────────────────────

ImportResult = Literal["new", "exists", "no_phone", "bad_phone", "bad_row"]


class ImportRowOut(BaseModel):
    """CSV 한 행의 판정. 글(협력사·이름·담당)은 번호를 가린 꼴(hide_phones), 걸린 칸의 글은 null(되돌려 보이지 않음)."""

    n: int  # 파일의 행 번호(머리줄 = 1, 첫 자료 행 = 2 — 스프레드시트의 행 번호)
    company: str | None
    name: str | None
    role_title: str | None
    phone_shown: str  # 맞는 번호 010-****-0199 · 틀린 번호 phone.mask_bad · 빈칸 「번호 없음」
    phone_kind: str | None
    do_not_contact: bool  # 그 번호가 어디서든 수신 거부(store.outreach)
    result: ImportResult
    reason: str | None  # bad_*·exists 의 한국어 까닭(값 없이)
    code: str | None  # bad_* 의 검사 코드(invalid_phone·invalid_text·missing_value …)
    column: str | None  # bad_row 가 걸린 CSV 열 이름(협력사·이름·공종·담당·성별·언어·메모)
    skipped: bool  # 요청의 skip 에 든 행(넣지 않음)


class ImportSummary(BaseModel):
    """건너뛴 행(skipped)은 다른 셈에 들지 않는다. bad = bad_phone + bad_row. 넣는(넣은) 사람 = new + no_phone."""

    new: int
    exists: int
    no_phone: int
    bad: int
    skipped: int


class ImportOut(BaseModel):
    rows: list[ImportRowOut]
    summary: ImportSummary


class CopySourceOut(BaseModel):
    schedule_id: int
    name: str
    people: int  # 숨기지 않은 사람 수


class CopyPersonOut(BaseModel):
    id: int
    name: str
    role_title: str
    phone_masked: str
    phone_kind: str | None
    has_phone: bool
    do_not_contact: bool
    already_here: bool  # 같은 번호(또는 번호 없이 같은 협력사·이름)가 이 일정에 이미 있다 — 복사하면 건너뜀


class CopyCompanyOut(BaseModel):
    id: int
    name: str
    trade: str
    people: list[CopyPersonOut]


class CopySourceDetail(BaseModel):
    schedule_id: int
    name: str
    companies: list[CopyCompanyOut]


class CopyIn(Strict):
    from_schedule_id: int
    contact_ids: list[int] = Field(min_length=1, max_length=500)


class CopyOut(BaseModel):
    copied: int
    skipped: int  # 이미 있음(같은 번호, 번호가 없으면 같은 협력사·이름)
    refused: int  # 주소록 입력 검사를 지나지 못한 예전 줄(복사하지 않음)
