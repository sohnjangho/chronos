"""schedule.find — 대상 일정에서 액티비티를 id·이름으로 찾는다(실적·지연을 말할 때 먼저 부른다).

차례: id 가 query 와 같은 것(대소문자 무시) 먼저, 그다음 이름(공백을 빼고 소문자)에 query(같게 바꾼 것)가 든 것.
둘 다 일정 차례. 없으면 빈 목록. 날짜·여유·상태는 일정 보기(view_data)의 계산값 그대로다.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.store.view import view_data
from app.tools.context import ToolContext, explained_schedule_errors
from app.tools.registry import tool


class FindIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=50, description="액티비티 id 또는 이름의 일부")
    limit: int = Field(default=5, ge=1, le=10, description="최대 몇 개")


class Match(BaseModel):
    id: str
    name: str
    wbs: str
    kind: str
    es: date
    ef: date
    plan_start: date | None
    plan_finish: date | None
    progress: float
    actual_start: date | None
    actual_finish: date | None
    status: str
    tf: int


class FindOut(BaseModel):
    matches: list[Match]


def _plain(text: str) -> str:
    """공백을 빼고 소문자로."""
    return "".join(text.split()).lower()


@tool(
    "schedule.find",
    "지금 일정에서 액티비티를 id·이름으로 찾는다: {query, limit?}. id 가 같은 것 먼저, 그다음 이름에 든 것. "
    "계산한 날짜(es·ef)·Plan·진도·실적·상태·여유(tf)를 함께 돌려준다.",
    program="schedule-table",
)
def find_activity(args: FindIn, ctx: ToolContext) -> FindOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        view = view_data(ctx.session, schedule_id)
    query = _plain(args.query)
    rows = view["activities"]
    by_id = [a for a in rows if a["id"].lower() == args.query.lower()]
    taken = {a["id"] for a in by_id}
    by_name = [a for a in rows if a["id"] not in taken and query in _plain(a["name"])]
    return FindOut(matches=[Match.model_validate(a) for a in (by_id + by_name)[: args.limit]])
