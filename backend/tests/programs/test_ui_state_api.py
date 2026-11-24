"""열어 둔 창·탭(화면 형태별) — 계정에 붙어 기기 사이를 따라간다. 자기 것만 읽고 쓰며, 모양이 틀리거나 크거나 번호 꼴이 섞이면 422."""

import json
from datetime import UTC, datetime, timedelta

from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.ui_states import UiState
from tests.helpers import auth

DESKTOP = {
    "v": 1,
    "wins": [
        {"program": "gantt", "x": 24, "y": 88, "w": 800, "h": 600, "min": False, "max": False, "params": {"id": "3"}},
        {
            "program": "contacts",
            "x": 60,
            "y": 120,
            "w": 900,
            "h": 640,
            "min": False,
            "max": True,
            "params": {"id": "3", "contact": "12", "tab": "calls"},
        },
    ],
    "deactivated": False,
}
PHONE = {"v": 1, "tab": "contacts", "sub": "schedule-table", "params": {"contact": "12", "tab": "messages"}}
TABLET = {"v": 1, "active": "field"}


def test_requires_login(client):
    assert client.get("/api/me/ui-state").status_code == 401
    assert client.put("/api/me/ui-state/desktop", json=DESKTOP).status_code == 401


def test_put_then_get_per_mode(client, user):
    assert client.get("/api/me/ui-state", headers=user).json() == {}
    r = client.put("/api/me/ui-state/desktop", json=DESKTOP, headers=user)
    assert r.status_code == 200
    assert r.json()["mode"] == "desktop" and r.json()["updated_at"].endswith("+00:00")
    assert client.put("/api/me/ui-state/phone", json=PHONE, headers=user).status_code == 200
    assert client.put("/api/me/ui-state/tablet", json=TABLET, headers=user).status_code == 200
    got = client.get("/api/me/ui-state", headers=user).json()
    assert set(got) == {"desktop", "phone", "tablet"}
    assert got["desktop"]["state"] == DESKTOP
    assert got["phone"]["state"] == PHONE
    assert got["tablet"]["state"] == TABLET


def test_last_write_wins(client, user):
    first = client.put("/api/me/ui-state/phone", json=PHONE, headers=user).json()["updated_at"]
    later = {**PHONE, "tab": "chat", "params": None}
    second = client.put("/api/me/ui-state/phone", json=later, headers=user).json()["updated_at"]
    assert second >= first
    got = client.get("/api/me/ui-state", headers=user).json()["phone"]
    assert got["state"] == {"v": 1, "tab": "chat", "sub": "schedule-table"}
    assert got["updated_at"] == second


def test_another_user_cannot_read_or_write_mine(client, session, user, admin):
    client.put("/api/me/ui-state/desktop", json=DESKTOP, headers=user)
    # 다른 사람(관리자)에게는 보이지 않고, 그 사람이 쓴 것은 그 사람 것에만 들어간다.
    assert client.get("/api/me/ui-state", headers=admin).json() == {}
    client.put("/api/me/ui-state/desktop", json={"v": 1, "wins": [], "deactivated": True}, headers=admin)
    assert client.get("/api/me/ui-state", headers=user).json()["desktop"]["state"] == DESKTOP
    # 경로에 남의 id 를 넣을 길이 없다(내 것만).
    assert client.get("/api/me/ui-state/1", headers=user).status_code in (404, 405)


def test_bad_mode_is_422(client, user):
    assert client.put("/api/me/ui-state/watch", json=DESKTOP, headers=user).status_code == 422


def test_bad_shapes_are_422(client, user):
    win = DESKTOP["wins"][0]
    bad = [
        ("desktop", {**DESKTOP, "v": 2}),
        ("desktop", {**DESKTOP, "extra": 1}),
        ("desktop", {**DESKTOP, "wins": [{**win, "program": "no-such-program"}]}),
        ("desktop", {**DESKTOP, "wins": [{**win, "x": "24"}]}),
        ("desktop", {**DESKTOP, "wins": [{**win, "w": 10**9}]}),
        ("desktop", {**DESKTOP, "wins": [{**win, "params": {"compose": "hello"}}]}),
        ("desktop", {**DESKTOP, "wins": [{**win, "params": {"tab": "Hello world"}}]}),
        ("desktop", {**DESKTOP, "wins": [{**win, "params": {"id": "abc"}}]}),
        ("desktop", {**DESKTOP, "wins": [win] * 41}),
        ("desktop", [1, 2]),
        ("phone", {**PHONE, "tab": "library"}),
        ("phone", {**PHONE, "sub": "cpm"}),
        ("tablet", {**TABLET, "active": "schedule"}),
    ]
    for mode, body in bad:
        r = client.put(f"/api/me/ui-state/{mode}", json=body, headers=user)
        assert r.status_code == 422, body
    assert client.get("/api/me/ui-state", headers=user).json() == {}


def test_not_json_is_422(client, user):
    r = client.put("/api/me/ui-state/desktop", content=b"{not json", headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_oversize_is_422(client, user):
    padded = json.dumps(DESKTOP) + " " * (33 * 1024)
    r = client.put("/api/me/ui-state/desktop", content=padded.encode(), headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["code"] == "ui_state_too_large"


def test_phone_like_values_are_rejected_and_not_echoed(client, user):
    for number in ("01000000000", "010-0000-0000", "0212345678", "15880000"):
        body = {**PHONE, "params": {"contact": number}}
        r = client.put("/api/me/ui-state/phone", json=body, headers=user)
        assert r.status_code == 422 and r.json()["code"] == "ui_state_phone", number
        assert number not in r.text
    assert client.get("/api/me/ui-state", headers=user).json() == {}


def test_rows_older_than_the_account_are_not_served(client, session, user_token):
    # 지운 계정의 id 를 새 계정이 다시 받았을 때 앞 사람 것이 보이지 않는다.
    user = session.get(User, 2)
    session.add(UiState(user_id=user.id, mode="desktop", state_json=DESKTOP, updated_at=user.created_at - timedelta(days=1)))
    session.commit()
    assert client.get("/api/me/ui-state", headers=auth(user_token)).json() == {}


def test_field_user_can_keep_own_state(client, session):
    field = User(login_id="field1", name="현장", role="field", password_hash=hash_password("x"))
    session.add(field)
    session.commit()
    headers = auth(issue_token(field.id))
    body = {"v": 1, "tab": "schedule", "sub": "field"}
    assert client.put("/api/me/ui-state/phone", json=body, headers=headers).status_code == 200
    assert client.get("/api/me/ui-state", headers=headers).json()["phone"]["state"] == body


def test_updated_at_is_recent_utc(client, user):
    at = client.put("/api/me/ui-state/tablet", json=TABLET, headers=user).json()["updated_at"]
    assert abs(datetime.fromisoformat(at) - datetime.now(UTC)) < timedelta(minutes=1)


def test_concurrent_first_puts_do_not_collide(client, monkeypatch):
    # 두 기기가 처음 저장을 같이 보내도(줄이 아직 없을 때) 겹침 오류(500) 없이 한 줄로 끝난다.
    # 「읽고 없으면 넣기」였다면 모두가 읽은 뒤 넣게 맞춰(읽기 뒤 장벽) 겹침을 늘 재현한다.
    import threading
    from contextlib import contextmanager
    from types import SimpleNamespace

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db import get_session
    from app.store import ui_states

    me = SimpleNamespace(id=1)
    barrier = threading.Barrier(6)
    after_read = threading.Barrier(6)
    real_get = Session.get

    def get_then_wait(self, *args, **kwargs):
        found = real_get(self, *args, **kwargs)
        if args and args[0] is UiState:
            after_read.wait(timeout=5)
        return found

    monkeypatch.setattr(Session, "get", get_then_wait)
    errors: list[BaseException] = []

    def first_put(i: int) -> None:
        try:
            with contextmanager(get_session)() as s:
                barrier.wait(timeout=10)
                ui_states.put(s, me, "desktop", {**DESKTOP, "deactivated": bool(i % 2)})
        except BaseException as e:  # noqa: BLE001 — 시험이 모은다
            errors.append(e)

    threads = [threading.Thread(target=first_put, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert errors == []
    with contextmanager(get_session)() as s:
        assert s.scalar(select(func.count()).select_from(UiState)) == 1
