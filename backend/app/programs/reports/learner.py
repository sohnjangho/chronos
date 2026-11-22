"""업로드된 보고서 양식 파일에서 목차·항목·표 열·자료 연결·말투·표기 규칙을 학습한다."""

import base64
import logging
import re

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.files import kinds
from app.llm import fake
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.programs.reports.schemas import (
    BlockKind,
    Cadence,
    DataBinding,
    StyleMemory,
    TemplateSection,
)
from app.programs.reports.templates_builtin import builtin_template
from app.store import files as files_store
from app.store.schedules import NotFound as StoreNotFound

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(
    r"^\s*(?:(?:#{1,3})\s+|(?:\d{1,2}|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])[\.\)]\s+|\(\d{1,2}\)\s+|\[)([^\]]+?)(?:\])?\s*$"
)
_PIPE_LINE_RE = re.compile(r"\|")

_VALID_BLOCK_KINDS: set[str] = {"prose", "kpi", "table", "chart", "manual"}
_VALID_BINDINGS: set[str] = {
    "summary_prose",
    "kpi_summary",
    "wbs_table",
    "milestone_table",
    "s_curve_month",
    "spi_trend",
    "delay_table",
    "lookahead_3w",
    "scenario_compare",
    "manual_input",
}

LEARN_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "suggested_name": {"type": "string"},
        "suggested_cadence": {"type": "string", "enum": ["monthly", "quarterly"]},
        "analysis_summary": {"type": "string"},
        "tone": {"type": "string"},
        "date_format": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "block_kind": {"type": "string", "enum": sorted(_VALID_BLOCK_KINDS)},
                    "data_binding": {"type": "string", "enum": sorted(_VALID_BINDINGS)},
                    "table_columns": {"type": "array", "items": {"type": "string"}},
                    "section_prompt": {"type": "string"},
                },
                "required": ["heading", "block_kind", "data_binding", "table_columns", "section_prompt"],
            },
        },
        "learned_rules": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "suggested_name",
        "suggested_cadence",
        "analysis_summary",
        "tone",
        "date_format",
        "sections",
        "learned_rules",
    ],
}


def _clean_stem(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].strip() if "." in filename else filename.strip()
    return stem[:80] or "사용자 보고서 양식"


def _infer_cadence(name: str, text: str, hint: Cadence | None) -> Cadence:
    if hint in ("monthly", "quarterly"):
        return hint
    probe = f"{name}\n{text[:800]}".lower()
    if any(tok in probe for tok in ("분기", "quarterly", "q1", "q2", "q3", "q4", "1분기", "2분기", "3분기", "4분기")):
        return "quarterly"
    return "monthly"


def _infer_binding(heading: str, has_table: bool) -> tuple[BlockKind, DataBinding]:
    h = heading.lower().replace(" ", "")
    if any(k in h for k in ("s-커브", "s커브", "scurve", "누적곡선", "누적그래프")):
        return "chart", "s_curve_month"
    if any(k in h for k in ("spi", "수행지수", "효율추이")):
        return "chart", "spi_trend"
    if any(k in h for k in ("요약", "총평", "개요", "경영요약", "종합의견", "summary", "executive")):
        return "prose", "summary_prose"
    if any(k in h for k in ("핵심지표", "핵심성과", "kpi", "주요지표", "공정지표")):
        return "kpi", "kpi_summary"
    if any(k in h for k in ("시나리오", "만약에", "단축안", "비교안", "대안")):
        return "table", "scenario_compare"
    if any(k in h for k in ("지연", "리스크", "위험", "만회", "이슈", "문제점", "delay", "risk")):
        return "table", "delay_table"
    if any(k in h for k in ("마일스톤", "주요이정표", "준공전망", "milestone")):
        return "table", "milestone_table"
    if any(k in h for k in ("익월", "차월", "차분기", "다음", "추진계획", "주요예정", "예정작업", "lookahead")):
        return "table", "lookahead_3w"
    if any(k in h for k in ("wbs", "공종", "공정률", "진도", "진척", "실적현황", "세부일정")):
        return "table", "wbs_table"
    if has_table:
        return "table", "wbs_table"
    return "manual", "manual_input"


def _detect_tone(text: str) -> str:
    formal = len(re.findall(r"(?:습니다|입니다|됩니다|하겠습니다|바랍니다)[.\s\n]", text))
    bullet = len(re.findall(r"(?:함|됨|임|완료|예정|필요|검토)[.\s\n]", text))
    if bullet > formal and bullet >= 2:
        return "개조식 (~함 · ~완료)"
    return "~습니다 (간결한 보고서 체)"


def _detect_date_format(text: str) -> str:
    if re.search(r"\b20\d{2}\.\d{1,2}\.\d{1,2}\b", text):
        return "YYYY.MM.DD"
    if re.search(r"\b20\d{2}-\d{1,2}-\d{1,2}\b", text):
        return "YYYY-MM-DD"
    if re.search(r"(?<!\d)\d{1,2}\.\d{1,2}(?!\d)", text):
        return "MM.DD"
    return "YYYY.MM.DD"


def _parse_pipe_header(lines: list[str], start_idx: int) -> list[str]:
    for j in range(start_idx, min(start_idx + 5, len(lines))):
        line = lines[j].strip()
        if not line or set(line) <= set("|-: "):
            continue
        if _PIPE_LINE_RE.search(line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            cleaned = [c for c in cells if c]
            if len(cleaned) >= 2:
                return cleaned[:8]
            break
    return []


def _heuristic_learn(
    text: str,
    file_name: str,
    cadence_hint: Cadence | None,
    name_hint: str | None,
) -> tuple[str, Cadence, list[TemplateSection], StyleMemory, str]:
    cadence = _infer_cadence(file_name, text, cadence_hint)
    suggested_name = (name_hint or "").strip() or f"{_clean_stem(file_name)} ({'분기' if cadence == 'quarterly' else '월간'} 양식)"

    lines = text.splitlines()
    raw_headings: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 70 or "|" in stripped:
            continue
        if _HEADING_RE.match(stripped):
            raw_headings.append((idx, stripped.lstrip("# ").strip()))

    sections: list[TemplateSection] = []
    for i, (line_idx, heading) in enumerate(raw_headings[:12]):
        cols = _parse_pipe_header(lines, line_idx + 1)
        kind, binding = _infer_binding(heading, bool(cols))
        sections.append(
            TemplateSection(
                id=f"s{i + 1}",
                heading=heading[:150],
                block_kind=kind,
                data_binding=binding,
                table_columns=cols if kind == "table" else [],
                section_prompt="",
            )
        )

    if not sections:
        base = builtin_template(cadence)
        sections = base.sections
        summary = f"「{file_name}」에서 표준 {'분기별' if cadence == 'quarterly' else '월간'} 구성을 기반으로 양식 초안을 생성했습니다."
    else:
        connected = sum(1 for s in sections if s.data_binding != "manual_input")
        summary = f"「{file_name}」에서 항목 {len(sections)}개를 추출하고, ChronOS 일정 자료 {connected}개와 자동 연결했습니다."

    style = StyleMemory(
        tone=_detect_tone(text),
        date_format=_detect_date_format(text),
        number_precision=1,
        header_note=f"원본 양식: {file_name}",
        learned_rules=[],
    )
    return suggested_name, cadence, sections, style, summary


def _sanitize_llm_result(
    parsed: dict,
    file_name: str,
    cadence_hint: Cadence | None,
    name_hint: str | None,
    fallback: tuple[str, Cadence, list[TemplateSection], StyleMemory, str],
) -> tuple[str, Cadence, list[TemplateSection], StyleMemory, str]:
    raw_sections = parsed.get("sections") or []
    sections: list[TemplateSection] = []
    for i, item in enumerate(raw_sections[:14]):
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or "").strip()
        if not heading:
            continue
        kind = str(item.get("block_kind") or "manual")
        binding = str(item.get("data_binding") or "manual_input")
        if kind not in _VALID_BLOCK_KINDS:
            kind = "manual"
        if binding not in _VALID_BINDINGS:
            binding = "manual_input"
        cols = [str(c).strip() for c in (item.get("table_columns") or []) if str(c).strip()][:8]
        sections.append(
            TemplateSection(
                id=f"s{i + 1}",
                heading=heading[:150],
                block_kind=kind,  # type: ignore[arg-type]
                data_binding=binding,  # type: ignore[arg-type]
                table_columns=cols if kind == "table" else [],
                section_prompt=str(item.get("section_prompt") or "")[:300],
            )
        )
    if not sections:
        return fallback

    cadence_val = parsed.get("suggested_cadence")
    cadence: Cadence = (
        cadence_hint
        if cadence_hint in ("monthly", "quarterly")
        else (cadence_val if cadence_val in ("monthly", "quarterly") else fallback[1])
    )
    name = (name_hint or "").strip() or str(parsed.get("suggested_name") or "").strip() or fallback[0]
    style = StyleMemory(
        tone=str(parsed.get("tone") or "").strip() or fallback[3].tone,
        date_format=str(parsed.get("date_format") or "").strip() or fallback[3].date_format,
        number_precision=1,
        header_note=f"원본 양식: {file_name}",
        learned_rules=[str(r).strip() for r in (parsed.get("learned_rules") or []) if str(r).strip()][:10],
    )
    summary = str(parsed.get("analysis_summary") or "").strip() or fallback[4]
    return name[:150], cadence, sections, style, summary


async def learn_from_file(
    session: Session,
    file_id: int,
    cadence_hint: Cadence | None = None,
    name_hint: str | None = None,
) -> tuple[str, str, Cadence, list[TemplateSection], StyleMemory, str]:
    """파일에서 양식 구조·자료 연결·말투를 학습한다. (file_name, suggested_name, cadence, sections, style, summary)"""
    try:
        row = files_store.get(session, file_id)
    except StoreNotFound:
        raise ApiError(404, "not_found", "양식 파일을 찾을 수 없습니다.") from None
    if row.deleted_at is not None:
        raise ApiError(404, "deleted", "삭제된 파일입니다.")

    chunks = files_store.chunks_of(session, row.id)
    text = "\n".join(c.text for c in chunks)
    fallback = _heuristic_learn(text, row.name, cadence_hint, name_hint)

    if fake.enabled():
        return row.name, *fallback

    system_prompt = (
        "너는 건설·플랜트 공정 보고서 양식 분석기다. 사용자가 올린 기존 월간/분기별 보고서에서 "
        "목차(sections), 각 항목의 형태(block_kind)와 ChronOS 자료 슬롯(data_binding), 표 열 이름(table_columns), "
        "문체(tone), 날짜 표기(date_format), 작성 규칙(learned_rules)을 정확히 추출해 JSON으로 답한다. "
        "연결할 ChronOS 자료가 없는 항목은 block_kind='manual', data_binding='manual_input'으로 둔다."
    )
    user_text = (
        f"파일 이름: {row.name}\n"
        f"희망 주기: {cadence_hint or '자동 판별 (monthly 또는 quarterly)'}\n"
        f"희망 양식 이름: {name_hint or '파일 내용 기반 추천'}\n\n"
        f"본문 발췌:\n{text[:10000]}"
    )

    purpose = "vision" if row.kind == "image" else "normal"
    if row.kind == "image":
        raw_file = files_store.raw_path(row.sha256)
        if raw_file.exists():
            b64 = base64.b64encode(raw_file.read_bytes()).decode("ascii")
            media = kinds.MEDIA_TYPES.get(f".{row.ext}", "image/png")
            user_content: str | list[dict] = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:{media};base64,{b64}"}},
            ]
        else:
            user_content = user_text
    else:
        user_content = user_text

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
    try:
        reply = await LlmClient(session).chat(purpose, messages, json_schema=LEARN_SCHEMA, timeout_s=45)
        if reply.parsed:
            learned = _sanitize_llm_result(reply.parsed, row.name, cadence_hint, name_hint, fallback)
            return row.name, *learned
    except (LlmNotReady, LlmFailed, ValueError, KeyError, TypeError) as exc:
        logger.info("보고서 양식 학습 LLM 생략/폴백(휴리스틱 사용): %s", type(exc).__name__)

    return row.name, *fallback
