"""도구가 실행될 때 받는 문맥과, 도구가 내는 오류."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.core.cpm import ScheduleError
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound
from app.store.tables import User

NO_SCHEDULE_MESSAGE = "대상 일정이 없습니다."
SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."


class ToolError(Exception):
    """도구가 일부러 내는 실패. message 는 그대로 ToolResult.error 가 된다(한국어, 자료 없이)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@contextmanager
def explained_schedule_errors() -> Iterator[None]:
    """없는 일정(NotFound)·계산이 안 되는 일정(ScheduleError)을 한국어 설명의 ToolError 로 바꾼다."""
    try:
        yield
    except NotFound:
        raise ToolError(SCHEDULE_NOT_FOUND_MESSAGE) from None
    except ScheduleError as e:
        raise ToolError(schedule_error_message(e)) from None


def _never() -> bool:
    return False


class NoArgs(BaseModel):
    """입력이 없는 도구의 입력 모델."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    session: Session
    user: User | None
    schedule_id: int | None  # 지금 다루는 일정. 없을 수 있다
    emit: Callable[[AgentEvent], None]
    chat_session_id: int | None = None  # 지금 대화. 대화 밖에서 부르면 None
    # 사용자가 멈춤을 눌렀는가. 오래 도는 도구(생성 루프)는 LLM 을 부르기 전에 본다. 대화 밖에서는 늘 False
    stop_requested: Callable[[], bool] = _never

    def require_schedule_id(self) -> int:
        """대상 일정 id. 없으면 ToolError."""
        if self.schedule_id is None:
            raise ToolError(NO_SCHEDULE_MESSAGE)
        return self.schedule_id
