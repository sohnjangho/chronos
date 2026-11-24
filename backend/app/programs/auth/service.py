"""로그인과 계정 관리."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.auth.schemas import MeUpdate, SignupIn, UserCreate, UserUpdate
from app.security.passwords import hash_password, verify_password
from app.store import devices
from app.store.devices import UserDevice
from app.store.tables import User


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def authenticate(session: Session, login_id: str, password: str) -> User:
    user = session.scalar(select(User).where(User.login_id == login_id))
    if user is None or not verify_password(password, user.password_hash):
        raise ApiError(401, "bad_credentials", "아이디 또는 비밀번호가 맞지 않습니다.")
    if user.status == "pending":
        raise ApiError(403, "account_pending", "관리자 승인 대기 중인 계정입니다. 승인 완료 후 로그인해 주세요.")
    if user.status == "rejected":
        raise ApiError(403, "account_rejected", "가입 신청이 거절된 계정입니다. 관리자에게 문의해 주세요.")
    if user.status != "active":
        raise ApiError(403, "account_disabled", "비활성화된 계정입니다. 관리자에게 문의해 주세요.")
    return user


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


def signup_user(session: Session, data: SignupIn) -> User:
    """공개 회원가입 신청: status='pending'으로 저장해 관리자 승인 전까지 로그인을 막는다."""
    if session.scalar(select(User).where(User.login_id == data.login_id)):
        raise ApiError(409, "login_id_taken", "이미 있는 아이디입니다.")
    user = User(
        login_id=data.login_id,
        name=data.name,
        role=data.role,
        status="pending",
        email=_clean(data.email),
        phone=_clean(data.phone),
        organization=_clean(data.organization),
        department=_clean(data.department),
        note=_clean(data.note),
        password_hash=hash_password(data.password),
    )
    session.add(user)
    session.commit()
    return user


def create_user(session: Session, data: UserCreate) -> User:
    if session.scalar(select(User).where(User.login_id == data.login_id)):
        raise ApiError(409, "login_id_taken", "이미 있는 아이디입니다.")
    user = User(
        login_id=data.login_id,
        name=data.name,
        role=data.role,
        status="active",
        email=_clean(data.email),
        phone=_clean(data.phone),
        organization=_clean(data.organization),
        department=_clean(data.department),
        note=_clean(data.note),
        password_hash=hash_password(data.password),
    )
    session.add(user)
    session.commit()
    return user


def _admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).where(User.role == "admin", User.status == "active")) or 0


def update_user(session: Session, user_id: int, data: UserUpdate) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "계정을 찾을 수 없습니다.")
    next_role = data.role if data.role is not None else user.role
    next_status = data.status if data.status is not None else user.status
    if user.role == "admin" and user.status == "active" and (next_role != "admin" or next_status != "active") and _admin_count(session) == 1:
        raise ApiError(422, "last_admin", "관리자가 한 명은 있어야 합니다.")
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.status is not None:
        user.status = data.status
    if data.email is not None:
        user.email = _clean(data.email)
    if data.phone is not None:
        user.phone = _clean(data.phone)
    if data.organization is not None:
        user.organization = _clean(data.organization)
    if data.department is not None:
        user.department = _clean(data.department)
    if data.note is not None:
        user.note = _clean(data.note)
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    session.commit()
    return user


def delete_user(session: Session, user_id: int, actor: User) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "계정을 찾을 수 없습니다.")
    if user.id == actor.id:
        raise ApiError(422, "cannot_delete_self", "본인 계정은 삭제할 수 없습니다.")
    if user.role == "admin" and user.status == "active" and _admin_count(session) == 1:
        raise ApiError(422, "last_admin", "관리자가 한 명은 있어야 합니다.")
    devices.revoke_all(session, user.id, actor.id)  # 기기 줄은 감사 기록으로 남기고 닫는다
    session.delete(user)
    session.commit()


def logout_device(session: Session, user: User, device_id: int) -> None:
    """본인 로그아웃: 지금 기기 줄을 닫는다(revoked_by = 본인). current_user 가 방금 열린 줄임을 확인했다."""
    row = session.get(UserDevice, device_id)
    if row is not None:
        devices.revoke(session, row, user.id)


def update_me(session: Session, user: User, data: MeUpdate) -> User:
    """로그인한 사용자 본인의 이름·비밀번호만 바꾼다."""
    if data.name is not None:
        user.name = data.name
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    session.commit()
    return user
