"""chronos 명령(app.cli)의 첫 실행: 데이터 폴더, 비밀 열쇠, 첫 관리자, 서버 설정."""

import os
import sqlite3
import stat

import pytest

from app import cli
from app.config import Settings, validate_settings
from app.security.passwords import verify_password


@pytest.fixture(autouse=True)
def no_admin_env(monkeypatch):
    """conftest 가 넣는 관리자 값을 지운다 — 판정자의 터미널처럼 처음엔 아무것도 없다."""
    monkeypatch.delenv("CHRONOS_ADMIN_ID", raising=False)
    monkeypatch.delenv("CHRONOS_ADMIN_PASSWORD", raising=False)


def _users(data_dir):
    with sqlite3.connect(data_dir / "chronos.db") as db:
        return db.execute("SELECT login_id, role, password_hash FROM users").fetchall()


def _no_prompt(*_a, **_k):
    raise AssertionError("묻지 않아야 한다")


def test_data_dir_option_env_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CHRONOS_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.data_dir_from(None) == tmp_path / ".chronos"
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(tmp_path / "env"))
    assert cli.data_dir_from(None) == tmp_path / "env"
    assert cli.data_dir_from(str(tmp_path / "opt")) == tmp_path / "opt"


def test_secret_key_created_private_and_reused(tmp_path):
    key = cli.secret_key(tmp_path)
    assert len(key) >= 32
    mode = stat.S_IMODE(os.stat(tmp_path / cli.SECRET_FILE).st_mode)
    assert mode == 0o600
    assert cli.secret_key(tmp_path) == key


def test_password_rules():
    assert cli.password_problem("short") is not None
    assert cli.password_problem("가" * 25) is not None  # 75바이트
    assert cli.password_problem("good-pass-1") is None


def test_ask_admin_hidden_with_confirm_and_retry():
    answers = iter(["short", "good-pass-1", "other-pass", "good-pass-1", "good-pass-1"])
    shown = []
    login_id, password = cli.ask_admin(
        ask=lambda _p: "  boss  ", ask_hidden=lambda _p: next(answers), say=shown.append, login_id=None,
    )
    assert (login_id, password) == ("boss", "good-pass-1")
    assert any("8자" in s for s in shown)
    assert any("같지 않" in s for s in shown)


def test_first_run_prompts_and_creates_admin(tmp_path):
    data = tmp_path / "data"
    hidden = iter(["good-pass-1", "good-pass-1"])
    args = cli.parse_args(["--data-dir", str(data), "--port", "18999"])
    env = cli.prepare(args, ask=lambda _p: "boss", ask_hidden=lambda _p: next(hidden), say=lambda _s: None)
    [(login_id, role, password_hash)] = _users(data)
    assert (login_id, role) == ("boss", "admin")
    assert verify_password("good-pass-1", password_hash)
    # 서버에 넘기는 값: 실제 비밀번호가 아니라 검사만 통과하는 버리는 값
    assert env["CHRONOS_ADMIN_ID"] == "boss"
    assert env["CHRONOS_ADMIN_PASSWORD"] != "good-pass-1"
    assert env["CHRONOS_DATA_DIR"] == str(data)
    assert env["CHRONOS_QDRANT_URL"] == ""
    assert env["CHRONOS_SECRET_KEY"] == (data / cli.SECRET_FILE).read_text().strip()


def test_prepared_env_passes_server_validation(tmp_path, monkeypatch):
    hidden = iter(["good-pass-1", "good-pass-1"])
    args = cli.parse_args(["--data-dir", str(tmp_path)])
    env = cli.prepare(args, ask=lambda _p: "boss", ask_hidden=lambda _p: next(hidden), say=lambda _s: None)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    validate_settings(Settings())


def test_second_run_reuses_admin_without_prompt(tmp_path):
    hidden = iter(["good-pass-1", "good-pass-1"])
    args = cli.parse_args(["--data-dir", str(tmp_path)])
    first = cli.prepare(args, ask=lambda _p: "boss", ask_hidden=lambda _p: next(hidden), say=lambda _s: None)
    again = cli.prepare(args, ask=_no_prompt, ask_hidden=_no_prompt, say=lambda _s: None)
    assert again["CHRONOS_ADMIN_ID"] == "boss"
    assert again["CHRONOS_SECRET_KEY"] == first["CHRONOS_SECRET_KEY"]
    assert len(_users(tmp_path)) == 1


def test_non_interactive_admin_from_option_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "env-pass-123")
    args = cli.parse_args(["--data-dir", str(tmp_path), "--admin-id", "judge", "--qdrant-url", "http://q:6333"])
    env = cli.prepare(args, ask=_no_prompt, ask_hidden=_no_prompt, say=lambda _s: None)
    [(login_id, _role, password_hash)] = _users(tmp_path)
    assert login_id == "judge"
    assert verify_password("env-pass-123", password_hash)
    assert env["CHRONOS_QDRANT_URL"] == "http://q:6333"


def test_non_interactive_bad_password_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "short")
    args = cli.parse_args(["--data-dir", str(tmp_path), "--admin-id", "judge"])
    with pytest.raises(SystemExit):
        cli.prepare(args, ask=_no_prompt, ask_hidden=_no_prompt, say=lambda _s: None)
    assert not (tmp_path / "chronos.db").exists()


def test_no_terminal_input_stops_with_hint(tmp_path, monkeypatch):
    def eof(_p):
        raise EOFError

    args = cli.parse_args(["--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as stop:
        cli.prepare(args, ask=eof, ask_hidden=eof, say=lambda _s: None)
    assert "--admin-id" in str(stop.value.code)


def test_defaults_and_korean_help(capsys):
    args = cli.parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 8210)
    with pytest.raises(SystemExit):
        cli.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "데이터 폴더" in out and "--admin-id" in out


def test_main_prints_url_and_serves(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "env-pass-123")
    served, said = [], []
    cli.main(
        ["--data-dir", str(tmp_path), "--admin-id", "judge", "--port", "18999"],
        serve=lambda host, port: served.append((host, port)), say=said.append,
    )
    assert served == [("127.0.0.1", 18999)]
    text = "\n".join(said)
    assert "http://127.0.0.1:18999" in text
    assert "설정" in text
    assert "env-pass-123" not in text
    assert os.environ["CHRONOS_SECRET_KEY"] not in text


def test_serve_plain_logs_and_web(monkeypatch):
    """로그 거르개가 메시지를 미리 펴 두므로 색 출력(color_message)을 쓰면 「%d」가 그대로 찍힌다 — 색을 끈다."""
    import uvicorn

    from app.main import app

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: seen.update(kw, target=target))
    monkeypatch.setattr(app.router, "routes", list(app.router.routes))  # 다른 시험의 앱에 화면 길이 남지 않게
    cli._serve("127.0.0.1", 18999)
    assert seen["use_colors"] is False
    assert (seen["host"], seen["port"], seen["target"]) == ("127.0.0.1", 18999, app)
