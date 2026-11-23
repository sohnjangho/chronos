"""연락 하네스 시험용 가짜(Task 64): 통로 가짜 FakeChannel, faked_channels()·fixture fake_channel, 진짜 통로 가드.
conftest 의 pytest_plugins 로 올리므로 아래 autouse 가드는 **모든 시험**에 걸린다.

- faked_channels() / fake_channel — FakeChannel 하나를 세 통로 이름(sms·kakao·call)으로 registry.pinned 로 덮는다. 시험 가운데
  진짜 통로 모듈이 처음 import 돼 스스로 등록해도 가짜가 앞에 서고, 끝나면 덮은 층만 걷혀 진짜 등록은 남는다. 끝날 때 세
  이름이 아직 가짜로 풀리는지 본다. 어느 이름으로 불렸든 deliver 는 Delivery(통로 이름, 줄 id)를 delivered 에 쌓는다.
- 진짜 통로 가드 두 겹: 세션 내내 깔린 바닥(_real_channel_floor — 시험 밖, 곧 시험이 끝난 뒤 남은 스레드·작업이나 고정물
  정리 중에 닿은 것을 모아 세션 끝에 실패로 알림)과 시험마다의 가드(no_real_channels, autouse — 그 시험 안에서 닿은 것).
  등록된 진짜 통로의 deliver 에 registry 로 닿으면 pytest.fail(BaseException 이라 문이 `except Exception` 으로 잡아도 새어
  나간다) + 끝에서 한 번 더 실패. 메시지에 통로 이름·어느 시험(또는 「시험 밖」)·스레드 이름. 등록되지 않은 통로는 그대로
  NotReady.
- 진짜 통로를 registry 로 부를 시험은 **시험 함수에 직접** 통로 이름과 함께 밝힌다: `@pytest.mark.real_channel("sms")` —
  그 이름만 풀린다. 모듈·클래스의 pytestmark 는 가드를 끄지 않고, 이름 없는(또는 모르는 이름) 표지는 시험을 멈춘다.
  통로 클래스를 직접 만들어 부르는 시험(예: SmsChannel().deliver)은 그것이 밝힌 것이다 — 그때는 제공사 가짜(fake_provider)를 쓴다.
"""

import inspect
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from app.outreach.harness import registry
from app.outreach.harness.types import Delivered

CHANNEL_NAMES = registry.CHANNEL_NAMES


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", 'real_channel(*names): 이 시험 함수가 registry 로 그 진짜 통로를 부른다 — 시험 함수에 '
                                       '직접, 통로 이름과 함께(@pytest.mark.real_channel("sms"))')


@dataclass(frozen=True)
class Delivery:
    """통로가 받은 한 번: 어느 통로 이름으로, 어느 줄을."""

    channel: str
    row_id: int


class FakeChannel:
    """통로 가짜. lane(이름)이 그 이름의 Channel 을 주고, 모두 이 객체의 delivered 에 쌓는다.

    result — deliver 가 돌려줄 것. None 이면 sent(provider_id 'fake-<n>'), Delivered 면 그것(failed·unsure 도), 예외면 (쌓은 뒤)
             던진다.
    during — deliver 안에서 돌려주기 전에 부를 함수(row_id). 통로를 부르는 동안 DB 쓰기 잠금이 없는지 볼 때 쓴다.
    """

    def __init__(self) -> None:
        self.delivered: list[Delivery] = []
        self.result: Delivered | Exception | None = None
        self.during: Callable[[int], object] | None = None

    def lane(self, name: str) -> "FakeLane":
        return FakeLane(name, self)

    async def _deliver(self, name: str, row_id: int) -> Delivered:
        self.delivered.append(Delivery(name, row_id))
        if self.during is not None:
            done = self.during(row_id)
            if inspect.isawaitable(done):
                await done
        if isinstance(self.result, Exception):
            raise self.result
        return self.result or Delivered("sent", provider_id=f"fake-{len(self.delivered)}")


@dataclass(frozen=True)
class FakeLane:
    """FakeChannel 의 한 이름(Channel 꼴)."""

    name: str
    fake: FakeChannel

    async def deliver(self, row_id: int) -> Delivered:
        return await self.fake._deliver(self.name, row_id)


@contextmanager
def faked_channels() -> Iterator[FakeChannel]:
    """세 통로 이름을 FakeChannel 하나로 덮는다. 끝날 때 세 이름이 아직 이 가짜로 풀리는지 본다."""
    fake = FakeChannel()
    lanes = {name: fake.lane(name) for name in CHANNEL_NAMES}
    with registry.pinned(lanes):
        yield fake
        moved = [name for name, lane in lanes.items() if registry.channel(name) is not lane]
        assert not moved, f"시험이 끝날 때 가짜가 아닌 통로로 풀림: {moved}"


class RealChannelGuard(Mapping):
    """registry 에 덮는 층: 등록된 진짜 통로마다(freed 에 든 이름 빼고) 가드를 준다. 등록되지 않은 이름은 없는 그대로.
    where 는 시험 이름(세션 바닥이면 None), hint 는 실패 글에 덧붙일 말."""

    def __init__(self, where: str | None, freed: frozenset[str] = frozenset(), hint: str = "") -> None:
        self.violations: list[str] = []
        self.where = where
        self.freed = freed
        self.hint = hint

    def __getitem__(self, name: str) -> "GuardLane":
        if name in self.freed:
            raise KeyError(name)
        registry._CHANNELS[name]  # 진짜 등록이 없으면 KeyError → 덮지 않는다
        return GuardLane(name, self)

    def __iter__(self) -> Iterator[str]:
        return iter([name for name in registry._CHANNELS if name not in self.freed])

    def __len__(self) -> int:
        return len(list(iter(self)))


@dataclass(frozen=True)
class GuardLane:
    name: str
    guard: RealChannelGuard

    async def deliver(self, row_id: int) -> Delivered:
        where = self.guard.where or "시험 밖(시험이 끝난 뒤 남은 스레드·작업 또는 고정물 정리 중)"
        message = (f"진짜 「{self.name}」 통로(줄 {row_id})에 닿았습니다 — {where}, 스레드 {threading.current_thread().name}. "
                   f'fake_channel 을 쓰거나 시험 함수에 직접 @pytest.mark.real_channel("{self.name}") 로 밝히세요.'
                   f"{self.guard.hint}")
        self.guard.violations.append(message)
        pytest.fail(message)


def _freed_names(item: pytest.Item) -> tuple[frozenset[str], str]:
    """시험 함수에 직접 붙은 real_channel 표지가 푸는 통로 이름과, 실패 글에 덧붙일 말."""
    own = [mark for mark in item.own_markers if mark.name == "real_channel"]
    names = [name for mark in own for name in mark.args]
    if own and (not names or not set(names) <= set(CHANNEL_NAMES)):
        pytest.fail(f"real_channel 표지에는 풀 통로 이름({'·'.join(CHANNEL_NAMES)})을 적습니다 — "
                    '예: @pytest.mark.real_channel("sms")', pytrace=False)
    hint = ""
    if not own and item.get_closest_marker("real_channel") is not None:
        hint = " (모듈·클래스의 real_channel 표지는 가드를 끄지 않습니다 — 시험 함수에 직접 붙이세요)"
    return frozenset(names), hint


@pytest.fixture(scope="session", autouse=True)
def _real_channel_floor() -> Iterator[RealChannelGuard]:
    """세션 내내 깔린 바닥 가드 — 시험 밖에서 진짜 통로에 닿은 것을 세션 끝에 실패로 알린다."""
    floor = RealChannelGuard(None)
    with registry.pinned(floor):
        yield floor
    assert not floor.violations, floor.violations[0]


@pytest.fixture(autouse=True)
def no_real_channels(request, _real_channel_floor) -> Iterator[RealChannelGuard]:
    """모든 시험: registry 로 진짜 통로에 닿으면 실패. 시험 함수에 직접 붙은 real_channel("이름") 의 이름만 푼다."""
    freed, hint = _freed_names(request.node)
    guard = RealChannelGuard(request.node.nodeid, freed, hint)
    _real_channel_floor.freed = freed
    try:
        with registry.pinned(guard):
            yield guard
    finally:
        _real_channel_floor.freed = frozenset()
    assert not guard.violations, guard.violations[0]


@pytest.fixture
def fake_channel(no_real_channels) -> Iterator[FakeChannel]:
    """sms·kakao·call 을 모두 이 가짜로(진짜 통로 가드보다 앞에). 시험이 끝나면 registry 는 전과 같다."""
    with faked_channels() as fake:
        yield fake
