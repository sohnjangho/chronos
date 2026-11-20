"""개발 콘솔: 턴 목록, 턴 하나의 에이전트 구조(칸 아홉)와 실행 추적 시간표, LLM 사용량.

구조 칸(차례): request 요청 받기 · context 컨텍스트 조립 · skill 스킬 찾기 · plan 워크플로우 짜기 ·
judge 판단 (모델) · tool 도구 실행 · check 조건 점검 · approval 승인 판단 · respond 응답·기록.
- skill 은 늘 skipped. plan = 첫 llm 사건, judge = 나머지 llm 사건(count).
- 단계(workflow_steps)는 도구 이름으로 check(harness.check·generate.run) · approval(out.submit_change·
  scenario.submit·rules.propose) · tool(그 밖).
- respond 는 end 사건이 있으면 past. 들른 칸은 past, 들르지 않은 칸은 todo.
- 턴이 돌고 있으면 끝나지 않은 사건(ms 없는 llm, running 단계)의 칸이 now, 없으면 judge 가 now.

detail = {in, out, ms, model, settings}:
- request: in = 모델이 읽은 사용자 글.
- context: in = {parts: [{name, chars, tokens, share}], history_count, tool_count}, ms = 조립 시간.
  tokens 는 첫 호출의 입력 토큰을 글자 수에 비례해 나눈 어림(첫 호출 토큰이 없으면 null), share 는 글자 비중 %.
- skill: in = "스킬은 묶음 3에서 — 지금은 늘 없음".
- plan·judge: in/out = (judge 는 마지막) llm 사건의 input_text / output_text(실패면 오류 글), ms = 합, model.
- tool·check·approval: in = [{n, tool, input}], out = [{n, status, output}], ms = 합.
  settings: check "점검 한도 5회", approval "승인 수준: <승인 수준 한국어>".
- respond: out = 마지막 답 글(실패·멈춤이면 그 안내), ms = 턴 전체 시간.
"""

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.agent import turns
from app.agent.context import wire
from app.agent.loop import MAX_STEPS
from app.errors import ApiError
from app.programs.devconsole.schemas import (
    NodeDetail,
    NodeOut,
    StructureOut,
    TimelineItem,
    TurnDetail,
    TurnOut,
    UsageGroup,
    UsageOut,
)
from app.store import traces as store
from app.store.settings import approval_mode
from app.store.tables import LlmCall, TraceEvent, WorkflowStep
from app.store.timeutil import as_utc
from app.store.workflows import steps_of

NODES = (
    ("request", "요청 받기"), ("context", "컨텍스트 조립"), ("skill", "스킬 찾기"), ("plan", "워크플로우 짜기"),
    ("judge", "판단 (모델)"), ("tool", "도구 실행"), ("check", "조건 점검"), ("approval", "승인 판단"),
    ("respond", "응답·기록"),
)
CHECK_TOOLS = frozenset({"harness.check", "generate.run"})
APPROVAL_TOOLS = frozenset({"out.submit_change", "scenario.submit", "rules.propose"})
SKILL_NOTE = "스킬은 묶음 3에서 — 지금은 늘 없음"
CHECK_SETTING = "점검 한도 5회"
MODE_LABELS = {"all": "모두 승인", "important": "중요한 것만", "auto": "자동"}
REQUEST_LIMIT = 60
NOT_FOUND_MESSAGE = "실행 추적을 찾을 수 없습니다."
_ERROR_LIMIT = 200


def _cell(tool: str) -> str:
    if tool in CHECK_TOOLS:
        return "check"
    return "approval" if tool in APPROVAL_TOOLS else "tool"


def _request(row: store.TurnRow) -> str:
    return wire("user", row.content)["content"] if row.content else ""


def _status(row: store.TurnRow) -> str:
    if row.end_status is not None:
        return row.end_status
    return "running" if row.latest and turns.is_running(row.chat_session_id) else "stopped"


def _turn_out(row: store.TurnRow) -> TurnOut:
    return TurnOut(
        turn_id=row.turn_id, chat_session_id=row.chat_session_id, user_name=row.user_name,
        request=_request(row)[:REQUEST_LIMIT], started_at=row.started_at, status=_status(row),
        llm_calls=row.llm_calls, tool_calls=row.tool_calls, tokens=row.tokens, cost=row.cost, ms=row.ms,
    )


def list_turns(session: Session, limit: int) -> list[TurnOut]:
    return [_turn_out(r) for r in store.turns(session, limit)]


def get_turn(session: Session, turn_id: int) -> TurnDetail:
    row = store.turn(session, turn_id)
    if row is None:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    events = store.events(session, turn_id)
    steps = steps_of(session, row.run_id) if row.run_id is not None else []
    inner = store.inner_calls(session, row.chat_session_id, row.started_at, row.ended_at)
    turn = _turn_out(row)
    structure = _structure(row, events, steps, running=turn.status == "running", mode=approval_mode(session))
    return TurnDetail(turn=turn, structure=structure, timeline=_timeline(events, steps, inner, row.started_at))


def usage(session: Session, *, days: int, group: UsageGroup) -> UsageOut:
    return store.usage(session, days=days, group=group)


# ── 구조 ────────────────────────────────────────────────────────────


def _detail(**fields) -> NodeDetail:
    return NodeDetail.model_validate(fields)


def _sum_ms(items: list) -> int | None:
    values = [i.ms for i in items if i.ms is not None]
    return sum(values) if values else None


def _context_detail(ctx: TraceEvent | None, llms: list[TraceEvent]) -> NodeDetail:
    if ctx is None:
        return _detail()
    try:
        body = json.loads(ctx.input_text)
    except ValueError:
        body = {}
    parts = body.get("parts", [])
    total = sum(p["chars"] for p in parts)
    tokens = llms[0].input_tokens if llms else 0
    body["parts"] = [
        {**p, "tokens": round(tokens * p["chars"] / total) if tokens and total else None,
         "share": round(100 * p["chars"] / total, 1) if total else 0.0}
        for p in parts
    ]
    return _detail(**{"in": body}, ms=ctx.ms)


def _llm_detail(llms: list[TraceEvent]) -> NodeDetail:
    if not llms:
        return _detail()
    last = llms[-1]
    return _detail(**{"in": last.input_text}, out=last.output_text or last.error, ms=_sum_ms(llms), model=last.model)


def _steps_detail(steps: list[WorkflowStep], settings: str | None) -> NodeDetail:
    return _detail(
        **{"in": [{"n": s.n, "tool": s.tool, "input": s.input_json} for s in steps]},
        out=[{"n": s.n, "status": s.status, "output": s.output_json} for s in steps],
        ms=_sum_ms(steps), settings=settings,
    )


def _now(llms: list[TraceEvent], steps: list[WorkflowStep]) -> str:
    """돌고 있는 턴에서 지금 칸."""
    open_llm = next((e for e in llms if e.ms is None), None)
    if open_llm is not None:
        return "plan" if open_llm is llms[0] else "judge"
    open_step = next((s for s in steps if s.status == "running"), None)
    return _cell(open_step.tool) if open_step is not None else "judge"


def _structure(row: store.TurnRow, events: list[TraceEvent], steps: list[WorkflowStep], *, running: bool,
               mode: str) -> StructureOut:
    llms = [e for e in events if e.kind == "llm"]
    ctx = next((e for e in events if e.kind == "context"), None)
    end = next((e for e in events if e.kind == "end"), None)
    cells: dict[str, list[WorkflowStep]] = {"tool": [], "check": [], "approval": []}
    for step in steps:
        cells[_cell(step.tool)].append(step)
    settings = {"tool": None, "check": CHECK_SETTING, "approval": f"승인 수준: {MODE_LABELS.get(mode, mode)}"}
    found = {
        "request": (1, _detail(**{"in": _request(row)})),
        "context": (int(ctx is not None), _context_detail(ctx, llms)),
        "skill": (0, _detail(**{"in": SKILL_NOTE})),
        "plan": (len(llms[:1]), _llm_detail(llms[:1])),
        "judge": (len(llms[1:]), _llm_detail(llms[1:])),
        **{k: (len(v), _steps_detail(v, settings[k])) for k, v in cells.items()},
        "respond": (int(end is not None), _detail(out=end.output_text, ms=end.ms) if end else _detail()),
    }
    now = _now(llms, steps) if running else None
    nodes = []
    for key, label in NODES:
        count, detail = found[key]
        state = "skipped" if key == "skill" else "now" if key == now else "past" if count else "todo"
        nodes.append(NodeOut(key=key, label=label, state=state, count=count, detail=detail))
    return StructureOut(nodes=nodes, loop_count=len(llms), limit=MAX_STEPS)


# ── 시간표 ──────────────────────────────────────────────────────────


def _call_count(llm: TraceEvent) -> int | None:
    """그 답이 부른 도구 수(output_text 의 tool_calls). 답이 없으면(실패·호출 중) 0, 읽을 수 없으면(잘림) None."""
    if not llm.output_text:
        return 0
    try:
        return len(json.loads(llm.output_text)["tool_calls"])
    except (ValueError, KeyError, TypeError):
        return None


def _event_item(e: TraceEvent) -> TimelineItem:
    return TimelineItem(
        seq=0, kind=e.kind, label=e.label if e.kind == "context" else f"모델 호출 ({e.label})",
        started_at=as_utc(e.started_at), ms=e.ms, model=e.model, input_tokens=e.input_tokens,
        output_tokens=e.output_tokens, cost=e.cost, ok=e.ok, error=e.error, input_text=e.input_text,
        output_text=e.output_text, parallel_group=None,
    )


def _step_error(step: WorkflowStep) -> str:
    if step.status != "failed":
        return step.status
    try:
        return str(json.loads(step.output_json or "")["error"])[:_ERROR_LIMIT]
    except (ValueError, KeyError, TypeError):
        return step.status


def _step_item(step: WorkflowStep, start: datetime, group: int | None) -> TimelineItem:
    ok = step.status in ("done", "running")
    return TimelineItem(
        seq=0, kind="tool", label=step.tool, started_at=start, ms=step.ms, model=None, input_tokens=0,
        output_tokens=0, cost=None, ok=ok, error=None if ok else _step_error(step), input_text=step.input_json,
        output_text=step.output_json or "", parallel_group=group,
    )


def _step_items(llms: list[TraceEvent], steps: list[WorkflowStep], turn_start: datetime) -> list[TimelineItem]:
    """단계를 그것을 부른 llm 사건(답의 tool_calls 수만큼 차례대로)에 잇는다. 시작은 그 답이 끝난 때부터
    앞 단계 시간을 더한 어림이다. 읽을 수 없는 답(잘림)을 만나면 그 뒤 단계는 모두 짝 없이(null)
    앞 단계 뒤에(앞 단계가 없으면 그 답 뒤에) 차례로 둔다."""
    queue = list(steps)
    items, cursor = [], turn_start

    def place(step: WorkflowStep, group: int | None) -> None:
        nonlocal cursor
        items.append(_step_item(step, cursor, group))
        cursor += timedelta(milliseconds=step.ms or 0)

    for llm in llms:
        if not queue:
            break
        count = _call_count(llm)
        end = as_utc(llm.started_at) + timedelta(milliseconds=llm.ms or 0)
        if count is None:
            cursor = max(cursor, end) if items else end
            break
        if count:
            cursor = end
        for _ in range(min(count, len(queue))):
            place(queue.pop(0), llm.seq)
    for step in queue:
        place(step, None)
    return items


def _inner_item(call: LlmCall) -> TimelineItem:
    created = as_utc(call.created_at)
    return TimelineItem(
        seq=0, kind="inner_llm", label=f"도구 안 모델 호출 ({call.purpose})",
        started_at=created - timedelta(milliseconds=call.latency_ms), ms=call.latency_ms, model=call.model,
        input_tokens=call.input_tokens, output_tokens=call.output_tokens, cost=call.cost, ok=call.ok,
        error=call.error_code, input_text="", output_text="", parallel_group=None,
    )


def _timeline(events: list[TraceEvent], steps: list[WorkflowStep], inner: list[LlmCall],
              turn_start: datetime) -> list[TimelineItem]:
    """context·llm·tool(단계)·inner_llm 을 시각 순으로(같은 시각은 이 차례). seq 는 1부터 다시 매긴다."""
    llms = [e for e in events if e.kind == "llm"]
    items = [_event_item(e) for e in events if e.kind in ("context", "llm")]
    items += _step_items(llms, steps, turn_start)
    items += [_inner_item(c) for c in inner]
    items.sort(key=lambda t: t.started_at)
    for seq, item in enumerate(items, 1):
        item.seq = seq
    return items
