"""에이전트에게 보내는 메시지 조립: 지시문 + 분야 지식 + 지금 상황(화면·일정 요약·조건 수·이 대화에 붙인 파일·날짜 도우미)
+ 대화 기록.

대화 기록은 마지막 HISTORY_LIMIT 개 메시지만 본다(요약은 하지 않는다). 도구 호출과 결과는 짝을 맞춰 보낸다.
화면 사건(role "event")은 모델에 보내지 않는다. 날짜 도우미의 날짜는 모두 코드가 계산한다.
"""

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.domains.loader import domains, levels_prompt, load
from app.harness.conditions import read_conditions
from app.store import files as file_store
from app.store import my_rules
from app.store.chats import recent_messages
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound
from app.store.schedules import load as load_schedule
from app.store.tables import ChatMessage, FileRow, User
from app.store.view import view_data
from app.tools.context import SCHEDULE_NOT_FOUND_MESSAGE
from app.tools.registry import ToolResult

logger = logging.getLogger(__name__)

PROMPT = Path(__file__).parent / "prompts" / "system.md"
GUIDES_DIR = PROMPT.parent / "guides"  # 기능마다 지시문 조각 하나(<기능>.md). "_" 로 시작하는 이름은 붙이지 않는다
HISTORY_LIMIT = 30  # 모델이 보는 지난 메시지 수(이번 사용자 메시지 포함)
RESULT_LIMIT = 4000  # 도구 결과 글의 길이 한도
CUT_NOTE = "\n(뒤는 생략)"
NOT_RUN = json.dumps({"error": "실행하지 않았습니다(턴이 중간에 멈췄습니다)."}, ensure_ascii=False)
_LAYERS = (("base", "기본"), ("domain", "분야"), ("mine", "내 규칙"), ("input", "입력"))
RULES_SHOWN, RULE_TEXT_LIMIT = 10, 60  # 대화 맥락에 보일 내 규칙 수·글 길이
FILES_SHOWN, SUMMARY_LIMIT = 20, 120  # 「이 대화에 붙인 파일」 줄의 파일 수(최근 것)·한 줄 요약 길이
NAME_LIMIT = REASON_LIMIT = 60  # 그 줄의 파일 이름·까닭 길이
AXIS_ORDER = ("종류", "공종", "현장", "시기", "출처")  # 분류 축 차례(설계 5-2). 그 밖의 축은 뒤에
FILE_STATUS = {"received": "읽는 중", "extracted": "읽음", "indexed": "저장됨", "classified": "분류됨", "failed": "실패"}
RULE_TITLE_PREFIX = "내 규칙 저장 — "  # rules.propose 가 만드는 승인 건 제목의 앞(tools/out/propose_rule.TITLE_PREFIX)
SEOUL = ZoneInfo("Asia/Seoul")
_WEEKDAYS = "월화수목금토일"
# "11월 30일", "2027년 11월 30일", "내년 3월 2일" (월·일이 다 있을 때만. "내년 3월" 은 계산하지 않는다)
_MONTH_DAY = re.compile(r"(?:(\d{4})\s*년\s*|(올해|금년|내년|명년|내후년)\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_YEAR_WORDS = {"올해": 0, "금년": 0, "내년": 1, "명년": 1, "내후년": 2}
_LEAP_SEARCH_YEARS = 8  # 2월 29일은 다음 윤년까지 찾는다


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


def _resolve(year: str | None, word: str | None, month: int, day: int, base: date) -> date | None:
    """연도가 적혀 있으면 그 해, '내년' 같은 말이면 그 해, 없으면 오늘 이후 가장 가까운 날. 없는 날이면 None."""
    if year or word:
        try:
            return date(int(year) if year else base.year + _YEAR_WORDS[word], month, day)
        except ValueError:
            return None
    for y in range(base.year, base.year + _LEAP_SEARCH_YEARS + 1):
        try:
            found = date(y, month, day)
        except ValueError:
            continue
        if found >= base:
            return found
    return None


def month_days(text: str, base: date) -> list[tuple[str, date | None]]:
    """글 속 'M월 D일'(앞에 연도나 '올해·내년·내후년' 이 붙을 수 있음)마다 (그 말, 코드가 정한 날짜)."""
    return [
        (m.group(0), _resolve(m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), base))
        for m in _MONTH_DAY.finditer(text)
    ]


def _date_texts(rows: list[ChatMessage]) -> list[str]:
    """날짜 도우미가 읽을 글: 마지막 사용자 글. 질문지 제출이면 그 답과, 그 앞의 마지막 사용자 글."""
    texts: list[str] = []
    for row in reversed(rows):
        if row.role != "user":
            continue
        content = row.content_json
        if content.get("kind") != "questionnaire_submitted":  # 글, 또는 승인 거부(그 이유 글)
            return [*texts, content.get("text") or content.get("note", "")]
        if not texts:
            texts = [f"{a['value']} {a['label']}" for a in content["answers"]]
    return texts


def date_helper(rows: list[ChatMessage], base: date) -> list[str]:
    """'## 날짜 도우미' 줄들: 오늘, 올해·내년, 사용자 글 속 'M월 D일' 의 온전한 날짜(모두 코드가 계산)."""
    lines = [
        "## 날짜 도우미 (코드가 계산했다. 날짜는 여기 있는 것을 그대로 옮겨 쓴다)",
        f"- 오늘: {today_text(base)}",
        f"- 올해: {base.year}년 · 내년: {base.year + 1}년",
    ]
    seen: set[str] = set()
    for text in _date_texts(rows):
        for phrase, day in month_days(text, base):
            if phrase not in seen:
                seen.add(phrase)
                lines.append(f"- '{phrase}' → {today_text(day) if day else '없는 날짜입니다'}")
    return lines


_GUIDE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("delay", ("지연", "늦어", "밀렸", "밀림", "늦음"), ("delays",)),
    ("shorten", ("만회", "단축", "앞당", "압축", "병행", "복구"), ("compare",)),
    ("actuals", ("실적", "진도", "공정률", "착수", "완료", "data date"), ("progress", "schedule-table")),
    ("scenario", ("복사본", "만약에", "시나리오", "비교"), ("compare",)),
    ("rules", ("규칙", "조건", "제약", "크레인", "금지"), ("conditions",)),
    ("evidence", ("근거", "기준", "법규", "법령", "인허가", "검색", "납기", "출처"), ()),
    ("weather", ("날씨", "비", "우천", "동절기", "기온", "장마", "한중", "기상", "예보"), ()),
    ("files", ("파일", "자료", "시방서", "사진", "도면", "첨부", "문서"), ("library",)),
    ("import", ("가져오", "엑셀", "xlsx", "csv", "초안", "공정표"), ("library",)),
    ("visual", ("그림", "차트", "보고서", "시각화", "그래프"), ("progress", "compare", "delays")),
)


def select_guides(user_text: str, ui: UiContext, has_files: bool) -> list[str]:
    """사용자 요청·열린 화면·첨부 파일에 맞는 가이드 이름만 동적으로 고른다(맞는 것이 없으면 전체)."""
    q = (user_text or "").lower()
    prog = ui.program or ""
    picked: list[str] = []
    for name, keywords, programs in _GUIDE_RULES:
        if (has_files and name in ("files", "import")) or (prog in programs) or any(k in q for k in keywords):
            picked.append(name)
    if not picked:
        return [f.stem for f in sorted(GUIDES_DIR.glob("*.md")) if not f.name.startswith("_")]
    return picked


def system_prompt(guide_names: list[str] | None = None) -> str:
    """prompts/system.md 에 분야 목록·정밀도 정의·분야 지식을 넣고, 끝에 지시문 조각을 붙인다.
    guide_names 가 None 이면 전체, 목록이면 고른 가이드만 동적으로 붙인다."""
    packs = [load(d) for d in domains()]
    base = (
        PROMPT.read_text(encoding="utf-8")
        .replace("{{domains}}", ", ".join(f"{p.id}({p.name})" for p in packs))
        .replace("{{levels}}", levels_prompt())
        .replace("{{packs}}", "\n\n".join(p.prompt() for p in packs))
    )
    all_guides = sorted(f for f in GUIDES_DIR.glob("*.md") if not f.name.startswith("_"))
    selected = all_guides if guide_names is None else [f for f in all_guides if f.stem in set(guide_names)]
    return "\n\n".join([base, *(f.read_text(encoding="utf-8") for f in selected)])


def compact_older_note(session: Session, chat_session_id: int, recent_rows: list[ChatMessage]) -> str:
    """최근 HISTORY_LIMIT 개 밖으로 밀린 옛 사용자 요청들을 한 줄씩 압축 요약한다."""
    recent_ids = {r.id for r in recent_rows}
    older = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session_id, ChatMessage.role == "user")
            .order_by(ChatMessage.id)
        )
    )
    dropped = [r for r in older if r.id not in recent_ids]
    if not dropped:
        return ""
    bullets: list[str] = []
    for r in dropped[-10:]:
        c = r.content_json or {}
        if c.get("kind") == "text" and c.get("text"):
            bullets.append(f"- 사용자 요청: {_clip(str(c['text']).strip(), 80)}")
        elif c.get("kind") == "questionnaire_submitted":
            bullets.append(f"- 질문지 #{c.get('questionnaire_id')} 제출")
        elif c.get("kind") == "approval_rejected":
            bullets.append(f"- 승인 거부 재요청: {_clip(str(c.get('title', '')), 60)}")
    if not bullets:
        return ""
    return "## 이전 대화 요약 (압축됨)\n" + "\n".join(bullets)


def build_context(
    session: Session, user: User, chat_session_id: int, ui: UiContext, *, history_limit: int = HISTORY_LIMIT
) -> list[dict]:
    """LLM 에 보낼 메시지: system(동적 가이드 + 지금 상황 + 붙인 파일 + 이전 대화 압축 + 날짜 도우미) + 최근 N개 대화."""
    rows = recent_messages(session, chat_session_id, history_limit)
    helper = "\n".join(date_helper(rows, today()))
    attached = files_line(session, chat_session_id)
    older = compact_older_note(session, chat_session_id, rows)
    last_text = " ".join(_date_texts(rows))
    guides = select_guides(last_text, ui, has_files=attached is not None)
    now = situation(session, user, ui) + (f"\n{attached}" if attached else "") + (f"\n\n{older}" if older else "")
    system = f"{system_prompt(guides)}\n\n{now}\n\n{helper}"
    return [{"role": "system", "content": system}, *history(rows)]


# ── 지금 상황 ───────────────────────────────────────────────────────


def situation(session: Session, user: User, ui: UiContext) -> str:
    role = "관리자" if user.role == "admin" else "일반 사용자"
    lines = ["## 지금 상황", f"- 사용자: {user.name} ({role})", f"- 열린 프로그램: {ui.program or '없음'}"]
    return "\n".join(lines + _schedule_lines(session, ui))


def _schedule_lines(session: Session, ui: UiContext) -> list[str]:
    selected = [f"- 고른 액티비티: {ui.selected_activity}"] if ui.selected_activity else []
    if ui.schedule_id is None:
        return ["- 대상 일정: 없음", _rules_line(session, None, None), *selected]
    try:
        view = view_data(session, ui.schedule_id)
        _, stored, _ = load_schedule(session, ui.schedule_id, view["version"])
    except NotFound:
        return [f"- 대상 일정: #{ui.schedule_id} 일정을 읽을 수 없습니다: {SCHEDULE_NOT_FOUND_MESSAGE}", *selected]
    except ScheduleError as e:
        return [f"- 대상 일정: #{ui.schedule_id} 일정을 읽을 수 없습니다: {schedule_error_message(e)}", *selected]
    except Exception as exc:  # noqa: BLE001 — 요약을 못 만들어도 턴은 이어 간다(종류만 남김)
        logger.warning("일정 요약 실패: schedule=%s (%s)", ui.schedule_id, type(exc).__name__)
        return [f"- 대상 일정: #{ui.schedule_id} 일정을 읽을 수 없습니다.", *selected]
    lines = [_schedule_line(view), _condition_line(stored), _rules_line(session, view["domain"], ui.schedule_id)]
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


def _rules_line(session: Session, domain: str | None, schedule_id: int | None) -> str:
    """켜진 내 규칙: 일정이 있으면 그 분야의 분야 범위 + 그 일정 범위, 없으면 모든 분야 범위. 10개·60자까지."""
    rules = my_rules.for_context(session, domain=domain, schedule_id=schedule_id)
    if not rules:
        return "- 내 규칙: 없음"
    texts = "; ".join(c.text[:RULE_TEXT_LIMIT] for c in rules[:RULES_SHOWN])
    more = f" 외 {len(rules) - RULES_SHOWN}개" if len(rules) > RULES_SHOWN else ""
    return f"- 내 규칙 {len(rules)}개: {texts}{more}"


def _activity_line(view: dict, activity_id: str) -> str:
    a = next((x for x in view["activities"] if x["id"] == activity_id), None)
    if a is None:
        return f"- 고른 액티비티: {activity_id} (일정에 없음)"
    critical = "크리티컬" if a["critical"] else "크리티컬 아님"
    return f"- 고른 액티비티: {a['id']} {a['name']} · 시작 {a['es']} · 끝 {a['ef']} · 여유 {a['tf']}일 · {critical}"


def files_line(session: Session, chat_session_id: int) -> str | None:
    """'- 이 대화에 붙인 파일: #12 시방서.pdf (pdf · 시방서·골조 · 분류됨) "요약" | …'. 붙인 차례로 최근 FILES_SHOWN 개,
    넘으면 끝에 「외 n개」. 지운 파일은 '#12 시방서.pdf (지워짐)'. 붙인 파일이 없으면 None."""
    rows = file_store.session_files(session, chat_session_id)
    if not rows:
        return None
    shown = [_file_text(session, f) for f in rows[-FILES_SHOWN:]]
    more = [f"외 {len(rows) - FILES_SHOWN}개"] if len(rows) > FILES_SHOWN else []
    return "- 이 대화에 붙인 파일: " + " | ".join(shown + more)


def _axis_rank(axis: str) -> int:
    return AXIS_ORDER.index(axis) if axis in AXIS_ORDER else len(AXIS_ORDER)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _file_text(session: Session, f: FileRow) -> str:
    head = f"#{f.id} {_clip(f.name, NAME_LIMIT)}"
    if f.deleted_at is not None:
        return f"{head} (지워짐)"
    axes = file_store.axes_of(session, f.id)
    values = "·".join(v for axis in sorted(axes, key=_axis_rank) for v in axes[axis])
    status = FILE_STATUS.get(f.status, f.status) + (f" — {_clip(f.reason, REASON_LIMIT)}" if f.reason else "")
    text = f"{head} ({' · '.join(p for p in (f.kind, values, status) if p)})"
    summary = (f.summary or "").strip()
    return f'{text} "{_clip(summary, SUMMARY_LIMIT)}"' if summary else text


# ── 대화 기록 ───────────────────────────────────────────────────────


def submission_text(content: dict) -> str:
    """질문지 제출 메시지를 모델이 읽을 한국어로."""
    lines = [f"질문지 제출됨 (질문지 {content['questionnaire_id']}).", "답한 것:"]
    lines += [f"- {a['question']}: {a['label']}" for a in content["answers"]] or ["- (없음)"]
    lines.append("답하지 않아 가정한 것:")
    lines += [f"- {a['question']}: {a['assumption']}" for a in content["assumed"]] or ["- (없음)"]
    return "\n".join(lines)


def rejection_text(content: dict) -> str:
    """승인 거부(다시 짜기) 메시지를 모델이 읽을 한국어로. 내 규칙 건(제목이 「내 규칙 저장 — 」)은 rules__propose 로 다시 낸다."""
    head = [f"승인 요청이 거부됨 (승인 {content['approval_id']}: {content['title']}).", f"거부 이유: {content['note']}"]
    if str(content.get("title", "")).startswith(RULE_TITLE_PREFIX):
        return "\n".join([*head, "내 규칙 제안이었다. 이 이유를 반영해 rules__propose 로 다시 제안한다(저장은 승인 뒤)."])
    return "\n".join([
        *head,
        "이 이유를 반영해 다시 짠 뒤 out__submit_change 로 다시 낸다.",
        "일정 고침이면 일정을 다시 읽고 지금 버전을 base_version 으로 쓴다.",
    ])


def arguments_text(arguments: dict | None, raw: str | None) -> str:
    """도구 호출 인자를 LLM 에 다시 보낼 글: 받은 원문 → 인자 dict 의 JSON → "{}". "null" 은 보내지 않는다."""
    if raw is not None:
        text = raw
    elif isinstance(arguments, dict):
        text = json.dumps(arguments, ensure_ascii=False)
    else:
        text = "{}"
    return "{}" if text.strip() == "null" else text


def result_text(result: ToolResult, *, limit: int = RESULT_LIMIT) -> str:
    """도구 결과를 LLM 에 보낼 JSON 글. limit 자를 넘으면 자르고 "(뒤는 생략)" 을 붙인다."""
    text = json.dumps(result.output if result.ok else {"error": result.error}, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + CUT_NOTE


def wire(role: str, content: dict) -> dict:
    """저장된 메시지 하나(role, content_json) → LLM 메시지."""
    if role == "user":
        if content.get("kind") == "questionnaire_submitted":
            return {"role": "user", "content": submission_text(content)}
        if content.get("kind") == "approval_rejected":
            return {"role": "user", "content": rejection_text(content)}
        return {"role": "user", "content": _with_files(content.get("text", ""), content.get("files"))}
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


def _with_files(text: str, refs: list[dict] | None) -> str:
    """사용자 글 끝에 그 메시지에 붙인 파일(id·이름)을 적는다. 그림 자체는 그 턴에만 보낸다(app.agent.image_turn)."""
    if not refs:
        return text
    return f"{text}\n(붙인 파일: {', '.join(f'#{r['file_id']} {r['name']}' for r in refs)})"


def _not_run(call_ids: list[str]) -> list[dict]:
    return [{"role": "tool", "tool_call_id": i, "content": NOT_RUN} for i in call_ids]


def history(rows: list[ChatMessage]) -> list[dict]:
    """저장된 메시지 → LLM 메시지. 앞의 호출이 없는 도구 결과(창에서 잘린 것)는 버리고,
    결과가 없는 호출(턴이 중간에 멈춘 것)에는 "실행하지 않았습니다" 결과를 채운다."""
    out: list[dict] = []
    pending: list[str] = []
    for row in rows:
        if row.role == "event":  # 화면 사건은 모델에 보내지 않는다(호출·결과 짝도 끊지 않는다)
            continue
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
