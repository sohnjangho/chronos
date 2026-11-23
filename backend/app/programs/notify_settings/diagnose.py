"""연결 진단 길(계획 4 Task 70) — Task 59 의 `diagnostics.run_checks` 를 저장된 키로 부른다.

- 실제 문자는 `send` 가 참일 때만, 받는 번호는 첫 허용 번호뿐(휴대전화여야 하고 발신번호가 있어야 한다).
- 연결마다 한 번에 하나(`_RUNNING`) — 표시는 끝·실패·끊김 모두에서 지운다.
- 부르는 동안 DB 트랜잭션을 쥐지 않는다(부르기 전에 commit, 끝난 뒤 줄을 다시 읽어 결과만 적는다).
- 전체 상한 DIAGNOSE_CEILING_S(진단 모듈의 요청마다 제한 위에 한 번 더). 넘으면 고른 단계를 「timeout」으로 돌려주고,
  문자를 보내던 중이었으면 「보냈는지 알 수 없음」(sent_unknown) — 다시 보내 보지 않는다.
- 결과 글은 한 번 더 지워(키·Account ID·발신·받는 번호·번호 꼴) `last_diagnosis_json` 에 저장한다.
"""

import asyncio
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.notify import diagnostics
from app.outreach import phone, provider, redact
from app.programs.notify_settings import service
from app.programs.notify_settings.schemas import DiagnoseIn, DiagnosisOut, StepOut
from app.store.tables_outreach import NotifyConnection

DIAGNOSE_CEILING_S = 150.0  # P1 15 + P2 15 + P3 4×(15+5) + P4 15 + 이름 풀이 5 ≈ 130초 위에 여유
ALL_STEPS = ("P1", "P2", "P3", "P4")
STOPPED = "timeout · 전체 시간({s:g}초)을 넘겨 멈췄습니다"
_RUNNING: set[int] = set()  # 진단이 도는 연결 id(이 프로세스)


def _test_number(conn: NotifyConnection) -> str:
    allow = list(conn.allow_numbers_json or [])
    if not allow:
        raise ApiError(422, "no_allow_numbers", "허용 번호를 먼저 넣어 주세요")
    if not phone.can_sms(allow[0]):
        raise ApiError(422, "test_number_not_mobile", "첫 허용 번호가 휴대전화가 아니라 시험 문자를 받을 수 없습니다.")
    if not conn.sender_number:
        raise ApiError(422, "no_sender", "발신번호를 먼저 골라 주세요.")
    return allow[0]


def _stopped(step_id: str, send: bool) -> diagnostics.DiagnosticStep:
    detail = f"timeout · {diagnostics.MAYBE_SENT}" if step_id == "P2" and send else STOPPED.format(s=DIAGNOSE_CEILING_S)
    return diagnostics.DiagnosticStep(id=step_id, label=diagnostics.LABELS[step_id], ok=False, detail=detail)


async def _checks(conn: diagnostics.DiagnosticConn, wanted: list[str], send: bool) -> tuple[list, bool]:
    """(걸음들, 상한에 걸렸는가)."""
    async with diagnostics.make_client() as http:
        try:
            async with asyncio.timeout(DIAGNOSE_CEILING_S):
                return await diagnostics.run_checks(conn, http, send_test_sms=send, steps=wanted), False
        except TimeoutError:
            return [_stopped(step, send) for step in wanted], True


def _result(ran_at: datetime, found: list, send: bool, stopped: bool, secrets: list[str]) -> DiagnosisOut:
    def clean(text: object) -> str:
        return redact.scrub(str(text), secrets)

    steps = [StepOut(id=str(s.id), label=clean(s.label), ok=s.ok is True, skipped=s.skipped is True,
                     detail=clean(s.detail), latency_ms=s.latency_ms if isinstance(s.latency_ms, int) else None,
                     notes=[clean(n) for n in (s.notes or [])]) for s in found]
    p2 = next((s for s in found if s.id == "P2"), None)
    sent_real = send and p2 is not None and p2.ok is True
    sent_unknown = (send and p2 is not None and p2.ok is not True and not p2.skipped
                    and (stopped or diagnostics.MAYBE_SENT in str(p2.detail)))
    return DiagnosisOut(ran_at=ran_at, steps=steps, sent_real=sent_real, sent_unknown=sent_unknown)


async def run(session: Session, conn_id: int, data: DiagnoseIn) -> DiagnosisOut:
    conn = service.get(session, conn_id)
    wanted = sorted(set(data.steps or ALL_STEPS))
    send = data.send is True
    test_to = _test_number(conn) if send else ""
    key = service.stored_key(conn)
    target = diagnostics.DiagnosticConn(base_url=conn.base_url, key=key, account_id=conn.account_id,
                                        sender=conn.sender_number or "", test_to=test_to)
    if conn_id in _RUNNING:
        raise ApiError(409, "diagnosis_running", "이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요.")
    _RUNNING.add(conn_id)
    try:
        provider.register_secrets(key, target.account_id)
        session.commit()  # 트랜잭션을 놓고 부른다
        ran_at = datetime.now(UTC)
        found, stopped = await _checks(target, wanted, send)
    finally:
        _RUNNING.discard(conn_id)
    result = _result(ran_at, found, send, stopped, [key, target.account_id, target.sender, target.test_to])
    conn = service.get(session, conn_id)  # 다시 읽어 결과 칸만 적는다
    conn.last_diagnosis_json = {"ran_at": ran_at.isoformat(), "steps": [s.model_dump() for s in result.steps],
                                "real": result.sent_real, "sent_unknown": result.sent_unknown}
    session.commit()
    return result


def last(session: Session, conn_id: int) -> DiagnosisOut | None:
    stored = service.get(session, conn_id).last_diagnosis_json
    if not isinstance(stored, dict):
        return None
    try:
        return DiagnosisOut(ran_at=stored["ran_at"], steps=stored["steps"], sent_real=stored.get("real") is True,
                            sent_unknown=stored.get("sent_unknown") is True)
    except (KeyError, TypeError, ValidationError):
        return None
