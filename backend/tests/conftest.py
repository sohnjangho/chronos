import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User


@pytest.fixture(autouse=True)
def test_env(monkeypatch, tmp_path):
    """시험은 실제 .env 없이 자기 값만 쓴다."""
    monkeypatch.setenv("CHRONOS_ADMIN_ID", "admin")
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "test-pass")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(tmp_path / "data"))


def auth(token: str) -> dict[str, str]:
    """Bearer 토큰을 요청 머리글로 바꾼다."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """시험마다 새 DB(tmp_path)로 앱을 띄운다. 첫 관리자 admin/test-pass 가 있다."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(client):
    """앱과 같은 시험 DB에 붙은 세션."""
    yield from get_session()


@pytest.fixture
def admin_token(session) -> str:
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    return issue_token(admin.id)


@pytest.fixture
def user_token(session) -> str:
    """일반 사용자 user1/user-pass 를 만들고 그 토큰을 준다."""
    user = User(
        login_id="user1",
        name="일반 사용자",
        role="user",
        password_hash=hash_password("user-pass"),
    )
    session.add(user)
    session.commit()
    return issue_token(user.id)


@pytest.fixture
def admin(admin_token) -> dict[str, str]:
    return auth(admin_token)


@pytest.fixture
def user(user_token) -> dict[str, str]:
    return auth(user_token)
