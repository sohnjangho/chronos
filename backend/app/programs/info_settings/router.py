from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.info_settings import service
from app.programs.info_settings.schemas import (
    InfoConnectionCreate,
    InfoConnectionOut,
    InfoConnectionUpdate,
    InfoTestOut,
    TemplateOut,
)
from app.security.deps import require_admin

router = APIRouter(prefix="/api/info", tags=["info"])

SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)


@router.get("/connections", dependencies=[AdminOnly])
def list_connections(session: SessionDep) -> list[InfoConnectionOut]:
    return [InfoConnectionOut.model_validate(c) for c in service.list_connections(session)]


@router.post("/connections", status_code=201, dependencies=[AdminOnly])
def create_connection(body: InfoConnectionCreate, session: SessionDep) -> InfoConnectionOut:
    return InfoConnectionOut.model_validate(service.create_connection(session, body))


@router.patch("/connections/{conn_id}", dependencies=[AdminOnly])
def update_connection(conn_id: int, body: InfoConnectionUpdate, session: SessionDep) -> InfoConnectionOut:
    return InfoConnectionOut.model_validate(service.update_connection(session, conn_id, body))


@router.delete("/connections/{conn_id}", status_code=204, dependencies=[AdminOnly])
def delete_connection(conn_id: int, session: SessionDep) -> Response:
    service.delete_connection(session, conn_id)
    return Response(status_code=204)


@router.post("/connections/{conn_id}/test", dependencies=[AdminOnly])
async def test_connection(conn_id: int, session: SessionDep) -> InfoTestOut:
    return await service.test_connection(session, conn_id)


@router.get("/templates", dependencies=[AdminOnly])
def list_templates() -> list[TemplateOut]:
    return service.list_templates()
