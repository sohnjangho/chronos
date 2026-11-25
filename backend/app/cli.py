"""chronos 명령: 한 줄 설치(uvx) 뒤 데이터 폴더·비밀 열쇠·첫 관리자를 챙기고, 빌드한 화면과 함께 서버를 띄운다.

    uvx --from "git+https://github.com/sohnjangho/chronos#subdirectory=backend" chronos

- 데이터 폴더: --data-dir > CHRONOS_DATA_DIR > ~/.chronos
- 비밀 열쇠: 처음에 만들어 <데이터 폴더>/secret_key(0600)에 두고 다음에도 쓴다. 화면에 찍지 않는다.
- 첫 관리자: 사용자가 없을 때만. --admin-id(또는 CHRONOS_ADMIN_ID)·CHRONOS_ADMIN_PASSWORD 가 있으면 묻지 않고,
  없으면 터미널에서 묻는다(비밀번호는 보이지 않게, 두 번). 만든 뒤 서버에는 실제 비밀번호 대신 검사만 통과하는
  버리는 값을 넘긴다 — 첫 관리자가 이미 있으면 init_db 는 그 값을 쓰지 않는다.
- 뜻 검색(Qdrant)은 기본으로 끈다(--qdrant-url 로 켠다). Liner 키 등은 로그인 뒤 설정에서 넣는다.
"""

import argparse
import getpass
import os
import secrets
import sqlite3
from collections.abc import Callable
from pathlib import Path

from app.config import MAX_ADMIN_PASSWORD_BYTES, MIN_ADMIN_PASSWORD_CHARS

SECRET_FILE = "secret_key"
MAX_LOGIN_ID_CHARS = 50  # users.login_id 칸 길이
TRIES = 3

Ask = Callable[[str], str]
Say = Callable[[str], None]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="chronos",
        description="ChronOS 를 이 컴퓨터에서 띄웁니다. 처음 실행이면 관리자 계정을 만듭니다.",
        add_help=False,
    )
    p.add_argument("-h", "--help", action="help", help="이 도움말을 보이고 끝냅니다")
    p.add_argument("--data-dir", help="데이터 폴더(DB·비밀 열쇠·파일). 기본: CHRONOS_DATA_DIR 또는 ~/.chronos")
    p.add_argument("--host", default="127.0.0.1", help="서버 주소(기본 127.0.0.1 — 이 컴퓨터에서만)")
    p.add_argument("--port", type=int, default=8210, help="서버 포트(기본 8210)")
    p.add_argument("--admin-id", help="처음 실행 때 만들 관리자 아이디(비밀번호는 CHRONOS_ADMIN_PASSWORD 로 주면 묻지 않음)")
    p.add_argument("--qdrant-url", default=os.environ.get("CHRONOS_QDRANT_URL", ""),
                   help="뜻 검색용 Qdrant 주소(기본: 끔 — 낱말 검색만)")
    return p.parse_args(argv)


def data_dir_from(option: str | None) -> Path:
    raw = option or os.environ.get("CHRONOS_DATA_DIR") or "~/.chronos"
    return Path(raw).expanduser().resolve()


def secret_key(data_dir: Path) -> str:
    """<데이터 폴더>/secret_key 를 읽는다. 없으면 임의 값으로 만든다(주인만 읽기 0600)."""
    path = data_dir / SECRET_FILE
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32) + "\n")
    return path.read_text().strip()


def password_problem(password: str) -> str | None:
    if len(password) < MIN_ADMIN_PASSWORD_CHARS or len(password.encode()) > MAX_ADMIN_PASSWORD_BYTES:
        return f"비밀번호는 {MIN_ADMIN_PASSWORD_CHARS}자 이상, {MAX_ADMIN_PASSWORD_BYTES}바이트 이하여야 합니다."
    return None


def _id_problem(login_id: str) -> str | None:
    if not login_id or len(login_id) > MAX_LOGIN_ID_CHARS:
        return f"아이디는 1~{MAX_LOGIN_ID_CHARS}자여야 합니다."
    return None


def ask_admin(ask: Ask, ask_hidden: Ask, say: Say, login_id: str | None) -> tuple[str, str]:
    """터미널에서 아이디(주지 않았으면)와 비밀번호(두 번)를 묻는다. 세 번 틀리면 멈춘다."""
    for _ in range(TRIES):
        if login_id is None or _id_problem(login_id):
            candidate = ask("관리자 아이디: ").strip()
            if problem := _id_problem(candidate):
                say(problem)
                continue
            login_id = candidate
        password = ask_hidden(f"비밀번호({MIN_ADMIN_PASSWORD_CHARS}자 이상, 입력이 보이지 않습니다): ")
        if problem := password_problem(password):
            say(problem)
            continue
        if ask_hidden("비밀번호 확인: ") != password:
            say("두 비밀번호가 같지 않습니다. 다시 넣어 주세요.")
            continue
        return login_id, password
    raise SystemExit("관리자 계정을 만들지 못했습니다. 다시 실행해 주세요.")


def existing_login(db_path: Path) -> str | None:
    """이미 있는 사용자 중 관리자(없으면 아무나) 아이디. DB·표가 없으면 None."""
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as db:
        try:
            row = db.execute("SELECT login_id FROM users ORDER BY role = 'admin' DESC, id LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return None
    return row[0] if row else None


def _first_admin(args: argparse.Namespace, ask: Ask, ask_hidden: Ask, say: Say) -> tuple[str, str]:
    login_id = args.admin_id or os.environ.get("CHRONOS_ADMIN_ID") or None
    password = os.environ.get("CHRONOS_ADMIN_PASSWORD")
    if login_id and password:
        if problem := password_problem(password) or _id_problem(login_id):
            raise SystemExit(f"CHRONOS_ADMIN_PASSWORD/--admin-id: {problem}")
        return login_id, password
    say("처음 실행입니다. 관리자 계정을 만듭니다.")
    try:
        return ask_admin(ask, ask_hidden, say, login_id)
    except EOFError:
        raise SystemExit(
            "터미널 입력을 받을 수 없습니다. --admin-id 와 CHRONOS_ADMIN_PASSWORD 환경 변수로 관리자를 주세요."
        ) from None


def prepare(args: argparse.Namespace, ask: Ask, ask_hidden: Ask, say: Say) -> dict[str, str]:
    """데이터 폴더·열쇠·첫 관리자를 챙기고 서버 환경 변수를 os.environ 에 넣는다(넣은 값을 돌려준다)."""
    data_dir = data_dir_from(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    say(f"데이터 폴더: {data_dir}")
    login_id = existing_login(data_dir / "chronos.db")
    new_password = None
    if login_id is None:
        login_id, new_password = _first_admin(args, ask, ask_hidden, say)
    env = {
        "CHRONOS_DATA_DIR": str(data_dir),
        "CHRONOS_SECRET_KEY": secret_key(data_dir),
        "CHRONOS_QDRANT_URL": args.qdrant_url,
        "CHRONOS_ADMIN_ID": login_id,
        "CHRONOS_ADMIN_PASSWORD": new_password or secrets.token_urlsafe(24),
    }
    os.environ.update(env)
    if new_password is not None:
        from app.db import close_db, init_db  # 환경을 넣은 뒤에 불러온다

        init_db()  # 표를 만들고 첫 관리자를 만든다(기존 env 방식과 같은 길)
        close_db()
        env["CHRONOS_ADMIN_PASSWORD"] = os.environ["CHRONOS_ADMIN_PASSWORD"] = secrets.token_urlsafe(24)
        say(f"관리자 계정 「{login_id}」을(를) 만들었습니다.")
    return env


def _serve(host: str, port: int) -> None:
    import uvicorn

    from app.main import app
    from app.serve_web import install_web

    install_web(app)
    # 색 출력은 원본 틀(color_message)을 써서 로그 거르개가 편 줄 대신 「%d」를 찍는다 — 색을 끈다
    uvicorn.run(app, host=host, port=port, access_log=False, use_colors=False)


def main(argv: list[str] | None = None, serve: Callable[[str, int], None] = _serve, say: Say = print) -> None:
    args = parse_args(argv)
    prepare(args, ask=input, ask_hidden=getpass.getpass, say=say)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    say("")
    say(f"ChronOS 주소: http://{shown}:{args.port}")
    say("브라우저에서 위 주소를 열고 관리자 계정으로 로그인하세요.")
    say("처음에는 설정에서 Liner API 키 등을 넣어야 에이전트가 일합니다(docs/manual/ChronOS_설치_사용설명서.pdf).")
    say("끄려면 Ctrl+C 를 누르세요.")
    serve(args.host, args.port)
