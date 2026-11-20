"""visual.make — 보고서·요약 그림 한 장. 표(열·단위·값)는 저장된 일정에서 코드가 만들고(인자에 숫자 없음),
Liner Visualization 이 그린 HTML 은 코드가 숫자 대조를 한다(app.llm.visualization). 일정은 바뀌지 않는다.

같은 입력의 통과한 그림이 있으면 다시 부르지 않는다. 대조가 두 번 실패하거나 Liner 를 부를 수 없으면 우리 그림(SVG)으로
대신하고 note 에 까닭을 적는다(그래도 ok). 그릴 자료가 없으면 ToolError. Liner 를 부르기 전에 commit 한다.
사건: card {kind: "visual", visual_id, schedule_id, visual_kind, title, version, data_date, verified, passed, total,
fallback, note}.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent import context
from app.agent.events import AgentEvent
from app.llm import visualization
from app.store import approvals
from app.store.visuals import TableError
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

VisualKind = Literal["summary", "delay_impact", "scenario_compare", "s_curve", "resource_load"]


class MakeVisualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: VisualKind = Field(description="summary 일정 요약(크리티컬 패스) · delay_impact 지연 영향 · "
                                         "scenario_compare 만약에 안 비교 · s_curve 진행 S-커브 · resource_load 자원 부하")
    schedule_id: int | None = Field(default=None, description="일정 id. 없으면 지금 다루는 일정")
    version: int | None = Field(default=None, description="버전 번호(summary·resource_load 만). 없으면 지금 버전")


class MakeVisualOut(BaseModel):
    visual_id: int
    title: str
    version: int
    verified: bool
    passed: int
    total: int
    fallback: bool
    note: str
    theme: str


@tool(
    "visual.make",
    "보고서·요약용 그림 한 장을 만든다: {kind, schedule_id?, version?}. 표의 값은 코드가 저장된 일정에서 만들고 "
    "Liner Visualization 이 그린다. 그린 그림은 코드가 숫자를 대조한다(통과 n/n). 값을 인자로 넣지 않는다. "
    "앱 안의 간트·S-커브는 창에서 본다 — 이 도구는 보고서용 그림이 필요할 때만 쓴다. 20~30초 걸린다.",
    mutates=True,
)
async def make_visual(args: MakeVisualIn, ctx: ToolContext) -> MakeVisualOut:
    schedule_id = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    with explained_schedule_errors():
        try:
            row = await visualization.make(
                ctx.session, kind=args.kind, schedule_id=schedule_id, version=args.version, today=context.today(),
                created_by=ctx.user.name if ctx.user else approvals.AGENT_NAME,
            )
        except TableError as e:
            raise ToolError(e.message) from None
    title = row.table_json["title"]
    ctx.emit(AgentEvent("card", {
        "kind": "visual", "visual_id": row.id, "schedule_id": schedule_id, "visual_kind": row.kind, "title": title,
        "version": row.version, "data_date": row.data_date.isoformat() if row.data_date else None,
        "verified": row.verified, "passed": row.passed, "total": row.total, "fallback": row.fallback, "note": row.note,
    }))
    return MakeVisualOut(visual_id=row.id, title=title, version=row.version, verified=row.verified, passed=row.passed,
                         total=row.total, fallback=row.fallback, note=row.note, theme=row.theme)
