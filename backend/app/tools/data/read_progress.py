"""progress.read — 대상 일정의 공정률·SPI·WBS 진도·마일스톤·지연 Top5·향후 3주 예정 작업."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError
from app.programs.progress import service
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

_WBS_LIMIT = 20
_LOOKAHEAD_DATES_LIMIT = 15
_BLOCKED_LIMIT = 10


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = Field(default=None, description="조회할 일정 id(없으면 지금 일정)")
    unit: Literal["week", "month"] = Field(default="week", description="집계 단위(week|month)")


class ProgressReadOut(BaseModel):
    schedule_id: int
    version: int
    data_date: date
    plan_now: float
    actual_now: float
    gap: float
    spi: float | None
    finish: dict
    counts: dict
    wbs: list[dict]
    milestones: list[dict]
    top_delays: list[dict]
    lookahead: dict
    cpm: dict


@tool(
    "progress.read",
    "지금 일정의 공정률(계획·실적·차이·SPI), 준공 예측, WBS별 진도, 주요 마일스톤, 지연 Top 5, "
    "향후 3주 예정 작업(Lookahead)을 읽는다.",
    program="progress",
)
def read_progress(args: ProgressIn, ctx: ToolContext) -> ProgressReadOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        with explained_schedule_errors():
            out = service.progress(ctx.session, sid, args.unit)
    except ApiError as e:
        raise ToolError(e.message) from None

    look = out.lookahead.model_dump(mode="json", by_alias=True)
    look["starts"] = look["starts"][:_LOOKAHEAD_DATES_LIMIT]
    look["finishes"] = look["finishes"][:_LOOKAHEAD_DATES_LIMIT]
    look["blocked"] = look["blocked"][:_BLOCKED_LIMIT]

    return ProgressReadOut(
        schedule_id=out.schedule_id,
        version=out.version,
        data_date=out.data_date,
        plan_now=out.plan_now,
        actual_now=out.actual_now,
        gap=out.gap,
        spi=out.spi,
        finish=out.finish.model_dump(mode="json"),
        counts=out.counts.model_dump(mode="json"),
        wbs=[row.model_dump(mode="json") for row in out.wbs[:_WBS_LIMIT]],
        milestones=[row.model_dump(mode="json") for row in out.milestones],
        top_delays=[row.model_dump(mode="json") for row in out.top_delays],
        lookahead=look,
        cpm=out.cpm.model_dump(mode="json"),
    )
