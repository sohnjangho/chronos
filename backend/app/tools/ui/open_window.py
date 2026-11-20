"""ui.open_window — 화면에 프로그램 창을 열게 한다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

# 화면(frontend/src/programs)에 있는 프로그램. 일정판(schedule)은 스케줄·간트차트·CPM·공정률로 나뉘었다(Task 16b).
# 화면에 프로그램을 더하면 여기와 prompts/system.md 의 프로그램 목록에 같이 더한다.
Program = Literal[
    "chat", "questionnaire", "workflow", "approvals", "explorer", "settings", "devconsole",
    "schedule-table", "gantt", "cpm", "progress", "compare", "conditions", "delays",
]

# 관리자만 여는 프로그램(화면 매니페스트의 adminOnly 와 같게 — 맞춤 시험이 있다).
ADMIN_ONLY = {"devconsole": "개발 콘솔"}

DESCRIPTION = (
    "사용자 화면에 프로그램 창을 연다. program: chat(에이전트 대화) · questionnaire(질문지) · workflow(워크플로우) · "
    "approvals(승인함) · explorer(탐색기) · settings(설정) · devconsole(개발 콘솔, 관리자용) · schedule-table(스케줄: 일정 표) · gantt(간트차트) · "
    "cpm(CPM 네트워크) · progress(공정률: 계획·실적 공정률과 S-커브) · compare(비교판) · conditions(조건·규칙) · "
    "delays(지연 기록). "
    "일정 창의 params: id(일정 id, 없으면 사용자가 고른 지금 일정) · activity(고르고 보일 액티비티 id)."
)


class OpenWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: Program = Field(description="열 프로그램 id (예: gantt)")
    params: dict[str, str] = Field(default_factory=dict, description="창에 넘길 값 (예: {\"id\": \"3\", \"activity\": \"A2020\"})")


class OpenWindowOut(BaseModel):
    opened: bool


@tool("ui.open_window", DESCRIPTION)
def open_window(args: OpenWindowIn, ctx: ToolContext) -> OpenWindowOut:
    if args.program in ADMIN_ONLY and (ctx.user is None or ctx.user.role != "admin"):
        raise ToolError(f"관리자만 열 수 있는 프로그램입니다: {ADMIN_ONLY[args.program]}")
    ctx.emit(AgentEvent("open_window", {"program": args.program, "params": dict(args.params)}))
    return OpenWindowOut(opened=True)
