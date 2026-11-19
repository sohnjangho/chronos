import pytest
from sqlalchemy import select

from app.llm.client import LlmClient
from app.store.tables import User
from app.tools.context import ToolContext
from tests.llm_doubles import FakeLiner, add_connection


@pytest.fixture
def events() -> list:
    """ctx.emit 으로 나온 AgentEvent 가 차례로 쌓인다."""
    return []


@pytest.fixture
def ctx(session, events) -> ToolContext:
    """대상 일정이 없는 문맥. 사용자는 관리자."""
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    return ToolContext(session=session, user=admin, schedule_id=None, emit=events.append)


@pytest.fixture
def liner() -> FakeLiner:
    return FakeLiner()


@pytest.fixture
def llm(session, liner) -> LlmClient:
    """기본 연결이 있는 LLM. 답은 liner 대본대로."""
    add_connection(session)
    return LlmClient(session, transport=liner.transport)


@pytest.fixture
def llm_empty(session, liner) -> LlmClient:
    """연결이 하나도 없는 LLM."""
    return LlmClient(session, transport=liner.transport)
