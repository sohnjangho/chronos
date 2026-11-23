"""schedule.create_project — 새 빈(스타터) 프로젝트 공간을 바로 생성한다."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.store.schedules import create_empty_project
from app.store.tables import ChatSession
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

DataDate = Annotated[date, Field(ge=date(1900, 1, 1), le=date(2199, 12, 31))]


class CreateProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120, description="새 프로젝트 이름")
    domain: str = Field(
        default="general",
        min_length=1,
        max_length=40,
        description="분야 id(general, rnd, permitting, procurement, software, marketing, manufacturing, construction 등)",
    )
    level: Literal["L1", "L2", "L3", "L4", "L5"] = Field(default="L3", description="WBS 정밀도 수준")
    start: DataDate | None = Field(default=None, description="시작일(YYYY-MM-DD). 말하지 않았으면 오늘")
    days_per_week: Literal[5, 6, 7] = Field(default=5, description="주 근무일 수(5·6·7)")


class CreateProjectOut(BaseModel):
    schedule_id: int
    name: str
    domain: str
    level: str
    version: int
    finish: date


@tool(
    "schedule.create_project",
    "새 빈 프로젝트(초기 스타터 일정)를 바로 생성한다. 전체 WBS·일정 초안 생성이 아니라 새 프로젝트 공간 자체를 만들 때 쓴다.",
    program="schedule-table",
    mutates=True,
)
def create_project(args: CreateProjectIn, ctx: ToolContext) -> CreateProjectOut:
    ctx.require_editor()
    name = args.name.strip()
    if not name:
        raise ToolError("프로젝트 이름을 적어 주세요.")
    domain = args.domain.strip() or "general"
    with explained_schedule_errors():
        sid, finish = create_empty_project(
            ctx.session,
            name=name,
            domain=domain,
            level=args.level,
            start=args.start,
            days_per_week=args.days_per_week,
            by_kind="agent",
            by_name=ctx.user.name if ctx.user else "에이전트",
            commit=False,
        )
    if ctx.chat_session_id is not None:
        chat = ctx.session.get(ChatSession, ctx.chat_session_id)
        if chat is not None:
            chat.schedule_id = sid
    ctx.session.flush()
    out = CreateProjectOut(
        schedule_id=sid,
        name=name,
        domain=domain,
        level=args.level,
        version=1,
        finish=finish,
    )
    ctx.emit(
        AgentEvent(
            "card",
            {
                "kind": "project_created",
                "schedule_id": sid,
                "name": name,
                "domain": domain,
                "level": args.level,
                "finish": finish.isoformat(),
            },
        )
    )
    return out
