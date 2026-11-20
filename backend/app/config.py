import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """환경 변수에서 읽는 설정. 만들 때마다 현재 환경을 읽는다."""

    admin_id: str = field(default_factory=lambda: _env("CHRONOS_ADMIN_ID", "admin"))
    admin_password: str = field(default_factory=lambda: _env("CHRONOS_ADMIN_PASSWORD"))
    secret_key: str = field(default_factory=lambda: _env("CHRONOS_SECRET_KEY"))
    data_dir: Path = field(
        default_factory=lambda: Path(_env("CHRONOS_DATA_DIR", "./data"))
    )
    # 뜻 검색 벡터 저장소(Qdrant 서버). 빈 값이면 뜻 검색을 끄고 낱말 검색만(시험이 이렇게 둔다).
    qdrant_url: str = field(default_factory=lambda: _env("CHRONOS_QDRANT_URL", "http://127.0.0.1:6333"))


# .env.example 에 적힌 예시 값 — 그대로 쓰면 누구나 아는 값이라 막는다.
EXAMPLE_SECRET_KEY = "change-me-to-a-long-random-string"
EXAMPLE_ADMIN_PASSWORD = "change-me"
MIN_SECRET_KEY_CHARS = 32
MIN_ADMIN_PASSWORD_CHARS = 8
MAX_ADMIN_PASSWORD_BYTES = 72  # bcrypt 가 받는 최대 길이


class ConfigError(Exception):
    """설정이 안전하지 않아 서버를 띄우지 않는다."""


def validate_settings(s: Settings) -> None:
    """약한 설정이면 변수 이름을 담은 한국어 메시지로 ConfigError 를 낸다."""
    if not s.admin_id:
        raise ConfigError("CHRONOS_ADMIN_ID 가 비어 있습니다. .env 에 관리자 아이디를 넣어 주세요.")
    if len(s.secret_key) < MIN_SECRET_KEY_CHARS or s.secret_key == EXAMPLE_SECRET_KEY:
        raise ConfigError(
            "CHRONOS_SECRET_KEY 는 예시 값이 아닌 32자 이상이어야 합니다. "
            "예: openssl rand -hex 32 의 출력"
        )
    password = s.admin_password
    if (
        len(password) < MIN_ADMIN_PASSWORD_CHARS
        or len(password.encode()) > MAX_ADMIN_PASSWORD_BYTES
        or password == EXAMPLE_ADMIN_PASSWORD
    ):
        raise ConfigError(
            "CHRONOS_ADMIN_PASSWORD 는 예시 값이 아닌 8자 이상, 72바이트 이하여야 합니다."
        )
