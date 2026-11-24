"""접속 신호와 관리자의 기기 목록·기기 로그아웃."""

import logging

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.presence.schemas import AccountPresenceOut, DeviceOut
from app.security.tokens import issue_token
from app.store import devices
from app.store.devices import UserDevice
from app.store.tables import User
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

OWN_DEVICE_MESSAGE = "지금 쓰고 있는 이 기기입니다. 로그아웃하면 바로 로그인 화면으로 갑니다."


def heartbeat(session: Session, user: User, device_id: int | None, device_key: str, kind: str, ua: str) -> str | None:
    """마지막 접속을 고친다. 기기 세션 전에 받은 토큰이면 이 브라우저의 기기 줄을 열고 그 줄에 묶인 새 토큰을 준다."""
    if device_id is not None:
        row = devices.active_device(session, device_id, user.id)
        if row is not None:  # current_user 가 방금 본 줄
            devices.touch(session, row, kind, ua)
            return None
    row = devices.open_device(session, user.id, device_key, kind, ua)
    return issue_token(user.id, row.id)


def _device_out(row: UserDevice, now, current_id: int | None) -> DeviceOut:
    return DeviceOut(
        id=row.id, kind=row.kind, browser=row.browser, os=row.os, online=devices.is_online(row, now),
        revoked=row.revoked_at is not None, current=row.id == current_id, created_at=as_utc(row.created_at),
        last_seen_at=as_utc(row.last_seen_at), revoked_at=as_utc(row.revoked_at) if row.revoked_at else None,
    )


def accounts(session: Session, current_id: int | None) -> list[AccountPresenceOut]:
    now = devices.utcnow()
    grouped: dict[int, list[DeviceOut]] = {}
    for row in devices.visible_devices(session):
        grouped.setdefault(row.user_id, []).append(_device_out(row, now, current_id))
    return [
        AccountPresenceOut(
            user_id=uid,
            online=any(d.online for d in rows),
            last_seen_at=max(d.last_seen_at for d in rows),
            devices=rows,
        )
        for uid, rows in grouped.items()
    ]


def logout_device(session: Session, device_id: int, actor: User, actor_device_id: int | None, confirm_self: bool) -> DeviceOut:
    row = session.get(UserDevice, device_id)
    if row is None:
        raise ApiError(404, "device_not_found", "기기를 찾을 수 없습니다.")
    if row.id == actor_device_id and not confirm_self:
        raise ApiError(409, "own_device", OWN_DEVICE_MESSAGE)
    was_open = row.revoked_at is None
    devices.revoke(session, row, actor.id)
    if was_open:
        logger.info("기기 로그아웃: 관리자 %s → 사용자 %s · 기기 %s", actor.id, row.user_id, row.id)
    return _device_out(row, devices.utcnow(), actor_device_id)
