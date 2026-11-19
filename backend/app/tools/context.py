"""도구가 실행될 때 받는 문맥과, 도구가 내는 오류."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.store.tables import User

NO_SCHEDULE_MESSAGE = "대상 일정이 없습니다."


class ToolError(Exception):
    """도구가 일부러 내는 실패. message 는 그대로 ToolResult.error 가 된다(한국어, 자료 없이)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NoArgs(BaseModel):
    """입력이 없는 도구의 입력 모델."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    session: Session
    user: User | None
    schedule_id: int | None  # 지금 다루는 일정. 없을 수 있다
    emit: Callable[[AgentEvent], None]

    def require_schedule_id(self) -> int:
        """대상 일정 id. 없으면 ToolError."""
        if self.schedule_id is None:
            raise ToolError(NO_SCHEDULE_MESSAGE)
        return self.schedule_id
