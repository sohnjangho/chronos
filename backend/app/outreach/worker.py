"""연락 일꾼(Task 71) — 서버 안에서 TICK_S 마다 한 바퀴: ① 때가 된 예약 보내기 ② 상태 조회 ③ 들어온 문자 받기.

- **보내기는 나가는 문으로만.** 때가 된 예약 메시지(scheduled · scheduled_at 이 지남)를 `gate.dispatch(…, SYSTEM)` 에 넣는다 —
  검사를 처음부터 다시 받고, 통과하지 못하면 문이 초안으로 돌리고 까닭을 남긴다. 통로를 직접 부르지 않는다.
  failed·unconfirmed·sending 줄은 다시 넣지 않는다(다시 보내기는 사람이 새 줄로). 통화 줄은 통화 일꾼(Task 88)의 몫이다.
- **알림 연결이 없거나 ok 가 아니거나 키를 풀 수 없으면 아무것도 하지 않는다**(예약 줄도 그대로 둔다 — 넣으면 문이 초안으로
  돌린다). 제공사가 안 되면(연결·키·잦은 요청·읽을 수 없는 답) 그 바퀴의 남은 요청을 그만두고 TICK_S 부터 두 배씩,
  길어야 QUIET_MAX_S 동안 쉰다(429 의 Retry-After 가 더 길면 그만큼) — 쉬는 동안은 예약도 내보내지 않는다.
- **상태 조회**: 제공사 id 가 있는 accepted·unconfirmed 줄을 status_gap(checks) 간격으로(10초 → 두 배씩 → 5분) 묻는다.
  도착·실패로 바뀌면 `delivery_update`(delivered·failed) 사건, GIVE_UP_AFTER_S 가 지나면 그만 묻고 fail_reason 에 GAVE_UP
  (`delivery_update` · gave_up). 실패 까닭은 제공사의 code 를 우리 글 표(diagnostics.FAILURES)로 옮긴 것만 적는다.
  id 가 없는 unconfirmed 줄은 사람이 정할 때까지 그대로 둔다. 어느 줄도 다시 보내지 않는다.
- **sending 으로 남은 줄**: 서버가 뜰 때 recover 가(그 전에 차지된 것 모두 — `server_restart` 사건), 그 뒤로는 바퀴마다
  STALE_SENDING_S 넘게 남은 것을(`delivery` noted — 문이 결과를 적지 못한 것) unconfirmed 로 옮긴다. 다시 보내지 않는다.
- **들어온 문자**: `received(since)` 의 다음 since 는 `Received.next_since` 만 쓴다(처음에는 지금 − 여유 — 옛 문자를 끌어오지
  않는다). 겹쳐 오는 줄은 제공사 id 로 한 번만, 우리 발신번호로 온 것이 아니면 버리고 센다. truncated·skipped·redated 는
  status() 에 드러낸다(쪽 상한 뒤의 줄은 다시 읽어도 오지 않으므로 커서는 그대로 나아간다). 줄을 먼저 쓰고(route 가 고른
  일정·연락처, peer_number 는 door.stored_peer_number) commit 한 뒤 `door.admit(…, exclude_message_id)` 로 받기 판정을 받아
  등급과 `admission` 사건을 남긴다. stop 이면 번호를 수신 거부로 표시하고(이미 표시된 번호가 아니고 Admission.confirm 이
  참일 때만) 확인 문자 한 줄(dnc_confirm · gate.DNC_CONFIRM_TEXT)을 만들어 문에 넣는다(문자 권한 설정대로 — 「승인 받기」면
  초안으로 남는다). engage·notice 는 `inbox.enqueue(message_id)`.
- **한 바퀴의 상한**(아래 상수): 제공사 요청 MAX_REQUESTS_PER_TICK 번(received 는 가장 많이 쓰는 수로 미리 뗀다), 예약
  DUE_PER_TICK 줄, 조회 STATUS_PER_TICK 줄, 확인 문자 CONFIRMS_PER_TICK 줄, 새로 받는 문자 INBOUND_ROWS_PER_TICK 줄, 옮기는
  줄 SWEEP_ROWS 줄. 고리는 모두 이 수로 끝난다. 일꾼 고리는 바퀴가 MIN_PASS_S 보다 빨리 MAX_FAST_PASSES 번 이어 돌면 스스로
  멈춘다(헛돌며 쌓지 않는다).
- DB 묶음은 짧게, 스레드에서(asyncio.to_thread), 묶음마다 새 세션. 제공사를 부르는 동안에는 세션도 잠금도 쥐지 않는다.
  어떤 예외도 일꾼을 멈추지 않는다 — 종류만 기록한다(번호·글·키는 로그·사건·status 어디에도 없다).
- 일꾼은 프로세스에 하나: start 를 두 번 불러도 하나, stop 은 돌던 바퀴를 STOP_WAIT_S 까지 기다린 뒤 끊는다(바퀴는 요청
  사이마다 멈춤 신호를 본다). 통로(app.outreach.channels)는 start 가 불러와 등록한다.
"""

import asyncio
import contextlib
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, literal, or_, select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.notify import diagnostics
from app.outreach import phone, provider
from app.outreach.harness import door, events, gate
from app.outreach.harness.types import Actor, Ref
from app.outreach.text import inbox
from app.store import contacts, outreach
from app.store.tables_outreach import (
    DoNotContactNumber,
    NotifyConnection,
    OutreachMessage,
    UtcDateTime,
)
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

TICK_S = 20.0  # 한 바퀴 간격
MAX_REQUESTS_PER_TICK = 20  # 한 바퀴의 제공사 요청(보내기·조회·받은 문자 읽기를 합쳐)
DUE_PER_TICK = 5  # 한 바퀴에 문에 넣는 예약 줄
STATUS_PER_TICK = 10  # 한 바퀴에 상태를 묻는 줄
CONFIRMS_PER_TICK = 2  # 한 바퀴에 문에 넣는 수신 거부 확인 문자
INBOUND_ROWS_PER_TICK = 200  # 한 바퀴에 새로 저장하는 받은 문자(넘으면 커서를 두고 다음 바퀴에 이어서)
SWEEP_ROWS = 50  # 한 묶음에 옮기는 줄(남은 sending · 조회 그만두기)
STATUS_FIRST_S, STATUS_MAX_S = 10, 300  # 상태 조회 간격: 처음 · 가장 긴 것
GIVE_UP_AFTER_S = 72 * 3600  # 이만큼 지나도 결과가 없으면 그만 묻는다
STALE_SENDING_S = 300  # sending 으로 이만큼 남은 줄은 결과를 적지 못한 것으로 본다(보내기 한 번은 15초 안에 끝난다)
INBOUND_S, INBOUND_IDLE_S = 20.0, 60.0  # 들어온 문자 조회 간격: 보통 · 받지 않음이고 최근에 보낸 것도 없을 때
ACTIVE_DAYS = 7  # 「최근에 보낸 것」
REPLY_LINK_S = 72 * 3600  # 이 안에 우리가 보낸 가장 최근 메시지에 답을 잇는다
QUIET_MAX_S = 300.0  # 제공사가 안 될 때 쉬는 가장 긴 시간
INBOUND_HOLD_MAX = 15  # 받은 문자를 저장하지 못해 커서를 붙잡아 두는 바퀴 수(넘으면 그 줄을 건너뛰고 나아간다)
STOP_WAIT_S = 5.0  # stop 이 돌던 바퀴를 기다리는 시간
MIN_PASS_S, MAX_FAST_PASSES = 1.0, 5  # 이보다 빨리 끝난 바퀴가 이만큼 이어지면 일꾼이 스스로 멈춘다
GAVE_UP = "결과를 확인하지 못했습니다"
RESTARTED = "서버가 다시 시작돼 보냈는지 확인이 필요합니다"
RESULT_LOST = "보낸 결과를 적지 못해 확인이 필요합니다"
CONFIRM_HELD = "한꺼번에 많이 들어와 자동으로 보내지 않았습니다. 확인하고 보내 주세요"
DELIVERY_FAILED = "전송에 실패했습니다"
STOP_REASON = "문자로 수신 거부"
CUT_MARK = "\n(뒤가 잘림)"
SYSTEM = Actor("system", None, "일꾼", None)
CONFIRM_ACTOR = Actor("agent", None, "수신 거부 확인", "user")  # 확인 문자는 문자 권한(위임)일 때만 저절로 나간다

_M = OutreachMessage
_WAITING = ("accepted", "unconfirmed")  # 결과를 기다리는 줄
_ADMIT_VERDICT = {"engage": "allowed", "notice": "allowed", "stop": "noted"}  # admission 사건의 판정(그 밖은 blocked)
_SENT_AT = func.coalesce(_M.sent_at, _M.claimed_at, _M.created_at)
_LAST_LOOK = func.coalesce(_M.last_checked_at, _M.sent_at, _M.claimed_at, _M.created_at)


@dataclass
class _State:
    """일꾼의 메모리 상태(프로세스에 하나 — status 가 읽는다). 번호·글·키는 두지 않는다."""

    running: bool = False
    ticking: bool = False
    last_tick_at: datetime | None = None
    last_due_at: datetime | None = None
    last_status_poll_at: datetime | None = None
    last_inbound_poll_at: datetime | None = None  # 마지막으로 읽기에 성공한 때
    inbound_truncated: int = 0  # 쪽 상한 뒤에 줄이 남았던 조회 수(그 줄들은 읽지 못했다 — 사람이 알아야 한다)
    inbound_truncated_at: datetime | None = None
    # 아래 셋은 **마지막 조회 한 번**의 수다(조회 창은 늘 최근 10분을 다시 훑으므로 같은 줄이 10분쯤 이어서 잡힌다)
    inbound_skipped: int = 0  # 제공사 호출이 읽지 못해 건너뛴 줄
    inbound_redated: int = 0  # 시각이 앞서 있어 조회 시각으로 바꾼 줄
    inbound_other_sender: int = 0  # 우리 발신번호로 온 것이 아니라 버린 줄
    inbound_failed: int = 0  # 저장하지 못해 끝내 건너뛴 줄
    last_error_kind: str | None = None  # 마지막 바퀴의 오류 종류(제공사 code 또는 예외 이름). 깨끗했으면 None
    quiet_until: datetime | None = None  # 이때까지 제공사를 부르지 않는다
    fail_streak: int = 0
    inbound_holds: int = 0


@dataclass
class _Plan:
    """한 바퀴에 할 일(스레드에서 한 번 읽는다)."""

    skip: str | None = None
    client: provider.Provider | None = None
    conn_id: int = 0
    our_number: str | None = None
    due: list[int] = field(default_factory=list)
    polls: list[tuple[int, str]] = field(default_factory=list)
    inbound_due: bool = False
    since: datetime | None = None


@dataclass
class _New:
    """새로 저장한 받은 문자 하나: 받기 판정(판정이 깨졌으면 None)과, 만들었으면 확인 문자 줄 id."""

    message_id: int
    verdict: str | None = None
    confirm_id: int | None = None


@dataclass
class _Stored:
    new: list[_New] = field(default_factory=list)
    other: int = 0
    failed: int = 0
    complete: bool = True  # 받은 줄을 모두 다뤘다(커서를 당겨도 된다)
    broke: bool = False  # 저장이 깨져 멈췄다
    error: str | None = None


_state = _State()
_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _db():
    return contextmanager(get_session)()


def _t(at: datetime) -> ColumnElement:
    """DB 의 시각 칸과 견줄 값(칸과 같은 꼴로 묶인다)."""
    return literal(at, UtcDateTime())


def _iso(at: datetime | None) -> str | None:
    return None if at is None else as_utc(at).isoformat()


def _stopping() -> bool:
    return _stop is not None and _stop.is_set()


def status() -> dict:
    """일꾼의 지금 모습(개발 콘솔 진단이 읽는다) — 메모리 값뿐, 시각은 ISO 글(UTC). 번호·키·글은 없다."""
    s = _state
    return {
        "running": s.running, "last_tick_at": _iso(s.last_tick_at), "last_due_at": _iso(s.last_due_at),
        "last_status_poll_at": _iso(s.last_status_poll_at), "last_inbound_poll_at": _iso(s.last_inbound_poll_at),
        "inbound_truncated": s.inbound_truncated, "inbound_truncated_at": _iso(s.inbound_truncated_at),
        "inbound_skipped": s.inbound_skipped, "inbound_redated": s.inbound_redated,
        "inbound_other_sender": s.inbound_other_sender, "inbound_failed": s.inbound_failed,
        "last_error_kind": s.last_error_kind, "quiet_until": _iso(s.quiet_until),
    }


def status_gap(checks: int) -> int:
    """상태를 checks 번 물은 줄을 다음에 묻기까지의 초: 10 → 20 → 40 → … → 길어야 300."""
    return min(STATUS_FIRST_S * 2 ** min(max(checks, 0), 16), STATUS_MAX_S)


# ── 한 바퀴 ──────────────────────────────────────────────────────────


class _Tick:
    """한 바퀴의 시각과 결과. now 를 주면(시험) 그 시각으로만 돈다."""

    def __init__(self, now: datetime | None) -> None:
        self.at = _now() if now is None else as_utc(now)
        self.clock = _now if now is None else (lambda: self.at)
        self.result: dict = {"skipped": None, "error": None, "due": 0, "status": 0, "inbound": 0, "requests": 0}
        self.broken = False  # 제공사가 안 된다 — 이 바퀴의 남은 요청을 하지 않는다

    def soft(self, exc: Exception, what: str) -> None:
        """한 건의 오류 — 그 건만 넘어간다. 종류만 남긴다(예외 글에는 번호·키가 있을 수 있다)."""
        self.result["error"] = type(exc).__name__
        logger.warning("연락 일꾼: %s 오류 (%s)", what, type(exc).__name__)

    def trouble(self, kind: str, retry_after_s: int | None = None) -> None:
        """제공사가 안 되거나 바퀴가 깨졌다 — 남은 요청을 그만두고 조금씩 길게 쉰다."""
        state = _state
        self.broken, self.result["error"], state.last_error_kind = True, kind, kind
        state.fail_streak += 1
        wait = min(TICK_S * 2 ** min(state.fail_streak - 1, 16), QUIET_MAX_S)
        state.quiet_until = self.at + timedelta(seconds=max(wait, retry_after_s or 0))
        logger.warning("연락 일꾼: 제공사 요청을 쉽니다 (%s)", kind)


async def tick(now: datetime | None = None) -> dict:
    """한 바퀴(모듈 머리 글). 예외를 올리지 않는다. 돌려주는 것: {skipped, error, due, status, inbound, requests} —
    skipped 는 busy(이미 도는 중)·quiet(쉬는 중)·no_connection·not_ok·제공사 code(키를 풀 수 없음) 또는 None,
    requests 는 이 바퀴가 쓴 제공사 요청 수의 위 끝(received 는 가장 많이 쓰는 수로 센다)."""
    state, run = _state, _Tick(now)
    if state.ticking:
        return run.result | {"skipped": "busy"}
    state.ticking, state.last_tick_at = True, run.at
    try:
        if state.quiet_until is not None and run.at < state.quiet_until:
            run.result["skipped"] = "quiet"
        else:
            await _work(run)
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 일꾼을 멈추지 않는다
        run.trouble(type(exc).__name__)
    finally:
        state.ticking = False
    return run.result


async def _work(run: _Tick) -> None:
    state = _state
    plan = await asyncio.to_thread(_plan, run.at)
    if plan.skip is not None:
        run.result["skipped"] = plan.skip
        state.last_error_kind = None if plan.skip in ("no_connection", "not_ok") else plan.skip
        return
    reserved = provider.RECEIVED_MAX_REQUESTS + CONFIRMS_PER_TICK if plan.inbound_due else 0
    room = MAX_REQUESTS_PER_TICK - reserved
    await _send_due(run, plan.due[:max(0, min(DUE_PER_TICK, room))])
    await _poll(run, plan, plan.polls[:max(0, min(STATUS_PER_TICK, room - run.result["due"]))])
    if plan.inbound_due and not run.broken and not _stopping():
        await _receive(run, plan)
    if not run.broken:
        state.last_error_kind, state.fail_streak, state.quiet_until = run.result["error"], 0, None


async def _send_due(run: _Tick, ids: list[int]) -> None:
    """① 때가 된 예약 줄을 문에 넣는다 — 검사는 문이 처음부터 다시 한다."""
    for row_id in ids:
        if _stopping():
            break
        run.result["due"] += 1
        run.result["requests"] += 1
        try:
            await gate.dispatch("message", row_id, SYSTEM, now=run.clock())
        except Exception as exc:  # noqa: BLE001
            run.soft(exc, "예약 보내기")
    _state.last_due_at = run.at


async def _poll(run: _Tick, plan: _Plan, polls: list[tuple[int, str]]) -> None:
    """② 상태 조회. 제공사가 그 메시지만 모르면(bad_request) 그 줄의 다음 조회만 미루고, 그 밖의 실패는 바퀴를 멈춘다."""
    for row_id, provider_id in polls:
        if _stopping():
            break
        run.result["requests"] += 1
        try:
            delivery = await plan.client.message_status(provider_id)
        except provider.ProviderFailed as exc:
            if exc.code != "bad_request":
                run.trouble(exc.code, exc.retry_after_s)
                return
            delivery = None
        run.result["status"] += 1
        await asyncio.to_thread(_apply_status, row_id, delivery, run.at)
    _state.last_status_poll_at = run.at


async def _receive(run: _Tick, plan: _Plan) -> None:
    """③ 들어온 문자: 읽고(세션 밖) → 저장·받기 판정(스레드) → 넘기기·확인 문자 → 커서."""
    state = _state
    run.result["requests"] += provider.RECEIVED_MAX_REQUESTS
    try:
        got = await plan.client.received(plan.since)
    except provider.ProviderFailed as exc:
        run.trouble(exc.code, exc.retry_after_s)
        return
    state.last_inbound_poll_at = run.at
    if got.truncated:
        state.inbound_truncated, state.inbound_truncated_at = state.inbound_truncated + 1, run.at
    state.inbound_skipped, state.inbound_redated = got.skipped, got.redated
    tolerant = state.inbound_holds >= INBOUND_HOLD_MAX
    stored = await asyncio.to_thread(_store_inbound, list(got.items), plan.our_number, run.at, tolerant)
    state.inbound_other_sender = stored.other
    state.inbound_failed += stored.failed
    run.result["inbound"] = len(stored.new)
    if stored.error is not None:
        run.result["error"] = stored.error
    confirms = CONFIRMS_PER_TICK
    for new in stored.new:
        try:
            if new.confirm_id is None:
                if new.verdict in ("engage", "notice"):
                    inbox.enqueue(new.message_id)
            elif confirms > 0 and not _stopping():
                confirms -= 1
                run.result["requests"] += 1
                await gate.dispatch("message", new.confirm_id, CONFIRM_ACTOR, now=run.clock())
            else:
                await asyncio.to_thread(_hold_confirm, new.confirm_id)
        except Exception as exc:  # noqa: BLE001
            run.soft(exc, "받은 문자 넘기기")
    if stored.complete:
        state.inbound_holds = 0
        await asyncio.to_thread(_save_cursor, plan.conn_id, got.next_since)
    elif stored.broke:
        state.inbound_holds += 1


# ── DB 묶음(스레드에서, 묶음마다 새 세션) ─────────────────────────────


def _plan(at: datetime) -> _Plan:
    """연결을 보고 이 바퀴에 할 일을 읽는다. 쓸 연결이 아니면 그 까닭만(아무것도 하지 않는다)."""
    with _db() as session:
        conn = outreach.connection(session)
        if conn is None:
            return _Plan(skip="no_connection")
        if conn.status != "ok":
            return _Plan(skip="not_ok")
        try:
            client = provider.client_for(conn)
        except provider.ProviderFailed as exc:
            return _Plan(skip=exc.code)
        since = as_utc(conn.reply_cursor) if conn.reply_cursor is not None else at - timedelta(seconds=provider.SINCE_MARGIN_S)
        plan = _Plan(client=client, conn_id=conn.id, our_number=phone.normalize(conn.sender_number), since=since,
                     inbound_due=_inbound_due(session, conn.inbound_mode, at))
        stale = _M.direction == "out", _M.status == "sending"
        old = func.coalesce(_M.claimed_at, _M.created_at) < _t(at - timedelta(seconds=STALE_SENDING_S))
        _close(session, list(session.scalars(select(_M.id).where(*stale, old).order_by(_M.id).limit(SWEEP_ROWS))),
               "delivery", RESULT_LOST, at)
        _give_up(session, at)
        due = select(_M.id).where(_M.direction == "out", _M.status == "scheduled", _M.scheduled_at <= at)
        plan.due = list(session.scalars(due.order_by(_M.scheduled_at, _M.id).limit(DUE_PER_TICK)))
        fresh = _SENT_AT > _t(at - timedelta(seconds=GIVE_UP_AFTER_S))
        polls = select(_M.id, _M.provider_message_id).where(_pollable(), fresh, _poll_due(at))
        plan.polls = [(row_id, pid) for row_id, pid in session.execute(polls.order_by(_LAST_LOOK, _M.id).limit(STATUS_PER_TICK))]
    return plan


def _inbound_due(session: Session, mode: str, at: datetime) -> bool:
    """들어온 문자를 읽을 때인가: INBOUND_S 마다, 받는 범위가 「받지 않음」이고 최근 ACTIVE_DAYS 일에 보낸 것이 없으면
    INBOUND_IDLE_S 마다(바퀴 간격의 흔들림만큼 너그럽게)."""
    last = _state.last_inbound_poll_at
    if last is None:
        return True
    recent = select(_M.id).where(_M.direction == "out", _M.claimed_at >= at - timedelta(days=ACTIVE_DAYS)).limit(1)
    idle = mode == "off" and session.scalar(recent) is None
    return (at - last).total_seconds() >= (INBOUND_IDLE_S if idle else INBOUND_S) * 0.9


def _pollable() -> ColumnElement[bool]:
    """결과를 물어볼 줄: 나간 것 · 접수 또는 확인 필요 · 제공사 id 있음 · 그만 묻기로 한 줄이 아님."""
    return and_(_M.direction == "out", _M.status.in_(_WAITING), _M.provider_message_id.is_not(None),
                or_(_M.fail_reason.is_(None), _M.fail_reason != GAVE_UP))


def _poll_due(at: datetime) -> ColumnElement[bool]:
    """마지막으로 본 때(없으면 나간 때)에서 status_gap(checks) 가 지났는가."""
    steps = next(n for n in range(32) if status_gap(n) >= STATUS_MAX_S)
    ladder = [(_M.checks == n, status_gap(n)) for n in range(steps)] + [(_M.checks >= steps, STATUS_MAX_S)]
    return or_(*[and_(rung, _LAST_LOOK <= _t(at - timedelta(seconds=gap))) for rung, gap in ladder])


def _close(session: Session, ids: list[int], rule: str, why: str, at: datetime) -> int:
    """sending 으로 남은 줄을 「보냈는지 확인 필요」로 옮긴다(그 사이 결과가 적혔으면 건드리지 않는다). 다시 보내지 않는다."""
    moved = 0
    for row_id in ids:
        closing = update(_M).where(_M.id == row_id, _M.status == "sending").values(status="unconfirmed", fail_reason=gate.UNSURE)
        if session.execute(closing).rowcount == 1:
            events.record(session, Ref("message", row_id), rule, "noted", why, now=at)
            moved += 1
        session.commit()
    return moved


def recover(now: datetime | None = None, *, before: datetime | None = None) -> int:
    """서버가 뜰 때: before(없으면 지금) 전에 차지돼 sending 으로 남은 메시지를 unconfirmed 로 옮기고 `server_restart`
    사건을 남긴다 — 다시 보내지 않는다. 옮긴 줄 수(한 번에 SWEEP_ROWS 줄까지 — 남은 것은 바퀴가 이어서 옮긴다)."""
    at = _now() if now is None else as_utc(now)
    cut = at if before is None else as_utc(before)
    with _db() as session:
        left = select(_M.id).where(_M.direction == "out", _M.status == "sending",
                                   or_(_M.claimed_at.is_(None), _M.claimed_at < cut))
        return _close(session, list(session.scalars(left.order_by(_M.id).limit(SWEEP_ROWS))), "server_restart", RESTARTED, at)


def _give_up(session: Session, at: datetime) -> None:
    """GIVE_UP_AFTER_S 가 지나도 결과가 없는 줄은 그만 묻는다(상태는 그대로, 까닭만 적는다)."""
    late = select(_M.id).where(_pollable(), _SENT_AT <= _t(at - timedelta(seconds=GIVE_UP_AFTER_S)))
    for row_id in list(session.scalars(late.order_by(_M.id).limit(SWEEP_ROWS))):
        marking = update(_M).where(_M.id == row_id, _M.status.in_(_WAITING)).values(fail_reason=GAVE_UP)
        if session.execute(marking).rowcount == 1:
            events.record(session, Ref("message", row_id), "delivery_update", "noted", "gave_up", now=at)
        session.commit()


def _apply_status(row_id: int, delivery: provider.Delivery | None, at: datetime) -> None:
    """조회 한 번의 결과를 적는다(delivery None = 그 메시지를 제공사가 모름 — 물은 것만 센다). 아직 기다리는 줄일 때만."""
    values: dict = {"checks": _M.checks + 1, "last_checked_at": at}
    event = None
    if delivery is not None and delivery.state == "delivered":
        values |= {"status": "delivered", "delivered_at": at, "fail_reason": None}
        event = ("allowed", "delivered")
    elif delivery is not None and delivery.state == "failed":
        values |= {"status": "failed", "fail_reason": diagnostics.FAILURES.get(delivery.fail_code, DELIVERY_FAILED)}
        event = ("blocked", "failed")
    if delivery is not None and delivery.fell_back:
        values["fallback_sms"] = True
    with _db() as session:
        changed = session.execute(update(_M).where(_M.id == row_id, _M.status.in_(_WAITING)).values(**values)).rowcount
        if changed == 1 and event is not None:
            events.record(session, Ref("message", row_id), "delivery_update", *event, now=at)
        session.commit()


def route(session: Session, from_number: str | None) -> tuple[int, int] | None:
    """들어온 문자가 들어갈 (일정 id, 연락처 id): 그 번호의 연락처들(숨긴 사람도) 가운데 **가장 최근에 우리가 문자를 보낸**
    사람 — 초안·실패한 것은 보낸 것이 아니다. 보낸 것이 없으면 보이는 연락처가 한 사람일 때만 그 사람. 정할 수 없으면 None
    (일정 없는 줄 — 모르는 번호 묶음)."""
    people = {person.id: person for person in contacts.by_number(session, from_number)} if from_number else {}
    if not people:
        return None
    last = select(_M.contact_id).where(_M.direction == "out", _M.contact_id.in_(list(people)), _M.claimed_at.is_not(None),
                                       _M.status.in_(outreach.SENT_MESSAGE))
    found = session.scalar(last.order_by(_M.claimed_at.desc(), _M.id.desc()).limit(1))
    if found is None:
        visible = [person.id for person in people.values() if not person.hidden]
        found = visible[0] if len(visible) == 1 else None
    return None if found is None else (people[found].schedule_id, found)


def _insert(session: Session, item: provider.Inbound, at: datetime) -> int:
    """받은 문자 한 줄을 쓰고 commit 한다. 우리가 보낸 요청의 답이면 잇는다(그 연락처에게 REPLY_LINK_S 안에 나간 가장
    최근 메시지 — reply_to_id 와 그 줄의 activity_id·field_item_id·batch_id)."""
    number = door.stored_peer_number(item.from_number)
    schedule_id, contact_id = route(session, number) or (None, None)
    asked = None
    if contact_id is not None:
        ours = select(_M).where(_M.direction == "out", _M.contact_id == contact_id, _M.status.in_(outreach.SENT_MESSAGE),
                                _M.claimed_at >= as_utc(item.at) - timedelta(seconds=REPLY_LINK_S))
        asked = session.scalar(ours.order_by(_M.claimed_at.desc(), _M.id.desc()).limit(1))
    row = OutreachMessage(
        schedule_id=schedule_id, contact_id=contact_id, peer_number=number, direction="in", channel="sms",
        status="received", origin="peer", body=item.body + (CUT_MARK if item.body_cut else ""), has_media=item.has_media,
        provider_message_id=item.provider_id, sent_at=min(as_utc(item.at), at), created_at=at,
        reply_to_id=asked.id if asked else None, activity_id=asked.activity_id if asked else None,
        field_item_id=asked.field_item_id if asked else None, batch_id=asked.batch_id if asked else None)
    session.add(row)
    session.flush()
    row_id = row.id
    session.commit()
    return row_id


def _admit(row_id: int, item: provider.Inbound, at: datetime) -> _New:
    """저장한 줄의 받기 판정(들어오는 문): 등급과 `admission` 사건을 남기고, 수신 거부 말이면 번호를 표시한다."""
    with _db() as session:
        admitted = door.admit(session, "sms", item.from_number, now=at, body=item.body, has_media=item.has_media,
                              exclude_message_id=row_id)
        session.execute(update(_M).where(_M.id == row_id).values(caller_class=admitted.caller.caller_class))
        events.record(session, Ref("message", row_id), "admission", _ADMIT_VERDICT.get(admitted.verdict, "blocked"),
                      admitted.reason, now=at)
        confirm_id = _refuse(session, row_id, item, admitted.confirm, at) if admitted.verdict == "stop" else None
        session.commit()
    return _New(row_id, admitted.verdict, confirm_id)


def _refuse(session: Session, row_id: int, item: provider.Inbound, confirm: bool, at: datetime) -> int | None:
    """수신 거부 말: 번호를 번호 기준 수신 거부로 표시한다. 새로 표시한 번호이고 confirm 이면 확인 문자 초안 한 줄을
    만들어 그 id 를 준다(표시마다 하나 — 다시 「수신거부」를 보내와도 더 만들지 않는다). commit 은 부른 쪽."""
    number = door.stored_peer_number(item.from_number)
    marked = session.scalar(select(DoNotContactNumber.id).where(DoNotContactNumber.number == number)) is not None
    outreach.mark_do_not_contact(session, number, reason=STOP_REASON)
    if marked or not confirm:
        return None
    asked = session.get(OutreachMessage, row_id)
    row = OutreachMessage(
        schedule_id=asked.schedule_id, contact_id=asked.contact_id, peer_number=None if asked.contact_id else number,
        direction="out", channel="sms", kind="dnc_confirm", body=gate.DNC_CONFIRM_TEXT, origin="agent",
        origin_name=CONFIRM_ACTOR.name, status="draft", reply_to_id=row_id, created_at=at)
    session.add(row)
    session.flush()
    return row.id


def _store_inbound(items: list[provider.Inbound], our_number: str | None, at: datetime, tolerant: bool) -> _Stored:
    """받은 줄들을 차례로: 우리 번호로 온 것만, 제공사 id 로 한 번만, 새 줄은 INBOUND_ROWS_PER_TICK 까지. 줄을 쓰고
    commit 한 뒤 받기 판정을 한다 — 판정이 깨져도 받은 문자는 남는다. 저장이 깨지면 멈춘다(tolerant 면 그 줄만 건너뛴다)."""
    out = _Stored()
    for item in items:
        if our_number is None or item.to_number != our_number:
            out.other += 1
            continue
        try:
            with _db() as session:
                seen = select(_M.id).where(_M.direction == "in", _M.provider_message_id == item.provider_id).limit(1)
                if session.scalar(seen) is not None:
                    continue
                if len(out.new) >= INBOUND_ROWS_PER_TICK:
                    out.complete = False
                    break
                row_id = _insert(session, item, at)
        except Exception as exc:  # noqa: BLE001
            out.error = type(exc).__name__
            logger.warning("연락 일꾼: 받은 문자를 저장하지 못했습니다 (%s)", out.error)
            if tolerant:
                out.failed += 1
                continue
            out.complete, out.broke = False, True
            break
        try:
            out.new.append(_admit(row_id, item, at))
        except Exception as exc:  # noqa: BLE001
            out.error = type(exc).__name__
            out.new.append(_New(row_id))
            logger.warning("연락 일꾼: 받은 문자의 받기 판정을 하지 못했습니다 (%s)", out.error)
    return out


def _hold_confirm(row_id: int) -> None:
    """한 바퀴의 상한을 넘은 확인 문자는 초안으로 남기고 까닭을 적는다(사람이 보낸다)."""
    with _db() as session:
        session.execute(update(_M).where(_M.id == row_id, _M.status == "draft").values(fail_reason=CONFIRM_HELD))
        session.commit()


def _save_cursor(conn_id: int, since: datetime) -> None:
    with _db() as session:
        session.execute(update(NotifyConnection).where(NotifyConnection.id == conn_id).values(reply_cursor=since))
        session.commit()


# ── 띄우기·멈추기 ────────────────────────────────────────────────────


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    """다음 바퀴까지 쉰다 — 멈춤 신호가 오면 곧바로 깬다."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def _run(stop: asyncio.Event, started: datetime) -> None:
    """일꾼 고리: 먼저 남은 sending 을 정리하고, 멈춤 신호가 올 때까지 한 바퀴 돌고 TICK_S 쉬기를 되풀이한다."""
    state = _state
    state.running = True
    try:
        try:
            await asyncio.to_thread(recover, before=started)
        except Exception as exc:  # noqa: BLE001
            logger.warning("연락 일꾼: 남은 줄을 정리하지 못했습니다 (%s)", type(exc).__name__)
        fast = 0
        while not stop.is_set():
            began = time.monotonic()
            try:
                await tick()
            except Exception as exc:  # noqa: BLE001 — tick 은 스스로 잡지만, 그것마저 깨져도 일꾼은 멈추지 않는다
                logger.warning("연락 일꾼: 한 바퀴가 오류로 끝났습니다 (%s)", type(exc).__name__)
            await _pause(stop, TICK_S)
            if stop.is_set():
                break
            fast = fast + 1 if time.monotonic() - began < MIN_PASS_S else 0
            if fast >= MAX_FAST_PASSES:  # 쉬지 못하고 헛돈다 — 끝없이 돌지 않고 멈춘다
                state.last_error_kind = "spinning"
                logger.error("연락 일꾼: 바퀴가 쉬지 않고 돌아 멈춥니다")
                break
    finally:
        state.running = False


def start() -> None:
    """서버가 뜰 때(lifespan, 이벤트 루프 안). 통로를 등록하고 일꾼을 띄운다 — 이미 떠 있으면 아무것도 하지 않는다.
    기다리지 않는다(첫 정리와 첫 바퀴는 띄운 작업 안에서 돈다)."""
    global _task, _stop
    if _task is not None and not _task.done():
        return
    import app.outreach.channels  # noqa: F401 — 진짜 통로(문자)를 등록한다. 불러오는 것은 여기 한 곳

    _stop = asyncio.Event()
    _state.running = True
    _task = asyncio.create_task(_run(_stop, _now()), name="outreach-worker")


async def stop() -> None:
    """서버를 닫을 때. 돌던 바퀴가 끝나기를 STOP_WAIT_S 까지 기다리고(쉬는 중이면 곧바로), 그래도 돌면 끊는다 —
    끊긴 보내기는 문이 「보냈는지 확인 필요」로 적는다. 떠 있지 않으면 아무것도 하지 않는다."""
    global _task, _stop
    task, stopping, _task = _task, _stop, None
    if task is None or stopping is None:
        return
    stopping.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=STOP_WAIT_S)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    except asyncio.CancelledError:
        if not task.done():  # stop 을 부른 쪽이 끊겼다 — 일꾼도 끊고 그대로 올린다
            task.cancel()
            raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("연락 일꾼: 멈추는 중 오류 (%s)", type(exc).__name__)
    _stop = None
