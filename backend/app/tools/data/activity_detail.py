"""schedule.activity_detail — 액티비티 상세(기간·선후행·자원·꼬리표·WBS 경로) 또는 자원·꼬리표별 작업 찾기."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.model import Schedule
from app.store.schedules import load
from app.store.view import view_data
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool


class ActivityDetailIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    activity_id: str | None = Field(default=None, description="상세 조회할 액티비티 id")
    resource_id: str | None = Field(default=None, description="특정 자원 id 또는 자원명이 배정된 액티비티 목록 조회")
    tag: str | None = Field(default=None, description="특정 꼬리표(tag)가 붙은 액티비티 목록 조회")
    schedule_id: int | None = Field(default=None, description="조회할 일정 id(없으면 지금 일정)")
    limit: int = Field(default=20, ge=1, le=50, description="필터 조회 시 최대 결과 수")

    @model_validator(mode="after")
    def _need_query(self) -> "ActivityDetailIn":
        if not any((self.activity_id, self.resource_id, self.tag)):
            raise ValueError("activity_id, resource_id, tag 중 하나 이상을 보내야 합니다.")
        return self


class RelationOut(BaseModel):
    id: str
    name: str
    type: str
    lag: int
    critical: bool


class ActivityDetailItem(BaseModel):
    id: str
    name: str
    kind: str
    wbs: str
    wbs_path: str
    od: int
    rd: int | None
    progress: float
    es: date
    ef: date
    ls: date
    lf: date
    tf: int
    ff: int
    critical: bool
    status: str
    actual_start: date | None
    actual_finish: date | None
    resources: list[str]
    tags: list[str]
    predecessors: list[RelationOut]
    successors: list[RelationOut]


class ActivityMatchSummary(BaseModel):
    id: str
    name: str
    wbs: str
    wbs_path: str
    od: int
    es: date
    ef: date
    tf: int
    critical: bool
    status: str
    resources: list[str]
    tags: list[str]


class ActivityDetailOut(BaseModel):
    detail: ActivityDetailItem | None = None
    matches: list[ActivityMatchSummary] = Field(default_factory=list)
    total_matched: int = 0


def _wbs_path(schedule: Schedule, code: str) -> str:
    by_code = {w.code: w for w in schedule.wbs}
    parts: list[str] = []
    seen: set[str] = set()
    cur: str | None = code
    while cur and cur not in seen and cur in by_code:
        seen.add(cur)
        node = by_code[cur]
        parts.append(f"{node.code} {node.name}".strip())
        cur = node.parent
    return " > ".join(reversed(parts)) if parts else code


@tool(
    "schedule.activity_detail",
    "액티비티의 기간(od)·선행/후행 관계·배정 자원·꼬리표(tags)·WBS 경로를 조회하거나, "
    "특정 자원/꼬리표가 붙은 액티비티 목록을 찾는다.",
    program="schedule-table",
)
def get_activity_detail(args: ActivityDetailIn, ctx: ToolContext) -> ActivityDetailOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    with explained_schedule_errors():
        schedule, _, _ = load(ctx.session, sid)
        view = view_data(ctx.session, sid)

    act_model = {a.id: a for a in schedule.activities}
    view_by_id = {a["id"]: a for a in view["activities"]}
    res_names = {r.id: r.name for r in schedule.resources}

    if args.activity_id:
        aid_lower = args.activity_id.lower()
        target = next((v for v in view["activities"] if v["id"].lower() == aid_lower), None)
        if target is None:
            raise ToolError(f"액티비티를 찾을 수 없습니다: {args.activity_id}")
        aid = target["id"]
        model = act_model[aid]
        preds = [
            RelationOut(
                id=r.pred,
                name=view_by_id[r.pred]["name"],
                type=r.type,
                lag=r.lag,
                critical=bool(view_by_id[r.pred]["critical"]),
            )
            for r in schedule.relations
            if r.succ == aid and r.pred in view_by_id
        ]
        succs = [
            RelationOut(
                id=r.succ,
                name=view_by_id[r.succ]["name"],
                type=r.type,
                lag=r.lag,
                critical=bool(view_by_id[r.succ]["critical"]),
            )
            for r in schedule.relations
            if r.pred == aid and r.succ in view_by_id
        ]
        return ActivityDetailOut(
            detail=ActivityDetailItem(
                id=aid,
                name=target["name"],
                kind=target["kind"],
                wbs=target["wbs"],
                wbs_path=_wbs_path(schedule, target["wbs"]),
                od=model.od,
                rd=model.rd,
                progress=target["progress"],
                es=target["es"],
                ef=target["ef"],
                ls=target["ls"],
                lf=target["lf"],
                tf=target["tf"],
                ff=target["ff"],
                critical=target["critical"],
                status=target["status"],
                actual_start=target["actual_start"],
                actual_finish=target["actual_finish"],
                resources=list(model.resources),
                tags=list(model.tags),
                predecessors=preds,
                successors=succs,
            )
        )

    res_q = args.resource_id.lower() if args.resource_id else None
    tag_q = args.tag.lower() if args.tag else None
    matched: list[ActivityMatchSummary] = []
    for row in view["activities"]:
        model = act_model[row["id"]]
        if res_q is not None and not any(
            res_q in rid.lower() or res_q in res_names.get(rid, "").lower()
            for rid in model.resources
        ):
            continue
        if tag_q is not None and not any(tag_q in t.lower() for t in model.tags):
            continue
        matched.append(
            ActivityMatchSummary(
                id=row["id"],
                name=row["name"],
                wbs=row["wbs"],
                wbs_path=_wbs_path(schedule, row["wbs"]),
                od=model.od,
                es=row["es"],
                ef=row["ef"],
                tf=row["tf"],
                critical=row["critical"],
                status=row["status"],
                resources=list(model.resources),
                tags=list(model.tags),
            )
        )
    return ActivityDetailOut(matches=matched[: args.limit], total_matched=len(matched))
