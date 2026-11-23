"""대화 에이전트의 연락 도구(계획 4 Task 80 — 설계 「글 에이전트 도구」): 사람이 대화 창에서 시킬 때 쓰는 길.

들어온 문자에 답하는 글 에이전트(하네스 도구 묶음)와 다르다. 여기 도구는 읽기와 **초안**뿐이다 — 보내기·걸기는 사람이
[보내기]·[전화 걸기]를 누르거나(위임이면) 나가는 문이 정한다. 이 도구들은 나가는 문을 부르지 않고 send_mode 를 쓰지 않는다.

모든 도구가 지키는 것:
- 현장 관리자면 FIELD_REFUSAL. 일정은 ctx.require_schedule_id() 로만 — 인자로 일정 id 를 받지 않는다.
- 연락처는 그 일정 것만(store.contacts.get_contact). 다른 일정·없는 id 는 같은 NOT_FOUND.
- 초안의 연락 가능 검사(수신 거부·번호·채널)는 메시지 API 의 하나뿐인 검사 `service.check_reachable` 이고, 문자 초안 줄은
  `service.create_agent_draft` 가 만든다([에이전트에게 초안 맡기기]와 같은 함수). 그 ApiError 는 refusal() 로 ToolError 가 된다.
- 결과·카드에 전화번호(가린 꼴도)·키·Account ID 를 싣지 않는다. 메모(note)·수신 거부 까닭(dnc_reason)은 싣지 않는다.
  이름·담당·협력사·공종도 자유 글이라 hide_phones 를 거쳐 싣는다(리뷰 판정 17·18 — 첫째 줄은 싣지 않기).
"""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach.redact import hide_phones
from app.programs.outreach import service
from app.store import contacts
from app.store.schedules import NotFound, load
from app.store.tables_outreach import Contact
from app.tools.context import ToolContext, ToolError

AGENT_NAME = service.AGENT_NAME  # 초안의 origin_name
FIELD_REFUSAL = "현장 관리자는 연락처를 쓸 수 없습니다."
NOT_FOUND = "연락처를 찾을 수 없습니다."
NO_ACTIVITY = "작업을 찾을 수 없습니다. 작업 id 는 일정 도구로 확인하세요."
HIDDEN_CHARS = "글에 보이지 않는 제어 글자나 글 방향을 바꾸는 글자가 있습니다. 빼고 다시 써 주세요."
_TOOL_TEXT = {service.BAD_TEXT: HIDDEN_CHARS, service.ACTIVITY_NOT_FOUND: NO_ACTIVITY}  # 도구가 전부터 쓰던 글


def schedule_for(ctx: ToolContext) -> int:
    """현장 관리자는 거절하고, 지금 일정 id 를 준다."""
    if ctx.user is not None and ctx.user.role == "field":
        raise ToolError(FIELD_REFUSAL)
    return ctx.require_schedule_id()


def contact_in(session: Session, schedule_id: int, contact_id: int) -> Contact:
    """그 일정의 연락처. 아니면 NOT_FOUND(다른 일정과 없는 id 가 같은 글)."""
    try:
        return contacts.get_contact(session, schedule_id, contact_id)
    except contacts.NotFound:
        raise ToolError(NOT_FOUND) from None


def refusal(error: ApiError) -> ToolError:
    """메시지 API 서비스의 거절 → 도구의 거절(글은 고정 한국어 — 번호·까닭 없음). 도구가 전부터 다르게 쓰던 두 글만 바꾼다."""
    return ToolError(_TOOL_TEXT.get(error.message, error.message))


def check_activity(session: Session, schedule_id: int, activity_id: str | None) -> None:
    """작업 id 는 지금 버전의 작업이어야 한다."""
    if activity_id is None:
        return
    try:
        schedule, _, _ = load(session, schedule_id)
    except NotFound:
        raise ToolError(NO_ACTIVITY) from None
    if activity_id not in {a.id for a in schedule.activities}:
        raise ToolError(NO_ACTIVITY)


def company_of(session: Session, who: Contact) -> tuple[str, str]:
    """(협력사 이름, 공종) — 번호를 가린 꼴."""
    try:
        firm = contacts.get_company(session, who.schedule_id, who.company_id)
    except contacts.NotFound:
        return "", ""
    return hide_phones(firm.name), hide_phones(firm.trade)


def card_contact(session: Session, who: Contact) -> dict:
    """카드의 contact {id, name, role_title, company} — 번호 없음."""
    return {"id": who.id, "name": hide_phones(who.name), "role_title": hide_phones(who.role_title),
            "company": company_of(session, who)[0]}
