"""scenario.create — 만약에 복사본을 만든다. 저장된 일정은 바꾸지 않는다.

지금 일정(base_version 이 지금 버전이어야 함)에 고침(changes)과 입력 조건(conditions)을 넣은 사본을 복사본 표에 둔다.
요약(준공·차이·위반·자원 최대)은 코드가 계산한다(store.scenarios.summarize). 반영은 비교판이나 scenario.submit 으로.
당김 효과(accel·accel_reason)는 바탕 버전과 견줘 끌어낸 이동으로 코드가 계산한다(store.scenarios.copy_accel).
사건: card {kind: "scenario_created", scenario_id, schedule_id, name, summary, accel, accel_reason} 와
open_window {program: "compare", params: {id, base: "current", other: "s:<id>"}}.
"""

from pydantic import BaseModel, Field

from app.agent.events import AgentEvent
from app.agent.ops import Op, OpError, Strict, apply_ops, with_inputs
from app.agent.proposals import STALE_MESSAGE, unchanged
from app.store import approvals, scenarios
from app.store.schedules import load, run
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

NO_CHANGE_MESSAGE = "바꾸는 것이 없는 복사본입니다."


class CreateScenarioIn(Strict):
    name: str = Field(min_length=1, max_length=100, description="복사본 이름(예: 크레인 2대면?)")
    base_version: int = Field(description="읽은 일정의 지금 버전")
    changes: list[Op] = Field(default_factory=list, max_length=100, description="고침 목록(차례대로 적용)")
    conditions: list[dict] | None = Field(default=None, description="입력 조건 전체(layer input). 바꿀 때만 보낸다")


class CreateScenarioOut(BaseModel):
    scenario_id: int
    summary: dict  # store.scenarios.summarize 의 요약
    accel: dict | None = None  # 당김 효과 {pulled_days, finish_gain, warn, next_chain}. 당김이 아니거나 셀 수 없으면 None
    accel_reason: str | None = None  # 여러 가지를 함께 바꿔 셀 수 없을 때의 까닭


@tool(
    "scenario.create",
    "'만약에 …면?' 을 일정을 바꾸지 않고 복사본으로 계산한다: {name, base_version(읽은 지금 버전), changes, conditions?}. "
    "changes 와 conditions 는 out__submit_change 와 같은 모양이다. 준공·차이·위반은 코드가 계산해 summary 로 준다. "
    "비교판이 열린다. 반영은 사람이 비교판에서 하거나 사용자가 반영하라고 할 때 scenario__submit 으로.",
    program="compare",
    mutates=True,
)
def create_scenario(args: CreateScenarioIn, ctx: ToolContext) -> CreateScenarioOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        before, stored, n = load(ctx.session, schedule_id)
    if args.base_version != n:
        raise ToolError(STALE_MESSAGE)
    try:
        after = apply_ops(before, args.changes)
        conditions = stored if args.conditions is None else with_inputs(stored, args.conditions)
    except OpError as e:
        raise ToolError(e.message) from None
    with explained_schedule_errors():
        run(after, conditions)  # 계산이 되는 복사본만
        if unchanged(before, stored, after, conditions):
            raise ToolError(NO_CHANGE_MESSAGE)
        row = scenarios.create(
            ctx.session, schedule_id=schedule_id, base_version=n, name=args.name, source="agent", schedule=after,
            conditions=conditions, created_by=ctx.user.name if ctx.user else approvals.AGENT_NAME,
        )
        accel, reason = scenarios.copy_accel(ctx.session, schedule_id, n, after, conditions)
    ctx.emit(AgentEvent("card", {"kind": "scenario_created", "scenario_id": row.id, "schedule_id": schedule_id,
                                 "name": row.name, "summary": row.summary_json, "accel": accel,
                                 "accel_reason": reason}))
    ctx.emit(AgentEvent("open_window", {"program": "compare",
                                        "params": {"id": str(schedule_id), "base": "current", "other": f"s:{row.id}"}}))
    return CreateScenarioOut(scenario_id=row.id, summary=row.summary_json, accel=accel, accel_reason=reason)
