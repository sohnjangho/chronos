"""통로 등록부. 통로 모듈(app/outreach/channels/<이름>.py)이 import 될 때 register_channel 로 스스로 등록하고
(문자 71 · 통화 88 · 카카오톡 101), 나가는 문은 channel(이름)으로 찾는다. 하네스는 통로를 import 하지 않는다.
같은 이름을 다시 등록하면 나중 것이 이긴다.
"""

from app.outreach.harness.types import Channel, NotReady

_CHANNELS: dict[str, Channel] = {}


def register_channel(name: str, channel: Channel) -> None:
    """그 이름(sms | kakao | call)의 통로로 둔다."""
    _CHANNELS[name] = channel


def channel(name: str) -> Channel:
    """그 이름의 통로. 등록돼 있지 않으면 NotReady."""
    try:
        return _CHANNELS[name]
    except KeyError:
        raise NotReady(f"「{name}」 통로가 아직 준비되지 않았습니다") from None
