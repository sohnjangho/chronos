"""다시 넣기 상태·다시 시작 API(Task 48 fix 1): GET /api/files/reindex · POST /api/files/reindex(관리자)."""

import httpx
import pytest

from app.files import jobs, vectors
from app.store.tables import LlmAssignment, ReindexJob
from tests.embed_doubles import LARGE, SMALL

URL = "/api/files/reindex"


def _assign(session, conn, model: str) -> None:
    session.merge(LlmAssignment(purpose="embedding", connection_id=conn.id, model=model, routing_strategy=None))
    session.commit()


def test_status_shows_active_assigned_and_latest_job(client, user, session, ready, put):
    assert client.get(URL, headers=user).json() == {"active_model": SMALL, "assigned_model": SMALL, "job": None}
    put("동절기 타설")
    jobs.enqueue_reindex(LARGE)
    _assign(session, ready, LARGE)  # Task 51 이 다시 넣기를 시작하고 배정을 바꾼 상태
    body = client.get(URL, headers=user).json()
    assert (body["active_model"], body["assigned_model"]) == (SMALL, LARGE)  # 진행 중에는 옛 모델로 찾는다
    job = body["job"]
    assert {k: job[k] for k in ("id", "model", "status", "total", "done", "finished_at")} == {
        "id": 1, "model": LARGE, "status": "running", "total": 1, "done": 0, "finished_at": None}
    assert job["started_at"]


async def test_restart_after_a_failed_reindex(client, admin, user, session, ready, put, embedder, monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_S", 0)
    put("동절기 타설")
    await jobs.drain()
    jobs.enqueue_reindex(LARGE)
    _assign(session, ready, LARGE)
    embedder.push(*[httpx.Response(500)] * 4)
    await jobs.drain()
    assert session.get(ReindexJob, 1).status == "failed"

    assert client.post(URL, headers=user).status_code == 403  # 관리자만
    r = client.post(URL, headers=admin)
    assert r.status_code == 202 and r.json() == {"job_id": 2, "total": 1}
    again = client.post(URL, headers=admin)
    assert again.status_code == 409 and again.json()["code"] == "already_running"
    await jobs.drain()
    assert client.get(URL, headers=user).json()["active_model"] == LARGE
    done = client.post(URL, headers=admin)
    assert done.status_code == 409 and done.json()["code"] == "nothing_to_do"  # 배정 = 지금 모델, 마지막 작업 done


@pytest.mark.real_http  # 꺼진 Qdrant 를 흉내 내려 127.0.0.1:1(아무도 듣지 않는 곳)에 실제로 붙어 본다
def test_restart_needs_qdrant(client, admin, session, ready, monkeypatch):
    _assign(session, ready, LARGE)
    monkeypatch.setattr(vectors, "STORE", vectors.Store("http://127.0.0.1:1", "t"))
    down = client.post(URL, headers=admin)
    monkeypatch.setattr(vectors, "STORE", None)
    off = client.post(URL, headers=admin)
    assert (down.status_code, off.status_code) == (503, 503)
    assert down.json()["message"] != off.json()["message"] and session.query(ReindexJob).count() == 0
