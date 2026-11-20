"""근거 목록: 일정(과 그 일정을 만든 초안)에 붙은 근거, 또는 한 대화의 검색이 찾은 근거.

거르기는 schedule_id 와 chat_session_id 가운데 정확히 하나(아니면 422 invalid_request).
일정은 로그인한 누구나, 대화는 만든 사용자만 본다(다른 사람에게는 404).
"""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.evidence.schemas import EvidenceOut, LinkOut
from app.store import chats
from app.store.evidence import Found, for_chat, for_schedule
from app.store.schedules import NotFound, get_record
from app.store.tables import User

ONE_FILTER_MESSAGE = "schedule_id 와 chat_session_id 가운데 하나만 주세요."
SCHEDULE_NOT_FOUND = "일정을 찾을 수 없습니다."
CHAT_NOT_FOUND = "대화를 찾을 수 없습니다."


def _out(f: Found) -> EvidenceOut:
    i = f.item
    return EvidenceOut(
        id=i.id, title=i.title, url=i.url, hostname=i.hostname, description=i.description, date=i.published,
        mode=f.search.mode, query=f.search.query,
        links=[LinkOut(condition_id=x.condition_id, assumption_label=x.assumption_label) for x in f.links],
    )


def _schedule(session: Session, schedule_id: int) -> list[Found]:
    try:
        get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND) from None
    return for_schedule(session, schedule_id)


def _chat(session: Session, user: User, chat_id: int) -> list[Found]:
    try:
        chat = chats.get_chat(session, chat_id)
    except chats.NotFound:
        chat = None
    if chat is None or chat.user_id != user.id:
        raise ApiError(404, "not_found", CHAT_NOT_FOUND)
    return for_chat(session, chat_id)


def list_evidence(session: Session, user: User, schedule_id: int | None, chat_session_id: int | None) -> list[EvidenceOut]:
    if (schedule_id is None) == (chat_session_id is None):
        raise ApiError(422, "invalid_request", ONE_FILTER_MESSAGE)
    found = _schedule(session, schedule_id) if schedule_id is not None else _chat(session, user, chat_session_id)
    return [_out(f) for f in found]
