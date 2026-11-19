"""계산값을 담은 일정(ScheduleView) 만들기. 계산과 자료 모으기는 app.store.view 가 한다."""

from sqlalchemy.orm import Session

from app.programs.schedule.schemas import ScheduleView
from app.store.view import view_data


def build_view(session: Session, schedule_id: int) -> ScheduleView:
    """지금 버전의 계산 포함 응답. 없는 일정이면 NotFound, 깨진 일정이면 ScheduleError."""
    return ScheduleView.model_validate(view_data(session, schedule_id))
