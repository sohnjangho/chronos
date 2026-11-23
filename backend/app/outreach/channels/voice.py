"""통화 통로(Task 88) — 얇다. 나가는 문(gate.dispatch)이 차지한 통화 줄(queued)을 통화 일꾼의 줄에 넣기만 하고 곧바로 돌아온다.
`Delivered("sent")` 는 「걸렸다」가 아니라 「줄에 넣었다」다. 거는 것·걸기 직전에 다시 보는 것·결과를 적는 것은 일꾼
(app.outreach.voice.runner)이 한다 — 일꾼은 queued → dialing 을 조건부로 차지한 뒤에만 건다.

- 줄에 넣지 못하면(꺼진 일꾼·가득 찬 줄) `Delivered("failed", fail_code="local_error")` — 아무것도 걸지 않았음이 확실하므로 문이
  줄을 failed 로 닫고, 사람이 곧바로 다시 걸 수 있다(gate.FAIL_TEXT 의 그 문장).
- 이 모듈을 불러오면 `registry.register_channel("call", CHANNEL)` — 객체는 프로세스에 하나(다시 불러와도 같은 객체). 불러오는 곳은
  통화 일꾼의 start 하나다(줄을 비울 일꾼이 있을 때만 통로가 생긴다). 시험은 fake_channel(registry.pinned)로 가짜를 앞에 세운다.
"""

from app.outreach.harness import registry
from app.outreach.harness.types import Delivered
from app.outreach.voice import runner

NOT_QUEUED = "local_error"  # 줄에 넣지 못함 — gate.FAIL_TEXT 의 열쇠(「보내기 전에 우리 서버에서 오류가 나 …」)


class VoiceChannel:
    """통화 통로(Channel). 나가는 문만 부른다."""

    name = "call"

    async def deliver(self, row_id: int) -> Delivered:
        if runner.enqueue(row_id):
            return Delivered("sent")
        return Delivered("failed", fail_code=NOT_QUEUED)


# 프로세스에 하나. 모듈을 다시 불러와도 처음 만든 객체를 그대로 쓴다(같은 객체를 다시 등록하는 것은 괜찮다).
CHANNEL: VoiceChannel = globals().get("CHANNEL") or VoiceChannel()
registry.register_channel("call", CHANNEL)
