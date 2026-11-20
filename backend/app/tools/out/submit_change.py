"""out.submit_change — 에이전트가 만든 변경을 내보낸다: 초안 저장(첫 저장) 또는 일정 고침.

승인이 필요한지는 코드(app.agent.approval.assess)가 승인 수준(settings 의 approval_mode)에 따라 정한다.
- 필요하면 승인 건(status pending)을 만들고 AgentEvent("approval", {id, title, reasons, summary}) 를 낸다.
- 아니면 바로 저장하고(by_kind "agent") 승인 표에 status auto 줄을 남긴 뒤(고침이면 되돌릴 버전 restore_to)
  AgentEvent("card", {kind: "auto_applied", schedule_id, version, count, summary}) 를 낸다.
쓰기는 flush 만 한다. 에이전트 루프가 성공한 도구 뒤에 commit 하고, 실패면 rollback 한다.
"""

from dataclasses import dataclass, replace
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.approval import assess
from app.agent.events import AgentEvent
from app.agent.generation_build import MAX_LAG, MAX_OD
from app.core.cpm import ScheduleError
from app.core.model import Activity, Relation, Schedule
from app.harness.assemble import assemble_all
from app.harness.checks import check
from app.harness.conditions import Condition, ConditionFormatError, read_conditions
from app.store import approvals
from app.store.diff import schedule_changes
from app.store.drafts import get_draft
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, from_json, load, run, to_json
from app.store.settings import approval_mode
from app.store.tables import Approval
from app.store.versions import VersionConflict
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

STALE_MESSAGE = "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."
USED_DRAFT_MESSAGE = "이미 저장한 초안입니다."
WAITING_DRAFT_MESSAGE = "이미 승인을 기다리는 초안입니다."
NO_DRAFT_MESSAGE = "초안을 찾을 수 없습니다."
OTHER_CHAT_DRAFT_MESSAGE = "이 대화의 초안이 아닙니다."
NO_CHANGE_MESSAGE = "바뀌는 것이 없습니다."

Od = Annotated[int, Field(ge=0, le=MAX_OD, strict=True)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PredIn(Strict):
    pred: str = Field(min_length=1, description="선행 액티비티 id")
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag: int = Field(default=0, ge=-MAX_LAG, le=MAX_LAG, strict=True)


class UpdateOp(Strict):
    """보낸 칸만 바꾼다. preds 를 보내면 이 액티비티의 선행 관계를 모두 그것으로 바꾼다."""

    op: Literal["update_activity"]
    id: str
    od: Od | None = Field(default=None, description="기간(근무일)")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    preds: list[PredIn] | None = None


class NewActivity(Strict):
    id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    od: Od
    preds: list[PredIn]
    wbs: str | None = Field(default=None, description="없으면 첫 선행의 WBS")
    resources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class AddOp(Strict):
    op: Literal["add_activity"]
    activity: NewActivity


class DeleteOp(Strict):
    """액티비티와 그것을 가리키는 관계를 지운다."""

    op: Literal["delete_activity"]
    id: str


Op = Annotated[UpdateOp | AddOp | DeleteOp, Field(discriminator="op")]


class SubmitIn(Strict):
    title: str = Field(min_length=1, max_length=100, description="승인함에 보일 짧은 제목")
    draft_id: int | None = Field(default=None, description="generate__run 의 draft_id (새 일정 저장)")
    schedule_id: int | None = Field(default=None, description="고칠 일정")
    base_version: int | None = Field(default=None, description="읽은 일정의 지금 버전")
    changes: list[Op] | None = Field(default=None, max_length=100, description="고침 목록(차례대로 적용)")
    conditions: list[dict] | None = Field(default=None, description="입력 조건 전체(layer input). 바꿀 때만 보낸다")

    @model_validator(mode="after")
    def _one_kind(self) -> "SubmitIn":
        if (self.draft_id is None) == (self.changes is None):
            raise ValueError("draft_id 와 changes 가운데 하나만 보냅니다.")
        if self.draft_id is not None and (self.schedule_id, self.base_version, self.conditions) != (None, None, None):
            raise ValueError("draft_id 에는 schedule_id·base_version·conditions 를 함께 보내지 않습니다.")
        if self.changes is not None and (self.schedule_id is None or self.base_version is None):
            raise ValueError("changes 에는 schedule_id 와 base_version 이 필요합니다.")
        if self.changes == [] and self.conditions is None:
            raise ValueError("changes 가 비었으면 conditions 를 보냅니다.")
        return self


class SubmitOut(BaseModel):
    applied: bool  # 바로 저장했는가(false 면 승인함에서 결정을 기다린다)
    approval_id: int
    version: int | None  # 저장했으면 그 버전
    schedule_id: int | None  # 대상 일정(첫 저장은 저장한 뒤에 생긴다)
    reasons: list[str]  # 승인이 필요한 사유(app.agent.approval.Reason)


@dataclass(frozen=True)
class _Proposal:
    kind: str  # first_save | change
    before: Schedule | None
    before_conditions: list[dict]
    after: Schedule
    after_conditions: list[dict]
    schedule_id: int | None
    draft_id: int | None
    base_version: int


def _from_draft(ctx: ToolContext, draft_id: int) -> _Proposal:
    try:
        draft = get_draft(ctx.session, draft_id)
    except NotFound:
        raise ToolError(NO_DRAFT_MESSAGE) from None
    if draft.chat_session_id != ctx.chat_session_id:  # 둘 다 없으면(대화 밖) 같다고 본다
        raise ToolError(OTHER_CHAT_DRAFT_MESSAGE)
    if draft.used_at is not None:
        raise ToolError(USED_DRAFT_MESSAGE)
    if approvals.pending_for_draft(ctx.session, draft_id):
        raise ToolError(WAITING_DRAFT_MESSAGE)
    after = from_json(draft.schedule_json)
    return _Proposal("first_save", None, [], after, list(draft.conditions_json), None, draft_id, 0)


def _index(acts: list[Activity], aid: str) -> int:
    for n, a in enumerate(acts):
        if a.id == aid:
            return n
    raise ToolError(f"없는 액티비티입니다: {aid}")


def _relations(aid: str, preds: list[PredIn]) -> list[Relation]:
    return [Relation(p.pred, aid, p.type, p.lag) for p in preds]


def _new_activity(schedule: Schedule, acts: list[Activity], new: NewActivity) -> Activity:
    wbs_of = {a.id: a.wbs for a in acts}
    first = next((wbs_of[p.pred] for p in new.preds if p.pred in wbs_of), None)
    wbs = new.wbs or first or (schedule.wbs[0].code if schedule.wbs else "")
    if new.wbs is not None and new.wbs not in {w.code for w in schedule.wbs}:
        raise ToolError(f"없는 WBS 코드입니다: {new.wbs}")
    missing = [r for r in new.resources if r not in {x.id for x in schedule.resources}]
    if missing:
        raise ToolError(f"없는 자원입니다: {', '.join(missing)}")
    return Activity(new.id, new.name, "task", wbs, new.od, resources=tuple(new.resources), tags=tuple(new.tags))


def _apply_ops(schedule: Schedule, ops: list[UpdateOp | AddOp | DeleteOp]) -> Schedule:
    """고침을 차례대로 일정 사본에 넣는다. 계산 확인은 하지 않는다."""
    acts, rels = list(schedule.activities), list(schedule.relations)
    for op in ops:
        if isinstance(op, AddOp):
            acts.append(_new_activity(schedule, acts, op.activity))
            rels += _relations(op.activity.id, op.activity.preds)
            continue
        n = _index(acts, op.id)
        if isinstance(op, DeleteOp):
            del acts[n]
            rels = [r for r in rels if op.id not in (r.pred, r.succ)]
            continue
        a = acts[n]
        acts[n] = replace(a, od=a.od if op.od is None else op.od, name=op.name or a.name)
        if op.preds is not None:
            rels = [r for r in rels if r.succ != op.id] + _relations(op.id, op.preds)
    ids = {a.id for a in acts}
    missing = sorted({r.pred for r in rels if r.pred not in ids})  # 없는 id·지운 액티비티를 선행으로 가리킴
    if missing:
        raise ToolError(f"없는 액티비티를 가리킵니다: {', '.join(missing)}")
    return replace(schedule, activities=tuple(acts), relations=tuple(rels))


def _with_inputs(stored: list[dict], given: list[dict]) -> list[dict]:
    """저장된 조건에서 입력 겹(layer input)만 given 으로 바꾼다(다른 겹은 그 자리 그대로, 새 입력은 끝에)."""
    fresh = []
    for d in given:
        try:
            c = Condition.from_dict(d)
        except ConditionFormatError as e:
            raise ToolError(f"조건을 읽을 수 없습니다: {e.condition_id}: {e.message}") from None
        if c.layer != "input":
            raise ToolError(f"입력 조건(layer input)만 바꿀 수 있습니다: {c.id}")
        fresh.append(c.to_dict())
    return [d for d in stored if not (isinstance(d, dict) and d.get("layer") == "input")] + fresh


def _from_changes(ctx: ToolContext, args: SubmitIn) -> _Proposal:
    with explained_schedule_errors():
        before, stored, n = load(ctx.session, args.schedule_id)
    if args.base_version != n:
        raise ToolError(STALE_MESSAGE)
    after = _apply_ops(before, args.changes)
    conditions = stored if args.conditions is None else _with_inputs(stored, args.conditions)
    return _Proposal("change", before, stored, after, conditions, args.schedule_id, None, n)


def _effective(stored: list[dict]) -> dict[str, tuple]:
    """조립한 조건을 id → (종류, 값, 켜짐) 으로(차례·글·진 표시와 상관없이 비교하려고)."""
    return {c.id: (c.kind, c.params, c.enabled) for c in assemble_all(read_conditions(stored)[0])}


def _unchanged(p: _Proposal, changes: list[dict]) -> bool:
    """고침인데 일정도 조건도 그대로인가."""
    if p.before is None or changes:
        return False
    return _effective(p.before_conditions) == _effective(p.after_conditions)


def _out(row: Approval, applied: bool) -> SubmitOut:
    return SubmitOut(applied=applied, approval_id=row.id, version=row.version, schedule_id=row.schedule_id,
                     reasons=list(row.reasons_json))


@tool(
    "out.submit_change",
    "일정을 저장하거나 고친다. 새 일정 저장: {draft_id, title} (generate__run 의 draft_id). "
    "일정 고침: {schedule_id, base_version(읽은 지금 버전), changes, title} — changes 는 "
    "update_activity{id, od?, name?, preds?} · add_activity{activity:{id, name, od, preds, wbs?, resources?, tags?}} · "
    "delete_activity{id}. 조건을 바꿀 때만 conditions(입력 조건 전체)를 함께 보낸다. "
    "승인이 필요한지는 코드가 정한다(준공·마일스톤·크리티컬 패스 변경, 조건 위반·변경, 삭제 등). "
    "applied=false 면 승인함에서 사람이 결정할 때까지 반영되지 않았으니 저장했다고 말하지 않는다.",
    program="approvals",
    mutates=True,
)
def submit_change(args: SubmitIn, ctx: ToolContext) -> SubmitOut:
    p = _from_draft(ctx, args.draft_id) if args.draft_id is not None else _from_changes(ctx, args)
    try:
        run(p.after, p.after_conditions)  # 화면과 같은 계산이 되는지
    except ScheduleError as e:
        raise ToolError(schedule_error_message(e)) from None
    changes = schedule_changes(p.before, p.after) if p.before is not None else []
    if _unchanged(p, changes):
        raise ToolError(NO_CHANGE_MESSAGE)
    conditions, unreadable = read_conditions(p.after_conditions)
    report = check(p.after, assemble_all(conditions))
    report = replace(report, invalid=unreadable + report.invalid)  # 읽지 못한 저장 조건도 센다(harness.check 와 같음)
    result = assess(p.before, p.after, p.before_conditions, p.after_conditions, report,
                    mode=approval_mode(ctx.session))
    row = approvals.create(
        ctx.session, kind=p.kind, title=args.title, reasons_json=list(result.decision.reasons),
        schedule_id=p.schedule_id, draft_id=p.draft_id, base_version=p.base_version, summary_json=result.summary,
        diff_json=result.diff, snapshot_json=to_json(p.after), conditions_json=p.after_conditions,
        changes_json=changes, status="pending", request=approvals.last_request(ctx.session, ctx.chat_session_id),
        chat_session_id=ctx.chat_session_id, requested_by=ctx.user.name if ctx.user else approvals.AGENT_NAME,
    )
    if result.decision.needs_approval:
        ctx.emit(AgentEvent("approval", {"id": row.id, "title": row.title, "reasons": list(row.reasons_json),
                                         "summary": row.summary_json}))
        return _out(row, applied=False)
    try:
        approvals.apply(ctx.session, row, by_name=approvals.AGENT_NAME)
    except VersionConflict:
        raise ToolError(STALE_MESSAGE) from None
    except approvals.DraftUsed:
        raise ToolError(USED_DRAFT_MESSAGE) from None
    row.status = "auto"
    row.restore_to = p.base_version if p.kind == "change" else None  # 첫 저장은 되돌릴 버전이 없다
    ctx.emit(AgentEvent("card", {"kind": "auto_applied", "schedule_id": row.schedule_id, "version": row.version,
                                 "count": result.summary["changed_count"], "summary": row.summary_json}))
    return _out(row, applied=True)
