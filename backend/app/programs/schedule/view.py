"""계산값을 담은 일정(ScheduleView) 만들기. 계산과 자료 모으기는 app.store.view 가 한다."""

from sqlalchemy.orm import Session

from app.core.cpm import CpmResult
from app.programs.schedule.schemas import ScheduleView
from app.store.view import view_data


def build_view(
    session: Session, schedule_id: int, computed: tuple[int, CpmResult] | None = None
) -> ScheduleView:
    """지금 버전의 계산 포함 응답. 없는 일정이면 NotFound, 깨진 일정이면 ScheduleError.

    computed=(버전 번호, run 결과) 는 방금 확인한 계산을 다시 하지 않으려고 넘긴다.
    """
    return ScheduleView.model_validate(view_data(session, schedule_id, computed))
