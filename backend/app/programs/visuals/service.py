"""보고서용 그림 API 의 일(Task 44). 그림 만들기는 도구 visual.make 와 같은 길(app.llm.visualization.make)이다."""

from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.agent import context
from app.core.cpm import ScheduleError
from app.errors import ApiError
from app.llm import visualization
from app.programs.visuals.schemas import VisualIn, VisualOut
from app.store import visuals
from app.store.messages import schedule_error_message
from app.store.tables import User, Visual

SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
NOT_FOUND_MESSAGE = "그림을 찾을 수 없습니다."


async def _explained(make: Callable[[], Awaitable[Visual]]) -> Visual:
    try:
        return await make()
    except visuals.NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None
    except visuals.TableError as e:
        raise ApiError(422, "no_data", e.message) from None


async def make(session: Session, schedule_id: int, body: VisualIn, user: User) -> VisualOut:
    row = await _explained(lambda: visualization.make(
        session, kind=body.kind, schedule_id=schedule_id, version=body.version, today=context.today(),
        created_by=user.name, unit=body.unit))
    session.commit()
    return VisualOut.model_validate(visuals.out(row))


def read(session: Session, schedule_id: int, visual_id: int) -> VisualOut:
    try:
        row = visuals.get(session, schedule_id, visual_id)
    except visuals.NotFound:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE) from None
    return VisualOut.model_validate(visuals.out(row))
