"""개발 콘솔 ②(Task 109): 구조·흐름도의 연락 가지 · 도구 목록의 연락 도구 · 글 쪽 모델 사용량. 읽기만 한다.

- **가지는 기록에서만 켜진다** — 설정(위임 권한)이나 도구 등록 여부를 읽지 않는다.
  대화 턴: 실행 걸음(WorkflowStep)의 도구 이름·상태·결과의 outcome. 연락 하나: 그 줄의 하네스 사건과 답 줄의 reply_to_id.
- 흐름도 마디(들어오는 문 → 도구 → 뒤 확인 → 나가는 문 → 통로)는 harness.types 의 묶음으로 사건을 모은다. 묶음·이름은
  상수에서 꺼낸다(사건 이름 글자를 적지 않는다 — outreach_view 와 같은 규칙). 판정 글은 시간표 줄이 이미 가진 것을 쓴다.
- 하네스 도구 12개는 등록부 도구가 아니다: 이름·설명·인자 꼴은 toolsets.tool_defs, 등급·매체는 toolsets.for_class 에서
  읽는다(표를 옮겨 적지 않는다). 끄기 길이 없다(toggle false).
"""

import json
from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.outreach.harness import toolsets
from app.outreach.harness.types import (
    ADMIT_REASONS,
    DELIVERY_UPDATES,
    EVENT_GROUP_KEYS,
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
    CallModelUsageOut,
    CallUsageOut,
    HarnessItem,
    OutreachFlowNode,
    OutreachFlowVerdict,
    StructureOut,
    TextModelUsageOut,
    TimelineItem,
)
from app.store.outreach_usage import KindUsage, UsageSummary
from app.store.tables import WorkflowStep
from app.store.tables_outreach import OutreachCall, OutreachMessage

# ── 대화 턴의 가지 ──────────────────────────────────────────────────

LOOKUP_TOOL = "contacts.list"
DRAFT_TOOLS = frozenset({"notify.draft_message", "notify.draft_call"})
SEND_TOOLS = frozenset({"notify.send_message", "notify.place_call"})  # 위임 도구(Task 81)
PASSED = frozenset({"accepted", "queued", "scheduled"})  # 위임 발송이 문을 지나간 판정 코드
UNSURE, FAILED = "unsure", "failed"  # 문은 지나갔는데 결과를 모름 · 통로가 보내지 못함 — 「막음」이 아니다(그 밖의 코드가 막음)
_SENT_FLAGS = {UNSURE: "outreach_unsure", FAILED: "outreach_failed"}


def step_flags(tool: str, status: str, out: dict) -> list[str]:
    """실행 걸음 하나가 보여 주는 연락 가지. 연락처 조회는 걸음이 있으면, 초안은 끝났으면, 위임 발송은 끝났고 결과에
    판정 코드(outcome)가 있으면 — 지나감 · 결과 모름 · 통로 실패 · 문이 막음 넷으로 가른다."""
    if tool == LOOKUP_TOOL:
        return ["contact_lookup"]
    if status != "done":
        return []
    if tool in DRAFT_TOOLS:
        return ["outreach_draft"]
    outcome = out.get("outcome")
    if tool in SEND_TOOLS and isinstance(outcome, str):
        return ["outreach_delegated" if outcome in PASSED else _SENT_FLAGS.get(outcome, "outreach_blocked")]
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
INBOUND_REFUSED = "inbound_refused"  # 받기 판정이 응대가 아님(막음·수신 거부 말)인데 고정 안내 답이 걸림


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


def _admission(value: object) -> str | None:
    """그 줄의 마지막 받기 판정 사건의 판정. 없으면 None."""
    found = [e for e in value if isinstance(e, dict) and e.get("rule") == ADMIT_RULE] if isinstance(value, list) else []
    return str(found[-1].get("verdict")) if found else None


def branches(session: Session, kind: str, row: Any) -> list[str]:
    """받은 문자 줄에 받기 판정 사건이 있고 답 줄이 reply_to_id 로 걸려 있으면(어느 쪽 줄을 보든): 판정이 응대
    (allowed)면 inbound_handled, 그 밖(막음·수신 거부 말)이면 inbound_refused. 통화 줄은 dialing 을 지났으면 call_placed."""
    if kind != "message":
        return [CALL_PLACED] if dialed(row.harness_json) is True else []
    if row.direction == "in":
        inbound = row
        linked = session.scalar(select(OutreachMessage.id).where(OutreachMessage.reply_to_id == row.id).limit(1))
    elif row.reply_to_id is not None:
        inbound = session.get(OutreachMessage, row.reply_to_id)
        linked = inbound is not None and inbound.direction == "in"
    else:
        return []
    verdict = _admission(inbound.harness_json) if linked else None
    if verdict is None:
        return []
    return [INBOUND_HANDLED if verdict == "allowed" else INBOUND_REFUSED]


# ── 통화 가지(Task 110) ─────────────────────────────────────────────

CALL_RULES = tuple(sorted(rule for rule, group in EVENT_GROUPS.items() if group == EVENT_GROUP_KEYS[6]))  # 「통화」 묶음
RECHECK_RULE = CALL_RULES[3]  # 걸기 직전 다시 본 문 — 이름 차례로 꺼낸다(시험이 이름으로 못 박는다)
PLACE_TOOL = "notify.place_call"
CALL_PLACED = "call_placed"
DELEGATED, BLOCKED = "outreach_delegated", "outreach_blocked"


def dialed(value: object) -> bool | None:
    """통화 줄의 걸기 직전 다시 보기의 마지막 판정: 지나감(queued → dialing 으로 차지함) True · 막힘(걸지 않음) False · 없음 None.
    차지한 뒤 준비 오류로 닫힌 줄은 그 뒤에 막힘이 남아 False 다."""
    found = [e.get("verdict") for e in value if isinstance(e, dict) and e.get("rule") == RECHECK_RULE] \
        if isinstance(value, list) else []
    return None if not found else found[-1] == "allowed"


def _placed_call(session: Session, step: WorkflowStep) -> bool | None:
    """대화 턴의 위임 통화 걸음(줄에 넣음까지 지남)이 가리키는 통화 줄의 dialed. 기록이 없으면 None."""
    out = _loads(step.output_json)
    if step.tool != PLACE_TOOL or step.status != "done" or out.get("outcome") not in PASSED:
        return None
    call_id = _loads(step.input_json).get("call_id")
    row = session.get(OutreachCall, call_id) if isinstance(call_id, int) else None
    return dialed(row.harness_json) if row is not None else None


def _loads(text: str | None) -> dict:
    try:
        value = json.loads(text or "")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def light_calls(session: Session, steps: list[WorkflowStep], structure: StructureOut,
                timeline: list[TimelineItem]) -> None:
    """위임 통화의 그 뒤를 통화 줄의 기록으로: dialing 을 지났으면 call_placed 를 더하고, 걸기 직전 다시 보기에 막혀 걸지 않았으면
    그 걸음의 outreach_delegated 를 outreach_blocked 로 바꾼다(줄에 넣기만 하고 막힘). 아직 줄에 있으면 그대로."""
    for step in steps:
        state = _placed_call(session, step)
        if state is None:
            continue
        for item in timeline:
            if item.kind == "tool" and item.label == step.tool and item.input_text == step.input_json:
                item.signals = [*item.signals, CALL_PLACED] if state else \
                    [BLOCKED if flag == DELEGATED else flag for flag in item.signals]
        structure.edges_lit += [flag for flag in ((CALL_PLACED,) if state else (BLOCKED,)) if flag not in structure.edges_lit]
    if not any(DELEGATED in item.signals for item in timeline if item.kind == "tool"):
        structure.edges_lit = [flag for flag in structure.edges_lit if flag != DELEGATED]


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

TEXT_KINDS = ("text_reply", "draft", "translation")  # 글 쪽 모델 사용(outreach_usage.kind) — 음성 쪽은 call_usage
CALL_KINDS = ("voice_model", "transcription", "summary")  # 통화 쪽 — transcription 은 기록이 있을 때만 줄이 생긴다
_NONE = KindUsage(count=0, input_tokens=0, output_tokens=0, seconds=0, cost=None)


def text_models(summary: UsageSummary) -> list[TextModelUsageOut]:
    """글 쪽 종류마다 횟수·토큰·요금(모델이 알려 준 것만 — 없으면 None). 줄이 없는 종류는 0."""
    out = []
    for kind in TEXT_KINDS:
        used = summary.by_kind.get(kind) or KindUsage(count=0, input_tokens=0, output_tokens=0, seconds=0, cost=None)
        out.append(TextModelUsageOut(kind=kind, count=used.count, input_tokens=used.input_tokens,
                                     output_tokens=used.output_tokens, cost=used.cost))
    return out


def call_usage(summary: UsageSummary) -> CallUsageOut:
    """통화 시간·건 통화 수와 통화 쪽 모델 사용(알려 준 초·토큰·요금만 — 어림하지 않는다)."""
    models = []
    for kind in CALL_KINDS:
        used = summary.by_kind.get(kind)
        if used is None and kind == "transcription":
            continue
        used = used or _NONE
        models.append(CallModelUsageOut(kind=kind, count=used.count, seconds=used.seconds, input_tokens=used.input_tokens,
                                        output_tokens=used.output_tokens, cost=used.cost))
    return CallUsageOut(call_seconds=summary.call_seconds, calls_placed=summary.calls_placed, models=models,
                        calls_answered=summary.calls_answered, calls_rejected=summary.calls_rejected)
