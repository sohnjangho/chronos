"""[에이전트에게 초안 맡기기](계획 4 Task 82): 입력창의 단추가 모델에게 그 사람에게 보낼 글의 초안을 맡긴다.

- 모델은 **초안 글만** 쓴다. 이 모듈은 줄을 만들지 않고 아무것도 쓰지 않는다 — 글을 돌려줄 뿐이다(줄은
  `programs.outreach.service.create_agent_draft`, 보내기는 사람이 [보내기]를 누를 때 나가는 문).
- 모델이 받는 것(지시문 `app/agent/prompts/outreach_draft.md` + `<자료>` JSON 하나 + 담당자 요청): 오늘(한국 시각 날짜·요일),
  현장 이름, 연락처
  이름·담당·협력사·공종·언어, 고른 작업의 id·이름·**코드가 일정 계산에서 읽은** 시작·종료일·상태, 그 사람이 알아도 되는 작업
  (`facts.allowed_for` — 하네스 도구와 같은 규칙, 날짜는 같은 계산), 최근 대화 6줄(보낸·받은 줄만, 초안·막힌 줄은 빼고,
  날짜는 해를 붙여 「2027년 1월 1일」),
  힌트. **번호는 없다**(연락처 번호 칸을 읽지 않는다). 자유 글(이름·담당·협력사·현장·대화·힌트)은 `hide_phones` 를 거친다.
  메모(note)·수신 거부 까닭(dnc_reason)은 싣지 않는다.
- 상대 글은 자료로만: `<자료>` 안 JSON 의 글 값이고, `<`·`>` 는 JSON 이스케이프(\\u003c·\\u003e)로 바꿔 자료 밖으로 나올 수 없다.
- 고른 작업은 알아도 되는 작업에 없어도 싣는다: 담당자가 이 초안에 그 작업을 연결했고, 연결된 작업은 하네스 규칙
  (`facts.linked`)으로도 그 사람에게 알아도 되는 작업이 된다.
- 부르기는 한 번: `LlmClient.chat("normal", …, json_schema={body, body_ko})`, 시간 TIMEOUT_S·답 길이 MAX_TOKENS.
  연결 없음은 DraftNotReady, 실패·시간 초과·쓸 수 없는 답은 DraftFailed(글·답 내용은 남기지 않는다).
- 한국어(`ko`)가 아닌 사람은 body(그 언어)와 body_ko(한국어 번역)가 둘 다 있어야 한다. `ko` 면 body_ko 는 None.
  쓸 언어는 자료 뒤 한 줄 `languages.line(언어, WRITE)`(Task 100 — 음성·글 지시문과 같은 상수). 모르는 언어 코드는 한국어.
"""

import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.outreach import hours, languages, site_name
from app.outreach.harness import facts
from app.outreach.redact import hide_phones
from app.store import contacts, outreach, schedules, view
from app.store.tables_outreach import Contact
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[1] / "agent" / "prompts" / "outreach_draft.md"
TIMEOUT_S = 30  # 부르기 전체 시간
MAX_TOKENS = 1000  # 답 길이(문자 초안은 짧다)
RECENT_LINES = 6  # 모델에게 주는 최근 대화 줄 수
SCAN_LINES = 50  # 그 6줄을 찾으려고 훑는 최근 줄 수(초안·막힌 줄이 섞여 있어도 끝이 있게)
LINE_CHARS = 300  # 대화 한 줄의 글자 수(가린 뒤 자른다)
FACTS_MAX = 8  # 알아도 되는 작업 수(끝나지 않은 것, 시작일 순)
SAID = ("sending", "accepted", "delivered", "unconfirmed")  # 상대에게 갔거나 갔을 수 있는 우리 줄
SCHEMA = {
    "type": "object",
    "properties": {"body": {"type": "string"}, "body_ko": {"type": ["string", "null"]}},
    "required": ["body", "body_ko"],
    "additionalProperties": False,
}
_WEEKDAYS = "월화수목금토일"
_CHANNEL = {"sms": "문자", "kakao": "카카오톡 알림톡(쓸 수 없으면 같은 글이 문자로 나감)"}


@dataclass(frozen=True)
class Drafted:
    body: str
    body_ko: str | None  # 상대 언어가 한국어가 아닐 때의 한국어 번역


class DraftFailed(Exception):
    """초안을 얻지 못함(호출 실패·시간 초과·쓸 수 없는 답). 까닭 글에 받은 값은 없다."""


class DraftNotReady(DraftFailed):
    """LLM 연결이 없거나 키를 읽을 수 없어 부르지 못함(LlmNotReady)."""


def _now() -> datetime:
    return datetime.now(UTC)


def client_for(session: Session) -> LlmClient:
    """초안 맡기기가 쓰는 LLM 클라이언트(대화 에이전트와 같은 클라이언트·배정). 시험이 대본 LLM 으로 바꾼다."""
    return LlmClient(session)


def _hide(text: str | None) -> str:
    return hide_phones(text or "")


def _fact(row: dict) -> dict:
    return {"id": row["id"], "이름": _hide(row["name"]), "시작": row["es"].isoformat(), "종료": row["ef"].isoformat(),
            "상태": row["status"]}


def _facts(session: Session, schedule_id: int, who: Contact, activity_id: str | None) -> tuple[dict | None, list[dict]]:
    """(고른 작업, 알아도 되는 작업). 날짜·상태는 일정 계산(app.store.view — 화면·하네스 도구와 같은 계산)에서 읽는다.
    계산할 수 없는 일정이면 고른 작업은 id·이름만, 목록은 비운다."""
    allowed = facts.allowed_for(session, schedule_id, [who.company_id], [who.id])
    try:
        rows = view.view_data(session, schedule_id)["activities"]
    except (schedules.NotFound, ScheduleError):
        rows = []
    picked = next((_fact(row) for row in rows if row["id"] == activity_id), None)
    if activity_id is not None and picked is None:
        picked = {"id": activity_id, "이름": _hide(facts.names(session, schedule_id).get(activity_id))}
    known = sorted((row for row in rows if row["id"] in allowed and row["id"] != activity_id and row["status"] != "done"),
                   key=lambda row: row["es"])
    return picked, [_fact(row) for row in known[:FACTS_MAX]]


def _recent(session: Session, schedule_id: int, contact_id: int) -> list[dict]:
    """최근 대화: 받은 줄과 상대에게 갔(을 수 있)는 우리 줄의 마지막 RECENT_LINES 개, 오래된 것부터. 글은 가린 뒤 자른다."""
    rows = outreach.thread(session, schedule_id, contact_id, limit=SCAN_LINES)
    said = [row for row in rows if row.direction == "in" or row.status in SAID][-RECENT_LINES:]
    out = []
    for row in said:
        day = as_utc(row.sent_at or row.created_at).astimezone(hours.KST)
        out.append({"날짜": f"{day.year}년 {day.month}월 {day.day}일", "쓴 쪽": "상대" if row.direction == "in" else "우리",
                    "글": _hide(row.body)[:LINE_CHARS]})
    return out


def material(session: Session, schedule_id: int, who: Contact, channel: str, activity_id: str | None) -> dict:
    """모델에게 주는 자료(번호 없음 — 모듈 머리 글). 현장은 부를 이름(site_name.spoken), 현장 정보는 적힌 참고 자료만."""
    try:
        firm = contacts.get_company(session, schedule_id, who.company_id)
        firm_name, trade = firm.name, firm.trade
    except contacts.NotFound:
        firm_name, trade = "", ""
    picked, known = _facts(session, schedule_id, who, activity_id)
    today = _now().astimezone(hours.KST).date()
    out = {
        "오늘": f"{today.isoformat()} ({_WEEKDAYS[today.weekday()]})",
        "현장": _hide(site_name.spoken(session, schedule_id)),
        "채널": _CHANNEL.get(channel, "문자"),
        "상대": {"이름": _hide(who.name), "담당": _hide(who.role_title), "협력사": _hide(firm_name),
                 "공종": _hide(trade), "언어": who.language},
        "고른 작업": picked,
        "알아도 되는 작업": known,
        "최근 대화": _recent(session, schedule_id, who.id),
    }
    if reference := site_name.reference(session, schedule_id):
        out["현장 정보"] = reference
    return out


def _user_text(data: dict, hint: str, language: str) -> str:
    # 자료 안의 < > 는 JSON 이스케이프로 — 상대 글이 </자료> 를 써도 자료 밖으로 나오지 않는다
    block = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    asked = _hide(hint).strip() or "(없음 — 최근 대화와 고른 작업에 맞춰 써 주세요)"
    # 쓸 언어 한 줄(Task 100 — 음성·글 지시문과 같은 상수): 「상대의 언어: en(영어). 영어로 씁니다.」
    return f"<자료>{block}</자료>\n\n{languages.line(language, languages.WRITE)}\n\n담당자 요청: {asked}"


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return unicodedata.normalize("NFC", value).strip() or None


def _drafted(parsed: object, language: str) -> Drafted:
    if not isinstance(parsed, dict):
        logger.warning("에이전트 초안: 답이 JSON 객체가 아님")
        raise DraftFailed
    body, body_ko = _text(parsed.get("body")), _text(parsed.get("body_ko"))
    if body is None:
        logger.warning("에이전트 초안: 답에 글이 없음")
        raise DraftFailed
    if languages.code(language) == "ko":  # 모르는 언어도 한국어(languages.code)
        return Drafted(body, None)
    if body_ko is None:
        logger.warning("에이전트 초안: 한국어가 아닌 상대인데 한국어 번역이 없음")
        raise DraftFailed
    return Drafted(body, body_ko)


async def draft_message(session: Session, schedule_id: int, contact_id: int, channel: str, *,
                        activity_id: str | None = None, hint: str = "") -> Drafted:
    """그 일정의 그 연락처에게 보낼 초안 글(모델 한 번). 쓰지 않는다. 부르는 쪽은 수신 거부·번호·채널을 먼저 본다
    (service.check_agent_draft). 그 일정 연락처가 아니면(그 사이 지워졌으면) contacts.NotFound, 연결 없음은 DraftNotReady,
    그 밖의 모델 쪽 실패는 DraftFailed."""
    who = contacts.get_contact(session, schedule_id, contact_id)
    messages = [
        {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
        {"role": "user", "content": _user_text(material(session, schedule_id, who, channel, activity_id), hint,
                                               who.language)},
    ]
    try:
        reply = await client_for(session).chat("normal", messages, json_schema=SCHEMA, timeout_s=TIMEOUT_S,
                                               max_tokens=MAX_TOKENS)
    except LlmNotReady:
        raise DraftNotReady from None
    except LlmFailed:
        raise DraftFailed from None  # 실패 종류는 LlmClient 가 이미 남겼다(내용 없이)
    return _drafted(reply.parsed, who.language)
