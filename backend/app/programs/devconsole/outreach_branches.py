"""개발 콘솔 ②(Task 109): 구조·흐름도의 연락 가지 · 도구 목록의 연락 도구 · 글 쪽 모델 사용량. 읽기만 한다.

- **가지는 기록에서만 켜진다** — 설정(위임 권한)이나 도구 등록 여부를 읽지 않는다.
  대화 턴: 실행 걸음(WorkflowStep)의 도구 이름·상태·결과의 outcome. 연락 하나: 그 줄의 하네스 사건과 답 줄의 reply_to_id.
- 흐름도 마디(들어오는 문 → 도구 → 뒤 확인 → 나가는 문 → 통로)는 harness.types 의 묶음으로 사건을 모은다. 묶음·이름은
  상수에서 꺼낸다(사건 이름 글자를 적지 않는다 — outreach_view 와 같은 규칙). 판정 글은 시간표 줄이 이미 가진 것을 쓴다.
- 하네스 도구 12개는 등록부 도구가 아니다: 이름·설명·인자 꼴은 toolsets.tool_defs, 등급·매체는 toolsets.for_class 에서
  읽는다(표를 옮겨 적지 않는다). 끄기 길이 없다(toggle false).
"""

from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.outreach.harness import toolsets
from app.outreach.harness.types import (
    ADMIT_REASONS,
    DELIVERY_UPDATES,
    EVENT_GROUPS,
    FIXED_DETAILS,
    GATE_NOTES,
    GATE_RULES,
    REVIEW_FLAGS,
    TOOL_REFUSALS,
    CallerClass,
    Medium,
)
from app.programs.devconsole.schemas import (
    HarnessItem,
    OutreachFlowNode,
    OutreachFlowVerdict,
    TextModelUsageOut,
)
from app.store.outreach_usage import KindUsage, UsageSummary
from app.store.tables_outreach import OutreachMessage

# ── 대화 턴의 가지 ──────────────────────────────────────────────────

LOOKUP_TOOL = "contacts.list"
DRAFT_TOOLS = frozenset({"notify.draft_message", "notify.draft_call"})
SEND_TOOLS = frozenset({"notify.send_message", "notify.place_call"})  # 위임 도구(Task 81)
PASSED = frozenset({"accepted", "queued", "scheduled"})  # 위임 발송이 문을 지나간 판정 코드 — 그 밖의 코드는 막힘


def step_flags(tool: str, status: str, out: dict) -> list[str]:
    """실행 걸음 하나가 보여 주는 연락 가지. 연락처 조회는 걸음이 있으면, 초안은 끝났으면, 위임 발송은 끝났고 결과에
    판정 코드(outcome)가 있으면."""
    if tool == LOOKUP_TOOL:
        return ["contact_lookup"]
    if status != "done":
        return []
    if tool in DRAFT_TOOLS:
        return ["outreach_draft"]
    outcome = out.get("outcome")
    if tool in SEND_TOOLS and isinstance(outcome, str):
        return ["outreach_delegated" if outcome in PASSED else "outreach_blocked"]
    return []


# ── 연락 하나의 흐름도 ──────────────────────────────────────────────

ADMIT_RULE = next(rule for rule, codes in FIXED_DETAILS.items() if codes is ADMIT_REASONS)
UPDATE_RULE = next(rule for rule, codes in FIXED_DETAILS.items() if codes is DELIVERY_UPDATES)
FLOW: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("inbound", "들어오는 문", frozenset({EVENT_GROUPS[ADMIT_RULE]})),
    ("tool", "도구", frozenset({EVENT_GROUPS[min(TOOL_REFUSALS)]})),
    ("post_check", "뒤 확인", frozenset({EVENT_GROUPS[min(REVIEW_FLAGS)]})),
    ("gate", "나가는 문", frozenset({EVENT_GROUPS[GATE_RULES[0]], EVENT_GROUPS[min(GATE_NOTES)]})),
    ("channel", "통로", frozenset({EVENT_GROUPS[UPDATE_RULE]})),
)
INBOUND_HANDLED = "inbound_handled"


def flow(items: list[HarnessItem]) -> list[OutreachFlowNode]:
    """다섯 마디마다 그 줄의 사건 수와 판정(판정 글마다 수, 처음 나온 차례). 모르는 사건은 어느 마디에도 들지 않는다."""
    nodes = []
    for key, label, groups in FLOW:
        mine = [i.harness for i in items if i.harness.group in groups]
        counts: dict[tuple[str | None, str], int] = {}
        for mark in mine:
            counts[(mark.verdict, mark.verdict_label)] = counts.get((mark.verdict, mark.verdict_label), 0) + 1
        verdicts = [OutreachFlowVerdict(verdict=v, label=text, count=n) for (v, text), n in counts.items()]
        nodes.append(OutreachFlowNode(key=key, label=label, count=len(mine), verdicts=verdicts))
    return nodes


def _admitted(value: object) -> bool:
    return isinstance(value, list) and any(isinstance(e, dict) and e.get("rule") == ADMIT_RULE for e in value)


def branches(session: Session, kind: str, row: Any) -> list[str]:
    """받은 문자 줄에 받기 판정 사건이 있고 답 줄이 reply_to_id 로 걸려 있으면(어느 쪽 줄을 보든) inbound_handled.
    통화 가지는 Task 110·98."""
    if kind != "message":
        return []
    if row.direction == "in":
        inbound = row
        linked = session.scalar(select(OutreachMessage.id).where(OutreachMessage.reply_to_id == row.id).limit(1))
    elif row.reply_to_id is not None:
        inbound = session.get(OutreachMessage, row.reply_to_id)
        linked = inbound is not None and inbound.direction == "in"
    else:
        return []
    return [INBOUND_HANDLED] if linked and _admitted(inbound.harness_json) else []


# ── 도구 목록 ───────────────────────────────────────────────────────

HARNESS_PREFIX = "outreach."
HARNESS_CATEGORY = "연락 하네스 도구"
HARNESS_ROLE = "음성·글 에이전트 — 사람이 직접 부르지 않음"
CHAT_PROGRAM = "contacts"  # 대화 에이전트 연락 도구(Task 80·81)의 program
CHAT_ROLE = "관리자·사용자 — 현장 관리자 불가"
DELEGATED_ROLE = "그 채널이 위임일 때만 보임"


def chat_role(name: str, program: str | None) -> dict[str, Any]:
    """대화 에이전트 연락 도구의 역할 칸(도구가 현장 관리자를 거절한다 — tools.notify.schedule_for). 다른 도구는 {}."""
    if program != CHAT_PROGRAM:
        return {}
    return {"roles": ["admin", "user"], "role_note": DELEGATED_ROLE if name in SEND_TOOLS else CHAT_ROLE}


def _grants(name: str) -> tuple[list[str], list[str]]:
    """그 도구를 받는 등급들(등급표 차례)과 매체들 — toolsets.for_class 에서."""
    classes: list[str] = []
    media: list[str] = []
    for medium in get_args(Medium):
        for caller_class in get_args(CallerClass):
            if name in toolsets.for_class(caller_class, medium):
                classes += [] if caller_class in classes else [caller_class]
                media += [] if medium in media else [medium]
    order = get_args(CallerClass)
    return sorted(classes, key=order.index), media


def harness_tools() -> list[dict[str, Any]]:
    """하네스 도구 12개(이름표 차례). 표시 id 는 outreach.<이름>, 모델 쪽 이름은 <이름> 그대로."""
    rows = []
    for definition in toolsets.tool_defs(toolsets.ALL):
        classes, media = _grants(definition.name)
        rows.append({
            "name": f"{HARNESS_PREFIX}{definition.name}", "llm_name": definition.name, "program": None,
            "category": HARNESS_CATEGORY, "enabled": True, "toggle": False, "roles": [], "role_note": HARNESS_ROLE,
            "classes": classes, "media": media, "description": definition.description,
            "schema": definition.json_schema(),
        })
    return rows


# ── 사용량 ──────────────────────────────────────────────────────────

TEXT_KINDS = ("text_reply", "draft", "translation")  # 글 쪽 모델 사용(outreach_usage.kind) — 음성 쪽은 Task 110


def text_models(summary: UsageSummary) -> list[TextModelUsageOut]:
    """글 쪽 종류마다 횟수·토큰·요금(모델이 알려 준 것만 — 없으면 None). 줄이 없는 종류는 0."""
    out = []
    for kind in TEXT_KINDS:
        used = summary.by_kind.get(kind) or KindUsage(count=0, input_tokens=0, output_tokens=0, seconds=0, cost=None)
        out.append(TextModelUsageOut(kind=kind, count=used.count, input_tokens=used.input_tokens,
                                     output_tokens=used.output_tokens, cost=used.cost))
    return out
