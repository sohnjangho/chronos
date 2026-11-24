"""관리 포인트 API·도구(points.check)가 함께 쓰는 조회와 [근거 문장 보기]·[담당자에게 확인 연락].

- view: 지금 버전의 포인트·마지막 차이·바깥 위험·근거 문장 상태·카드 꼴(바뀜이 없으면 card null). what_if 면 지연 분석의
  가정 줄(app.points.card). 읽기만 한다 — 바깥 위험 찾기·근거 문장 채우기를 부르지 않는다. 날짜·여유는 저장한 엔진 값 그대로.
  지금 버전 포인트가 표에 없으면(이 기능 전 버전) 계산해 둔다(카드 줄은 만들지 않는다).
- quote: 사람이 누른 때만 quotes.fill(question=, mode="general", retry=). 그 위험 줄(ok)이 있어야 한다.
- people / contact: 담당 협력사(그 작업이 협력사 공종 말·연결 기록에 걸리는 곳 — 하네스 facts.allowed_for 와 같은 규칙)의 사람을
  보이고(번호 없음), 사람이 고른 연락처로 질문 글을 코드가 짓는다(포인트·위험 줄의 값만 — 숫자를 지어내지 않는다). preview 면
  글만, 아니면 기존 초안 길(메시지 API·통화 API 의 사람 초안, 보내지 않음)로 초안을 만들고 기존 초안 카드 꼴을 돌려준다.
  보내기는 늘 사람이 [보내기]·[전화 걸기]를 누르고 나가는 문(시험 모드·허용 번호·근무시간·권한)이 그대로 본다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.errors import ApiError
from app.outreach import phone, site_name
from app.outreach.harness import facts
from app.outreach.redact import hide_phones
from app.points import card, quotes
from app.points import service as points_service
from app.programs.outreach import calls_service
from app.programs.outreach import service as outreach_service
from app.programs.outreach.calls_schemas import CallIn
from app.programs.outreach.schemas import MessageIn
from app.store import contacts, outreach
from app.store import points as points_store
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load
from app.store.settings import points_config
from app.store.tables import User
from app.tools.notify import card_contact

SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
NO_WHAT_IF = "가정 관리 포인트가 없습니다 — 지연을 기록하거나 분석한 뒤에 볼 수 있습니다."
NOT_A_POINT = "지금 관리 포인트가 아닙니다."
NO_RISK = "근거 문장을 찾을 바깥 자료 줄이 없습니다."
QUESTION_MAX = 200
RISK_LINES_MAX = 3


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_if: bool = False
    retry: bool = False  # 「다시 찾기」 — 실패한 것만 다시 부른다


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: int
    channel: Literal["sms", "call"]
    what_if: bool = False
    preview: bool = False  # 글만 보고 초안은 만들지 않는다


def _schedule(session: Session, schedule_id: int) -> int:
    """지금 버전. 없는 일정 404."""
    try:
        get_record(session, schedule_id)
        return load(session, schedule_id)[2]
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None


def _row(session: Session, schedule_id: int, *, what_if: bool) -> tuple[int, card.PointCard | None, list[dict]]:
    """(지금 버전, 카드 줄, 포인트)."""
    n = _schedule(session, schedule_id)
    row = card.get(session, schedule_id, n, what_if=what_if)
    if what_if:
        if row is None:
            raise ApiError(404, "no_what_if", NO_WHAT_IF)
        return n, row, list(row.points_json)
    points = points_store.get(session, schedule_id, n)
    if points is None:
        try:
            points_service.refresh(session, schedule_id, n)
        except ScheduleError as e:
            session.rollback()
            raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None
        session.commit()
        points = points_store.get(session, schedule_id, n) or ()
    return n, row, [card.point_json(p) for p in points]


def view(session: Session, schedule_id: int, *, what_if: bool = False) -> dict:
    n, row, points = _row(session, schedule_id, what_if=what_if)
    cfg = points_config(session)
    basis = row.data_json["basis"] if row is not None else {"tf_days": cfg.tf_days, "window_weeks": cfg.window_weeks}
    risks = list(row.risks_json or []) if row is not None else []
    status = card.status_of(row) if row is not None else card.NOTHING
    return {
        "schedule_id": schedule_id, "version": n, "what_if": what_if, "basis": basis, "points": points,
        "diff": row.data_json["diff"] if row is not None else None,
        "risk_status": status, "risk_message": card.RISK_MESSAGES[status], "risks": risks,
        "quotes": card.quote_states(session, schedule_id, n, risks),
        "card": card.payload(session, row) if row is not None else None,
    }


def _point(session: Session, schedule_id: int, activity_id: str, *, what_if: bool
           ) -> tuple[int, dict, int | None, list[dict]]:
    """(지금 버전, 포인트, 앞 여유(모르면 None), 그 포인트의 위험 줄)."""
    n, row, points = _row(session, schedule_id, what_if=what_if)
    point = next((p for p in points if p["activity_id"] == activity_id), None)
    if point is None:
        raise ApiError(404, "not_a_point", NOT_A_POINT)
    before = None
    risks: list[dict] = []
    if row is not None:
        data = row.data_json
        for item in [*data["new"], *data["tightened"]]:
            if item["activity_id"] == activity_id and "before_tf" in item:
                before = item["before_tf"]
        risks = [r for r in row.risks_json or [] if r["activity_id"] == activity_id]
    return n, point, before, risks


# ── [근거 문장 보기] ─────────────────────────────────────────────────


def _quote_question(point: dict, lines: list[str]) -> str:
    return (f"「{point['name']}」 작업({point['es']}~{point['ef']}) 기간에 영향을 줄 수 있는 다음 바깥 소식의 근거가 되는 "
            f"기사·자료 문장을 찾아 주세요: {' / '.join(lines)}")


async def quote(session: Session, schedule_id: int, activity_id: str, kind: str, body: QuoteIn) -> dict:
    n, point, _, risks = _point(session, schedule_id, activity_id, what_if=body.what_if)
    lines = [r["line"] for r in risks if r["kind"] == kind and r["status"] == "ok"]
    if not lines:
        raise ApiError(404, "no_risk", NO_RISK)
    session.commit()  # fill 은 쌓인 쓰기 없이 부른다(자기 세션으로 pending 을 적는다)
    await quotes.fill(schedule_id, n, activity_id, kind, question=_quote_question(point, lines), mode="general",
                      retry=body.retry)
    session.expire_all()
    return card.quote_json(quotes.get(session, schedule_id, n, activity_id, kind)) or {}


# ── [담당자에게 확인 연락] ───────────────────────────────────────────

_CHANNELS = (("sms", "can_sms", phone.can_sms), ("call", "can_call", phone.can_call))


def people(session: Session, schedule_id: int, activity_id: str, *, what_if: bool = False) -> dict:
    """그 작업 담당 협력사의 사람들(숨긴 것 빼고). 번호는 없다 — 받을 수 있는 채널(sms·call)과 수신 거부만."""
    _, point, _, _ = _point(session, schedule_id, activity_id, what_if=what_if)
    found = []
    for firm, folks in contacts.listed(session, schedule_id):
        if not folks or activity_id not in facts.allowed_for(session, schedule_id, [firm.id], [w.id for w in folks]):
            continue
        refused = outreach.do_not_contact_numbers(session, [w.phone for w in folks if w.phone])
        for who in folks:
            number = phone.normalize(who.phone)
            usable = number is not None and not who.phone_invalid
            blocked = bool(who.do_not_contact) or number in refused
            found.append({
                "contact_id": who.id, "name": hide_phones(who.name), "role_title": hide_phones(who.role_title),
                "company": hide_phones(firm.name), "trade": hide_phones(firm.trade), "do_not_contact": blocked,
                "channels": [] if blocked or not usable else
                [c for c, flag, able in _CHANNELS if getattr(who, flag) and able(number)],
            })
    return {"activity_id": activity_id, "name": point["name"], "people": found}


def _span(point: dict) -> str:
    es, ef = point["es"], point["ef"]  # 저장한 ISO 날짜
    return f"{es[5:7]}.{es[8:10]}~{ef[5:7]}.{ef[8:10]}"


def _state_line(point: dict, before: int | None) -> str:
    tf = point["tf"]
    if before is not None and before > tf:
        return f"여유가 {before}일에서 {tf}일로 줄었습니다" if tf > 0 else f"여유가 {before}일에서 없어졌습니다"
    if point["critical"] or tf <= 0:
        return "여유가 없는 작업입니다"
    return f"여유가 {tf}일입니다"


def _risk_lines(risks: list[dict]) -> list[str]:
    return [hide_phones(r["line"]) for r in risks if r["status"] == "ok"][:RISK_LINES_MAX]


def message_body(site: str, person: str, point: dict, before: int | None, risks: list[dict]) -> str:
    head = f"[{site}] " if site else ""
    text = f"{head}{person} 님, 「{point['name']}」({_span(point)}) {_state_line(point, before)}."
    lines = _risk_lines(risks)
    if lines:
        text += f" 참고한 바깥 소식: {'; '.join(lines)}."
    return text + " 일정대로 진행할 수 있는지 알려 주시겠어요?"


def call_text(point: dict, before: int | None, risks: list[dict]) -> tuple[str, list[str]]:
    purpose = f"「{point['name']}」 일정 확인"[:QUESTION_MAX]
    first = f"「{point['name']}」({_span(point)}) 작업을 일정대로 마칠 수 있나요? {_state_line(point, before)}."
    questions = [first[:QUESTION_MAX]]
    questions += [f"{line} — 이 소식이 일정에 영향을 주나요?"[:QUESTION_MAX] for line in _risk_lines(risks)[:2]]
    return purpose, questions


async def contact(session: Session, schedule_id: int, activity_id: str, body: ContactIn, user: User) -> dict:
    _, point, before, risks = _point(session, schedule_id, activity_id, what_if=body.what_if)
    who = outreach_service.check_reachable(session, schedule_id, body.contact_id, body.channel)  # 404·409(번호·까닭 없음)
    person = hide_phones(who.name)
    if body.channel == "sms":
        text = message_body(site_name.spoken(session, schedule_id), person, point, before, risks)
        if body.preview:
            return {"preview": True, "channel": "sms", "body": text}
        made = await outreach_service.create(session, schedule_id, MessageIn(
            contact_id=who.id, channel="sms", body=text, activity_id=activity_id), user)
        return {"preview": False, "card": {
            "kind": "outreach_draft", "schedule_id": schedule_id, "message_id": made.message.id,
            "contact": card_contact(session, who), "channel": "sms", "body": made.message.body, "body_ko": None,
            "needs_approval": True}}
    purpose, questions = call_text(point, before, risks)
    if body.preview:
        return {"preview": True, "channel": "call", "purpose": purpose, "questions": questions}
    made = calls_service.create(session, schedule_id, CallIn(
        contact_id=who.id, purpose=purpose, questions=questions, activity_id=activity_id), user)
    return {"preview": False, "card": {
        "kind": "outreach_call_draft", "schedule_id": schedule_id, "call_id": made.id,
        "contact": card_contact(session, who), "purpose": hide_phones(purpose),
        "questions": [hide_phones(q) for q in questions], "avoid": [], "language": who.language,
        "needs_approval": True}}
