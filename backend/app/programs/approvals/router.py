from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.approvals import service
from app.programs.approvals.schemas import (
    ApprovalDetail,
    ApprovalList,
    CountOut,
    DecideIn,
    DecideOut,
    ModeIO,
)
from app.security.deps import current_user, require_admin
from app.store.tables import User

# 승인함은 팀이 같이 쓴다: 로그인한 누구나 보고 결정한다.
router = APIRouter(prefix="/api/approvals", tags=["approvals"], dependencies=[Depends(current_user)])
# 승인 수준: 누구나 읽고, 관리자만 바꾼다.
settings_router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("")
def list_approvals(session: SessionDep, status: Literal["pending", "decided", "auto"] = "pending") -> ApprovalList:
    return service.list_approvals(session, status)


@router.get("/count")
def count_pending(session: SessionDep) -> CountOut:
    return service.count(session)


@router.get("/{approval_id}")
def read_approval(approval_id: int, session: SessionDep) -> ApprovalDetail:
    return service.detail(session, approval_id)


@router.post("/{approval_id}/decide")
def decide(approval_id: int, body: DecideIn, session: SessionDep, user: UserDep) -> DecideOut:
    return service.decide(session, approval_id, body, user)


@settings_router.get("/approval")
def read_approval_mode(session: SessionDep) -> ModeIO:
    return service.get_mode(session)


@settings_router.put("/approval", dependencies=[Depends(require_admin)])
def update_approval_mode(body: ModeIO, session: SessionDep) -> ModeIO:
    return service.put_mode(session, body)
