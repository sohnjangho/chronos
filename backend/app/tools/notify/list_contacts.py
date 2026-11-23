"""contacts.list — 지금 일정의 주소록에서 사람 찾기(이름·담당·협력사·공종). 숨긴 사람·숨긴 협력사는 뺀다.

번호는 주지 않는다 — has_phone 과 받을 수 있는 채널(channels: 연락처의 깃발이 켜져 있고 번호 종류가 그 채널을 받는 것)만.
do_not_contact 는 이 줄의 표시 또는 그 번호의 수신 거부(번호 기준 — 다른 일정에서 표시한 것도). 메모·까닭은 싣지 않는다.
working_now 는 지금(서울) 그 사람의 근무시간 안인가(없으면 일정 달력의 기본 근무시간).
"""

import unicodedata
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.outreach import hours, phone
from app.outreach.redact import hide_phones
from app.store import contacts, outreach
from app.tools.context import ToolContext
from app.tools.notify import schedule_for
from app.tools.registry import tool

_CHANNELS = (("sms", "can_sms", phone.can_sms), ("kakao", "can_kakao", phone.can_sms), ("call", "can_call", phone.can_call))


def _now() -> datetime:
    return datetime.now(UTC)


class ListContactsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=100, description="이름·담당·협력사·공종에 든 말(없으면 모두)")
    limit: int = Field(default=10, ge=1, le=20, description="돌려줄 사람 수(1~20)")


class ContactItem(BaseModel):
    contact_id: int
    name: str
    role_title: str
    company: str
    trade: str  # 공종
    channels: list[str]  # sms | kakao | call 가운데 받을 수 있는 것
    has_phone: bool
    working_now: bool
    language: str
    do_not_contact: bool


class ListContactsOut(BaseModel):
    total: int  # 맞는 사람 수(items 는 그 가운데 앞 limit 명)
    items: list[ContactItem]


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


@tool(
    "contacts.list",
    "지금 일정의 주소록에서 사람을 찾는다: {query?(이름·담당·협력사·공종), limit?}. contact_id 와 받을 수 있는 채널·"
    "근무 중인지·언어·수신 거부를 준다. 전화번호는 주지 않는다.",
    program="contacts",
)
def list_contacts(args: ListContactsIn, ctx: ToolContext) -> ListContactsOut:
    schedule_id = schedule_for(ctx)
    session = ctx.session
    q = _fold(args.query.strip()) if args.query and args.query.strip() else None
    found = []
    for firm, people in contacts.listed(session, schedule_id):
        for who in people:
            if q is None or any(q in _fold(text) for text in (who.name, who.role_title, firm.name, firm.trade)):
                found.append((firm, who))
    if q is not None:  # 이름이 물은 말과 같은 사람 먼저(나머지는 협력사·이름 순 그대로)
        found.sort(key=lambda pair: _fold(pair[1].name) != q)
    shown = found[: args.limit]
    refused = outreach.do_not_contact_numbers(session, [w.phone for _, w in shown if w.phone])
    calendar, now = contacts.calendar_of(session, schedule_id), _now()
    items = []
    for firm, who in shown:
        number = phone.normalize(who.phone)
        usable = number is not None and not who.phone_invalid
        items.append(ContactItem(
            contact_id=who.id, name=hide_phones(who.name), role_title=hide_phones(who.role_title),
            company=hide_phones(firm.name), trade=hide_phones(firm.trade),
            channels=[name for name, flag, able in _CHANNELS if usable and getattr(who, flag) and able(number)],
            has_phone=usable, working_now=hours.is_working(who.hours_json, calendar, now), language=who.language,
            do_not_contact=bool(who.do_not_contact) or number in refused,
        ))
    return ListContactsOut(total=len(found), items=items)
