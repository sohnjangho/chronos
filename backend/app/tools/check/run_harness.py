"""harness.check — 대상 일정(지금 버전)을 저장된 조건과 기본 규칙으로 점검한다."""

from pydantic import BaseModel

from app.harness.assemble import assemble_all
from app.harness.checks import Violation, check
from app.harness.conditions import read_conditions
from app.store.schedules import load
from app.tools.context import NoArgs, ToolContext, explained_schedule_errors
from app.tools.registry import tool


class ViolationOut(BaseModel):
    condition_id: str
    message: str
    activity_ids: list[str]
    amount: int | None


class InvalidOut(BaseModel):
    condition_id: str  # 저장된 조건에 id 가 없으면 "?"
    message: str


class HarnessOut(BaseModel):
    passed: list[str]
    violations: list[ViolationOut]
    notices: list[ViolationOut]
    uncheckable: list[str]
    skipped: list[str]
    invalid: list[InvalidOut]


def _out(v: Violation) -> ViolationOut:
    return ViolationOut(
        condition_id=v.condition_id, message=v.message, activity_ids=list(v.activity_ids), amount=v.amount
    )


@tool(
    "harness.check",
    "지금 일정을 조건으로 점검한다: 통과한 조건, 위반(조건 id·설명·관련 액티비티·어긴 양), "
    "알림(자원 맞춤이 풀어 준 겹침), 자동 점검이 안 되는 조건, 일정이 계산되지 않아 점검하지 못한 조건, "
    "형식이 틀려 읽지 못한 조건.",
    program="conditions",
)
def run_harness(args: NoArgs, ctx: ToolContext) -> HarnessOut:
    with explained_schedule_errors():
        schedule, stored, _ = load(ctx.session, ctx.require_schedule_id())
    # 하나씩 읽어 못 읽은 것은 invalid 로. 저장된 기본 규칙은 버리고 BASE_RULES 를 새로 넣는다.
    # 분야·내 규칙은 저장된 목록 그대로 쓴다.
    conditions, unreadable = read_conditions(stored)
    report = check(schedule, assemble_all(conditions))
    return HarnessOut(
        passed=report.passed,
        violations=[_out(v) for v in report.violations],
        notices=[_out(v) for v in report.notices],
        uncheckable=report.uncheckable,
        skipped=report.skipped,
        invalid=[InvalidOut(**i) for i in unreadable + report.invalid],
    )
