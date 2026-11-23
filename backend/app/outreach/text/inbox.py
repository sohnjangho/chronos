"""들어온 문자를 응대(responder.handle)에 넘기는 줄(Task 84 — Task 71 의 자리를 채움).

- **넘기기**: 일꾼(app.outreach.worker)이 받기 판정이 engage·notice 인 문자를 저장·commit 한 뒤 이벤트 루프에서
  `inbox.enqueue(message_id)` 를 부른다(모듈 속성으로 — 시험이 바꿔 끼운다). 받기 판정·수신 거부는 일꾼이 이미 했다 — 여기서도
  응대에서도 다시 하지 않는다. enqueue 는 id 를 메모리 줄(QUEUE_MAX 까지 — 넘치면 버리고 쓸기가 찾는다)에 넣고 응대 작업을
  하나 띄운다(이미 돌면 그것이 이어서 꺼낸다). **일꾼 고리가 돌 때만**(worker.status()["running"]) 넘긴다 — 일꾼을 끈 서버·
  손으로 돌린 한 바퀴(시험·콘솔)에서는 아무것도 하지 않고, 응대는 부른 쪽이 drain 으로 한다.
- **쓸기**(enqueue 만 믿지 않는다 — 넘기기는 판정이 commit 된 뒤 메모리에서 일어나 그 사이 서버가 꺼지면 잃는다): 응대 작업이
  시작할 때마다(drain) 먼저 DB 에서 「받기 판정이 engage·notice(`admission` allowed)이고 아직 잡히지 않은(claimed_at 없음) 받은
  줄」을 LOOKBACK_S 안에서 오래된 차례로 SWEEP_ROWS 줄까지 찾아 줄 앞에 넣는다. 같은 때 「잡힌 채 답도 까닭도 없이
  responder.CLAIM_STALE_S 가 지난 줄」(응대 중에 프로세스가 죽음)을 SWEEP_ROWS 줄까지 `reply_failed`(INTERRUPTED)로 닫는다 —
  다시 답하지는 않는다(도구가 이미 무언가를 남겼을 수 있다).
- **한 번만 답한다**: 줄에 같은 id 가 두 번 들어가도, 넘기기와 쓸기가 겹쳐도, 같은 DB 에 일꾼이 둘이어도 — 응대는 받은 줄의
  claimed_at 을 조건부 UPDATE 한 문장으로 잡은 쪽만 답한다(SQLite 가 쓰기를 한 줄로 세우므로 둘 가운데 하나만 바뀐 줄 1).
- 응대 작업은 줄이 빌 때까지 하나씩 꺼내(같은 번호는 응대 안에서도 차례로) 끝나면 스스로 멈춘다 — 남아 도는 것이 없다.
  한 건의 예외는 그 건만 끝낸다. 기다리지 않는다: 프로세스를 닫을 때 끊긴 응대는 다음 쓸기가 닫는다.
- **남은 구멍**: 쓸기는 응대 작업이 시작할 때(새 문자가 넘어올 때·drain·kick) 돈다. 서버가 다시 뜬 뒤 새 문자가 오기 전에는
  잃은 줄을 찾지 않는다 — 일꾼 바퀴(worker.tick)나 lifespan 이 `inbox.kick()` 을 한 줄 부르면 바퀴마다 쓴다(그 파일은 Task 71 것).
"""

import asyncio
import logging
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func, literal_column, not_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.outreach.harness import events
from app.outreach.harness.types import Ref
from app.store.tables_outreach import OutreachMessage
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

QUEUE_MAX = 200  # 메모리 줄의 길이(넘치면 버린다 — 쓸기가 찾는다)
SWEEP_ROWS = 20  # 쓸기 한 번에 찾는 줄(답할 줄 · 멈춘 줄 각각)
LOOKBACK_S = 7 * 24 * 3600  # 쓸기가 보는 받은 줄의 나이(그보다 오래된 줄은 사람에게)

_M = OutreachMessage
_pending: deque[int] = deque()
_task: asyncio.Task | None = None


def _db():
    return contextmanager(get_session)()


def _answering() -> bool:
    # 일꾼이 이 모듈을 불러오므로 일꾼은 여기서(부를 때) 읽는다
    from app.outreach import worker

    return bool(worker.status()["running"])


def _put(message_id: int) -> None:
    if message_id not in _pending and len(_pending) < QUEUE_MAX:
        _pending.append(message_id)


def enqueue(message_id: int) -> None:
    """받은 문자 한 건을 응대 줄에 넣고 응대 작업을 띄운다(일꾼 고리가 돌 때만 — 모듈 머리 글). 예외를 올리지 않는다."""
    if type(message_id) is not int or not _answering():
        return
    _put(message_id)
    _start()


def kick() -> None:
    """응대 작업을 띄운다(쓸기부터) — 일꾼 고리가 돌 때만, 이벤트 루프 안에서만."""
    if _answering():
        _start()


def _start() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 루프 밖(스레드)에서 불림 — 다음 쓸기가 찾는다
        return
    _task = loop.create_task(_run(), name="outreach-text-inbox")


async def _run() -> None:
    try:
        await drain()
    except Exception as exc:  # noqa: BLE001 — 응대 작업이 무엇으로 깨져도 일꾼에는 닿지 않는다
        logger.warning("들어온 문자 응대 작업이 오류로 끝났습니다 (%s)", type(exc).__name__)


async def drain(*, now: datetime | None = None) -> int:
    """쓸고(모듈 머리 글) 줄이 빌 때까지 하나씩 응대한다. 꺼낸 수를 준다. now 는 시험·대본의 시각(없으면 지금)."""
    from app.outreach.text import (
        responder,  # 응대 모듈은 무겁다 — 일꾼을 불러오는 모든 곳이 끌어오지 않게
    )

    at = datetime.now(UTC) if now is None else as_utc(now)
    try:
        found = await asyncio.to_thread(_sweep, at)
    except Exception as exc:  # noqa: BLE001 — 쓸기가 안 돼도 넘어온 줄은 답한다
        logger.warning("들어온 문자 쓸기가 오류로 끝났습니다 (%s)", type(exc).__name__)
        found = []
    for message_id in reversed(found):  # 쓸어 찾은 것(오래된 것)이 앞
        if message_id not in _pending:
            _pending.appendleft(message_id)
    while len(_pending) > QUEUE_MAX + SWEEP_ROWS:
        _pending.pop()
    handled = 0
    while _pending:
        message_id = _pending.popleft()
        handled += 1
        try:
            await responder.handle(message_id, now=now)
        except Exception as exc:  # noqa: BLE001 — handle 은 스스로 잡지만, 그것마저 깨져도 다음 건으로
            logger.warning("들어온 문자 응대가 오류로 끝났습니다 (%s)", type(exc).__name__)
    return handled


async def idle() -> None:
    """떠 있는 응대 작업이 끝나기를 기다린다(시험·콘솔)."""
    task = _task
    if task is not None:
        await task


def _pending_count() -> int:
    return len(_pending)


# ── 쓸기(스레드에서) ─────────────────────────────────────────────────


def _has_event(rule: str, verdict: str | None = None, details: tuple[str, ...] = ()):
    """그 줄의 사건(harness_json) 가운데 그 이름(·판정·detail)이 있는가 — SQLite json_each."""
    log = func.json_each(_M.harness_json).table_valued("value").alias("log")
    where = [func.json_extract(log.c.value, "$.rule") == rule]
    if verdict is not None:
        where.append(func.json_extract(log.c.value, "$.verdict") == verdict)
    if details:
        where.append(func.json_extract(log.c.value, "$.detail").in_(details))
    return exists(select(literal_column("1")).select_from(log).where(*where))


def _received_since(at: datetime):
    from app.outreach.text import responder

    return and_(_M.direction == "in", _M.channel == "sms", _M.origin == "peer", _M.status == "received",
                _M.caller_class.is_not(None), _M.created_at >= at - timedelta(seconds=LOOKBACK_S),
                _has_event("admission", "allowed", tuple(responder.VERDICTS)))


def _unanswered(session: Session, at: datetime) -> list[int]:
    """아직 잡히지 않은 engage·notice 받은 줄(오래된 차례, SWEEP_ROWS 줄까지)."""
    stmt = select(_M.id).where(_received_since(at), _M.claimed_at.is_(None))
    return list(session.scalars(stmt.order_by(_M.id).limit(SWEEP_ROWS)))


def _interrupted(session: Session, at: datetime) -> list[int]:
    """잡힌 채 CLAIM_STALE_S 가 지났는데 답 줄도 reply_failed 도 없는 줄."""
    from app.outreach.text import responder

    reply = _M.__table__.alias("reply")
    made = exists(select(literal_column("1")).select_from(reply).where(
        reply.c.reply_to_id == _M.id, reply.c.direction == "out", reply.c.origin == "agent",
        reply.c.kind.in_(responder.AUTO_KINDS)))
    stale = _M.claimed_at < at - timedelta(seconds=responder.CLAIM_STALE_S)
    stmt = select(_M.id).where(_received_since(at), stale, not_(made), not_(_has_event("reply_failed")))
    return list(session.scalars(stmt.order_by(_M.id).limit(SWEEP_ROWS)))


def _sweep(at: datetime) -> list[int]:
    from app.outreach.text import responder

    with _db() as session:
        for message_id in _interrupted(session, at):
            events.record(session, Ref("message", message_id), "reply_failed", "noted", responder.INTERRUPTED, now=at)
        session.commit()
        return _unanswered(session, at)
