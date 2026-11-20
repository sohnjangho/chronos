"""쓰임새(purpose)마다 어느 연결의 어느 모델을 쓸지 푼다.

저장된 배정이 없으면 기본 연결을 가리키는 기본값을 쓴다.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.store.tables import LlmAssignment, LlmConnection

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
# 설정 화면 「작업별 모델 배정」 표에 나오는 쓰임새. vision·embedding 줄은 Task 52 가 표(API·화면)에 더한다.
TABLE_PURPOSES = ("light", "normal", "hard", "longdoc")


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
    """배정 표의 네 쓰임새(light·normal·hard·longdoc 순, TABLE_PURPOSES)."""
    stored = {a.purpose: a for a in session.scalars(select(LlmAssignment))}
    default = default_connection(session)
    return [_resolve(stored, default, purpose) for purpose in TABLE_PURPOSES]


def resolve(session: Session, purpose: str) -> Assignment:
    """한 쓰임새의 배정(vision·embedding 포함). 없는 쓰임새면 KeyError."""
    if purpose not in DEFAULT_ASSIGNMENTS:
        raise KeyError(purpose)
    found = session.get(LlmAssignment, purpose)
    return _resolve({purpose: found} if found else {}, default_connection(session), purpose)
