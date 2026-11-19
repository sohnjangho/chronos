from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.auth import service
from app.programs.auth.schemas import (
    AccountOut,
    LoginIn,
    LoginOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security.deps import current_user, require_admin
from app.security.tokens import issue_token
from app.store.tables import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)


@router.post("/login")
def login(body: LoginIn, session: SessionDep) -> LoginOut:
    user = service.authenticate(session, body.login_id, body.password)
    return LoginOut(token=issue_token(user.id), user=UserOut.model_validate(user))


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/users", dependencies=[AdminOnly])
def list_users(session: SessionDep) -> list[AccountOut]:
    return [AccountOut.model_validate(u) for u in service.list_users(session)]


@router.post("/users", status_code=201, dependencies=[AdminOnly])
def create_user(body: UserCreate, session: SessionDep) -> AccountOut:
    return AccountOut.model_validate(service.create_user(session, body))


@router.patch("/users/{user_id}", dependencies=[AdminOnly])
def update_user(user_id: int, body: UserUpdate, session: SessionDep) -> AccountOut:
    return AccountOut.model_validate(service.update_user(session, user_id, body))
