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
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import turns
from app.agent.context import wire
from app.agent.loop import MAX_STEPS
from app.config import Settings
from app.errors import ApiError
from app.files import vectors
from app.llm.assignments import default_connection
from app.llm.connections import secret_is_sendable
from app.programs.devconsole.schemas import (
    ActiveTurnOut,
    DbHealthOut,
    HealthOut,
    LlmHealthOut,
    NodeDetail,
    NodeOut,
    QdrantHealthOut,
    SearchHealthOut,
    StopTurnOut,
    StructureOut,
    TimelineItem,
    ToolToggleOut,
    TurnDetail,
    TurnOut,
    UsageGroup,
    UsageOut,
)
from app.security.crypto import SecretUnreadable, decrypt
from app.store import settings as settings_store
from app.store import traces as store
from app.store.evidence import NOT_SEARCH_MODES
from app.store.settings import approval_mode, get_agent_config
from app.store.tables import (
    Approval,
    ChatSession,
    EvidenceSearch,
    FileRow,
    LlmAssignment,
    LlmCall,
    LlmConnection,
    ReportRow,
    ScheduleRecord,
    SkillRow,
    TraceEvent,
    User,
    WorkflowRun,
    WorkflowStep,
)
from app.store.timeutil import as_utc
from app.store.workflows import steps_of
from app.tools import registry

NODES = (
    ("request", "요청 받기"), ("context", "컨텍스트 조립"), ("skill", "스킬 찾기"), ("plan", "워크플로우 짜기"),
    ("judge", "판단 (모델)"), ("tool", "도구 실행"), ("check", "조건 점검"), ("approval", "승인 판단"),
    ("respond", "응답·기록"),
)
CHECK_TOOLS = frozenset({"harness.check", "generate.run", "schedule.import"})
APPROVAL_TOOLS = frozenset({"out.submit_change", "scenario.submit", "rules.propose"})
SKILL_NOTE = "일치하는 스킬 없음"
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
    cfg = get_agent_config(session)
    structure = _structure(
        row, events, steps, running=turn.status == "running", mode=cfg["approval_mode"],
        max_steps=cfg["max_steps"], check_retries=cfg["max_check_retries"],
    )
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


def _parsed_output(step: WorkflowStep) -> dict:
    try:
        out = json.loads(step.output_json or "")
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def _branch_signals(llms: list[TraceEvent], steps: list[WorkflowStep], skill_ev: TraceEvent | None = None) -> tuple[list[str], dict | None]:
    """실제 실행 기록에서 분기 플래그와 하네스 점검 요약을 뽑는다."""
    lit: list[str] = []
    if skill_ev is not None and skill_ev.output_text:
        lit.append("skill_matched")
    if any(e.label == "vision" for e in llms):
        lit.append("vision_turn")
    if any(s.tool.startswith("files.") or s.tool == "schedule.import" for s in steps):
        lit.append("files_used")
    if any(s.tool == "info.weather" for s in steps):
        lit.append("weather_used")
    failed_seen = False
    for s in steps:
        if s.status == "failed":
            failed_seen = True
        elif failed_seen and s.status == "done":
            lit.append("self_corrected")
            break

    check_steps = [s for s in steps if s.tool in CHECK_TOOLS]
    harness_summary: dict | None = None
    if check_steps:
        rounds, passed, violations, uncheckable = 0, 0, 0, 0
        for s in check_steps:
            out = _parsed_output(s)
            r = out.get("rounds")
            rounds += len(r) if isinstance(r, list) else (r if isinstance(r, int) else 1)
            for key, acc in (("passed", "p"), ("violations", "v"), ("uncheckable", "u")):
                val = out.get(key)
                n = len(val) if isinstance(val, list) else (val if isinstance(val, int) else 0)
                if acc == "p":
                    passed += n
                elif acc == "v":
                    violations += n
                else:
                    uncheckable += n
            if isinstance(out.get("uncheckable_count"), int):
                uncheckable += out["uncheckable_count"]
        if rounds > len(check_steps) or violations > 0:
            lit.append("check_repair")
        harness_summary = {
            "tools": [s.tool for s in check_steps],
            "rounds": rounds,
            "passed": passed,
            "violations": violations,
            "uncheckable": uncheckable,
        }

    for s in steps:
        if s.tool not in APPROVAL_TOOLS:
            continue
        out = _parsed_output(s)
        if out.get("applied") is False or (out.get("approval_id") and out.get("applied") is not True):
            if "approval_inbox" not in lit:
                lit.append("approval_inbox")
        elif out.get("applied") is True:
            if "approval_auto" not in lit:
                lit.append("approval_auto")
    return lit, harness_summary


def _structure(row: store.TurnRow, events: list[TraceEvent], steps: list[WorkflowStep], *, running: bool,
               mode: str, max_steps: int = MAX_STEPS, check_retries: int = 5) -> StructureOut:
    llms = [e for e in events if e.kind == "llm"]
    ctx = next((e for e in events if e.kind == "context"), None)
    skill_ev = next((e for e in events if e.kind == "skill"), None)
    end = next((e for e in events if e.kind == "end"), None)
    cells: dict[str, list[WorkflowStep]] = {"tool": [], "check": [], "approval": []}
    for step in steps:
        cells[_cell(step.tool)].append(step)
    settings = {"tool": None, "check": f"점검 한도 {check_retries}회", "approval": f"승인 수준: {MODE_LABELS.get(mode, mode)}"}
    skill_matched = skill_ev is not None and bool(skill_ev.output_text)
    skill_detail = (
        _detail(**{"in": skill_ev.input_text}, out=skill_ev.output_text, ms=skill_ev.ms)
        if skill_matched
        else _detail(**{"in": skill_ev.input_text if skill_ev is not None else SKILL_NOTE})
    )
    found = {
        "request": (1, _detail(**{"in": _request(row)})),
        "context": (int(ctx is not None), _context_detail(ctx, llms)),
        "skill": (int(skill_matched), skill_detail),
        "plan": (len(llms[:1]), _llm_detail(llms[:1])),
        "judge": (len(llms[1:]), _llm_detail(llms[1:])),
        **{k: (len(v), _steps_detail(v, settings[k])) for k, v in cells.items()},
        "respond": (int(end is not None), _detail(out=end.output_text, ms=end.ms) if end else _detail()),
    }
    now = _now(llms, steps) if running else None
    nodes = []
    for key, label in NODES:
        count, detail = found[key]
        if key == "skill":
            state = "past" if skill_matched else "skipped"
        else:
            state = "now" if key == now else "past" if count else "todo"
        nodes.append(NodeOut(key=key, label=label, state=state, count=count, detail=detail))
    edges_lit, harness_summary = _branch_signals(llms, steps, skill_ev)
    return StructureOut(
        nodes=nodes, loop_count=len(llms), limit=max_steps,
        edges_lit=edges_lit, harness_summary=harness_summary,
    )


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


# ── 시스템 진단 · 턴 제어 · 도구 제어 ────────────────────────────────


def _llm_health(session: Session) -> LlmHealthOut:
    conn_count = session.scalar(select(func.count()).select_from(LlmConnection)) or 0
    assign_count = session.scalar(select(func.count()).select_from(LlmAssignment)) or 0
    conn = default_connection(session)
    if conn is None:
        return LlmHealthOut(
            status="warn",
            connections_count=conn_count,
            assignments_count=assign_count,
            key_ready=False,
            message="기본 LLM 연결이 설정되지 않았습니다.",
        )
    key_ready = False
    try:
        key = decrypt(conn.secret_ciphertext)
        key_ready = secret_is_sendable(key)
    except SecretUnreadable:
        key_ready = False
    return LlmHealthOut(
        status="ok" if key_ready else "error",
        connections_count=conn_count,
        assignments_count=assign_count,
        default_name=conn.name,
        default_provider=conn.provider,
        default_base_url=conn.base_url,
        key_ready=key_ready,
        message="기본 연결 및 인증 키 준비됨" if key_ready else "저장된 API 키를 읽을 수 없거나 비어 있습니다.",
    )


def _qdrant_health() -> QdrantHealthOut:
    store_obj = vectors.STORE
    if store_obj is None:
        return QdrantHealthOut(status="off", message="CHRONOS_QDRANT_URL 미설정 (키워드 검색만 사용)")
    t0 = time.perf_counter()
    try:
        available = store_obj.available()
    except Exception:  # noqa: BLE001
        available = False
    latency_ms = round((time.perf_counter() - t0) * 1000)
    if not available:
        return QdrantHealthOut(status="error", latency_ms=latency_ms, message="Qdrant 서버에 연결할 수 없습니다.")
    cols: list[str] = []
    points = 0
    try:
        cols = store_obj.collections()
        for name in cols:
            info = store_obj.client.get_collection(name)
            points += int(getattr(info, "points_count", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    return QdrantHealthOut(
        status="ok",
        collections=cols,
        points_count=points,
        latency_ms=latency_ms,
        message=f"연결 정상 (컬렉션 {len(cols)}개 · 벡터 {points:,}건)",
    )


def _search_health(session: Session, llm_health: LlmHealthOut) -> SearchHealthOut:
    since = (datetime.now(UTC) - timedelta(days=7)).replace(tzinfo=None)
    calls = session.scalar(
        select(func.count()).select_from(EvidenceSearch).where(
            EvidenceSearch.mode.notin_(NOT_SEARCH_MODES), EvidenceSearch.created_at >= since
        )
    ) or 0
    failed = session.scalar(
        select(func.count()).select_from(EvidenceSearch).where(
            EvidenceSearch.mode.notin_(NOT_SEARCH_MODES),
            EvidenceSearch.created_at >= since,
            EvidenceSearch.ok.is_(False),
        )
    ) or 0
    ready = llm_health.default_provider == "liner" and llm_health.key_ready
    msg = (
        f"Liner Search/MCP 준비됨 (최근 7일 {calls}회 · 실패 {failed}건)"
        if ready
        else "Liner 기본 연결이 있어야 웹·법령 근거 검색이 동작합니다."
    )
    return SearchHealthOut(status="ok" if ready else "warn", ready=ready, calls_7d=calls, failed_7d=failed, message=msg)


def _db_health(session: Session) -> DbHealthOut:
    db_file = Settings().data_dir / "chronos.db"
    size = db_file.stat().st_size if db_file.exists() else 0
    counts = {
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "schedules": session.scalar(select(func.count()).select_from(ScheduleRecord)) or 0,
        "chats": session.scalar(select(func.count()).select_from(ChatSession)) or 0,
        "workflow_runs": session.scalar(select(func.count()).select_from(WorkflowRun)) or 0,
        "files": session.scalar(select(func.count()).select_from(FileRow).where(FileRow.deleted_at.is_(None))) or 0,
        "approvals": session.scalar(select(func.count()).select_from(Approval).where(Approval.status == "pending")) or 0,
        "reports": session.scalar(select(func.count()).select_from(ReportRow)) or 0,
        "skills": session.scalar(select(func.count()).select_from(SkillRow)) or 0,
    }
    return DbHealthOut(status="ok", size_bytes=size, counts=counts)


def health(session: Session) -> HealthOut:
    llm_h = _llm_health(session)
    qdrant_h = _qdrant_health()
    search_h = _search_health(session, llm_h)
    db_h = _db_health(session)
    running = turns.active_turns()
    titles = {}
    if running:
        cids = [t["chat_session_id"] for t in running]
        rows = session.scalars(select(ChatSession).where(ChatSession.id.in_(cids)))
        titles = {r.id: r.title or f"대화 #{r.id}" for r in rows}
    active = [
        ActiveTurnOut(
            chat_session_id=t["chat_session_id"],
            title=titles.get(t["chat_session_id"], f"대화 #{t['chat_session_id']}"),
            stop_requested=t["stop_requested"],
        )
        for t in running
    ]
    return HealthOut(llm=llm_h, qdrant=qdrant_h, search=search_h, db=db_h, active_turns=active)


def stop_turn(chat_session_id: int) -> StopTurnOut:
    return StopTurnOut(chat_session_id=chat_session_id, stopped=turns.request_stop(chat_session_id))


def toggle_tool(session: Session, tool_name: str, enabled: bool) -> ToolToggleOut:
    registry.load_all()
    known = {t.name for t in registry.list_tools(enabled_only=False)}
    if tool_name not in known:
        raise ApiError(404, "not_found", f"도구를 찾을 수 없습니다: {tool_name}")
    registry.set_enabled(tool_name, enabled)
    settings_store.set_tool_enabled(session, tool_name, enabled)
    return ToolToggleOut(name=tool_name, enabled=enabled)
