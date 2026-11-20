"""evidence.attach — 찾은 근거(evidence_id)를 일정이나 초안의 조건·가정에 붙인다(evidence_links, flush 만).

대상은 일정(schedule_id)과 초안(draft_id) 가운데 하나, 항목마다 조건(condition_id)과 가정(assumption_label)
가운데 하나. 초안이 승인되어 일정이 되면 초안에 붙인 근거도 그 일정의 조건 화면·근거 목록에 보인다.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.store.drafts import get_draft
from app.store.evidence import existing_ids, link
from app.store.schedules import NotFound, get_record
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

ONE_TARGET_MESSAGE = "schedule_id 와 draft_id 가운데 하나만 주세요."
ONE_SUBJECT_MESSAGE = "항목마다 condition_id 와 assumption_label 가운데 하나만 주세요."


class AttachItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: int = Field(description="evidence__search 결과의 evidence_id")
    condition_id: str | None = Field(default=None, min_length=1, max_length=100, description="받친 조건 id(예: in.finish_by)")
    assumption_label: str | None = Field(default=None, min_length=1, max_length=100, description="받친 가정의 label")


class AttachIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = Field(default=None, description="근거를 붙일 일정")
    draft_id: int | None = Field(default=None, description="근거를 붙일 초안(generate__run 의 draft_id)")
    items: list[AttachItem] = Field(min_length=1, max_length=10)


class AttachOut(BaseModel):
    linked: int  # 새로 붙인 수(이미 있던 같은 링크는 세지 않는다)


def _check_target(args: AttachIn, ctx: ToolContext) -> None:
    if (args.schedule_id is None) == (args.draft_id is None):
        raise ToolError(ONE_TARGET_MESSAGE)
    if args.schedule_id is not None:
        with explained_schedule_errors():
            get_record(ctx.session, args.schedule_id)
        return
    try:
        get_draft(ctx.session, args.draft_id)
    except NotFound:
        raise ToolError(f"없는 초안입니다: {args.draft_id}") from None


@tool(
    "evidence.attach",
    "찾은 근거(evidence_id)를 초안(draft_id)이나 일정(schedule_id) 하나에 붙인다. 항목마다 그 근거가 받친 "
    "조건(condition_id)이나 가정(assumption_label) 하나를 적는다. 붙인 근거는 조건 화면에 출처 링크로 보인다.",
    mutates=True,
)
def attach_evidence(args: AttachIn, ctx: ToolContext) -> AttachOut:
    _check_target(args, ctx)
    if any((i.condition_id is None) == (i.assumption_label is None) for i in args.items):
        raise ToolError(ONE_SUBJECT_MESSAGE)
    known = existing_ids(ctx.session, (i.evidence_id for i in args.items))
    missing = next((i.evidence_id for i in args.items if i.evidence_id not in known), None)
    if missing is not None:
        raise ToolError(f"없는 근거입니다: {missing}")
    linked = sum(
        link(ctx.session, evidence_ids=[i.evidence_id], schedule_id=args.schedule_id, draft_id=args.draft_id,
             condition_id=i.condition_id, assumption_label=i.assumption_label)
        for i in args.items
    )
    return AttachOut(linked=linked)
