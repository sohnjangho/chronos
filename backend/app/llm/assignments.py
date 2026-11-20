"""쓰임새(purpose)마다 어느 연결의 어느 모델을 쓸지 푼다.

저장된 배정이 없으면 기본 연결을 가리키는 기본값을 쓴다.
대화마다 고른 모델(chat_sessions 의 모델 칸)은 에이전트 루프의 대화 호출(normal)에만 쓴다(설계 5-5).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.store.tables import ChatSession, LlmAssignment, LlmConnection

Purpose = Literal["light", "normal", "hard", "longdoc", "vision", "embedding"]

# 쓰임새별 기본 배정: (모델, 라우팅 전략). 기본 연결을 가리킨다.
DEFAULT_ASSIGNMENTS: dict[str, tuple[str, str | None]] = {
    "light": ("liner-claude-router", "cost"),
    "normal": ("liner-claude-router", "balanced"),
    "hard": ("liner-claude-router", "quality"),
    "longdoc": ("liner-mark", None),
    "vision": ("liner-claude-router", "balanced"),  # 그림 읽기(계획 3)
    "embedding": ("openai/text-embedding-3-small", None),  # 임베딩(계획 3)
}
# 설정 화면 「작업별 모델 배정」 표에 나오는 쓰임새(차례 그대로).
TABLE_PURPOSES = ("light", "normal", "hard", "longdoc", "vision", "embedding")


@dataclass(frozen=True)
class Assignment:
    purpose: str
    connection_id: int | None  # 기본 연결이 없으면 None
    model: str
    routing_strategy: str | None


def default_connection(session: Session) -> LlmConnection | None:
    return session.scalar(select(LlmConnection).where(LlmConnection.is_default))


def _resolve(stored: dict[str, LlmAssignment], default: LlmConnection | None, purpose: str) -> Assignment:
    found = stored.get(purpose)
    if found is not None:
        return Assignment(purpose, found.connection_id, found.model, found.routing_strategy)
    model, strategy = DEFAULT_ASSIGNMENTS[purpose]
    return Assignment(purpose, default.id if default else None, model, strategy)


def resolve_all(session: Session) -> list[Assignment]:
    """배정 표의 여섯 쓰임새(light·normal·hard·longdoc·vision·embedding 순, TABLE_PURPOSES)."""
    stored = {a.purpose: a for a in session.scalars(select(LlmAssignment))}
    default = default_connection(session)
    return [_resolve(stored, default, purpose) for purpose in TABLE_PURPOSES]


# 지금 실행 맥락에서 normal 대신 쓸 배정(대화 모델). using_chat_model 안에서 만든 asyncio 작업만 본다.
_chat_override: ContextVar[Assignment | None] = ContextVar("chat_model_override", default=None)


@contextmanager
def using_chat_model(assignment: Assignment | None) -> Iterator[None]:
    """블록 안에서 resolve(…, "normal") 이 assignment 를 돌려준다(None 이면 그대로).

    에이전트 루프가 대화 호출 작업을 만들 때만 두른다 — 작업은 만들 때의 맥락을 복사하므로
    그 호출에만 닿고, 도구 안의 호출(hard·light·normal)은 배정 그대로다.
    """
    token = _chat_override.set(assignment)
    try:
        yield
    finally:
        _chat_override.reset(token)


def chat_model(session: Session, chat_id: int) -> Assignment | None:
    """그 대화에서 고른 모델(purpose normal). 고르지 않았거나 연결이 지워졌으면 None(→ 설정 배정)."""
    chat = session.get(ChatSession, chat_id)
    if chat is None or chat.model_name is None or chat.model_connection_id is None:
        return None
    if session.get(LlmConnection, chat.model_connection_id) is None:
        return None
    return Assignment("normal", chat.model_connection_id, chat.model_name, chat.model_routing)


def resolve(session: Session, purpose: str) -> Assignment:
    """한 쓰임새의 배정(vision·embedding 포함). 없는 쓰임새면 KeyError.

    using_chat_model 안의 normal 은 그 대화 모델.
    """
    if purpose not in DEFAULT_ASSIGNMENTS:
        raise KeyError(purpose)
    override = _chat_override.get()
    if purpose == "normal" and override is not None:
        return override
    found = session.get(LlmAssignment, purpose)
    return _resolve({purpose: found} if found else {}, default_connection(session), purpose)
