"""정보 API 범용 연결 칸: 기존 DB 의 info_connections 에도 시작할 때 더해지고, 있던 줄은 기상청(kma) 그대로다."""

import sqlite3
from contextlib import closing

from sqlalchemy import create_engine

from app.store.tables import Base
from app.store.upgrade import add_missing_columns

# 범용 연결 전 모양 그대로
OLD = """CREATE TABLE info_connections (
    id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, preset VARCHAR(30) NOT NULL, base_url VARCHAR(500) NOT NULL,
    secret_ciphertext TEXT NOT NULL, secret_last4 VARCHAR(4) NOT NULL, status VARCHAR(10) NOT NULL,
    checked_at DATETIME, PRIMARY KEY (id))"""


def test_new_columns_are_added_to_an_old_db_with_defaults(tmp_path):
    path = tmp_path / "old.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute(OLD)
        db.execute("INSERT INTO info_connections VALUES (1, '기상청', 'kma', 'https://apis.data.go.kr/1360000', "
                   "'cipher', 'a1B2', 'ok', NULL)")
        db.commit()
    engine = create_engine(f"sqlite:///{path}")
    added = add_missing_columns(engine, Base.metadata)
    engine.dispose()
    assert {f"info_connections.{c}" for c in ("description", "usage", "key_in", "key_name", "test_path")} <= set(added)
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT preset, description, usage, key_in, key_name, test_path, status "
                         "FROM info_connections").fetchone()
    assert row == ("kma", "", "", "query", "serviceKey", "", "ok")
