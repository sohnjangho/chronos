import time

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.main import app
from app.security.tokens import issue_token
from app.store.tables import User
from tests.helpers import auth


def login(client, login_id, password):
    return client.post("/api/auth/login", json={"login_id": login_id, "password": password})


# 계획서의 시험
def test_first_admin_can_login(client):
    r = client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


def test_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"login_id": "admin", "password": "x"})
    assert r.status_code == 401 and r.json()["code"] == "bad_credentials"


def test_user_cannot_list_users(client, user_token):
    assert client.get("/api/auth/users", headers=auth(user_token)).status_code == 403


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_password_is_not_stored_plain(session):
    assert "test-pass" not in session.get(User, 1).password_hash


# 응답 형식과 토큰
def test_login_returns_token_usable_for_me(client):
    body = login(client, "admin", "test-pass").json()
    assert set(body["user"]) == {"id", "name", "role"}
    me = client.get("/api/auth/me", headers=auth(body["token"]))
    assert me.status_code == 200 and me.json() == body["user"]


def test_error_shape(client):
    r = login(client, "nobody", "x")
    assert r.status_code == 401
    assert r.json() == {
        "code": "bad_credentials",
        "message": "아이디 또는 비밀번호가 맞지 않습니다.",
        "detail": None,
    }


def test_invalid_request_shape(client):
    r = client.post("/api/auth/login", json={"login_id": "admin"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid_request"
    assert body["message"] == "요청 형식이 올바르지 않습니다."
    assert body["detail"]


def test_tampered_token_401(client, admin_token):
    r = client.get("/api/auth/me", headers=auth(admin_token[:-2] + "xx"))
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"
    assert r.json()["message"] == "다시 로그인해 주세요."


def test_expired_token_401(client, session, monkeypatch):
    issued_at = int(time.time()) - 12 * 3600 - 1
    with monkeypatch.context() as m:
        m.setattr(TimestampSigner, "get_timestamp", lambda self: issued_at)
        token = issue_token(1)
    r = client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


# 계정 관리(관리자만)
def test_user_cannot_create_or_update(client, user):
    new = {"login_id": "x", "name": "x", "role": "user", "password": "pw"}
    r = client.post("/api/auth/users", headers=user, json=new)
    assert r.status_code == 403 and r.json()["code"] == "admin_only"
    r = client.patch("/api/auth/users/1", headers=user, json={"name": "x"})
    assert r.status_code == 403 and r.json()["code"] == "admin_only"


def test_admin_creates_user_who_can_login(client, admin):
    new = {"login_id": "kim", "name": "김공정", "role": "user", "password": "kim-pass"}
    r = client.post("/api/auth/users", headers=admin, json=new)
    assert r.status_code == 201
    assert r.json()["name"] == "김공정" and r.json()["role"] == "user"
    assert login(client, "kim", "kim-pass").json()["user"]["role"] == "user"
    ids = [u["login_id"] for u in client.get("/api/auth/users", headers=admin).json()]
    assert ids == ["admin", "kim"]


def test_duplicate_login_id_409(client, admin):
    dup = {"login_id": "admin", "name": "또", "role": "user", "password": "pw"}
    r = client.post("/api/auth/users", headers=admin, json=dup)
    assert r.status_code == 409
    assert r.json()["code"] == "login_id_taken"
    assert r.json()["message"] == "이미 있는 아이디입니다."


def test_admin_updates_user(client, admin, user):
    me = client.get("/api/auth/me", headers=user).json()
    patch = {"name": "박공정", "role": "admin", "password": "new-pass"}
    r = client.patch(f"/api/auth/users/{me['id']}", headers=admin, json=patch)
    assert r.status_code == 200
    assert r.json()["name"] == "박공정" and r.json()["role"] == "admin"
    assert login(client, "user1", "user-pass").status_code == 401
    assert login(client, "user1", "new-pass").json()["user"]["role"] == "admin"


def test_cannot_remove_last_admin(client, admin):
    r = client.patch("/api/auth/users/1", headers=admin, json={"role": "user"})
    assert r.status_code == 422
    assert r.json()["code"] == "last_admin"
    assert r.json()["message"] == "관리자가 한 명은 있어야 합니다."


def test_update_unknown_user_404(client, admin):
    r = client.patch("/api/auth/users/999", headers=admin, json={"name": "x"})
    assert r.status_code == 404


def test_restart_keeps_existing_admin():
    with TestClient(app) as first:
        token = login(first, "admin", "test-pass").json()["token"]
        first.patch("/api/auth/users/1", headers=auth(token), json={"password": "changed"})
    with TestClient(app) as again:
        assert login(again, "admin", "test-pass").status_code == 401
        assert login(again, "admin", "changed").status_code == 200


def test_too_long_password_is_rejected_not_500(client, admin):
    assert login(client, "admin", "가" * 30).status_code == 401
    new = {"login_id": "kim", "name": "김", "role": "user", "password": "가" * 30}
    r = client.post("/api/auth/users", headers=admin, json=new)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_me_patch_updates_own_name_and_password(client, user):
    r = client.patch("/api/auth/me", headers=user, json={"name": "김내정보", "password": "my-new-pass"})
    assert r.status_code == 200
    assert r.json()["name"] == "김내정보" and r.json()["role"] == "user"
    assert login(client, "user1", "user-pass").status_code == 401
    assert login(client, "user1", "my-new-pass").json()["user"]["name"] == "김내정보"
    # role 같은 정의되지 않은 필드는 거부한다.
    bad = client.patch("/api/auth/me", headers=user, json={"role": "admin"})
    assert bad.status_code == 422


def test_admin_creates_field_user_and_last_admin_cannot_demote_to_field(client, admin):
    new = {"login_id": "site1", "name": "박현장", "role": "field", "password": "field-pass"}
    r = client.post("/api/auth/users", headers=admin, json=new)
    assert r.status_code == 201 and r.json()["role"] == "field"
    assert login(client, "site1", "field-pass").json()["user"]["role"] == "field"
    demote = client.patch("/api/auth/users/1", headers=admin, json={"role": "field"})
    assert demote.status_code == 422 and demote.json()["code"] == "last_admin"


def test_public_signup_requires_admin_approval_before_login(client, admin):
    bad_role = client.post(
        "/api/auth/signup",
        json={
            "login_id": "newadmin",
            "password": "pw-1234",
            "name": "시도",
            "role": "admin",
            "email": "newadmin@example.com",
        },
    )
    assert bad_role.status_code == 422

    r = client.post(
        "/api/auth/signup",
        json={
            "login_id": "hong_gildong",
            "password": "pw-1234",
            "name": "홍길동",
            "role": "field",
            "email": "hong@example.com",
            "phone": "010-1234-5678",
            "organization": "크로노스건설",
            "department": "안전·골조반",
            "note": "현장 일일점검 담당",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["role"] == "field"
    uid = body["id"]

    blocked = login(client, "hong_gildong", "pw-1234")
    assert blocked.status_code == 403 and blocked.json()["code"] == "account_pending"

    approved = client.patch(f"/api/auth/users/{uid}", headers=admin, json={"status": "active"})
    assert approved.status_code == 200 and approved.json()["status"] == "active"

    ok = login(client, "hong_gildong", "pw-1234")
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "field"
    tok = ok.json()["token"]
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 200

    disabled = client.patch(f"/api/auth/users/{uid}", headers=admin, json={"status": "disabled"})
    assert disabled.status_code == 200
    assert login(client, "hong_gildong", "pw-1234").status_code == 403
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 401

    assert client.delete("/api/auth/users/1", headers=admin).status_code == 422
    assert client.delete(f"/api/auth/users/{uid}", headers=admin).status_code == 204
    assert all(u["id"] != uid for u in client.get("/api/auth/users", headers=admin).json())
