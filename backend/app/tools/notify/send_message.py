"""notify.send_message — 이 대화에서 만든 에이전트 문자 초안 하나를 나가는 문에 넣는다(계획 4 Task 81 — 위임).

모델에게 보이는 것은 문자·카카오톡 권한이 위임일 때뿐이다(outreach.policy.hidden_tools). 그래도 불리면 문이 권한 차례에서
needs_approval 로 막는다(두 겹). 판정은 모두 문(gate.dispatch, Actor("agent", …))이 한다 — 이 도구는 send_mode·approved_by·
status 를 쓰지 않고, 문에 넣기 전에 ctx.session 에 아무것도 쓰지 않는다(루프가 도구 앞에서 commit 했고, 문은 자기 세션으로
읽고 쓴다 — 도구가 뒤에 실패해 루프가 되돌려도 문이 적은 것은 남는다). 한 번 부르면 문도 한 번이다.
보낼 수 있는 줄: 이 일정 · 이 대화(chat_session_id) · origin "agent" · 나가는 줄 · 아직 나가지 않은 것(문자 draft, 통화 draft·
blocked_hours). 아니면 NOT_YOURS — 없는 줄과 같은 글이다(다른 대화·다른 일정의 줄이 있는지 알려 주지 않는다).
결과는 문의 판정 그대로 {outcome, message, scheduled_at}: unsure 는 「보냈는지 확인 필요」이지 보냄이 아니고, 다시 보내지 않는다.
카드 card{kind:"outreach_sent", schedule_id, message_id | call_id, contact, channel, outcome, message} — 번호 없음.
notify.place_call 도 이 모듈의 send_draft 를 쓴다.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.outreach.harness import gate
from app.outreach.harness.types import Actor, OutcomeCode
from app.store import contacts, outreach
from app.tools.context import ToolContext, ToolError
from app.tools.notify import AGENT_NAME, card_contact, schedule_for
from app.tools.registry import tool

NOT_YOURS = "이 대화에서 만든 초안만 보낼 수 있습니다."
_OPEN = {"message": ("draft",), "call": ("draft", "blocked_hours")}  # 아직 나가지 않은 줄(예약된 줄은 건드리지 않는다)
_ID = {"message": "message_id", "call": "call_id"}


class SendMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int = Field(description="이 대화에서 notify__draft_message 가 준 message_id")


class SendOut(BaseModel):
    outcome: OutcomeCode  # 나가는 문의 판정 그대로
    message: str  # 문의 글 그대로(사람에게 전할 말)
    scheduled_at: datetime | None  # 근무시간 밖이라 예약했으면 그 시각(KST)


def _now() -> datetime:
    return datetime.now(UTC)


def _contact(session: Session, schedule_id: int, contact_id: int | None) -> dict | None:
    if contact_id is None:
        return None
    try:
        return card_contact(session, contacts.get_contact(session, schedule_id, contact_id))
    except contacts.NotFound:
        return None


async def send_draft(kind: Literal["message", "call"], row_id: int, ctx: ToolContext) -> SendOut:
    """그 줄이 이 대화의 에이전트 초안이면 문에 한 번 넣고 판정을 돌려준다. 문에 넣기 전에는 읽기만 한다."""
    schedule_id = schedule_for(ctx)
    session = ctx.session
    try:
        row = outreach.get_message(session, schedule_id, row_id) if kind == "message" else \
            outreach.get_call(session, schedule_id, row_id)
    except outreach.NotFound:
        raise ToolError(NOT_YOURS) from None
    if (ctx.chat_session_id is None or row.chat_session_id != ctx.chat_session_id or row.origin != "agent"
            or row.direction != "out" or row.status not in _OPEN[kind]):
        raise ToolError(NOT_YOURS)
    who = _contact(session, schedule_id, row.contact_id)
    user = ctx.user
    actor = Actor("agent", user.id if user else None, AGENT_NAME, user.role if user else None)
    outcome = await gate.dispatch(kind, row_id, actor, now=_now())
    session.expire_all()  # 문이 자기 세션으로 쓴 것을 다시 읽는다(카카오톡이 문자로 나가면 channel 이 바뀐다)
    ctx.emit(AgentEvent("card", {
        "kind": "outreach_sent", "schedule_id": schedule_id, _ID[kind]: row_id, "contact": who,
        "channel": "call" if kind == "call" else row.channel, "outcome": outcome.code, "message": outcome.message,
    }))
    return SendOut(outcome=outcome.code, message=outcome.message, scheduled_at=outcome.scheduled_at)


@tool(
    "notify.send_message",
    "이 대화에서 notify__draft_message 로 만든 문자 초안을 보낸다(문자 또는 카카오톡 권한이 위임일 때 보인다 — 그 초안의 "
    "채널 권한이 위임이어야 나간다): {message_id}. 사용자가 보내라(걸어라)고 한 초안만 보낸다 — 초안만 원하면 부르지 않는다. "
    "시험 모드·수신 거부·근무시간·상한은 보낼 때 다시 본다. 결과 outcome 을 그대로 전한다 — accepted 만 「보냈습니다」, "
    "scheduled 는 예약, unsure 는 「보냈는지 확인 필요」, 그 밖은 막힌 까닭(message). accepted·unsure 뒤에는 같은 초안으로 "
    "다시 부르지 않는다.",
    program="contacts",
    mutates=True,
)
async def send_message(args: SendMessageIn, ctx: ToolContext) -> SendOut:
    return await send_draft("message", args.message_id, ctx)
