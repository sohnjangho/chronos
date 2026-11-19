import pytest
from sqlalchemy import select

from app.store.tables import User
from app.tools import registry
from app.tools.context import ToolContext
from tests.tool_doubles import Empty, SpyIn, SpyOut, registered


@pytest.fixture(autouse=True)
def all_tools():
    registry.load_all()


@pytest.fixture
def events() -> list:
    """ctx.emit 으로 나온 AgentEvent 가 차례로 쌓인다."""
    return []


@pytest.fixture
def ctx(session, events) -> ToolContext:
    """대상 일정이 없는 문맥. 사용자는 관리자."""
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    return ToolContext(session=session, user=admin, schedule_id=None, emit=events.append)


class Spy:
    def __init__(self) -> None:
        self.calls = 0


@pytest.fixture
def spy_tool():
    """도구 'spy' {n: int} → {n}. 불린 횟수를 calls 에 센다."""
    spy = Spy()

    def run(args: SpyIn, ctx: ToolContext) -> SpyOut:
        spy.calls += 1
        return SpyOut(n=args.n)

    with registered("spy", run):
        yield spy


@pytest.fixture
def boom_tool():
    """도구 'boom': 부르면 비밀이 든 메시지로 예외를 낸다."""

    def run(args: Empty, ctx: ToolContext) -> Empty:
        raise RuntimeError("secret-data-in-message")

    with registered("boom", run):
        yield
