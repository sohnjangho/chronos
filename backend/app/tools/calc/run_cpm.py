"""calc.cpm — 대상 일정의 계산 결과(자원 맞춤까지 한, 화면과 같은 값)."""

from datetime import date

from pydantic import BaseModel

from app.store.schedules import load
from app.store.view import run
from app.tools.context import NoArgs, ToolContext, explained_schedule_errors
from app.tools.registry import tool


class CpmRowOut(BaseModel):
    id: str
    es: date
    ef: date
    ls: date
    lf: date
    tf: int
    ff: int
    critical: bool


class CpmOut(BaseModel):
    finish: date
    activities: list[CpmRowOut]


@tool(
    "calc.cpm",
    "지금 일정을 계산한다: 액티비티마다 빠른·늦은 시작과 종료(es·ef·ls·lf), 여유(tf·ff), "
    "주공정 여부, 그리고 준공일.",
    program="schedule",
)
def run_cpm(args: NoArgs, ctx: ToolContext) -> CpmOut:
    with explained_schedule_errors():
        schedule, conditions, _ = load(ctx.session, ctx.require_schedule_id())
        cpm = run(schedule, conditions)  # 화면과 같은 계산(저장된 조건을 넣는다)
    rows = []
    for a in schedule.activities:
        row = cpm.rows[a.id]
        rows.append(
            CpmRowOut(
                id=a.id, es=row.es, ef=row.ef, ls=row.ls, lf=row.lf,
                tf=row.tf, ff=row.ff, critical=row.critical,
            )
        )
    return CpmOut(finish=cpm.finish, activities=rows)
