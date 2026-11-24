"""관리 포인트 위험 줄의 근거 문장(Search Agent) — 뒤에서 채운다.

- 표 point_quotes: (일정, 버전, 액티비티, 갈래 kind) 마다 한 줄. 상태 pending(찾는 중) → ready(문장·링크) | failed(까닭 code).
- fill 은 pending 을 적고 바로 돌아온다. 찾기는 asyncio 작업이 한다(상한 TIMEOUT_S): 부를 곳은 짧은 세션으로 읽고 닫은 뒤
  기다린다(기다리는 동안 DB 연결을 쥐지 않는다). 한꺼번에 MAX_CONCURRENT 개까지만 부른다(Liner 한도·DB 풀).
- 다시 부르는 규칙: ready 는 다시 부르지 않는다. pending 은 찾는 중이라 부르지 않는다. failed(STALE_AFTER 넘은 pending 은
  get 이 failed·stale 로 보인다)는 retry=True 일 때만 다시 부른다 — 화면의 「다시 찾기」만 retry 를 준다.
- **Task 5: fill 은 사람이 [근거 문장 보기]·「다시 찾기」를 눌렀을 때만 부른다. GET·되풀이 조회(polling)에서 부르지 않는다**(부를
  때마다 $0.02). 조회는 get 으로.
- 줄에는 문장·링크·까닭 code 만 둔다(키·받은 글 원문은 두지 않는다). app.db 가 import 해서 create_all 이 표를 만든다.
"""

import asyncio
import logging
import weakref
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
STALE_AFTER = timedelta(seconds=2 * search_agent.TIMEOUT_S)  # 이보다 오래된 찾는 중은 멈춘 것(서버가 다시 켜짐 등)
MAX_CONCURRENT = 3
Status = Literal["pending", "ready", "failed"]
MESSAGES: dict[str, str] = {"pending": "근거 문장 찾는 중", "ready": "", "failed": "근거 문장을 찾지 못했습니다"}

Key = tuple[int, int, str, str]
_tasks: set[asyncio.Task] = set()  # 끝나기 전에 사라지지 않게 쥔다
_inflight: set[Key] = set()  # 이 프로세스에서 찾는 중(이벤트 루프 안에서만 바꾼다)
_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


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


def _state(row: PointQuote) -> QuoteState:
    if row.status == "pending" and datetime.now(UTC) - as_utc(row.updated_at) >= STALE_AFTER:
        return QuoteState("failed", [], "stale")
    found = [AgentQuote(q["text"], q["url"], q["title"]) for q in row.quotes_json or []]
    return QuoteState(row.status, found, row.error_code)  # type: ignore[arg-type]


def get(session: Session, schedule_id: int, version: int, activity_id: str, kind: str) -> QuoteState | None:
    """채운 상태. 아직 부르지 않았으면 None. 멈춘 찾는 중은 failed(stale)."""
    row = session.get(PointQuote, (schedule_id, version, activity_id, kind))
    return None if row is None else _state(row)


def _save(key: Key, status: Status, found: list[AgentQuote], code: str | None) -> None:
    with Session(_engine()) as session:
        row = session.get(PointQuote, key) or PointQuote(schedule_id=key[0], version=key[1], activity_id=key[2], kind=key[3])
        row.status, row.error_code, row.updated_at = status, code, datetime.now(UTC)
        row.quotes_json = [{"text": q.text, "url": q.url, "title": q.title} for q in found]
        session.add(row)
        session.commit()


def _claim(key: Key, retry: bool) -> bool:
    """부를지 정하고, 부르면 pending 을 적는다."""
    with Session(_engine()) as session:
        row = session.get(PointQuote, key)
        state = None if row is None else _state(row)
    if state is not None and (state.status != "failed" or not retry):
        return False
    _save(key, "pending", [], None)
    return True


def _finish(key: Key, found: list[AgentQuote], code: str | None) -> None:
    """결과를 적는다. 적지 못하면 종류만 남기고 failed 로라도 적어 본다(찾는 중으로 남지 않게)."""
    try:
        _save(key, "failed" if code else "ready", found, code)
    except Exception as exc:  # noqa: BLE001 — 예외 글에 SQL·값이 있을 수 있어 종류만 남긴다
        logger.warning("근거 문장 저장 실패: %s", type(exc).__name__)
        try:
            _save(key, "failed", [], "save_error")
        except Exception as again:  # noqa: BLE001
            logger.warning("근거 문장 실패 표시도 못 함: %s", type(again).__name__)


def _prepare():
    with Session(_engine()) as session:  # 짧게 읽고 닫는다 — 기다리는 동안 연결을 쥐지 않는다
        return search_agent.prepare(session)


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if (sem := _slots.get(loop)) is None:
        sem = _slots[loop] = asyncio.Semaphore(MAX_CONCURRENT)
    return sem


async def _run(key: Key, question: str, mode: Literal["general", "scholar"]) -> None:
    found: list[AgentQuote] = []
    code: str | None = None
    try:
        async with _slot():
            target = await asyncio.to_thread(_prepare)
            found = await search_agent.call(target, _engine(), question, mode=mode, timeout=TIMEOUT_S)
    except SearchAgentFailed as exc:
        code = exc.code
    # 뒤 작업은 어떤 일이 있어도 상태를 끝내야 한다(찾는 중으로 남지 않게). 예외 글은 남기지 않고 종류만.
    except Exception as exc:  # noqa: BLE001
        code = "unknown"
        logger.warning("근거 문장 채우기 실패: %s", type(exc).__name__)
    await asyncio.to_thread(_finish, key, found, code)


async def fill(schedule_id: int, version: int, activity_id: str, kind: str, *, question: str,
               mode: Literal["general", "scholar"] = "general", retry: bool = False) -> asyncio.Task | None:
    """찾는 중을 적고 뒤 작업을 띄운다. 부르지 않으면 None(찾는 중·채워짐, 실패인데 retry 가 아님).

    사람이 누른 때만 부른다(GET·되풀이 조회에서 부르지 않는다). 부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 부르지 않는다.
    """
    loop = asyncio.get_running_loop()  # 루프 밖이면 pending 을 적기 전에 실패한다
    key = (schedule_id, version, activity_id, kind)
    if key in _inflight:
        return None
    _inflight.add(key)
    try:
        claimed = await asyncio.to_thread(_claim, key, retry)
    except BaseException:
        _inflight.discard(key)
        raise
    if not claimed:
        _inflight.discard(key)
        return None
    task = loop.create_task(_run(key, question, mode))
    _tasks.add(task)
    task.add_done_callback(lambda t: (_tasks.discard(t), _inflight.discard(key)))
    return task
