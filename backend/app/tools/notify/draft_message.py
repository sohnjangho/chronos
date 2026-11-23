"""notify.draft_message — 문자 초안 하나를 만든다(보내지 않는다).

줄은 메시지 API 의 공용 함수 `service.create_agent_draft` 가 만든다(origin "agent" · origin_name "에이전트" · status "draft" ·
chat_session_id 는 이 대화 · send_mode·approved_by 비움 · flush 까지). 연락 가능 검사(수신 거부·번호·카카오톡 통로·문자/카카오톡
받기 — `service.check_reachable`)·글자 검사(본문·번역·문안 값)·작업 검사도 그 함수가 하고, 거절이면 줄을 만들지 않는다.
나가는 문을 부르지 않는다 — 사람이 [보내기]를 누르면(위임이면 보낼 때) 문이 처음부터 본다.
도구에 남는 것: 문안 규칙(문자 초안의 template_* 거절 · 카카오톡 template_use 는 기본 연결의 승인된 문안), body 없음,
needs_approval·note·카드. 결과·카드에 번호가 없다. 카드 card{kind:"outreach_draft", …}.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.errors import ApiError
from app.outreach import policy
from app.programs.outreach import service
from app.programs.outreach.schemas import ActivityId, Body, VarName, VarValue
from app.store import outreach
from app.store.tables_outreach import KakaoTemplate
from app.tools.context import ToolContext, ToolError
from app.tools.notify import card_contact, refusal, schedule_for
from app.tools.registry import tool

NEED_BODY = "문자 글(body)을 넣어 주세요."
SMS_HAS_NO_TEMPLATE = "알림톡 문안(template_use·template_vars)은 카카오톡 초안에만 씁니다 — 문자는 body 에 글을 넣으세요."
NO_TEMPLATE = "그 용도의 승인된 알림톡 문안이 없습니다 — 문자로 초안을 만드세요."
NOT_SENT = "초안만 만들었습니다 — 아직 보내지 않았습니다."
ASK_TO_PRESS = "사람이 [보내기]를 눌러야 나갑니다."
DELEGATED = "이 채널은 위임이지만, 보낼 때 시험 모드·수신 거부·근무시간·상한을 다시 봅니다. 사람이 [보내기]를 눌러도 됩니다."
NOT_READY = "알림 연결이 아직 준비되지 않아 지금은 나가지 않습니다."


class DraftMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: int = Field(description="contacts__list 가 준 contact_id")
    channel: Literal["sms", "kakao"] = Field(description="sms 문자 · kakao 카카오톡(아직 쓸 수 없음)")
    body: Body | None = Field(default=None, description="보낼 글(상대의 언어로, 1~1000자). 문자는 꼭 넣는다")
    body_ko: Body | None = Field(default=None, description="상대 언어가 한국어가 아니면 body 의 한국어 번역")
    template_use: Annotated[str, Field(min_length=1, max_length=50)] | None = Field(
        default=None, description="카카오톡 알림톡 문안의 용도(카카오톡만)")
    template_vars: Annotated[dict[VarName, VarValue], Field(max_length=20)] | None = Field(
        default=None, description="알림톡 문안의 빈칸 값(카카오톡만)")
    activity_id: ActivityId | None = Field(default=None, description="이 연락이 걸린 작업 id(있으면)")


class DraftMessageOut(BaseModel):
    message_id: int
    status: Literal["draft"]
    needs_approval: bool  # 이 채널이 「승인 받기」(사람이 [보내기]를 눌러야 함)
    note: str  # 모델에게: 보내지 않았다는 것과 다음 할 일


def _template(session: Session, use: str) -> int:
    """기본 연결의 승인된 알림톡 문안 가운데 그 용도의 것(가장 앞 id). 없으면 거절."""
    conn = outreach.connection(session)
    found = None if conn is None else session.scalar(select(KakaoTemplate.id).where(
        KakaoTemplate.connection_id == conn.id, KakaoTemplate.use == use, KakaoTemplate.status == "approved",
    ).order_by(KakaoTemplate.id).limit(1))
    if found is None:
        raise ToolError(NO_TEMPLATE)
    return found


def note_for(needs_approval: bool, ready: bool) -> str:
    parts = [NOT_SENT, ASK_TO_PRESS if needs_approval else DELEGATED]
    return " ".join(parts + ([] if ready else [NOT_READY]))


@tool(
    "notify.draft_message",
    "문자 초안을 만든다(보내지 않는다): {contact_id, channel: sms, body, body_ko?, activity_id?}. 사람이 [보내기]를 "
    "눌러야 나간다. 번호는 코드가 붙인다. 수신 거부·번호 없음·문자를 받을 수 없는 번호면 거절한다.",
    program="contacts",
    mutates=True,
)
def draft_message(args: DraftMessageIn, ctx: ToolContext) -> DraftMessageOut:
    schedule_id = schedule_for(ctx)
    session = ctx.session
    kakao = args.channel == "kakao"
    try:  # 문안·글을 보기 전에 사람·채널부터(거절 차례는 전과 같다). 아무것도 쓰지 않는다
        who = service.check_reachable(session, schedule_id, args.contact_id, args.channel)
        if not kakao and (args.template_use is not None or args.template_vars is not None):
            raise ToolError(SMS_HAS_NO_TEMPLATE)
        template_id = _template(session, args.template_use) if kakao and args.template_use is not None else None
        if args.body is None:
            raise ToolError(NEED_BODY)
        row = service.create_agent_draft(
            session, schedule_id, contact_id=who.id, channel=args.channel, body=args.body, body_ko=args.body_ko,
            activity_id=args.activity_id, template_id=template_id, template_vars=args.template_vars,
            chat_session_id=ctx.chat_session_id)
    except ApiError as e:
        raise refusal(e) from None
    rules = policy.for_agent(session)
    needs_approval = (rules.kakao if kakao else rules.sms) != "delegate"
    ctx.emit(AgentEvent("card", {
        "kind": "outreach_draft", "schedule_id": schedule_id, "message_id": row.id,
        "contact": card_contact(session, who), "channel": row.channel, "body": row.body, "body_ko": row.body_ko,
        "needs_approval": needs_approval,
    }))
    return DraftMessageOut(message_id=row.id, status="draft", needs_approval=needs_approval,
                           note=note_for(needs_approval, rules.ready))
