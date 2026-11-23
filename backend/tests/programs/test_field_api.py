"""현장 허브 API(/api/schedules/{id}/field...): 체크인 반영·사진 판독."""

from sqlalchemy import func, select

from app.store.tables import Approval, DelayEvent


def _count(session, table) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(table))


def _pending_checkin(client, admin, sid, aid="B") -> dict:
    r = client.post(f"/api/schedules/{sid}/field/checkins/dispatch", json={"activity_ids": [aid]}, headers=admin)
    assert r.status_code == 200, r.json()
    return next(i for i in r.json()["items"] if i["kind"] == "checkin" and i["activity_id"] == aid and i["status"] == "pending")


def test_delayed_checkin_raises_only_its_approval_and_no_delay_event(client, admin, session, sid):
    """F2: 「지연 우려」 회신을 반영해도 지연 사건을 따로 만들지 않는다(승인 건 1개만)."""
    item = _pending_checkin(client, admin, sid)
    r = client.post(
        f"/api/schedules/{sid}/field/{item['id']}/respond",
        json={"response_choice": "delayed", "reported_progress": 30, "reported_rd": 6, "response_note": "자재 반입 지연"},
        headers=admin,
    )
    assert r.status_code == 200, r.json()
    approvals_before = _count(session, Approval)

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)

    assert r.status_code == 200, r.json()
    assert _count(session, DelayEvent) == 0
    assert _count(session, Approval) == approvals_before + 1
    applied = next(i for i in r.json()["items"] if i["id"] == item["id"])
    assert applied["status"] == "applied" and applied["approval_id"] is not None
