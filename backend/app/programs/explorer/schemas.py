from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel

from app.store.timeutil import as_utc

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 Z 가 붙는다


class TreeSchedule(BaseModel):
    id: int
    name: str
    domain: str
    level: str
    version: int  # 지금 버전
    finish: date | None  # 화면과 같은 계산값(저장된 조건을 넣음). 깨진 일정이면 null
    updated_at: UtcDatetime  # 지금 버전을 만든 때


class TreeOut(BaseModel):
    schedules: list[TreeSchedule]  # id 순


class DeletedOut(BaseModel):
    deleted: int  # 지운 일정 id
