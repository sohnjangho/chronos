"""받는 통화 통로(Task 95). 우리 AI 전화 번호로 걸려 온 전화를 **받기 전에** 하네스의 들어오는 문이 판정하고(거절 · 부재중 ·
응대), 벨마다 통화 줄을 남기며, 응대하는 통화는 그 등급의 도구 묶음만 받고, 끝나면 뒤 확인·요약만 돈다. SDK 를 import 하지 않는다.

- **판정은 하네스 것 하나**: `door.admit(session, "call", 건 번호, now, live_calls)` — 등급·받기 규칙·범위(`door.scope_of`)·
  도구(`toolsets.for_class(등급, "call")` + `tools.Toolbox`)를 여기서 다시 쓰지 않는다. 차단·시험 모드·받는 범위는 판정할 때마다
  DB 에서 읽으므로 설정에서 바꾼 것이 곧바로 듣는다.
- **벨마다 한 줄**(`outreach_calls`, direction in) — 받든 안 받든, 사건 `admission`(detail 은 판정의 ADMIT_REASONS 코드) 하나와
  함께, 쓰고 곧바로 commit. 상대가 한 사람이면 contact_id·schedule_id, 아니면 peer_number(door.stored_peer_number). 건 번호는
  문과 그 줄에만 간다 — 명세·지시문·사건·로그에는 없다.
- reject → `rejected`(받지 않음) · missed(통화 중 한도) → `missed` + 아는 연락처면 회신 문자 초안(고정 글, 문자 권한대로
  `gate.dispatch` — 「승인 받기」면 초안) · engage → 받는 통화의 CallSpec(그 등급의 도구만 · 첫마디 greeting.inbound_line(한 현장
  연락처면 현장 이름) · 한 사람이면 그 사람의 음성(voices.pick)·언어 · 최대 시간은 limits(낮은 등급은 _unknown) · 걸 번호 없음 ·
  녹음 끔)과 `CallRun`(call_run — 거는 통화와 같은 손잡이).
- **한 번에 한 통**: 응대한 통화는 거는 일꾼의 줄(runner._state.live)에 든다 — 그동안 거는 일꾼은 기다리고(run_one WAITING), 음성
  진단은 붙지 않고(holds_line), 걸려 온 다른 전화는 부재중이다. 거는 일꾼이 줄을 쥔 동안(걸기 직전 ~ 통화 뒤 일)도 부재중이다.
  판정은 한 번에 하나씩(잠금) — 두 벨이 함께 응대되지 않는다.
- **끝**: 통화가 끝나면(끝 사건 · 실제 시간 상한 max_seconds + PLACE_GRACE_S · 듣기가 끊김) 줄을 놓고 `call_run.run_after` —
  completed 인 통화만 뒤 확인·요약(후속 줄은 만들지 않는다). 받지 않은 통화(백엔드의 on_failed)는 부재중·실패로 닫고 다시 걸지 않는다.
- **듣기 고리**(runner.start 가 띄움): CHECK_S 마다 설정을 보고 받는 범위가 「받지 않음」이 아니고 백엔드·번호가 준비됐으면
  `backend.listen(AI 전화 번호, on_incoming)`. 번호·백엔드 설정이 바뀌면 다시 건다(통화 중이면 끝난 뒤에). 거는 일꾼이 줄을 쥐었거나 음성 진단이 돌면
  붙지 않는다(control 연결은 번호당 하나). 듣기가 실패하면 RETRY_S 뒤 다시, 이어서 MAX_FAILS 번이면 설정이 바뀔 때까지 쉰다.
- **앱이 꺼진 동안의 전화**: 백엔드가 `missed_calls(since, until)`(SDK 어댑터 — 공개 REST 의 통화 목록)을 주면 듣기가 붙은 뒤
  한 번 읽어, 적지 않은 받는 통화를 부재중으로 남긴다(같은 제공사 id 는 한 번, 우리가 이미 적은 때와 겹치면 뺀다).
"""

import asyncio
import contextlib
import hashlib
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select, update

from app.db import get_session
from app.outreach import phone
from app.outreach.harness import door, events, gate, toolsets
from app.outreach.harness.tools import AGENT, AGENT_NAME, Toolbox
from app.outreach.harness.types import Caller, NotReady, Ref, Scope
from app.outreach.voice import call_run, greeting, instructions, numbers, runner, voices
from app.outreach.voice import session as voice_session
from app.outreach.voice.call_run import _LIVE, CallRun, _broken, _tries
from app.outreach.voice.session import CallSpec, Incoming, VoiceBackend
from app.store import outreach
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    OutreachCall,
    OutreachMessage,
    VoiceSettings,
)
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

CHECK_S = 10.0  # 듣기 고리가 설정을 다시 보는 간격
RETRY_S = 30.0  # 듣기가 실패한 뒤 다시 걸기까지
MAX_FAILS = 3  # 이어서 이만큼 실패하면 설정이 바뀔 때까지 다시 걸지 않는다
STABLE_S = 300.0  # 이만큼 붙어 있다가 끊겼으면 실패 셈을 처음부터
BACKFILL_AFTER_S = CHECK_S  # 듣기가 붙고 이만큼 지난 뒤에 앱이 꺼진 동안의 전화를 한 번 읽는다
BACKFILL_DAYS = 1  # 그보다 오래된 전화는 읽지 않는다
OVERLAP_S = 10  # 이미 적은 받는 통화와 이만큼 가까운 때의 전화는 같은 통화로 본다
LOW_CLASSES = frozenset({"unknown", "withheld", "do_not_contact"})  # 짧은 최대 시간(max_call_seconds_unknown)
SITE_CLASSES = frozenset({"contact", "shared"})  # 한 현장으로 정해지는 연락처 등급 — 첫마디·지시문에 현장 이름
REPLY_CLASSES = frozenset({"contact", "contact_multi", "shared"})  # 부재중이면 회신 문자 초안을 만드는 등급(아는 연락처)
MISSED_SMS = "ChronOS AI 비서입니다. 방금 주신 전화를 받지 못했습니다. 담당자가 확인 후 연락드리겠습니다."
REJECTED = "받지 않고 거절했습니다"
MISSED = "통화 중이라 받지 못했습니다"
NOT_READY = "받을 준비를 하지 못해 받지 않았습니다"
NOT_STARTED = "받았지만 통화가 시작되지 않았습니다"
IN_FAILED = "받은 통화를 시작하지 못했습니다"
IN_BROKE = "음성 통화 오류로 받은 통화가 끊겼습니다"
TOO_LATE = "받기 판정이 늦어 받지 못했습니다"
WHILE_OFF = "앱이 꺼져 있는 동안 걸려 와 받지 못했습니다"
_VERDICT = {"engage": "allowed", "missed": "noted"}  # admission 사건의 판정(그 밖 — reject — 은 blocked)
_STATUS = {"reject": ("rejected", REJECTED), "missed": ("missed", MISSED)}


def _now() -> datetime:
    return datetime.now(UTC)


def _clock() -> float:
    return time.monotonic()


def _db():
    return contextmanager(get_session)()


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


@dataclass
class _State:
    """받는 쪽의 메모리 상태(프로세스에 하나). 번호·키·글은 두지 않는다(바인딩은 해시만)."""

    task: asyncio.Task | None = None  # 듣기 고리
    stop: asyncio.Event | None = None
    listen: asyncio.Task | None = None  # backend.listen
    binding: str | None = None  # 지금 들은 설정의 해시
    since: float = 0.0  # 듣기를 건 때(시계)
    failures: int = 0
    failed_at: float | None = None
    backfilled: bool = False
    last_error_kind: str | None = None
    follows: set = field(default_factory=set)  # 통화 뒤 일 · 회신 문자 넣기(뒤에서 도는 일)
    lock: asyncio.Lock | None = None


_state = _State()


@dataclass(frozen=True)
class _Engage:
    call_id: int
    spec: CallSpec
    caller_class: str
    scope: Scope
    model: str | None


# ── 받기 전 판정 ─────────────────────────────────────────────────────


def _busy() -> int:
    """동시 통화 셈 — 통화 중인 통화, 그리고 거는 일꾼이 줄을 쥐었으면(걸기 직전 ~ 통화 뒤 일) 그것도 하나."""
    state = runner._state
    return len(state.live) + int(state.holding is not None and state.holding not in state.live)


async def on_incoming(incoming: Incoming) -> tuple[CallSpec, CallRun] | None:
    """백엔드가 받기 전에 부른다(listen 의 on_incoming). 받을 통화면 (명세, 손잡이), 아니면 None. 줄은 받든 안 받든 남긴다."""
    state = _state
    if state.lock is None:
        state.lock = asyncio.Lock()
    async with state.lock:  # 판정은 하나씩 — 두 벨이 함께 응대되지 않는다
        work = asyncio.ensure_future(asyncio.to_thread(_decide, incoming, _busy(), as_utc(incoming.at)))
        try:
            decided = await asyncio.shield(work)
        except asyncio.CancelledError:  # 백엔드가 기다리다 그만뒀다 — 받기로 적었으면 받지 못한 줄로 닫는다
            work.add_done_callback(_too_late)
            raise
        if isinstance(decided, int):  # 부재중 — 아는 연락처의 회신 문자 초안을 문에 넣는다(판정 시한 밖에서)
            _behind(gate.dispatch("message", decided, AGENT, now=as_utc(incoming.at)))
            return None
        if decided is None:
            return None
        run = _InboundRun(decided.call_id, decided.spec, as_utc(incoming.at), decided.model)
        cls = decided.caller_class
        run.box = Toolbox(decided.scope, "call", Ref("call", decided.call_id), names=toolsets.for_class(cls, "call"),
                          caller_class=cls, clock=run.at)
        runner._state.live[decided.call_id] = run  # 한 번에 한 통 — 거는 일꾼·진단이 이것을 본다
        _behind(_follow(run, state.listen))
        return decided.spec, run


def _behind(work) -> None:
    task = asyncio.ensure_future(work)
    _state.follows.add(task)
    task.add_done_callback(_state.follows.discard)


def _too_late(work: asyncio.Future) -> None:
    if work.cancelled() or work.exception() is not None or not isinstance(work.result(), _Engage):
        return
    _behind(asyncio.to_thread(_tries, _not_taken, work.result().call_id, "missed", TOO_LATE, None, _now()))


def _decide(incoming: Incoming, live: int, at: datetime) -> "_Engage | int | None":
    """판정 한 번(스레드, 짧은 세션, 쓰고 곧바로 commit). 응대면 _Engage, 부재중에 회신 초안을 만들었으면 그 문자 줄 id, 아니면 None."""
    with _db() as session:
        admitted = door.admit(session, "call", incoming.caller_number, now=at, live_calls=live)
        caller, verdict = admitted.caller, admitted.verdict
        spec, model, status, why = None, None, *_STATUS.get(verdict, ("dialing", None))
        if verdict == "engage":
            try:
                spec, model = _spec(session, caller)
            except (ValueError, AttributeError):
                status, why = "missed", NOT_READY  # 받을 명세를 지을 수 없다(번호 없음·글에 번호) — 받지 않는다
        row = _row(caller, incoming.caller_number, status=status, fail_reason=why, created_at=at,
                   ended_at=None if spec is not None else at)
        session.add(row)
        session.flush()
        events.record(session, Ref("call", row.id), "admission", _VERDICT.get(verdict, "blocked"), admitted.reason, now=at)
        reply = _reply(session, caller, at) if verdict == "missed" else None
        session.commit()
        if spec is not None:  # 범위는 문이 정한 상대로만(scope_of — 같은 판정의 Caller)
            return _Engage(row.id, spec, caller.caller_class, door.scope_of(session, caller), model)
        return reply


def _row(caller: Caller, number: str | None, *, status: str, fail_reason: str | None, created_at: datetime,
         ended_at: datetime | None, provider_call_id: str | None = None) -> OutreachCall:
    """받는 통화 한 줄 — 상대가 한 사람이면 그 연락처, 아니면 번호 칸(문이 정한 꼴). 번호는 이 칸에만 간다."""
    pairs = caller.candidates
    one = pairs[0] if len(pairs) == 1 else None
    places = {pair.schedule_id for pair in pairs}
    return OutreachCall(direction="in", origin="peer", origin_name="", caller_class=caller.caller_class,
                        schedule_id=one.schedule_id if one else (next(iter(places)) if len(places) == 1 else None),
                        contact_id=one.contact_id if one else None,
                        peer_number=None if one else door.stored_peer_number(number), status=status,
                        fail_reason=fail_reason, created_at=created_at, ended_at=ended_at,
                        provider_call_id=provider_call_id)


def _spec(session, caller: Caller) -> tuple[CallSpec, str | None]:
    """받는 통화의 명세. 도구는 그 등급의 묶음만, 걸 번호는 없다. 번호가 든 글이면 CallSpec 이 ValueError."""
    cls, pairs = caller.caller_class, caller.candidates
    conn = outreach.connection(session)
    settings = session.get(VoiceSettings, conn.id)
    agent_number = phone.normalize(numbers.effective_agent_number(conn, settings))
    if agent_number is None:
        raise ValueError("AI 전화 번호가 없습니다")
    who = session.get(Contact, pairs[0].contact_id) if len(pairs) == 1 else None
    places = {pair.schedule_id for pair in pairs}
    record = session.get(ScheduleRecord, next(iter(places))) if cls in SITE_CLASSES and len(places) == 1 else None
    site = record.name if record is not None else None
    language = (who.language if who is not None and who.language else None) or greeting.DEFAULT_LANGUAGE
    if who is not None:
        voice_id = voices.pick(who.gender, who.voice_mode, who.voice_id, language, settings)
    else:
        voice_id = voices.pick("unknown", None, None, language, settings)
    limits = outreach.limits(conn)
    spec = CallSpec(direction="in", to_number=None, from_number=agent_number, language=language, voice_id=voice_id,
                    first_line=greeting.inbound_line(language, site),
                    instructions=instructions.inbound(cls, site, who.name if who is not None else None, language),
                    tools=toolsets.tool_defs(toolsets.for_class(cls, "call")),
                    max_seconds=limits.max_call_seconds_unknown if cls in LOW_CLASSES else limits.max_call_seconds,
                    record_to=None)
    model = numbers.effective_model(settings.provider, settings.model) if settings is not None else None
    return spec, model


def _reply(session, caller: Caller, at: datetime) -> int | None:
    """부재중인 아는 연락처에게 회신 문자 초안 한 줄(고정 글 — 모델 글이 아니다). 그 줄 id(commit 은 부른 쪽)."""
    if caller.caller_class not in REPLY_CLASSES or not caller.candidates:
        return None
    pair = caller.candidates[0]
    made = OutreachMessage(schedule_id=pair.schedule_id, contact_id=pair.contact_id, direction="out", channel="sms",
                           kind="normal", body=MISSED_SMS, origin="agent", origin_name=AGENT_NAME, status="draft",
                           created_at=at)
    session.add(made)
    session.flush()
    return made.id


# ── 통화 한 통의 손잡이 ───────────────────────────────────────────────


class _InboundRun(CallRun):
    """받는 통화의 CallRun — 받지 않고 끝난 통화(on_failed)는 부재중·실패로 닫고 다시 걸지 않는다(거는 통화의 「받지 않음 →
    다시 걸기」가 없다). 고장(broke)은 받기 전이면 「걸렸는지 모름」이 아니라 그냥 실패다. 끝을 적은 뒤 written 이 선다."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.written = asyncio.Event()

    async def on_end(self, reason: str, seconds: int) -> None:
        try:
            await super().on_end(reason, seconds)
        finally:
            self.written.set()

    async def on_failed(self, code: str, detail: str) -> None:
        self.ended = True
        self.end_seen.set()
        try:
            self.outcome = "missed" if code in ("no_answer", "busy") else "failed"
            why = MISSED if code == "busy" else NOT_STARTED if code == "no_answer" else IN_FAILED
            await asyncio.to_thread(_tries, _not_taken, self.call_id, self.outcome, why,
                                    code if code in ("no_answer", "busy", "failed") else "failed", self.at())
        finally:
            self.written.set()

    async def broke(self) -> None:
        if self.started:
            return await super().broke()
        self.outcome = "failed"
        await asyncio.to_thread(_tries, _broken, self.call_id, IN_BROKE, [], None, self.at(), "backend_error", False)


def _not_taken(call_id: int, status: str, why: str, code: str | None, at: datetime) -> None:
    with _db() as session:
        done = session.execute(update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(_LIVE))
                               .values(status=status, fail_reason=why, ended_at=at)
                               .execution_options(synchronize_session=False))
        if done.rowcount == 1 and code is not None:
            events.record(session, Ref("call", call_id), "call_result", "noted", code, now=at)
        session.commit()


async def _follow(run: _InboundRun, listening: asyncio.Task | None) -> None:
    """통화가 끝날 때까지(실제 시간 상한이 있다) 기다리고, 줄을 놓은 뒤 통화 뒤 일. 끝 사건 없이 끝나면 고장으로 닫는다."""
    end, hung, written = (asyncio.ensure_future(event.wait()) for event in (run.end_seen, run.hung, run.written))
    gone = {listening} if listening is not None else set()
    try:
        done, _ = await asyncio.wait({end, hung, *gone}, timeout=run.spec.max_seconds + runner.PLACE_GRACE_S,
                                     return_when=asyncio.FIRST_COMPLETED)
        if hung in done and not done & {end, *gone}:
            await asyncio.wait({end, *gone}, timeout=call_run.HANGUP_WAIT_S, return_when=asyncio.FIRST_COMPLETED)
        if run.ended:
            await asyncio.wait({written}, timeout=call_run.END_WRITE_WAIT_S)
        else:
            await run.broke()
    except asyncio.CancelledError:
        if not run.ended:
            run.stopped()
        raise
    finally:
        for waiter in (end, hung, written):
            waiter.cancel()
        runner._state.live.pop(run.call_id, None)
    await call_run.run_after(run)


# ── 듣기 고리 ─────────────────────────────────────────────────────────


def listening() -> bool:
    """듣기가 걸려 있는가(그 번호의 control 연결을 쥐고 있다 — 음성 진단이 붙지 않는다)."""
    task = _state.listen
    return task is not None and not task.done()


def _wanted() -> tuple[VoiceBackend, str, str] | str:
    """들을 것: (백엔드, AI 전화 번호, 바인딩 해시) 또는 듣지 않는 까닭 off · not_ready."""
    with _db() as session:
        conn = outreach.connection(session)
        if conn is None or conn.inbound_mode not in ("known", "all"):
            return "off"
        settings = session.get(VoiceSettings, conn.id)
        number = phone.normalize(numbers.effective_agent_number(conn, settings))
        if number is None:
            return "not_ready"
        try:
            backend = voice_session.backend_for(session)
        except NotReady:
            return "not_ready"
    binding = getattr(backend, "binding", None)
    key = f"{binding if binding is not None else id(backend)}|{number}"
    return backend, number, hashlib.sha256(key.encode()).hexdigest()


async def _unbind() -> None:
    task, _state.listen, _state.binding = _state.listen, None, None
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(task, call_run.HANGUP_WAIT_S)


async def sync() -> str:
    """듣기 고리의 한 바퀴: 설정을 보고 듣기를 걸거나·다시 걸거나·푼다. 돌려주는 것: off · not_ready · waiting · gave_up ·
    listening. 예외를 올리지 않는다(취소만)."""
    state = _state
    try:
        wanted = await asyncio.to_thread(_wanted)
    except Exception as exc:  # noqa: BLE001 — 설정을 못 읽음: 그대로 둔다
        state.last_error_kind = _kind(exc)
        return "not_ready"
    in_call = listening() and (runner._state.live or runner._state.holding is not None)
    if isinstance(wanted, str):
        if in_call:
            return "waiting"  # 통화 중에는 듣기를 풀지 않는다(풀면 그 통화의 연결이 닫힌다) — 끝난 뒤 다음 바퀴에
        await _unbind()
        state.failures, state.failed_at = 0, None
        return wanted
    backend, number, binding = wanted
    task = state.listen
    if task is not None and task.done():  # 듣기가 끝났다 — 실패면 센다
        state.listen = None
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            state.last_error_kind = _kind(failure)
            logger.warning("받는 통화: 듣기가 끊겼습니다 (%s)", _kind(failure))
            state.failures = 1 if _clock() - state.since >= STABLE_S else state.failures + 1
            state.failed_at = _clock()
    if state.binding != binding:
        if in_call:
            return "waiting"
        await _unbind()
        state.failures, state.failed_at, state.backfilled = 0, None, False
    if listening():
        if not state.backfilled and _clock() - state.since >= BACKFILL_AFTER_S:
            state.backfilled = True
            _behind(backfill(backend))
        return "listening"
    if state.failures >= MAX_FAILS:
        return "gave_up"
    if state.failed_at is not None and _clock() - state.failed_at < RETRY_S:
        return "waiting"
    if runner._state.holding is not None or runner._state.live or runner._diagnosing():
        return "waiting"  # control 연결은 번호당 하나 — 거는 통화·진단이 쓰는 동안 붙지 않는다
    state.binding, state.since = binding, _clock()
    state.listen = asyncio.ensure_future(backend.listen(number, on_incoming))
    return "listening"


async def _run(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await sync()
        except Exception as exc:  # noqa: BLE001 — 어떤 예외도 고리를 멈추지 않는다
            _state.last_error_kind = _kind(exc)
            logger.warning("받는 통화: 듣기 고리가 오류로 끝났습니다 (%s)", _kind(exc))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CHECK_S)


def start() -> None:
    """runner.start 가 부른다(이벤트 루프 안). 이미 떠 있으면 아무것도 하지 않는다."""
    state = _state
    if state.task is not None and not state.task.done():
        return
    state.stop = asyncio.Event()
    state.task = asyncio.create_task(_run(state.stop), name="outreach-call-inbound")


async def stop() -> None:
    """runner.stop 이 부른다: 고리·듣기를 접고, 뒤에서 도는 일(통화 뒤 일)을 runner.STOP_WAIT_S 까지 기다린 뒤 끊는다."""
    state = _state
    task, state.task = state.task, None
    if state.stop is not None:
        state.stop.set()
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    await _unbind()
    pending = [work for work in state.follows if not work.done()]
    if pending:
        _, late = await asyncio.wait(pending, timeout=runner.STOP_WAIT_S)
        for work in late:
            work.cancel()
    state.stop = None


# ── 앱이 꺼진 동안의 전화 ─────────────────────────────────────────────


async def backfill(backend: object) -> int:
    """백엔드가 받는 통화 목록을 주면(missed_calls) 적지 않은 것을 부재중으로 남긴다. 남긴 줄 수. 던지지 않는다."""
    read: Callable | None = getattr(backend, "missed_calls", None)
    if read is None:
        return 0
    until = _now() - timedelta(seconds=OVERLAP_S)
    try:
        since = await asyncio.to_thread(_since, until)
        found = await read(since, until)
        made = await asyncio.to_thread(_backfill, list(found))
    except Exception as exc:  # noqa: BLE001
        _state.last_error_kind = _kind(exc)
        logger.warning("받는 통화: 앱이 꺼진 동안의 전화를 읽지 못했습니다 (%s)", _kind(exc))
        return 0
    for message_id, at in made[1]:
        _behind(gate.dispatch("message", message_id, AGENT, now=at))
    return made[0]


def _since(until: datetime) -> datetime:
    """마지막으로 적은 받는 통화 때(그보다 오래면 BACKFILL_DAYS 전부터)."""
    with _db() as session:
        last = session.scalar(select(OutreachCall.created_at).where(OutreachCall.direction == "in")
                              .order_by(OutreachCall.created_at.desc()).limit(1))
    floor = until - timedelta(days=BACKFILL_DAYS)
    return max(floor, as_utc(last) - timedelta(seconds=OVERLAP_S)) if last is not None else floor


def _backfill(found: list) -> tuple[int, list[tuple[int, datetime]]]:
    made, replies = 0, []
    with _db() as session:
        for item in found:
            at = as_utc(item.at)
            caller = door.admit(session, "call", item.caller_number, now=at).caller  # 등급만 쓴다(받기는 이미 지났다)
            row = _row(caller, item.caller_number, status="missed", fail_reason=WHILE_OFF, created_at=at, ended_at=at,
                       provider_call_id=item.call_id)
            near = OutreachCall.created_at.between(at - timedelta(seconds=OVERLAP_S), at + timedelta(seconds=OVERLAP_S))
            same = [column.is_(None) if value is None else column == value
                    for column, value in ((OutreachCall.contact_id, row.contact_id),
                                          (OutreachCall.peer_number, row.peer_number))]
            taken = select(OutreachCall.id).where(OutreachCall.direction == "in").where(
                (OutreachCall.provider_call_id == item.call_id) | and_(near, *same))
            if session.scalar(taken.limit(1)) is not None:  # 이미 적은 통화(같은 id, 또는 같은 상대·같은 때)
                continue
            session.add(row)
            session.flush()
            events.record(session, Ref("call", row.id), "call_result", "noted", "no_answer", now=at)
            reply = _reply(session, caller, at)
            session.commit()
            made += 1
            if reply is not None:
                replies.append((reply, at))
    return made, replies
