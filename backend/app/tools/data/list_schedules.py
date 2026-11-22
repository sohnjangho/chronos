"""schedule.list — 전체 프로젝트 일정 목록과 위험도·준공·지연 요약."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.programs.attention import service
from app.tools.context import ToolContext
from app.tools.registry import tool


class ListSchedulesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["danger", "warning", "ok"] | None = Field(
        default=None,
        description="위험도 필터(danger|warning|ok). 없으면 전체",
    )


class ScheduleSummaryItem(BaseModel):
    id: int
    name: str
    domain: str
    level: Literal["danger", "warning", "ok"]
    finish: date | None
    plan_finish: date | None
    finish_delta: int | None
    late_count: int
    negative_float_count: int
    open_delays: int
    violations: int


class ListSchedulesOut(BaseModel):
    total: int
    danger_count: int
    warning_count: int
    ok_count: int
    items: list[ScheduleSummaryItem]


@tool(
    "schedule.list",
    "전체 프로젝트 일정 목록과 각 일정의 위험도(danger·warning·ok), 준공일, Plan 대비 차이, 지연·위반 건수를 읽는다.",
    program="explorer",
)
def list_schedules(args: ListSchedulesIn, ctx: ToolContext) -> ListSchedulesOut:
    att = service.attention(ctx.session)
    all_items = [
        ScheduleSummaryItem(
            id=item.id,
            name=item.name,
            domain=item.domain,
            level=item.level,
            finish=item.finish,
            plan_finish=item.plan_finish,
            finish_delta=item.finish_delta,
            late_count=item.late_count,
            negative_float_count=item.negative_float_count,
            open_delays=item.open_delays,
            violations=item.violations,
        )
        for item in att.items
    ]
    shown = [i for i in all_items if args.level is None or i.level == args.level]
    return ListSchedulesOut(
        total=len(all_items),
        danger_count=sum(1 for i in all_items if i.level == "danger"),
        warning_count=sum(1 for i in all_items if i.level == "warning"),
        ok_count=sum(1 for i in all_items if i.level == "ok"),
        items=shown,
    )
