from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.auth import service
from app.programs.auth.schemas import (
    AccountOut,
    LoginIn,
    LoginOut,
    MeUpdate,
    SignupIn,
    SignupOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security.deps import current_user, require_admin
from app.security.tokens import issue_token
from app.store import devices
from app.store.tables import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)


@router.post("/login")
def login(body: LoginIn, request: Request, session: SessionDep) -> LoginOut:
    user = service.authenticate(session, body.login_id, body.password)
    device = devices.open_device(session, user.id, body.device_key, body.kind, request.headers.get("user-agent", ""))
    return LoginOut(token=issue_token(user.id, device.id), user=UserOut.model_validate(user))


@router.post("/signup", status_code=201)
def signup(body: SignupIn, session: SessionDep) -> SignupOut:
    user = service.signup_user(session, body)
    return SignupOut(
        id=user.id,
        login_id=user.login_id,
        name=user.name,
        role=user.role,
        status=user.status,
        message="회원가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    )


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me")
def update_me(body: MeUpdate, session: SessionDep, user: Annotated[User, Depends(current_user)]) -> UserOut:
    return UserOut.model_validate(service.update_me(session, user, body))


@router.get("/users", dependencies=[AdminOnly])
def list_users(session: SessionDep) -> list[AccountOut]:
    return [AccountOut.model_validate(u) for u in service.list_users(session)]


@router.post("/users", status_code=201, dependencies=[AdminOnly])
def create_user(body: UserCreate, session: SessionDep) -> AccountOut:
    return AccountOut.model_validate(service.create_user(session, body))


@router.patch("/users/{user_id}", dependencies=[AdminOnly])
def update_user(user_id: int, body: UserUpdate, session: SessionDep) -> AccountOut:
    return AccountOut.model_validate(service.update_user(session, user_id, body))


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, session: SessionDep, actor: Annotated[User, AdminOnly]) -> None:
    service.delete_user(session, user_id, actor)
