from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.store.timeutil import as_utc

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 Z 가 붙는다


class RuleOut(BaseModel):
    id: int
    scope: Literal["domain", "schedule"]
    domain: str
    schedule_id: int | None
    condition: dict  # Condition.to_dict 모양(layer mine, source 「내 규칙」)
    enabled: bool
    created_by: str
    created_at: UtcDatetime
    in_schedule: bool | None  # schedule_id 로 물었을 때만: 그 일정 지금 조건에 같은 id 가 있는가


class EnabledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(strict=True)


class DeletedOut(BaseModel):
    deleted: int
