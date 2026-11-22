"""작업 공간 및 에이전트·하네스 실행 설정(settings 표: key → value)."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.store.tables import Setting

APPROVAL_MODE = "approval_mode"
DEFAULT_APPROVAL_MODE = "important"  # all | important | auto (app.agent.approval.Mode)
VALID_APPROVAL_MODES = frozenset({"all", "important", "auto"})
DISABLED_TOOLS_KEY = "agent_disabled_tools"

DEFAULT_AGENT_CONFIG: dict[str, Any] = {
    "approval_mode": DEFAULT_APPROVAL_MODE,
    "max_steps": 12,
    "max_check_retries": 5,
    "tool_output_limit": 4000,
    "history_limit": 30,
    "enable_skill_match": True,
    "enable_self_reflection": True,
}

_INT_BOUNDS: dict[str, tuple[str, int, int]] = {
    "max_steps": ("agent_max_steps", 4, 24),
    "max_check_retries": ("agent_max_check_retries", 1, 10),
    "tool_output_limit": ("agent_tool_output_limit", 1000, 16000),
    "history_limit": ("agent_history_limit", 6, 60),
}

_BOOL_KEYS: dict[str, str] = {
    "enable_skill_match": "agent_enable_skill_match",
    "enable_self_reflection": "agent_enable_self_reflection",
}


def _upsert(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def approval_mode(session: Session) -> str:
    """지금 승인 수준. 정한 적이 없으면 important."""
    row = session.get(Setting, APPROVAL_MODE)
    return row.value if row is not None else DEFAULT_APPROVAL_MODE


def set_approval_mode(session: Session, mode: str) -> None:
    """승인 수준을 바꾸고 commit 한다. 값 확인은 부르는 쪽(API 의 요청 모델)이 한다."""
    _upsert(session, APPROVAL_MODE, mode)
    session.commit()


def _read_int(session: Session, key: str, lo: int, hi: int, default: int) -> int:
    row = session.get(Setting, key)
    if row is None:
        return default
    try:
        return max(lo, min(hi, int(row.value)))
    except ValueError:
        return default


def _read_bool(session: Session, key: str, default: bool) -> bool:
    row = session.get(Setting, key)
    if row is None:
        return default
    val = row.value.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def get_agent_config(session: Session) -> dict[str, Any]:
    """에이전트·하네스 실시간 실행 설정을 돌려준다."""
    mode = approval_mode(session)
    out: dict[str, Any] = {
        "approval_mode": mode if mode in VALID_APPROVAL_MODES else DEFAULT_APPROVAL_MODE,
    }
    for field, (db_key, lo, hi) in _INT_BOUNDS.items():
        out[field] = _read_int(session, db_key, lo, hi, DEFAULT_AGENT_CONFIG[field])
    for field, db_key in _BOOL_KEYS.items():
        out[field] = _read_bool(session, db_key, DEFAULT_AGENT_CONFIG[field])
    return out


def set_agent_config(session: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """에이전트·하네스 실행 설정을 저장하고 최신 설정 전체를 돌려준다."""
    if "approval_mode" in patch and patch["approval_mode"] is not None:
        mode = str(patch["approval_mode"])
        if mode in VALID_APPROVAL_MODES:
            _upsert(session, APPROVAL_MODE, mode)
    for field, (db_key, lo, hi) in _INT_BOUNDS.items():
        if field in patch and patch[field] is not None:
            clamped = max(lo, min(hi, int(patch[field])))
            _upsert(session, db_key, str(clamped))
    for field, db_key in _BOOL_KEYS.items():
        if field in patch and patch[field] is not None:
            _upsert(session, db_key, "true" if bool(patch[field]) else "false")
    session.commit()
    return get_agent_config(session)


def get_disabled_tools(session: Session) -> list[str]:
    """비활성화된 에이전트 도구 이름 목록을 돌려준다."""
    row = session.get(Setting, DISABLED_TOOLS_KEY)
    if row is None or not row.value:
        return []
    try:
        parsed = json.loads(row.value)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    seen: list[str] = []
    for item in parsed:
        name = str(item).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def set_tool_enabled(session: Session, name: str, enabled: bool) -> list[str]:
    """도구 활성/비활성 상태를 저장하고 비활성 목록을 돌려준다."""
    disabled = set(get_disabled_tools(session))
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    ordered = sorted(disabled)
    _upsert(session, DISABLED_TOOLS_KEY, json.dumps(ordered, ensure_ascii=False))
    session.commit()
    return ordered
