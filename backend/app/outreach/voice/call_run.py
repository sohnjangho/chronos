"""통화 한 통의 손잡이(Task 88) — `CallRun` 은 voice.session.CallHandlers 를 구현한다. 거는 통화 일꾼(runner)이 쓰고, 받는 통화
(Task 95)도 같은 것을 쓴다. 통화 중의 상한(침묵·정리 말·최대 시간·받아쓰기 줄·도구 호출)과 끝을 적는 쓰기가 여기 있다.
걸기 전에 다시 보는 것·줄·고리는 runner 에 있다. 이 모듈은 SDK 를 import 하지 않는다.

- 받아쓰기는 `{role: agent|peer, text(redact.hide_phones), t}` — 우리 말과 상대 말을 가른다. 통화 중에는 한 줄씩 짧게 적고(실패해도
  통화는 이어진다), 끝에 모은 것을 한꺼번에 다시 적는다.
- 첫 발화가 AI 비서·기록을 밝히지 않으면(greeting.discloses — 그 통화 언어의 꼭 하는 말·부정 말, Task 100) 고정 첫마디를 한 번
  더 시키고, 그래도 아니면 끊는다.
- 끝: 받음 → completed(+길이·사용량) · 받은 뒤 연결·세션이 끊김(END_LOST) → failed 「확인 필요」 · 받지 않음/통화 중/
  실패 → 그 상태(+받지 않음은 gate.after_no_answer) · 고장 → failed(`call_result` backend_error). 모든 쓰기는 짧은 세션을 스레드에서.
- 통화 뒤 일(after_call → Task 89 after.finish)은 끝 손잡이 안에서 돌지 않는다: 통화를 돌린 쪽이 place 가 끝난 뒤 `run_after`
  로 부른다 — 줄이 completed 로 적혔을 때만, 자기 시간 상한 AFTER_WAIT_S 로, 실패·시간 넘김은 통화의 결과를 바꾸지 않는다.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update

from app.db import get_session
from app.outreach import redact
from app.outreach.harness import events, gate
from app.outreach.harness.tools import Toolbox
from app.outreach.harness.types import DELIVERY_VERDICT, Ref
from app.outreach.voice import after, greeting
from app.outreach.voice import session as voice_session
from app.outreach.voice.session import CallSpec
from app.store import outreach
from app.store.tables_outreach import OutreachCall

logger = logging.getLogger(__name__)

SILENCE_S = 15  # 이만큼 아무도 말하지 않으면 확인 말
SILENCE_CHECKS = 2  # 확인 말 수 — 그다음 침묵에는 끊는다
WRAP_UP_S = 20  # 최대 시간 이만큼 전에 정리 말
MAX_TURNS = 400  # 한 통화의 받아쓰기 줄(우리 말·상대 말 합쳐)
MAX_TOOL_CALLS = 40  # 한 통화의 도구 호출
HANGUP_WAIT_S = 15.0  # 고장 뒤 끊기를 기다리는 시간 · 일꾼이 끊기를 건넨 뒤 끝 사건을 기다리는 시간 — SDK 어댑터의 끊기
#                     (보낸 소리가 다 나갈 때까지 5초 + 여유: kat_sdk.SDK_HANGUP_S 8초)와 끝 확인(kat_sdk.END_GRACE_S 11초)보다 길게
END_WRITE_WAIT_S = 30.0  # 끝 사건이 온 뒤: 끝을 적는 쓰기(_tries — WRITE_TRIES 번, SQLite 기다림 포함)와 백엔드가 place 에서
#                         돌아오기까지를 함께 기다리는 시간(넘으면 place 를 끊되 끝은 그대로 — runner._place)
AFTER_WAIT_S = 90.0  # 통화 뒤 일(뒤 확인 + 요약 — 요약 부름은 after.TIMEOUT_S)을 기다리는 시간
WRITE_TRIES, WRITE_PAUSE_S = 3, 0.2  # 통화 끝을 적는 시도
HELLO = "여보세요, 들리시나요?"
GIVE_UP = "잘 들리지 않아 통화를 마치겠습니다"
WRAP_UP = "시간이 다 되어 정리하겠습니다. 담당자가 다시 연락드리겠습니다"
FAILED_TEXT = {"no_answer": "받지 않았습니다", "busy": "통화 중이었습니다", "failed": "전화를 걸지 못했습니다"}
RESTARTED = "서버가 다시 시작돼 끊겼습니다"
UNKNOWN_IF_PLACED = "음성 통화 오류 — 전화가 걸렸는지 확인 필요"
BROKE_DURING_CALL = "통화 중 음성 통화 오류로 끊겼습니다"
NOT_DISCLOSED = "첫마디에 AI 비서·기록 안내가 없어 끊었습니다"
LOST = "통화 연결이 중간에 끊겼습니다 — 확인 필요"
TOOL_CAP = "이 통화에서는 더 처리할 수 없습니다"
_LIVE = ("dialing", "in_call")


async def after_call(call_id: int, box: Toolbox | None = None) -> None:
    """받은 통화가 끝난 뒤의 일 — Task 89 의 뒤 확인·요약·결과 제안. box 는 그 통화의 도구 상자(도구 결과·범위)."""
    await after.finish(call_id, box)


async def run_after(run: "CallRun") -> None:
    """통화를 돌린 쪽이 place 가 끝난 뒤(그 시간 창 밖에서) 부른다: 줄이 completed 로 적힌 통화만, AFTER_WAIT_S 안에서.
    실패·시간 넘김은 종류만 로그 — 통화의 결과(줄·outcome)는 그대로다. 취소(일꾼이 멈춤)만 지나간다."""
    if not run.recorded:
        return
    try:
        await asyncio.wait_for(after_call(run.call_id, run.box), AFTER_WAIT_S)
    except Exception as exc:  # noqa: BLE001 — TimeoutError 포함
        logger.warning("통화 일꾼: 통화 뒤 일을 마치지 못했습니다 (%s)", _kind(exc))


def _db():
    return contextmanager(get_session)()


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


class CallRun:
    """통화 한 통의 손잡이(voice.session.CallHandlers) — 거는 통화와 받는 통화(Task 95)가 같이 쓴다. 손잡이는 차례대로 불리지만
    say 안에서 받아쓰기가 다시 불릴 수 있어(백엔드가 그 말을 돌려준다) 잠그지 않는다. 시각은 base + 백엔드 시계."""

    def __init__(self, call_id: int, spec: CallSpec, base: datetime, model: str | None) -> None:
        self.call_id, self.spec, self.base, self.model = call_id, spec, base, model
        self.box: Toolbox | None = None
        self.loop = asyncio.get_running_loop()
        self.control: Any = None
        self.elapsed = 0.0
        self.lines: list[dict] = []  # 받아쓰기(가린 글) — 끝에 한꺼번에 다시 적는다
        self.started = self.ended = self.closing = self.by_person = self.wrapped = self.resaid = False
        self.hung = asyncio.Event()  # 일꾼이 끊기를 건넸다 — 그 뒤로는 끝 사건을 HANGUP_WAIT_S 만 기다린다(runner)
        self.end_seen = asyncio.Event()  # 끝 사건(on_end·on_failed)이 왔다 — 실제 시간 상한은 여기까지(runner)
        self.recorded = False  # 끝을 completed 로 적었다(그때만 통화 뒤 일)
        self.opening_pending = True
        self.silence_checks, self.last_check, self.turns, self.tool_calls = 0, None, 0, 0
        self.note: str | None = None  # 끝난 줄의 fail_reason 에 남길 말
        self.outcome: str | None = None
        self._pending: set[asyncio.Task] = set()

    def at(self) -> datetime:
        return self.base + timedelta(seconds=self.elapsed)

    # ── CallHandlers ──────────────────────────────────────────────────────────────────────────────
    async def on_start(self, control: Any) -> None:
        self.control, self.started = control, True
        self.box.set_control(control)
        await self._quiet(_mark_in_call, self.call_id, self.at())

    async def on_transcript(self, role: str, text: str, t: float) -> None:
        self.elapsed = max(self.elapsed, float(t))
        self.turns += 1
        if self.turns > MAX_TURNS:
            if not self.closing:
                await self._event("time_limit", f"받아쓰기 상한({MAX_TURNS}줄)")
                await self._hang()
            return
        role = role if role in ("agent", "peer") else "peer"
        line = {"role": role, "text": redact.hide_phones(text) if isinstance(text, str) else "", "t": round(float(t), 1)}
        self.lines.append(line)
        await self._quiet(_write_transcript, self.call_id, line)
        if role == "peer":
            self.silence_checks = 0
        elif self.opening_pending:
            await self._opening(text)

    async def on_tool(self, name: str, args: dict) -> dict:
        self.tool_calls += 1
        if self.tool_calls > MAX_TOOL_CALLS:
            if not self.closing:
                await self._event("time_limit", f"도구 호출 상한({MAX_TOOL_CALLS}번)")
                await self._hang()
            return {"error": TOOL_CAP}
        return await self.box.call(name, args)

    async def on_tick(self, elapsed: float, silent_for: float) -> None:
        self.elapsed = max(self.elapsed, float(elapsed))
        if self.closing:
            return
        limit = self.spec.max_seconds
        if elapsed >= limit:
            await self._event("time_limit", "최대 통화 시간")
            await self._hang()
        elif not self.wrapped and elapsed >= limit - WRAP_UP_S:
            self.wrapped = True
            await self._event("time_limit", "정리 안내")
            await self.control.say(WRAP_UP)
        elif silent_for >= SILENCE_S and (self.last_check is None or elapsed - self.last_check >= SILENCE_S):
            self.last_check = elapsed
            self.silence_checks += 1
            if self.silence_checks <= SILENCE_CHECKS:
                await self._event("silence", f"침묵 확인 {self.silence_checks}")
                await self.control.say(HELLO)
            else:
                await self._event("silence", "침묵으로 끊음")
                await self.control.say(GIVE_UP)
                await self._hang()

    async def on_end(self, reason: str, seconds: int) -> None:
        self.ended = True
        self.end_seen.set()
        self.elapsed = max(self.elapsed, float(seconds))
        if reason == voice_session.END_LOST:  # 받은 뒤 연결·세션이 끊김 — 통화됨이 아니다(확인 필요)
            self.outcome = "failed"
            await asyncio.to_thread(_tries, _broken, self.call_id, LOST, list(self.lines), int(seconds), self.at())
            return
        if self.note == NOT_DISCLOSED:  # 밝히지 않아 끊은 통화는 「통화됨」이 아니다(사용량·통화 뒤 일 없음)
            self.outcome = "failed"
            await asyncio.to_thread(_tries, _broken, self.call_id, NOT_DISCLOSED, list(self.lines), int(seconds), self.at(),
                                    "failed")
            return
        self.outcome = "completed"
        self.recorded = await asyncio.to_thread(_tries, _finish, self.call_id, list(self.lines), int(seconds), self.note,
                                                self.by_person, self.model, self.at()) is True

    async def on_failed(self, code: str, detail: str) -> None:
        self.ended = True
        self.end_seen.set()
        self.outcome = code if code in FAILED_TEXT else "failed"
        await asyncio.to_thread(_tries, _unanswered, self.call_id, self.outcome, self.at())
        if self.outcome == "no_answer":
            try:
                await asyncio.to_thread(gate.after_no_answer, self.call_id, now=self.at())
            except Exception as exc:  # noqa: BLE001 — 다시 걸기를 못 만들어도 이 통화의 끝은 적혔다
                logger.warning("통화 일꾼: 다시 걸 줄을 만들지 못했습니다 (%s)", _kind(exc))

    # ── 끝나지 못한 통화 ─────────────────────────────────────────────────────────────────────────────
    async def broke(self) -> None:
        """백엔드 고장·예외·시간 넘김: 통화 중이면 끊어 보고(기다림에 끝이 있다) failed 로 닫는다. 받기 전이면 「걸렸는지 확인 필요」."""
        if self.started and self.control is not None and not self.closing:
            self.closing = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.control.hangup(), HANGUP_WAIT_S)
        self.outcome = "failed"
        why = BROKE_DURING_CALL if self.started else UNKNOWN_IF_PLACED
        await asyncio.to_thread(_tries, _broken, self.call_id, why, list(self.lines),
                                int(self.elapsed) if self.started else None, self.at(), "backend_error", True)

    def stopped(self) -> None:
        """일꾼이 멈추며 통화가 끊겼다(취소) — 기다리지 않고 곧바로 닫는다(서버가 다시 뜬 것과 같은 끝)."""
        self.outcome = "failed"
        try:
            _close(self.call_id, _LIVE, "failed", RESTARTED, self.at())
        except Exception as exc:  # noqa: BLE001 — 못 적으면 다음에 뜰 때 recover 가 닫는다
            logger.warning("통화 일꾼: 끊긴 통화를 적지 못했습니다 (%s)", _kind(exc))

    def request_hangup(self) -> None:
        """이벤트 루프에서: 끊기를 시작한다(사람이 끊음·일꾼이 멈춤)."""
        task = asyncio.ensure_future(self._hang())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    # ── 안쪽 ───────────────────────────────────────────────────────────────────────────────────────
    async def _opening(self, text: str) -> None:
        """첫 발화가 AI 비서·기록을 밝혔는가. 아니면 고정 첫마디를 한 번 더 말하게 하고, 그래도 아니면 끊는다."""
        if _discloses(self.spec.language, text, self.spec.first_line):
            self.opening_pending = False
        elif not self.resaid:
            self.resaid = True
            await self.control.say(self.spec.first_line)
        else:
            self.opening_pending, self.note = False, NOT_DISCLOSED
            await self._hang()

    async def _hang(self) -> None:
        if self.closing or self.control is None:
            return
        self.closing = True
        self.hung.set()
        await self.control.hangup()

    async def _event(self, rule: str, detail: str) -> None:
        await self._quiet(_record, self.call_id, rule, detail, self.at())

    async def _quiet(self, work: Callable, *args: Any) -> None:
        """통화 중의 짧은 쓰기 — 실패해도 통화를 끊지 않는다(종류만 로그). 받아쓰기는 끝에 한꺼번에 다시 적는다."""
        try:
            await asyncio.to_thread(work, *args)
        except Exception as exc:  # noqa: BLE001
            logger.warning("통화 일꾼: 통화 중 기록을 적지 못했습니다 (%s)", _kind(exc))


def _discloses(language: str, spoken: str, first_line: str | None = None) -> bool:
    """그 통화 언어(spec.language)로 AI 임·기록됨을 밝혔는가 — 부정 말(「AI 가 아니고 … 기록되지 않습니다」 · not …)은 greeting 이
    언어마다 거른다(Task 100 — 예전에는 여기서 한국어 부정 말만 걸렀다)."""
    return greeting.discloses(language, spoken, first_line)  # 첫마디의 현장·사람 이름은 부정으로 보지 않는다


# ── 통화의 쓰기(스레드에서, 짧은 세션, 곧바로 commit) ─────────────────────────────


def _tries(work: Callable, *args: Any) -> Any:
    """통화의 끝은 꼭 적는다 — 몇 번 다시 해 보고(돌려준 값을 그대로), 끝내 못 적으면 종류만 로그하고 None(줄은 다음에 뜰 때
    recover 가 닫는다)."""
    for attempt in range(WRITE_TRIES):
        if attempt:
            time.sleep(WRITE_PAUSE_S)
        try:
            return work(*args)
        except Exception as exc:  # noqa: BLE001
            failure = _kind(exc)
    logger.error("통화 일꾼: 통화의 끝을 적지 못했습니다 (%s)", failure)
    return None


def _mark_in_call(call_id: int, at: datetime) -> None:
    with _db() as session:
        session.execute(update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status == "dialing")
                        .values(status="in_call", started_at=at).execution_options(synchronize_session=False))
        session.commit()


def _write_transcript(call_id: int, line: dict) -> None:
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        if row is not None:
            row.transcript_json = [*(row.transcript_json or []), line][:MAX_TURNS]
            session.commit()


def _record(call_id: int, rule: str, detail: str, at: datetime) -> None:
    with _db() as session:
        events.record(session, Ref("call", call_id), rule, "noted", detail, now=at)
        session.commit()


def _finish(call_id: int, lines: list[dict], seconds: int, note: str | None, by_person: bool, model: str | None,
            at: datetime) -> bool:
    """받은 통화의 끝: completed · 길이 · 받아쓰기 전부 · 사용량(초 — 토큰·요금은 백엔드가 알려 줄 때만, 지금은 없음).
    completed 로 옮겼으면 True(이미 끝난 줄이면 False — 아무것도 바꾸지 않음)."""
    with _db() as session:
        done = session.execute(
            update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(_LIVE))
            .values(status="completed", duration_s=seconds, ended_at=at, transcript_json=lines, fail_reason=note)
            .execution_options(synchronize_session=False))
        moved = done.rowcount == 1
        if moved:
            if by_person:
                events.record(session, Ref("call", call_id), "hangup_by_person", "noted", "사람이 화면에서 끊었습니다", now=at)
            outreach.add_usage(session, "voice_model", ref=("call", call_id), model=model, seconds=seconds)
        session.commit()
        return moved


def _unanswered(call_id: int, code: str, at: datetime) -> None:
    with _db() as session:
        done = session.execute(
            update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(_LIVE))
            .values(status=code, fail_reason=FAILED_TEXT[code], ended_at=at).execution_options(synchronize_session=False))
        if done.rowcount == 1:
            events.record(session, Ref("call", call_id), "call_result", "noted", code, now=at)
        session.commit()


def _unsure(session, call_id: int, at: datetime) -> None:
    """결과를 모르는 통화(걸렸을 수 있음)를 나가는 문이 아는 꼴로 — delivery · unsure. 문은 이것으로 그 번호의 다음 전화를
    DUPLICATE_WINDOW_S 동안 막는다(gate._closed_unsure)."""
    events.record(session, Ref("call", call_id), "delivery", DELIVERY_VERDICT["unsure"], gate.UNSURE, now=at)


def _broken(call_id: int, why: str, lines: list[dict], seconds: int | None, at: datetime, detail: str = "backend_error",
            unsure: bool = False) -> None:
    """받지 못했거나 끝을 모르는 통화를 failed 로(call_result blocked detail). unsure 면 문이 다시 걸기를 막게 delivery · unsure."""
    with _db() as session:
        done = session.execute(
            update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(_LIVE))
            .values(status="failed", fail_reason=why, ended_at=at, duration_s=seconds, transcript_json=lines)
            .execution_options(synchronize_session=False))
        if done.rowcount == 1:
            events.record(session, Ref("call", call_id), "call_result", "blocked", detail, now=at)
            if unsure:
                _unsure(session, call_id, at)
        session.commit()


def _close(call_id: int, states: tuple[str, ...], status: str, why: str, at: datetime) -> int:
    """서버가 다시 뜸·일꾼이 멈춤: 그 상태일 때만 옮기고 server_restart. 옮긴 줄 수(0·1)."""
    with _db() as session:
        closing = update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status.in_(states))
        if status == "failed":
            closing = closing.values(status=status, fail_reason=why, ended_at=at)
        else:  # 줄에서 기다리던 것 — 건 적이 없으니 그날 셈에서 뺀다
            closing = closing.values(status=status, fail_reason=why, claimed_at=None)
        if session.execute(closing.execution_options(synchronize_session=False)).rowcount != 1:
            return 0
        events.record(session, Ref("call", call_id), "server_restart", "noted", why, now=at)
        if status == "failed":  # 걸던 중·통화 중에 끊김 — 아직 울리고 있을 수 있다
            _unsure(session, call_id, at)
        session.commit()
        return 1
