"""로그인한 사용자와 관리자 확인 의존성."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.security.tokens import read_claims
from app.store.devices import active_device
from app.store.messages import FIELD_READ_ONLY_MESSAGE
from app.store.tables import User

_bearer = HTTPBearer(auto_error=False)
FIELD_NO_CONTACTS_MESSAGE = "현장 관리자는 연락처를 열 수 없습니다."
DEVICE_LOGGED_OUT_MESSAGE = "이 기기는 로그아웃되었습니다. 다시 로그인해 주세요."


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    """토큰의 사용자. 토큰에 기기 세션(sid)이 있으면 그 줄이 닫히지 않았는지도 본다(기본 키로 한 번) — 그 sid 는
    request.state.device_id 에 둔다(없으면 None: 기기 세션 전에 받은 토큰)."""
    claims = read_claims(credentials.credentials) if credentials else None
    user = session.get(User, claims[0]) if claims is not None else None
    if user is None or user.status != "active":
        raise ApiError(401, "unauthorized", "다시 로그인해 주세요.")
    device_id = claims[1] if claims else None
    if device_id is not None and active_device(session, device_id, user.id) is None:
        raise ApiError(401, "device_logged_out", DEVICE_LOGGED_OUT_MESSAGE)
    request.state.device_id = device_id
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise ApiError(403, "admin_only", "관리자만 할 수 있습니다.")
    return user


def require_editor(user: Annotated[User, Depends(current_user)]) -> User:
    """일정 쓰기·승인 결정·상신. 현장 관리자(field)는 읽고 현장 회신·지연 기록만 남긴다(F4). 사용자·관리자는 그대로."""
    if user.role == "field":
        raise ApiError(403, "field_read_only", FIELD_READ_ONLY_MESSAGE)
    return user


def require_contacts(user: Annotated[User, Depends(current_user)]) -> User:
    """연락처·연락 기록(계획 4). 현장 관리자(field)는 주소록을 열 수 없다. 관리자·사용자는 그대로."""
    if user.role == "field":
        raise ApiError(403, "field_no_contacts", FIELD_NO_CONTACTS_MESSAGE)
    return user
