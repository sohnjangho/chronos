from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings, validate_settings
from app.main import app


def test_settings_read_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_ADMIN_ID", "boss")
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "key")
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(tmp_path))
    s = Settings()
    assert (s.admin_id, s.admin_password, s.secret_key) == ("boss", "pw", "key")
    assert s.data_dir == tmp_path


def test_data_dir_defaults_to_local_data(monkeypatch):
    monkeypatch.delenv("CHRONOS_DATA_DIR", raising=False)
    assert Settings().data_dir == Path("./data")


STRONG_KEY = "k" * 32
REJECTED = [
    ("CHRONOS_SECRET_KEY", ""),
    ("CHRONOS_SECRET_KEY", "k" * 31),
    ("CHRONOS_SECRET_KEY", "change-me-to-a-long-random-string"),
    ("CHRONOS_ADMIN_PASSWORD", ""),
    ("CHRONOS_ADMIN_PASSWORD", "change-me"),
    ("CHRONOS_ADMIN_PASSWORD", "short7!"),
    ("CHRONOS_ADMIN_PASSWORD", "가" * 25),  # 75바이트
    ("CHRONOS_ADMIN_ID", ""),
]


@pytest.mark.parametrize(("name", "value"), REJECTED)
def test_weak_settings_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        validate_settings(Settings())


def test_app_refuses_to_start_with_weak_settings(monkeypatch):
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "")
    with pytest.raises(ConfigError, match="CHRONOS_SECRET_KEY"), TestClient(app):
        pass


def test_valid_settings_start_normally(monkeypatch):
    monkeypatch.setenv("CHRONOS_SECRET_KEY", STRONG_KEY)
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "12345678")
    validate_settings(Settings())
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
