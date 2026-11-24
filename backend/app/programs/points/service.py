"""관리 포인트 API·도구(points.check)가 함께 쓰는 조회와 [근거 문장 보기]·[담당자에게 확인 연락].

- view: 지금 버전의 포인트·마지막 차이·바깥 위험·근거 문장 상태·카드 꼴(바뀜이 없으면 card null). what_if 면 지연 분석의
  가정 줄(app.points.card). 읽기만 한다 — 바깥 위험 찾기·근거 문장 채우기를 부르지 않는다. 날짜·여유는 저장한 엔진 값 그대로.
  지금 버전 포인트가 표에 없으면(이 기능 전 버전) 계산해 둔다(카드 줄은 만들지 않는다).
- quote: 사람이 누른 때만 quotes.fill(question=, mode="general", retry=). 그 위험 줄(ok)이 있어야 한다. 질문은
  card.quote_question(업체 갈래는 받은 제목을 넣지 않음), 열쇠 kind 는 card.quote_kind(가정 여부·질문 지문).
- retry_risks: 사람의 「다시 찾기」 — 실패·멈춘 바깥 위험 찾기만 다시 띄운다(자동으로는 다시 찾지 않는다).
- people / contact: 담당 협력사(그 작업이 협력사 공종 말·연결 기록에 걸리는 곳 — 하네스 facts.allowed_for 와 같은 규칙)의 사람을
  보이고(번호 없음), 사람이 고른 연락처로 질문 글을 코드가 짓는다(포인트·위험 줄의 값만 — 숫자를 지어내지 않는다). AI 통화의
  물어볼 것에는 코드가 지은 줄만 넣는다(업체 소식 제목 같은 바깥 글은 빼다 — 지시로 들어가지 않게). 문자에는 사람이 읽으므로
  제목도 넣되 글자 검사(check_body)를 지난 줄만. preview 면
  글만, 아니면 기존 초안 길(메시지 API·통화 API 의 사람 초안, 보내지 않음)로 초안을 만들고 기존 초안 카드 꼴을 돌려준다.
  보내기는 늘 사람이 [보내기]·[전화 걸기]를 누르고 나가는 문(시험 모드·허용 번호·근무시간·권한)이 그대로 본다.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError
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
NOT_FAILED = "다시 찾을 것이 없습니다 — 바깥 위험 찾기가 실패했거나 아직 찾지 않았을 때만 찾습니다."
TOO_LONG = "보낼 글이 너무 깁니다. 직접 줄여서 초안을 만들어 주세요."
QUESTION_MAX = 200
RISK_LINES_MAX = 3


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_if: bool = False
    retry: bool = False  # 「다시 찾기」 — 실패한 것만 다시 부른다


class RetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_if: bool = False


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
        try:
            session.commit()
        except IntegrityError:  # 동시에 첫 읽기 — 다른 요청이 먼저 저장했다. 되돌리고 저장된 줄을 읽는다
            session.rollback()
        points = points_store.get(session, schedule_id, n) or ()
    return n, row, [card.point_json(p) for p in points]


def view(session: Session, schedule_id: int, *, what_if: bool = False, field: bool = False) -> dict:
    """field = 보는 사람이 현장 관리자(카드에 [담당자에게 확인 연락]을 싣지 않는다)."""
    n, row, points = _row(session, schedule_id, what_if=what_if)
    cfg = points_config(session)
    basis = row.data_json["basis"] if row is not None else {"tf_days": cfg.tf_days, "window_weeks": cfg.window_weeks}
    risks = list(row.risks_json or []) if row is not None else []
    status = card.status_of(row) if row is not None else card.NOTHING
    return {
        "schedule_id": schedule_id, "version": n, "what_if": what_if, "basis": basis, "points": points,
        "diff": row.data_json["diff"] if row is not None else None,
        "risk_status": status, "risk_message": card.RISK_MESSAGES[status], "risks": risks,
        "quotes": card.quote_states(session, row) if row is not None else {},
        "card": card.payload(session, row, field=field) if row is not None else None,
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


async def quote(session: Session, schedule_id: int, activity_id: str, kind: str, body: QuoteIn) -> dict:
    n, point, _, risks = _point(session, schedule_id, activity_id, what_if=body.what_if)
    question = card.quote_question(point, kind, risks)
    if question is None:
        raise ApiError(404, "no_risk", NO_RISK)
    stored = card.quote_kind(kind, question, what_if=body.what_if)
    session.commit()  # fill 은 쌓인 쓰기 없이 부른다(자기 세션으로 pending 을 적는다)
    await quotes.fill(schedule_id, n, activity_id, stored, question=question, mode="general", retry=body.retry)
    session.expire_all()
    return card.quote_json(quotes.get(session, schedule_id, n, activity_id, stored)) or {}


def retry_risks(session: Session, schedule_id: int, body: RetryIn, *, field: bool = False) -> dict:
    """「다시 찾기」·[바깥 위험 찾기](not_started 의 첫 찾기) → 지금 카드 상태(view). 그 밖이면 409 not_failed."""
    n, row, _ = _row(session, schedule_id, what_if=body.what_if)
    if row is None or not card.retry(session, row):
        session.rollback()
        raise ApiError(409, "not_failed", NOT_FAILED)
    session.commit()
    card.launch(schedule_id, n, what_if=body.what_if)
    return view(session, schedule_id, what_if=body.what_if, field=field)


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
    if tf < 0:
        return f"여유가 {-tf}일 모자랍니다"
    if before is not None and before > tf:
        return f"여유가 {before}일에서 {tf}일로 줄었습니다" if tf > 0 else f"여유가 {before}일에서 없어졌습니다"
    if point["critical"] or tf <= 0:
        return "여유가 없는 작업입니다"
    return f"여유가 {tf}일입니다"


def _clean(line: str) -> bool:
    try:
        outreach_service.check_body(line)
    except ApiError:
        return False
    return True


def _risk_lines(risks: list[dict], *, outside_text: bool) -> list[str]:
    """ok 위험 줄(번호 가림, 글자 검사를 지난 것). outside_text 가 아니면 업체 갈래(받은 제목)는 뺀다."""
    lines = [hide_phones(r["line"]) for r in risks if r["status"] == "ok" and (outside_text or r["kind"] != "business")]
    return [line for line in lines if _clean(line)][:RISK_LINES_MAX]


def message_body(site: str, person: str, point: dict, before: int | None, risks: list[dict]) -> str:
    head = f"[{site}] " if site else ""
    text = f"{head}{person} 님, 「{point['name']}」({_span(point)}) {_state_line(point, before)}."
    lines = _risk_lines(risks, outside_text=True)  # 사람이 읽는 문자
    if lines:
        text += f" 참고한 바깥 소식: {'; '.join(lines)}."
    return text + " 일정대로 진행할 수 있는지 알려 주시겠어요?"


# ── AI 통화의 물어볼 것(11-24 되돌이 시험·PM 녹음 확인): 전화로 사람이 묻듯 ───────────────────────────────
# 상황(어느 작업이 언제까지) + 물음. 작업 id·여유(TF)·크리티컬 같은 일정표 말, 점 찍은 날짜, 출처 꼬리표(「· The World Bank ·
# 2026-10」)는 넣지 않는다 — 음성 모델이 적힌 글을 그대로 읽었다. 바깥 위험은 카드에 ok 로 있는 줄만, 코드가 아는 꼴(risk.py 가
# 지은 줄)일 때만 말로 바꾸고, 꼴을 모르면 넣지 않는다(꼬리표째 읽지 않게). 방향은 자료 그대로, 까닭은 말하지 않는다.
ASK_ON_TIME = "제시간에 끝낼 수 있을까요? 어렵다면 무엇이 필요할까요?"
ASK_SUPPLY = "자재 수급은 제때 가능할까요?"
_MONTHS_SPOKEN = {1: "한 달", 2: "두 달", 3: "석 달", 6: "여섯 달", 12: "열두 달"}
_CONSONANT_END = set("013678lmnr")  # 숫자·라틴 글자를 소리 내 읽은 끝에 받침이 있는 것(영·일·삼·육·칠·팔, 엘·엠·엔·알)
_MATERIAL = re.compile(r"^(?P<label>\S+) (?P<months>\d+)개월 (?P<pct>[+-]?\d+(?:\.\d+)?)% · ")
_FX = re.compile(r"^원·달러 (?P<rate>\d{1,3}(?:,\d{3})*)원 · ")
_FORECAST = re.compile(r"^(?P<a>\d{2})-(?P<b>\d{2})(?:~(?P<c>\d{2})-(?P<d>\d{2}))? 강수확률 최고 (?P<pop>\d+)% · 기상청")
_HISTORY = re.compile(r"^(?P<month>\d{1,2})월 지난 (?P<years>\d+)년 강수일 평균 (?P<days>\d+(?:\.\d+)?)일 · 기상청")


def _subject(name: str) -> str:
    """작업 이름 + 이/가(끝 글자의 받침으로 — 숫자·라틴 글자는 읽은 소리로)."""
    last = name.strip()[-1:].lower()
    if "가" <= last <= "힣":
        has_final = (ord(last) - 0xAC00) % 28 != 0
    else:
        has_final = last in _CONSONANT_END
    return f"{name.strip()}{'이' if has_final else '가'}"


def _spoken_day(iso: str) -> str:
    return f"{int(iso[5:7])}월 {int(iso[8:10])}일"


def _trend(pct: float) -> str:
    """시세 움직임을 말로: 3.2 → 「3% 남짓 내렸는데」, 3.7 → 「4% 가까이 …」, 0.3 → 「조금 …」, 0 → 「거의 그대로인데」."""
    if pct == 0:
        return "거의 그대로인데"
    way = "올랐는데" if pct > 0 else "내렸는데"
    size = abs(pct)
    whole = int(size + 0.5)
    if whole == 0:
        return f"조금 {way}"
    amount = f"{whole}%" if size == whole else f"{whole}% {'남짓' if size > whole else '가까이'}"
    return f"{amount} {way}"


def _risk_question(risk: dict) -> str | None:
    """카드의 위험 줄 하나 → 전화 말씨의 물음. 아는 꼴이 아니면 None(넣지 않는다)."""
    line = risk["line"]
    if risk["kind"] == "materials" and (hit := _MATERIAL.match(line)):
        months = int(hit["months"])
        return (f"{hit['label']} 시세가 최근 {_MONTHS_SPOKEN.get(months, f'{months}개월')} {_trend(float(hit['pct']))}, "
                f"{ASK_SUPPLY}")
    if risk["kind"] == "fx" and (hit := _FX.match(line)):
        rate = int(hit["rate"].replace(",", "")) // 10 * 10
        return f"요즘 원·달러 환율이 {rate:,}원대인데, {ASK_SUPPLY}"
    if risk["kind"] == "weather" and (hit := _FORECAST.match(line)):
        start = f"{int(hit['a'])}월 {int(hit['b'])}일"
        if hit["c"] is None:
            return f"{start} 비 올 확률이 최고 {hit['pop']}%로 예보됐는데, 그날 작업에 지장은 없을까요?"
        end = f"{int(hit['d'])}일" if hit["c"] == hit["a"] else f"{int(hit['c'])}월 {int(hit['d'])}일"
        return f"{start}부터 {end} 사이 비 올 확률이 최고 {hit['pop']}%로 예보됐는데, 그동안 작업에 지장은 없을까요?"
    if risk["kind"] == "weather" and (hit := _HISTORY.match(line)):
        return (f"{int(hit['month'])}월은 지난 {hit['years']}년 동안 비 온 날이 평균 {hit['days']}일인데, "
                "그 달 작업 일정은 괜찮을까요?")
    return None


def call_text(point: dict, before: int | None, risks: list[dict]) -> tuple[str, list[str]]:
    """AI 통화 초안의 (목적, 물어볼 것). before 는 문자와 같은 인자(통화 물음에는 여유 말을 넣지 않는다)."""
    purpose = f"「{point['name']}」 일정 확인"[:QUESTION_MAX]
    first = f"{_subject(point['name'])} {_spoken_day(point['ef'])}까지 끝나야 하는 일정인데, {ASK_ON_TIME}"
    questions = [first[:QUESTION_MAX]]
    asked = [_risk_question(r) for r in risks if r["status"] == "ok" and r["kind"] != "business"]  # 코드가 지은 줄만
    questions += [q[:QUESTION_MAX] for q in asked if q is not None and _clean(q)][:2]
    return purpose, questions


async def contact(session: Session, schedule_id: int, activity_id: str, body: ContactIn, user: User) -> dict:
    _, point, before, risks = _point(session, schedule_id, activity_id, what_if=body.what_if)
    who = outreach_service.check_reachable(session, schedule_id, body.contact_id, body.channel)  # 404·409(번호·까닭 없음)
    person = hide_phones(who.name)
    if body.channel == "sms":
        text = message_body(site_name.spoken(session, schedule_id), person, point, before, risks)
        try:  # 길이·글자를 서비스 전에 본다(422, 500 아님)
            draft = MessageIn(contact_id=who.id, channel="sms", body=text, activity_id=activity_id)
            outreach_service.check_body(draft.body)
        except ValidationError:
            raise ApiError(422, "invalid_text", TOO_LONG) from None
        if body.preview:
            return {"preview": True, "channel": "sms", "body": draft.body}
        made = await outreach_service.create(session, schedule_id, draft, user)
        return {"preview": False, "card": {
            "kind": "outreach_draft", "schedule_id": schedule_id, "message_id": made.message.id,
            "contact": card_contact(session, who), "channel": "sms", "body": made.message.body, "body_ko": None,
            "needs_approval": True}}
    purpose, questions = call_text(point, before, risks)
    try:
        draft_call = CallIn(contact_id=who.id, purpose=purpose, questions=questions, activity_id=activity_id)
        outreach_service.check_body(purpose, *questions)
    except ValidationError:
        raise ApiError(422, "invalid_text", TOO_LONG) from None
    if body.preview:
        return {"preview": True, "channel": "call", "purpose": purpose, "questions": questions}
    made = calls_service.create(session, schedule_id, draft_call, user)
    return {"preview": False, "card": {
        "kind": "outreach_call_draft", "schedule_id": schedule_id, "call_id": made.id,
        "contact": card_contact(session, who), "purpose": hide_phones(purpose),
        "questions": [hide_phones(q) for q in questions], "avoid": [], "language": who.language,
        "needs_approval": True}}
