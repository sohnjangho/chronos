"""로그인한 사용자와 관리자 확인 의존성."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.security.tokens import read_token
from app.store.tables import User

_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    user_id = read_token(credentials.credentials) if credentials else None
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise ApiError(401, "unauthorized", "다시 로그인해 주세요.")
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise ApiError(403, "admin_only", "관리자만 할 수 있습니다.")
    return user
