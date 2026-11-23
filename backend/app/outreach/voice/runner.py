"""거는 통화 일꾼(Task 88). 통화 통로(channels/voice.py)가 줄에 넣은 통화(queued)를 하나씩 꺼내 다시 보고, 음성 백엔드
(voice.session.VoiceBackend — 지금은 시험·모래상자가 끼운 가짜뿐, SDK 어댑터는 Task 113)로 걸고, 하네스 도구 묶음으로 통화를
돌린 뒤 결과를 적는다. 통화 한 통의 손잡이(상한·끝 적기)는 call_run.CallRun 이다. 이 모듈은 SDK 를 import 하지 않는다.

- **걸기 직전에 다시 본다**(줄은 기다리는 동안 바뀔 수 있다): 연락처·번호(문과 같은 규칙 — 정리된 꼴·잘못된 번호·전화 받음) →
  `gate.reach_block`(시험 모드·허용 번호·차단·수신 거부) → 근무시간 → 백엔드·SDK 로그 가리개·AI 전화 번호·키 → 통화 명세(번호가
  든 글이면 만들어지지 않는다). 걸리면 `recheck_before_dial` blocked(detail 은 GATE_RULES 이름 또는 not_ready)와 함께 시험 모드는
  blocked_test, 근무시간은 blocked_hours, 그 밖은 draft(fail_reason 에 까닭). 지나가면 `claim(queued → dialing)` 한 조건부
  쓰기로 차지하고 `recheck_before_dial` allowed("ok") — 차지하지 못하면 걸지 않는다. send_mode 는 건드리지 않는다.
- **번호는 코드만 붙인다**: `CallSpec.to_number`(연락처의 지금 번호)·`from_number`(voice_settings.agent_number)는 백엔드만 읽는다.
  첫마디·지시문에는 번호가 없다(greeting·instructions — 자유 글은 가린 뒤에 넣고, 가리개가 놓친 번호는 CallSpec 이 거절한다).
- **도구는 하네스의 것 그대로**: `Toolbox(door.outbound_scope(…), "call", Ref("call", id), names=toolsets.for_class("outbound",
  "call"), caller_class="outbound")` — on_tool 은 `Toolbox.call` 로만 간다.
- **한 통화의 상한**(모두 끝이 있다): 최대 시간은 알림 연결의 `limits.max_call_seconds`(백엔드 시계 on_tick 으로 — WRAP_UP_S 전에
  정리 말, 닿으면 끊음 · `time_limit`), 침묵 SILENCE_S 마다 확인 말 SILENCE_CHECKS 번, 그다음은 끊음(`silence`), 받아쓰기
  MAX_TURNS 줄·도구 MAX_TOOL_CALLS 번(넘으면 끊음 · `time_limit`), 그리고 실제 시간으로도 `max_call_seconds + PLACE_GRACE_S`
  (백엔드가 돌아오지 않으면 끊고 「걸렸는지 확인 필요」).
- **끝은 늘 정해진 상태로**: 받음 → completed(+duration_s·사용량 voice_model) · 받지 않음/통화 중/실패 →
  no_answer/busy/failed(`call_result` · 받지 않음은 gate.after_no_answer — 다시 거는 것은 **새 줄**) · 백엔드 고장·예외·시간 넘김 →
  failed(`call_result` backend_error — 받기 전이면 「걸렸는지 확인 필요」) · 서버가 다시 뜸 → recover. 결과를 모르는 통화는
  자동으로 다시 걸지 않는다. 실제 시간 상한은 **끝 사건이 올 때까지만**이다 — 그 뒤 끝 적기는 call_run.END_WRITE_WAIT_S 로
  따로 묶고, 통화 뒤 일(call_run.run_after → after.finish: 뒤 확인·요약)은 place 가 끝난 뒤 completed 로 적힌 통화만
  call_run.AFTER_WAIT_S 안에서 돈다. 어느 쪽의 실패·시간 넘김도 적힌 통화의 결과를 바꾸지 않는다.
- **번호·키·글은 로그에 없다**: 예외는 종류만. 음성 키는 백엔드를 쓰기 전에 redact.add_secrets 로 거르개에 올리고, SDK 로거가
  가리개에 덮였는지(redact.covers) 본 뒤에만 건다. 받아쓰기는 `{role: agent|peer, text(hide_phones), t}` 로 우리 말과 상대 말을 가른다.
- **통화가 도는 동안 열린 세션·쓰기 잠금이 없다**: DB 일은 짧은 세션을 스레드에서(asyncio.to_thread), 쓰고 곧바로 commit.
- **한 번에 한 통**(MAX_LIVE = door.MAX_LIVE_CALLS): 줄은 걸기 직전부터 끝까지 쥔다(holds_line). 음성 진단(설정의 AI 전화 진단 —
  control 연결은 번호당 하나)이 도는 동안은 걸지 않고 줄은 기다린다. 진단은 notify_settings.voice.worker_connected 로 이 쥠을 본다.
- **일꾼 고리**: TICK_S 마다(줄에 넣으면 곧바로 깨어) 한 바퀴 — 때가 된 예약 통화(자동 다시 걸기 포함)를 문에 DUE_PER_TICK 줄까지
  `gate.dispatch(…, SYSTEM)`, 그리고 줄에서 CALLS_PER_TICK 통을 건다. 바퀴가 MIN_PASS_S 보다 빨리 MAX_FAST_PASSES 번 이어 돌면
  스스로 멈춘다. 끄는 설정은 문자 일꾼과 같다(CHRONOS_OUTREACH_WORKER · CHRONOS_HARNESS_SANDBOX=1) — 꺼진 일꾼은 통로를 등록하지
  않고 줄을 받지 않으며 아무것도 쓰지 않는다. 어떤 예외도 일꾼을 멈추지 않는다 — 그 통화만 failed.
"""

import asyncio
import contextlib
import importlib.util
import logging
import os
import sys
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, literal, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.outreach import hours, phone, redact, worker
from app.outreach.harness import door, events, gate, registry, toolsets
from app.outreach.harness.tools import Toolbox
from app.outreach.harness.types import (
    GATE_RULES,
    Actor,
    NotReady,
    Ref,
    Scope,
)
from app.outreach.voice import call_run, greeting, instructions, numbers, voices
from app.outreach.voice import session as voice_session
from app.outreach.voice.call_run import _LIVE, RESTARTED, CallRun, _close
from app.outreach.voice.session import CallSpec, VoiceBackend
from app.security import crypto
from app.store import contacts, outreach
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    NotifyConnection,
    OutreachCall,
    UtcDateTime,
    VoiceSettings,
)
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

MAX_LIVE = door.MAX_LIVE_CALLS  # 한 번에 한 통(한 곳에만 둔 값)
TICK_S = 10.0  # 한 바퀴 간격(줄에 넣으면 곧바로 깬다)
CALLS_PER_TICK = 1  # 한 바퀴에 거는 통화
DUE_PER_TICK = 3  # 한 바퀴에 문에 넣는 예약 통화
QUEUE_MAX = 50  # 줄의 길이
CHECK_WAIT_S = 10.0  # 백엔드 check 를 기다리는 실제 시간
PLACE_GRACE_S = 60.0  # 실제 시간 상한 = max_call_seconds + 이만큼(백엔드가 돌아오지 않을 때)
STOP_WAIT_S = 20.0  # stop 이 도는 바퀴를 기다리는 시간 — 통화 중이면 SDK 의 끊기(kat_sdk.SDK_HANGUP_S 8초) · 끝 프레임 · 끝 적기까지
SWEEP_ROWS = 50  # recover 가 한 번에 옮기는 줄(상태마다)
MIN_PASS_S, MAX_FAST_PASSES = 1.0, 60  # 이보다 빠른 바퀴가 이만큼 이어지면 스스로 멈춘다(줄에 넣어 깬 바퀴도 센다)
SDK_LOGGERS = ("clawops", "aiohttp", "google_genai", "google.genai", "websockets", "livekit")  # 가리개가 덮어야 걸 수 있다
SWITCH_ON = ("", "on", "1", "true")  # worker.SWITCH_ENV 의 켬 값(문자 일꾼과 같다)
_DIAGNOSIS_MODULE = "app.programs.notify_settings.voice"  # 음성 진단 표시(_VOICE_RUNNING)가 있는 곳 — 불러오지 않고 읽기만

WAITING = "waiting"  # run_one: 줄을 다른 통화나 음성 진단이 쥐고 있어 기다린다(줄은 그대로)
NOT_PLACED = ("draft", "blocked_test", "blocked_hours")  # 다시 보고 걸지 않은 끝
REQUEUED = "서버가 다시 시작돼 걸지 않았습니다. 다시 걸어 주세요"
SPEC_REFUSED = "통화 목적·질문·이름에 전화번호처럼 보이는 글이 있거나 첫마디를 지을 수 없어 걸지 않았습니다"
NO_CONTACT = "이 일정의 연락처가 없어 걸지 않았습니다"
BAD_NUMBER = "받는 번호가 없거나 맞지 않아 걸지 않았습니다"
OFF_HOURS = "걸기 직전에 보니 근무시간 밖이라 걸지 않았습니다"
REACH_TEXT = {
    "test_mode": "걸기 직전에 보니 시험 모드라 허용한 번호에만 겁니다",
    "blocked_or_dnc": "걸기 직전에 보니 차단했거나 수신 거부한 번호라 걸지 않았습니다",
    "precheck": "걸기 직전에 보니 알림 연결이 없거나 번호가 맞지 않아 걸지 않았습니다",
}
NOT_READY_BACKEND = "음성 통화 백엔드가 아직 준비되지 않아 걸지 않았습니다"
LOGS_NOT_COVERED = "음성 SDK 로그 가리개가 준비되지 않아 걸지 않았습니다"
BACKEND_DOWN = "음성 통화 백엔드를 쓸 수 없어 걸지 않았습니다"
KEY_UNREADABLE = "저장된 음성 모델 키를 읽을 수 없어 걸지 않았습니다. 설정에서 키를 다시 넣어 주세요"
NO_AGENT_NUMBER = "AI 전화 번호가 설정되지 않아 걸지 않았습니다"
PREP_FAILED = "걸 준비를 하다 오류가 나 걸지 않았습니다. 다시 걸어 주세요"
SYSTEM = Actor("system", None, "통화 일꾼", None)
_NAMES = toolsets.for_class("outbound", "call")
_PRECHECK, _TEST_MODE, _WORKING_HOURS = GATE_RULES[0], GATE_RULES[1], GATE_RULES[3]
_NOT_READY = "not_ready"
_BAD_HOURS = (KeyError, TypeError, ValueError, AttributeError)


@dataclass
class _State:
    """일꾼의 메모리 상태(프로세스에 하나). 번호·글·키는 두지 않는다."""

    running: bool = False
    ticking: bool = False
    off_reason: str | None = None  # 띄우지 않은 까닭: disabled · sandbox
    queue: deque = field(default_factory=deque)  # 걸 차례를 기다리는 통화 id
    holding: int | None = None  # 줄을 쥔 통화 id(걸기 직전부터 끝까지)
    live: dict = field(default_factory=dict)  # 걸고 있는 통화 id → CallRun
    last_call_at: datetime | None = None
    last_error_kind: str | None = None  # 마지막 통화의 오류 종류(깨끗했으면 None)
    task: asyncio.Task | None = None
    stop: asyncio.Event | None = None
    wake: asyncio.Event | None = None


_state = _State()


@dataclass(frozen=True)
class _Plan:
    """다시 보고 차지한 통화 — 걸 것."""

    spec: CallSpec
    scope: Scope
    model: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _db():
    return contextmanager(get_session)()


def _t(at: datetime):
    return literal(at, UtcDateTime())


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


# ── 밖에서 부르는 것 ───────────────────────────────────────────────────


def enqueue(call_id: int) -> bool:
    """통로가 부른다: 그 통화를 걸 차례에 넣는다(이미 있으면 그대로). 꺼진 일꾼이거나 줄이 가득 차면 False(넣지 못함)."""
    state = _state
    if state.off_reason is not None:
        return False
    if call_id in state.queue:
        return True
    if len(state.queue) >= QUEUE_MAX:
        return False
    state.queue.append(call_id)
    if state.wake is not None:
        state.wake.set()
    return True


def live() -> int:
    """지금 걸고 있는 통화 수."""
    return len(_state.live)


def holds_line(number: str | None = None) -> bool:
    """일꾼이 음성 백엔드의 연결을 쥐고 있는가(걸기 직전부터 통화가 끝날 때까지). 번호와 상관없이 닫힌 쪽으로 답한다 — 음성 진단이
    이것으로 붙지 않는다."""
    return _state.holding is not None or bool(_state.live)


def hangup(call_id: int) -> bool:
    """사람이 화면에서 끊는다. 그 통화가 지금 통화 중이면 끊기를 건네고 True(사건 hangup_by_person), 아니면 False.
    어느 스레드에서 불러도 된다(끊기는 일꾼의 이벤트 루프에서 돈다)."""
    run = _state.live.get(call_id)
    if run is None or run.control is None or run.closing or run.ended:
        return False
    run.by_person = True
    run.loop.call_soon_threadsafe(run.request_hangup)
    return True


def status() -> dict:
    """일꾼의 지금 모습(개발 콘솔 진단이 읽는다) — 메모리 값과 백엔드 준비 상태뿐. 번호·키·글은 없다."""
    s = _state
    return {"running": s.running, "live": live(), "backend": _backend_state(), "listening": False,
            "last_call_at": None if s.last_call_at is None else as_utc(s.last_call_at).isoformat(),
            "last_error_kind": s.last_error_kind, "off_reason": s.off_reason}


def _backend_state() -> str:
    """백엔드 준비 상태 — 걸 때와 같은 길(음성 설정을 읽는 backend_for(session))로 본다."""
    try:
        with _db() as session:
            voice_session.backend_for(session)
    except NotReady:
        try:
            return "sdk_missing" if importlib.util.find_spec("clawops") is None else "not_ready"
        except (ImportError, ValueError):
            return "not_ready"
    except Exception as exc:  # noqa: BLE001 — 상태 보기는 던지지 않는다(DB 를 못 읽음 등)
        logger.warning("통화 일꾼: 음성 백엔드 상태를 읽지 못했습니다 (%s)", _kind(exc))
        return "not_ready"
    return "ok" if all(redact.covers(name) for name in SDK_LOGGERS) else "not_ready"


def _diagnosing() -> bool:
    """이 프로세스에서 음성 진단이 도는가(그 진단이 control 연결을 쓴다). 진단 모듈을 불러오지 않고 표시만 읽는다."""
    module = sys.modules.get(_DIAGNOSIS_MODULE)
    return bool(getattr(module, "_VOICE_RUNNING", None))


# ── 한 통화 ────────────────────────────────────────────────────────────


async def run_one(call_id: int, *, now: datetime | None = None) -> str | None:
    """그 통화를 다시 보고 걸어 끝까지 돌린다. 돌려주는 것: 줄의 끝 상태(completed · no_answer · busy · failed · draft ·
    blocked_test · blocked_hours), WAITING(다른 통화나 음성 진단이 줄을 쥐고 있음 — 줄은 queued 그대로), None(걸 줄이 아님 —
    아무것도 하지 않음). now 를 주면(시험) 그 시각에서 백엔드 시계만큼 흐른 것으로 적는다. 예외를 올리지 않는다(취소만 지나간다)."""
    state = _state
    if state.holding is not None or len(state.live) >= MAX_LIVE or _diagnosing():
        return WAITING
    state.holding = call_id  # 기다림 없이 쥔다 — 진단의 표시 확인·더하기와 엇갈리지 않는다
    base = _now() if now is None else as_utc(now)
    try:
        return await _call(call_id, base)
    except Exception as exc:  # noqa: BLE001 — 걸기 전(다시 보기·명세·도구 상자)의 뜻밖의 예외: 그 줄만 닫고 일꾼은 이어 간다
        state.last_error_kind = _kind(exc)
        logger.warning("통화 일꾼: 통화를 준비하지 못했습니다 (%s)", _kind(exc))
        try:
            return await asyncio.to_thread(_prep_failed, call_id, base)
        except Exception as again:  # noqa: BLE001 — 못 닫으면 다음에 뜰 때 recover 가 닫는다
            logger.warning("통화 일꾼: 준비하지 못한 통화를 닫지 못했습니다 (%s)", _kind(again))
            return None
    finally:
        state.holding = None
        state.live.pop(call_id, None)


async def _call(call_id: int, base: datetime) -> str | None:
    state = _state
    backend, problem = await asyncio.to_thread(_backend_for)
    if backend is not None:
        problem = await _check(backend)
    plan = await asyncio.to_thread(_prepare, call_id, base, problem)
    if not isinstance(plan, _Plan):
        return plan
    run = CallRun(call_id, plan.spec, base, plan.model)
    run.box = Toolbox(plan.scope, "call", Ref("call", call_id), names=_NAMES, caller_class="outbound", clock=run.at)
    state.live[call_id] = run
    state.last_call_at = base
    try:
        await _place(backend, plan.spec, run)
    except asyncio.CancelledError:
        if not run.ended:  # 끝 사건이 왔으면 끝은 정해졌다(끝 쓰기는 스레드에서 마친다) — 멈춤이 실패로 덮지 않는다
            run.stopped()
        raise
    except Exception as exc:  # noqa: BLE001 — 백엔드 고장·손잡이 예외·실제 시간 넘김: 이 통화만 failed
        state.last_error_kind = _kind(exc)
        logger.warning("통화 일꾼: 통화가 예외로 끝났습니다 (%s)", _kind(exc))
        await run.broke()
    else:
        if run.ended:
            state.last_error_kind = None
        else:  # 끝 손잡이 없이 돌아왔다 — 약속을 어긴 백엔드
            state.last_error_kind = "no_end"
            await run.broke()
    state.live.pop(call_id, None)  # 통화는 끝났다(끊기·live 셈에서 빠짐). 줄은 통화 뒤 일까지 쥔다 — 한 번에 한 통
    await call_run.run_after(run)
    return run.outcome


async def _place(backend: VoiceBackend, spec: CallSpec, run: CallRun) -> None:
    """건다 — 실제 시간 상한은 끝 사건(on_end·on_failed)이 올 때까지만: 통화 전체 max_seconds + PLACE_GRACE_S, 그리고 일꾼이
    끊기를 건넨 뒤에는 끝 사건을 call_run.HANGUP_WAIT_S 만 기다린다(세션이 실패해 끝 사건이 오지 않는 백엔드). 그 전에 넘으면
    TimeoutError. 끝 사건이 온 뒤에는 끝 적기를 call_run.END_WRITE_WAIT_S 까지 기다리고, 그 뒤의 예외·시간 넘김은 종류만
    로그한다(끝은 이미 정해졌다 — 고장으로 바꾸지 않는다)."""
    task = asyncio.ensure_future(backend.place(spec, run))
    hung = asyncio.ensure_future(run.hung.wait())
    end = asyncio.ensure_future(run.end_seen.wait())
    try:
        done, _ = await asyncio.wait({task, hung, end}, timeout=spec.max_seconds + PLACE_GRACE_S,
                                     return_when=asyncio.FIRST_COMPLETED)
        if hung in done and not done & {task, end}:
            done, _ = await asyncio.wait({task, end}, timeout=call_run.HANGUP_WAIT_S, return_when=asyncio.FIRST_COMPLETED)
        if not done & {task, end}:
            raise TimeoutError
        if not run.ended:  # 끝 사건 없이 place 가 돌아왔다 — 예외면 그대로(고장), 아니면 부른 쪽이 no_end 로
            task.result()
            return
        if not task.done():
            await asyncio.wait({task}, timeout=call_run.END_WRITE_WAIT_S)
        if not task.done() or task.cancelled() or task.exception() is not None:
            failure = "TimeoutError" if not task.done() else "CancelledError" if task.cancelled() else _kind(task.exception())
            logger.warning("통화 일꾼: 끝 사건 뒤 통화를 마무리하지 못했습니다 (%s)", failure)
    finally:
        hung.cancel()
        end.cancel()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def _prep_failed(call_id: int, at: datetime) -> str | None:
    """걸기 전의 뜻밖의 예외: 아직 queued·dialing(차지만 하고 걸지 않음)이면 failed 로 닫는다 — 건 것이 없으니 그날 셈에서 빼고
    문을 막지 않는다. 바꾼 상태(또는 None)."""
    with _db() as session:
        closing = update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(("queued", "dialing")))
        moved = session.execute(closing.values(status="failed", fail_reason=PREP_FAILED, claimed_at=None)
                                .execution_options(synchronize_session=False))
        if moved.rowcount != 1:
            return None
        events.record(session, Ref("call", call_id), "recheck_before_dial", "blocked", "local_error", now=at)
        session.commit()
        return "failed"


def _backend_for() -> tuple[VoiceBackend | None, str | None]:
    """음성 설정의 키를 거르개에 올리고(백엔드를 쓰기 전에) 쓸 백엔드를 고른다. (백엔드, 없거나 쓸 수 없는 까닭)."""
    with _db() as session:
        conn = outreach.connection(session)
        settings = session.get(VoiceSettings, conn.id) if conn is not None else None
        if settings is not None and settings.secret_ciphertext:
            try:
                redact.add_secrets(crypto.decrypt(settings.secret_ciphertext))
            except crypto.SecretUnreadable:
                return None, KEY_UNREADABLE
        try:
            return voice_session.backend_for(session), None
        except NotReady:
            return None, NOT_READY_BACKEND


async def _check(backend: VoiceBackend) -> str | None:
    """걸어도 되는 백엔드인가 — SDK 로거가 가리개에 덮였고 check 가 참이면 None, 아니면 까닭."""
    if not all(redact.covers(name) for name in SDK_LOGGERS):
        return LOGS_NOT_COVERED
    try:
        ok, _why = await asyncio.wait_for(backend.check(), CHECK_WAIT_S)
    except Exception as exc:  # noqa: BLE001
        logger.warning("통화 일꾼: 음성 백엔드를 확인하지 못했습니다 (%s)", _kind(exc))
        ok = False
    return None if ok is True else BACKEND_DOWN


def _prepare(call_id: int, at: datetime, problem: str | None) -> "_Plan | str | None":
    """걸기 직전에 다시 보고(모듈 머리 글), 걸 수 있으면 queued → dialing 으로 차지한다(스레드에서, 짧은 세션)."""
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        if row is None or row.direction != "out" or row.status != "queued":
            return None
        contact = session.get(Contact, row.contact_id) if row.contact_id is not None else None
        if contact is None or contact.schedule_id != row.schedule_id:
            return _stop(session, call_id, "draft", NO_CONTACT, _PRECHECK, at)
        number = phone.normalize(contact.phone)
        if (number is None or contact.phone != number or contact.phone_invalid or not contact.can_call
                or not phone.can_call(number)):
            return _stop(session, call_id, "draft", BAD_NUMBER, _PRECHECK, at)
        barred = gate.reach_block(session, number)
        if barred is not None:
            status = "blocked_test" if barred == _TEST_MODE else "draft"
            return _stop(session, call_id, status, REACH_TEXT.get(barred, REACH_TEXT[_PRECHECK]), barred, at)
        if not _working(session, contact, row.schedule_id, at):
            return _stop(session, call_id, "blocked_hours", OFF_HOURS, _WORKING_HOURS, at)
        if problem is not None:
            return _stop(session, call_id, "draft", problem, _NOT_READY, at)
        conn = outreach.connection(session)
        settings = session.get(VoiceSettings, conn.id)
        agent_number = phone.normalize(numbers.effective_agent_number(conn, settings))  # 비었으면 알림 연결의 발신번호
        if agent_number is None:
            return _stop(session, call_id, "draft", NO_AGENT_NUMBER, _NOT_READY, at)
        try:
            spec = _spec(session, row, contact, number, agent_number, settings, conn)
            scope = door.outbound_scope(session, row.schedule_id, contact.id)
        except (ValueError, contacts.NotFound):
            return _stop(session, call_id, "draft", SPEC_REFUSED, _PRECHECK, at)
        model = numbers.effective_model(settings.provider, settings.model) if settings is not None else None
        if not outreach.claim(session, "call", call_id, ("queued",), "dialing", now=at):
            session.rollback()
            return None
        events.record(session, Ref("call", call_id), "recheck_before_dial", "allowed", "ok", now=at)
        session.commit()
        return _Plan(spec, scope, model)


def _working(session: Session, contact: Contact, schedule_id: int | None, at: datetime) -> bool:
    try:
        return hours.is_working(contact.hours_json, contacts.calendar_of(session, schedule_id), at)
    except _BAD_HOURS:
        return False


def _spec(session: Session, row: OutreachCall, contact: Contact, number: str, agent_number: str,
          settings: VoiceSettings, conn: NotifyConnection) -> CallSpec:
    """통화 명세. 번호는 to_number·from_number 에만 — 글에 번호가 있으면 CallSpec 이 ValueError(걸지 않는다)."""
    record = session.get(ScheduleRecord, row.schedule_id)
    site = record.name if record is not None else ""
    company = contacts.get_company(session, row.schedule_id, contact.company_id)
    language = contact.language or greeting.DEFAULT_LANGUAGE
    voice_id = row.voice_id or voices.pick(contact.gender, contact.voice_mode, contact.voice_id, language, settings)
    text = instructions.outbound(site, contact.name, contact.role_title, company.name, row.purpose, row.questions_json,
                                 row.avoid_json, language)
    return CallSpec(direction="out", to_number=number, from_number=agent_number, language=language, voice_id=voice_id,
                    first_line=greeting.first_line(language, site, contact.name), instructions=text,
                    tools=toolsets.tool_defs(_NAMES), max_seconds=outreach.limits(conn).max_call_seconds,
                    record_to=Settings().data_dir / "recordings" / str(row.schedule_id) / str(row.id))


def _stop(session: Session, call_id: int, status: str, why: str, rule: str, at: datetime) -> str | None:
    """다시 본 것에 걸렸다: queued 일 때만 그 상태로(까닭은 fail_reason) 옮기고 recheck_before_dial blocked."""
    moved = session.execute(update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status == "queued")
                            .values(status=status, fail_reason=why, claimed_at=None)  # 건 적 없음 — 그날 셈에서 뺀다
                            .execution_options(synchronize_session=False))
    if moved.rowcount != 1:
        session.rollback()
        return None
    events.record(session, Ref("call", call_id), "recheck_before_dial", "blocked", rule, now=at)
    session.commit()
    return status


def recover(now: datetime | None = None, *, before: datetime | None = None) -> int:
    """서버가 뜰 때(고리가 처음에 한 번): before(없으면 지금) 전에 차지된 dialing·in_call 통화는 failed 「서버가 다시 시작돼
    끊겼습니다」, 줄에서 기다리던 queued 통화는 draft(다시 걸지 않는다 — 사람이 다시 누른다). 둘 다 server_restart. 옮긴 줄 수."""
    at = _now() if now is None else as_utc(now)
    cut = at if before is None else min(at, as_utc(before))
    stamp = func.coalesce(OutreachCall.claimed_at, OutreachCall.created_at)
    with _db() as session:
        stale = list(session.scalars(select(OutreachCall.id).where(OutreachCall.status.in_(_LIVE), stamp < _t(cut))
                                     .order_by(OutreachCall.id).limit(SWEEP_ROWS)))
        waiting = list(session.scalars(select(OutreachCall.id).where(OutreachCall.status == "queued", stamp < _t(cut))
                                       .order_by(OutreachCall.id).limit(SWEEP_ROWS)))
    moved = sum(_close(call_id, _LIVE, "failed", RESTARTED, at) for call_id in stale)
    return moved + sum(_close(call_id, ("queued",), "draft", REQUEUED, at) for call_id in waiting)


# ── 일꾼 고리 ──────────────────────────────────────────────────────────


def _stopping() -> bool:
    return _state.stop is not None and _state.stop.is_set()


def _due(at: datetime) -> list[int]:
    """때가 된 예약 통화(사람의 예약·자동 다시 걸기), 이른 것부터 DUE_PER_TICK 줄까지."""
    with _db() as session:
        due = select(OutreachCall.id).where(OutreachCall.direction == "out", OutreachCall.status == "scheduled",
                                            OutreachCall.scheduled_at <= _t(at))
        return list(session.scalars(due.order_by(OutreachCall.scheduled_at, OutreachCall.id).limit(DUE_PER_TICK)))


async def tick(now: datetime | None = None) -> dict:
    """한 바퀴: 때가 된 예약 통화를 문에 넣고(문이 처음부터 다시 검사한다 — 지나가면 통로가 줄에 넣는다), 줄에서 CALLS_PER_TICK
    통을 건다. 돌려주는 것 {skipped: None | "busy", due: 문에 넣은 수, placed: 건 수}. 예외를 올리지 않는다."""
    state, result = _state, {"skipped": None, "due": 0, "placed": 0}
    if state.ticking:
        return result | {"skipped": "busy"}
    state.ticking = True
    try:
        at = _now() if now is None else as_utc(now)
        for call_id in await asyncio.to_thread(_due, at):
            if _stopping():
                break
            try:
                await gate.dispatch("call", call_id, SYSTEM, now=at)
            except Exception as exc:  # noqa: BLE001
                logger.warning("통화 일꾼: 예약 통화를 문에 넣지 못했습니다 (%s)", _kind(exc))
                continue
            result["due"] += 1
        for _ in range(QUEUE_MAX):  # 걸 줄이 아닌 것(끝난 줄 등)은 버리고 다음 것 — 줄 길이만큼까지
            if not state.queue or _stopping() or result["placed"] >= CALLS_PER_TICK:
                break
            call_id = state.queue.popleft()
            outcome = await run_one(call_id, now=now)
            if outcome == WAITING:
                state.queue.appendleft(call_id)
                break
            if outcome is not None and outcome not in NOT_PLACED:
                result["placed"] += 1
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 일꾼을 멈추지 않는다
        state.last_error_kind = _kind(exc)
        logger.warning("통화 일꾼: 한 바퀴가 오류로 끝났습니다 (%s)", _kind(exc))
    finally:
        state.ticking = False
    return result


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    """다음 바퀴까지 쉰다 — 멈춤 신호나 줄에 넣은 것이 오면 곧바로 깬다."""
    wake = _state.wake
    waiters = [asyncio.ensure_future(stop.wait())] + ([asyncio.ensure_future(wake.wait())] if wake is not None else [])
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        if wake is not None:
            wake.clear()


async def _run(stop: asyncio.Event, started: datetime) -> None:
    """일꾼 고리: 먼저 recover, 그다음 멈춤 신호가 올 때까지 한 바퀴 돌고 쉬기."""
    state = _state
    state.running = True
    try:
        try:
            await asyncio.to_thread(recover, before=started)
        except Exception as exc:  # noqa: BLE001
            logger.warning("통화 일꾼: 남은 통화를 정리하지 못했습니다 (%s)", _kind(exc))
        fast = 0
        while not stop.is_set():
            began = time.monotonic()
            try:
                await tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("통화 일꾼: 한 바퀴가 오류로 끝났습니다 (%s)", _kind(exc))
            await _pause(stop, TICK_S)
            if stop.is_set():
                break
            fast = fast + 1 if time.monotonic() - began < MIN_PASS_S else 0
            if fast >= MAX_FAST_PASSES:  # 쉬지 못하고 헛돈다 — 끝없이 돌지 않고 멈춘다
                state.last_error_kind = "spinning"
                logger.error("통화 일꾼: 바퀴가 쉬지 않고 돌아 멈춥니다")
                break
    finally:
        state.running = False


def _off_reason() -> str | None:
    """띄우지 않을 까닭 — 문자 일꾼과 같은 끄는 설정(worker.SWITCH_ENV)과 모래상자 프로세스."""
    if os.environ.get(registry.SANDBOX_ENV) == "1":
        return "sandbox"
    return None if os.environ.get(worker.SWITCH_ENV, "").strip().lower() in SWITCH_ON else "disabled"


def start() -> None:
    """서버가 뜰 때(lifespan, 이벤트 루프 안). 통화 통로를 등록하고 일꾼을 띄운다 — 이미 떠 있으면 아무것도 하지 않는다.
    끄는 설정이면 띄우지 않는다(통로도 등록하지 않고, 줄도 받지 않고, 아무것도 쓰지 않는다)."""
    state = _state
    if state.task is not None and not state.task.done():
        return
    state.off_reason = _off_reason()
    if state.off_reason is not None:
        logger.info("통화 일꾼: 띄우지 않습니다 (%s)", state.off_reason)
        return
    import app.outreach.channels.voice  # noqa: F401 — 통화 통로를 등록한다(줄을 비울 일꾼이 있을 때만)

    state.stop, state.wake = asyncio.Event(), asyncio.Event()
    state.running = True
    state.task = asyncio.create_task(_run(state.stop, _now()), name="outreach-call-runner")
    logger.info("통화 일꾼: 띄웁니다")


async def stop() -> None:
    """서버를 닫을 때. 통화 중이면 끊기를 건네고, 고리가 끝나기를 STOP_WAIT_S 까지 기다린 뒤 그래도 돌면 끊는다(끊긴 통화는
    「서버가 다시 시작돼 끊겼습니다」로 닫힌다). 떠 있지 않으면 아무것도 하지 않는다."""
    state = _state
    task, stopping, state.task = state.task, state.stop, None
    if task is None or stopping is None:
        return
    stopping.set()
    for run in list(state.live.values()):
        run.request_hangup()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=STOP_WAIT_S)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("통화 일꾼: 멈추는 중 오류 (%s)", _kind(exc))
    state.stop = None
