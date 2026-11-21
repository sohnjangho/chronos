"""동적 도메인 프로필 합성: 건설·생산 외 모든 분야에 맞춘 DomainPack 을 즉석에서 만든다."""

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from app.agent.generation_steps import strict_object
from app.domains.loader import DomainPack, is_specialty_domain, load, resolve_pack
from app.harness.conditions import Condition
from app.llm.client import LlmClient, LlmFailed, LlmNotReady

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent / "prompts" / "domain_profile.md"
_RES_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_STR = {"type": "string"}
_SUBPHASE = strict_object({"code": _STR, "name": _STR})
_PHASE = strict_object({"code": _STR, "name": _STR, "subphases": {"type": "array", "items": _SUBPHASE}})
_KEY_RES = strict_object({"id": _STR, "name": _STR, "unit": _STR})
_ASSUMP = strict_object({"label": _STR, "value": _STR, "note": _STR})

SYNTH_SCHEMA = strict_object(
    {
        "domain_name": _STR,
        "days_per_week": {"type": "integer"},
        "deadline_label": _STR,
        "start_term": _STR,
        "activity_term": _STR,
        "resource_term": _STR,
        "rules": {"type": "array", "items": _STR},
        "key_resources": {"type": "array", "items": _KEY_RES},
        "wbs_phases": {"type": "array", "items": _PHASE},
        "assumption_defaults": {"type": "array", "items": _ASSUMP},
    }
)


def _user_message(
    domain: str, request: str, facts: Sequence[dict], assumptions: Sequence[dict], conditions: Sequence[Condition]
) -> str:
    lines = [f"분야 id: {domain}", f"요청: {request}", "알고 있는 것:"]
    lines += [f"- {f.get('label', '')}: {f.get('value', '')}" for f in facts] or ["- (없음)"]
    lines.append("가정한 것:")
    lines += [f"- {a.get('label', '')}: {a.get('value', '')}" for a in assumptions] or ["- (없음)"]
    lines.append("입력 조건:")
    lines += [f"- [{c.kind}] {c.text} ({c.params})" for c in conditions if c.layer == "input"] or ["- (없음)"]
    return "\n".join(lines)


def _build_pack(base: DomainPack, parsed: dict, conditions: Sequence[Condition]) -> DomainPack:
    domain_name = str(parsed.get("domain_name") or "").strip() or base.name
    days_raw = parsed.get("days_per_week", base.default_calendar.days_per_week)
    try:
        days = max(5, min(7, int(days_raw)))
    except (TypeError, ValueError):
        days = base.default_calendar.days_per_week

    terms = dict(base.terms)
    terms["start"] = str(parsed.get("start_term") or "").strip() or base.terms["start"]
    terms["deadline"] = str(parsed.get("deadline_label") or "").strip() or base.terms["deadline"]
    terms["activity"] = str(parsed.get("activity_term") or "").strip() or base.terms["activity"]
    terms["resource"] = str(parsed.get("resource_term") or "").strip() or base.terms["resource"]

    rules = []
    for idx, text in enumerate(parsed.get("rules") or (), start=1):
        cleaned = str(text).strip()
        if cleaned:
            rules.append(
                {
                    "id": f"dyn.{idx}",
                    "layer": "domain",
                    "kind": "text_only",
                    "params": {},
                    "text": cleaned[:200],
                    "source": "분야 규칙",
                    "enabled": True,
                }
            )

    key_resources: list[dict] = []
    seen_res: set[str] = set()
    for item in parsed.get("key_resources") or ():
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        unit = str(item.get("unit") or "").strip() or "단위"
        if _RES_ID_RE.fullmatch(rid) and name and rid not in seen_res:
            seen_res.add(rid)
            key_resources.append({"id": rid, "name": name[:60], "unit": unit[:20], "tags": []})

    for c in conditions:
        if c.kind == "resource_cap" and c.enabled:
            rid = str(c.params.get("resource_id") or "").strip()
            if _RES_ID_RE.fullmatch(rid) and rid not in seen_res:
                seen_res.add(rid)
                key_resources.append({"id": rid, "name": c.text[:60] or rid, "unit": "단위", "tags": []})

    wbs_nodes: list[dict] = []
    seen_codes: set[str] = set()
    for p_idx, phase in enumerate(parsed.get("wbs_phases") or (), start=1):
        if not isinstance(phase, dict):
            continue
        p_code = str(phase.get("code") or p_idx).strip()
        p_name = str(phase.get("name") or "").strip()
        if not p_code or not p_name or p_code in seen_codes:
            continue
        seen_codes.add(p_code)
        wbs_nodes.append({"code": p_code, "name": p_name[:80], "parent": None})
        for s_idx, sub in enumerate(phase.get("subphases") or (), start=1):
            if not isinstance(sub, dict):
                continue
            s_code = str(sub.get("code") or f"{p_code}.{s_idx}").strip()
            s_name = str(sub.get("name") or "").strip()
            if s_code and s_name and s_code not in seen_codes:
                seen_codes.add(s_code)
                wbs_nodes.append({"code": s_code, "name": s_name[:80], "parent": p_code})

    defaults: list[dict] = []
    for idx, item in enumerate(parsed.get("assumption_defaults") or (), start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        val = str(item.get("value") or "").strip()
        note = str(item.get("note") or "").strip()
        if label and val:
            defaults.append({"key": f"dyn_{idx}", "label": label[:80], "value": val[:120], "note": note[:200]})

    payload = {
        "id": base.id,
        "name": domain_name[:60],
        "terms": terms,
        "default_calendar": {"days_per_week": days, "holidays": "KR"},
        "display": {
            "gantt_group_by": "wbs",
            "deadline_label": terms["deadline"][:40],
            "extra_columns": ["resources"] if key_resources else [],
        },
        "rules": rules,
        "key_resources": key_resources,
        "activity_types": [],
        "wbs_template": wbs_nodes or [n.model_dump() for n in base.wbs_template],
        "assumption_defaults": defaults or [d.model_dump() for d in base.assumption_defaults],
    }
    return DomainPack.model_validate(payload)


async def synthesize_pack(
    llm: LlmClient,
    domain: str,
    request: str,
    facts: Sequence[dict] = (),
    assumptions: Sequence[dict] = (),
    conditions: Sequence[Condition] = (),
    chat_session_id: int | None = None,
) -> DomainPack:
    """전문 팩이 있으면 그대로, 없으면 요청에 맞는 동적 분야 프로필을 light 모델로 합성해 돌려준다(실패 시 범용 기본)."""
    if is_specialty_domain(domain):
        return load(domain)
    base = resolve_pack(domain)
    system = _PROMPT_FILE.read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _user_message(domain, request, facts, assumptions, conditions)},
    ]
    try:
        reply = await llm.chat("light", messages, json_schema=SYNTH_SCHEMA, timeout_s=60, chat_session_id=chat_session_id)
        if not isinstance(reply.parsed, dict):
            return base
        return _build_pack(base, reply.parsed, conditions)
    except (LlmNotReady, LlmFailed, ValidationError, TypeError, ValueError) as exc:
        logger.warning("동적 도메인 프로필 합성 폴백: domain=%s (%s)", domain, type(exc).__name__)
        return base
