import pytest

from app.llm.client import LlmClient
from tests.llm_doubles import FakeLiner, add_connection


@pytest.fixture
def liner() -> FakeLiner:
    return FakeLiner()


@pytest.fixture
def fake_liner(liner) -> FakeLiner:
    """정상으로 답하는 가짜 Liner (model claude-opus-5.5, cost 0.04)."""
    return liner


@pytest.fixture
def fake_liner_timeout(liner) -> FakeLiner:
    """답하기 전에 1초를 끄는 가짜 Liner."""
    liner.delay_s = 1.0
    return liner


@pytest.fixture
def connection(session):
    """기본 연결 하나(키 tests.llm_doubles.KEY)."""
    return add_connection(session)


@pytest.fixture
def llm(session, connection, liner) -> LlmClient:
    return LlmClient(session, transport=liner.transport)


@pytest.fixture
def llm_empty(session, liner) -> LlmClient:
    """연결이 하나도 없는 상태."""
    return LlmClient(session, transport=liner.transport)
