from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.devconsole import catalog, service
from app.programs.devconsole.schemas import TurnDetail, TurnOut, UsageGroup, UsageOut
from app.security.deps import require_admin

# 관리자만(아니면 403 admin_only).
router = APIRouter(prefix="/api/devconsole", tags=["devconsole"], dependencies=[Depends(require_admin)])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/turns")
def list_turns(session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 30) -> list[TurnOut]:
    return service.list_turns(session, limit)


@router.get("/turns/{turn_id}")
def get_turn(turn_id: int, session: SessionDep) -> TurnDetail:
    return service.get_turn(session, turn_id)


@router.get("/usage")
def read_usage(
    session: SessionDep, days: Annotated[int, Query(ge=1, le=90)] = 14, group: UsageGroup = "model",
) -> UsageOut:
    return service.usage(session, days=days, group=group)


@router.get("/catalog")
def read_catalog(session: SessionDep) -> dict[str, Any]:
    return catalog.get_catalog(session)


@router.post("/harness/{rule_id}/test")
def test_harness_rule(rule_id: str) -> dict[str, Any]:
    return catalog.run_harness_test(rule_id)
