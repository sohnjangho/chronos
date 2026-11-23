"""notify.status — 지금 일정의 최근 연락(문자·통화)과 열린 보고 수. contact_id 를 주면 그 사람 것만.

상태 값은 이름표 그대로(문자 draft·scheduled·sending·accepted·delivered·failed·unconfirmed·blocked_test·received,
통화 draft·…·completed·no_answer …). 글·요약은 hide_phones 를 거쳐 앞 TEXT_LIMIT 자 — 받은 문자에는 상대가 적은 번호가
있을 수 있다. 다른 일정의 줄·일정 없는 줄(주소록에 없는 번호)은 보이지 않는다. 판정 까닭·사건은 싣지 않는다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.outreach.redact import hide_phones
from app.store.tables_outreach import ContactReport, OutreachCall, OutreachMessage
from app.store.timeutil import as_utc
from app.tools.context import ToolContext
from app.tools.notify import contact_in, schedule_for
from app.tools.registry import tool

TEXT_LIMIT = 200


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: int | None = Field(default=None, description="이 사람 것만(없으면 지금 일정 전체)")
    limit: int = Field(default=5, ge=1, le=10, description="문자·통화 각각 최근 몇 건(1~10)")


class MessageLine(BaseModel):
    id: int
    contact_id: int | None
    direction: str  # out 보냄 · in 받음
    channel: str
    status: str
    at: datetime  # 도착·보낸·만든 시각 가운데 가장 나중 것(UTC)
    text: str


class CallLine(BaseModel):
    id: int
    contact_id: int | None
    direction: str
    status: str
    at: datetime  # 끝난·시작한·만든 시각 가운데 가장 나중 것(UTC)
    summary: str


class StatusOut(BaseModel):
    messages: list[MessageLine]  # 최근 것부터
    calls: list[CallLine]
    reports_open: int  # 사람이 아직 확인하지 않은 보고(문자·전화로 받은 것)


def _clip(text: str | None) -> str:
    return hide_phones(text or "")[:TEXT_LIMIT]


@tool(
    "notify.status",
    "지금 일정의 최근 문자·통화 상태와 확인하지 않은 보고 수를 본다: {contact_id?, limit?}. "
    "status: accepted·delivered 보냄 · failed 실패 · unconfirmed 확인 필요(다시 보내지 않는다) · draft 초안.",
    program="contacts",
)
def status(args: StatusIn, ctx: ToolContext) -> StatusOut:
    schedule_id = schedule_for(ctx)
    session = ctx.session
    if args.contact_id is not None:
        contact_in(session, schedule_id, args.contact_id)
    mine = [OutreachMessage.schedule_id == schedule_id]
    calls_mine = [OutreachCall.schedule_id == schedule_id]
    reports = [ContactReport.schedule_id == schedule_id, ContactReport.status == "open"]
    if args.contact_id is not None:
        mine.append(OutreachMessage.contact_id == args.contact_id)
        calls_mine.append(OutreachCall.contact_id == args.contact_id)
        reports.append(ContactReport.contact_id == args.contact_id)
    messages = session.scalars(select(OutreachMessage).where(*mine).order_by(OutreachMessage.id.desc()).limit(args.limit))
    calls = session.scalars(select(OutreachCall).where(*calls_mine).order_by(OutreachCall.id.desc()).limit(args.limit))
    return StatusOut(
        messages=[MessageLine(id=m.id, contact_id=m.contact_id, direction=m.direction, channel=m.channel,
                              status=m.status, at=as_utc(m.delivered_at or m.sent_at or m.created_at),
                              text=_clip(m.body)) for m in messages],
        calls=[CallLine(id=c.id, contact_id=c.contact_id, direction=c.direction, status=c.status,
                        at=as_utc(c.ended_at or c.started_at or c.created_at), summary=_clip(c.summary_ko))
               for c in calls],
        reports_open=session.scalar(select(func.count()).select_from(ContactReport).where(*reports)) or 0,
    )
