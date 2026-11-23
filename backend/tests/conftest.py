import functools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import get_session
from app.files import classify, jobs, merge_suggest
from app.main import app
from app.outreach import worker
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from tests import schedules
from tests.helpers import auth

pytest_plugins = ["tests.outreach_doubles", "tests.harness_doubles", "tests.provider_doubles"]


@pytest.fixture(autouse=True)
def test_env(monkeypatch, tmp_path):
    """시험은 실제 .env 없이 자기 값만 쓴다."""
    monkeypatch.setenv("CHRONOS_ADMIN_ID", "admin")
    monkeypatch.setenv("CHRONOS_ADMIN_PASSWORD", "test-pass")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "test-secret-key-0123456789abcdef")
    monkeypatch.setenv("CHRONOS_DATA_DIR", str(tmp_path / "data"))
    # 뜻 검색(Qdrant)을 끈다: 앱이 뜰 때 뒤 작업 일꾼이 돌지 않고, 시험이 Qdrant·Liner 에 나가지 않는다.
    # 뜻 검색 시험은 app.files.vectors.STORE 와 app.llm.embeddings.TRANSPORT 를 가짜로 끼운다(tests/files).
    monkeypatch.setenv("CHRONOS_QDRANT_URL", "")


@pytest.fixture(autouse=True)
def quiet_file_worker(monkeypatch):
    """파일 뒤 작업(Task 48·49). 분류 단계·합치기 제안은 끈다 — 일꾼이 Liner 를 부르지 않게(분류 시험이 다시 켠다).
    서버의 일꾼은 뜻 검색이 꺼져도 늘 돌지만, 시험에서는 CHRONOS_QDRANT_URL 을 준 시험에서만 앱(lifespan)이 띄운다 —
    앱 스레드의 일꾼이 시험이 jobs.drain 으로 돌리는 작업 줄을 가로채지 않게. 진짜 start 는 jobs.start.__wrapped__."""
    real_start = jobs.start

    @functools.wraps(real_start)
    def start() -> None:
        if Settings().qdrant_url:
            real_start()

    async def skip(*_args) -> None:
        return None

    monkeypatch.setattr(jobs, "start", start)
    monkeypatch.setattr(classify, "after_index", skip)
    monkeypatch.setattr(merge_suggest, "suggest_if_due", skip)


@pytest.fixture(autouse=True)
def quiet_outreach_worker(monkeypatch):
    """연락 일꾼(Task 71 — 예약 발송·상태 조회·들어온 문자). 시험에서는 앱(lifespan)이 일꾼을 띄우지 않는다 — 시험은
    worker.tick(now=…) 을 한 바퀴씩 직접 부른다. 일꾼의 메모리 상태(status)도 시험마다 새것. 진짜 start 는
    worker.start.__wrapped__."""
    real_start = worker.start

    @functools.wraps(real_start)
    def start() -> None:
        return None

    monkeypatch.setattr(worker, "start", start)
    monkeypatch.setattr(worker, "_state", worker._State())


@pytest.fixture
def client():
    """시험마다 새 DB(tmp_path)로 앱을 띄운다. 첫 관리자 admin/test-pass 가 있다."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(client):
    """앱과 같은 시험 DB에 붙은 세션.

    API로 바꾼 행을 다시 읽기 전에는 session.expire_all() 을 불러야 새 값이 보인다.
    """
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


@pytest.fixture
def sample_schedule():
    """A(3일) → B(2일). 2027-03-01(월) 시작, 주 5일. A 3/1~3/3, B 3/4~3/5."""
    return schedules.sample()


@pytest.fixture
def sid(session, sample_schedule) -> int:
    """sample_schedule 을 버전 1로 저장한 일정 id."""
    return schedules.store(session, sample_schedule)
