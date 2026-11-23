"""연락 하네스 시험용 가짜(Task 64): 통로 가짜 FakeChannel 과 fixture fake_channel. conftest 의 pytest_plugins 로 올린다.

fake_channel 은 FakeChannel 하나를 세 통로 이름(sms·kakao·call)으로 registry 에 등록하고, 시험이 끝나면 전에 있던
등록으로 되돌린다. 어느 이름으로 불렸든 deliver 는 Delivery(통로 이름, 줄 id)를 delivered 에 쌓는다. 제공사·DB 를 부르지 않는다.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.outreach.harness import registry
from app.outreach.harness.types import Delivered

CHANNEL_NAMES = ("sms", "kakao", "call")


@dataclass(frozen=True)
class Delivery:
    """통로가 받은 한 번: 어느 통로 이름으로, 어느 줄을."""

    channel: str
    row_id: int


class FakeChannel:
    """통로 가짜. lane(이름)이 그 이름의 Channel 을 주고, 모두 이 객체의 delivered 에 쌓는다.

    result — deliver 가 돌려줄 것. None 이면 성공(provider_id 'fake-<n>'), Delivered 면 그것, 예외면 (쌓은 뒤) 던진다.
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
        return self.result or Delivered(ok=True, provider_id=f"fake-{len(self.delivered)}")


@dataclass(frozen=True)
class FakeLane:
    """FakeChannel 의 한 이름(Channel 꼴)."""

    name: str
    fake: FakeChannel

    async def deliver(self, row_id: int) -> Delivered:
        return await self.fake._deliver(self.name, row_id)


@pytest.fixture
def fake_channel(monkeypatch) -> FakeChannel:
    """sms·kakao·call 을 모두 이 가짜로. 시험이 끝나면 registry 는 전과 같다."""
    fake = FakeChannel()
    for name in CHANNEL_NAMES:
        monkeypatch.setitem(registry._CHANNELS, name, fake.lane(name))
    return fake
