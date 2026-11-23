"""보고서 및 양식 관리 서비스(프로젝트별 기억 · 타 프로젝트 양식 선택/복사)."""

from datetime import datetime
from urllib.parse import quote

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.reports import export, generator, learner
from app.programs.reports.schemas import (
    Cadence,
    ReportGenerateIn,
    ReportListOut,
    ReportOut,
    ReportRegenerateIn,
    ReportReviseIn,
    ReportSummaryOut,
    ReportUpdateIn,
    StyleMemory,
    TemplateAdoptIn,
    TemplateCreateIn,
    TemplateLearnIn,
    TemplateLearnOut,
    TemplateListOut,
    TemplateOut,
    TemplateSection,
    TemplateUpdateIn,
)
from app.programs.reports.templates_builtin import (
    BUILTIN_MONTHLY,
    BUILTIN_QUARTERLY,
    builtin_template,
)
from app.store.schedules import NotFound as ScheduleNotFound
from app.store.schedules import get_record, list_records
from app.store.tables import ReportRow, ReportTemplate, User


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _template_out(row: ReportTemplate, project_names: dict[int, str]) -> TemplateOut:
    return TemplateOut(
        id=row.id,
        builtin_key=None,
        schedule_id=row.schedule_id,
        project_name=project_names.get(row.schedule_id),
        cadence=row.cadence,  # type: ignore[arg-type]
        name=row.name,
        is_default=row.is_default,
        is_builtin=False,
        source_file_id=row.source_file_id,
        source_file_name=row.source_file_name,
        sections=[TemplateSection.model_validate(s) for s in (row.sections_json or [])],
        style=StyleMemory.model_validate(row.style_json or {}),
        created_by=row.created_by,
        updated_at=_iso(row.updated_at),
    )


def _report_summary(row: ReportRow) -> ReportSummaryOut:
    return ReportSummaryOut(
        id=row.id,
        schedule_id=row.schedule_id,
        template_id=row.template_id,
        template_name=row.template_name,
        cadence=row.cadence,  # type: ignore[arg-type]
        period_label=row.period_label,
        title=row.title,
        data_date=row.data_date,
        schedule_version=row.schedule_version,
        status=row.status,
        created_by=row.created_by,
        updated_at=row.updated_at.isoformat(),
    )


def _report_out(row: ReportRow) -> ReportOut:
    return ReportOut(
        **_report_summary(row).model_dump(),
        blocks=row.blocks_json or [],
        style=StyleMemory.model_validate(row.style_json or {}),
    )


def _require_schedule(session: Session, schedule_id: int) -> None:
    try:
        get_record(session, schedule_id)
    except ScheduleNotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None


def _clear_defaults(session: Session, schedule_id: int, cadence: Cadence) -> None:
    rows = session.scalars(
        select(ReportTemplate).where(
            ReportTemplate.schedule_id == schedule_id,
            ReportTemplate.cadence == cadence,
            ReportTemplate.is_default.is_(True),
        )
    )
    for r in rows:
        r.is_default = False


def list_templates(session: Session, schedule_id: int, cadence: Cadence | None = None) -> TemplateListOut:
    _require_schedule(session, schedule_id)
    project_names = {r.id: r.name for r in list_records(session)}
    stmt = select(ReportTemplate).order_by(ReportTemplate.is_default.desc(), ReportTemplate.updated_at.desc(), ReportTemplate.id.desc())
    if cadence is not None:
        stmt = stmt.where(ReportTemplate.cadence == cadence)
    all_rows = list(session.scalars(stmt))

    current = [_template_out(r, project_names) for r in all_rows if r.schedule_id == schedule_id]
    others = [_template_out(r, project_names) for r in all_rows if r.schedule_id != schedule_id]
    builtins = [BUILTIN_MONTHLY.model_copy(deep=True), BUILTIN_QUARTERLY.model_copy(deep=True)]
    if cadence is not None:
        builtins = [b for b in builtins if b.cadence == cadence]
    return TemplateListOut(current_project=current, other_projects=others, builtins=builtins)


async def learn_template(session: Session, user: User, body: TemplateLearnIn) -> TemplateLearnOut:
    _require_schedule(session, body.schedule_id)
    file_name, name, cadence, sections, style, summary = await learner.learn_from_file(
        session, body.file_id, body.cadence, body.name
    )
    saved: TemplateOut | None = None
    if body.auto_save:
        saved = create_template(
            session,
            user,
            TemplateCreateIn(
                schedule_id=body.schedule_id,
                cadence=cadence,
                name=name,
                is_default=True,
                source_file_id=body.file_id,
                source_file_name=file_name,
                sections=sections,
                style=style,
            ),
        )
    return TemplateLearnOut(
        suggested_name=name,
        suggested_cadence=cadence,
        source_file_id=body.file_id,
        source_file_name=file_name,
        analysis_summary=summary,
        sections=sections,
        style=style,
        saved_template=saved,
    )


def create_template(session: Session, user: User, body: TemplateCreateIn) -> TemplateOut:
    _require_schedule(session, body.schedule_id)
    if body.is_default:
        _clear_defaults(session, body.schedule_id, body.cadence)
    row = ReportTemplate(
        schedule_id=body.schedule_id,
        cadence=body.cadence,
        name=body.name.strip(),
        is_default=body.is_default,
        source_file_id=body.source_file_id,
        source_file_name=body.source_file_name,
        sections_json=[s.model_dump() for s in body.sections],
        style_json=body.style.model_dump(),
        created_by=user.name,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _template_out(row, {r.id: r.name for r in list_records(session)})


def update_template(session: Session, template_id: int, body: TemplateUpdateIn) -> TemplateOut:
    row = session.get(ReportTemplate, template_id)
    if row is None:
        raise ApiError(404, "not_found", "보고서 양식을 찾을 수 없습니다.")
    target_cadence: Cadence = body.cadence or row.cadence  # type: ignore[assignment]
    if body.is_default is True:
        _clear_defaults(session, row.schedule_id, target_cadence)
        row.is_default = True
    elif body.is_default is False:
        row.is_default = False
    if body.name is not None:
        row.name = body.name.strip()
    if body.cadence is not None:
        row.cadence = body.cadence
    if body.sections is not None:
        row.sections_json = [s.model_dump() for s in body.sections]
    if body.style is not None:
        row.style_json = body.style.model_dump()
    session.commit()
    session.refresh(row)
    return _template_out(row, {r.id: r.name for r in list_records(session)})


def adopt_template(session: Session, user: User, template_id: int, body: TemplateAdoptIn) -> TemplateOut:
    _require_schedule(session, body.schedule_id)
    src = session.get(ReportTemplate, template_id)
    if src is None:
        raise ApiError(404, "not_found", "가져올 보고서 양식을 찾을 수 없습니다.")
    cadence: Cadence = src.cadence  # type: ignore[assignment]
    if body.is_default:
        _clear_defaults(session, body.schedule_id, cadence)
    clone = ReportTemplate(
        schedule_id=body.schedule_id,
        cadence=cadence,
        name=(body.name or src.name).strip(),
        is_default=body.is_default,
        source_file_id=src.source_file_id,
        source_file_name=src.source_file_name,
        sections_json=list(src.sections_json or []),
        style_json=dict(src.style_json or {}),
        created_by=user.name,
    )
    session.add(clone)
    session.commit()
    session.refresh(clone)
    return _template_out(clone, {r.id: r.name for r in list_records(session)})


def delete_template(session: Session, template_id: int) -> None:
    row = session.get(ReportTemplate, template_id)
    if row is None:
        raise ApiError(404, "not_found", "보고서 양식을 찾을 수 없습니다.")
    session.delete(row)
    session.commit()


def _resolve_template(
    session: Session, schedule_id: int, cadence: Cadence, template_id: int | None, use_builtin: bool
) -> tuple[int | None, str, list[TemplateSection], StyleMemory]:
    if use_builtin:
        b = builtin_template(cadence)
        return None, b.name, b.sections, b.style
    if template_id is not None:
        row = session.get(ReportTemplate, template_id)
        if row is None:
            raise ApiError(404, "not_found", "선택한 보고서 양식을 찾을 수 없습니다.")
        return (
            row.id,
            row.name,
            [TemplateSection.model_validate(s) for s in (row.sections_json or [])],
            StyleMemory.model_validate(row.style_json or {}),
        )
    # 프로젝트별 기억: 현재 프로젝트(schedule_id)의 기본 양식만 자동 회상한다.
    project_default = session.scalar(
        select(ReportTemplate)
        .where(
            ReportTemplate.schedule_id == schedule_id,
            ReportTemplate.cadence == cadence,
            ReportTemplate.is_default.is_(True),
        )
        .order_by(ReportTemplate.updated_at.desc(), ReportTemplate.id.desc())
        .limit(1)
    )
    if project_default is not None:
        return (
            project_default.id,
            project_default.name,
            [TemplateSection.model_validate(s) for s in (project_default.sections_json or [])],
            StyleMemory.model_validate(project_default.style_json or {}),
        )
    b = builtin_template(cadence)
    return None, b.name, b.sections, b.style


def list_reports(session: Session, schedule_id: int, cadence: Cadence | None = None) -> ReportListOut:
    _require_schedule(session, schedule_id)
    stmt = (
        select(ReportRow)
        .where(ReportRow.schedule_id == schedule_id)
        .order_by(ReportRow.updated_at.desc(), ReportRow.id.desc())
    )
    if cadence is not None:
        stmt = stmt.where(ReportRow.cadence == cadence)
    rows = list(session.scalars(stmt))
    return ReportListOut(items=[_report_summary(r) for r in rows])


def _get_report(session: Session, schedule_id: int, report_id: int) -> ReportRow:
    row = session.get(ReportRow, report_id)
    if row is None or row.schedule_id != schedule_id:
        raise ApiError(404, "not_found", "보고서를 찾을 수 없습니다.")
    return row


def get_report(session: Session, schedule_id: int, report_id: int) -> ReportOut:
    return _report_out(_get_report(session, schedule_id, report_id))


async def generate_report(session: Session, user: User, schedule_id: int, body: ReportGenerateIn) -> ReportOut:
    _require_schedule(session, schedule_id)
    tpl_id, tpl_name, sections, style = _resolve_template(
        session, schedule_id, body.cadence, body.template_id, body.use_builtin
    )
    from app.programs.progress import (
        service as progress_service,  # circular avoidance check: clean
    )

    prog_date = progress_service.progress(session, schedule_id, "month").data_date
    period_label = (body.period_label or "").strip() or generator.default_period_label(prog_date, body.cadence)
    project_name, data_date, version, blocks = await generator.generate_report_blocks(
        session, schedule_id, body.cadence, period_label, sections, style, body.extra_note
    )
    title = (body.title or "").strip() or generator.default_title(project_name, body.cadence, period_label)
    row = ReportRow(
        schedule_id=schedule_id,
        template_id=tpl_id,
        template_name=tpl_name,
        cadence=body.cadence,
        period_label=period_label,
        title=title,
        data_date=generator.format_date(data_date, style.date_format),
        schedule_version=version,
        status="draft",
        blocks_json=[b.model_dump() for b in blocks],
        style_json=style.model_dump(),
        created_by=user.name,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _report_out(row)


def update_report(session: Session, schedule_id: int, report_id: int, body: ReportUpdateIn) -> ReportOut:
    row = _get_report(session, schedule_id, report_id)
    if body.title is not None:
        row.title = body.title.strip()
    if body.period_label is not None:
        row.period_label = body.period_label.strip()
    if body.status is not None:
        row.status = body.status
    if body.blocks is not None:
        row.blocks_json = [b.model_dump() for b in body.blocks]
    session.commit()
    session.refresh(row)
    return _report_out(row)


async def regenerate_report(session: Session, schedule_id: int, report_id: int, body: ReportRegenerateIn) -> ReportOut:
    row = _get_report(session, schedule_id, report_id)
    cadence: Cadence = row.cadence  # type: ignore[assignment]
    tpl_id, tpl_name, sections, style = _resolve_template(
        session, schedule_id, cadence, body.template_id if body.template_id is not None else row.template_id, body.use_builtin
    )
    _, data_date, version, blocks = await generator.generate_report_blocks(
        session, schedule_id, cadence, row.period_label, sections, style, body.extra_note
    )
    row.template_id = tpl_id
    row.template_name = tpl_name
    row.data_date = generator.format_date(data_date, style.date_format)
    row.schedule_version = version
    row.blocks_json = [b.model_dump() for b in blocks]
    row.style_json = style.model_dump()
    session.commit()
    session.refresh(row)
    return _report_out(row)


async def revise_report_block(session: Session, schedule_id: int, report_id: int, body: ReportReviseIn) -> ReportOut:
    row = _get_report(session, schedule_id, report_id)
    blocks = list(row.blocks_json or [])
    idx = next((i for i, b in enumerate(blocks) if b.get("id") == body.block_id), -1)
    if idx < 0:
        raise ApiError(404, "not_found", "수정할 보고서 항목을 찾을 수 없습니다.")
    style = StyleMemory.model_validate(row.style_json or {})
    new_text = await generator.revise_block_text(
        session, blocks[idx], body.instruction, style, schedule_id=schedule_id
    )

    updated = dict(blocks[idx])
    updated["text"] = new_text
    blocks[idx] = updated
    row.blocks_json = blocks

    if body.remember_rule:
        rule = body.instruction.strip()
        if rule and rule not in style.learned_rules:
            style.learned_rules = [*style.learned_rules, rule][:15]
            row.style_json = style.model_dump()
        if row.template_id is not None:
            tpl = session.get(ReportTemplate, row.template_id)
            if tpl is not None and tpl.schedule_id == schedule_id:
                t_style = StyleMemory.model_validate(tpl.style_json or {})
                if rule and rule not in t_style.learned_rules:
                    t_style.learned_rules = [*t_style.learned_rules, rule][:15]
                    tpl.style_json = t_style.model_dump()

    session.commit()
    session.refresh(row)
    return _report_out(row)


def delete_report(session: Session, schedule_id: int, report_id: int) -> None:
    row = _get_report(session, schedule_id, report_id)
    session.delete(row)
    session.commit()


def export_report(session: Session, schedule_id: int, report_id: int, fmt: str) -> Response:
    row = _get_report(session, schedule_id, report_id)
    project_name = get_record(session, schedule_id).name
    safe_base = quote(f"{row.title}".replace("/", "_"))
    if fmt == "docx":
        data = export.render_docx(row, project_name)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_base}.docx"},
        )
    html = export.render_html(row, project_name)
    return Response(content=html, media_type="text/html; charset=utf-8")
