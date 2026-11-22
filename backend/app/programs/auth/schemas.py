from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.security.passwords import MAX_PASSWORD_BYTES

Role = Literal["admin", "user", "field"]


def _fits_bcrypt(password: str) -> str:
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"비밀번호는 {MAX_PASSWORD_BYTES}바이트를 넘을 수 없습니다.")
    return password


NewPassword = Annotated[str, Field(min_length=1), AfterValidator(_fits_bcrypt)]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class LoginIn(BaseModel):
    login_id: str
    password: Annotated[str, Field(min_length=1)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: Role


class AccountOut(UserOut):
    """관리자가 보는 계정 목록 한 줄."""

    login_id: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    login_id: Annotated[str, Field(min_length=1, max_length=50)]
    name: Name
    role: Role
    password: NewPassword


class UserUpdate(BaseModel):
    name: Name | None = None
    role: Role | None = None
    password: NewPassword | None = None


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    password: NewPassword | None = None
