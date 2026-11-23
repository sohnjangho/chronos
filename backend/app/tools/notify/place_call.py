"""notify.place_call — 이 대화에서 만든 에이전트 통화 초안 하나를 나가는 문에 넣는다(계획 4 Task 81 — 위임).

전화 권한이 위임일 때만 모델에게 보인다. 규칙은 notify.send_message 와 같다(send_draft) — 이 대화의 에이전트 초안만, 문에 넣기
전에는 읽기만, 결과는 문의 판정 그대로. 문을 지나면 「걸 차례에 넣음」(queued)이지 「통화됨」이 아니다.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context import ToolContext
from app.tools.notify.send_message import SendOut, send_draft
from app.tools.registry import tool


class PlaceCallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: int = Field(description="이 대화에서 notify__draft_call 이 준 call_id")


@tool(
    "notify.place_call",
    "이 대화에서 notify__draft_call 로 만든 AI 전화 초안을 건다(전화 권한이 위임일 때만): {call_id}. 시험 모드·수신 거부·"
    "근무시간·상한은 걸 때 다시 본다. 결과 outcome 을 그대로 전한다 — queued 는 「걸 차례에 넣었습니다」(아직 통화한 것이 "
    "아님), blocked_hours 는 근무시간 밖, unsure 는 「확인 필요」(다시 걸지 않는다), 그 밖은 막힌 까닭(message).",
    program="contacts",
    mutates=True,
)
async def place_call(args: PlaceCallIn, ctx: ToolContext) -> SendOut:
    return await send_draft("call", args.call_id, ctx)
