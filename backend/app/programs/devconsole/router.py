from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.devconsole import catalog, service
from app.programs.devconsole.schemas import AgentConfigOut, AgentConfigPatch, TurnDetail, TurnOut, UsageGroup, UsageOut
from app.security.deps import require_admin
from app.store import settings as settings_store

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


@router.get("/agent-config")
def read_agent_config(session: SessionDep) -> AgentConfigOut:
    return AgentConfigOut.model_validate(settings_store.get_agent_config(session))


@router.put("/agent-config")
def write_agent_config(body: AgentConfigPatch, session: SessionDep) -> AgentConfigOut:
    updated = settings_store.set_agent_config(session, body.model_dump(exclude_unset=True))
    return AgentConfigOut.model_validate(updated)
