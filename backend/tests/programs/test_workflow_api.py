"""워크플로우 API: 실행 기록 목록·단계, 볼 수 있는 사람, 일반 사용자에게는 입출력을 2,000자에서 자름."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.store import chats
from app.store.tables import User, WorkflowRun, WorkflowStep

BIG = json.dumps({"text": "가" * 5000}, ensure_ascii=False)


def _user_id(session, login_id: str) -> int:
    return session.scalars(select(User).where(User.login_id == login_id)).one().id


def _run(session, owner_id: int, *, output: str = '{"ok": true}', title: str = "실행") -> int:
    chat = chats.create_chat(session, user_id=owner_id)
    run = WorkflowRun(chat_session_id=chat.id, title=title, request=title + " 요청", status="done",
                      started_at=datetime(2027, 3, 1, 9, tzinfo=UTC), ended_at=datetime(2027, 3, 1, 9, 1, tzinfo=UTC),
                      tokens=30, cost=0.5)
    session.add(run)
    session.flush()
    session.add(WorkflowStep(run_id=run.id, n=1, tool="schedule.read", program="schedule", why="읽겠습니다",
                             status="done", input_json=BIG, output_json=output, ms=12, model="m", tokens=30, cost=0.5))
    session.commit()
    return run.id


@pytest.fixture
def run_id_with_big_output(session, user) -> int:
    return _run(session, _user_id(session, "user1"), output=BIG)


@pytest.fixture
def admin_run(session) -> int:
    return _run(session, _user_id(session, "admin"), title="관리자 실행")


def test_step_io_truncated_for_user_role(client, user, run_id_with_big_output):
    assert len(client.get(f"/api/workflows/runs/{run_id_with_big_output}", headers=user).json()["steps"][0]["output_json"]) <= 2000


def test_user_gets_the_first_2000_characters_admin_gets_everything(client, user, admin, run_id_with_big_output):
    step = client.get(f"/api/workflows/runs/{run_id_with_big_output}", headers=user).json()["steps"][0]
    assert step["input_json"] == BIG[:2000] and step["output_json"] == BIG[:2000]
    full = client.get(f"/api/workflows/runs/{run_id_with_big_output}", headers=admin).json()["steps"][0]
    assert full["input_json"] == BIG and full["output_json"] == BIG


def test_run_detail_shape(client, admin, admin_run):
    body = client.get(f"/api/workflows/runs/{admin_run}", headers=admin).json()
    assert set(body) == {
        "id", "chat_session_id", "title", "request", "status", "started_at", "ended_at", "tokens", "cost",
        "step_count", "steps",
    }
    assert (body["title"], body["request"], body["status"], body["tokens"], body["cost"]) == (
        "관리자 실행", "관리자 실행 요청", "done", 30, 0.5,
    )
    assert body["started_at"] == "2027-03-01T09:00:00Z" and body["step_count"] == 1
    assert body["steps"][0] == {
        "n": 1, "tool": "schedule.read", "program": "schedule", "why": "읽겠습니다", "status": "done",
        "input_json": BIG, "output_json": '{"ok": true}', "ms": 12, "model": "m", "tokens": 30, "cost": 0.5,
    }


def test_users_see_runs_of_their_own_chats_admin_sees_all(client, admin, user, admin_run, run_id_with_big_output):
    mine = client.get("/api/workflows/runs", headers=user).json()
    assert [r["id"] for r in mine] == [run_id_with_big_output]
    assert set(mine[0]) == {
        "id", "chat_session_id", "title", "status", "started_at", "ended_at", "tokens", "cost", "step_count",
    }
    everything = client.get("/api/workflows/runs", headers=admin).json()
    assert [r["id"] for r in everything] == [run_id_with_big_output, admin_run]  # 새것부터


def test_someone_elses_run_is_404_for_a_user(client, user, admin, admin_run):
    r = client.get(f"/api/workflows/runs/{admin_run}", headers=user)
    assert r.status_code == 404 and r.json()["message"] == "실행 기록을 찾을 수 없습니다."
    assert client.get("/api/workflows/runs/999", headers=admin).status_code == 404


def test_login_is_required(client):
    assert client.get("/api/workflows/runs").status_code == 401
