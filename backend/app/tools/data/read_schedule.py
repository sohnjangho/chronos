"""schedule.read — 대상 일정의 요약."""

from datetime import date

from pydantic import BaseModel

from app.store.schedules import load
from app.store.view import view_data
from app.tools.context import NoArgs, ToolContext, explained_schedule_errors
from app.tools.registry import tool


class SummaryOut(BaseModel):
    critical_count: int
    negative_float_count: int
    warning_count: int


class ReadScheduleOut(BaseModel):
    name: str
    domain: str
    level: str
    version: int
    finish: date
    activity_count: int
    critical: list[str]  # 주공정 액티비티 id (일정 순서대로)
    condition_count: int
    summary: SummaryOut


@tool(
    "schedule.read",
    "지금 일정의 요약을 읽는다: 이름·수준·버전·준공일·액티비티 수·주공정 액티비티·조건 수.",
    program="schedule",
)
def read_schedule(args: NoArgs, ctx: ToolContext) -> ReadScheduleOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        view = view_data(ctx.session, schedule_id)
    _, conditions, _ = load(ctx.session, schedule_id, view["version"])
    return ReadScheduleOut(
        name=view["name"],
        domain=view["domain"],
        level=view["level"],
        version=view["version"],
        finish=view["finish"],
        activity_count=len(view["activities"]),
        critical=[a["id"] for a in view["activities"] if a["critical"]],
        condition_count=len(conditions),
        summary=view["summary"],
    )
