"""tests/files 공용: 빈 작업 줄·가짜 임베딩·메모리 Qdrant·파일 올리기."""

from collections.abc import Callable

import pytest
from sqlalchemy import select

from app.files import classify, jobs, vectors
from app.llm import embeddings
from app.store import files
from app.store.tables import FileRow, User
from tests.embed_doubles import FakeEmbedder
from tests.llm_doubles import add_connection


@pytest.fixture(autouse=True)
def empty_jobs(monkeypatch):
    """작업 줄은 프로세스에 하나다 — 시험마다 비운다(다른 시험이 올린 파일이 섞이지 않게)."""
    monkeypatch.setattr(jobs, "_queue", [])
    monkeypatch.setattr(jobs, "_waiting", set())
    monkeypatch.setattr(jobs, "_cursors", {})


@pytest.fixture(autouse=True)
def no_classify(monkeypatch):
    """분류 단계(Task 49)는 끈다 — 임베딩 시험의 일꾼이 LLM 을 부르지 않게. 분류 시험(test_classify)이 다시 켠다."""

    async def skip(*_args) -> None:
        return None

    monkeypatch.setattr(classify, "after_index", skip)
    monkeypatch.setattr(classify, "suggest_if_due", skip)


@pytest.fixture
def embedder(monkeypatch) -> FakeEmbedder:
    double = FakeEmbedder()
    monkeypatch.setattr(embeddings, "TRANSPORT", double.transport)
    return double


@pytest.fixture
def store(monkeypatch) -> vectors.Store:
    memory = vectors.Store(":memory:", "t")
    monkeypatch.setattr(vectors, "STORE", memory)
    return memory


@pytest.fixture
def ready(session, embedder, store):
    """기본 Liner 연결 + 가짜 임베딩 + 메모리 Qdrant."""
    return add_connection(session)


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def put(session, admin_user) -> Callable[..., FileRow]:
    """글 파일 하나를 올린다(저장·글 뽑기·작업 줄에 넣기까지 — 임베딩은 jobs.drain 이 한다)."""

    def upload(body: str, name: str = "메모.txt") -> FileRow:
        return files.save_upload(session, body.encode("utf-8"), name, admin_user)

    return upload
