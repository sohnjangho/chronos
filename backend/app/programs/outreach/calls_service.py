"""통화 API(계획 4 Task 91): 한 사람과의 통화 읽기, 초안 쓰기·고치기·지우기, 걸기·예약·취소, 끊기, 다시 걸기, 결과 확정, 녹음.

- **걸기는 나가는 문 하나**: 이 모듈은 통로를 부르지 않는다. 읽기 트랜잭션을 닫은 뒤 `gate.dispatch("call", id, actor)` 를
  부르고, 문이 준 판정(code·message·scheduled_at)을 그대로 돌려준다 — 막힌 것도 결과라 늘 200. `unsure`(「보냈는지 확인 필요」)는
  오류가 아니고, 문의 `duplicate`(차지하지 못함 — 「잠시 뒤 다시 해 보세요」)도 그대로다. 근무시간 밖이면 문이 `blocked_hours` 와
  다음 근무 시작을 준다(전화는 걸지 않는다) — 사람이 그 시각이나 다른 시각을 골라 `schedule` 한다.
- **격리**[리뷰 판정 7]: 문은 일정 id 를 받지 않으므로 줄을 건드리는 길은 모두 먼저 `store.outreach.get_call(일정, id)` 로 그 일정의
  줄인지 본다(아니면 404, 문·일꾼을 부르지 않음). 본문의 연락처·작업도 그 일정 것이어야 한다.
- **Actor 는 로그인한 사람에게서만**: `Actor("user", user.id, user.name, user.role)`.
- **다시 걸기는 새 줄**[리뷰 판정 14]: 받지 않음·통화 중·실패로 끝난 줄은 다시 걸 수 없고(409), `redial` 이 같은 내용의 새 초안
  (`retry_of`)을 만든다. 걸지는 않는다.
- **예약**: 사람이 고른 시각이 그 사람의 근무시간 안이어야 한다(여기서 422). 예약은 `gate.schedule` 이 사람의 결정(자기 초안
  manual, 에이전트 초안 approved + 누른 사람)을 적는다 — **send_mode 는 문만 적는다**. 때가 되면 일꾼이 그 방식으로 문을 처음부터
  다시 지난다. 취소는 초안으로 돌리며 시각·방식·승인한 사람을 비운다. **PATCH 는 승인이 아니다**(approved_by 를 적지 않는다).
- 상태를 바꾸는 쓰기는 `UPDATE/DELETE … WHERE status …` 한 문장 — 그 사이 문이나 일꾼이 줄을 가져갔으면 아무것도 바꾸지 않고 409.
- 번호: 응답에 번호 칸이 없다. 받아쓰기·답·사건·보고·요약·제안된 결과는 hide_phones 를 거친다. 오류 글에 받은 값을 싣지 않는다.
- 녹음: 그 일정의 녹음 폴더(`<data_dir>/recordings/<일정 id>/`) 안에 있는 파일만, 이름은 `call-<id>.<확장자>`. 없으면 「통화를 찾을
  수 없습니다」와 같은 404.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.outreach import hours
from app.outreach.harness import gate
from app.outreach.harness.types import Actor
from app.outreach.redact import hide_phones
from app.programs.outreach import service
from app.programs.outreach.calls_schemas import (
    AnswerOut,
    CallContact,
    CallDetail,
    CallEventOut,
    CallIn,
    CallOut,
    CallPatch,
    CallResult,
    ConfirmIn,
    ReportOut,
    ScheduleIn,
    TranscriptLine,
)
from app.programs.outreach.schemas import ActivityOut, OutcomeOut
from app.store import contacts, outreach
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    OutreachCall,
)
from app.store.timeutil import as_utc

CALL_NOT_FOUND = "통화를 찾을 수 없습니다."
BAD_TEXT = "통화 내용에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다."
USE_REDIAL = "이미 끝난 통화입니다. 다시 걸려면 [다시 걸기]를 눌러 주세요."
DONE = "이미 처리된 통화입니다."
NOT_SCHEDULABLE = "초안이거나 근무시간 밖이라 멈춘 통화만 예약할 수 있습니다."
OUTSIDE_HOURS = "근무시간 안의 시각을 골라 주세요"
PAST_TIME = "지난 시각은 고를 수 없습니다"
NOT_SCHEDULED = "예약된 통화가 아닙니다."
NOT_LIVE = "진행 중인 통화가 아닙니다."
RUNNER_NOT_READY = "통화 일꾼이 아직 준비되지 않았습니다."
NOT_REDIALABLE = "받지 않았거나 통화 중이었거나 실패한 통화만 다시 걸 수 있습니다."
NOT_COMPLETED = "통화가 끝난 뒤에만 결과를 확정할 수 있습니다."
PLACEABLE = ("draft", "scheduled", "blocked_hours", *outreach.LIVE_CALL)  # 문에 넘기는 상태(나가는 중이면 문이 「잠시 뒤 다시」)
REDIALABLE = ("no_answer", "busy", "failed")
SCHEDULABLE = ("draft", "blocked_hours", "scheduled")
_BAD_HOURS = (KeyError, TypeError, ValueError, AttributeError)  # 저장된 근무시간이 틀린 꼴(NoWorkingTime 은 ValueError)
_AUDIO = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".webm": "audio/webm", ".m4a": "audio/mp4"}


def _now() -> datetime:
    return datetime.now(UTC)


def _runner():
    """통화 일꾼(Task 88 `app.outreach.voice.runner`). 부를 때 불러온다 — 아직 없으면 503, 시험은 이 함수를 바꿔 가짜를 끼운다."""
    try:
        from app.outreach.voice import runner
    except ImportError:
        raise ApiError(503, "not_ready", RUNNER_NOT_READY) from None
    return runner


def _actor(user: User) -> Actor:
    """누른 사람. 요청의 값이 아니라 로그인한 세션의 사용자에게서만 만든다."""
    return Actor("user", user.id, user.name, user.role)


# ── 찾기·검사 ────────────────────────────────────────────────────────────────


def _call(session: Session, schedule_id: int, call_id: int) -> OutreachCall:
    try:
        return outreach.get_call(session, schedule_id, call_id)
    except outreach.NotFound:
        raise ApiError(404, "not_found", CALL_NOT_FOUND) from None


def _contact(session: Session, schedule_id: int, contact_id: int) -> Contact:
    try:
        return contacts.get_contact(session, schedule_id, contact_id)
    except contacts.NotFound:
        raise ApiError(404, "not_found", service.PERSON_NOT_FOUND) from None


def _check_text(field: str, *texts: str | None) -> None:
    """음성 에이전트에게 갈 글(목적·물어볼 것·말하지 않을 것)과 확정 결과에 보이지 않는 글자가 있으면 422. 값은 싣지 않는다."""
    if any(text and any(service._bad_char(char) for char in text) for text in texts):
        raise ApiError(422, "invalid_text", BAD_TEXT, detail={"field": field})


def _check_draft(session: Session, schedule_id: int, body: CallIn | CallPatch) -> None:
    sent = body.model_fields_set
    for field in ("purpose", "questions", "avoid"):
        value = getattr(body, field) if field in sent or isinstance(body, CallIn) else None
        _check_text(field, *([value] if isinstance(value, str) else value or []))
    if body.activity_id is not None:
        service._check_links(session, schedule_id, activity_id=body.activity_id)


def purpose_key(purpose: str) -> str:
    """같은 목적의 통화를 묶는 손잡이 — 빈칸을 고르고 대소문자를 접은 목적 글의 해시. 문이 같은 번호·같은 손잡이의 통화를
    짧은 시간 안에 또 걸지 않는다[리뷰 판정 8]."""
    return hashlib.sha256(" ".join(purpose.split()).casefold().encode()).hexdigest()


def recording_file(row: OutreachCall) -> Path | None:
    """그 줄의 녹음 파일 — 그 일정의 녹음 폴더 안에 실제로 있을 때만(밖을 가리키거나 없으면 None)."""
    if not row.recording_path or row.schedule_id is None:
        return None
    root = (Settings().data_dir / "recordings" / str(row.schedule_id)).resolve()
    try:
        path = Path(row.recording_path).resolve()
    except (OSError, ValueError):
        return None
    return path if path.is_relative_to(root) and path.is_file() else None


def audio_type(path: Path) -> str:
    return _AUDIO.get(path.suffix.lower(), "application/octet-stream")


# ── 응답 만들기 ──────────────────────────────────────────────────────────────


def _text(value: object) -> str:
    return hide_phones(value) if isinstance(value, str) else ""


def _answers(log: object) -> list[AnswerOut]:
    if not isinstance(log, list):
        return []
    return [AnswerOut(question=_text(a.get("question")), answer=_text(a.get("answer")), quote=_text(a.get("quote")),
                      quote_found=a.get("quote_found") is True) for a in log if isinstance(a, dict)]


def _events(log: object) -> list[CallEventOut]:
    """하네스 사건(harness_json — 남길 때 이미 번호·비밀을 지웠다). detail 은 한 번 더 가린다."""
    if not isinstance(log, list):
        return []
    return [CallEventOut(rule=str(e.get("rule")), verdict=str(e.get("verdict")),
                         detail=hide_phones(e["detail"]) if isinstance(e.get("detail"), str) else None,
                         at=e.get("at") if isinstance(e.get("at"), str) else None)
            for e in log if isinstance(e, dict)]


def _lines(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else as_utc(value)


def _out(session: Session, schedule_id: int, rows: list[OutreachCall]) -> list[CallOut]:
    """통화 줄들 → CallOut. 작업 이름·연락처·협력사는 한 번에 읽는다."""
    names = service._activity_names(session, schedule_id) if any(r.activity_id for r in rows) else {}
    people_ids = {r.contact_id for r in rows if r.contact_id is not None}
    people = {c.id: c for c in session.scalars(select(Contact).where(
        Contact.id.in_(people_ids), Contact.schedule_id == schedule_id))} if people_ids else {}
    company_ids = {c.company_id for c in people.values()}
    companies = {c.id: c.name for c in session.scalars(select(ContactCompany).where(
        ContactCompany.id.in_(company_ids)))} if company_ids else {}
    out = []
    for row in rows:
        who = people.get(row.contact_id) if row.contact_id is not None else None
        out.append(CallOut(
            id=row.id, direction=row.direction, caller_class=row.caller_class,
            contact=None if who is None else CallContact(id=who.id, name=who.name, role_title=who.role_title,
                                                         company=companies.get(who.company_id, "")),
            origin=row.origin, origin_name=row.origin_name, send_mode=row.send_mode, approved_by=row.approved_by,
            status=row.status, fail_reason=row.fail_reason, purpose=row.purpose, questions=_lines(row.questions_json),
            avoid=_lines(row.avoid_json), language=row.language, voice_id=row.voice_id, duration_s=row.duration_s,
            summary_ko=_text(row.summary_ko), result_proposed=_text(row.result_proposed),
            result_confirmed=row.result_confirmed, confirmed_by=row.confirmed_by, answers=_answers(row.answers_json),
            events=_events(row.harness_json), has_recording=recording_file(row) is not None,
            prev_call_id=row.prev_call_id,
            activity=ActivityOut(id=row.activity_id, name=names.get(row.activity_id)) if row.activity_id else None,
            scheduled_at=_utc(row.scheduled_at), started_at=_utc(row.started_at), ended_at=_utc(row.ended_at),
            created_at=as_utc(row.created_at),
        ))
    return out


def _one(session: Session, schedule_id: int, row: OutreachCall) -> CallOut:
    session.refresh(row)
    return _out(session, schedule_id, [row])[0]


def _transcript(log: object) -> list[TranscriptLine]:
    if not isinstance(log, list):
        return []
    return [TranscriptLine(role=str(line.get("role")), text=_text(line.get("text")),
                           t=line.get("t") if isinstance(line.get("t"), int | float) else None)
            for line in log if isinstance(line, dict)]


# ── 길 ───────────────────────────────────────────────────────────────────────


def listed(session: Session, schedule_id: int, contact_id: int | None) -> list[CallOut]:
    """그 일정의 통화(contact_id 를 주면 그 사람 것만), 최근 것부터."""
    query = select(OutreachCall).where(OutreachCall.schedule_id == schedule_id)
    if contact_id is not None:
        _contact(session, schedule_id, contact_id)
        query = query.where(OutreachCall.contact_id == contact_id)
    rows = list(session.scalars(query.order_by(OutreachCall.id.desc())))
    return _out(session, schedule_id, rows)


def detail(session: Session, schedule_id: int, call_id: int) -> CallDetail:
    """한 통화 + 받아쓰기·이 통화에서 받은 보고(번호는 가린 꼴)."""
    row = _call(session, schedule_id, call_id)
    reports = session.scalars(select(ContactReport).where(
        ContactReport.schedule_id == schedule_id, ContactReport.call_id == row.id).order_by(ContactReport.id))
    return CallDetail(
        **_out(session, schedule_id, [row])[0].model_dump(),
        transcript=_transcript(row.transcript_json),
        reports=[ReportOut(id=r.id, kind=r.kind, text=_text(r.text), quote=_text(r.quote), quote_found=r.quote_found,
                           status=r.status, reviewed_by=r.reviewed_by, created_at=as_utc(r.created_at)) for r in reports],
    )


def create(session: Session, schedule_id: int, body: CallIn, user: User) -> CallOut:
    """초안(origin user). 언어를 주지 않으면 그 사람의 언어. 걸지 않는다."""
    who = _contact(session, schedule_id, body.contact_id)
    _check_draft(session, schedule_id, body)
    row = OutreachCall(
        schedule_id=schedule_id, contact_id=who.id, direction="out", purpose=body.purpose,
        questions_json=list(body.questions), avoid_json=list(body.avoid), language=body.language or who.language,
        voice_id=body.voice_id, purpose_key=purpose_key(body.purpose), origin="user", origin_name=user.name,
        status="draft", activity_id=body.activity_id,
    )
    session.add(row)
    session.commit()
    return _one(session, schedule_id, row)


def patch(session: Session, schedule_id: int, call_id: int, body: CallPatch) -> CallOut:
    """초안만: 보낸 칸만 바꾼다(목적을 바꾸면 손잡이도). 승인이 아니다 — 방식·승인한 사람은 그대로."""
    row = _call(session, schedule_id, call_id)
    _check_draft(session, schedule_id, body)
    sent = body.model_fields_set
    changed = session.execute(update(OutreachCall).where(
        OutreachCall.id == row.id, OutreachCall.status == "draft",
    ).values(
        purpose=body.purpose if "purpose" in sent else row.purpose,
        purpose_key=purpose_key(body.purpose) if "purpose" in sent else row.purpose_key,
        questions_json=list(body.questions) if "questions" in sent else row.questions_json,
        avoid_json=list(body.avoid) if "avoid" in sent else row.avoid_json,
        activity_id=body.activity_id if "activity_id" in sent else row.activity_id,
        language=body.language if "language" in sent else row.language,
        voice_id=body.voice_id if "voice_id" in sent else row.voice_id,
    )).rowcount
    if changed != 1:
        session.rollback()
        raise ApiError(409, "not_draft", service.NOT_DRAFT)
    session.commit()
    return _one(session, schedule_id, row)


def remove(session: Session, schedule_id: int, call_id: int) -> None:
    """초안만 지운다. 그 밖은 409 not_draft."""
    row = _call(session, schedule_id, call_id)
    gone = session.execute(delete(OutreachCall).where(
        OutreachCall.id == row.id, OutreachCall.status == "draft")).rowcount
    if gone != 1:
        session.rollback()
        raise ApiError(409, "not_draft", service.NOT_DRAFT)
    session.commit()


async def place(session: Session, schedule_id: int, call_id: int, user: User) -> CallResult:
    """그 줄을 나가는 문에 넣는다 → {call, outcome}. 끝난 줄은 409 not_sendable(받지 않음·통화 중·실패는 [다시 걸기]로 새 줄)."""
    row = _call(session, schedule_id, call_id)
    if row.direction != "out" or row.status not in PLACEABLE:
        raise ApiError(409, "not_sendable", USE_REDIAL if row.status in REDIALABLE else DONE)
    session.commit()  # 읽기 트랜잭션을 닫는다 — 문은 자기 연결로 쓰기 잠금을 잡는다
    outcome = await gate.dispatch("call", row.id, _actor(user), now=_now())
    session.expire_all()
    return CallResult(call=_one(session, schedule_id, row),
                      outcome=OutcomeOut(code=outcome.code, message=outcome.message, scheduled_at=outcome.scheduled_at))


def schedule(session: Session, schedule_id: int, call_id: int, body: ScheduleIn, user: User) -> CallOut:
    """초안·근무시간 밖으로 멈춘 줄(또는 예약을 다른 시각으로)을 그 시각에 예약한다. 시각은 앞날이고 그 사람의 근무시간 안이어야
    한다(422). 예약은 문(gate.schedule)을 지나 사람의 결정(방식·승인한 사람)을 적는다 — 이 모듈은 send_mode 를 적지 않는다.
    문이 예약하지 않으면(그 사이 일꾼이 가져감·DB 가 바쁨 …) 409 not_schedulable, 글은 문의 것."""
    row = _call(session, schedule_id, call_id)
    if row.direction != "out" or row.status not in SCHEDULABLE:
        raise ApiError(409, "not_schedulable", NOT_SCHEDULABLE)
    if body.at <= _now():
        raise ApiError(422, "past_time", PAST_TIME)
    who = session.get(Contact, row.contact_id) if row.contact_id is not None else None
    try:
        working = hours.is_working(who.hours_json if who is not None else None,
                                   contacts.calendar_of(session, schedule_id), body.at)
    except _BAD_HOURS:
        working = False
    if not working:
        raise ApiError(422, "outside_hours", OUTSIDE_HOURS)
    session.commit()  # 읽기 트랜잭션을 닫는다 — 문은 자기 연결로 쓰기 잠금을 잡는다
    outcome = gate.schedule("call", row.id, _actor(user), body.at, now=_now())
    if outcome.code != "scheduled":
        raise ApiError(409, "not_schedulable", outcome.message)
    session.expire_all()
    return _one(session, schedule_id, row)


def cancel(session: Session, schedule_id: int, call_id: int) -> CallOut:
    """예약 → 초안: 시각·보내는 방식·승인한 사람을 비운다. 그 사이 일꾼이 가져갔거나 예약이 아니면 409 not_scheduled."""
    row = _call(session, schedule_id, call_id)
    changed = session.execute(update(OutreachCall).where(
        OutreachCall.id == row.id, OutreachCall.status == "scheduled",
    ).values(status="draft", scheduled_at=None, send_mode=None, approved_by=None)).rowcount
    if changed != 1:
        session.rollback()
        raise ApiError(409, "not_scheduled", NOT_SCHEDULED)
    session.commit()
    return _one(session, schedule_id, row)


def hangup(session: Session, schedule_id: int, call_id: int) -> CallOut:
    """진행 중인 통화를 끊으라고 일꾼에게 말한다(runner.hangup). 끝난 줄이거나 일꾼이 쥔 통화가 아니면 409 not_live.
    줄의 상태는 일꾼이 적는다(사건 hangup_by_person)."""
    row = _call(session, schedule_id, call_id)
    if row.status not in outreach.LIVE_CALL:
        raise ApiError(409, "not_live", NOT_LIVE)
    session.commit()
    if not _runner().hangup(row.id):
        raise ApiError(409, "not_live", NOT_LIVE)
    session.expire_all()
    return _one(session, schedule_id, row)


def redial(session: Session, schedule_id: int, call_id: int, user: User) -> CallOut:
    """받지 않음·통화 중·실패로 끝난 줄 → 같은 내용의 새 초안(retry_of, 옛 줄은 그대로). 걸지 않는다 — 사람이 [전화 걸기]를 누른다.
    방식·승인·결과는 옮기지 않는다."""
    old = _call(session, schedule_id, call_id)
    if old.direction != "out" or old.status not in REDIALABLE:
        raise ApiError(409, "not_redialable", NOT_REDIALABLE)
    row = OutreachCall(
        schedule_id=schedule_id, contact_id=old.contact_id, peer_number=old.peer_number, caller_class=old.caller_class,
        direction="out", purpose=old.purpose, questions_json=list(old.questions_json or []),
        avoid_json=list(old.avoid_json or []), language=old.language, voice_id=old.voice_id,
        purpose_key=old.purpose_key, origin="user", origin_name=user.name, status="draft", retry_of=old.id,
        activity_id=old.activity_id, field_item_id=old.field_item_id, approval_id=old.approval_id,
    )
    session.add(row)
    session.commit()
    return _one(session, schedule_id, row)


def confirm(session: Session, schedule_id: int, call_id: int, body: ConfirmIn, user: User) -> CallOut:
    """끝난(completed) 통화의 결과를 사람이 확정한다 — 확정한 사람은 로그인한 사람. 다시 확정하면 덮는다."""
    row = _call(session, schedule_id, call_id)
    _check_text("result", body.result)
    changed = session.execute(update(OutreachCall).where(
        OutreachCall.id == row.id, OutreachCall.status == "completed",
    ).values(result_confirmed=body.result, confirmed_by=user.name)).rowcount
    if changed != 1:
        session.rollback()
        raise ApiError(409, "not_completed", NOT_COMPLETED)
    session.commit()
    return _one(session, schedule_id, row)


def recording(session: Session, schedule_id: int, call_id: int) -> tuple[Path, str]:
    """(파일, 내려줄 이름). 녹음이 없으면 없는 통화와 같은 404."""
    row = _call(session, schedule_id, call_id)
    path = recording_file(row)
    if path is None:
        raise ApiError(404, "not_found", CALL_NOT_FOUND)
    return path, f"call-{row.id}{path.suffix.lower()}"
