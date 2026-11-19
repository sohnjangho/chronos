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
