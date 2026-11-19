"""대화 저장: 대화(chat_sessions)와 메시지(chat_messages).

메시지 content_json 모양(role 별):
- user:      {"kind": "text", "text"} | {"kind": "questionnaire_submitted", "questionnaire_id", "answers", "assumed"}
- assistant: {"kind": "text", "text"} | {"kind": "tool_calls", "text", "tool_calls": [{"id", "name", "arguments"}]}
             (name 은 등록부 이름, arguments 는 LLM 에 다시 보낼 JSON 글)
- tool:      {"kind": "tool_result", "tool_call_id", "name", "ok", "content"}  (content 는 LLM 에 보낸 글)
- event:     {"type": "card" | "questionnaire" | "approval", "data": {...}}  (도구가 낸 화면 사건. 모델에는 보내지 않는다)
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.store.schedules import NotFound
from app.store.tables import ChatMessage, ChatSession

__all__ = [
    "NotFound", "add_message", "create_chat", "get_chat", "list_chats", "messages", "recent_messages", "was_resumed",
]


def create_chat(session: Session, *, user_id: int, schedule_id: int | None = None) -> ChatSession:
    """새 대화(제목은 빈 글). commit 한다."""
    chat = ChatSession(user_id=user_id, schedule_id=schedule_id, title="")
    session.add(chat)
    session.commit()
    return chat


def get_chat(session: Session, chat_id: int) -> ChatSession:
    """대화 한 줄. 없으면 NotFound."""
    chat = session.get(ChatSession, chat_id)
    if chat is None:
        raise NotFound(chat_id)
    return chat


def list_chats(session: Session, user_id: int) -> list[ChatSession]:
    """그 사용자의 대화, 새것부터."""
    return list(session.scalars(select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.id.desc())))


def add_message(session: Session, chat_id: int, role: str, content: dict) -> ChatMessage:
    """메시지 한 줄을 더한다. commit 하지 않는다(부르는 쪽이 한다)."""
    message = ChatMessage(session_id=chat_id, role=role, content_json=content)
    session.add(message)
    return message


def messages(session: Session, chat_id: int) -> list[ChatMessage]:
    """대화의 모든 메시지, 오래된 것부터."""
    query = select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id)
    return list(session.scalars(query))


def recent_messages(session: Session, chat_id: int, limit: int) -> list[ChatMessage]:
    """모델이 볼 메시지(event 제외) 가운데 마지막 limit 개, 오래된 것부터."""
    query = (
        select(ChatMessage)
        .where(ChatMessage.session_id == chat_id, ChatMessage.role != "event")
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(session.scalars(query).all()))


def was_resumed(session: Session, chat_id: int, questionnaire_id: int) -> bool:
    """이 질문지 제출로 이미 턴을 이어 갔는가(questionnaire_submitted 메시지가 있는가)."""
    query = select(ChatMessage.content_json).where(ChatMessage.session_id == chat_id, ChatMessage.role == "user")
    return any(
        c.get("kind") == "questionnaire_submitted" and c.get("questionnaire_id") == questionnaire_id
        for c in session.scalars(query)
    )
