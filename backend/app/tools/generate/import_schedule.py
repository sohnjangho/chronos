"""schedule.import — 공정표 파일(csv·tsv·xlsx)을 확인하고, 사용자가 원하면 일정 초안으로 가져와 승인함에 낸다(설계 5-4).

먼저 묻고 가져온다:
- confirmed=false(확인): 표를 끝까지 읽고(코드) 공정표인지 에이전트가 판단한다. 공정표면 열 대응을 받아 요약 카드
  card{kind: schedule_file, file_id, sheet, rows, columns_found, missing} 를 낸다(숫자는 코드가 센다). 아니면 카드 없음.
- confirmed=true(가져오기): 열 대응·빈 칸(ask|estimate)·파일 날짜 제약을 에이전트가 정하고, 코드가 행을 액티비티로
  바꾼다(파일 값 그대로). 물을 것이 있으면 기존 질문지 도구(ask.questionnaire)로 묻고 멈춘다. 아니면(또는 답을 받았으면)
  생성 루프가 빈 칸만 추정해(같은 점검·고침, 가정 출처 「추정」) 초안을 만들고, 기존 첫 저장 길(out.submit_change →
  승인함)로 낸다. 날짜는 코드가 계산한다. 초안·승인 건을 저장하므로 mutates.
"""

import asyncio
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import app.tools.generate as package
from app.agent.events import AgentEvent
from app.agent.generation import generate
from app.agent.generation_steps import PROMPTS, strict_object
from app.domains.loader import UnknownDomain
from app.files import schedule_import as imports
from app.files.schedule_import import (
    COLUMNS,
    UNREAD,
    ImportedRow,
    ImportedRows,
    ImportProblem,
    Plan,
    Table,
)
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.tools.context import ToolContext, ToolError
from app.tools.generate.run import RunOut, result_card
from app.tools.generate.run import _out as run_out
from app.tools.registry import call, tool

NEED_LEVEL = "가져오려면 분야(domain)와 정밀도(level)를 정해 주세요. 정밀도는 액티비티 수(rows)에 맞게 고릅니다."
ASK_TITLE = "공정표 가져오기 — 빈 칸 확인"
NEXT_AFTER_CHECK = (  # 확인 결과에 붙는 다음 할 일(I1: 모델이 확인만 되풀이하지 않게)
    "요약 카드를 띄웠다. 카드 내용을 한두 문장으로 말하고 턴을 끝낸다 — 같은 인자로 다시 부르지 않는다. "
    "사용자가 [일정 초안으로 가져오기]를 누르거나 가져오라고 하면 그때 confirmed=true 와 domain·level, 위 columns 그대로 다시 부른다"
    "(domain·level 은 위 값이 카드에 보인 기본값이다 — 대화에서 따로 정했으면 그것)."
)
PREVIEW_ROWS = 20  # 판단에 보여 줄 앞 행 수(숫자는 코드가 센 통계로 따로 준다)
JUDGE_MAX_TOKENS = 12000  # 판단 답의 한도. normal 기본(4000)이면 열 대응 답이 잘려 「표를 판단하지 못했습니다」가 잦다
ESTIMATE_RULES = (
    "- 파일 값은 그대로 쓴다: id·이름·WBS 와 파일에 있는 기간·선행은 코드가 파일 값으로 덮어쓴다.",
    "- '?' 인 칸만 정한다: 기간이 '?' 면 kind 와 od(근무일), 선행이 '?' 면 predecessors(이 표의 id 만).",
    "- '?' 칸이 있는 행만 activities 에 내면 된다(id 그대로). 새 액티비티(착공·준공 마일스톤 포함)는 더하지 않는다 — 더해도 버린다.",
    "- 날짜는 내지 않는다. 파일의 날짜도 코드가 다룬다.",
)
_NULLABLE = {"type": ["string", "null"]}
_QUESTION = strict_object({
    "id": {"type": "string"}, "group": {"type": "string"}, "question": {"type": "string"}, "why": {"type": "string"},
    "options": {"type": "array", "items": strict_object({
        "value": {"type": "string"}, "label": {"type": "string"}, "hint": _NULLABLE, "recommended": {"type": "boolean"},
    })},
    "allow_free": {"type": "boolean"}, "assumption": {"type": "string"},
})
DETECT_SCHEMA = strict_object({"is_schedule": {"type": "boolean"}, "reason": {"type": "string"}})
PLAN_SCHEMA = strict_object({
    **dict.fromkeys(COLUMNS, _NULLABLE),
    "blanks": {"type": "string", "enum": ["ask", "estimate"]},
    "questions": {"type": "array", "items": _QUESTION},
    "start_constraint": {"type": "boolean"}, "finish_constraint": {"type": "boolean"}, "reason": {"type": "string"},
})


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


class AssumedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    assumption: str


class ColumnsIn(BaseModel):
    """확인 단계가 돌려준 columns(열 대응 + 파일 날짜를 제약으로 둘지) 그대로."""

    model_config = ConfigDict(extra="forbid")

    id_col: str | None = None
    name_col: str | None = None
    wbs_col: str | None = None
    duration_col: str | None = None
    pred_col: str | None = None
    start_col: str | None = None
    finish_col: str | None = None
    resource_col: str | None = None
    start_constraint: bool = False
    finish_constraint: bool = False


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int = Field(description="표 파일 id(#번호)")
    sheet: str | None = Field(default=None, description="엑셀 시트 이름. null 이면 첫 시트")
    confirmed: bool = Field(
        default=False, description="사용자가 가져오기를 고르거나 가져오라고 했을 때만 true. false 면 확인(요약 카드)만"
    )
    domain: str | None = Field(
        default=None, description="가져올 때: 분야 id(예: construction, manufacturing, rnd, permitting, procurement, general 등)"
    )
    level: Literal["L1", "L2", "L3", "L4", "L5"] | None = Field(
        default=None, description="가져올 때: 정밀도(액티비티 수에 맞게)"
    )
    answers: list[AnswerIn] = Field(default_factory=list, description="질문지에 답한 것 [{question, answer}]")
    assumed: list[AssumedIn] = Field(default_factory=list, description="답하지 않아 가정한 것 [{question, assumption}]")
    columns: ColumnsIn | None = Field(
        default=None, description="가져올 때: 확인 결과의 columns 그대로. 주면 열 대응을 다시 판단하지 않는다"
    )


class ImportOut(BaseModel):
    step: Literal["checked", "asked", "drafted"]  # 확인만 · 질문지를 열고 멈춤 · 초안을 만들어 승인함에 냄
    is_schedule: bool
    reason: str  # 에이전트 판단의 까닭
    file_id: int
    sheet: str | None
    sheets: list[str]  # 엑셀의 시트 이름들(csv 는 [])
    rows: int  # 코드가 센 액티비티 행 수
    columns_found: list[str]
    missing: list[str]
    columns: dict | None = None  # 열 대응·날짜 판단(카드와 같다) — 가져올 때 그대로 넘긴다
    domain: str | None = None  # checked(공정표): 카드에 보인 가져오기 기본 분야(files.schedule_import.defaults)
    level: str | None = None  # checked(공정표): 카드에 보인 가져오기 기본 정밀도
    next: str | None = None  # checked(공정표): 다음에 할 일(같은 인자로 다시 부르지 않는다)
    questionnaire: dict | None = None  # asked: ask.questionnaire 의 결과
    draft: RunOut | None = None  # drafted: generate.run 과 같은 모양(가정의 source "추정" = 추정한 칸)
    approval: dict | None = None  # drafted: out.submit_change 의 결과(applied=false 면 승인 대기)


@dataclass(frozen=True)
class Detected:
    is_schedule: bool
    reason: str


def _preview(table: Table) -> str:
    lines = [f"파일: {table.title}", "열: " + " | ".join(table.header), f"앞 {PREVIEW_ROWS}행:"]
    return "\n".join(lines + [" | ".join(cells) for _, cells in table.rows[:PREVIEW_ROWS]])


def _stats(table: Table) -> str:
    lines = [f"열마다 값이 있는 칸(코드가 셈, 전체 {len(table.rows)}행):"]
    for i, name in enumerate(table.header):
        values = [cells[i] for _, cells in table.rows if i < len(cells) and cells[i]]
        samples = ", ".join(list(dict.fromkeys(values))[:3])
        lines.append(f"- {name}: 값 {len(values)} · 빈 칸 {len(table.rows) - len(values)}" + (f" · 예: {samples}" if samples else ""))
    return "\n".join(lines)


async def _judge(llm: LlmClient, prompt: str, user: str, schema: dict, ctx: ToolContext) -> object:
    """에이전트 판단 한 번(normal, strict JSON). 답을 읽지 못하면 ImportProblem, LLM 실패는 그대로 올라간다."""
    system = (PROMPTS / f"{prompt}.md").read_text(encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    reply = await llm.chat("normal", messages, json_schema=schema, chat_session_id=ctx.chat_session_id,
                           max_tokens=JUDGE_MAX_TOKENS)
    if reply.parsed is None or reply.finish_reason == "length":
        raise ImportProblem(UNREAD)
    return reply.parsed


async def _detect(llm: LlmClient, table: Table, ctx: ToolContext) -> Detected:
    """표가 공정표인가(에이전트 판단, prompts/import_detect.md)."""
    parsed = await _judge(llm, "import_detect", _preview(table), DETECT_SCHEMA, ctx)
    if not (isinstance(parsed, dict) and isinstance(parsed.get("is_schedule"), bool)):
        raise ImportProblem(UNREAD)
    return Detected(parsed["is_schedule"], str(parsed.get("reason") or ""))


async def _plan(llm: LlmClient, table: Table, ctx: ToolContext) -> Plan:
    """열 대응·빈 칸·날짜 제약(에이전트 판단, prompts/import_map.md). 코드가 센 열 통계를 함께 보낸다."""
    parsed = await _judge(llm, "import_map", f"{_preview(table)}\n{_stats(table)}", PLAN_SCHEMA, ctx)
    return imports.plan_from(parsed, table)


def _request(rows: ImportedRows) -> str:
    """생성 루프에 줄 요청 글: 규칙과 표 전체(빈 칸은 '?'). 담당자원 열이 있으면 자원 열도(빈 칸은 「미지정」 — 추정하지 않는다)."""
    def preds(r: ImportedRow) -> str:
        return "?" if r.preds is None else imports.pred_text(list(r.preds)) or "-"
    has_resources = any(r.resources != () for r in rows.rows)

    def resources(r: ImportedRow) -> str:
        return f" | {', '.join(r.resources or ()) or '미지정'}" if has_resources else ""
    head = [f"파일 「{rows.title}」에서 가져온 공정표다. 아래 액티비티 {len(rows.rows)}개가 전부다.", *ESTIMATE_RULES]
    lines = [f"{r.id} | {r.name} | {r.wbs} | {'?' if r.od is None else r.od} | {preds(r)}{resources(r)}" for r in rows.rows]
    return "\n".join([*head, "id | 이름 | WBS | 기간 | 선행" + (" | 자원" if has_resources else ""), *lines])


def _facts(rows: ImportedRows, args: ImportIn) -> list[dict]:
    """알고 있는 것: 파일, 파일의 가장 이른 시작일(착공일 — 코드가 고른다), 질문지 답."""
    out = [{"label": "가져온 파일", "value": f"{rows.title} · 액티비티 {len(rows.rows)}개", "source": "파일"}]
    if starts := [r.start for r in rows.rows if r.start]:
        out.append({"label": "착공일", "value": min(starts).isoformat(), "source": "파일"})
    return out + [{"label": a.question, "value": a.answer, "source": "질문지"} for a in args.answers]


def _out(step: str, table: Table, is_schedule: bool, reason: str, card: dict | None = None, **more) -> ImportOut:
    card = card or {"rows": len(table.rows), "columns_found": [], "missing": []}
    return ImportOut(step=step, is_schedule=is_schedule, reason=reason, file_id=table.file_id, sheet=table.sheet,
                     sheets=table.sheets, rows=card["rows"], columns_found=card["columns_found"],
                     missing=card["missing"], columns=card.get("columns"), domain=card.get("domain"),
                     level=card.get("level"), **more)


async def _check(ctx: ToolContext, llm: LlmClient, table: Table) -> ImportOut:
    found = await _detect(llm, table, ctx)
    if not found.is_schedule:
        return _out("checked", table, False, found.reason)
    card = imports.card(table, await _plan(llm, table, ctx))
    if card["blank_rows"] > imports.BLANK_LIMIT:  # 추정을 부르기 전에 멈춘다(빈 칸 수는 열 대응에 달려 있다)
        raise ImportProblem(imports.TOO_MANY_BLANKS.format(card["blank_rows"]))
    card |= imports.defaults(ctx.session, ctx.schedule_id, card["rows"])  # 카드 단추가 쓸 기본 분야·정밀도(I1)
    ctx.emit(AgentEvent("card", {"kind": "schedule_file", **card}))
    return _out("checked", table, True, found.reason, card, next=NEXT_AFTER_CHECK)


async def _ask(ctx: ToolContext, args: ImportIn, plan: Plan, rows: ImportedRows) -> dict:
    prefilled = [{"label": "파일", "value": rows.title, "source": "파일"},
                 {"label": "액티비티", "value": f"{len(rows.rows)}개", "source": "파일"}]
    asked = await call("ask.questionnaire", {"purpose": "generate", "title": ASK_TITLE, "domain": args.domain,
                                             "level": args.level, "questions": plan.questions, "prefilled": prefilled}, ctx)
    if not asked.ok:
        raise ToolError(f"질문지를 열지 못했습니다: {asked.error}")
    return asked.output or {}


async def _draft(ctx: ToolContext, llm: LlmClient, args: ImportIn, rows: ImportedRows) -> RunOut:
    facts = _facts(rows, args)
    assumed = [{"label": a.question, "value": a.assumption, "source": "가정"} for a in args.assumed]
    try:
        result = await generate(ctx, llm, domain=args.domain, level=args.level, request=_request(rows), facts=facts,
                                assumptions=assumed, fixed=rows, max_rounds=2)  # 파일 값이 많아 고칠 것이 적다
    except UnknownDomain:
        raise ToolError(f"올바르지 않은 분야입니다: {args.domain}") from None
    out = run_out(result)
    ctx.emit(result_card(out))
    return out


async def _import(ctx: ToolContext, llm: LlmClient, table: Table, args: ImportIn) -> ImportOut:
    plan = imports.plan_from(args.columns.model_dump(), table) if args.columns else await _plan(llm, table, ctx)
    rows = imports.convert(table, plan)  # 액티비티 400·빈 칸 150 한도는 여기서 — 추정 LLM 전
    card = imports.card(table, plan)
    answered = bool(args.answers or args.assumed)
    if rows.blanks and not answered and args.columns:  # 열 대응은 넘긴 것 그대로, 빈 칸을 물을지만 판단을 받는다
        judged = await _plan(llm, table, ctx)
        plan = plan.model_copy(update={"blanks": judged.blanks, "questions": judged.questions, "reason": judged.reason})
    if rows.blanks and plan.blanks == "ask" and plan.questions and not answered:
        return _out("asked", table, True, plan.reason, card, questionnaire=await _ask(ctx, args, plan, rows))
    draft = await _draft(ctx, llm, args, rows)
    if draft.draft_id is None and not ctx.stop_requested():  # 초안이 하나도 없다 — generate.run 처럼 실패한 단계로(A2)
        raise ToolError(draft.reason or "일정 초안을 만들지 못했습니다.")
    approval = None
    if draft.draft_id is not None:  # 기존 첫 저장 길(승인함)
        sent = await call("out.submit_change", {"title": f"{table.name} 가져오기"[:100], "draft_id": draft.draft_id}, ctx)
        if not sent.ok:
            raise ToolError(f"초안({draft.draft_id})은 만들었지만 승인 요청을 내지 못했습니다: {sent.error}")
        approval = sent.output
    return _out("drafted", table, True, plan.reason, card, draft=draft, approval=approval)


@tool(
    "schedule.import",
    "공정표 파일(csv·tsv·xlsx)을 일정 초안으로 가져온다. 먼저 confirmed=false 로 부르면 표를 끝까지 읽고 공정표인지 판단해, "
    "공정표면 요약 카드(액티비티 수·찾은 열·빠진 것·[일정 초안으로 가져오기])를 대화에 띄운다 — 가져오지는 않는다. "
    "사용자가 가져오기를 고르거나 가져오라고 하면 confirmed=true 와 domain·level, 확인 결과의 columns 로 다시 부른다. 물을 빈 칸이 있으면 "
    "질문지를 열고 멈춘다(step asked) — 제출되면 answers·assumed 를 넣어 다시 부른다. 아니면 빈 칸만 추정해 초안을 "
    "만들고 승인함에 낸다(step drafted, draft·approval). 파일 값은 그대로 두고, 추정한 칸은 가정(source 추정)에 남는다. "
    "날짜는 코드가 계산한다. approval.applied=false 면 승인을 기다리는 중이니 저장했다고 말하지 않는다.",
    mutates=True,
)
async def import_schedule(args: ImportIn, ctx: ToolContext) -> ImportOut:
    # 질문지 답(answers·assumed)을 넣어 다시 부른 것은 가져오기다 — confirmed 를 빠뜨려도 확인 단계로 되돌아가지 않는다(I1).
    confirmed = args.confirmed or bool(args.answers or args.assumed)
    if confirmed and (args.domain is None or args.level is None):
        raise ToolError(NEED_LEVEL)
    llm = package.client_for(ctx)
    try:
        table = await asyncio.to_thread(imports.read_table, ctx.session, args.file_id, args.sheet)  # 원본 전체 — 루프를 막지 않게
        if len(table.rows) > imports.MAX_ACTIVITIES:  # 코드가 센다 — 판단(LLM)을 부르기 전에
            raise ImportProblem(imports.TOO_MANY_ROWS.format(len(table.rows)))
        return await (_import(ctx, llm, table, args) if confirmed else _check(ctx, llm, table))
    except ImportProblem as e:
        raise ToolError(e.message) from None
    except LlmNotReady as e:
        raise ToolError(e.message) from None
    except LlmFailed as e:
        raise ToolError(e.error.message) from None
