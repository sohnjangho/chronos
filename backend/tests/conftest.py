import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def test_env(monkeypatch, tmp_path):
    """시험은 실제 .env 없이 자기 값만 쓴다."""
    monkeypatch.setenv("CHRONOS_ADMIN_ID", "admin")
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "test-pass")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
