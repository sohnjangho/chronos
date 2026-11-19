from pathlib import Path

from app.config import Settings


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
