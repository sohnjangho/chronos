"""개발 콘솔 — 관리 포인트(계획 5 Task 7): 설정 읽기·저장과 실행 추적의 「관리 포인트」 단계.

- 설정: app.store.settings 의 points_config · accel_warn_ratio · set_points_config(범위 검사는 요청 모델과 setter 둘 다).
  분야 표의 줄 = 건설·제조(전문 팩) + 저장한 다른 분야 + 「그 밖의 분야」(OTHER_DOMAIN).
- 단계: point_cards 한 줄(버전 바뀜·가정) = 계산(포인트·들어옴·줄어듦·빠짐) → 겨냥 검색(갈래별) → Search Agent.
  겨냥 검색 수는 그 차이를 적은 때(changed_at)부터 위험 찾기가 끝난 때(찾는 중이면 지금)까지 대화 없이 남은 관리 포인트 줄
  (날씨 = 질의 「관리 포인트 …」, 자재·환율 = mode knowledge, 업체 = 「business: …」)을 시각으로 이은 값이다 — 두 찾기가 겹치면
  양쪽에 든다. 저장된 값을 다시 쓴 것은 호출이 아니라 들지 않는다. Search Agent 는 그 줄의 근거 문장 상태(point_quotes).
- 비용은 Liner 가 알리지 않아 호출 수 × 단가(per_1k, 1,000회당 USD)로 어림한다. 기상청은 Liner 가 아니다(null).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.points import card
from app.programs.devconsole.schemas import (
    PointsAgentOut,
    PointsComputeOut,
    PointsConfigOut,
    PointsDomainOut,
    PointsSearchOut,
    PointsStageOut,
)
from app.store import settings as settings_store
from app.store.evidence import KNOWLEDGE_MODE, WEATHER_MODE
from app.store.tables import EvidenceSearch, ScheduleRecord
from app.store.timeutil import as_utc
from app.store.traces import is_business

PACK_DOMAINS = ("construction", "manufacturing")  # 전문 팩이 있는 분야 — 늘 표에 둔다
DOMAIN_LABELS = {
    "construction": "건설", "manufacturing": "제조·생산", "rnd": "연구개발", "permitting": "인허가", "procurement": "조달",
    "software": "소프트웨어", "marketing": "마케팅", "general": "일반", settings_store.OTHER_DOMAIN: "그 밖의 분야",
}
WEATHER_QUERY_PREFIX = "관리 포인트 "  # app.points.risk 날씨 질의(「관리 포인트 예보 …」·「관리 포인트 기후 …」)
# 갈래 → (보이는 이름, 비용 종류, 1,000회당 USD)
BRANCHES: dict[str, tuple[str, str, float | None]] = {
    "weather": ("날씨 (기상청)", "기상청 — Liner 비용 없음", None),
    "knowledge": ("자재·환율 (Premium Data)", "Search + Premium Data", 2.0),
    "business": ("업체·규제 소식 (MCP search_business·search_legal)", "MCP", 2.0),
}
SEARCH_AGENT = ("Search Agent", 20.0)
RUNS_DEFAULT, RUNS_MAX = 30, 100


# ── 설정 ────────────────────────────────────────────────────────────


def config(session: Session) -> PointsConfigOut:
    cfg = settings_store.points_config(session)
    other = settings_store.OTHER_DOMAIN
    sources = {**cfg.sources}
    sources.setdefault(other, list(settings_store.OTHER_DOMAIN_SOURCES))
    order = [*PACK_DOMAINS, *sorted(d for d in sources if d not in PACK_DOMAINS and d != other), other]
    bounds = {f"points_{f}": b for f, b in settings_store.POINTS_BOUNDS.items()}
    bounds["accel_warn_ratio"] = settings_store._ACCEL_WARN_RATIO_BOUNDS
    return PointsConfigOut(
        points_tf_days=cfg.tf_days, points_window_weeks=cfg.window_weeks, points_max_new=cfg.max_new,
        points_forecast_reuse_hours=cfg.forecast_reuse_hours, accel_warn_ratio=settings_store.accel_warn_ratio(session),
        points_sources={d: sources[d] for d in order},
        domains=[PointsDomainOut(id=d, label=DOMAIN_LABELS.get(d, d)) for d in order], bounds=bounds,
    )


def save(session: Session, patch: dict) -> PointsConfigOut:
    """patch = PointsConfigPatch(points_ 머리 붙은 이름). setter 는 머리 없는 이름을 받는다."""
    names = {"points_sources": "sources", "accel_warn_ratio": "accel_warn_ratio"}
    settings_store.set_points_config(session, {names.get(k, k.removeprefix("points_")): v for k, v in patch.items()})
    return config(session)


# ── 실행 추적 단계 ──────────────────────────────────────────────────


def _finished(row: card.PointCard) -> datetime | None:
    status = card.status_of(row)
    return as_utc(row.updated_at) if status != card.LOOKING else None


def _searches(session: Session, start: datetime, end: datetime) -> list[PointsSearchOut]:
    rows = session.execute(
        select(EvidenceSearch.mode, EvidenceSearch.query, EvidenceSearch.ok).where(
            EvidenceSearch.chat_session_id.is_(None), EvidenceSearch.mode.in_((WEATHER_MODE, KNOWLEDGE_MODE)),
            EvidenceSearch.created_at >= as_utc(start).replace(tzinfo=None),
            EvidenceSearch.created_at <= as_utc(end).replace(tzinfo=None))
    ).all()
    counts = {b: [0, 0] for b in BRANCHES}
    for mode, query, ok in rows:
        if mode == WEATHER_MODE:
            if not query.startswith(WEATHER_QUERY_PREFIX):
                continue
            branch = "weather"
        else:
            branch = "business" if is_business(query) else "knowledge"
        counts[branch][0] += 1
        counts[branch][1] += 0 if ok else 1
    return [PointsSearchOut(branch=b, label=label, calls=counts[b][0], failed=counts[b][1], cost_kind=kind, per_1k=per)
            for b, (label, kind, per) in BRANCHES.items()]


def _agent(session: Session, row: card.PointCard) -> PointsAgentOut:
    states = [s for s in card.quote_states(session, row).values() if s is not None]
    pending = sum(1 for s in states if s["status"] == "pending")
    failed = sum(1 for s in states if s["status"] == "failed")
    return PointsAgentOut(calls=len(states) - pending, failed=failed, pending=pending, cost_kind=SEARCH_AGENT[0],
                          per_1k=SEARCH_AGENT[1])


def stage(session: Session, row: card.PointCard, names: dict[int, str]) -> PointsStageOut:
    data = row.data_json or {}
    changed = as_utc(row.changed_at)
    finished = _finished(row)
    searches = _searches(session, changed, finished or datetime.now(UTC))
    agent = _agent(session, row)
    cost = sum(s.calls * s.per_1k for s in searches if s.per_1k is not None) + agent.calls * agent.per_1k
    return PointsStageOut(
        schedule_id=row.schedule_id, schedule_name=names.get(row.schedule_id, ""), version=row.version,
        what_if=row.what_if, trigger=data.get("trigger") or {}, changed_at=changed, finished_at=finished,
        compute=PointsComputeOut(points=len(row.points_json or []),
                                 new=len(data.get("new", [])) + int(data.get("more", 0)),
                                 tightened=len(data.get("tightened", [])), removed=len(data.get("removed", []))),
        risk_status=card.status_of(row), searches=searches,
        skipped=sum(1 for r in row.risks_json or [] if r.get("status") == "skipped"), search_agent=agent,
        cost=cost / 1000,
    )


def _stages(session: Session, rows: list[card.PointCard]) -> list[PointsStageOut]:
    ids = {r.schedule_id for r in rows}
    names = dict(session.execute(select(ScheduleRecord.id, ScheduleRecord.name).where(ScheduleRecord.id.in_(ids))).all())
    return [stage(session, r, names) for r in rows]


def for_turn(session: Session, start: datetime, end: datetime | None) -> list[PointsStageOut]:
    """턴의 시간(start ~ end, 없으면 지금) 안에 적힌 관리 포인트 차이, 적은 차례."""
    query = select(card.PointCard).where(card.PointCard.changed_at >= start,
                                         card.PointCard.changed_at <= (end or datetime.now(UTC)))
    return _stages(session, list(session.scalars(query.order_by(card.PointCard.changed_at))))


def runs(session: Session, limit: int) -> list[PointsStageOut]:
    """최근 관리 포인트 차이(버전 바뀜·가정), 새것부터 limit 개 — 승인함·화면 단추처럼 대화 턴 밖에서 바뀐 것도."""
    query = select(card.PointCard).where(card.PointCard.changed_at.is_not(None))
    return _stages(session, list(session.scalars(query.order_by(card.PointCard.changed_at.desc()).limit(limit))))
