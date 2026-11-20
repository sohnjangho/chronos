from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.llm.connections import ProbeResult
from app.programs.llm_settings import service
from app.programs.llm_settings.schemas import (
    AssignmentsIn,
    AssignmentsOut,
    ConnectionCreate,
    ConnectionOut,
    ConnectionSaved,
    ConnectionTestIn,
    ConnectionUpdate,
    ModelsOut,
    ProbeOut,
    StatusOut,
)
from app.security.deps import current_user, require_admin
from app.store.tables import LlmConnection

router = APIRouter(prefix="/api/llm", tags=["llm"])

SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)


def _probe_out(result: ProbeResult) -> ProbeOut:
    return ProbeOut.model_validate(asdict(result))


def _out(conn: LlmConnection) -> ConnectionOut:
    out = ConnectionOut.model_validate(conn)
    out.chat_model_count = service.chat_model_count(conn)
    return out


def _saved(conn: LlmConnection, result: ProbeResult | None) -> ConnectionSaved:
    out = ConnectionSaved.model_validate(conn)
    out.chat_model_count = service.chat_model_count(conn)
    if result is not None and result.error is not None:
        out.error = _probe_out(result).error
    return out


@router.get("/connections", dependencies=[AdminOnly])
def list_connections(session: SessionDep) -> list[ConnectionOut]:
    return [_out(c) for c in service.list_connections(session)]


@router.post("/connections/test", dependencies=[AdminOnly])
def test_new_connection(body: ConnectionTestIn) -> ProbeOut:
    return _probe_out(service.test_connection(body))


@router.post("/connections", status_code=201, dependencies=[AdminOnly])
def create_connection(body: ConnectionCreate, session: SessionDep) -> ConnectionSaved:
    return _saved(*service.create_connection(session, body))


@router.patch("/connections/{conn_id}", dependencies=[AdminOnly])
def update_connection(
    conn_id: int, body: ConnectionUpdate, session: SessionDep
) -> ConnectionSaved:
    return _saved(*service.update_connection(session, conn_id, body))


@router.post("/connections/{conn_id}/test", dependencies=[AdminOnly])
def retest_connection(conn_id: int, session: SessionDep) -> ProbeOut:
    return _probe_out(service.retest_connection(session, conn_id))


@router.get("/connections/{conn_id}/models", dependencies=[AdminOnly])
def connection_models(conn_id: int, session: SessionDep) -> ModelsOut:
    return ModelsOut(models=service.connection_models(session, conn_id))


@router.delete("/connections/{conn_id}", status_code=204, dependencies=[AdminOnly])
def delete_connection(conn_id: int, session: SessionDep) -> Response:
    service.delete_connection(session, conn_id)
    return Response(status_code=204)


@router.get("/assignments", dependencies=[AdminOnly])
def get_assignments(session: SessionDep) -> AssignmentsOut:
    return AssignmentsOut(items=service.get_assignments(session))


@router.put("/assignments", dependencies=[AdminOnly])
def put_assignments(body: AssignmentsIn, session: SessionDep) -> AssignmentsOut:
    service.put_assignments(session, body)
    return AssignmentsOut(items=service.get_assignments(session))


@router.get("/status", dependencies=[Depends(current_user)])
def llm_status(session: SessionDep) -> StatusOut:
    return service.status(session)
