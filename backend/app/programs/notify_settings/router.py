"""알림 연결 API(계획 4 Task 70). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.
상태(`/status`)만 로그인한 관리자·사용자, 나머지는 관리자. DB 만 쓰는 길은 동기 함수(스레드에서 돈다), 제공사를 부르는 길은
async 이고 DB 일은 service·diagnose 가 스레드에서 한다."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.notify_settings import blocked, diagnose, service
from app.programs.notify_settings.schemas import (
    BlockedOut,
    BlockIn,
    ConnectionCreate,
    ConnectionOut,
    ConnectionSaved,
    ConnectionTestIn,
    ConnectionUpdate,
    DiagnoseIn,
    DiagnosisOut,
    LimitsOut,
    ProbeOut,
    StatusOut,
)
from app.security.deps import require_admin, require_contacts
from app.store.tables import User

router = APIRouter(prefix="/api/notify", tags=["notify"])

SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)
Admin = Annotated[User, Depends(require_admin)]


@router.get("/connections", dependencies=[AdminOnly])
def list_connections(session: SessionDep) -> list[ConnectionOut]:
    return service.list_out(session)


@router.post("/connections/test", dependencies=[AdminOnly])
async def test_new_connection(body: ConnectionTestIn, session: SessionDep) -> ProbeOut:
    return await service.test_new(session, body)


@router.post("/connections", status_code=201, dependencies=[AdminOnly])
async def create_connection(body: ConnectionCreate, session: SessionDep) -> ConnectionSaved:
    return await service.create(session, body)


@router.patch("/connections/{conn_id}", dependencies=[AdminOnly])
async def update_connection(conn_id: int, body: ConnectionUpdate, session: SessionDep) -> ConnectionSaved:
    return await service.update(session, conn_id, body)


@router.post("/connections/{conn_id}/test", dependencies=[AdminOnly])
async def retest_connection(conn_id: int, session: SessionDep) -> ProbeOut:
    return await service.retest(session, conn_id)


@router.delete("/connections/{conn_id}", status_code=204, dependencies=[AdminOnly])
def delete_connection(conn_id: int, session: SessionDep) -> Response:
    service.delete_connection(session, conn_id)
    return Response(status_code=204)


@router.get("/connections/{conn_id}/limits", dependencies=[AdminOnly])
def get_limits(conn_id: int, session: SessionDep) -> LimitsOut:
    return service.limits_out(service.get(session, conn_id))


@router.put("/connections/{conn_id}/limits", dependencies=[AdminOnly])
def put_limits(conn_id: int, body: Annotated[dict[str, Any], Body()], session: SessionDep) -> LimitsOut:
    return service.put_limits(session, conn_id, body)


@router.post("/connections/{conn_id}/limits/reset", dependencies=[AdminOnly])
def reset_limits(conn_id: int, session: SessionDep) -> LimitsOut:
    return service.reset_limits(session, conn_id)


@router.post("/connections/{conn_id}/diagnose")
async def run_diagnosis(conn_id: int, body: DiagnoseIn, session: SessionDep, user: Admin) -> DiagnosisOut:
    return await diagnose.run(session, conn_id, body, user.name)


@router.get("/connections/{conn_id}/diagnosis", dependencies=[AdminOnly])
def last_diagnosis(conn_id: int, session: SessionDep) -> DiagnosisOut | None:
    return diagnose.last(session, conn_id)


@router.get("/status")
def notify_status(session: SessionDep, _user: Annotated[User, Depends(require_contacts)]) -> StatusOut:
    return service.status(session)


@router.get("/blocked", dependencies=[AdminOnly])
def list_blocked(session: SessionDep) -> list[BlockedOut]:
    return blocked.list_blocked(session)


@router.post("/blocked", status_code=201)
def block_number(body: BlockIn, session: SessionDep, user: Admin) -> BlockedOut:
    return blocked.add(session, body, user)


@router.delete("/blocked/{blocked_id}", status_code=204, dependencies=[AdminOnly])
def unblock_number(blocked_id: int, session: SessionDep) -> Response:
    blocked.remove(session, blocked_id)
    return Response(status_code=204)
