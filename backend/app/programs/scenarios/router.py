from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.scenarios import compare, service
from app.programs.scenarios.schemas import (
    CompareOut,
    CompareSummaryOut,
    DiscardOut,
    ScenarioDetail,
    ScenarioOut,
    StatusGroup,
    SubmitIn,
    SubmitOut,
)
from app.security.deps import current_user
from app.store.tables import User

# 만약에 복사본: 로그인한 누구나 보고, 버리고, 승인함으로 낸다(반영은 승인함의 결정).
router = APIRouter(prefix="/api/schedules", tags=["scenarios"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/{schedule_id}/scenarios")
def list_scenarios(schedule_id: int, session: SessionDep, status: StatusGroup = "open") -> list[ScenarioOut]:
    return service.list_scenarios(session, schedule_id, status)


@router.get("/{schedule_id}/scenarios/{scenario_id}")
def read_scenario(schedule_id: int, scenario_id: int, session: SessionDep) -> ScenarioDetail:
    return service.detail(session, schedule_id, scenario_id)


@router.delete("/{schedule_id}/scenarios/{scenario_id}")
def discard_scenario(schedule_id: int, scenario_id: int, session: SessionDep) -> DiscardOut:
    return service.discard(session, schedule_id, scenario_id)


@router.post("/{schedule_id}/scenarios/{scenario_id}/submit")
def submit_scenario(schedule_id: int, scenario_id: int, body: SubmitIn, session: SessionDep, user: UserDep) -> SubmitOut:
    return service.submit(session, schedule_id, scenario_id, body, user)


@router.get("/{schedule_id}/compare")
def compare_plans(schedule_id: int, other: str, session: SessionDep, base: str = "current") -> CompareOut:
    """두 안(current · plan · v:<n> · s:<복사본 id>)의 요약과 액티비티별 차이."""
    return compare.compare(session, schedule_id, base, other)


@router.get("/{schedule_id}/compare/summary")
def compare_summary(schedule_id: int, session: SessionDep) -> CompareSummaryOut:
    return compare.summary(session, schedule_id)
