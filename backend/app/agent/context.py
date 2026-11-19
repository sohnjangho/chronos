"""에이전트에게 보내는 메시지 조립: 지시문 + 분야 지식 + 지금 상황(화면·일정 요약·조건 수) + 대화 기록.

대화 기록은 마지막 HISTORY_LIMIT 개 메시지만 본다(요약은 하지 않는다). 도구 호출과 결과는 짝을 맞춰 보낸다.
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.domains.loader import domains, levels_prompt, load
from app.harness.conditions import read_conditions
from app.store.chats import recent_messages
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound
from app.store.schedules import load as load_schedule
from app.store.tables import ChatMessage, User
from app.store.view import view_data
from app.tools.context import SCHEDULE_NOT_FOUND_MESSAGE
from app.tools.registry import ToolResult

PROMPT = Path(__file__).parent / "prompts" / "system.md"
HISTORY_LIMIT = 30  # 모델이 보는 지난 메시지 수(이번 사용자 메시지 포함)
RESULT_LIMIT = 4000  # 도구 결과 글의 길이 한도
CUT_NOTE = "\n(뒤는 생략)"
NOT_RUN = json.dumps({"error": "실행하지 않았습니다(턴이 중간에 멈췄습니다)."}, ensure_ascii=False)
_LAYERS = (("base", "기본"), ("domain", "분야"), ("mine", "내 규칙"), ("input", "입력"))
SEOUL = ZoneInfo("Asia/Seoul")
_WEEKDAYS = "월화수목금토일"


@dataclass(frozen=True)
class UiContext:
    """화면 맥락: 열린 프로그램, 다루는 일정, 고른 액티비티."""

    program: str | None = None
    schedule_id: int | None = None
    selected_activity: str | None = None


def today() -> date:
    """오늘(서울). 시험은 이 함수를 바꿔 끼운다."""
    return datetime.now(SEOUL).date()


def today_text(day: date) -> str:
    """'2026-11-20 (금)'."""
    return f"{day.isoformat()} ({_WEEKDAYS[day.weekday()]})"


def system_prompt() -> str:
    """prompts/system.md 에 오늘 날짜·분야 목록·정밀도 정의·분야 지식을 넣은 지시문(턴마다 새로 만든다)."""
    packs = [load(d) for d in domains()]
    return (
        PROMPT.read_text(encoding="utf-8")
        .replace("{{today}}", today_text(today()))
        .replace("{{domains}}", ", ".join(f"{p.id}({p.name})" for p in packs))
        .replace("{{levels}}", levels_prompt())
        .replace("{{packs}}", "\n\n".join(p.prompt() for p in packs))
    )


def build_context(session: Session, user: User, chat_session_id: int, ui: UiContext) -> list[dict]:
    """LLM 에 보낼 메시지: system(지시문 + 지금 상황) 하나 뒤에 마지막 30개 대화 메시지."""
    system = system_prompt() + "\n\n" + situation(session, user, ui)
    rows = recent_messages(session, chat_session_id, HISTORY_LIMIT)
    return [{"role": "system", "content": system}, *history(rows)]


# ── 지금 상황 ───────────────────────────────────────────────────────


def situation(session: Session, user: User, ui: UiContext) -> str:
    role = "관리자" if user.role == "admin" else "일반 사용자"
    lines = ["## 지금 상황", f"- 사용자: {user.name} ({role})", f"- 열린 프로그램: {ui.program or '없음'}"]
    return "\n".join(lines + _schedule_lines(session, ui))


def _schedule_lines(session: Session, ui: UiContext) -> list[str]:
    selected = [f"- 고른 액티비티: {ui.selected_activity}"] if ui.selected_activity else []
    if ui.schedule_id is None:
        return ["- 대상 일정: 없음", *selected]
    try:
        view = view_data(session, ui.schedule_id)
        _, stored, _ = load_schedule(session, ui.schedule_id, view["version"])
    except NotFound:
        return [f"- 대상 일정: #{ui.schedule_id} 일정을 읽을 수 없습니다: {SCHEDULE_NOT_FOUND_MESSAGE}", *selected]
    except ScheduleError as e:
        return [f"- 대상 일정: #{ui.schedule_id} 일정을 읽을 수 없습니다: {schedule_error_message(e)}", *selected]
    lines = [_schedule_line(view), _condition_line(stored)]
    if ui.selected_activity:
        lines.append(_activity_line(view, ui.selected_activity))
    return lines


def _schedule_line(view: dict) -> str:
    s = view["summary"]
    return (
        f"- 대상 일정: #{view['id']} {view['name']} · 분야 {view['domain']} · 정밀도 {view['level']}"
        f" · 버전 {view['version']} · 준공 {view['finish']} · 액티비티 {len(view['activities'])}개"
        f" · 크리티컬 {s['critical_count']}개 · 음수 여유 {s['negative_float_count']}개 · 늦음 {s['warning_count']}개"
    )


def _condition_line(stored: list) -> str:
    conditions, invalid = read_conditions(stored)
    layers = Counter(c.layer for c in conditions)
    by_layer = " · ".join(f"{name} {layers[layer]}" for layer, name in _LAYERS)
    line = (
        f"- 조건 {len(stored)}개 ({by_layer}) · 꺼짐 {sum(not c.enabled for c in conditions)}개"
        f" · 자동 점검 안 됨 {sum(not c.checkable for c in conditions)}개"
    )
    return line + (f" · 읽을 수 없음 {len(invalid)}개" if invalid else "")


def _activity_line(view: dict, activity_id: str) -> str:
    a = next((x for x in view["activities"] if x["id"] == activity_id), None)
    if a is None:
        return f"- 고른 액티비티: {activity_id} (일정에 없음)"
    critical = "크리티컬" if a["critical"] else "크리티컬 아님"
    return f"- 고른 액티비티: {a['id']} {a['name']} · 시작 {a['es']} · 끝 {a['ef']} · 여유 {a['tf']}일 · {critical}"


# ── 대화 기록 ───────────────────────────────────────────────────────


def submission_text(content: dict) -> str:
    """질문지 제출 메시지를 모델이 읽을 한국어로."""
    lines = [f"질문지 제출됨 (질문지 {content['questionnaire_id']}).", "답한 것:"]
    lines += [f"- {a['question']}: {a['label']}" for a in content["answers"]] or ["- (없음)"]
    lines.append("답하지 않아 가정한 것:")
    lines += [f"- {a['question']}: {a['assumption']}" for a in content["assumed"]] or ["- (없음)"]
    return "\n".join(lines)


def arguments_text(arguments: dict | None, raw: str | None) -> str:
    """도구 호출 인자를 LLM 에 다시 보낼 글: 받은 원문 → 인자 dict 의 JSON → "{}". "null" 은 보내지 않는다."""
    if raw is not None:
        text = raw
    elif isinstance(arguments, dict):
        text = json.dumps(arguments, ensure_ascii=False)
    else:
        text = "{}"
    return "{}" if text.strip() == "null" else text


def result_text(result: ToolResult) -> str:
    """도구 결과를 LLM 에 보낼 JSON 글. 4,000자를 넘으면 자르고 "(뒤는 생략)" 을 붙인다."""
    text = json.dumps(result.output if result.ok else {"error": result.error}, ensure_ascii=False)
    return text if len(text) <= RESULT_LIMIT else text[:RESULT_LIMIT] + CUT_NOTE


def wire(role: str, content: dict) -> dict:
    """저장된 메시지 하나(role, content_json) → LLM 메시지."""
    if role == "user":
        if content.get("kind") == "questionnaire_submitted":
            return {"role": "user", "content": submission_text(content)}
        return {"role": "user", "content": content.get("text", "")}
    if role == "tool":
        return {"role": "tool", "tool_call_id": content["tool_call_id"], "content": content["content"]}
    calls = content.get("tool_calls") or []
    if not calls:
        return {"role": "assistant", "content": content.get("text", "")}
    return {
        "role": "assistant",
        "content": content.get("text") or None,
        "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in calls
        ],
    }


def _not_run(call_ids: list[str]) -> list[dict]:
    return [{"role": "tool", "tool_call_id": i, "content": NOT_RUN} for i in call_ids]


def history(rows: list[ChatMessage]) -> list[dict]:
    """저장된 메시지 → LLM 메시지. 앞의 호출이 없는 도구 결과(창에서 잘린 것)는 버리고,
    결과가 없는 호출(턴이 중간에 멈춘 것)에는 "실행하지 않았습니다" 결과를 채운다."""
    out: list[dict] = []
    pending: list[str] = []
    for row in rows:
        message = wire(row.role, row.content_json)
        if message["role"] == "tool":
            if message["tool_call_id"] in pending:
                pending.remove(message["tool_call_id"])
                out.append(message)
            continue
        out += _not_run(pending)
        out.append(message)
        pending = [c["id"] for c in message.get("tool_calls", [])]
    return out + _not_run(pending)
