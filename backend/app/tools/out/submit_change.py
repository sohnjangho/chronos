"""out.submit_change — 에이전트가 만든 변경을 내보낸다: 초안 저장(첫 저장) 또는 일정 고침.

승인이 필요한지는 코드(app.agent.proposals.propose → app.agent.approval.assess)가 승인 수준(settings 의
approval_mode)에 따라 정한다.
- 필요하면 승인 건(status pending)을 만들고 AgentEvent("approval", {id, title, reasons, summary}) 를 낸다.
- 아니면 바로 저장하고(by_kind "agent") 승인 표에 status auto 줄을 남긴 뒤(고침이면 되돌릴 버전 restore_to)
  AgentEvent("card", {kind: "auto_applied", schedule_id, version, count, summary}) 를 낸다.
쓰기는 flush 만 한다. 에이전트 루프가 성공한 도구 뒤에 commit 하고, 실패면 rollback 한다.
"""

from pydantic import BaseModel, Field, model_validator

from app.agent.ops import Op, OpError, Strict, apply_ops, with_inputs
from app.agent.proposals import Proposal, ProposalError, propose
from app.store import approvals
from app.store.drafts import get_draft
from app.store.schedules import NotFound, from_json, load
from app.store.tables import Approval
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

STALE_MESSAGE = "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."
USED_DRAFT_MESSAGE = "이미 저장한 초안입니다."
WAITING_DRAFT_MESSAGE = "이미 승인을 기다리는 초안입니다."
NO_DRAFT_MESSAGE = "초안을 찾을 수 없습니다."
OTHER_CHAT_DRAFT_MESSAGE = "이 대화의 초안이 아닙니다."


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


def _from_draft(ctx: ToolContext, args: SubmitIn) -> Proposal:
    try:
        draft = get_draft(ctx.session, args.draft_id)
    except NotFound:
        raise ToolError(NO_DRAFT_MESSAGE) from None
    if draft.chat_session_id != ctx.chat_session_id:  # 둘 다 없으면(대화 밖) 같다고 본다
        raise ToolError(OTHER_CHAT_DRAFT_MESSAGE)
    if draft.used_at is not None:
        raise ToolError(USED_DRAFT_MESSAGE)
    if approvals.pending_for_draft(ctx.session, args.draft_id):
        raise ToolError(WAITING_DRAFT_MESSAGE)
    after = from_json(draft.schedule_json)
    return Proposal("first_save", args.title, None, [], after, list(draft.conditions_json), None, args.draft_id, 0)


def _from_changes(ctx: ToolContext, args: SubmitIn) -> Proposal:
    with explained_schedule_errors():
        before, stored, n = load(ctx.session, args.schedule_id)
    if args.base_version != n:
        raise ToolError(STALE_MESSAGE)
    try:
        after = apply_ops(before, args.changes)
        conditions = stored if args.conditions is None else with_inputs(stored, args.conditions)
    except OpError as e:
        raise ToolError(e.message) from None
    return Proposal("change", args.title, before, stored, after, conditions, args.schedule_id, None, n)


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
    p = _from_draft(ctx, args) if args.draft_id is not None else _from_changes(ctx, args)
    try:
        result = propose(ctx.session, p, chat_session_id=ctx.chat_session_id,
                         requested_by=ctx.user.name if ctx.user else approvals.AGENT_NAME, emit=ctx.emit)
    except ProposalError as e:
        raise ToolError(e.message) from None
    return _out(result.row, applied=result.applied)
