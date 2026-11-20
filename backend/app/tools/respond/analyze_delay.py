"""delay.analyze — 지금 일정에 기록한 지연의 영향 묶음(코드가 계산). 저장된 일정·Plan 은 바꾸지 않는다.

열린 사건은 지금 버전으로 분석한 몫, 반영된 사건은 적어 둔 몫이다(store.delays.report — 지연 기록 API 와 같은 값).
finish = {plan, current, with_open, deadline, deadline_float}, totals = 책임별 준공 영향·흡수·비용 합.
"""

from pydantic import BaseModel

from app.store import delays
from app.tools.context import NoArgs, ToolContext, explained_schedule_errors
from app.tools.registry import tool


class EventSummary(BaseModel):
    event_id: int
    activity_id: str
    days: int
    status: str  # open | reflected
    finish_delta: int | None  # 근무일(영향이 없으면 null)
    absorbed: int | None


class AnalyzeDelayOut(BaseModel):
    finish: dict
    totals: dict
    events: list[EventSummary]


@tool(
    "delay.analyze",
    "기록한 지연 전체의 영향을 읽는다: 준공(Plan·지금·열린 지연 포함·기한 여유), 책임별 준공 영향, 흡수된 일수, 비용, "
    "사건마다 준공 영향과 흡수 일수. 모두 코드가 계산한 값이다.",
    program="delays",
)
def analyze_delay(args: NoArgs, ctx: ToolContext) -> AnalyzeDelayOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        data = delays.report(ctx.session, schedule_id)
    events = [
        EventSummary(event_id=e["id"], activity_id=e["activity_id"], days=e["days"], status=e["status"],
                     finish_delta=e["impact"]["finish_delta"] if e["impact"] else None,
                     absorbed=e["impact"]["absorbed"] if e["impact"] else None)
        for e in data["events"]
    ]
    return AnalyzeDelayOut(finish=data["finish"], totals=data["totals"], events=events)
