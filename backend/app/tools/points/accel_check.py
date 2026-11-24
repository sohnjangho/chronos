"""points.accel_check — 「〔작업〕을 n일 당기면?」 당긴 일수 가운데 준공에 반영되는 일수와 다음에 약속을 정하는 줄(읽기).

기준은 만회안(shorten.make)과 같다: 지금 버전에 열린 지연 사건을 넣고(store.delays.delayed_base) 저장 조건을 넣은 일정.
계산은 core.accel(엔진 값만). 경고 비율은 설정 accel_warn_ratio, 관리 포인트 표시는 설정 points_tf_days·points_window_weeks.
사건: card {kind: "accel_check", …}(출력과 같음). 일정은 바뀌지 않는다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.core.accel import AccelRefused, AccelResult, accel_effect, pull_request
from app.core.model import Schedule
from app.harness.assemble import prepare_stored
from app.store.delays import delayed_base
from app.store.settings import accel_warn_ratio, points_config
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

WARN_LINE = "당긴 {n}일 중 {m}일만 준공에 반영됩니다"
SUMMARY_LINE = "{name} {n}일 당김 → 준공 {m}일 당겨짐"


class ChainItem(BaseModel):
    activity_id: str
    name: str
    point: bool  # 관리 포인트인가


class AccelCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    activity_id: str = Field(min_length=1, max_length=50, description="당길 액티비티 id(schedule__find 로 찾은 것)")
    days: int = Field(ge=1, le=365, description="당길 근무일 수(그 작업 기간을 이만큼 줄인다, 최소 1일까지)")


class AccelCheckOut(BaseModel):
    kind: Literal["accel_check"] = "accel_check"
    schedule_id: int
    activity_id: str
    name: str
    od_before: int
    od_after: int
    pulled_days: int  # 당긴 일수
    reached_days: int  # 그 가운데 준공에 반영된 근무일
    ratio: float
    warn: bool  # 반영 비율이 accel_warn_ratio 보다 낮음
    warn_line: str | None  # 「당긴 n일 중 m일만 준공에 반영됩니다」(경고일 때만)
    summary_line: str  # 「〔작업〕 n일 당김 → 준공 m일 당겨짐」
    finish_before: str
    finish_after: str
    next_chain: list[ChainItem]  # 다음에 약속을 정하는 줄(위상 순)
    same_chain: bool  # 당긴 뒤에도 같은 줄이 약속을 정한다


def chain_items(schedule: Schedule, result: AccelResult) -> list[dict]:
    """다음 결정 줄을 이름·관리 포인트 표시와 함께(만회안 카드·비교판도 같은 꼴)."""
    names = {a.id: a.name for a in schedule.activities}
    points = set(result.next_chain_points)
    return [{"activity_id": i, "name": names[i], "point": i in points} for i in result.next_chain]


def warn_line(result: AccelResult) -> str | None:
    if not result.warn or result.pulled_days <= 0:
        return None
    return WARN_LINE.format(n=result.pulled_days, m=result.finish_gain)


@tool(
    "points.accel_check",
    "작업을 당기면 준공이 실제로 당겨지는지 본다: {activity_id, days}. 그 작업 기간을 days 만큼 줄여(최소 1일, 실적 있는 "
    "작업은 안 됨) 당긴 일수 가운데 준공에 반영되는 일수와, 당긴 뒤 약속을 정하는 다음 줄(관리 포인트 표시)을 코드가 "
    "계산한다. 일정은 바뀌지 않는다.",
)
def accel_check(args: AccelCheckIn, ctx: ToolContext) -> AccelCheckOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        db = delayed_base(ctx.session, schedule_id)
        ready = prepare_stored(db.schedule, db.conditions)
        try:
            moves = pull_request(ready, args.activity_id, args.days)
        except AccelRefused as e:
            raise ToolError(str(e)) from None
        cfg = points_config(ctx.session)
        result = accel_effect(ready, moves, warn_ratio=accel_warn_ratio(ctx.session), tf_days=cfg.tf_days,
                              window_weeks=cfg.window_weeks)
    a = next(a for a in ready.activities if a.id == args.activity_id)
    out = AccelCheckOut(
        schedule_id=schedule_id, activity_id=a.id, name=a.name, od_before=a.od, od_after=moves[0].od,
        pulled_days=result.pulled_days, reached_days=result.finish_gain, ratio=result.ratio, warn=result.warn,
        warn_line=warn_line(result),
        summary_line=SUMMARY_LINE.format(name=a.name, n=result.pulled_days, m=result.finish_gain),
        finish_before=result.finish_before.isoformat(), finish_after=result.finish_after.isoformat(),
        next_chain=chain_items(ready, result), same_chain=result.same_chain,
    )
    ctx.emit(AgentEvent("card", out.model_dump(mode="json")))
    return out
