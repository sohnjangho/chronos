"""보고서 및 학습 양식 API 라우터 (월간 · 분기별, 일간 제외)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.reports import service
from app.programs.reports.schemas import (
    Cadence,
    ReportGenerateIn,
    ReportListOut,
    ReportOut,
    ReportRegenerateIn,
    ReportReviseIn,
    ReportUpdateIn,
    TemplateAdoptIn,
    TemplateCreateIn,
    TemplateLearnIn,
    TemplateLearnOut,
    TemplateListOut,
    TemplateOut,
    TemplateUpdateIn,
)
from app.security.deps import current_user
from app.store.tables import User

templates_router = APIRouter(prefix="/api/reports/templates", tags=["reports"], dependencies=[Depends(current_user)])
router = APIRouter(prefix="/api/schedules", tags=["reports"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@templates_router.get("")
def list_templates(schedule_id: int, session: SessionDep, cadence: Cadence | None = None) -> TemplateListOut:
    return service.list_templates(session, schedule_id, cadence)


@templates_router.post("/learn")
async def learn_template(body: TemplateLearnIn, session: SessionDep, user: UserDep) -> TemplateLearnOut:
    return await service.learn_template(session, user, body)


@templates_router.post("")
def create_template(body: TemplateCreateIn, session: SessionDep, user: UserDep) -> TemplateOut:
    return service.create_template(session, user, body)


@templates_router.patch("/{template_id}")
def update_template(template_id: int, body: TemplateUpdateIn, session: SessionDep) -> TemplateOut:
    return service.update_template(session, template_id, body)


@templates_router.post("/{template_id}/adopt")
def adopt_template(template_id: int, body: TemplateAdoptIn, session: SessionDep, user: UserDep) -> TemplateOut:
    return service.adopt_template(session, user, template_id, body)


@templates_router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, session: SessionDep) -> Response:
    service.delete_template(session, template_id)
    return Response(status_code=204)


@router.get("/{schedule_id}/reports")
def list_reports(schedule_id: int, session: SessionDep, cadence: Cadence | None = None) -> ReportListOut:
    return service.list_reports(session, schedule_id, cadence)


@router.post("/{schedule_id}/reports")
async def generate_report(schedule_id: int, body: ReportGenerateIn, session: SessionDep, user: UserDep) -> ReportOut:
    return await service.generate_report(session, user, schedule_id, body)


@router.get("/{schedule_id}/reports/{report_id}")
def get_report(schedule_id: int, report_id: int, session: SessionDep) -> ReportOut:
    return service.get_report(session, schedule_id, report_id)


@router.patch("/{schedule_id}/reports/{report_id}")
def update_report(schedule_id: int, report_id: int, body: ReportUpdateIn, session: SessionDep) -> ReportOut:
    return service.update_report(session, schedule_id, report_id, body)


@router.post("/{schedule_id}/reports/{report_id}/regenerate")
async def regenerate_report(schedule_id: int, report_id: int, body: ReportRegenerateIn, session: SessionDep) -> ReportOut:
    return await service.regenerate_report(session, schedule_id, report_id, body)


@router.post("/{schedule_id}/reports/{report_id}/revise")
async def revise_report_block(schedule_id: int, report_id: int, body: ReportReviseIn, session: SessionDep) -> ReportOut:
    return await service.revise_report_block(session, schedule_id, report_id, body)


@router.delete("/{schedule_id}/reports/{report_id}", status_code=204)
def delete_report(schedule_id: int, report_id: int, session: SessionDep) -> Response:
    service.delete_report(session, schedule_id, report_id)
    return Response(status_code=204)


@router.get("/{schedule_id}/reports/{report_id}/export")
def export_report(schedule_id: int, report_id: int, session: SessionDep, format: Literal["html", "docx"] = "html") -> Response:
    return service.export_report(session, schedule_id, report_id, format)
