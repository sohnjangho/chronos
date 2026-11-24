"""관리 포인트 저장·차이(app.points.service, store.points)·버전 저장과 지연 분석 뒤 훅·설정값(store.settings)."""

import logging
from dataclasses import replace
from datetime import date

import pytest

from app.core.cpm import compute
from app.core.model import Relation
from app.core.points import Point, compute_points
from app.points import service
from app.programs.delays import service as delays_service
from app.store import points as points_store
from app.store.schedules import load
from app.store.settings import PointsConfig, points_config, sources_for
from app.store.tables import ScheduleVersion, Setting
from app.store.versions import restore, save_new_version
from tests.schedules import make, store, task


def _base():
    """A(3) → B(2) 크리티컬, C(1) 홀로(여유 4 — 포인트 아님)."""
    return make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])


def _save(session, sid, schedule, base: int, **k) -> int:
    return save_new_version(session, sid, schedule, [], by_kind="user", by_name="손장호", note="고침", changes=[],
                            base_version=base, plan_change=False, **k)


def _longer_c(schedule):
    """C 를 4일로 — 여유 4 → 1, 새 포인트."""
    return replace(schedule, activities=tuple(replace(a, od=4) if a.id == "C" else a for a in schedule.activities))


def test_first_version_stores_points_without_diff(session):
    sid = store(session, _base())
    assert service.refresh(session, sid, 1) is None  # 「처음 계산」 — 바뀜이 아니다
    session.commit()
    got = points_store.get(session, sid, 1)
    assert [p.activity_id for p in got] == ["A", "B"]
    s = _base()
    assert got == compute_points(s, compute(s), tf_days=3, window_weeks=3)


def test_get_missing_is_none(session):
    sid = store(session, _base())
    assert points_store.get(session, sid, 1) is None
    assert points_store.get(session, sid, 9) is None


def test_save_hook_stores_points_and_refresh_diffs(session):
    sid = store(session, _base())
    n = _save(session, sid, _longer_c(_base()), 1)
    stored = points_store.get(session, sid, n)
    assert [p.activity_id for p in stored] == ["A", "C", "B"]  # ES 순(A·C 3/1, B 3/4)
    diff = service.refresh(session, sid, n)  # 앞 버전(1)은 저장된 것이 없어도 계산해 견준다
    assert [p.activity_id for p in diff.added] == ["C"]
    assert diff.removed == () and diff.tightened == ()
    assert points_store.get(session, sid, 1) is not None


def test_refresh_reports_tightened_and_removed(session):
    sid = store(session, _base())
    service.refresh(session, sid, 1)
    n2 = _save(session, sid, _longer_c(_base()), 1)  # C 여유 1
    c5 = replace(_base(), activities=tuple(replace(a, od=5) if a.id == "C" else a for a in _base().activities))
    n3 = _save(session, sid, c5, n2)  # C 여유 0(크리티컬), B 는 그대로
    diff = service.refresh(session, sid, n3)
    assert diff.added == () and diff.removed == ()
    assert diff.tightened == (("C", 1, 0),)
    n4 = restore(session, sid, 1, by_name="손장호")  # 되돌리기도 같은 훅
    diff = service.refresh(session, sid, n4)
    assert diff.removed == ("C",)


def test_save_survives_points_failure(session, monkeypatch, caplog):
    sid = store(session, _base())

    def boom(*_a, **_k):
        raise RuntimeError("계산 실패")

    monkeypatch.setattr(service, "compute_points", boom)
    with caplog.at_level(logging.WARNING, logger="app.points.service"):
        n = _save(session, sid, _longer_c(_base()), 1)
    assert n == 2
    session.expire_all()
    assert session.get(ScheduleVersion, (sid, 2)) is not None
    assert load(session, sid)[2] == 2
    assert points_store.get(session, sid, 2) is None
    assert any("관리 포인트" in r.getMessage() for r in caplog.records)


def test_save_without_commit_survives_points_failure(session, monkeypatch):
    sid = store(session, _base())
    monkeypatch.setattr(service, "compute_points", lambda *_a, **_k: 1 / 0)
    n = _save(session, sid, _longer_c(_base()), 1, commit=False)
    session.commit()  # 부른 쪽이 끝내는 트랜잭션은 깨지지 않았다
    session.expire_all()
    assert n == 2 and session.get(ScheduleVersion, (sid, 2)) is not None


def test_save_of_broken_schedule_still_saves(session):
    """저장은 계산을 확인하지 않는다(부르는 쪽 몫) — 계산이 안 되는 일정이어도 포인트 훅이 저장을 막지 않는다."""
    sid = store(session, _base())
    broken = replace(_base(), relations=(Relation("A", "B"), Relation("B", "A")))
    assert _save(session, sid, broken, 1) == 2
    assert points_store.get(session, sid, 2) is None


def test_delay_analysis_refreshes_points(session):
    sid = store(session, _base())
    delays_service.analyze(session, sid)
    assert [p.activity_id for p in points_store.get(session, sid, 1)] == ["A", "B"]


def test_refresh_uses_settings(session):
    sid = store(session, _base())
    session.add(Setting(key="points_tf_days", value="4"))
    session.commit()
    service.refresh(session, sid, 1)
    assert [p.activity_id for p in points_store.get(session, sid, 1)] == ["A", "C", "B"]


# ── 설정값 ────────────────────────────────────────────────────────────


def _set(session, **values) -> None:
    for key, value in values.items():
        session.add(Setting(key=key, value=value))
    session.commit()


def test_points_config_defaults(session):
    cfg = points_config(session)
    assert isinstance(cfg, PointsConfig)
    assert (cfg.tf_days, cfg.window_weeks, cfg.max_new, cfg.forecast_reuse_hours) == (3, 3, 5, 6)
    assert set(cfg.sources["construction"]) == {"weather", "materials", "fx", "business"}
    assert set(cfg.sources["manufacturing"]) == {"materials", "fx", "business"}


def test_points_config_reads_values_in_range(session):
    _set(session, points_tf_days="0", points_window_weeks="8", points_max_new="1", points_forecast_reuse_hours="48")
    cfg = points_config(session)
    assert (cfg.tf_days, cfg.window_weeks, cfg.max_new, cfg.forecast_reuse_hours) == (0, 8, 1, 48)


@pytest.mark.parametrize(
    "values",
    [
        {"points_tf_days": "11", "points_window_weeks": "0", "points_max_new": "11", "points_forecast_reuse_hours": "49"},
        {"points_tf_days": "-1", "points_window_weeks": "9", "points_max_new": "0", "points_forecast_reuse_hours": "0"},
        {"points_tf_days": "abc", "points_window_weeks": "2.5", "points_max_new": "", "points_forecast_reuse_hours": "x"},
    ],
)
def test_points_config_out_of_range_or_malformed_gives_defaults(session, values):
    _set(session, **values)
    cfg = points_config(session)
    assert (cfg.tf_days, cfg.window_weeks, cfg.max_new, cfg.forecast_reuse_hours) == (3, 3, 5, 6)


def test_sources_for_defaults(session):
    assert sources_for(session, "construction") == {"weather", "materials", "fx", "business"}
    assert "weather" not in sources_for(session, "manufacturing")
    assert sources_for(session, "manufacturing") == {"materials", "fx", "business"}
    assert sources_for(session, "general") == {"business"}
    assert sources_for(session, "모르는 분야") == {"business"}


def test_sources_override_per_domain(session):
    _set(session, points_sources='{"construction": ["weather"], "general": [], "it": ["fx", "nope"]}')
    assert sources_for(session, "construction") == {"weather"}
    assert sources_for(session, "general") == set()  # 다 끔
    assert sources_for(session, "it") == {"fx"}  # 모르는 갈래는 뺀다
    assert sources_for(session, "manufacturing") == {"materials", "fx", "business"}  # 적지 않은 분야는 기본값


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"weather"', '{"construction": "weather"}'])
def test_sources_malformed_gives_defaults(session, raw):
    _set(session, points_sources=raw)
    assert sources_for(session, "construction") == {"weather", "materials", "fx", "business"}
    assert sources_for(session, "manufacturing") == {"materials", "fx", "business"}
    assert sources_for(session, "general") == {"business"}


def test_point_type():
    p = Point("A", "기초", True, 0, date(2027, 3, 1), date(2027, 3, 3))
    assert (p.activity_id, p.name, p.critical, p.tf, p.es, p.ef) == ("A", "기초", True, 0, date(2027, 3, 1),
                                                                      date(2027, 3, 3))
