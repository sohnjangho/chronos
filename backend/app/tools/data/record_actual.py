"""schedule.record_actual — 사용자가 말한 실적(진도·실제 시작·실제 종료)을 일정에 넣는다. 바로 반영하고 되돌릴 수 있다.

빈칸은 코드가 채우고 assumed 에 적는다(LLM 은 날짜를 계산하지 않는다):
- Data Date = 인자 → 일정의 data_date → context.today(). 인자가 있고 일정 것과 다르면 일정 data_date 도 바꾼다.
- actual_finish 가 있으면 진도 1. 진도 > 0 인데 실제 시작이 없으면 지금 계산 ES(≤ Data Date) 또는 Data Date.
  진도 1 인데 실제 종료가 없으면 Data Date. 진행 중(task)이면 rd = max(1, ceil(od × (1 − 진도))).
- 실적 날짜 > Data Date · 종료 < 시작 · 마일스톤 진도 0·1 밖 · 없는 id 는 ToolError.
저장은 propose(kind change, force_auto=True) — 준공이 바뀌어도 바로 반영하고 승인 표에 auto·restore_to 줄을 남긴다.
지연: 그 액티비티의 Plan 대비 늦음(근무일)이 저장 뒤에 늘었으면 delay = {activity_id, late_days(는 일수), finish_delta}.
사건: card {kind: "actual_recorded", schedule_id, activity_id, name, progress, assumed, delay, version}.
"""

from dataclasses import replace
from datetime import date
from math import ceil

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent import context
from app.agent.events import AgentEvent
from app.agent.proposals import Proposal, ProposalError, propose
from app.core.calendar import WorkCalendar
from app.core.model import Activity, Schedule
from app.harness.assemble import prepare_stored
from app.store import approvals
from app.store.schedules import load
from app.store.view import view_data
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

NEED_ONE_MESSAGE = "progress·actual_start·actual_finish 가운데 적어도 하나가 있어야 합니다."
ORDER_MESSAGE = "실제 종료일이 실제 시작일보다 앞설 수 없습니다."
MILESTONE_MESSAGE = "마일스톤은 진도 0 또는 1만 넣을 수 있습니다."


class RecordActualIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    activity_id: str = Field(min_length=1, max_length=50, description="액티비티 id(schedule__find 로 찾은 것)")
    progress: float | None = Field(default=None, ge=0, le=1, description="진도 0~1(60% 는 0.6). 말하지 않았으면 null")
    actual_start: date | None = Field(default=None, description="실제 시작일(날짜 도우미의 날짜). 모르면 null")
    actual_finish: date | None = Field(default=None, description="실제 종료일(날짜 도우미의 날짜). 모르면 null")
    data_date: date | None = Field(default=None, description="실적 기준일. 말하지 않았으면 null(일정 Data Date → 오늘)")

    @model_validator(mode="after")
    def _one_actual(self) -> "RecordActualIn":
        if self.progress is None and self.actual_start is None and self.actual_finish is None:
            raise ValueError(NEED_ONE_MESSAGE)
        return self


class ActivityOut(BaseModel):
    id: str
    name: str
    progress: float
    actual_start: date | None
    actual_finish: date | None
    rd: int | None
    es: date
    ef: date
    status: str


class DelayOut(BaseModel):
    activity_id: str
    late_days: int  # Plan 대비 늦음이 는 근무일 수
    finish_delta: int  # 전 준공 → 뒤 준공, 근무일


class FinishOut(BaseModel):
    before: date
    after: date


class RecordActualOut(BaseModel):
    version: int
    applied: bool
    approval_id: int
    data_date: date
    activity: ActivityOut
    assumed: list[str]
    finish: FinishOut
    delay: DelayOut | None
    before_version: int
    after_version: int


def _start(a: Activity, progress: float, start: date | None, es: date, dd: date, assumed: list[str]) -> date | None:
    """진도가 있는데 실제 시작이 없으면 계산 ES(≤ Data Date) 또는 Data Date."""
    if progress <= 0 or start is not None:
        return start
    start, why = (es, "계획 시작일") if es <= dd else (dd, "Data Date")
    assumed.append(f"실제 시작일을 {start.isoformat()}로 두었습니다({why}).")
    return start


def _filled(a: Activity, args: RecordActualIn, es: date, dd: date) -> tuple[Activity, list[str]]:
    """인자를 넣고 빈칸을 채운 액티비티와 채운 것의 설명."""
    finish = args.actual_finish
    if finish is None and (args.progress is None or args.progress >= 1):
        finish = a.actual_finish  # 진도를 1 밑으로 말하면 끝나지 않은 것이다
    progress = 1.0 if finish is not None else (a.progress if args.progress is None else args.progress)
    if a.kind != "task" and progress not in (0, 1):
        raise ToolError(MILESTONE_MESSAGE)
    assumed: list[str] = []
    start = _start(a, progress, args.actual_start or a.actual_start, es, dd, assumed)
    if progress >= 1 and finish is None:
        finish = dd
        assumed.append(f"실제 종료일을 Data Date {dd.isoformat()}로 두었습니다.")
    rd = None if finish is not None else a.rd
    if a.kind == "task" and start is not None and finish is None:
        rd = max(1, ceil(round(a.od * (1 - progress), 6)))
        assumed.append(f"남은 기간을 {rd}일로 두었습니다(원래 기간 × (1 − 진도)).")
    return replace(a, progress=progress, actual_start=start, actual_finish=finish, rd=rd), assumed


def _checked(a: Activity, dd: date) -> None:
    """실적 날짜는 Data Date 뒤일 수 없고, 종료는 시작보다 앞설 수 없다."""
    if any(d is not None and d > dd for d in (a.actual_start, a.actual_finish)):
        raise ToolError(f"실적 날짜가 Data Date({dd.isoformat()})보다 뒤일 수 없습니다.")
    if a.actual_start and a.actual_finish and a.actual_finish < a.actual_start:
        raise ToolError(ORDER_MESSAGE)


def _late(cal: WorkCalendar, row: dict) -> int:
    """Plan 종료 대비 늦은 근무일(앞섰거나 Plan 이 없으면 0)."""
    if row["plan_finish"] is None:
        return 0
    return max(0, cal.workdays_between(row["plan_finish"], row["ef"], tuple(row["tags"])))


def _calendar(schedule: Schedule, conditions: list[dict]) -> WorkCalendar:
    """조건을 넣은 달력(일정 보기가 늦음을 세는 달력)."""
    return WorkCalendar(prepare_stored(schedule, conditions).calendar)


def _row(view: dict, aid: str) -> dict:
    return next(r for r in view["activities"] if r["id"] == aid)


def _save(ctx: ToolContext, schedule_id: int, before: Schedule, after: Schedule, conditions: list[dict], n: int,
          title: str) -> int:
    """바로 반영하고 승인 건 id 를 돌려준다."""
    p = Proposal(kind="change", title=title, before=before, before_conditions=conditions, after=after,
                 after_conditions=conditions, schedule_id=schedule_id, draft_id=None, base_version=n,
                 requested_kind="agent")
    try:
        result = propose(ctx.session, p, chat_session_id=ctx.chat_session_id,
                         requested_by=ctx.user.name if ctx.user else approvals.AGENT_NAME, force_auto=True)
    except ProposalError as e:
        raise ToolError(e.message) from None
    return result.row.id


@tool(
    "schedule.record_actual",
    "사용자가 말한 실적을 일정에 넣는다: {activity_id, progress?(0~1), actual_start?, actual_finish?, data_date?}. "
    "셋 가운데 적어도 하나. 빈 실제 시작·종료·남은 기간은 코드가 채우고 assumed 에 적는다(꼭 사용자에게 말한다). "
    "바로 반영되고 되돌릴 수 있다. Plan 보다 늦어졌으면 delay 가 온다.",
    program="schedule-table",
    mutates=True,
)
def record_actual(args: RecordActualIn, ctx: ToolContext) -> RecordActualOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        before_view = view_data(ctx.session, schedule_id)
        schedule, conditions, n = load(ctx.session, schedule_id)
        target = next((a for a in schedule.activities if a.id == args.activity_id), None)
        if target is None:
            raise ToolError(f"없는 액티비티입니다: {args.activity_id}")
        dd = args.data_date or schedule.data_date or context.today()
        updated, assumed = _filled(target, args, _row(before_view, target.id)["es"], dd)
        _checked(updated, dd)
        after = replace(schedule, activities=tuple(updated if a.id == target.id else a for a in schedule.activities),
                        data_date=args.data_date or schedule.data_date)
        approval_id = _save(ctx, schedule_id, schedule, after, conditions, n,
                            f"{target.id} 실적 {round(updated.progress * 100, 1):g}%")
        after_view = view_data(ctx.session, schedule_id)
        row = _row(after_view, target.id)
        grew = _late(_calendar(after, conditions), row) - _late(_calendar(schedule, conditions),
                                                                _row(before_view, target.id))
        finish_delta = _calendar(after, conditions).workdays_between(before_view["finish"], after_view["finish"])
    delay = DelayOut(activity_id=target.id, late_days=grew, finish_delta=finish_delta) if grew > 0 else None
    out = RecordActualOut(
        version=after_view["version"], applied=True, approval_id=approval_id, data_date=dd,
        activity=ActivityOut.model_validate(row), assumed=assumed,
        finish=FinishOut(before=before_view["finish"], after=after_view["finish"]), delay=delay,
        before_version=n, after_version=after_view["version"],
    )
    ctx.emit(AgentEvent("card", {"kind": "actual_recorded", "schedule_id": schedule_id, "activity_id": target.id,
                                 "name": target.name, "progress": updated.progress, "assumed": assumed,
                                 "delay": delay.model_dump() if delay else None, "version": out.version}))
    return out
