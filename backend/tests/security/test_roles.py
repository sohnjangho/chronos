"""역할(F4): 현장 관리자(field)는 일정을 고치거나 승인·거부할 수 없다(403). 사용자(user)는 그대로 승인할 수 있다."""

import pytest
from sqlalchemy import select

from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import FieldItem, User
from tests.helpers import auth

FIELD_ONLY = "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def _approval(client, headers, session, sid) -> int:
    """현장 체크인 회신을 반영해 승인 대기 건 하나를 만든다(현장 관리자도 할 수 있는 일)."""
    client.get(f"/api/schedules/{sid}/field", headers=headers)
    item = session.scalars(select(FieldItem).where(FieldItem.kind == "checkin", FieldItem.status == "pending")).first()
    r = client.post(
        f"/api/schedules/{sid}/field/{item.id}/respond",
        json={"response_choice": "on_track", "reported_progress": 50, "reported_rd": 1, "response_note": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/schedules/{sid}/field/{item.id}/apply", headers=headers)
    assert r.status_code == 200, r.json()
    return next(i for i in r.json()["items"] if i["id"] == item.id)["approval_id"]


WRITES = [
    ("POST", "/api/schedules", {"name": "새 현장"}),
    ("PATCH", "/api/schedules/{sid}", {"data_date": "2027-03-02", "base_version": 1}),
    ("PATCH", "/api/schedules/{sid}/activities/A", {"name": "작업 A2", "base_version": 1}),
    ("POST", "/api/schedules/{sid}/activities", {"name": "작업 C", "kind": "task", "wbs": "1", "od": 1, "base_version": 1}),
    ("DELETE", "/api/schedules/{sid}/activities/B?base_version=1", None),
    ("PUT", "/api/schedules/{sid}/activities/B/predecessors", {"items": [], "base_version": 1}),
    ("POST", "/api/schedules/{sid}/versions/1/restore", {"base_version": 1}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES, ids=[f"{m} {p}" for m, p, _ in WRITES])
def test_field_role_cannot_edit_schedules(client, field_user, sid, method, path, body):
    r = client.request(method, path.format(sid=sid), json=body, headers=field_user)

    assert r.status_code == 403, r.json()
    assert (r.json()["code"], r.json()["message"]) == ("field_read_only", FIELD_ONLY)


def test_field_role_still_reads_schedules(client, field_user, sid):
    assert client.get(f"/api/schedules/{sid}", headers=field_user).status_code == 200


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_field_role_cannot_decide_approvals_but_can_raise_them(client, field_user, session, sid, decision):
    approval_id = _approval(client, field_user, session, sid)

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": decision}, headers=field_user)

    assert r.status_code == 403, r.json()
    assert (r.json()["code"], r.json()["message"]) == ("field_read_only", FIELD_ONLY)


def test_user_role_may_still_approve(client, user, session, sid):
    approval_id = _approval(client, user, session, sid)

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=user)

    assert r.status_code == 200, r.json()
