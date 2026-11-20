"""scenario.submit — 만약에 복사본을 승인함으로 낸다(app.agent.proposals.submit_scenario → propose).

복사본이 open 이고 떠 온 버전이 지금 버전일 때만 낸다. 승인 기준·사건은 out.submit_change 와 같다
(approval {id, title, reasons, summary} / card auto_applied).
"""

from pydantic import Field

from app.agent.ops import Strict
from app.agent.proposals import ProposalError, ScenarioError, submit_scenario
from app.store import approvals, scenarios
from app.tools.context import ToolContext, ToolError
from app.tools.out.submit_change import SubmitOut
from app.tools.registry import tool

NOT_FOUND_MESSAGE = "복사본을 찾을 수 없습니다."


class SubmitScenarioIn(Strict):
    scenario_id: int = Field(description="scenario__create 의 scenario_id")
    title: str | None = Field(default=None, min_length=1, max_length=100, description="승인함 제목(없으면 복사본 이름)")


@tool(
    "scenario.submit",
    "만약에 복사본을 일정에 반영하도록 승인함으로 낸다: {scenario_id, title?}. 사용자가 반영하라고 할 때만 쓴다. "
    "applied=false 면 승인함에서 사람이 결정할 때까지 반영되지 않았으니 반영했다고 말하지 않는다.",
    program="approvals",
    mutates=True,
)
def submit_scenario_tool(args: SubmitScenarioIn, ctx: ToolContext) -> SubmitOut:
    try:
        row = scenarios.get(ctx.session, args.scenario_id)
    except scenarios.NotFound:
        raise ToolError(NOT_FOUND_MESSAGE) from None
    try:
        result = submit_scenario(ctx.session, row, title=args.title, chat_session_id=ctx.chat_session_id,
                                 requested_by=ctx.user.name if ctx.user else approvals.AGENT_NAME, emit=ctx.emit)
    except (ScenarioError, ProposalError) as e:
        raise ToolError(e.message) from None
    a = result.row
    return SubmitOut(applied=result.applied, approval_id=a.id, version=a.version, schedule_id=a.schedule_id,
                     reasons=list(a.reasons_json))
