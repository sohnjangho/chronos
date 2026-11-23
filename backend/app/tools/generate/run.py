"""generate.run — 생성 루프(app.agent.generation.generate)를 돌려 일정 초안을 만든다.

초안은 schedule_drafts 에만 넣는다(그래서 mutates). 일정 저장(첫 버전)은 승인 뒤에 한다.
끝나면 결과 카드 `AgentEvent("card", {"kind": "generation_result", …})` 를 한 번 낸다.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import app.tools.generate as package
from app.agent.events import AgentEvent
from app.agent.generation import GenResult, generate
from app.core.cpm import ScheduleError
from app.domains.loader import UnknownDomain
from app.harness.conditions import Condition, ConditionFormatError
from app.store import settings as settings_store
from app.store.drafts import violation_json
from app.store.schedules import run as run_schedule
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool


class FactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    source: str
    evidence_ids: list[int] = Field(default_factory=list, description="받친 근거(evidence__search 의 evidence_id)")


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(
        description="분야 id (예: construction, manufacturing, rnd, permitting, procurement, software, general 등)"
    )
    level: Literal["L1", "L2", "L3", "L4", "L5"] = Field(description="정밀도")
    request: str = Field(min_length=1, description="사용자의 요청(프롬프트)")
    facts: list[FactIn] = Field(default_factory=list, description="generate.extract_conditions 의 facts")
    conditions: list[dict] = Field(default_factory=list, description="generate.extract_conditions 의 conditions")
    assumptions: list[FactIn] = Field(default_factory=list, description="가정한 것 {label, value, source}")


class RoundOut(BaseModel):
    n: int
    activity_count: int
    violations: int  # -1 = 깨진 초안


class ViolationOut(BaseModel):
    condition_id: str
    message: str
    activity_ids: list[str]
    amount: int | None


class UncheckedOut(BaseModel):
    id: str
    name: str  # 조건 글


class InvalidOut(BaseModel):
    id: str
    reason: str


class RunOut(BaseModel):
    ok: bool
    draft_id: int | None
    finish: date | None  # 화면과 같은 계산(조건·자원 맞춤 포함)의 준공일
    activity_count: int
    critical_count: int
    rounds: list[RoundOut]
    violations: list[ViolationOut]
    notices: list[ViolationOut]
    assumptions: list[FactIn]
    warnings: list[str]  # 정밀도 맞춤·뺀 조건 알림(위반 아님)
    conflict: list[str]
    reason: str | None
    uncheckable: list[UncheckedOut]  # 자동 점검하지 않은 조건 — 통과가 아니다
    invalid: list[InvalidOut]  # 형식이 틀려 읽지 않은 조건


def _inputs(stored: list[dict]) -> list[Condition]:
    try:
        return [Condition.from_dict(d) for d in stored]
    except ConditionFormatError as e:
        raise ToolError(f"조건을 읽을 수 없습니다: {e.condition_id}: {e.message}") from None


def _out(r: GenResult) -> RunOut:
    finish, critical = None, 0
    if r.schedule is not None:
        try:
            cpm = run_schedule(r.schedule, [c.to_dict() for c in r.conditions])
            finish, critical = cpm.finish, len(cpm.critical_path)
        except ScheduleError:  # 달력 조건이 일할 날을 없앤 경우(보고서의 base.calendar 위반)
            pass
    report = r.report
    return RunOut(
        ok=r.ok,
        draft_id=r.draft_id,
        finish=finish,
        activity_count=len(r.schedule.activities) if r.schedule else 0,
        critical_count=critical,
        rounds=[RoundOut(n=x.n, activity_count=x.activity_count, violations=x.violations) for x in r.rounds],
        violations=[ViolationOut(**violation_json(v)) for v in report.violations] if report else [],
        notices=[ViolationOut(**violation_json(v)) for v in report.notices] if report else [],
        assumptions=[FactIn(**a) for a in r.assumptions],
        warnings=r.warnings,
        conflict=r.conflict,
        reason=r.reason,
        uncheckable=[UncheckedOut(**u) for u in r.uncheckable],
        invalid=[InvalidOut(**i) for i in r.invalid],
    )


def result_card(out: RunOut) -> AgentEvent:
    """대화에 보일 결과 카드: 준공·액티비티 수·크리티컬 수·가정·위반과 점검하지 않은 조건 수."""
    data = out.model_dump(mode="json")
    keys = ("ok", "draft_id", "finish", "activity_count", "critical_count", "assumptions", "violations")
    card = {"kind": "generation_result", **{k: data[k] for k in keys}}
    card |= {"uncheckable_count": len(out.uncheckable), "invalid_count": len(out.invalid)}
    return AgentEvent("card", card | {"conflict": data["conflict"], "reason": data["reason"]})


@tool(
    "generate.run",
    "일정 초안을 만든다: WBS → 액티비티(기간·선후 관계) → 코드가 날짜·크리티컬 패스 계산 → 조건 점검 → "
    "위반이면 고쳐 다시(최대 5회, 같은 위반이 두 회차 이어지면 멈춘다). 입력은 generate.extract_conditions 의 결과(facts·conditions·assumptions). "
    "단계마다 생성 카드가 대화에 보인다. 초안은 저장 전 상태(draft_id)이고, 일정 저장은 승인 뒤에 한다. "
    "한도까지 못 맞추거나 LLM 호출이 중간에 실패하면 ok=false 와 그때까지 가장 나은 안, 부딪히는 조건(conflict)을 준다. "
    "ok 는 자동 점검한 조건만의 결과입니다. uncheckable 의 조건은 점검하지 않았으니 통과로 말하지 마세요.",
    mutates=True,
)
async def run(args: RunIn, ctx: ToolContext) -> RunOut:
    inputs = _inputs(args.conditions)
    max_rounds = int(settings_store.get_agent_config(ctx.session)["max_check_retries"]) if ctx.session is not None else 5
    try:
        result = await generate(
            ctx,
            package.client_for(ctx),
            domain=args.domain,
            level=args.level,
            request=args.request,
            facts=[f.model_dump() for f in args.facts],
            inputs=inputs,
            assumptions=[a.model_dump() for a in args.assumptions],
            max_rounds=max_rounds,
        )
    except UnknownDomain:
        raise ToolError(f"올바르지 않은 분야입니다: {args.domain}") from None
    out = _out(result)
    ctx.emit(result_card(out))
    return out
