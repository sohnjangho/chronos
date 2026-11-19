"""쓰임새(purpose)마다 어느 연결의 어느 모델을 쓸지 푼다.

저장된 배정이 없으면 기본 연결을 가리키는 기본값을 쓴다.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.store.tables import LlmAssignment, LlmConnection

Purpose = Literal["light", "normal", "hard", "longdoc"]

# 쓰임새별 기본 배정: (모델, 라우팅 전략). 기본 연결을 가리킨다.
DEFAULT_ASSIGNMENTS: dict[str, tuple[str, str | None]] = {
    "light": ("liner-claude-router", "cost"),
    "normal": ("liner-claude-router", "balanced"),
    "hard": ("liner-claude-router", "quality"),
    "longdoc": ("liner-mark", None),
}


@dataclass(frozen=True)
class Assignment:
    purpose: str
    connection_id: int | None  # 기본 연결이 없으면 None
    model: str
    routing_strategy: str | None


def default_connection(session: Session) -> LlmConnection | None:
    return session.scalar(select(LlmConnection).where(LlmConnection.is_default))


def resolve_all(session: Session) -> list[Assignment]:
    """네 쓰임새 모두(light·normal·hard·longdoc 순)."""
    stored = {a.purpose: a for a in session.scalars(select(LlmAssignment))}
    default = default_connection(session)
    items = []
    for purpose, (model, strategy) in DEFAULT_ASSIGNMENTS.items():
        found = stored.get(purpose)
        if found is not None:
            items.append(
                Assignment(purpose, found.connection_id, found.model, found.routing_strategy)
            )
        else:
            items.append(Assignment(purpose, default.id if default else None, model, strategy))
    return items


def resolve(session: Session, purpose: str) -> Assignment:
    """한 쓰임새의 배정. 없는 쓰임새면 KeyError."""
    for item in resolve_all(session):
        if item.purpose == purpose:
            return item
    raise KeyError(purpose)
