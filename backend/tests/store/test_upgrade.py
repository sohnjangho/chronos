"""기존 DB 칸 추가(app.store.upgrade): 모델에 있는데 DB 표에 없는 칸을 더하고, 있던 줄은 그대로 둔다."""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    text,
)

from app.main import app
from app.store.tables import Base
from app.store.upgrade import add_missing_columns

# 앞 작업들이 만든 모양 그대로: llm_calls 에 finish_reason 이 없고, schedule_drafts 에 used_at·schedule_id 가 없다.
OLD_LLM_CALLS = """CREATE TABLE llm_calls (
    id INTEGER NOT NULL, chat_session_id INTEGER, purpose VARCHAR(10) NOT NULL, model VARCHAR(200) NOT NULL,
    requested_model VARCHAR(200) NOT NULL, routing_strategy VARCHAR(10), input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, cost DOUBLE, latency_ms INTEGER NOT NULL, ok BOOLEAN NOT NULL,
    error_code VARCHAR(20), created_at DATETIME NOT NULL, PRIMARY KEY (id))"""
OLD_DRAFTS = """CREATE TABLE schedule_drafts (
    id INTEGER NOT NULL, chat_session_id INTEGER, domain VARCHAR(50) NOT NULL, level VARCHAR(2) NOT NULL,
    schedule_json JSON NOT NULL, conditions_json JSON NOT NULL, report_json JSON NOT NULL,
    assumptions_json JSON NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id))"""
CALL_ROW = (1, 5, "hard", "claude-sonnet-5.5", "liner-claude-router", "quality", 1409, 845, None, 3200, 1, None,
            "2026-11-20 10:00:00")
DRAFT_ROW = (1, 5, "construction", "L3", '{"activities": []}', "[]", '{"violations": []}', "[]",
             "2026-11-20 10:01:00")


def _old_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute(OLD_LLM_CALLS)
        db.execute(OLD_DRAFTS)
        db.execute(f"INSERT INTO llm_calls VALUES ({', '.join('?' * len(CALL_ROW))})", CALL_ROW)
        db.execute(f"INSERT INTO schedule_drafts VALUES ({', '.join('?' * len(DRAFT_ROW))})", DRAFT_ROW)
        db.commit()


def _columns(path: Path, table: str) -> list[str]:
    with closing(sqlite3.connect(path)) as db:
        return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


def _rows(path: Path, sql: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


def test_app_start_adds_missing_columns_and_keeps_rows(tmp_path):
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    _old_db(path)
    with TestClient(app):  # 시작할 때 create_all 뒤에 칸을 더한다
        pass
    assert _columns(path, "llm_calls")[-2:] == ["cost_estimated", "finish_reason"]
    assert _columns(path, "schedule_drafts")[-2:] == ["used_at", "schedule_id"]
    assert _rows(path, "SELECT * FROM llm_calls") == [(*CALL_ROW, None, None)]  # 예전 줄은 비용·추정 표시 모두 NULL 그대로
    assert _rows(path, "SELECT * FROM schedule_drafts") == [(*DRAFT_ROW, None, None)]
    assert _rows(path, "SELECT login_id FROM users") == [("admin",)]  # 없던 표는 create_all 이 만든다


def test_second_run_adds_nothing_and_logs_only_names(tmp_path, caplog):
    path = tmp_path / "old.db"
    _old_db(path)
    engine = create_engine(f"sqlite:///{path}")
    caplog.set_level(logging.INFO, logger="app.store.upgrade")
    added = add_missing_columns(engine, Base.metadata)
    assert added == ["llm_calls.cost_estimated", "llm_calls.finish_reason", "schedule_drafts.used_at",
                     "schedule_drafts.schedule_id"]
    assert [r.args for r in caplog.records] == [
        ("llm_calls", "cost_estimated"), ("llm_calls", "finish_reason"), ("schedule_drafts", "used_at"), ("schedule_drafts", "schedule_id"),
    ]  # 기록에 들어가는 값은 표·칸 이름뿐이다
    caplog.clear()
    assert add_missing_columns(engine, Base.metadata) == [] and caplog.records == []
    assert _rows(path, "SELECT count(*) FROM llm_calls") == [(1,)]
    engine.dispose()


def test_only_safe_columns_are_added_and_the_rest_are_warned(tmp_path, caplog):
    path = tmp_path / "t.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE parent (id INTEGER NOT NULL, PRIMARY KEY (id))")
        db.execute("CREATE TABLE t (id INTEGER NOT NULL, legacy TEXT, PRIMARY KEY (id))")
        db.execute("INSERT INTO t (id, legacy) VALUES (1, 'old')")
        db.commit()
    meta = MetaData()
    Table("parent", meta, Column("id", Integer, primary_key=True))
    Table(
        "t", meta,
        Column("id", Integer, primary_key=True),
        Column("note", String(20)),  # NULL 가능 → 더함(기존 줄은 NULL)
        Column("n", Integer, nullable=False, default=0),  # 값 기본값 → 더함(기존 줄은 0)
        Column("flag", Boolean, nullable=False, default=False),
        Column("label", String(10), nullable=False, server_default="x"),  # DDL 기본값 → 더함
        Column("need", Integer, nullable=False),  # 기본값 없는 NOT NULL → 경고만
        Column("stamp", Integer, nullable=False, default=lambda: 1),  # 함수 기본값 → 경고만
        Column("parent_id", Integer, ForeignKey("parent.id")),  # 외래 키 → 경고만
        Column("code", String(5), unique=True),  # 겹침 금지 → 경고만
        Column("idx", Integer, index=True),  # 색인 → 경고만
    )
    engine = create_engine(f"sqlite:///{path}")
    caplog.set_level(logging.INFO, logger="app.store.upgrade")
    assert add_missing_columns(engine, meta) == ["t.note", "t.n", "t.flag", "t.label"]
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, legacy, note, n, flag, label FROM t")).one()
    assert tuple(row) == (1, "old", None, 0, 0, "x")
    assert {c["name"] for c in inspect(engine).get_columns("t")} == {"id", "legacy", "note", "n", "flag", "label"}
    warned = [r.args for r in caplog.records if r.levelno == logging.WARNING]
    # 더할 수 없는 칸, 그리고 DB 에만 있는 칸(지우지 않는다)
    assert warned == [("t", "need"), ("t", "stamp"), ("t", "parent_id"), ("t", "code"), ("t", "idx"), ("t", "legacy")]
    engine.dispose()


def _table_t(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE t (id INTEGER NOT NULL, legacy TEXT, PRIMARY KEY (id))")
        db.execute("INSERT INTO t (id, legacy) VALUES (1, 'old')")
        db.commit()


def test_only_constant_server_defaults_are_added(tmp_path, caplog):
    """SQLite 는 ADD COLUMN 에 상수가 아닌 기본값(CURRENT_TIMESTAMP·함수)을 거절한다 → 더하지 않고 경고만."""
    path = tmp_path / "t.db"
    _table_t(path)
    meta = MetaData()
    Table(
        "t", meta,
        Column("id", Integer, primary_key=True),
        Column("made", DateTime, server_default=func.now()),  # NULL 가능이어도 상수가 아니면 경고만
        Column("stamp", String(30), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        Column("kind", String(10), nullable=False, server_default="plain"),  # 글 상수 → 더함
        Column("legacy", String(10)),
    )
    engine = create_engine(f"sqlite:///{path}")
    caplog.set_level(logging.INFO, logger="app.store.upgrade")
    assert add_missing_columns(engine, meta) == ["t.kind"]  # 시작을 막지 않는다
    assert _rows(path, "SELECT id, legacy, kind FROM t") == [(1, "old", "plain")]
    warned = [r.args for r in caplog.records if r.levelno == logging.WARNING]
    assert warned == [("t", "made"), ("t", "stamp")]
    engine.dispose()


def test_a_column_sqlite_rejects_is_warned_and_the_rest_still_added(tmp_path, caplog):
    path = tmp_path / "t.db"
    _table_t(path)
    meta = MetaData()
    Table(
        "t", meta,
        Column("id", Integer, primary_key=True),
        Column("LEGACY", String(10)),  # SQLite 칸 이름은 대소문자를 가리지 않는다 → "duplicate column name"
        Column("note", String(20)),
    )
    engine = create_engine(f"sqlite:///{path}")
    caplog.set_level(logging.INFO, logger="app.store.upgrade")
    assert add_missing_columns(engine, meta) == ["t.note"]
    assert _columns(path, "t") == ["id", "legacy", "note"] and _rows(path, "SELECT * FROM t") == [(1, "old", None)]
    warned = [r.args for r in caplog.records if r.levelno == logging.WARNING]
    assert ("t", "LEGACY") in warned and all(len(a) == 2 for a in warned)  # 표·칸 이름만
    engine.dispose()


def test_defaults_with_colons_are_not_bind_parameters(tmp_path):
    path = tmp_path / "t.db"
    _table_t(path)
    meta = MetaData()
    Table(
        "t", meta,
        Column("id", Integer, primary_key=True),
        Column("legacy", String(10)),
        Column("tpl", String(20), nullable=False, server_default="a :name"),
        Column("tpl2", String(20), nullable=False, default="b :other"),
    )
    engine = create_engine(f"sqlite:///{path}")
    assert add_missing_columns(engine, meta) == ["t.tpl", "t.tpl2"]
    assert _rows(path, "SELECT tpl, tpl2 FROM t") == [("a :name", "b :other")]
    engine.dispose()
