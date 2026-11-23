"""rules.propose — 사용자가 늘 쓰는 방식을 내 규칙(겹 mine 조건)으로 제안한다. 저장은 승인 뒤(store.links.after_apply).

- scope domain: 승인 건 kind 'rule'(사유 rule_save, 일정 없음, summary {rule}). 승인 수준을 따른다(auto 면 바로 저장).
  승인을 기다리면 사건 approval, 바로 저장하면 card {kind: "rule_saved", approval_id, rule}.
- scope schedule: 지금 일정에 그 조건을 더한 고침을 propose 로 낸다(link_kind 'rule', 사유에 rule_save).
  승인 건 summary 와 approval·auto_applied 사건의 summary 에도 분야 범위와 같은 rule 을 더한다.
  승인되면 새 버전에 조건이 들어가고 그 일정 범위의 내 규칙이 생긴다. 사건은 out.submit_change 와 같다.
분야는 주지 않으면 대상 일정의 분야. 조건 id 는 mine.<6자리 16진>, 출처 「내 규칙」.
"""

import secrets
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.approval import _needs
from app.agent.events import AgentEvent
from app.agent.ops import Strict
from app.agent.proposals import Proposal, ProposalError, propose
from app.domains.loader import is_valid_domain_id
from app.harness.conditions import Condition, validate_params
from app.store import approvals
from app.store.schedules import get_record, load
from app.store.settings import approval_mode
from app.tools.context import (
    NO_SCHEDULE_MESSAGE,
    ToolContext,
    ToolError,
    explained_schedule_errors,
)
from app.tools.registry import tool

RULE_KINDS = ("min_gap", "max_duration", "duration_per_unit", "text_only", "blocked_period", "calendar")
SOURCE = "내 규칙"
NO_DOMAIN_MESSAGE = "어느 분야의 규칙인지 알려 주세요."
TITLE_PREFIX = "내 규칙 저장 — "  # agent.context.rejection_text 가 이 앞글로 내 규칙 건을 알아본다


class RuleConditionIn(Strict):
    kind: str = Field(description="min_gap · max_duration · duration_per_unit · text_only · blocked_period · calendar")
    params: dict = Field(default_factory=dict, description="종류에 맞는 값(조건 params 와 같은 모양)")
    text: str = Field(min_length=1, max_length=200, description="사용자가 말한 규칙 글")


class ProposeRuleIn(Strict):
    scope: Literal["domain", "schedule"] = Field(description="domain = 그 분야의 새 일정 모두, schedule = 지금 일정만")
    domain: str | None = Field(default=None, description="분야 id(없으면 대상 일정의 분야)")
    condition: RuleConditionIn
    why: str = Field(min_length=1, max_length=200, description="규칙으로 두려는 까닭(사용자 말)")


class ProposeRuleOut(BaseModel):
    approval_id: int
    applied: bool  # 바로 저장했는가(false 면 승인함에서 결정을 기다린다)
    rule: dict  # {scope, domain, schedule_id, condition}


def _condition(args: RuleConditionIn) -> Condition:
    if args.kind not in RULE_KINDS:
        raise ToolError(f"내 규칙으로 둘 수 없는 종류입니다: {args.kind}")
    if (problem := validate_params(args.kind, args.params)) is not None:
        raise ToolError(problem)
    return Condition(f"mine.{secrets.token_hex(3)}", "mine", args.kind, dict(args.params), args.text, SOURCE)


def _domain(args: ProposeRuleIn, ctx: ToolContext) -> str:
    """분야 범위에 분야를 주면 그 분야, 아니면 대상 일정의 분야(일정 범위는 늘 그 일정의 분야)."""
    if args.scope == "domain" and args.domain is not None:
        if not is_valid_domain_id(args.domain):
            raise ToolError(f"올바르지 않은 분야입니다: {args.domain}")
        return args.domain.strip()
    if ctx.schedule_id is None:
        raise ToolError(NO_DOMAIN_MESSAGE if args.scope == "domain" else NO_SCHEDULE_MESSAGE)
    with explained_schedule_errors():
        return get_record(ctx.session, ctx.schedule_id).domain


def _domain_rule(ctx: ToolContext, rule: dict, summary: dict, requested_by: str) -> ProposeRuleOut:
    row = approvals.create(
        ctx.session, kind="rule", title=(TITLE_PREFIX + rule["condition"]["text"])[:100], reasons_json=["rule_save"],
        schedule_id=None, draft_id=None, base_version=0, summary_json={"rule": summary}, diff_json=[],
        snapshot_json={}, conditions_json=[], changes_json=[], status="pending",
        request=approvals.last_request(ctx.session, ctx.chat_session_id), chat_session_id=ctx.chat_session_id,
        requested_by=requested_by, requested_kind="agent", link_kind="rule", rule_json=rule,
    )
    if _needs(approval_mode(ctx.session), ["rule_save"]):
        ctx.emit(AgentEvent("approval", {"id": row.id, "title": row.title, "reasons": ["rule_save"],
                                         "summary": row.summary_json}))
        return ProposeRuleOut(approval_id=row.id, applied=False, rule=rule)
    approvals.apply(ctx.session, row, by_name=approvals.AGENT_NAME)
    row.status = "auto"
    ctx.emit(AgentEvent("card", {"kind": "rule_saved", "approval_id": row.id, "rule": rule}))
    return ProposeRuleOut(approval_id=row.id, applied=True, rule=rule)


def _with_rule(emit: Callable[[AgentEvent], None], summary: dict) -> Callable[[AgentEvent], None]:
    """propose 가 내는 approval·card auto_applied 사건의 summary 에 rule 을 더해 넘긴다(승인함 카드가 규칙을 보이게)."""
    def forward(e: AgentEvent) -> None:
        if e.type == "approval" or e.data.get("kind") == "auto_applied":
            e = AgentEvent(e.type, {**e.data, "summary": {**e.data["summary"], "rule": summary}})
        emit(e)
    return forward


def _schedule_rule(ctx: ToolContext, rule: dict, summary: dict, requested_by: str) -> ProposeRuleOut:
    """승인 건 summary = propose 요약 + rule(분야 범위와 같은 모양)."""
    sid = ctx.require_schedule_id()
    try:
        with explained_schedule_errors():
            before, stored, n = load(ctx.session, sid)
            p = Proposal(kind="change", title=(TITLE_PREFIX + rule["condition"]["text"])[:100], before=before,
                         before_conditions=stored, after=before, after_conditions=[*stored, rule["condition"]],
                         schedule_id=sid, draft_id=None, base_version=n, link_kind="rule", rule_json=rule)
            result = propose(ctx.session, p, chat_session_id=ctx.chat_session_id, requested_by=requested_by,
                             emit=_with_rule(ctx.emit, summary), extra_reasons=["rule_save"])
    except ProposalError as e:
        raise ToolError(e.message) from None
    result.row.summary_json = {**result.row.summary_json, "rule": summary}  # plan_change 는 approvals.create 가 넣었다
    return ProposeRuleOut(approval_id=result.row.id, applied=result.applied, rule=rule)


@tool(
    "rules.propose",
    "사용자가 늘 쓰는 방식을 내 규칙으로 제안한다: {scope: domain(그 분야 새 일정 모두)|schedule(지금 일정만), domain?, "
    "condition: {kind, params, text}, why}. 저장은 승인 뒤다. applied=false 면 아직 저장되지 않았다고 말한다.",
    program="conditions",
    mutates=True,
)
def propose_rule(args: ProposeRuleIn, ctx: ToolContext) -> ProposeRuleOut:
    condition = _condition(args.condition)
    domain = _domain(args, ctx)
    schedule_id = ctx.schedule_id if args.scope == "schedule" else None
    rule = {"scope": args.scope, "domain": domain, "schedule_id": schedule_id, "condition": condition.to_dict()}
    requested_by = ctx.user.name if ctx.user else approvals.AGENT_NAME
    summary = {"scope": args.scope, "domain": domain, "text": condition.text, "kind": condition.kind,
               "params": condition.params}
    if args.scope == "schedule":
        return _schedule_rule(ctx, rule, summary, requested_by)
    return _domain_rule(ctx, rule, summary, requested_by)
