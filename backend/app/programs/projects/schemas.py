"""프로젝트 관리 API 의 입력·출력. 글의 길이·글자·번호 검사는 service 한 곳(한국어 까닭으로 422, 값은 싣지 않음)."""

import unicodedata
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.store.timeutil import as_utc


def _nfc(value: object) -> object:
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value


# 길이 상한은 service 가 칸마다 글로 알린다 — 여기 상한은 지나치게 긴 몸을 막는 둘째 줄일 뿐이다
Text = Annotated[str, BeforeValidator(_nfc), Field(max_length=1000)]
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]


class ProjectOut(BaseModel):
    """spoken = 에이전트가 실제로 부르는 이름(spoken_name, 비었으면 날짜·판 표시를 뗀 이름). same_name = 그 이름이 다른 프로젝트와 겹침."""

    id: int
    name: str
    spoken_name: str
    spoken: str
    site_address: str
    summary: str
    client_builder: str
    updated_at: UtcDatetime | None
    updated_by: str
    same_name: bool = False  # 부를 이름이 다른 프로젝트의 부를 이름·다듬은 이름과 같다(통화에서 구별 못 함)
    same_as: str | None = None  # 그 겹치는 프로젝트의 이름


class ProjectPatch(BaseModel):
    """보낸 칸만 바꾼다. 빈 글은 지움(이름 밖). null 은 받지 않는다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Text | None = None
    spoken_name: Text | None = None
    site_address: Text | None = None
    summary: Text | None = None
    client_builder: Text | None = None

    @model_validator(mode="after")
    def _no_null(self) -> "ProjectPatch":
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다(빈 글로 보내 주세요).")
        return self
