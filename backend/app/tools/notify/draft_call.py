"""notify.draft_call — 전화 초안 하나를 만든다(걸지 않는다). 걸기는 사람이 [전화 걸기]를 누르거나(위임이면) 문이 정한다.

줄: origin "agent" · origin_name "에이전트" · status "draft" · language 는 연락처의 언어 · chat_session_id 는 이 대화 ·
send_mode·approved_by 는 비움. 나가는 문을 부르지 않는다. 만들기 전에 거절하는 것(줄을 만들지 않음): 수신 거부 · 쓸 번호
없음 · 전화를 받을 수 없음(걸 수 없는 번호 또는 전화 받기 꺼짐) — 이 셋은 문자 초안과 같은 하나뿐인 검사
`service.check_reachable(…, "call")` — · 글의 보이지 않는 글자(`service.check_body`) · 글에 든 번호(통화 API 와 같은 검사
`hide_phones(글) != 글` · 같은 글 — 사람은 가린 글을 승인하는데 음성 에이전트가 번호를 받는 일이 없게) · 없는 작업.
AI 전화 설정(음성 설정 — Task 90)이 아직 없거나 상태가 ok 가 아니면 초안은 만들되 note 에 그렇다고 적는다.
결과·카드에 번호가 없다. 카드 card{kind:"outreach_call_draft", …}.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.errors import ApiError
from app.outreach import policy
from app.outreach.redact import hide_phones
from app.programs.outreach import calls_service, service
from app.programs.outreach.schemas import ActivityId, Nfc
from app.store import outreach
from app.store.tables_outreach import OutreachCall, VoiceSettings
from app.tools.context import ToolContext
from app.tools.notify import (
    AGENT_NAME,
    card_contact,
    check_activity,
    refusal,
    schedule_for,
)
from app.tools.registry import tool

PURPOSE_MAX = 200
ITEM_MAX = 200  # 질문·피할 말 하나의 길이
NOT_PLACED = "초안만 만들었습니다 — 아직 전화를 걸지 않았습니다."
ASK_TO_PRESS = "사람이 [전화 걸기]를 눌러야 겁니다."
DELEGATED = "전화는 위임이지만, 걸 때 시험 모드·수신 거부·근무시간·상한을 다시 봅니다. 사람이 [전화 걸기]를 눌러도 됩니다."
NOT_READY = "알림 연결이 아직 준비되지 않아 지금은 걸 수 없습니다."
VOICE_NOT_READY = "AI 전화 설정(설정 → 알림 연결 → AI 전화)이 끝나야 걸 수 있습니다."

Text = Annotated[str, Nfc, Field(min_length=1, max_length=ITEM_MAX)]


class DraftCallIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: int = Field(description="contacts__list 가 준 contact_id")
    purpose: Annotated[str, Nfc, Field(min_length=1, max_length=PURPOSE_MAX)] = Field(description="통화 목적(한 줄)")
    questions: list[Text] = Field(min_length=1, max_length=5, description="물을 것(1~5개)")
    avoid: list[Text] = Field(default_factory=list, max_length=5, description="말하지 않을 것(0~5개)")
    activity_id: ActivityId | None = Field(default=None, description="이 통화가 걸린 작업 id(있으면)")


class DraftCallOut(BaseModel):
    call_id: int
    status: Literal["draft"]
    language: str  # 통화 언어(연락처의 언어)
    needs_approval: bool  # 전화가 「승인 받기」(사람이 [전화 걸기]를 눌러야 함)
    note: str  # 모델에게: 걸지 않았다는 것과 다음 할 일


def _voice_ready(session, conn_id: int | None) -> bool:
    found = None if conn_id is None else session.get(VoiceSettings, conn_id)
    return found is not None and found.status == "ok" and bool(found.agent_number)


@tool(
    "notify.draft_call",
    "AI 전화 초안을 만든다(걸지 않는다): {contact_id, purpose, questions(1~5), avoid?(0~5), activity_id?}. "
    "사람이 [전화 걸기]를 눌러야 건다. 번호는 코드가 붙인다. 수신 거부·번호 없음·걸 수 없는 번호면 거절한다.",
    program="contacts",
    mutates=True,
)
def draft_call(args: DraftCallIn, ctx: ToolContext) -> DraftCallOut:
    schedule_id = schedule_for(ctx)
    session = ctx.session
    try:
        who = service.check_reachable(session, schedule_id, args.contact_id, "call")
        service.check_body(args.purpose, *args.questions, *args.avoid)
        if any(hide_phones(text) != text for text in (args.purpose, *args.questions, *args.avoid)):
            raise ApiError(422, "has_phone", calls_service.HAS_PHONE)
    except ApiError as e:
        raise refusal(e) from None
    check_activity(session, schedule_id, args.activity_id)
    row = OutreachCall(
        schedule_id=schedule_id, contact_id=who.id, direction="out", purpose=args.purpose,
        questions_json=list(args.questions), avoid_json=list(args.avoid), language=who.language, origin="agent",
        origin_name=AGENT_NAME, status="draft", activity_id=args.activity_id, chat_session_id=ctx.chat_session_id,
    )
    session.add(row)
    session.flush()
    conn = outreach.connection(session)
    rules = policy.for_agent(session)
    needs_approval = rules.call != "delegate"
    ctx.emit(AgentEvent("card", {
        "kind": "outreach_call_draft", "schedule_id": schedule_id, "call_id": row.id,
        "contact": card_contact(session, who), "purpose": hide_phones(row.purpose),
        "questions": [hide_phones(q) for q in row.questions_json], "avoid": [hide_phones(a) for a in row.avoid_json], "language": row.language, "needs_approval": needs_approval,
    }))
    parts = [NOT_PLACED, ASK_TO_PRESS if needs_approval else DELEGATED]
    parts += [] if rules.ready else [NOT_READY]
    parts += [] if _voice_ready(session, conn.id if conn else None) else [VOICE_NOT_READY]
    return DraftCallOut(call_id=row.id, status="draft", language=row.language, needs_approval=needs_approval,
                        note=" ".join(parts))
