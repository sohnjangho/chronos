from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.security.passwords import MAX_PASSWORD_BYTES

Role = Literal["admin", "user", "field"]
SignupRole = Literal["user", "field"]
AccountStatus = Literal["pending", "active", "rejected", "disabled"]


def _fits_bcrypt(password: str) -> str:
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"비밀번호는 {MAX_PASSWORD_BYTES}바이트를 넘을 수 없습니다.")
    return password


def _valid_email(value: str) -> str:
    v = value.strip()
    local, sep, domain = v.partition("@")
    if not sep or not local or "." not in domain or any(ch.isspace() for ch in v):
        raise ValueError("올바른 이메일 주소를 입력해 주세요.")
    return v


NewPassword = Annotated[str, Field(min_length=1), AfterValidator(_fits_bcrypt)]
SignupPassword = Annotated[str, Field(min_length=4), AfterValidator(_fits_bcrypt)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Email = Annotated[str, Field(min_length=3, max_length=120), AfterValidator(_valid_email)]


DeviceKind = Literal["desktop", "tablet", "phone"]
DeviceKey = Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class LoginIn(BaseModel):
    login_id: str
    password: Annotated[str, Field(min_length=1)]
    # 이 브라우저의 기기 열쇠(화면이 만든 임의 값)와 모양. 없으면 서버가 열쇠를 만들고 모양은 User-Agent 로 짐작한다
    device_key: DeviceKey | None = None
    kind: DeviceKind | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: Role


class AccountOut(UserOut):
    """관리자가 보는 계정 목록 한 줄."""

    login_id: str
    status: AccountStatus = "active"
    email: str | None = None
    phone: str | None = None
    organization: str | None = None
    department: str | None = None
    note: str | None = None
    created_at: datetime | None = None


class LoginOut(BaseModel):
    token: str
    user: UserOut


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    login_id: Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$")]
    password: SignupPassword
    name: Name
    role: SignupRole = "user"
    email: Email
    phone: str | None = Field(default=None, max_length=40)
    organization: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=200)


class SignupOut(BaseModel):
    id: int
    login_id: str
    name: str
    role: SignupRole
    status: AccountStatus
    message: str


class UserCreate(BaseModel):
    login_id: Annotated[str, Field(min_length=1, max_length=50)]
    name: Name
    role: Role
    password: NewPassword
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    organization: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=200)


class UserUpdate(BaseModel):
    name: Name | None = None
    role: Role | None = None
    status: AccountStatus | None = None
    password: NewPassword | None = None
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    organization: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=200)


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    password: NewPassword | None = None
