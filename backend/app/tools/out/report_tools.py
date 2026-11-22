"""에이전트용 보고서 도구: 양식 학습·기억(report.learn_template), 월간·분기별 보고서 생성(report.generate)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.errors import ApiError
from app.programs.reports import service
from app.programs.reports.schemas import ReportGenerateIn, ReportReviseIn, TemplateLearnIn, TemplateOut
from app.store.tables import User
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool


def _actor(ctx: ToolContext) -> User:
    if ctx.user is not None:
        return ctx.user
    return User(id=0, name="에이전트", login_id="agent", password_hash="", role="user", status="active")


class LearnTemplateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int = Field(description="올려진 보고서 양식 파일 ID")
    schedule_id: int | None = Field(default=None, description="기억할 프로젝트 일정 ID(없으면 지금 일정)")
    cadence: Literal["monthly", "quarterly"] | None = Field(default=None, description="월간(monthly) 또는 분기별(quarterly)")
    name: str | None = Field(default=None, description="양식 이름")


class LearnTemplateOut(BaseModel):
    template_id: int
    name: str
    cadence: Literal["monthly", "quarterly"]
    sections_count: int
    analysis_summary: str


class GenerateReportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: Literal["monthly", "quarterly"] = Field(description="monthly(월간) 또는 quarterly(분기별)")
    schedule_id: int | None = Field(default=None, description="대상 일정 ID(없으면 지금 일정)")
    template_id: int | None = Field(default=None, description="특정 양식 ID(다른 프로젝트 양식도 지정 가능, 없으면 현재 프로젝트 기본 양식)")
    period_label: str | None = Field(default=None, description="예: 2027년 6월 또는 2027년 2분기")
    title: str | None = Field(default=None, description="보고서 제목")
    extra_note: str = Field(default="", description="보고서에 덧붙일 특기사항")


class GenerateReportOut(BaseModel):
    report_id: int
    title: str
    cadence: Literal["monthly", "quarterly"]
    period_label: str
    template_name: str
    sections_count: int


class ListTemplatesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = Field(default=None, description="조회할 일정 id(없으면 지금 일정)")
    cadence: Literal["monthly", "quarterly"] | None = Field(default=None, description="월간(monthly) 또는 분기별(quarterly)")


class TemplateRefOut(BaseModel):
    id: int | None
    builtin_key: str | None
    project_name: str | None
    cadence: Literal["monthly", "quarterly"]
    name: str
    is_default: bool
    sections_count: int
    tone: str


class ListTemplatesOut(BaseModel):
    current_project: list[TemplateRefOut]
    other_projects: list[TemplateRefOut]
    builtins: list[TemplateRefOut]


class ReviseReportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int = Field(description="수정할 보고서 ID")
    block_id: str = Field(min_length=1, description="수정할 보고서 블록(섹션) ID")
    instruction: str = Field(min_length=1, max_length=500, description="어떻게 수정할지 지시")
    schedule_id: int | None = Field(default=None, description="대상 일정 ID(없으면 지금 일정)")
    remember_rule: bool = Field(default=False, description="수정 지시를 양식 말투·규칙에 기억할지 여부")


class ReviseReportOut(BaseModel):
    report_id: int
    block_id: str
    heading: str
    updated_text: str


def _tpl_ref(t: TemplateOut) -> TemplateRefOut:
    return TemplateRefOut(
        id=t.id,
        builtin_key=t.builtin_key,
        project_name=t.project_name,
        cadence=t.cadence,
        name=t.name,
        is_default=t.is_default,
        sections_count=len(t.sections),
        tone=t.style.tone,
    )


@tool(
    "report.learn_template",
    "사용자가 올린 기존 보고서 파일(file_id)에서 목차·표 구조·말투를 학습하고 현재 프로젝트 기본 양식으로 기억한다.",
    program="reports",
    mutates=True,
)
async def learn_template(args: LearnTemplateArgs, ctx: ToolContext) -> LearnTemplateOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        learned = await service.learn_template(
            ctx.session,
            _actor(ctx),
            TemplateLearnIn(file_id=args.file_id, schedule_id=sid, cadence=args.cadence, name=args.name, auto_save=True),
        )
    except ApiError as e:
        raise ToolError(e.message) from None
    saved = learned.saved_template
    assert saved is not None and saved.id is not None
    ctx.emit(
        AgentEvent(
            "card",
            {
                "kind": "report_template",
                "template_id": saved.id,
                "schedule_id": sid,
                "cadence": saved.cadence,
                "name": saved.name,
                "summary": learned.analysis_summary,
            },
        )
    )
    return LearnTemplateOut(
        template_id=saved.id,
        name=saved.name,
        cadence=saved.cadence,
        sections_count=len(saved.sections),
        analysis_summary=learned.analysis_summary,
    )


@tool(
    "report.generate",
    "현재 일정의 월간(monthly) 또는 분기별(quarterly) 보고서를 작성한다. 이 프로젝트에 학습·기억된 양식이 있으면 자동 반영한다.",
    program="reports",
    mutates=True,
)
async def generate_report(args: GenerateReportArgs, ctx: ToolContext) -> GenerateReportOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        report = await service.generate_report(
            ctx.session,
            _actor(ctx),
            sid,
            ReportGenerateIn(
                cadence=args.cadence,
                template_id=args.template_id,
                period_label=args.period_label,
                title=args.title,
                extra_note=args.extra_note,
            ),
        )
    except ApiError as e:
        raise ToolError(e.message) from None
    ctx.emit(
        AgentEvent(
            "card",
            {
                "kind": "report",
                "report_id": report.id,
                "schedule_id": sid,
                "cadence": report.cadence,
                "title": report.title,
                "template_name": report.template_name,
            },
        )
    )
    return GenerateReportOut(
        report_id=report.id,
        title=report.title,
        cadence=report.cadence,
        period_label=report.period_label,
        template_name=report.template_name,
        sections_count=len(report.blocks),
    )


@tool(
    "report.list_templates",
    "현재 프로젝트에 기억된 보고서 양식, 다른 프로젝트에서 학습된 양식, 기본 내장 양식 목록을 조회한다.",
    program="reports",
)
def list_templates(args: ListTemplatesArgs, ctx: ToolContext) -> ListTemplatesOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        res = service.list_templates(ctx.session, sid, args.cadence)
    except ApiError as e:
        raise ToolError(e.message) from None
    return ListTemplatesOut(
        current_project=[_tpl_ref(t) for t in res.current_project],
        other_projects=[_tpl_ref(t) for t in res.other_projects],
        builtins=[_tpl_ref(t) for t in res.builtins],
    )


@tool(
    "report.revise",
    "생성된 월간·분기별 보고서의 특정 항목(block_id)을 사용자 지시대로 다듬어 수정한다.",
    program="reports",
    mutates=True,
)
async def revise_report(args: ReviseReportArgs, ctx: ToolContext) -> ReviseReportOut:
    sid = args.schedule_id if args.schedule_id is not None else ctx.require_schedule_id()
    try:
        report = await service.revise_report_block(
            ctx.session,
            sid,
            args.report_id,
            ReportReviseIn(
                block_id=args.block_id,
                instruction=args.instruction,
                remember_rule=args.remember_rule,
            ),
        )
    except ApiError as e:
        raise ToolError(e.message) from None
    ctx.emit(
        AgentEvent(
            "card",
            {
                "kind": "report",
                "report_id": report.id,
                "schedule_id": sid,
                "cadence": report.cadence,
                "title": report.title,
                "template_name": report.template_name,
            },
        )
    )
    updated = next((b for b in report.blocks if b.id == args.block_id), None)
    return ReviseReportOut(
        report_id=report.id,
        block_id=args.block_id,
        heading=updated.heading if updated else "",
        updated_text=updated.text if updated else "",
    )
