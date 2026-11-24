"""통화 뒤(Task 89): 끝난(completed) 통화 한 통에 ① 하네스의 뒤 확인 ② 모델 요약 ③ 결과 제안 저장. **후속 줄은 만들지 않는다**
— 담당자에게 새 통화·다시 걸 약속·음성사서함 문자 초안은 Task 67 의 도구가 통화 중에 이미 만든 줄이고, 위임으로 줄에 들어간
후속 통화는 이 통화가 끝난 뒤 통화 일꾼이 건다.

- **completed 인 줄만**: 줄의 상태로 정한다. 받지 않음·통화 중·실패(받기 전 고장 「걸렸는지 확인 필요」·통화 중 고장·받은 뒤
  끊김·첫마디에 밝히지 않음은 모두 failed)·진행 중·없는 줄은 아무것도 하지 않는다(뒤 확인도 요약도 부르지 않음).
- **① 뒤 확인은 하네스 것 하나**: `review.check(session, Ref("call", id), said=받아쓰기의 agent 말, peer_lines=peer 말,
  tool_results=그 통화의 도구 결과(box.results), scope=box.scope, caller_class=box.caller_class, now=통화가 끝난 때)`.
  box 가 없으면(일꾼 밖에서 다시 부름) 도구 결과는 없고, 거는 통화는 `door.outbound_scope`, 그 밖은 닫힌 빈 범위 — 근거가
  줄어 깃발이 늘 뿐 줄지 않는다. check 가 예외면 판정이 없으므로 「깨끗하지 않음」으로: 그 통화에 review 보고 한 줄(이미
  있으면 그대로)을 남기고 요약은 이어 간다.
- **② 요약**: `LlmClient.chat("normal", …, json_schema={summary_ko, result})` 한 번(시간 TIMEOUT_S · 답 길이 MAX_TOKENS ·
  다시 시도 없음). 자료(`<자료>` JSON — `<`·`>` 는 이스케이프)는 오늘·통화한 날(한국 날짜), 현장, 상대 이름·담당·협력사,
  목적·물어볼 것, 답(뒤 확인 뒤의 quote_found 가 참이 아니면 「확인 필요」), 저장된 받아쓰기(쪽·초·말 — 줄 MAX_LINES,
  한 줄 LINE_CHARS, 합 TEXT_CHARS). **번호 없음**: 연락처 번호 칸을 읽지 않고, 모든 자유 글은 `hide_phones` 를 한 번 더
  거친다(저장된 가린 글은 가린 채 — 되살리지 않는다). 지시문은 `app/agent/prompts/call_summary.md`.
- **언어**(Task 100): 자료에 「통화 언어」(languages.name)를 싣고, 받아쓰기는 그 언어 원문 그대로(번호만 가림) 준다. 요약·결과는
  한국어만 쓴다 — 한국어가 아닌 답(languages.is_korean 거짓)은 쓸 수 없는 답이다.
- **실패**(연결 없음·호출 실패·시간 초과·쓸 수 없는 답): summary_ko 는 빈 글 그대로, 결과 제안도 없고 통화 기록은 바뀌지 않는다.
  사용량 `add_usage(session, "summary", ref=("call", id), model, input_tokens, output_tokens, cost)` 은 **답이 온 때만**(쓸 수
  없는 답도 토큰을 썼으므로 센다. 연결 없음·호출 실패·시간 초과는 받은 토큰이 없어 세지 않는다 — llm_calls 에는 LlmClient 가 남긴다).
- **④ 결과 제안**: `result_proposed`(가린 글 — 모델이 결과를 비우면 NO_RESULT 「결과 확인 필요」)만 쓴다 — `result_confirmed`·`confirmed_by` 는 사람이 확정하는 칸이라 건드리지 않는다.
- **⓪ 수신 거부 뒤받침**(H1): 받아쓰기의 상대 말에 수신 거부 말(door.is_stop, 한 낱말 규칙 빼고 — call_run 과 같은 규칙)이 있는데
  그 번호가 아직 수신 거부가 아니면(통화 중 표시가 실패함) 그 통화의 도구 상자로 `mark_do_not_contact` 를 한 번 더 부른다. box 가
  없거나 그 등급의 묶음에 그 도구가 없으면 하지 않는다(통화 중에도 못 했다). 실패는 종류만 로그 — 뒤 확인·요약은 이어 간다.
- DB 일은 짧은 세션을 스레드에서. 모델을 부르는 동안 쥔 쓰기가 없다. 로그에는 예외의 종류만.
"""

import asyncio
import json
import logging
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.llm.client import LlmClient, LlmFailed, LlmNotReady, LlmReply
from app.outreach import hours, languages
from app.outreach.harness import door, review
from app.outreach.harness.tools import Toolbox
from app.outreach.harness.types import CallerClass, Ref, Scope
from app.outreach.redact import hide_phones
from app.store import contacts, outreach
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import ContactReport, OutreachCall
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[2] / "agent" / "prompts" / "call_summary.md"
TIMEOUT_S = 30  # 부르기 전체 시간
MAX_TOKENS = 1000  # 답 길이
MAX_LINES = 400  # 자료에 넣는 받아쓰기 줄(call_run.MAX_TURNS 와 같음)
LINE_CHARS = 500  # 받아쓰기 한 줄(가린 뒤 자른다)
TEXT_CHARS = 20_000  # 받아쓰기 전체 글자 — 넘으면 앞에서부터 이만큼, 「받아쓰기 잘림」
MAX_QUESTIONS = MAX_ANSWERS = 20
FIELD_CHARS = 300  # 목적·질문·답·근거 말 한 칸
SUMMARY_CHARS, RESULT_CHARS = 2000, 300  # 모델 답의 상한 — 넘으면 쓸 수 없는 답
UNVERIFIED, VERIFIED = "확인 필요", "근거 확인됨"
NO_RESULT = "결과 확인 필요"  # 모델이 결과를 비워 두었을 때 저장하는 제안
HEARD_OPT_OUT = "통화 중 상대가 수신 거부를 말함"  # 코드가 들은 수신 거부의 까닭(통화 중·통화 뒤 같은 글)
SCHEMA = {
    "type": "object",
    "properties": {"summary_ko": {"type": "string"}, "result": {"type": "string"}},
    "required": ["summary_ko", "result"],
    "additionalProperties": False,
}
_CLOSED = Scope("unknown", (), (), False, "none")  # 닫힌 빈 범위(도구 상자와 같은 꼴)
_WEEKDAYS = "월화수목금토일"


def _now() -> datetime:
    return datetime.now(UTC)


def _db():
    return contextmanager(get_session)()


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


def client_for(session: Session) -> LlmClient:
    """요약이 쓰는 LLM 클라이언트(대화 에이전트·초안과 같은 클라이언트·배정). 시험이 대본 LLM 으로 바꾼다."""
    return LlmClient(session)


async def finish(call_id: int, box: Toolbox | None = None) -> None:
    """끝난 통화의 뒤 일(모듈 머리 글). box 는 그 통화의 도구 상자(도구 결과·지금의 범위·등급) — 일꾼이 넘긴다."""
    await _opt_out_again(call_id, box)
    data = await asyncio.to_thread(_check, call_id, box)
    if data is None:
        return
    reply = await _ask(data)
    if reply is not None:
        await asyncio.to_thread(_store, call_id, reply)


# ── ⓪ 수신 거부 뒤받침 ──────────────────────────────────────────────


async def _opt_out_again(call_id: int, box: Toolbox | None) -> None:
    if box is None or "mark_do_not_contact" not in box.names:
        return
    try:
        missed = await asyncio.to_thread(_opt_out_missed, call_id, box)
    except Exception as exc:  # noqa: BLE001 — 뒤받침이 못 봐도 뒤 확인·요약은 이어 간다
        logger.warning("통화 뒤: 수신 거부를 다시 보지 못했습니다 (%s)", _kind(exc))
        return
    if missed:
        await box.call("mark_do_not_contact", {"reason": HEARD_OPT_OUT})  # 도구는 예외를 내지 않는다(사건도 도구 길 그대로)


def _opt_out_missed(call_id: int, box: Toolbox) -> bool:
    """상대가 수신 거부를 말했는데 그 번호(도구와 같은 box.number)가 아직 수신 거부가 아닌가."""
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        if row is None:
            return False
        heard = any(line.get("role") == "peer" and door.is_stop(line["text"], single_words=False) for line in _lines(row))
        number = box.number(session) if heard else None
        return number is not None and not outreach.is_do_not_contact(session, number)


# ── ① 뒤 확인 ──────────────────────────────────────────────────────


def _lines(row: OutreachCall) -> list[dict]:
    raw = row.transcript_json if isinstance(row.transcript_json, list) else []
    return [line for line in raw if isinstance(line, dict) and isinstance(line.get("text"), str)]


def _review_input(session: Session, row: OutreachCall, box: Toolbox | None) -> tuple[list[dict], Scope, str]:
    if box is not None:
        return list(box.results), box.scope, box.caller_class
    if row.direction == "out" and row.schedule_id is not None and row.contact_id is not None:
        try:
            return [], door.outbound_scope(session, row.schedule_id, row.contact_id), "outbound"
        except (contacts.NotFound, ValueError):
            pass
    known = row.caller_class if row.caller_class in get_args(CallerClass) else "unknown"
    return [], _CLOSED, known


def _check(call_id: int, box: Toolbox | None) -> dict | None:
    """completed 인 줄이면 뒤 확인을 하고(check 가 commit), 그 뒤의 줄로 요약 자료를 만든다. 아니면 None."""
    with _db() as session:
        row = session.get(OutreachCall, call_id)
        if row is None or row.status != "completed":
            return None
        lines = _lines(row)
        ended = as_utc(row.ended_at) if row.ended_at is not None else _now()
        tool_results, scope, caller_class = _review_input(session, row, box)
        try:
            review.check(session, Ref("call", call_id), said=[line["text"] for line in lines if line.get("role") == "agent"],
                         peer_lines=[line["text"] for line in lines if line.get("role") == "peer"],
                         tool_results=tool_results, scope=scope, caller_class=caller_class, now=ended)
        except Exception as exc:  # noqa: BLE001 — 판정이 없음 = 깨끗하지 않음(보고 한 줄)
            session.rollback()
            logger.warning("통화 뒤: 뒤 확인을 마치지 못했습니다 (%s)", _kind(exc))
            _unchecked(session, call_id)
        session.expire_all()
        row = session.get(OutreachCall, call_id)
        return None if row is None else _material(session, row, ended)


def _unchecked(session: Session, call_id: int) -> None:
    """뒤 확인이 판정을 내지 못한 통화에 review 보고 한 줄(이미 있으면 그대로) — review.check 가 남기는 것과 같은 꼴."""
    try:
        row = session.get(OutreachCall, call_id)
        if row is None or session.scalar(select(ContactReport.id).filter_by(kind=review.REVIEW_KIND, call_id=call_id)
                                         .limit(1)) is not None:
            return
        outreach.add_report(session, schedule_id=row.schedule_id, medium="call", contact_id=row.contact_id,
                            kind=review.REVIEW_KIND, text=hide_phones(review.REVIEW_TEXT), call_id=call_id)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("통화 뒤: 확인 필요 보고를 남기지 못했습니다 (%s)", _kind(exc))


# ── ② 요약 자료 ─────────────────────────────────────────────────────


def _hide(text: object, limit: int = FIELD_CHARS) -> str:
    return hide_phones(text if isinstance(text, str) else "")[:limit]


def _day(at: datetime) -> str:
    day = as_utc(at).astimezone(hours.KST).date()
    return f"{day.isoformat()} ({_WEEKDAYS[day.weekday()]})"


def _peer(session: Session, row: OutreachCall) -> dict | None:
    """상대의 이름·담당·협력사(번호 칸은 읽지 않는다)."""
    if row.schedule_id is None or row.contact_id is None:
        return None
    try:
        who = contacts.get_contact(session, row.schedule_id, row.contact_id)
    except contacts.NotFound:
        return None
    try:
        firm = contacts.get_company(session, row.schedule_id, who.company_id).name
    except contacts.NotFound:
        firm = ""
    return {"이름": _hide(who.name), "담당": _hide(who.role_title), "협력사": _hide(firm)}


def _answers(row: OutreachCall) -> list[dict]:
    raw = row.answers_json if isinstance(row.answers_json, list) else []
    return [{"질문": _hide(item.get("question")), "답": _hide(item.get("answer")), "근거 말": _hide(item.get("quote")),
             "확인": VERIFIED if item.get("quote_found") is True else UNVERIFIED}
            for item in raw[:MAX_ANSWERS] if isinstance(item, dict)]


def _transcript(lines: list[dict]) -> tuple[list[dict], bool]:
    out, used = [], 0
    for line in lines[:MAX_LINES]:
        said = _hide(line["text"], LINE_CHARS)
        if used + len(said) > TEXT_CHARS:
            return out, True
        used += len(said)
        t = line.get("t")
        out.append({"쪽": "우리" if line.get("role") == "agent" else "상대",
                    "초": round(float(t), 1) if isinstance(t, int | float) else None, "말": said})
    return out, len(lines) > MAX_LINES or any(len(hide_phones(line["text"])) > LINE_CHARS for line in lines[:MAX_LINES])


def _material(session: Session, row: OutreachCall, ended: datetime) -> dict:
    record = session.get(ScheduleRecord, row.schedule_id) if row.schedule_id is not None else None
    questions = row.questions_json if isinstance(row.questions_json, list) else []
    lines, cut = _transcript(_lines(row))
    return {
        "오늘": _day(_now()),
        "통화한 날": _day(ended),
        "현장": _hide(record.name if record is not None else ""),
        "상대": _peer(session, row),
        "방향": "우리가 건 통화" if row.direction == "out" else "받은 통화",
        "통화 언어": languages.name(languages.call_language(row.language)),  # 실제로 건 언어 — 받아쓰기는 그대로, 요약은 한국어
        "목적": _hide(row.purpose),
        "물어볼 것": [_hide(q) for q in questions[:MAX_QUESTIONS]],
        "답": _answers(row),
        "받아쓰기": lines,
        "받아쓰기 잘림": cut,
    }


def _user_text(data: dict) -> str:
    # 자료 안의 < > 는 JSON 이스케이프로 — 상대 말이 </자료> 를 써도 자료 밖으로 나오지 않는다
    block = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<자료>{block}</자료>"


async def _ask(data: dict) -> LlmReply | None:
    messages = [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": _user_text(data)}]
    with _db() as session:  # 읽기만(연결·배정) — 쥔 쓰기가 없다
        try:
            return await client_for(session).chat("normal", messages, json_schema=SCHEMA, timeout_s=TIMEOUT_S,
                                                  max_tokens=MAX_TOKENS)
        except LlmNotReady:
            logger.warning("통화 뒤: LLM 연결이 없어 요약을 만들지 않았습니다")
        except LlmFailed:
            pass  # 실패 종류는 LlmClient 가 이미 남겼다(내용 없이)
    return None


# ── ③ 저장 ─────────────────────────────────────────────────────────


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value).strip()
    return text if len(text) <= limit else None


def _usable(reply: LlmReply) -> tuple[str, str] | None:
    parsed = reply.parsed if isinstance(reply.parsed, dict) else {}
    summary, result = _text(parsed.get("summary_ko"), SUMMARY_CHARS), _text(parsed.get("result"), RESULT_CHARS)
    if not summary or result is None or not languages.is_korean(summary) or not languages.is_korean(result):
        return None  # 요약·결과는 한국어만(Task 100 — 영어 통화라도 영어 요약은 담당자가 읽을 글이 아니다)
    return summary, result or NO_RESULT


def _store(call_id: int, reply: LlmReply) -> None:
    """쓸 수 있는 답이면 summary_ko·result_proposed(가린 글)를 completed 인 줄에만. 답이 왔으면 사용량은 늘 센다."""
    usable = _usable(reply)
    if usable is None:
        logger.warning("통화 뒤: 모델 답을 요약으로 쓸 수 없습니다")
    try:
        with _db() as session:
            if usable is not None:
                summary, result = usable
                session.execute(update(OutreachCall).where(OutreachCall.id == call_id, OutreachCall.status == "completed")
                                .values(summary_ko=hide_phones(summary), result_proposed=hide_phones(result))
                                .execution_options(synchronize_session=False))
            outreach.add_usage(session, "summary", ref=("call", call_id), model=reply.model,
                               input_tokens=reply.usage.input_tokens, output_tokens=reply.usage.output_tokens,
                               cost=reply.usage.cost)
            session.commit()
    except Exception as exc:  # noqa: BLE001 — 요약을 못 적어도 통화 기록은 그대로
        logger.warning("통화 뒤: 요약을 적지 못했습니다 (%s)", _kind(exc))
