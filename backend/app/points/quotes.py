"""관리 포인트 위험 줄의 근거 문장(Search Agent) — 뒤에서 채운다.

- 표 point_quotes: (일정, 버전, 액티비티, 갈래 kind) 마다 한 줄. 상태 pending(찾는 중) → ready(문장·링크) | failed(까닭 code).
- fill 은 pending 을 적고 바로 돌아온다. 찾기는 asyncio 작업이 자기 DB 세션으로 한다(상한 TIMEOUT_S) — 대화·카드를 막지 않는다.
  이미 찾는 중이거나 채워졌으면 다시 부르지 않는다. 실패했거나 오래 멈춘 찾는 중(서버가 다시 켜짐)은 다시 찾는다.
- 줄에는 문장·링크·까닭 code 만 둔다(키·받은 글 원문은 두지 않는다). app.db 가 import 해서 create_all 이 표를 만든다.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.llm import search_agent
from app.llm.search_agent import AgentQuote, SearchAgentFailed
from app.store.tables import Base
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

TIMEOUT_S = search_agent.TIMEOUT_S
STALE_AFTER = timedelta(seconds=TIMEOUT_S + 60)  # 이보다 오래된 찾는 중은 멈춘 것으로 본다
Status = Literal["pending", "ready", "failed"]
MESSAGES: dict[str, str] = {"pending": "근거 문장 찾는 중", "ready": "", "failed": "근거 문장을 찾지 못했습니다"}

_tasks: set[asyncio.Task] = set()  # 끝나기 전에 사라지지 않게 쥔다


class PointQuote(Base):
    __tablename__ = "point_quotes"

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # weather·materials·fx·business
    status: Mapped[str] = mapped_column(String(10))
    quotes_json: Mapped[list] = mapped_column(JSON, default=list)  # [{text, url, title}]
    error_code: Mapped[str | None] = mapped_column(String(20), default=None)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class QuoteState:
    status: Status
    quotes: list[AgentQuote] = field(default_factory=list)
    error_code: str | None = None

    @property
    def message(self) -> str:
        return MESSAGES[self.status]


def _engine():
    # app.db 가 이 모듈을 import 한다 — 돌림 import 를 피해 부를 때 읽는다
    from app.db import current_engine

    return current_engine()


def get(session: Session, schedule_id: int, version: int, activity_id: str, kind: str) -> QuoteState | None:
    """채운 상태. 아직 부르지 않았으면 None."""
    row = session.get(PointQuote, (schedule_id, version, activity_id, kind))
    if row is None:
        return None
    found = [AgentQuote(q["text"], q["url"], q["title"]) for q in row.quotes_json or []]
    return QuoteState(row.status, found, row.error_code)  # type: ignore[arg-type]


def _busy(row: PointQuote | None) -> bool:
    if row is None or row.status == "failed":
        return False
    return row.status == "ready" or datetime.now(UTC) - as_utc(row.updated_at) < STALE_AFTER


def _save(key: tuple[int, int, str, str], status: Status, found: list[AgentQuote], code: str | None) -> None:
    with Session(_engine()) as session:
        row = session.get(PointQuote, key) or PointQuote(schedule_id=key[0], version=key[1], activity_id=key[2], kind=key[3])
        row.status, row.error_code, row.updated_at = status, code, datetime.now(UTC)
        row.quotes_json = [{"text": q.text, "url": q.url, "title": q.title} for q in found]
        session.add(row)
        session.commit()


async def _run(key: tuple[int, int, str, str], question: str, mode: Literal["general", "scholar"]) -> None:
    found: list[AgentQuote] = []
    code: str | None = None
    try:
        with Session(_engine()) as session:
            found = await search_agent.ask(session, question, mode=mode, timeout=TIMEOUT_S)
    except SearchAgentFailed as exc:
        code = exc.code
    # 뒤 작업은 어떤 일이 있어도 상태를 끝내야 한다(찾는 중으로 남지 않게). 예외 글은 남기지 않고 종류만.
    except Exception as exc:  # noqa: BLE001
        code = "unknown"
        logger.warning("근거 문장 채우기 실패: %s", type(exc).__name__)
    await asyncio.to_thread(_save, key, "failed" if code else "ready", found, code)


def fill(schedule_id: int, version: int, activity_id: str, kind: str, *, question: str,
         mode: Literal["general", "scholar"] = "general") -> asyncio.Task | None:
    """찾는 중을 적고 뒤 작업을 띄운다(실행 중인 이벤트 루프에서 부른다). 이미 찾는 중·채워졌으면 None.

    부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 부르지 않는다(찾는 중을 적는 따로 연 세션이 잠금을 기다린다).
    """
    key = (schedule_id, version, activity_id, kind)
    with Session(_engine()) as session:
        if _busy(session.get(PointQuote, key)):
            return None
    _save(key, "pending", [], None)
    task = asyncio.get_running_loop().create_task(_run(key, question, mode))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
