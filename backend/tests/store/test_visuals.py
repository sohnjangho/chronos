"""보고서용 그림의 표(app.store.visuals): 저장된 버전에서 코드가 만든 열·값, 저장·찾기, 기존 DB 에 visuals 표."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date

import pytest

from app.core.model import Relation, Resource
from app.db import close_db, init_db
from app.store import delays, scenarios, visuals
from app.store.schedules import NotFound, load
from app.store.versions import save_new_version
from app.store.visuals import TableError
from tests.schedules import make, store, task

TODAY = date(2027, 3, 1)


def build(session, kind, sid, version=None):
    return visuals.build(session, kind, sid, version, today=TODAY)


def test_summary_lists_the_critical_path_in_order(session, sid):
    t = build(session, "summary", sid)
    assert (t.kind, t.chart, t.version, t.data_date) == ("summary", "timeline", 1, date(2027, 3, 1))
    assert t.columns == ["작업", "시작", "끝"]
    assert t.rows == [["작업 A", "2027-03-01", "2027-03-03"], ["작업 B", "2027-03-04", "2027-03-05"]]


def test_summary_reads_the_asked_version(session, sid):
    schedule, conditions, _ = load(session, sid)
    longer = replace(schedule, activities=(replace(schedule.activities[0], od=4), schedule.activities[1]))
    save_new_version(session, sid, longer, conditions, by_kind="user", by_name="김하늘", note="A 4일", changes=[],
                     base_version=1)
    assert build(session, "summary", sid).rows[0] == ["작업 A", "2027-03-01", "2027-03-04"]
    old = build(session, "summary", sid, 1)
    assert (old.version, old.rows[0]) == (1, ["작업 A", "2027-03-01", "2027-03-03"])


def test_delay_impact_rows_come_from_the_delay_report(session, sid):
    delays.record(session, schedule_id=sid, activity_id="B", start_date=date(2027, 3, 4), days=2, cause="우천",
                  responsibility="force", daily_cost=None, evidence="", source="chat", created_by="김하늘",
                  before_version=None)
    session.commit()
    t = build(session, "delay_impact", sid)
    assert t.columns == ["작업", "지연(근무일)", "흡수(근무일)", "준공 영향(근무일)", "상태"]
    assert t.rows == [["작업 B", 2, 0, 2, "열림"]]
    assert t.chart == "bars"


def test_delay_impact_without_events(session, sid):
    with pytest.raises(TableError) as e:
        build(session, "delay_impact", sid)
    assert e.value.message == "기록한 지연이 없습니다."


def test_current_only_kinds_refuse_an_old_version(session, sid):
    with pytest.raises(TableError) as e:
        build(session, "delay_impact", sid, 5)
    assert e.value.message == "이 그림은 지금 버전(v1)으로만 그립니다."


def test_scenario_compare_puts_the_current_schedule_first(session, sid):
    schedule, conditions, n = load(session, sid)
    longer = replace(schedule, activities=(replace(schedule.activities[0], od=5), schedule.activities[1]))
    scenarios.create(session, schedule_id=sid, base_version=n, name="A 늘림 안", source="agent", schedule=longer,
                     conditions=conditions, created_by="김하늘")
    session.commit()
    t = build(session, "scenario_compare", sid)
    assert t.columns == ["안", "준공", "크리티컬(개)", "위반(개)"]
    assert t.rows == [["지금 일정", "2027-03-05", 2, 0], ["A 늘림 안", "2027-03-09", 2, 0]]


def test_scenario_compare_without_scenarios(session, sid):
    with pytest.raises(TableError) as e:
        build(session, "scenario_compare", sid)
    assert e.value.message == "비교할 만약에 안이 없습니다."


def test_s_curve_points_are_plan_and_actual(session, sid):
    t = build(session, "s_curve", sid)
    assert (t.columns, t.chart) == (["날짜", "계획 누적(%)", "실적 누적(%)"], "line")
    assert all(len(r) == 3 and date.fromisoformat(r[0]) for r in t.rows)
    assert t.rows[-1][1] == 100 and isinstance(t.rows[-1][1], int)  # 100.0 → 100(글자 그대로 대조)


def test_resource_load_rows(session):
    sid = store(session, make([task("A", 3, resources=("crane",)), task("B", 2, resources=("crane",))],
                              [Relation("A", "B")], [Resource("crane", "타워크레인", "대", 1)]))
    t = build(session, "resource_load", sid)
    assert t.columns == ["자원", "한도", "최고 사용", "최고 사용일", "한도 넘은 날(일)"]
    assert t.rows == [["타워크레인", 1, 1, "2027-03-01", 0]]


def test_resource_load_without_used_resources(session, sid):
    with pytest.raises(TableError) as e:
        build(session, "resource_load", sid)
    assert e.value.message == "쓰는 자원이 없습니다."


def test_missing_schedule(session):
    with pytest.raises(NotFound):
        build(session, "summary", 99)


def test_save_find_and_out(session, sid):
    t = build(session, "summary", sid)
    row = visuals.save(session, schedule_id=sid, table=t, key="k1", html="<html></html>", theme="summary",
                       description="요약", resource_id="viz_1", verified=True, passed=6, total=6, problems=[],
                       external=["https://cdn.example/a.js"], attempts=1, fallback=False, note="", latency_ms=900,
                       created_by="김하늘")
    assert visuals.find_verified(session, sid, "k1").id == row.id
    assert visuals.find_verified(session, sid, "k2") is None
    o = visuals.out(row)
    assert (o["html"], o["passed"], o["total"], o["version"], o["data_date"]) == ("<html></html>", 6, 6, 1, date(2027, 3, 1))
    assert o["rows"] == t.rows and o["columns"] == t.columns and o["chart"] == "timeline"


def test_fallback_rows_are_not_found_and_hide_html(session, sid):
    t = build(session, "summary", sid)
    row = visuals.save(session, schedule_id=sid, table=t, key="k1", html="<html>틀림</html>", theme="", description="",
                       resource_id="", verified=False, passed=5, total=6, problems=["HTML 에 없는 표 값: 작업 B"],
                       external=[], attempts=2, fallback=True, note="Liner 그림 검증 실패 → 기본 그림", latency_ms=None,
                       created_by="김하늘")
    assert visuals.find_verified(session, sid, "k1") is None
    assert visuals.out(row)["html"] is None


def test_existing_db_gets_the_visuals_table(tmp_path):
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE settings (key VARCHAR(100) NOT NULL, value JSON NOT NULL, PRIMARY KEY (key))")
        db.commit()
    init_db()
    close_db()
    with closing(sqlite3.connect(path)) as db:
        assert "visuals" in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
