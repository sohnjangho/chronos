from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.programs.auth.schemas import DeviceKey, DeviceKind


class PresenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_key: DeviceKey
    kind: DeviceKind


class PresenceOut(BaseModel):
    # 기기 세션 전에 받은 토큰으로 부르면 이 기기에 묶인 새 토큰(화면이 바꿔 낀다). 이미 묶인 토큰이면 null
    token: str | None = None


class DeviceOut(BaseModel):
    """관리자가 보는 기기 한 줄. device_key 는 내보내지 않는다."""

    id: int
    kind: str
    browser: str
    os: str
    online: bool
    revoked: bool
    current: bool  # 부른 관리자가 지금 쓰는 이 기기
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None


class AccountPresenceOut(BaseModel):
    """계정 하나의 접속 상태. 보일 기기(30일 안)가 있는 계정만 나온다."""

    user_id: int
    online: bool
    last_seen_at: datetime
    devices: list[DeviceOut]


class DeviceLogoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_self: bool = False  # 지금 쓰는 이 기기를 닫는다는 확인
