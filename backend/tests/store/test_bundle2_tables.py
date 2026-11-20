"""묶음 2 자료(Task 21): 새 표·칸, 기존 DB 에 칸 더하기, 액티비티 manual_weight 저장."""

import sqlite3
from contextlib import closing
from dataclasses import replace

from sqlalchemy import inspect

from app.db import close_db, init_db
from app.store.schedules import activity_from_json, activity_json, from_json, to_json

NEW_TABLES = {
    "scenarios", "delay_events", "my_rules", "evidence_searches", "evidence_items", "evidence_links", "trace_events",
}

# 계획 1 이 만든 모양 그대로(묶음 2 칸 없음)
OLD_APPROVALS = """CREATE TABLE approvals (
    id INTEGER NOT NULL, schedule_id INTEGER, draft_id INTEGER, kind VARCHAR(10) NOT NULL,
    title VARCHAR(100) NOT NULL, reasons_json JSON NOT NULL, base_version INTEGER NOT NULL,
    summary_json JSON NOT NULL, diff_json JSON NOT NULL, snapshot_json JSON NOT NULL,
    conditions_json JSON NOT NULL, changes_json JSON NOT NULL, status VARCHAR(10) NOT NULL,
    retry BOOLEAN NOT NULL, version INTEGER, restore_to INTEGER, request TEXT NOT NULL,
    chat_session_id INTEGER, requested_by VARCHAR(100) NOT NULL, requested_kind VARCHAR(10) NOT NULL,
    decided_by VARCHAR(100), note TEXT NOT NULL, created_at DATETIME NOT NULL, decided_at DATETIME,
    PRIMARY KEY (id))"""
OLD_SCHEDULES = """CREATE TABLE schedules (
    id INTEGER NOT NULL, name VARCHAR(200) NOT NULL, domain VARCHAR(50) NOT NULL, level VARCHAR(2) NOT NULL,
    current_version INTEGER NOT NULL, created_by VARCHAR(100) NOT NULL, created_at DATETIME NOT NULL,
    PRIMARY KEY (id))"""
APPROVAL_ROW = (1, 1, None, "change", "A 기간 고침", "[]", 1, "{}", "[]", "{}", "[]", "[]", "pending", 0, None,
                None, "", None, "김하늘", "agent", None, "", "2026-11-20 10:00:00", None)
SCHEDULE_ROW = (1, "5층 사무동 신축", "construction", "L3", 1, "김하늘", "2026-11-20 09:00:00")


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


def test_new_tables_and_columns(session):
    insp = inspect(session.get_bind())
    assert NEW_TABLES <= set(insp.get_table_names())
    assert {"link_kind", "link_id", "reset_plan", "rule_json"} <= {c["name"] for c in insp.get_columns("approvals")}
    assert "weight_mode" in {c["name"] for c in insp.get_columns("schedules")}


def test_existing_db_gets_new_columns(tmp_path):
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute(OLD_APPROVALS)
        db.execute(OLD_SCHEDULES)
        db.execute(f"INSERT INTO approvals VALUES ({', '.join('?' * len(APPROVAL_ROW))})", APPROVAL_ROW)
        db.execute(f"INSERT INTO schedules VALUES ({', '.join('?' * len(SCHEDULE_ROW))})", SCHEDULE_ROW)
        db.commit()
    init_db()
    close_db()
    with closing(sqlite3.connect(path)) as db:
        assert _columns(db, "approvals")[-4:] == ["link_kind", "link_id", "reset_plan", "rule_json"]
        assert _columns(db, "schedules")[-1] == "weight_mode"
        assert db.execute("SELECT * FROM approvals").fetchall() == [(*APPROVAL_ROW, None, None, 0, None)]
        assert db.execute("SELECT * FROM schedules").fetchall() == [(*SCHEDULE_ROW, "duration")]
        assert NEW_TABLES <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_manual_weight_roundtrip(sample_schedule):
    s = replace(
        sample_schedule,
        activities=(replace(sample_schedule.activities[0], manual_weight=2.5), sample_schedule.activities[1]),
    )
    assert from_json(to_json(s)) == s
    assert activity_json(s.activities[0])["manual_weight"] == 2.5
    old = {k: v for k, v in activity_json(s.activities[0]).items() if k != "manual_weight"}
    assert activity_from_json(old).manual_weight is None
