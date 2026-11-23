"""보고서 수치 집계 및 양식 슬롯 채우기(숫자·표는 코드 계산, 서술만 AI/규칙 작성)."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.llm import fake
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.programs.progress import service as progress_service
from app.programs.progress.schemas import ProgressOut
from app.programs.reports.schemas import (
    Cadence,
    ReportBlock,
    StyleMemory,
    TemplateSection,
)
from app.store import delays as delays_store
from app.store import scenarios as scenarios_store
from app.store.schedules import get_record

logger = logging.getLogger(__name__)

_RESP_LABEL = {"owner": "발주처", "ours": "시공사/우리", "force": "불가항력", "undecided": "미정"}
_STATUS_LABEL = {"open": "열림(검토 중)", "reflected": "반영됨"}
_SCEN_STATUS = {"open": "검토 중", "submitted": "승인 대기", "applied": "반영 완료", "discarded": "폐기"}


def format_date(d: date | str | None, fmt: str) -> str:
    if d is None:
        return "—"
    dt = date.fromisoformat(d) if isinstance(d, str) else d
    if fmt == "YYYY-MM-DD":
        return dt.isoformat()
    if fmt == "MM.DD":
        return f"{dt.month:02d}.{dt.day:02d}"
    return f"{dt.year}.{dt.month:02d}.{dt.day:02d}"


def default_period_label(data_date: date, cadence: Cadence) -> str:
    if cadence == "quarterly":
        q = (data_date.month - 1) // 3 + 1
        return f"{data_date.year}년 {q}분기"
    return f"{data_date.year}년 {data_date.month}월"


def default_title(project_name: str, cadence: Cadence, period_label: str) -> str:
    prefix = "분기별 공정 보고서" if cadence == "quarterly" else "월간 공정 보고서"
    return f"{prefix} — {project_name} ({period_label})"


def _fmt_pct(val: float, precision: int) -> str:
    return f"{val:.{precision}f}%"


def _fmt_signed(val: float, precision: int) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.{precision}f}"


# 표 종류마다 기본 열(순서대로)의 값을 넣을 양식 열 이름에 들어 있을 낱말.
_COL_WORDS: dict[str, list[tuple[str, ...]]] = {
    "wbs_table": [("wbs", "공종", "구분", "작업", "항목", "분류"), ("가중", "비중", "비율"), ("계획",), ("실적",),
                  ("차이", "편차", "증감")],
    "milestone_table": [("마일스톤", "구분", "이름", "항목", "공종"), ("계획", "plan", "기준"), ("예측", "실적", "전망", "예상"),
                        ("차이", "편차", "지연"), ("상태", "특기", "비고", "결과")],
    "delay_table": [("사건", "작업", "공종", "원인", "내용", "항목"), ("책임", "귀책"), ("영향", "준공", "지연일", "일수"),
                    ("상태", "대책", "조치", "결과")],
    "lookahead_3w": [("일자", "날짜", "기간", "일정", "예정", "시기"), ("구분", "상태"), ("작업", "공종", "액티비티", "항목"),
                     ("선행", "유의", "조치", "점검", "비고")],
    "scenario_compare": [("시나리오", "대안", "만회안", "이름"), ("준공", "완료일", "종료"), ("차이", "단축", "효과", "증감"),
                         ("크리티컬 수", "크리티컬 작업", "주공정 수"), ("상태", "승인", "결과")],
}


def _fit_columns(binding: str, custom: list[str], std: list[str]) -> tuple[list[str], list[int | None]]:
    """양식 열마다 뜻이 맞는 기본 열 번호(없으면 None). 이름 끝 쪽 낱말이 뜻을 정한다(「준공 차이」 → 차이).
    양식 열이 없거나 기본 열의 절반도 못 맞추면 기본 열을 그대로 쓴다(틀린 칸보다 낫다)."""
    same: list[int | None] = list(range(len(std)))
    plain = (list(std), same)
    if not custom:
        return plain
    words = _COL_WORDS[binding]
    used: set[int] = set()
    picks: list[int | None] = []
    for col in custom:
        name = col.lower()
        best: tuple[int, int] | None = None  # (낱말이 끝나는 자리, 기본 열 번호)
        for i, ws in enumerate(words):
            if i in used:
                continue
            ends = [name.rfind(w) + len(w) for w in ws if w in name]
            if ends and (best is None or max(ends) > best[0]):
                best = (max(ends), i)
        if best is not None:
            used.add(best[1])
        picks.append(None if best is None else best[1])
    if len(used) * 2 < len(std):
        return plain
    return list(custom), picks


def _pick(row: list[object], picks: list[int | None]) -> list[object]:
    return ["—" if i is None else row[i] for i in picks]


def _deterministic_summary(
    project_name: str,
    cadence: Cadence,
    period_label: str,
    prog: ProgressOut,
    delay_events: list[dict],
    style: StyleMemory,
    extra_note: str = "",
) -> str:
    p = style.number_precision
    spi_txt = f"{prog.spi:.2f}" if prog.spi is not None else "산출 전"
    delta = prog.finish.delta
    if delta is None:
        finish_desc = f"예상 준공일은 {format_date(prog.finish.current, style.date_format)}"
    elif delta > 0:
        finish_desc = f"예상 준공일은 Plan({format_date(prog.finish.plan, style.date_format)}) 대비 +{delta}일 지연된 {format_date(prog.finish.current, style.date_format)}"
    elif delta < 0:
        finish_desc = f"예상 준공일은 Plan 대비 {abs(delta)}일 앞선 {format_date(prog.finish.current, style.date_format)}"
    else:
        finish_desc = f"예상 준공일은 Plan({format_date(prog.finish.current, style.date_format)})과 동일"

    is_bullet = "개조식" in style.tone or "~함" in style.tone
    period_word = "분기" if cadence == "quarterly" else "월간"
    open_n = sum(1 for ev in delay_events if ev.get("status") == "open")
    events_txt = f"기록된 지연 사건 {len(delay_events)}건"
    if delay_events:
        events_txt += "(모두 반영)" if open_n == 0 else f"(열림 {open_n}건)"

    if is_bullet:
        lines = [
            (f"• {project_name} {period_label}({period_word}) 실적 공정률 {_fmt_pct(prog.actual_now, p)} "
            f"(계획 {_fmt_pct(prog.plan_now, p)}, 차이 {_fmt_signed(prog.gap, p)}%p, SPI {spi_txt}) 기록함."),
            (f"• {finish_desc}이며 전체 {prog.counts.total}개 작업 중 완료 {prog.counts.done}건, 진행 {prog.counts.in_progress}건, "
            f"계획보다 늦은 작업 {prog.counts.late}건임."),
            f"• {events_txt}, 향후 3주 착수·종료 예정 작업({len(prog.lookahead.starts) + len(prog.lookahead.finishes)}건) 선행 조건 점검 필요함.",
        ]
    else:
        lines = [
            (f"{project_name}의 {period_label} {period_word} 공정률은 계획 {_fmt_pct(prog.plan_now, p)} 대비 "
            f"실적 {_fmt_pct(prog.actual_now, p)}({ _fmt_signed(prog.gap, p) }%p), SPI {spi_txt}입니다."),
            (f"{finish_desc}이며, 총 {prog.counts.total}개 액티비티 중 {prog.counts.done}개가 완료되었고 "
            f"{prog.counts.in_progress}개가 진행 중이며, 계획보다 늦은 작업은 {prog.counts.late}개입니다."),
            f"{events_txt}이며, 향후 3주 내 예정된 작업 착수 및 선행 공정 관리를 통해 공기 준수를 도모합니다.",
        ]
    if extra_note.strip():
        lines.append(f"• 특기사항: {extra_note.strip()}" if is_bullet else f"특기사항으로 {extra_note.strip()}")
    return "\n".join(lines)


def _progress_facts_text(
    project_name: str,
    prog: ProgressOut,
    delay_count: int,
    style: StyleMemory,
) -> str:
    return (
        f"프로젝트: {project_name}\n"
        f"Data Date: {format_date(prog.data_date, style.date_format)}\n"
        f"계획 공정률: {prog.plan_now:.{style.number_precision}f}%\n"
        f"실적 공정률: {prog.actual_now:.{style.number_precision}f}%\n"
        f"공정 차이: {prog.gap:+.{style.number_precision}f}%p\n"
        f"SPI: {f'{prog.spi:.2f}' if prog.spi is not None else '미산출'}\n"
        f"현재 예상 준공: {format_date(prog.finish.current, style.date_format)} "
        f"(Plan 대비 {prog.finish.delta if prog.finish.delta is not None else '미정'}일)\n"
        f"액티비티: 전체 {prog.counts.total}, 완료 {prog.counts.done}, 진행 {prog.counts.in_progress}, 계획보다 늦음 {prog.counts.late}\n"
        f"기록된 지연 사건 수: {delay_count}건\n"
    )


_NO_MARKUP = "- 제목 줄을 다시 쓰지 않는다. 마크다운 기호를 쓰지 않는다(**, # 등).\n"


def _tidy(text: str, heading: str) -> str:
    """모델 답 뒷손질: 첫 줄이 절 제목과 같으면(앞뒤 **·#·「」 무시) 빼고, 남은 ** 를 지운다."""
    def bare(s: str) -> str:
        return s.strip().strip("*#「」『』[]:： ").strip()

    lines = text.strip().splitlines()
    if lines and bare(lines[0]) == bare(heading):
        lines = lines[1:]
    return "\n".join(lines).replace("**", "").strip()


async def _draft_prose_with_llm(
    session: Session,
    fallback_text: str,
    project_name: str,
    cadence: Cadence,
    period_label: str,
    prog: ProgressOut,
    delay_events: list[dict],
    section: TemplateSection,
    style: StyleMemory,
    extra_note: str,
) -> tuple[str, bool]:
    """(문단, 자동 문안인가). 모델 글을 받지 못하면 코드가 만든 문안과 참을 돌려준다(화면이 그 사실을 알린다)."""
    if fake.enabled():
        return fallback_text, True

    rules_txt = "\n".join(f"- {r}" for r in style.learned_rules) or "- 별도 추가 규칙 없음"
    facts = (
        f"주기: {'분기별' if cadence == 'quarterly' else '월간'} ({period_label})\n"
        + _progress_facts_text(project_name, prog, len(delay_events), style)
    )
    prompt = (
        f"다음 검증된 공정 수치만을 사용해 보고서의 「{section.heading}」 항목 문단을 3~5문장으로 작성하라.\n"
        f"- 절대 위에 없는 숫자나 날짜를 만들어내지 마라.\n"
        f"- 말투: {style.tone}\n"
        f"- 날짜 형식: {style.date_format}\n"
        f"- 섹션 지침: {section.section_prompt or '핵심 성과, 지연 위험, 향후 조치 요약'}\n"
        f"- 사용자 기억 규칙:\n{rules_txt}\n"
        f"- 추가 메모: {extra_note or '없음'}\n"
        + _NO_MARKUP
        + f"\n[공정 수치]\n{facts}"
    )
    messages = [
        {"role": "system", "content": "너는 건설·플랜트 PM 보고서 작성 비서다. 제공된 수치만 인용한다."},
        {"role": "user", "content": prompt},
    ]
    try:
        client = LlmClient(session)
        reply = await client.chat("normal", messages, timeout_s=35, max_tokens=4000)
        if reply.finish_reason == "length":
            logger.warning("보고서 서술 LLM 토큰 상한 절단 → 길이를 올려 한 번 더 (heading=%s)", section.heading)
            reply = await client.chat("normal", messages, timeout_s=35, max_tokens=12000)
        if reply.finish_reason == "length":
            logger.warning("보고서 서술 LLM 다시 절단 → 결정론적 문안 폴백 (heading=%s)", section.heading)
            return fallback_text, True
        cleaned = _tidy(reply.text or "", section.heading)
        return (cleaned, False) if cleaned else (fallback_text, True)
    except (LlmNotReady, LlmFailed, ValueError) as exc:
        logger.info("보고서 서술 LLM 생략/폴백(결정론적 문안 사용): %s", type(exc).__name__)
        return fallback_text, True


async def generate_report_blocks(
    session: Session,
    schedule_id: int,
    cadence: Cadence,
    period_label: str,
    sections: list[TemplateSection],
    style: StyleMemory,
    extra_note: str = "",
) -> tuple[str, date, int, list[ReportBlock]]:
    """코드 엔진으로 수치·표·차트를 채우고 서술 항목을 작성한다."""
    rec = get_record(session, schedule_id)
    prog = progress_service.progress(session, schedule_id, "month")

    delay_events: list[dict] = []
    try:
        delay_rep = delays_store.report(session, schedule_id)
        delay_events = delay_rep.get("events") or []
    except Exception:  # noqa: BLE001
        delay_events = []

    scen_rows = scenarios_store.listed(session, schedule_id, ("open", "submitted", "applied"))
    # 이번 차례의 안만: 지금 버전 기준 안 + 마지막으로 반영된 안과 기준 버전이 같은 안(옛 실행의 열린 안은 뺀다).
    keep = {prog.version} | {next((s.base_version for s in scen_rows if s.status == "applied"), prog.version)}
    scen_rows = [s for s in scen_rows if s.base_version in keep]
    # delays.report() 가 refresh 를 수행했을 수 있으므로 LLM 호출 전에 쓰기를 마친다.
    session.commit()

    p = style.number_precision
    dfmt = style.date_format
    blocks: list[ReportBlock] = []

    for sec in sections:
        binding = sec.data_binding
        if binding == "kpi_summary":
            spi_val = f"{prog.spi:.2f}" if prog.spi is not None else "—"
            delta = prog.finish.delta
            delta_txt = "Plan과 동일" if delta == 0 else (f"Plan +{delta}일" if delta and delta > 0 else (f"Plan {delta}일" if delta else "Plan 없음"))
            metrics = [
                {"label": "계획 공정률", "value": _fmt_pct(prog.plan_now, p), "sub": format_date(prog.data_date, dfmt)},
                {"label": "실적 공정률", "value": _fmt_pct(prog.actual_now, p), "sub": f"{_fmt_signed(prog.gap, p)}%p"},
                {"label": "일정 수행 지수(SPI)", "value": spi_val, "sub": "1.00 이상 계획대로"},
                {"label": "예상 준공일", "value": format_date(prog.finish.current, dfmt), "sub": delta_txt},
                {"label": "완료 / 전체 작업", "value": f"{prog.counts.done} / {prog.counts.total}", "sub": f"진행 {prog.counts.in_progress} · 지연 {prog.counts.late}"},
            ]
            blocks.append(ReportBlock(id=sec.id, heading=sec.heading, block_kind="kpi", data_binding=binding, metrics=metrics))
        elif binding == "wbs_table":
            std_cols = ["WBS", "가중치", "계획(%)", "실적(%)", "차이(%p)"]
            cols, picks = _fit_columns(binding, sec.table_columns, std_cols)
            rows = []
            for r in prog.wbs:
                std_row: list[object] = [
                    f"{r.code} {r.name}",
                    f"{r.weight * 100:.1f}%",
                    f"{r.plan:.{p}f}",
                    f"{r.actual:.{p}f}",
                    _fmt_signed(r.diff, p),
                ]
                rows.append(_pick(std_row, picks))
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="table",
                    data_binding=binding,
                    table={"columns": cols, "rows": rows},
                )
            )
        elif binding == "milestone_table":
            std_cols = ["마일스톤", "Plan", "실적·예측", "차이(일)", "상태"]
            cols, picks = _fit_columns(binding, sec.table_columns, std_cols)
            rows = []
            for m in prog.milestones:
                std_row = [
                    m.name,
                    format_date(m.plan, dfmt),
                    format_date(m.actual_or_forecast, dfmt),
                    "—" if m.delta is None else f"{m.delta:+d}",
                    m.status,
                ]
                rows.append(_pick(std_row, picks))
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="table",
                    data_binding=binding,
                    table={"columns": cols, "rows": rows},
                )
            )
        elif binding == "delay_table":
            std_cols = ["사건", "책임", "준공 영향", "상태·대책"]
            cols, picks = _fit_columns(binding, sec.table_columns, std_cols)
            rows = []
            for ev in delay_events:
                impact = ev.get("impact") or {}
                fdelta = impact.get("finish_delta")
                impact_txt = f"+{fdelta}일" if isinstance(fdelta, int) and fdelta > 0 else ("0일" if fdelta == 0 else "분석 전")
                std_row = [
                    f"{ev.get('activity_name')} — {ev.get('cause')}",
                    _RESP_LABEL.get(str(ev.get("responsibility")), str(ev.get("responsibility"))),
                    impact_txt,
                    f"{_STATUS_LABEL.get(str(ev.get('status')), str(ev.get('status')))} ({ev.get('days')}일 지연)",
                ]
                rows.append(_pick(std_row, picks))
            if not rows and prog.top_delays:
                for td in prog.top_delays:
                    rows.append(
                        _pick(
                            [f"{td.id} {td.name}", "진행 실적", f"+{td.finish_impact}일", f"지연 {td.delay}일 · 여유 {td.tf}일"],
                            picks,
                        )
                    )
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="table",
                    data_binding=binding,
                    text="기록된 지연 사건이 없습니다." if not rows else "",
                    table={"columns": cols, "rows": rows},
                )
            )
        elif binding == "lookahead_3w":
            std_cols = ["일자", "구분", "작업명", "선행·유의사항"]
            cols, picks = _fit_columns(binding, sec.table_columns, std_cols)
            blocked_map = {b.id: b.reason for b in prog.lookahead.blocked}
            events_la: list[tuple[date, list[object]]] = []
            for s in prog.lookahead.starts:
                events_la.append((s.date, [format_date(s.date, dfmt), "착수 예정", f"{s.id} {s.name}", blocked_map.get(s.id, "착수 가능")]))
            for f in prog.lookahead.finishes:
                events_la.append((f.date, [format_date(f.date, dfmt), "완료 예정", f"{f.id} {f.name}", "마감 점검"]))
            events_la.sort(key=lambda x: x[0])
            rows = [_pick(r, picks) for _, r in events_la[:20]]
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="table",
                    data_binding=binding,
                    text="향후 3주 내 착수·종료 예정 작업이 없습니다." if not rows else "",
                    table={"columns": cols, "rows": rows},
                )
            )
        elif binding == "scenario_compare":
            std_cols = ["시나리오", "예상 준공", "준공 차이(만들 때 일정 대비)", "크리티컬 수", "상태"]
            cols, picks = _fit_columns(binding, sec.table_columns, std_cols)
            # 기본 양식의 「준공 차이」도 무엇 대비인지 밝힌다.
            cols = [std_cols[2] if c == "준공 차이" else c for c in cols]
            rows = []
            for sc in scen_rows[:10]:
                sm = sc.summary_json or {}
                f_delta = sm.get("finish_delta")
                delta_str = f"{f_delta:+d}일" if isinstance(f_delta, int) else "—"
                std_row = [
                    sc.name,
                    format_date(sm.get("finish"), dfmt),
                    delta_str,
                    sm.get("critical_count", "—"),
                    _SCEN_STATUS.get(sc.status, sc.status),
                ]
                rows.append(_pick(std_row, picks))
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="table",
                    data_binding=binding,
                    text="생성된 만회 시나리오(만약에 안)가 없습니다." if not rows else "",
                    table={"columns": cols, "rows": rows},
                )
            )
        elif binding == "s_curve_month":
            points = [
                {
                    "date": format_date(pt.date, dfmt),
                    "plan_cum": pt.plan_cum,
                    "actual_cum": pt.actual_cum,
                    "forecast_cum": pt.forecast_cum,
                }
                for pt in prog.curve
            ]
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="chart",
                    data_binding=binding,
                    text=f"Data Date {format_date(prog.data_date, dfmt)} 기준 계획 {_fmt_pct(prog.plan_now, p)} · 실적 {_fmt_pct(prog.actual_now, p)}",
                    chart={"kind": "s_curve", "unit": "month", "points": points},
                )
            )
        elif binding == "spi_trend":
            points = [{"date": format_date(pt.date, dfmt), "spi": pt.spi} for pt in prog.spi_trend]
            latest = points[-1]["spi"] if points else None
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="chart",
                    data_binding=binding,
                    text=f"최근 월별 SPI {latest:.2f}" if latest is not None else "실적 기준 SPI 추이 데이터가 없습니다.",
                    chart={"kind": "spi_trend", "points": points},
                )
            )
        elif binding == "summary_prose":
            fb = _deterministic_summary(rec.name, cadence, period_label, prog, delay_events, style, extra_note)
            prose, auto = await _draft_prose_with_llm(
                session, fb, rec.name, cadence, period_label, prog, delay_events, sec, style, extra_note
            )
            blocks.append(
                ReportBlock(id=sec.id, heading=sec.heading, block_kind="prose", data_binding=binding, text=prose, auto_text=auto)
            )
        else:
            blocks.append(
                ReportBlock(
                    id=sec.id,
                    heading=sec.heading,
                    block_kind="manual",
                    data_binding="manual_input",
                    text="",
                )
            )

    return rec.name, prog.data_date, prog.version, blocks


async def revise_block_text(
    session: Session,
    block: dict,
    instruction: str,
    style: StyleMemory,
    *,
    schedule_id: int | None = None,
) -> str:
    """사용자의 지시에 따라 특정 보고서 문단 블록을 고친다."""
    current_text = str(block.get("text") or "")
    heading = str(block.get("heading") or "")
    if fake.enabled():
        return f"{current_text}\n[반영됨: {instruction}]".strip()

    facts_section = ""
    if schedule_id is not None:
        try:
            rec = get_record(session, schedule_id)
            prog = progress_service.progress(session, schedule_id, "month")
            delay_events = delays_store.listed(session, schedule_id)
            facts_section = (
                "\n\n[프로젝트 공정 수치]\n"
                + _progress_facts_text(rec.name, prog, len(delay_events), style)
            )
        except Exception as exc:  # noqa: BLE001 — 수치 보조 조회 실패 시에도 문단 다듬기는 계속 시도
            logger.warning("보고서 수정 참고 수치 조회 실패(수치 없이 다듬음): %s", type(exc).__name__)

    prompt = (
        f"아래 보고서 항목「{heading}」의 내용을 사용자 요청대로 다듬어라.\n"
        f"- 말투 규칙: {style.tone}\n"
        f"- 기억된 규칙: {', '.join(style.learned_rules) or '없음'}\n"
        + _NO_MARKUP
        + f"- 숫자와 날짜를 임의로 지어내지 말고, 기존 내용 또는 아래 [프로젝트 공정 수치]의 값만 인용하라.{facts_section}\n\n"
        f"[기존 내용]\n{current_text or '(비어 있음)'}\n\n"
        f"[수정 지시]\n{instruction}"
    )
    try:
        reply = await LlmClient(session).chat(
            "normal",
            [
                {"role": "system", "content": "너는 PM 보고서 편집 도우미다. 수정된 본문만 간결히 돌려준다."},
                {"role": "user", "content": prompt},
            ],
            timeout_s=30,
            max_tokens=4000,
        )
    except LlmNotReady:
        logger.info("보고서 수정 LLM 미연결 → 오프라인 지침 반영 폴백")
        return f"{current_text}\n[수정 반영: {instruction}]".strip()
    except (LlmFailed, ValueError) as exc:
        logger.warning("보고서 수정 LLM 실패: %s", type(exc).__name__)
        raise ApiError(502, "llm_revise_failed", "AI 문단 수정에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None
    text = _tidy(reply.text or "", heading)
    if reply.finish_reason == "length" or not text:
        raise ApiError(502, "llm_revise_failed", "AI 문단 수정 응답이 불완전하여 기존 내용을 유지했습니다.")
    return text
