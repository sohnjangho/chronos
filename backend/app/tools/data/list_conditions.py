"""conditions.list — 대상 일정의 모든 조건·제약(기본·분야·내 규칙·입력)과 자원 용량·점검 상태."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.harness.assemble import assemble_all
from app.harness.checks import check
from app.harness.conditions import read_conditions
from app.store.schedules import load
from app.tools.context import ToolContext, explained_schedule_errors
from app.tools.registry import tool


class ListConditionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = Field(default=None, description="조회할 일정 id(없으면 지금 일정)")
    layer: Literal["base", "domain", "mine", "input"] | None = Field(
        default=None,
        description="특정 겹만 조회(base|domain|mine|input)",
    )
    enabled_only: bool = Field(default=False, description="켜진 조건만 볼지 여부")


class ConditionItemOut(BaseModel):
    id: str
    layer: str
    kind: str
    params: dict
    text: str
    source: str
    enabled: bool
    overridden_by: str | None
    checkable: bool
    state: Literal["passed", "violated", "uncheckable", "off"]
    message: str | None


class ResourceCapOut(BaseModel):
    id: str
    name: str
    unit: str
    capacity: int


class ListConditionsOut(BaseModel):
    schedule_id: int
    version: int
    conditions: list[ConditionItemOut]
    resources: list[ResourceCapOut]
    invalid_count: int


@tool(
    "conditions.list",
    "지금 일정에 적용된 모든 조건·제약(기본·분야·내 규칙·입력 조건)의 원문, 파라미터, 활성 여부, "
    "통과/위반 상태와 자원 용량을 읽는다.",
    program="conditions",
)
def list_conditions(args: ListConditionsIn, ctx: ToolContext) -> ListConditionsOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    with explained_schedule_errors():
        schedule, stored, version = load(ctx.session, sid)
    readable, invalid = read_conditions(stored)
    assembled = assemble_all(readable)
    report = check(schedule, assembled)
    violations_by_id = {v.condition_id: v.message for v in report.violations}
    unchecked = set(report.uncheckable) | set(report.skipped)

    out_conditions: list[ConditionItemOut] = []
    for c in assembled:
        if args.layer is not None and c.layer != args.layer:
            continue
        if args.enabled_only and not c.enabled:
            continue
        if not c.enabled:
            state: Literal["passed", "violated", "uncheckable", "off"] = "off"
            message = None
        elif c.id in violations_by_id:
            state = "violated"
            message = violations_by_id[c.id]
        elif c.id in unchecked:
            state = "uncheckable"
            message = None
        else:
            state = "passed"
            message = None
        out_conditions.append(
            ConditionItemOut(
                id=c.id,
                layer=c.layer,
                kind=c.kind,
                params=dict(c.params),
                text=c.text,
                source=c.source,
                enabled=c.enabled,
                overridden_by=c.overridden_by,
                checkable=c.checkable,
                state=state,
                message=message,
            )
        )

    resources = [
        ResourceCapOut(id=r.id, name=r.name, unit=r.unit, capacity=r.capacity)
        for r in schedule.resources
    ]
    return ListConditionsOut(
        schedule_id=sid,
        version=version,
        conditions=out_conditions,
        resources=resources,
        invalid_count=len(invalid),
    )
