"""로그인과 계정 관리."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.auth.schemas import MeUpdate, UserCreate, UserUpdate
from app.security.passwords import hash_password, verify_password
from app.store.tables import User


def authenticate(session: Session, login_id: str, password: str) -> User:
    user = session.scalar(select(User).where(User.login_id == login_id))
    if user is None or not verify_password(password, user.password_hash):
        raise ApiError(401, "bad_credentials", "아이디 또는 비밀번호가 맞지 않습니다.")
    return user


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


def create_user(session: Session, data: UserCreate) -> User:
    if session.scalar(select(User).where(User.login_id == data.login_id)):
        raise ApiError(409, "login_id_taken", "이미 있는 아이디입니다.")
    user = User(
        login_id=data.login_id,
        name=data.name,
        role=data.role,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    session.commit()
    return user


def _admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).where(User.role == "admin")) or 0


def update_user(session: Session, user_id: int, data: UserUpdate) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "계정을 찾을 수 없습니다.")
    if user.role == "admin" and data.role is not None and data.role != "admin" and _admin_count(session) == 1:
        raise ApiError(422, "last_admin", "관리자가 한 명은 있어야 합니다.")
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    session.commit()
    return user


def update_me(session: Session, user: User, data: MeUpdate) -> User:
    """로그인한 사용자 본인의 이름·비밀번호만 바꾼다."""
    if data.name is not None:
        user.name = data.name
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    session.commit()
    return user
