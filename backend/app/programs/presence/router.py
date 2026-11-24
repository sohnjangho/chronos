"""접속 신호(로그인한 누구나)와 계정별 접속 상태·기기 로그아웃(관리자만)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.presence import service
from app.programs.presence.schemas import (
    AccountPresenceOut,
    DeviceLogoutIn,
    DeviceOut,
    PresenceIn,
    PresenceOut,
)
from app.security.deps import current_user, require_admin
from app.store.tables import User

SessionDep = Annotated[Session, Depends(get_session)]

me_router = APIRouter(prefix="/api/me", tags=["presence"])
admin_router = APIRouter(prefix="/api/admin", tags=["presence"])


def _device_id(request: Request) -> int | None:
    return getattr(request.state, "device_id", None)


@me_router.post("/presence")
def presence(body: PresenceIn, request: Request, session: SessionDep,
             user: Annotated[User, Depends(current_user)]) -> PresenceOut:
    token = service.heartbeat(session, user, _device_id(request), body.device_key, body.kind,
                              request.headers.get("user-agent", ""))
    return PresenceOut(token=token)


@admin_router.get("/accounts/devices")
def account_devices(request: Request, session: SessionDep,
                    _admin: Annotated[User, Depends(require_admin)]) -> list[AccountPresenceOut]:
    return service.accounts(session, _device_id(request))


@admin_router.post("/devices/{device_id}/logout")
def logout_device(device_id: int, body: DeviceLogoutIn, request: Request, session: SessionDep,
                  admin: Annotated[User, Depends(require_admin)]) -> DeviceOut:
    return service.logout_device(session, device_id, admin, _device_id(request), body.confirm_self)
