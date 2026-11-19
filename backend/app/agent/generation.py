"""일정 생성 루프: WBS → 스케줄 초안 → 코드 계산 → 크리티컬 패스 → 조건 점검 → (위반이면) 고침.

LLM 은 구조와 기간·선후 관계만 낸다. 날짜·여유·조건 통과는 app/core·app/harness 가 계산한다.

회차(round): 스케줄 초안 한 번(처음 초안 또는 고친 초안)이 한 회차다. WBS 답이 깨져 다시 받는 것도
한 회차로 센다(violations=-1). WBS 는 처음 한 번만 받고, 고침 답이 새 WBS 를 낼 때만 바꾼다.
멈춤: 위반 0 인 초안(ok) · 회차가 max_rounds 에 닿음(가장 나은 안) · LLM 실패(초안 없음).
쓰기: 초안은 맨 끝에 한 번만 넣고 commit 한다. LLM 을 부르는 동안 쓰지 않는다.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from app.agent.events import AgentEvent
from app.agent.generation_build import (
    DraftProblem,
    DraftReply,
    Setting,
    WbsIn,
    build,
    condition_tags,
    fit_warnings,
    read_draft,
    read_wbs,
    setting,
    start_date,
)
from app.agent.generation_steps import (
    REPAIR_SCHEMA,
    SCHEDULE_SCHEMA,
    WBS_SCHEMA,
    Brief,
    ask,
    repair_messages,
    schedule_messages,
    wbs_messages,
)
from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.domains.loader import DomainPack, load
from app.harness.assemble import assemble
from app.harness.checks import CheckReport, Violation
from app.harness.checks import check as check_schedule
from app.harness.conditions import Condition
from app.llm.client import LlmClient, LlmFailed, LlmNotReady, LlmReply
from app.store.drafts import create_draft
from app.store.schedules import run
from app.tools.context import ToolContext

GenStage = Literal["wbs", "schedule", "compute", "critical", "check"]
# 이 기본 규칙을 어기면 초안이 깨진 것이다(LLM 이 고쳐야 한다). base.calendar 는 조건 탓이라 위반으로 센다.
BROKEN_RULES = frozenset({"base.no_cycle", "base.no_dangling", "base.valid"})
LIMIT_REASON = "조건을 모두 맞추지 못했습니다."
NO_DRAFT_REASON = "일정 초안을 만들지 못했습니다. 다시 시도해 주세요."


@dataclass(frozen=True)
class GenRound:
    n: int
    activity_count: int
    violations: int  # -1 = 깨진 초안


@dataclass(frozen=True)
class GenResult:
    ok: bool
    draft_id: int | None
    schedule: Schedule | None  # 맞춤 전 일정(조건도 넣지 않은 것). 화면 날짜는 run(schedule, conditions)
    conditions: list[Condition]  # 조립된 목록(기본 규칙 + 분야 규칙 + 입력 조건)
    report: CheckReport | None
    rounds: list[GenRound]
    assumptions: list[dict]  # [{label, value, source}]
    warnings: list[str] = field(default_factory=list)  # 정밀도 맞춤 알림(위반 아님)
    conflict: list[str] = field(default_factory=list)  # 한도에서 아직 어긴 조건 id
    reason: str | None = None


@dataclass(frozen=True)
class _Scored:
    """점검까지 마친 초안."""

    schedule: Schedule
    report: CheckReport
    warnings: list[str]


class _Loop:
    def __init__(self, ctx: ToolContext, llm: LlmClient, pack: DomainPack, brief: Brief, s: Setting,
                 conditions: list[Condition]) -> None:
        self.ctx, self.llm, self.pack, self.brief, self.setting = ctx, llm, pack, brief, s
        self.conditions = conditions
        self.stored = [c.to_dict() for c in conditions]
        self.chat_session_id: int | None = getattr(ctx, "chat_session_id", None)  # 문맥이 대화 id 를 가질 때만
        self.rounds: list[GenRound] = []
        self.wbs: list[WbsIn] | None = None
        self.draft: DraftReply | None = None  # 마지막으로 읽은 초안(고칠 바탕)
        self.drafted = False  # 스케줄 초안을 한 번이라도 청했나(다음부터는 고침)
        self.feedback = ""  # 다음 부름에 줄 문제
        self.sent: set[str] = set()  # 이미 보낸 정밀도 맞춤 알림
        self.best: _Scored | None = None

    def card(self, stage: GenStage) -> None:
        rounds = [asdict(r) for r in self.rounds]
        self.ctx.emit(AgentEvent("card", {"kind": "generation", "stage": stage, "rounds": rounds}))

    def record(self, activity_count: int, violations: int) -> None:
        self.rounds.append(GenRound(len(self.rounds) + 1, activity_count, violations))

    def broken(self, problem: DraftProblem) -> None:
        self.record(problem.activity_count, -1)
        self.feedback = f"앞 답이 깨졌습니다: {problem.message}"

    async def run(self, max_rounds: int) -> None:
        while len(self.rounds) < max_rounds:
            if self.wbs is None and not await self.make_wbs():
                continue
            self.card("schedule")
            scored = self.score(await self.ask_draft())
            if scored is not None and not scored.report.violations:
                return

    async def make_wbs(self) -> bool:
        self.card("wbs")
        messages = wbs_messages(self.pack, self.brief, self.feedback)
        reply = await ask(self.llm, messages, WBS_SCHEMA, self.chat_session_id)
        try:
            self.wbs = read_wbs(reply)
        except DraftProblem as problem:
            self.broken(problem)
            return False
        self.feedback = ""
        return True

    async def ask_draft(self) -> LlmReply:
        wbs = [n.model_dump() for n in self.wbs or ()]
        if not self.drafted:
            self.drafted = True
            messages = schedule_messages(self.pack, self.brief, wbs)
            return await ask(self.llm, messages, SCHEDULE_SCHEMA, self.chat_session_id)
        draft = [a.model_dump() for a in self.draft.activities] if self.draft else None
        messages = repair_messages(self.pack, self.brief, wbs, draft, self.feedback)
        return await ask(self.llm, messages, REPAIR_SCHEMA, self.chat_session_id)

    def compute(self, schedule: Schedule) -> CpmResult | None:
        """화면과 같은 계산(조건을 넣고 자원 맞춤까지). 깨졌으면 None(점검이 까닭을 알린다)."""
        self.card("compute")
        try:
            cpm = run(schedule, self.stored)
        except ScheduleError:
            return None
        self.card("critical")
        return cpm

    def score(self, reply: LlmReply) -> _Scored | None:
        """초안을 읽고 계산·점검한다. 깨졌으면 None 이고 그 까닭이 다음 고침으로 간다."""
        try:
            self.draft, self.wbs = read_draft(reply, self.wbs or [])
        except DraftProblem as problem:
            self.broken(problem)
            return None
        schedule = build(self.draft, self.wbs, self.setting)
        count = len(schedule.activities)
        cpm = self.compute(schedule)
        report = check_schedule(schedule, self.conditions)
        base = [v for v in report.violations if v.condition_id in BROKEN_RULES]
        if base:
            self.broken(DraftProblem(" / ".join(_described(v) for v in base), count))
        else:
            self.record(count, len(report.violations))
        self.card("check")  # 점검을 마친 뒤: 이 회차의 결과가 rounds 에 들어 있다
        if base:
            return None
        scored = _Scored(schedule, report, fit_warnings(self.brief.level, self.wbs, count))
        if self.best is None or len(report.violations) <= len(self.best.report.violations):
            self.best = scored  # 위반 수가 같으면 나중 안
        self.feedback = self.repair_note(scored, cpm)
        return scored

    def repair_note(self, scored: _Scored, cpm: CpmResult | None) -> str:
        lines = ["지킬 조건을 어긴 곳:"]
        for v in scored.report.violations:
            lines.append(f"- [{v.condition_id}] {_described(v)}")
        if cpm is not None:
            path = " → ".join(cpm.critical_path)
            lines.append(f"코드가 계산한 결과: 준공 {cpm.finish.isoformat()}, 크리티컬 패스 {path}")
        fresh = [w for w in scored.warnings if w not in self.sent]
        if fresh:
            self.sent.update(fresh)
            lines += ["정밀도 맞춤(위반은 아니지만 고칠 때 맞춘다):", *(f"- {w}" for w in fresh)]
        return "\n".join(lines)

    def result(self, assumptions: list[dict]) -> GenResult:
        best = self.best
        base = {"conditions": self.conditions, "rounds": self.rounds, "assumptions": assumptions}
        if best is None:
            return GenResult(ok=False, draft_id=None, schedule=None, report=None, reason=NO_DRAFT_REASON, **base)
        ok = not best.report.violations
        draft_id = create_draft(
            self.ctx.session, chat_session_id=self.chat_session_id, domain=self.pack.id, level=self.brief.level,
            schedule=best.schedule, conditions=self.conditions, report=best.report, assumptions=assumptions,
        )
        return GenResult(
            ok=ok, draft_id=draft_id, schedule=best.schedule, report=best.report, warnings=best.warnings,
            conflict=[] if ok else [v.condition_id for v in best.report.violations],
            reason=None if ok else LIMIT_REASON, **base,
        )


def _described(v: Violation) -> str:
    return f"{v.message} ({', '.join(v.activity_ids)})" if v.activity_ids else v.message


def _llm_reason(error: LlmNotReady | LlmFailed) -> str:
    message = error.message if isinstance(error, LlmNotReady) else error.error.message
    return f"일정을 만들지 못했습니다. {message}"


async def generate(
    ctx: ToolContext,
    llm: LlmClient,
    *,
    domain: str,
    level: str,
    request: str,
    facts: Sequence[dict] = (),
    inputs: Sequence[Condition] = (),
    assumptions: Sequence[dict] = (),
    max_rounds: int = 5,
) -> GenResult:
    """요청·알고 있는 것·입력 조건·가정으로 일정 초안을 만든다(모듈 설명글 참고).

    없는 분야면 UnknownDomain, 없는 정밀도면 KeyError. LLM 실패는 ok=False·schedule=None·reason 으로 바뀐다.
    결과 초안은 schedule_drafts 에만 넣는다(일정 저장은 승인 뒤).
    """
    pack = load(domain)
    domain_rules = [Condition.from_dict(r) for r in pack.rules_raw]
    conditions = assemble(domain_rules, [], inputs)
    start, start_note = start_date(conditions, facts, date.today())
    noted = [*(dict(a) for a in assumptions), *start_note]
    s = setting(pack, level, start, condition_tags(conditions))
    effective = [c for c in conditions if c.layer not in ("base", "domain") and c.enabled]
    brief = Brief(level, request, [dict(f) for f in facts], noted, effective, list(s.known_tags))
    loop = _Loop(ctx, llm, pack, brief, s, conditions)
    try:
        await loop.run(max_rounds)
    except (LlmNotReady, LlmFailed) as error:
        return GenResult(ok=False, draft_id=None, schedule=None, conditions=conditions, report=None,
                         rounds=loop.rounds, assumptions=noted, reason=_llm_reason(error))
    return loop.result(noted)
