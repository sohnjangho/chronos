"""계정별 접속 상태·기기 목록·기기 로그아웃(관리자). 기기마다 서버 쪽 기기 세션 줄(user_devices)에 로그인을 묶는다."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, select

from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import devices
from app.store.devices import UserDevice
from app.store.tables import User
from tests.helpers import auth

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/17.4 Mobile/15E148 Safari/604.1")
MAC_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
KEY_A = "devkey-aaaaaaaaaaaaaaaa"
KEY_B = "devkey-bbbbbbbbbbbbbbbb"
T0 = datetime(2026, 11, 24, 5, 12, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    """기기 표가 읽는 지금 시각. clock.now 를 바꾸면 그 순간으로 간다."""

    class Clock:
        now = T0

    c = Clock()
    monkeypatch.setattr(devices, "utcnow", lambda: c.now)
    return c


def _login(client, login_id="admin", password="test-pass", key=KEY_A, kind="desktop", ua=MAC_CHROME):
    body = {"login_id": login_id, "password": password}
    if key is not None:
        body |= {"device_key": key, "kind": kind}
    r = client.post("/api/auth/login", json=body, headers={"User-Agent": ua})
    assert r.status_code == 200, r.text
    return auth(r.json()["token"])


def _user(session, login_id="kim", role="user", password="user-pass"):
    row = User(login_id=login_id, name="김하늘", role=role, password_hash=hash_password(password))
    session.add(row)
    session.commit()
    return row


def _beat(client, headers, key=KEY_A, kind="desktop", ua=MAC_CHROME):
    return client.post("/api/me/presence", json={"device_key": key, "kind": kind}, headers=headers | {"User-Agent": ua})


def _accounts(client, headers):
    r = client.get("/api/admin/accounts/devices", headers=headers)
    assert r.status_code == 200, r.text
    return {a["user_id"]: a for a in r.json()}


# ── UA 를 작은 고정 낱말로 ──
@pytest.mark.parametrize(
    ("ua", "browser", "os"),
    [
        (MAC_CHROME, "Chrome", "macOS"),
        (IPHONE, "Safari", "iOS"),
        (("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
         "Safari/537.36 Edg/131.0.0.0"), "Edge", "Windows"),
        ("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0", "Firefox", "Linux"),
        (("Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
         "Mobile Safari/537.36"), "Chrome", "Android"),
        (("Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 "
         "Mobile/15E148 Safari/604.1"), "Chrome", "iOS"),
        (("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
         "Safari/605.1.15"), "Safari", "macOS"),
        (("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 "
         "Chrome/121.0.0.0 Mobile Safari/537.36"), "기타", "Android"),
        ("curl/8.4.0", "기타", "기타"),
        ("", "기타", "기타"),
    ],
)
def test_user_agent_is_parsed_into_a_small_fixed_vocabulary(ua, browser, os):
    assert devices.parse_user_agent(ua) == (browser, os)


# ── 접속 신호 ──
def test_login_opens_a_device_and_the_heartbeat_updates_last_seen(client, session, clock):
    headers = _login(client)
    row = session.scalars(select(UserDevice)).one()
    assert (row.kind, row.browser, row.os) == ("desktop", "Chrome", "macOS")
    assert row.last_seen_at == T0.replace(tzinfo=None)
    clock.now = T0 + timedelta(minutes=1)
    r = _beat(client, headers)
    assert r.status_code == 200 and r.json()["token"] is None
    session.expire_all()
    assert session.get(UserDevice, row.id).last_seen_at == clock.now.replace(tzinfo=None)
    assert session.scalars(select(UserDevice)).all() == [row]  # 같은 기기는 줄을 더 만들지 않는다


def test_online_only_within_two_minutes_of_the_last_heartbeat(client, admin, session, clock):
    _user(session)
    phone = _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    uid = session.scalar(select(User.id).where(User.login_id == "kim"))
    clock.now = T0 + timedelta(minutes=1, seconds=59)
    got = _accounts(client, admin)[uid]
    assert got["online"] is True
    assert got["devices"][0] | {"id": 0} == {
        "id": 0, "kind": "phone", "browser": "Safari", "os": "iOS", "online": True, "revoked": False,
        "current": False, "created_at": "2026-11-24T05:12:00Z", "last_seen_at": "2026-11-24T05:12:00Z",
        "revoked_at": None,
    }
    clock.now = T0 + timedelta(minutes=2, seconds=1)
    got = _accounts(client, admin)[uid]
    assert got["online"] is False and got["last_seen_at"] == "2026-11-24T05:12:00Z"
    clock.now = T0 + timedelta(minutes=3)
    assert _beat(client, phone, key=KEY_B, kind="phone", ua=IPHONE).status_code == 200
    assert _accounts(client, admin)[uid]["online"] is True


def test_no_ip_address_and_no_raw_user_agent_are_stored(client, session, clock):
    ua = MAC_CHROME + " ProbeMarker/9.9"
    headers = _login(client, ua=ua)
    _beat(client, headers, ua=ua)
    cols = {c["name"] for c in inspect(session.get_bind()).get_columns("user_devices")}
    assert cols == {"id", "user_id", "device_key", "kind", "browser", "os", "created_at", "last_seen_at",
                    "revoked_at", "revoked_by"}
    stored = " ".join(str(getattr(r, c)) for r in session.scalars(select(UserDevice)) for c in cols)
    assert "ProbeMarker" not in stored and "Mozilla" not in stored
    assert "testclient" not in stored and "127.0.0.1" not in stored  # TestClient 의 접속 주소


def test_presence_rejects_a_bad_device_key_or_kind(client, admin):
    assert _beat(client, admin, key="short").status_code == 422
    assert _beat(client, admin, key="bad key with spaces!!").status_code == 422
    assert _beat(client, admin, kind="watch").status_code == 422
    assert client.post("/api/me/presence", json={"device_key": KEY_A, "kind": "phone"}).status_code == 401


def test_a_token_from_before_device_sessions_gets_a_bound_token_from_the_heartbeat(client, admin, session, clock):
    r = _beat(client, admin)  # admin 고정물은 기기 없는 예전 토큰
    assert r.status_code == 200
    bound = auth(r.json()["token"])
    row = session.scalars(select(UserDevice)).one()
    assert _beat(client, bound).json()["token"] is None
    assert len(session.scalars(select(UserDevice)).all()) == 1
    assert client.post(f"/api/admin/devices/{row.id}/logout", json={"confirm_self": True}, headers=bound).status_code == 200
    assert client.get("/api/auth/me", headers=bound).status_code == 401


def test_login_without_a_device_key_is_still_bound_to_a_device_session(client, session, clock):
    headers = _login(client, key=None, ua=IPHONE)
    row = session.scalars(select(UserDevice)).one()
    assert (row.kind, row.browser, row.os) == ("phone", "Safari", "iOS")
    assert client.get("/api/auth/me", headers=headers).status_code == 200


# ── 기기 로그아웃 ──
def test_revoked_device_gets_401_on_its_next_request_and_can_sign_in_again(client, admin, session, clock, caplog):
    caplog.set_level(logging.INFO)
    kim = _user(session)
    phone = _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    laptop = _login(client, "kim", "user-pass", key=KEY_A)
    phone_row = session.scalars(select(UserDevice).where(UserDevice.device_key == KEY_B)).one()
    admin_id = session.scalar(select(User.id).where(User.login_id == "admin"))
    clock.now = T0 + timedelta(minutes=5)
    r = client.post(f"/api/admin/devices/{phone_row.id}/logout", json={}, headers=admin)
    assert r.status_code == 200 and r.json()["revoked"] is True
    session.expire_all()
    row = session.get(UserDevice, phone_row.id)
    assert row.revoked_at == clock.now.replace(tzinfo=None) and row.revoked_by == admin_id
    gone = client.get("/api/auth/me", headers=phone)
    assert gone.status_code == 401 and gone.json()["code"] == "device_logged_out"
    assert _beat(client, phone, key=KEY_B, kind="phone", ua=IPHONE).status_code == 401
    assert client.get("/api/auth/me", headers=laptop).status_code == 200  # 다른 기기는 그대로
    assert any("기기 로그아웃" in m and str(kim.id) in m for m in caplog.messages)
    again = _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    assert client.get("/api/auth/me", headers=again).status_code == 200
    assert session.get(UserDevice, phone_row.id).revoked_at is not None  # 감사 줄은 남는다


def test_revoking_your_own_current_device_needs_a_confirmation(client, session, clock):
    headers = _login(client)
    own = session.scalars(select(UserDevice)).one()
    got = _accounts(client, headers)
    assert got[own.user_id]["devices"][0]["current"] is True
    r = client.post(f"/api/admin/devices/{own.id}/logout", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "own_device"
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    r = client.post(f"/api/admin/devices/{own.id}/logout", json={"confirm_self": True}, headers=headers)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_of_an_unknown_device_is_404(client, admin):
    assert client.post("/api/admin/devices/999/logout", json={}, headers=admin).status_code == 404


# ── 관리자만 ──
def test_admin_routes_are_403_for_user_and_field(client, session, user):
    _user(session, "site1", role="field", password="field-pass")
    field = _login(client, "site1", "field-pass")
    row = session.scalars(select(UserDevice)).one()
    for headers in (user, field):
        assert client.get("/api/admin/accounts/devices", headers=headers).status_code == 403
        assert client.post(f"/api/admin/devices/{row.id}/logout", json={}, headers=headers).status_code == 403
    assert client.get("/api/admin/accounts/devices").status_code == 401
    session.expire_all()
    assert session.get(UserDevice, row.id).revoked_at is None


def test_the_list_never_returns_a_device_key(client, admin, session, clock):
    _user(session)
    _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    _login(client, key=KEY_A)
    r = client.get("/api/admin/accounts/devices", headers=admin)
    assert KEY_A not in r.text and KEY_B not in r.text and "device_key" not in r.text


def test_devices_without_a_heartbeat_for_30_days_are_hidden_but_kept(client, admin, session, clock):
    _user(session)
    _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    uid = session.scalar(select(User.id).where(User.login_id == "kim"))
    clock.now = T0 + timedelta(days=29)
    assert len(_accounts(client, admin)[uid]["devices"]) == 1
    clock.now = T0 + timedelta(days=30, minutes=1)
    assert uid not in _accounts(client, admin)
    assert len(session.scalars(select(UserDevice)).all()) == 1


# ── 개발 콘솔 한 줄 ──
def test_devconsole_health_counts_people_and_devices_online_now(client, admin, session, clock):
    _user(session)
    _login(client, "kim", "user-pass", key=KEY_B, kind="phone", ua=IPHONE)
    _login(client, "kim", "user-pass", key=KEY_A)
    _login(client, key=KEY_A)
    clock.now = T0 + timedelta(minutes=1)
    assert client.get("/api/devconsole/health", headers=admin).json()["presence"] == {"online_users": 2, "online_devices": 3}
    clock.now = T0 + timedelta(minutes=3)
    assert client.get("/api/devconsole/health", headers=admin).json()["presence"] == {"online_users": 0, "online_devices": 0}


def test_a_token_for_another_users_device_is_refused(client, session, clock):
    """기기 줄의 주인과 토큰의 사용자가 다르면(지운 사용자 id 를 다시 쓴 때 등) 받지 않는다."""
    _user(session)
    _login(client, "kim", "user-pass", key=KEY_B)
    row = session.scalars(select(UserDevice)).one()
    admin_id = session.scalar(select(User.id).where(User.login_id == "admin"))
    forged = auth(issue_token(admin_id, row.id))
    assert client.get("/api/auth/me", headers=forged).status_code == 401
