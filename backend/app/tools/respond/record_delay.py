"""delay.record — 지연 사건을 적고 그 영향을 코드가 계산해 돌려준다. 저장된 일정·Plan 은 바꾸지 않는다.

source 'chat'(대화에서 말한 지연)은 열린 사건이 되고, 열린 사건을 모두 다시 분석한다(store.delays.report).
source 'actual'(실적 입력에서 감지 — 이미 일정에 들어감)은 before_version 이 있어야 하고, 바로 reflected
(reflected_version = 지금 버전)이며 영향 = core.delay.diff_impact(before_version 일정, 지금 일정)이다.
start_date 기본 = 일정의 data_date → context.today().
사건: card {kind: "delay_impact", schedule_id, event_id, activity_id, name, days, status, impact, totals} 와
open_window {program: "delays", params: {id, event}}.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent import context
from app.agent.events import AgentEvent
from app.core.delay import diff_impact
from app.core.model import Schedule
from app.harness.assemble import prepare_stored
from app.store import approvals, delays
from app.store.schedules import NotFound, load
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

NEED_BEFORE_MESSAGE = "실적에서 감지한 지연은 before_version 이 필요합니다."


class RecordDelayIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    activity_id: str = Field(min_length=1, max_length=50, description="지연된 액티비티 id(schedule__find 로 찾은 것)")
    days: int = Field(ge=1, le=365, description="지연 근무일 수")
    cause: str = Field(min_length=1, max_length=200, description="사용자가 말한 원인")
    responsibility: Literal["owner", "ours", "force", "undecided"] = Field(
        default="undecided", description="책임: owner 발주처 · ours 우리 · force 불가항력 · 모르면 undecided")
    daily_cost: int | None = Field(default=None, ge=0, description="사용자가 말한 하루 금액(원). 모르면 null")
    start_date: date | None = Field(default=None, description="지연이 생긴 날. 없으면 Data Date, 그것도 없으면 오늘")
    source: Literal["chat", "actual"] = Field(default="chat", description="actual = 실적 입력에서 감지한 지연")
    before_version: int | None = Field(default=None, description="source actual 일 때 실적 입력 전 버전")


class RecordDelayOut(BaseModel):
    event_id: int
    status: str  # open | reflected
    impact: dict | None
    totals: dict


def _before(ctx: ToolContext, schedule_id: int, version: int) -> Schedule:
    """실적 입력 전 버전을 조건 넣어 준비한 일정. 없는 버전이면 ToolError."""
    try:
        before, conditions, _ = load(ctx.session, schedule_id, version)
    except NotFound:
        raise ToolError(f"없는 버전입니다: {version}") from None
    return prepare_stored(before, conditions)


def _reflect(ctx: ToolContext, row: delays.DelayEventRow, before: Schedule) -> None:
    """실적에서 감지한 지연: 이미 지금 버전에 있다. 앞 버전 → 지금 버전의 차이를 그 사건의 영향으로 적는다."""
    now, conditions, n = load(ctx.session, row.schedule_id)
    impact = diff_impact(before, prepare_stored(now, conditions), event_id=str(row.id), days=row.days,
                         daily_cost=row.daily_cost)
    delays.update(ctx.session, row, reflected_version=n, impact_json=delays.impact_json(impact), analyzed_version=n)


@tool(
    "delay.record",
    "사용자가 말한 지연을 기록하고 영향을 계산한다: {activity_id, days, cause, responsibility?, daily_cost?, "
    "start_date?, source?, before_version?}. 원인·책임·하루 금액은 사용자가 말한 것만 넣는다. "
    "결과의 준공 영향·흡수된 일수·크리티컬 변화·비용은 코드가 계산한 값이다. 일정은 바뀌지 않는다.",
    program="delays",
    mutates=True,
)
def record_delay(args: RecordDelayIn, ctx: ToolContext) -> RecordDelayOut:
    schedule_id = ctx.require_schedule_id()
    if args.source == "actual" and args.before_version is None:
        raise ToolError(NEED_BEFORE_MESSAGE)
    with explained_schedule_errors():
        schedule, _, _ = load(ctx.session, schedule_id)
        target = next((a for a in schedule.activities if a.id == args.activity_id), None)
        if target is None:
            raise ToolError(f"없는 액티비티입니다: {args.activity_id}")
        actual = args.source == "actual"
        before = _before(ctx, schedule_id, args.before_version) if actual else None
        row = delays.create(
            ctx.session, schedule_id=schedule_id, activity_id=args.activity_id,
            start_date=args.start_date or schedule.data_date or context.today(), days=args.days, cause=args.cause,
            responsibility=args.responsibility, daily_cost=args.daily_cost, evidence="", source=args.source,
            created_by=ctx.user.name if ctx.user else approvals.AGENT_NAME,
            status="reflected" if actual else "open",
        )
        if before is not None:
            _reflect(ctx, row, before)
        data = delays.report(ctx.session, schedule_id)
    event = next(e for e in data["events"] if e["id"] == row.id)
    out = RecordDelayOut(event_id=row.id, status=row.status, impact=event["impact"], totals=data["totals"])
    ctx.emit(AgentEvent("card", {"kind": "delay_impact", "schedule_id": schedule_id, "event_id": row.id,
                                 "activity_id": target.id, "name": target.name, "days": row.days, "status": row.status,
                                 "impact": out.impact, "totals": out.totals}))
    ctx.emit(AgentEvent("open_window", {"program": "delays", "params": {"id": str(schedule_id), "event": str(row.id)}}))
    return out
