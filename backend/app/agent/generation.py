"""일정 생성 루프: WBS → 스케줄 초안 → 코드 계산 → 크리티컬 패스 → 조건 점검 → (위반이면) 고침.

LLM 은 구조와 기간·선후 관계만 낸다. 날짜·여유·조건 통과는 app/core·app/harness 가 계산한다.

회차(round): 스케줄 초안 한 번(처음 초안 또는 고친 초안)이 한 회차다. WBS 답이 깨져 다시 받는 것도
한 회차로 센다(violations=-1). WBS 는 처음 한 번만 받고, 고침 답이 새 WBS 를 낼 때만 바꾼다.
멈춤: 위반 0 인 초안(ok) · 회차가 max_rounds 에 닿음(가장 나은 안) · LLM 실패(그때까지 가장 나은 안, 없으면 초안 없음).
쓰기: 초안은 맨 끝에 한 번만 넣고 commit 한다. LLM 을 부르는 동안 쓰지 않는다.
개략 일정(L1·L2)은 자원을 다루지 않는다: resource_cap 입력 조건은 빼고 warnings 에 알린다.
파일에서 가져온 행(fixed, Task 53)이 있으면 WBS 를 청하지 않고 그 행이 전부다: 파일 값이 LLM 답보다 앞서고, LLM 은
빈 칸만 정한다(가정 출처 「추정」). 빈 칸이 없으면 LLM 을 부르지 않는다. 파일 날짜 제약은 fixed 가 넣는다.
가져오기는 정밀도와 상관없이 주요 자원을 붙이지 않는다(파일에 없는 자원 맞춤이 파일 날짜를 옮기지 않게).
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from typing import Literal

from app.agent.events import AgentEvent
from app.agent.generation_build import (
    ROUGH_RESOURCE_MESSAGE,
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
    uses_resources,
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
from app.agent.domain_synth import synthesize_pack
from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.domains.loader import DomainPack, is_specialty_domain, resolve_pack
from app.files.schedule_import import REPAIR_NOTE, ImportedRows
from app.harness.assemble import assemble
from app.harness.checks import CheckReport, Violation
from app.harness.checks import check as check_schedule
from app.harness.conditions import Condition
from app.llm.client import LlmClient, LlmFailed, LlmNotReady, LlmReply
from app.store import my_rules
from app.store.drafts import create_draft
from app.store.schedules import run
from app.tools.context import ToolContext

GenStage = Literal["wbs", "schedule", "compute", "critical", "check"]
# 이 기본 규칙을 어기면 초안이 깨진 것이다(LLM 이 고쳐야 한다). base.calendar 는 조건 탓이라 위반으로 센다.
BROKEN_RULES = frozenset({"base.no_cycle", "base.no_dangling", "base.valid"})
LIMIT_REASON = "조건을 모두 맞추지 못했습니다."
NO_DRAFT_REASON = "일정 초안을 만들지 못했습니다. 다시 시도해 주세요."
OUT_OF_RANGE = "날짜 계산이 범위를 넘었습니다(기간·lag 가 너무 큽니다)."
STOPPED_REASON = "중단했습니다."


class _Stopped(Exception):
    """사용자가 멈춤을 눌렀다(LLM 을 부르기 전에 ctx.stop_requested 로 안다)."""


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
    conditions: list[Condition]  # 조립된 목록(기본 규칙 + 분야 규칙 + 내 규칙 + 입력 조건)
    report: CheckReport | None
    rounds: list[GenRound]
    assumptions: list[dict]  # [{label, value, source}]
    warnings: list[str] = field(default_factory=list)  # 정밀도 맞춤·뺀 조건 알림(위반 아님)
    conflict: list[str] = field(default_factory=list)  # 끝에 아직 어긴 조건 id(돌려준 초안 기준)
    reason: str | None = None
    # 자동 점검하지 않은 조건(통과가 아니다) [{id, name}]·형식이 틀려 읽지 않은 조건 [{id, reason}]
    uncheckable: list[dict] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _Scored:
    """점검까지 마친 초안."""

    round: int
    schedule: Schedule
    report: CheckReport
    warnings: list[str]


class _Loop:
    def __init__(self, ctx: ToolContext, llm: LlmClient, pack: DomainPack, brief: Brief, s: Setting,
                 conditions: list[Condition], notes: list[str], fixed: ImportedRows | None = None) -> None:
        self.ctx, self.llm, self.pack, self.brief, self.setting = ctx, llm, pack, brief, s
        self.conditions = conditions
        self.notes = notes  # 생성 전에 정한 알림(뺀 조건 등)
        self.stored = [c.to_dict() for c in conditions]
        self.chat_session_id: int | None = getattr(ctx, "chat_session_id", None)  # 문맥이 대화 id 를 가질 때만
        self.rounds: list[GenRound] = []
        self.fixed = fixed  # 파일에서 가져온 행(있으면 그 WBS 를 쓰고, 파일 값이 LLM 답보다 앞선다)
        self.wbs: list[WbsIn] | None = [WbsIn(**n) for n in fixed.wbs] if fixed else None
        self.draft: DraftReply | None = None  # 마지막으로 읽은 초안(고칠 바탕)
        self.drafted = False  # 스케줄 초안을 한 번이라도 청했나(다음부터는 고침)
        self.feedback = ""  # 다음 부름에 줄 문제
        self.violation_note = ""  # 마지막으로 점검한 초안의 위반·계산 결과(깨진 회차에도 함께 보낸다)
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
        if self.violation_note:
            self.feedback += f"\n그 앞 초안(점검한 것)에서 아직 남은 문제:\n{self.violation_note}"

    async def run(self, max_rounds: int) -> None:
        while len(self.rounds) < max_rounds:
            if self.wbs is None and not await self.make_wbs():
                continue
            self.stop_check()
            self.card("schedule")
            scored = self.score(await self.ask_draft())
            if scored is not None and not scored.report.violations:
                return
            if self.fixed is not None and not self.fixed.blanks:  # 파일 값뿐 — LLM 이 고칠 칸이 없다
                return

    def stop_check(self) -> None:
        if self.ctx.stop_requested():
            raise _Stopped

    async def make_wbs(self) -> bool:
        self.stop_check()
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
        if self.fixed is not None and not self.fixed.blanks:  # 빈 칸이 없으면 LLM 을 부르지 않는다
            return self.fixed.merge(None)
        wbs = [n.model_dump() for n in self.wbs or ()]
        if not self.drafted:
            self.drafted = True
            messages = schedule_messages(self.pack, self.brief, wbs)
            return await ask(self.llm, messages, SCHEDULE_SCHEMA, self.chat_session_id)
        draft = [a.model_dump() for a in self.draft.activities] if self.draft else None
        messages = repair_messages(self.pack, self.brief, wbs, draft, self.feedback)
        if self.fixed is not None:  # repair.md 의 「activities 전부」 를 덮는다: '?' 칸 행만
            messages[-1]["content"] += f"\n{REPAIR_NOTE}"
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
            if self.fixed is not None:
                reply = self.fixed.merge(reply)  # 파일 값으로 덮는다(빈 칸 행이 빠졌으면 DraftProblem)
            self.draft, self.wbs = read_draft(reply, self.wbs or [])
        except DraftProblem as problem:
            self.broken(problem)
            return None
        schedule = build(self.draft, self.wbs, self.setting)
        if self.fixed is not None:
            schedule = self.fixed.constrain(schedule)
        count = len(schedule.activities)
        try:
            cpm, report = self.measure(schedule, count)
        except DraftProblem as problem:
            self.broken(problem)
            self.card("check")
            return None
        self.record(count, len(report.violations))
        self.card("check")  # 점검을 마친 뒤: 이 회차의 결과가 rounds 에 들어 있다
        scored = _Scored(len(self.rounds), schedule, report, fit_warnings(self.brief.level, self.wbs, count))
        if self.best is None or len(report.violations) <= len(self.best.report.violations):
            self.best = scored  # 위반 수가 같으면 나중 안
        self.feedback = self.repair_note(scored, cpm)
        return scored

    def measure(self, schedule: Schedule, count: int) -> tuple[CpmResult | None, CheckReport]:
        """계산과 점검. 날짜 셈이 넘치거나(OverflowError·ValueError) 구조 규칙을 어기면 DraftProblem."""
        try:
            cpm = self.compute(schedule)
            report = check_schedule(schedule, self.conditions)
        except (OverflowError, ValueError):
            raise DraftProblem(OUT_OF_RANGE, count) from None
        base = [v for v in report.violations if v.condition_id in BROKEN_RULES]
        if base:
            raise DraftProblem(" / ".join(_described(v) for v in base), count)
        return cpm, report

    def repair_note(self, scored: _Scored, cpm: CpmResult | None) -> str:
        lines = ["지킬 조건을 어긴 곳:", *(f"- [{v.condition_id}] {_described(v)}" for v in scored.report.violations)]
        if cpm is not None:
            path = " → ".join(cpm.critical_path)
            deadline_label = self.pack.terms.get("deadline", "완료")
            lines.append(f"코드가 계산한 결과: {deadline_label} {cpm.finish.isoformat()}, 크리티컬 패스 {path}")
        self.violation_note = "\n".join(lines)
        fresh = [w for w in scored.warnings if w not in self.sent]
        if not fresh:
            return self.violation_note
        self.sent.update(fresh)
        fit = ["정밀도 맞춤(위반은 아니지만 고칠 때 맞춘다):", *(f"- {w}" for w in fresh)]
        return "\n".join([self.violation_note, *fit])

    def result(self, assumptions: list[dict], failure: str | None = None, stopped: bool = False) -> GenResult:
        """끝 결과. failure 는 LLM 실패 안내 글, stopped 는 멈춤(둘 다 그때까지 가장 나은 초안이 있으면 저장한다)."""
        best = self.best
        if best is not None and self.fixed is not None:  # 추정한 칸(출처 「추정」)
            assumptions = [*assumptions, *self.fixed.estimates(best.schedule)]
        base = {"conditions": self.conditions, "rounds": self.rounds, "assumptions": assumptions}
        if best is None:
            reason = STOPPED_REASON if stopped else f"일정을 만들지 못했습니다. {failure}" if failure else NO_DRAFT_REASON
            return GenResult(ok=False, draft_id=None, schedule=None, report=None, warnings=list(self.notes),
                             reason=reason, **base)
        ok = not best.report.violations
        draft_id = create_draft(
            self.ctx.session, chat_session_id=self.chat_session_id, domain=self.pack.id, level=self.brief.level,
            schedule=best.schedule, conditions=self.conditions, report=best.report, assumptions=assumptions,
        )
        uncheckable, invalid = _unchecked(best.report, self.conditions)
        return GenResult(
            ok=ok, draft_id=draft_id, schedule=best.schedule, report=best.report,
            warnings=[*self.notes, *best.warnings], conflict=[] if ok else [v.condition_id for v in best.report.violations],
            reason=None if ok else _end_reason(best, failure, stopped), uncheckable=uncheckable, invalid=invalid,
            **base,
        )


def _described(v: Violation) -> str:
    return f"{v.message} ({', '.join(v.activity_ids)})" if v.activity_ids else v.message


def _end_reason(best: _Scored, failure: str | None, stopped: bool = False) -> str:
    count = len(best.report.violations)
    if stopped:
        return f"중단해서 지금까지 가장 나은 초안({best.round}회차, 위반 {count})을 저장했습니다."
    if failure is None:
        return LIMIT_REASON
    return f"LLM 호출이 실패해 지금까지 가장 나은 초안({best.round}회차, 위반 {count})을 저장했습니다. {failure}"


def _unchecked(report: CheckReport, conditions: list[Condition]) -> tuple[list[dict], list[dict]]:
    """([{id, name}] 자동 점검하지 않은 조건, [{id, reason}] 형식이 틀린 조건). name 은 조건 글(같은 id 는 마지막 것)."""
    names = {c.id: c.text for c in conditions}
    uncheckable = [{"id": i, "name": names.get(i, i)} for i in report.uncheckable]
    invalid = [{"id": i["condition_id"], "reason": i["message"]} for i in report.invalid]
    return uncheckable, invalid


def _llm_message(error: LlmNotReady | LlmFailed) -> str:
    return error.message if isinstance(error, LlmNotReady) else error.error.message


def _for_level(level: str, inputs: Sequence[Condition]) -> tuple[list[Condition], list[str]]:
    """(쓸 입력 조건, 알림). 개략 일정(L1·L2)이면 resource_cap 을 뺀다."""
    if uses_resources(level):
        return list(inputs), []
    kept = [c for c in inputs if c.kind != "resource_cap"]
    return kept, [ROUGH_RESOURCE_MESSAGE] if len(kept) < len(inputs) else []


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
    fixed: ImportedRows | None = None,
) -> GenResult:
    """요청·알고 있는 것·입력 조건·가정으로 일정 초안을 만든다(모듈 설명글 참고).

    없는 분야면 UnknownDomain, 없는 정밀도면 KeyError. LLM 실패는 ok=False·reason 으로 바뀌고, 그때까지
    점검한 초안이 있으면 가장 나은 것을 저장한다(없으면 schedule=None). 결과 초안은 schedule_drafts 에만
    넣는다(일정 저장은 승인 뒤). ctx.stop_requested() 가 참이면 다음 LLM 호출 전에 멈추고 같은 식으로
    끝낸다(가장 나은 초안이 있으면 저장, 없으면 reason "중단했습니다.").
    fixed(파일에서 가져온 행)를 주면 그 행으로 초안을 만든다(모듈 설명글 참고).
    """
    pack = resolve_pack(domain)
    inputs, notes = _for_level(level, inputs)
    if fixed is None and not is_specialty_domain(domain):
        pack = await synthesize_pack(
            llm,
            domain,
            request,
            facts=facts,
            assumptions=assumptions,
            conditions=inputs,
            chat_session_id=getattr(ctx, "chat_session_id", None),
        )
    domain_rules = [Condition.from_dict(r) for r in pack.rules_raw]
    conditions = assemble(domain_rules, my_rules.for_generation(ctx.session, domain), inputs)  # 켜진 분야 범위 내 규칙
    start, start_note = start_date(conditions, facts, date.today(), start_term=pack.terms.get("start", "시작"))
    noted = [*(dict(a) for a in assumptions), *start_note]
    s = setting(
        pack,
        level,
        start,
        condition_tags(conditions),
        conditions=conditions,
        strict_tags=is_specialty_domain(pack.id),
    )
    if fixed is not None:
        s = replace(s, resources=(), allow_resources=False)  # 가져오기: 자원 자동 붙이기 끄기(모든 정밀도)
    effective = [c for c in conditions if c.layer not in ("base", "domain") and c.enabled]
    brief = Brief(level, request, [dict(f) for f in facts], noted, effective, list(s.known_tags))
    loop = _Loop(ctx, llm, pack, brief, s, conditions, notes, fixed)
    try:
        await loop.run(max_rounds)
    except (LlmNotReady, LlmFailed) as error:
        return loop.result(noted, failure=_llm_message(error))
    except _Stopped:
        return loop.result(noted, stopped=True)
    return loop.result(noted)
