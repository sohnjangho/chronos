"""통로 등록부. 통로 모듈(app/outreach/channels/<이름>.py)이 import 될 때 register_channel 로 스스로 등록하고
(문자 71 · 통화 88 · 카카오톡 101), 나가는 문은 channel(이름)으로 찾는다. 하네스는 통로를 import 하지 않는다.

- 이름은 이름표의 통로(CHANNEL_NAMES)만, 그리고 통로의 name 과 같아야 한다. 같은 이름에 다른 객체를 등록하면 ValueError
  (갈아 끼우려면 replace=True). 같은 객체를 다시 등록하는 것은 괜찮다.
- pinned(mapping) 은 등록 위에 덮는 층이다: channel() 은 가장 나중에 덮은 층부터 보고, 없으면 등록을 본다. 덮는 동안
  register_channel 이 불려도(진짜 통로 모듈이 처음 import 됨) 덮은 것이 앞에 서고, 등록은 그대로 남는다.
  덮는 층은 프로세스 전체에 걸린다 — 진짜 발송이 도는 서버 프로세스 안에서는 쓰지 말 것(시험·따로 띄운 자식 프로세스 몫).
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from app.outreach.harness.types import Channel, NotReady

CHANNEL_NAMES = ("sms", "kakao", "call")
_CHANNELS: dict[str, Channel] = {}
_PINNED: list[Mapping[str, Channel]] = []


def register_channel(name: str, channel: Channel, *, replace: bool = False) -> None:
    """그 이름(sms | kakao | call)의 통로로 둔다(모듈 머리 글의 규칙)."""
    if name not in CHANNEL_NAMES:
        raise ValueError(f"통로 이름은 {CHANNEL_NAMES} 가운데 하나입니다")
    if getattr(channel, "name", None) != name:
        raise ValueError(f"「{name}」 으로 등록하는 통로의 name 이 다릅니다")
    current = _CHANNELS.get(name)
    if current is not None and current is not channel and not replace:
        raise ValueError(f"「{name}」 통로가 이미 등록돼 있습니다(갈아 끼우려면 replace=True)")
    _CHANNELS[name] = channel


def channel(name: str) -> Channel:
    """그 이름의 통로 — 덮은 층(나중 것부터), 없으면 등록. 어디에도 없으면 NotReady."""
    for layer in reversed(_PINNED):
        found = layer.get(name)
        if found is not None:
            return found
    try:
        return _CHANNELS[name]
    except KeyError:
        raise NotReady(f"「{name}」 통로가 아직 준비되지 않았습니다") from None


def registered() -> list[str]:
    """channel() 이 찾을 수 있는 이름(등록 + 덮은 층), 이름 순."""
    return sorted(set(_CHANNELS).union(*_PINNED))


@contextmanager
def pinned(mapping: Mapping[str, Channel]) -> Iterator[None]:
    """이 블록 동안 mapping 의 통로를 등록보다 앞에 세운다(모듈 머리 글). 나갈 때 이 층만 걷는다."""
    _PINNED.append(mapping)
    try:
        yield
    finally:
        for index in range(len(_PINNED) - 1, -1, -1):
            if _PINNED[index] is mapping:
                del _PINNED[index]
                break
