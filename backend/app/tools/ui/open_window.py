"""ui.open_window — 화면에 프로그램 창을 열게 한다."""

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.tools.context import ToolContext
from app.tools.registry import tool


class OpenWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str = Field(description="열 프로그램 id (예: schedule)")
    params: dict[str, str] = Field(default_factory=dict, description="창에 넘길 값")


class OpenWindowOut(BaseModel):
    opened: bool


@tool("ui.open_window", "사용자 화면에 프로그램 창을 연다.")
def open_window(args: OpenWindowIn, ctx: ToolContext) -> OpenWindowOut:
    ctx.emit(AgentEvent("open_window", {"program": args.program, "params": dict(args.params)}))
    return OpenWindowOut(opened=True)
