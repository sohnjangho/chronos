"""Task 18 fix round 1 이 store 에 더한 것: 승인 건의 requested_kind 칸, 메모리 일정으로 보기 만들기(view_of)."""

import sqlite3
from contextlib import closing
from datetime import datetime

from sqlalchemy import Column, MetaData, Table, create_engine, insert

from app.core.model import Relation, Resource
from app.harness.assemble import prepare_stored
from app.harness.conditions import Condition
from app.store.schedules import load, run
from app.store.tables import Approval, Base
from app.store.upgrade import add_missing_columns
from app.store.view import plan_of, view_data, view_of
from tests.schedules import make, store, task


def test_an_old_approvals_table_gets_requested_kind_agent(tmp_path):
    path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{path}")
    old = Table("approvals", MetaData(), *(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
                                         for c in Approval.__table__.columns if c.name != "requested_kind"))
    old.create(engine)
    with engine.begin() as conn:
        conn.execute(insert(old).values(
            id=1, kind="change", title="B 기간 4일", reasons_json=[], base_version=1, summary_json={}, diff_json=[],
            snapshot_json={}, conditions_json=[], changes_json=[], status="pending", retry=False, request="",
            requested_by="에이전트", note="", created_at=datetime(2026, 11, 20, 10, 0)))
    assert add_missing_columns(engine, Base.metadata) == ["approvals.requested_kind"]
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT requested_kind FROM approvals").fetchall() == [("agent",)]
    engine.dispose()


def test_view_data_is_view_of_the_stored_schedule(session):
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",)), task("C", 2)],
                    [Relation("A", "C")], [crane])
    two = Condition("i1", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "", "프롬프트").to_dict()
    sid = store(session, schedule, conditions=[two])
    stored, conditions, n = load(session, sid)
    ready = prepare_stored(stored, conditions)
    cpm = run(ready)
    assert view_data(session, sid) == view_of(session, sid, n, stored, ready, cpm, plan_of(session, sid, n, cpm))
