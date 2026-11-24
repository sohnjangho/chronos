from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.devconsole import (
    catalog,
    outreach_view,
    points_view,
    service,
    updates,
)
from app.programs.devconsole.schemas import (
    AgentConfigOut,
    AgentConfigPatch,
    DevUsageOut,
    HealthOut,
    OutreachDetailOut,
    OutreachListOut,
    PointsConfigOut,
    PointsConfigPatch,
    PointsStageOut,
    StopTurnOut,
    ToolToggleIn,
    ToolToggleOut,
    TurnDetail,
    TurnOut,
    UpdatesOut,
    UsageGroup,
)
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


@router.get("/outreach")
def list_outreach(
    session: SessionDep, kind: Literal["message", "call"] | None = None,
    limit: Annotated[int, Query(ge=1, le=outreach_view.LIST_MAX)] = outreach_view.LIST_DEFAULT,
) -> OutreachListOut:
    return outreach_view.list_rows(session, kind, limit)


@router.get("/outreach/{kind}/{row_id}")
def get_outreach(kind: Literal["message", "call"], row_id: int, session: SessionDep) -> OutreachDetailOut:
    return outreach_view.detail(session, kind, row_id)


@router.get("/usage")
def read_usage(
    session: SessionDep, days: Annotated[int, Query(ge=1, le=90)] = 14, group: UsageGroup = "model",
) -> DevUsageOut:
    return service.usage(session, days=days, group=group)


@router.get("/catalog")
def read_catalog(session: SessionDep) -> dict[str, Any]:
    return catalog.get_catalog(session)


@router.post("/harness/{rule_id}/test")
def test_harness_rule(rule_id: str, session: SessionDep, broken: bool = False) -> dict[str, Any]:
    return catalog.run_harness_test(rule_id, session, broken)  # broken: 연락 하네스 칸을 지키는 곳을 끄고(자식 안에서만)


@router.get("/agent-config")
def read_agent_config(session: SessionDep) -> AgentConfigOut:
    return AgentConfigOut.model_validate(settings_store.get_agent_config(session))


@router.put("/agent-config")
def write_agent_config(body: AgentConfigPatch, session: SessionDep) -> AgentConfigOut:
    updated = settings_store.set_agent_config(session, body.model_dump(exclude_unset=True))
    return AgentConfigOut.model_validate(updated)


@router.get("/points-config")
def read_points_config(session: SessionDep) -> PointsConfigOut:
    return points_view.config(session)


@router.put("/points-config")
def write_points_config(body: PointsConfigPatch, session: SessionDep) -> PointsConfigOut:
    return points_view.save(session, body.model_dump(exclude_none=True))


@router.get("/points-runs")
def list_points_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=points_view.RUNS_MAX)] = points_view.RUNS_DEFAULT,
) -> list[PointsStageOut]:
    return points_view.runs(session, limit)  # 관리 포인트 차이(버전 바뀜·가정), 새것부터 — 턴 밖에서 바뀐 것도


@router.get("/health")
def read_health(session: SessionDep) -> HealthOut:
    return service.health(session)


@router.get("/updates")
def read_updates() -> UpdatesOut:
    return updates.listing()  # deploy/updates.jsonl 새것부터 + 지금 실서버 판(켤 때 읽은 커밋)


@router.post("/turns/{chat_id}/stop")
def stop_active_turn(chat_id: int) -> StopTurnOut:
    return service.stop_turn(chat_id)


@router.put("/tools/{tool_name}")
def toggle_tool(tool_name: str, body: ToolToggleIn, session: SessionDep) -> ToolToggleOut:
    return service.toggle_tool(session, tool_name, body.enabled)
