"""연락 하네스 시험용 가짜(Task 64): 통로 가짜 FakeChannel, faked_channels()·fixture fake_channel, 진짜 통로 가드.
conftest 의 pytest_plugins 로 올리므로 아래 autouse 가드는 **모든 시험**에 걸린다.

- faked_channels() / fake_channel — FakeChannel 하나를 세 통로 이름(sms·kakao·call)으로 registry.pinned 로 덮는다. 시험 가운데
  진짜 통로 모듈이 처음 import 돼 스스로 등록해도 가짜가 앞에 서고, 끝나면 덮은 층만 걷혀 진짜 등록은 남는다. 끝날 때 세
  이름이 아직 가짜로 풀리는지 본다. 어느 이름으로 불렸든 deliver 는 Delivery(통로 이름, 줄 id)를 delivered 에 쌓는다.
- no_real_channels(autouse) — 등록된 진짜 통로를 가드로 덮는다. 시험이 registry 로 진짜 통로의 deliver 에 닿으면 pytest.fail
  (BaseException 이라 문이 `except Exception` 으로 잡아도 새어 나간다) + 끝에서 한 번 더 실패. 등록되지 않은 통로는 그대로
  NotReady. 진짜 통로를 registry 로 부를 시험은 `@pytest.mark.real_channel` 로 밝힌다. 통로 클래스를 직접 만들어 부르는 시험
  (예: SmsChannel().deliver)은 그것이 밝힌 것이다 — 그때는 제공사 가짜(fake_provider)를 쓴다.
"""

import inspect
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from app.outreach.harness import registry
from app.outreach.harness.types import Delivered

CHANNEL_NAMES = registry.CHANNEL_NAMES


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "real_channel: 이 시험은 registry 로 진짜 통로를 부른다(진짜 통로 가드를 끈다)")


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
    """registry 에 덮는 층: 등록된 진짜 통로마다 가드를 준다(등록되지 않은 이름은 없는 그대로)."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    def __getitem__(self, name: str) -> "GuardLane":
        registry._CHANNELS[name]  # 진짜 등록이 없으면 KeyError → 덮지 않는다
        return GuardLane(name, self)

    def __iter__(self) -> Iterator[str]:
        return iter(list(registry._CHANNELS))

    def __len__(self) -> int:
        return len(registry._CHANNELS)


@dataclass(frozen=True)
class GuardLane:
    name: str
    guard: RealChannelGuard

    async def deliver(self, row_id: int) -> Delivered:
        message = (f"시험이 진짜 「{self.name}」 통로(줄 {row_id})에 닿았습니다 — fake_channel 을 쓰거나 "
                   "@pytest.mark.real_channel 로 밝히세요")
        self.guard.violations.append(message)
        pytest.fail(message)


@pytest.fixture(autouse=True)
def no_real_channels(request) -> Iterator[RealChannelGuard | None]:
    """모든 시험: registry 로 진짜 통로에 닿으면 실패. `@pytest.mark.real_channel` 이면 끈다(None)."""
    if request.node.get_closest_marker("real_channel"):
        yield None
        return
    guard = RealChannelGuard()
    with registry.pinned(guard):
        yield guard
    assert not guard.violations, guard.violations[0]


@pytest.fixture
def fake_channel(no_real_channels) -> Iterator[FakeChannel]:
    """sms·kakao·call 을 모두 이 가짜로(진짜 통로 가드보다 앞에). 시험이 끝나면 registry 는 전과 같다."""
    with faked_channels() as fake:
        yield fake
