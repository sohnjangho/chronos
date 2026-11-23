"""연결 진단 길(계획 4 Task 70) — Task 59 의 `diagnostics.run_checks` 를 저장된 키로 부른다. 계약: task-70-contract.md.

- 실제 문자는 `send` 가 참일 때만, 받는 번호는 첫 허용 번호뿐이다.
  - 휴대전화여야 하고, 발신번호가 있어야 하고, 확인한 목록 판(`allow_numbers_version`)이 지금 목록과 같아야 한다.
- 보내기 전에 `last_diagnosis_json` 에 「보내는 중」 기록(state "sending")과 시험 문자 기록(`sends`, 최근 20개, 번호 없음)을
  남기고, 끝나면 결과로 바꾼다.
  - 끝나지 못한 채 남은 기록은 상한이 지나면 「보냈는지 모름」으로 읽힌다.
  - 마지막 시험 문자가 「보내는 중」·「모름」이고 10분이 안 됐으면, `confirm_resend` 없이는 다시 보내지 않는다.
- 연결마다 한 번에 하나(`_RUNNING`) — 표시는 끝·실패·끊김 모두에서 지운다.
- DB 일은 스레드에서 하고(이벤트 루프를 막지 않게), 부르는 동안 트랜잭션을 쥐지 않는다. 기록은 쓰기 트랜잭션 하나로 쓴다.
- 걸음은 덩어리(P1 · P2+P3 · P4)마다 `run_checks` 를 불러 요청 상한(Calls)을 함께 쓴다 — 전체 상한(DIAGNOSE_CEILING_S)에
  걸려도 끝난 걸음은 실제 결과를 남기기 위해서다. P2 요청이 나간 뒤 끊겼으면 「보냈는지 모름」이고, 다시 보내 보지 않는다.
- 결과 글은 한 번 더 지운다(키·Account ID·발신·받는 번호·번호 꼴).
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.errors import ApiError
from app.notify import diagnostics
from app.outreach import phone, provider, redact
from app.programs.notify_settings import service
from app.programs.notify_settings.schemas import (
    DiagnoseIn,
    DiagnosisOut,
    SendRecord,
    StepOut,
)
from app.store.tables_outreach import NotifyConnection

DIAGNOSE_CEILING_S = 150.0  # P1 15 + P2 15 + P3 4×(15+5) + P4 15 + 이름 풀이 5×3 ≈ 140초 위에 여유
RESEND_WINDOW = timedelta(minutes=10)
SENDS_KEPT = 20
ALL_STEPS = ("P1", "P2", "P3", "P4")
CHUNKS = (("P1",), ("P2", "P3"), ("P4",))  # P3 은 P2 가 받은 messageId 를 쓴다 — 한 덩어리
STOPPED = "전체 시간({s:g}초)을 넘겨 멈췄습니다"
NOT_FINISHED = "보냈는지 알 수 없음 — 요청이 끝나지 않은 채 남았습니다. 휴대전화에 문자가 왔는지 확인해 주세요."
RESEND = ("앞서 보낸 시험 문자가 갔는지 아직 모릅니다. 휴대전화에 문자가 왔는지 먼저 확인해 주세요. "
          "확인한 뒤에도 다시 보내려면 다시 보내기를 골라 주세요.")
_RUNNING: set[int] = set()  # 진단이 도는 연결 id(이 프로세스)


@dataclass(frozen=True)
class _Prep:
    target: diagnostics.DiagnosticConn
    wanted: list[str]
    send: bool


# ── 보내기 전 검사·기록 ──────────────────────────────────────────────


def _test_number(conn: NotifyConnection, data: DiagnoseIn) -> str:
    allow = list(conn.allow_numbers_json or [])
    if not allow:
        raise ApiError(422, "no_allow_numbers", "허용 번호를 먼저 넣어 주세요")
    service.check_allow_version(conn, data.allow_numbers_version,
                                "시험 문자를 보내려면 허용 번호 목록 판(allow_numbers_version)을 함께 보내 주세요.")
    if not phone.can_sms(allow[0]):
        raise ApiError(422, "test_number_not_mobile", "첫 허용 번호가 휴대전화가 아니라 시험 문자를 받을 수 없습니다.")
    if not conn.sender_number:
        raise ApiError(422, "no_sender", "발신번호를 먼저 골라 주세요.")
    return allow[0]


def _prepare_sync(session: Session, conn_id: int, data: DiagnoseIn) -> _Prep:
    conn = service.get(session, conn_id)
    send = data.send is True
    test_to = _test_number(conn, data) if send else ""
    key = service.stored_key(conn)
    target = diagnostics.DiagnosticConn(base_url=conn.base_url, key=key, account_id=conn.account_id,
                                        sender=conn.sender_number or "", test_to=test_to)
    session.rollback()  # 트랜잭션을 끝내고 부른다
    return _Prep(target=target, wanted=sorted(set(data.steps or ALL_STEPS)), send=send)


def _when(value: object) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _sends(stored: object) -> list[dict]:
    rows = stored.get("sends") if isinstance(stored, dict) else None
    return [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _open_send(sends: list[dict], now: datetime) -> bool:
    """마지막 시험 문자의 결과를 모르고(보내는 중·모름) 10분이 안 됐는가."""
    if not sends or sends[-1].get("outcome") not in ("sending", "unknown"):
        return False
    at = _when(sends[-1].get("at"))
    return at is None or now - at < RESEND_WINDOW


def _mark_sending_sync(session: Session, conn_id: int, data: DiagnoseIn, by: str, now: datetime) -> None:
    """쓰기 트랜잭션 하나: 목록 판·앞선 문자 결과를 다시 보고 「보내는 중」 기록을 남긴다."""
    service.begin_write(session)
    try:
        conn = service.get(session, conn_id, fresh=True)
        _test_number(conn, data)
        sends = _sends(conn.last_diagnosis_json)
        if not data.confirm_resend and _open_send(sends, now):
            raise ApiError(409, "sent_unknown_pending", RESEND)
    except ApiError:
        session.rollback()
        raise
    sends = (sends + [{"at": now.isoformat(), "by": by, "outcome": "sending"}])[-SENDS_KEPT:]
    conn.last_diagnosis_json = {"state": "sending", "ran_at": now.isoformat(), "by": by, "steps": [], "real": False,
                                "sent_unknown": False, "sends": sends}
    session.commit()


# ── 걸음 돌리기 ─────────────────────────────────────────────────────


async def _checks(prep: _Prep) -> tuple[dict, bool, bool]:
    """({걸음 id: 결과}, 상한에 걸렸는가, 끝나지 못한 P2 의 요청이 나갔는가)."""
    rows: dict[str, diagnostics.DiagnosticStep] = {}
    calls = diagnostics.Calls()
    stopped = False
    async with diagnostics.make_client() as http:
        try:
            async with asyncio.timeout(DIAGNOSE_CEILING_S):
                for chunk in CHUNKS:
                    ids = [s for s in chunk if s in prep.wanted]
                    if not ids:
                        continue
                    found = await diagnostics.run_checks(prep.target, http, send_test_sms=prep.send, steps=ids,
                                                         calls=calls)
                    rows.update({s.id: s for s in found if s.id in ids})
        except TimeoutError:
            stopped = True
    posted = stopped and prep.send and "P2" not in rows and calls.maybe_sent  # 끊긴 P2 의 요청 본문이 나갔는가
    return rows, stopped, posted


def _line(step_id: str, *, ok: bool = False, skipped: bool = False, detail: str, code: str,
          maybe_sent: bool = False) -> StepOut:
    return StepOut(id=step_id, label=diagnostics.LABELS[step_id], ok=ok, skipped=skipped, detail=detail,
                   latency_ms=None, notes=[], code=code, maybe_sent=maybe_sent, pending=False)


def _result(prep: _Prep, rows: dict, stopped: bool, posted: bool, ran_at: datetime, by: str,
            sends: list[dict]) -> DiagnosisOut:
    secrets = [prep.target.key, prep.target.account_id, prep.target.sender, prep.target.test_to]

    def clean(value: object) -> str:
        return redact.scrub(str(value), secrets)

    steps: list[StepOut] = []
    for step_id in ALL_STEPS:
        step = rows.get(step_id)
        if step is not None:
            steps.append(StepOut(
                id=step_id, label=diagnostics.LABELS[step_id], ok=step.ok is True, skipped=step.skipped is True,
                detail=clean(step.detail), latency_ms=step.latency_ms if isinstance(step.latency_ms, int) else None,
                notes=[clean(n) for n in (step.notes or [])], code=clean(step.code),
                maybe_sent=step.maybe_sent is True and step_id == "P2" and prep.send, pending=step.pending is True))
        elif step_id not in prep.wanted:
            steps.append(_line(step_id, skipped=True, detail=diagnostics.NOT_REQUESTED, code="skipped_not_requested"))
        elif step_id == "P2" and posted:
            steps.append(_line(step_id, detail=f"{STOPPED.format(s=DIAGNOSE_CEILING_S)} · {diagnostics.MAYBE_SENT}",
                               code="timeout", maybe_sent=True))
        else:
            steps.append(_line(step_id, detail=STOPPED.format(s=DIAGNOSE_CEILING_S), code="timeout"))
    p2 = steps[1]
    sent_real = prep.send and p2.ok
    sent_unknown = prep.send and not p2.ok and p2.maybe_sent
    return DiagnosisOut(state="done", ran_at=ran_at, by=by, steps=steps, sent_real=sent_real,
                        sent_unknown=sent_unknown, sends=_records(sends, ran_at))


def _save_sync(session: Session, conn_id: int, result: DiagnosisOut, send: bool) -> DiagnosisOut:
    """결과로 바꾼다(쓰기 트랜잭션 하나). 시험 문자 기록은 이어 쓰고, 이번 것은 결과로 고친다."""
    service.begin_write(session)
    conn = session.get(NotifyConnection, conn_id, populate_existing=True)
    if conn is None:  # 그사이 지워졌다
        session.rollback()
        return result
    sends = _sends(conn.last_diagnosis_json)
    if send:
        stamp = result.ran_at.isoformat()
        outcome = "accepted" if result.sent_real else "unknown" if result.sent_unknown else "not_sent"
        for record in sends:
            if record.get("at") == stamp:
                record["outcome"] = outcome
    conn.last_diagnosis_json = {"state": "done", "ran_at": result.ran_at.isoformat(), "by": result.by,
                                "steps": [s.model_dump() for s in result.steps], "real": result.sent_real,
                                "sent_unknown": result.sent_unknown, "sends": sends}
    session.commit()
    return result.model_copy(update={"sends": _records(sends, datetime.now(UTC))})


async def run(session: Session, conn_id: int, data: DiagnoseIn, by: str) -> DiagnosisOut:
    prep = await run_in_threadpool(_prepare_sync, session, conn_id, data)
    if conn_id in _RUNNING:
        raise ApiError(409, "diagnosis_running", "이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요.")
    _RUNNING.add(conn_id)
    try:
        ran_at = datetime.now(UTC)
        if prep.send:
            await run_in_threadpool(_mark_sending_sync, session, conn_id, data, by, ran_at)
        provider.register_secrets(prep.target.key, prep.target.account_id)
        rows, stopped, posted = await _checks(prep)
        result = _result(prep, rows, stopped, posted, ran_at, by, [])
        return await run_in_threadpool(_save_sync, session, conn_id, result, prep.send)
    finally:
        _RUNNING.discard(conn_id)


# ── 읽기 ────────────────────────────────────────────────────────────


def _records(sends: list[dict], now: datetime) -> list[SendRecord]:
    """시험 문자 기록. 상한보다 오래 「보내는 중」으로 남은 것은 「모름」으로 읽는다."""
    out = []
    for record in sends:
        at = _when(record.get("at"))
        if at is None:
            continue
        outcome = record.get("outcome")
        if outcome == "sending" and now - at > timedelta(seconds=DIAGNOSE_CEILING_S):
            outcome = "unknown"
        try:
            out.append(SendRecord(at=at, by=str(record.get("by") or ""), outcome=outcome))
        except ValidationError:
            continue
    return out


def last(session: Session, conn_id: int) -> DiagnosisOut | None:
    stored = service.get(session, conn_id).last_diagnosis_json
    if not isinstance(stored, dict):
        return None
    now = datetime.now(UTC)
    ran_at = _when(stored.get("ran_at"))
    if ran_at is None:
        return None
    sends = _records(_sends(stored), now)
    by = stored.get("by") if isinstance(stored.get("by"), str) else None
    if stored.get("state") == "sending":
        if now - ran_at <= timedelta(seconds=DIAGNOSE_CEILING_S):
            return DiagnosisOut(state="sending", ran_at=ran_at, by=by, steps=[], sent_real=False, sent_unknown=False,
                                sends=sends)
        steps = [_line(s, skipped=True, detail=NOT_FINISHED if s == "P2" else "끝나지 않음", code="not_finished")
                 for s in ALL_STEPS]
        steps[1] = _line("P2", detail=NOT_FINISHED, code="not_finished", maybe_sent=True)
        return DiagnosisOut(state="done", ran_at=ran_at, by=by, steps=steps, sent_real=False, sent_unknown=True,
                            sends=sends)
    try:
        return DiagnosisOut(state="done", ran_at=ran_at, by=by, steps=stored.get("steps") or [],
                            sent_real=stored.get("real") is True, sent_unknown=stored.get("sent_unknown") is True,
                            sends=sends)
    except ValidationError:
        return None
