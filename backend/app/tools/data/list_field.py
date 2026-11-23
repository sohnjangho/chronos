"""field.list — 대상 일정의 현장 점검 목록(일일 체크인·사진 AI 판독·만회안 의견·D-3 핸드오프)과 요약 집계(A6-3).

화면의 GET /api/schedules/{id}/field 와 같은 서비스(programs.progress.field.list_field)라 그 일정의 항목만 본다.
그 일정에 항목이 하나도 없으면 화면을 처음 열 때처럼 서비스가 시연 항목을 채운다.
- kind·status 로 거른 뒤 최근 것부터 ITEM_LIMIT 개. total 은 거른 항목 수, summary 는 거르기 전 그 일정 전체.
- 글은 TEXT_LIMIT 자, payload_json 의 목록은 LIST_LIMIT 개까지. 사진 원본(photo_data_url)은 넣지 않는다 —
  도구 결과 한도(4,000자) 안에 든다.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError
from app.programs.progress import field
from app.programs.progress.field import FieldSummary
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

ITEM_LIMIT = 4
TEXT_LIMIT = 70
LIST_LIMIT = 2
LEFT_OUT = {"photo_data_url"}  # 사진 원본(수십만 자)


class FieldListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = Field(default=None, description="조회할 일정 id(없으면 지금 일정)")
    kind: Literal["checkin", "photo", "poll", "handoff"] | None = Field(
        default=None, description="checkin 일일 체크인 · photo 사진 판독 · poll 만회안 의견 · handoff D-3 핸드오프")
    status: Literal["pending", "responded", "applied"] | None = Field(
        default=None, description="pending 회신 대기 · responded 회신함 · applied 반영함")


class FieldItemBrief(BaseModel):
    id: int
    kind: str
    activity_id: str
    activity_name: str
    trade: str
    status: str
    title: str
    response_choice: str | None
    reported_progress: int | None
    reported_rd: int | None
    response_note: str
    payload_json: dict[str, Any]  # 핸드오프는 checklist{material·equipment·workforce}·pred_handover_ok
    updated_at: datetime


class FieldListToolOut(BaseModel):
    schedule_id: int
    schedule_name: str
    summary: FieldSummary
    total: int  # 거른 항목 수(items 는 그 가운데 최근 ITEM_LIMIT 개)
    items: list[FieldItemBrief]


def _short(value: Any) -> Any:
    if isinstance(value, str):
        return value[:TEXT_LIMIT]
    if isinstance(value, list):
        return [_short(v) for v in value[:LIST_LIMIT]]
    if isinstance(value, dict):
        return {k: _short(v) for k, v in value.items() if k not in LEFT_OUT}
    return value


def _brief(item: field.FieldItemOut) -> FieldItemBrief:
    return FieldItemBrief(
        id=item.id, kind=item.kind, activity_id=item.activity_id, activity_name=_short(item.activity_name),
        trade=_short(item.trade), status=item.status, title=_short(item.title), response_choice=item.response_choice,
        reported_progress=item.reported_progress, reported_rd=item.reported_rd,
        response_note=_short(item.response_note), payload_json=_short(item.payload_json), updated_at=item.updated_at,
    )


@tool(
    "field.list",
    "대상 일정의 현장 점검 목록(일일 체크인·현장 사진 AI 판독·만회안 의견·D-3 핸드오프 자재/장비/인력 준비 상태)과 "
    f"요약 집계를 읽는다. kind·status 로 거를 수 있고 최근 항목부터 {ITEM_LIMIT}개를 준다(total 은 거른 항목 수).",
    program="progress",
)
def list_field(args: FieldListIn, ctx: ToolContext) -> FieldListToolOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        out = field.list_field(ctx.session, sid)
    except ApiError as e:
        raise ToolError(e.message) from None
    picked = [i for i in out.items if args.kind in (None, i.kind) and args.status in (None, i.status)]
    return FieldListToolOut(schedule_id=out.schedule_id, schedule_name=_short(out.schedule_name), summary=out.summary,
                            total=len(picked), items=[_brief(i) for i in picked[:ITEM_LIMIT]])
