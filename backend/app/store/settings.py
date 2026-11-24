"""작업 공간 및 에이전트·하네스 실행 설정(settings 표: key → value)."""

import json
from dataclasses import dataclass
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


# 사진 사람 판독(PM 11-24): AI 가 못 읽은 사진에 진도를 넣을 수 있는 등급. 기본 관리자만, 넓히면 사용자까지. 현장 관리자는 늘 못 한다.
HUMAN_READ_ROLE = "human_read_role"
DEFAULT_HUMAN_READ_ROLE = "admin"
VALID_HUMAN_READ_ROLES = frozenset({"admin", "user"})


def human_read_role(session: Session) -> str:
    row = session.get(Setting, HUMAN_READ_ROLE)
    return row.value if row is not None and row.value in VALID_HUMAN_READ_ROLES else DEFAULT_HUMAN_READ_ROLE


def set_human_read_role(session: Session, role: str) -> None:
    """바꾸고 commit 한다. 값 확인은 부르는 쪽(API 의 요청 모델)이 한다."""
    _upsert(session, HUMAN_READ_ROLE, role)
    session.commit()


def can_human_read(session: Session, role: str) -> bool:
    """이 등급이 사람 판독(과 다시 찍기 요청)을 할 수 있는가. field 는 늘 False."""
    return role == "admin" or (role == "user" and human_read_role(session) == "user")


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


# ── 관리 포인트(계획 5) ──────────────────────────────────────────────

POINT_SOURCES = ("weather", "materials", "fx", "business")  # 바깥 자료 갈래: 날씨·금속/원자재·환율·업체 소식
POINTS_SOURCES_KEY = "points_sources"
OTHER_DOMAIN = "_other"  # points_sources 안의 「그 밖의 분야」(표에 따로 없는 분야) 열쇠 — 개발 콘솔에서 바꾼다
OTHER_DOMAIN_SOURCES = ("business",)  # 표에 없는 분야(OTHER_DOMAIN 을 저장한 적이 없을 때)
DEFAULT_POINTS_SOURCES: dict[str, list[str]] = {  # PM 결정 11-24: 분야별로 켜고 끈다
    "construction": ["weather", "materials", "fx", "business"],
    "manufacturing": ["materials", "fx", "business"],
}

ACCEL_WARN_RATIO_KEY = "accel_warn_ratio"  # 당김 효과(계획 5 F) — 아래 accel_warn_ratio
_ACCEL_WARN_RATIO_BOUNDS = (0.1, 1.0)

# 필드 → (DB 키, 하한, 상한, 기본값). 범위 밖·숫자 아님은 기본값(에이전트 설정처럼 자르지 않는다).
_POINTS_INT_BOUNDS: dict[str, tuple[str, int, int, int]] = {
    "tf_days": ("points_tf_days", 0, 10, 3),  # k: 크리티컬 직전으로 볼 여유(근무일)
    "window_weeks": ("points_window_weeks", 1, 8, 3),  # w: Data Date 부터 보는 창(달력 주)
    "max_new": ("points_max_new", 1, 10, 5),  # 바깥 위험을 찾을 새 포인트 수
    "forecast_reuse_hours": ("points_forecast_reuse_hours", 1, 48, 6),  # 예보 근거 재사용 시간
}


@dataclass(frozen=True)
class PointsConfig:
    tf_days: int
    window_weeks: int
    max_new: int
    forecast_reuse_hours: int
    sources: dict[str, list[str]]  # 분야 → 켜진 갈래. 표에 없는 분야는 OTHER_DOMAIN_SOURCES


def _read_bounded(session: Session, key: str, lo: int, hi: int, default: int) -> int:
    row = session.get(Setting, key)
    if row is None:
        return default
    try:
        value = int(row.value)
    except ValueError:
        return default
    return value if lo <= value <= hi else default


def _read_sources(session: Session) -> dict[str, list[str]]:
    """기본값 위에 저장한 분야만 덮는다. JSON 이 깨졌거나 dict 가 아니면 기본값, 목록이 아닌 분야는 기본값, 모르는 갈래는 뺀다."""
    out = {d: list(s) for d, s in DEFAULT_POINTS_SOURCES.items()}
    row = session.get(Setting, POINTS_SOURCES_KEY)
    if row is None:
        return out
    try:
        parsed = json.loads(row.value)
    except ValueError:
        return out
    if not isinstance(parsed, dict):
        return out
    for domain, kinds in parsed.items():
        if isinstance(kinds, list):
            out[str(domain)] = [k for k in POINT_SOURCES if k in kinds]
    return out


def points_config(session: Session) -> PointsConfig:
    ints = {f: _read_bounded(session, key, lo, hi, d) for f, (key, lo, hi, d) in _POINTS_INT_BOUNDS.items()}
    return PointsConfig(**ints, sources=_read_sources(session))


def sources_for(session: Session, domain: str) -> set[str]:
    """그 분야에 켜진 바깥 자료 갈래. 표에 없는 분야는 「그 밖의 분야」(OTHER_DOMAIN, 저장한 적 없으면 OTHER_DOMAIN_SOURCES)."""
    sources = _read_sources(session)
    return set(sources.get(domain, sources.get(OTHER_DOMAIN, OTHER_DOMAIN_SOURCES)))


POINTS_BOUNDS: dict[str, tuple[int, int]] = {f: (lo, hi) for f, (_, lo, hi, _) in _POINTS_INT_BOUNDS.items()}


def set_points_config(session: Session, patch: dict[str, Any]) -> None:
    """관리 포인트 설정(tf_days·window_weeks·max_new·forecast_reuse_hours·accel_warn_ratio·sources)을 저장하고 commit.

    읽기와 같은 범위(_POINTS_INT_BOUNDS·_ACCEL_WARN_RATIO_BOUNDS)를 검사해 하나라도 벗어나면 ValueError — 아무것도 적지 않는다
    (읽기처럼 기본값으로 바꾸지 않는다). sources = 분야 → 켜진 갈래(POINT_SOURCES 만, 빈 목록 = 다 끔). 덮어쓴다 — 적지 않은
    건설·제조는 기본값, 적지 않은 그 밖의 분야는 OTHER_DOMAIN_SOURCES.
    """
    writes: list[tuple[str, str]] = []
    for field, (key, lo, hi, _) in _POINTS_INT_BOUNDS.items():
        if patch.get(field) is not None:
            value = patch[field]
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ValueError(field)
            writes.append((key, str(value)))
    if patch.get("accel_warn_ratio") is not None:
        ratio, (lo, hi) = patch["accel_warn_ratio"], _ACCEL_WARN_RATIO_BOUNDS
        if isinstance(ratio, bool) or not isinstance(ratio, int | float) or not lo <= ratio <= hi:
            raise ValueError("accel_warn_ratio")
        writes.append((ACCEL_WARN_RATIO_KEY, str(float(ratio))))
    if patch.get("sources") is not None:
        sources = patch["sources"]
        if not isinstance(sources, dict):
            raise ValueError("sources")
        clean: dict[str, list[str]] = {}
        for domain, kinds in sources.items():
            if not isinstance(domain, str) or not domain or not isinstance(kinds, list | tuple) \
                    or any(k not in POINT_SOURCES for k in kinds):
                raise ValueError("sources")
            clean[domain] = [k for k in POINT_SOURCES if k in kinds]
        writes.append((POINTS_SOURCES_KEY, json.dumps(clean, ensure_ascii=False)))
    for key, value in writes:
        _upsert(session, key, value)
    session.commit()


# ── 당김 효과(계획 5 F) ──────────────────────────────────────────────

DEFAULT_ACCEL_WARN_RATIO = 0.5


def accel_warn_ratio(session: Session) -> float:
    """당긴 일수 가운데 준공에 반영된 비율이 이보다 낮으면 경고한다. 범위(0.1~1.0) 밖·숫자 아님은 기본값 0.5."""
    row = session.get(Setting, ACCEL_WARN_RATIO_KEY)
    if row is None:
        return DEFAULT_ACCEL_WARN_RATIO
    try:
        value = float(row.value)
    except ValueError:
        return DEFAULT_ACCEL_WARN_RATIO
    lo, hi = _ACCEL_WARN_RATIO_BOUNDS
    return value if lo <= value <= hi else DEFAULT_ACCEL_WARN_RATIO
