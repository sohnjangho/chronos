"""연락처 — 관리자 등급·한 사람 여러 프로젝트(11-24 PM).

「연락처에 관리자 등급을 넣어 줘서 관리자 등급이 여러 개를 관리할 경우 대응하게 해 주고, 한 사람이 여러 개의 프로젝트를 담당할
수도 있으니 연락처에 여러 개의 프로젝트가 등록되게 해 줘.」

- access_level(trade 기본 · manager): 관리자만 정하고 바꾼다(403 admin_only_level, 아무것도 바뀌지 않음), 바뀐 줄마다
  contact_access_changes 에 한 줄(번호 없음).
- 주소록은 프로젝트마다 줄이 따로고 person_key 로 잇는다. 등록은 그 프로젝트에 이은 줄을 만들고, 빼기는 그 줄을 숨긴다(연락
  기록은 그대로). 이름·번호·성별·언어·음성·채널·수신 거부·등급은 이은 줄 모두에, 협력사·담당·근무시간·메모는 줄마다.
- 기존 DB 에는 init_db → store.upgrade 가 두 칸을 더한다(옛 줄은 trade · 열쇠 없음).
번호·이름은 모두 가상이다.
"""

import json
import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import close_db, init_db
from app.errors import ApiError
from app.outreach.harness import door
from app.programs.contacts import service
from app.programs.contacts.schemas import CompanyIn, PersonIn
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach
from app.store.tables import Base, User
from app.store.tables_outreach import (
    Contact,
    ContactAccessChange,
    NotifyConnection,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE, assert_clean

ADMIN_LEVEL = ("admin_only_level", "관리자 등급은 관리자만 정하거나 바꿀 수 있습니다.")
NEW_NUMBER = "010-0000-0198"
NOW = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/contacts{rest}"


def _company(client, headers, sid, name="가람건설") -> int:
    r = client.post(_url(sid, "/companies"), json={"name": name, "trade": "골조"}, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _person(client, headers, sid, company_id, **kw) -> dict:
    body = {"name": "김공정", "role_title": "공무", "company_id": company_id, "phone": SENTINEL_PHONE, **kw}
    r = client.post(_url(sid, "/people"), json=body, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()


def _err(r) -> tuple[str, str]:
    return r.json()["code"], r.json()["message"]


def _link(client, headers, sid, pid, other, company_id=None, **kw):
    body = {"schedule_id": other, **({"company_id": company_id} if company_id is not None else {}), **kw}
    return client.post(_url(sid, f"/people/{pid}/projects"), json=body, headers=headers)


def _audit(session) -> list[tuple]:
    session.expire_all()
    return session.execute(select(ContactAccessChange.schedule_id, ContactAccessChange.contact_id,
                                  ContactAccessChange.login_id, ContactAccessChange.before, ContactAccessChange.after)
                           .order_by(ContactAccessChange.id)).all()


def _row(session, contact_id) -> Contact:
    session.expire_all()
    return session.get(Contact, contact_id)


# ── 관리자 등급 ─────────────────────────────────────────────────────────────


def test_new_person_is_trade_and_shows_its_level(client, user, sid):
    created = _person(client, user, sid, _company(client, user, sid))

    assert (created["access_level"], created["projects"]) == ("trade", 1)
    listed = client.get(_url(sid), headers=user).json()["companies"][0]["people"][0]
    assert (listed["access_level"], listed["projects"]) == ("trade", 1)


def test_only_an_admin_sets_the_manager_level(client, user, admin, session, sid, caplog):
    caplog.set_level(logging.INFO)
    company = _company(client, admin, sid)

    refused_new = client.post(_url(sid, "/people"), json={"name": "최소장", "company_id": company, "phone": SENTINEL_PHONE,
                                                         "access_level": "manager"}, headers=user)
    pid = _person(client, user, sid, company)["id"]
    refused_patch = client.patch(_url(sid, f"/people/{pid}"), json={"access_level": "manager", "note": "x"}, headers=user)

    assert (refused_new.status_code, _err(refused_new)) == (403, ADMIN_LEVEL)
    assert (refused_patch.status_code, _err(refused_patch)) == (403, ADMIN_LEVEL)
    assert (_row(session, pid).access_level, _row(session, pid).note) == ("trade", "")  # 아무것도 바뀌지 않음
    assert session.scalar(select(Contact.id).where(Contact.name == "최소장")) is None
    assert client.patch(_url(sid, f"/people/{pid}"), json={"access_level": "trade"}, headers=user).status_code == 200  # 그대로면 됨

    granted = client.patch(_url(sid, f"/people/{pid}"), json={"access_level": "manager"}, headers=admin)
    made = client.post(_url(sid, "/people"), json={"name": "최소장", "company_id": company, "phone": NEW_NUMBER,
                                                  "access_level": "manager"}, headers=admin)

    assert granted.status_code == 200 and granted.json()["access_level"] == "manager"
    assert made.status_code == 201 and made.json()["access_level"] == "manager"
    assert _audit(session) == [(sid, pid, "admin", "trade", "manager"), (sid, made.json()["id"], "admin", None, "manager")]
    lines = [m for m in caplog.messages if m.startswith("관리자 등급")]
    assert len(lines) == 2 and SENTINEL_DIGITS not in json.dumps(lines)
    assert_clean(caplog)

    back = client.patch(_url(sid, f"/people/{pid}"), json={"access_level": "trade"}, headers=user)  # 내리기도 관리자만
    assert (back.status_code, _err(back)) == (403, ADMIN_LEVEL)


def test_proposal_style_create_without_a_user_is_trade_only(session, sid):
    company = service.create_company(session, sid, CompanyIn(name="가람건설"))
    made = service.create_person(session, sid, PersonIn(name="김공정", company_id=company.id))
    assert made.access_level == "trade"
    with pytest.raises(ApiError) as caught:
        service.create_person(session, sid, PersonIn(name="최소장", company_id=company.id, access_level="manager"))
    assert caught.value.code == "admin_only_level"


def test_manager_level_reaches_the_door_after_the_api_change(client, admin, session, sid):
    session.add(NotifyConnection(name="기본", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="9999",
                                 account_id="acc", is_default=True, test_mode=False, inbound_mode="all"))
    session.commit()
    pid = _person(client, admin, sid, _company(client, admin, sid))["id"]
    now = NOW

    trade = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=now))
    client.patch(_url(sid, f"/people/{pid}"), json={"access_level": "manager"}, headers=admin)
    session.expire_all()
    manager = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=now))

    assert (trade.facts, manager.facts, manager.schedule_ids) == ("trade", "all", (sid,))
    assert door.outbound_scope(session, sid, pid).facts == "all"


# ── 참여 프로젝트: 등록·빼기 ─────────────────────────────────────────────────────


def test_adding_a_project_creates_a_linked_row_with_shared_fields(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid), gender="female", language="en",
                  hours={"days": [0, 1], "start": "07:00", "end": "16:00"}, note="본사 메모")["id"]
    there = _company(client, user, sid2, name="나래건설")

    missing = _link(client, user, sid, pid, sid2)
    r = _link(client, user, sid, pid, sid2, there, role_title="현장소장")

    assert (missing.status_code, _err(missing)) == (422, ("company_required", "그 프로젝트의 협력사를 골라 주세요."))
    assert r.status_code == 201, r.json()
    links = r.json()["project_links"]
    assert [(p["schedule_id"], p["current"]) for p in links] == [(sid, True), (sid2, False)]
    assert r.json()["projects"] == 2 and links[1]["company_name"] == "나래건설"
    new = _row(session, links[1]["contact_id"])
    src = _row(session, pid)
    assert new.person_key == src.person_key and new.person_key
    assert (new.name, new.phone, new.gender, new.language, new.company_id, new.role_title) == (
        "김공정", src.phone, "female", "en", there, "현장소장")
    assert (new.hours_json, new.note) == (None, "")  # 프로젝트마다 따로
    listed = client.get(_url(sid2), headers=user).json()["companies"][0]["people"][0]
    assert listed["projects"] == 2
    assert SENTINEL_DIGITS not in r.text and SENTINEL_PHONE not in r.text
    again = _link(client, user, sid, pid, sid2, there)
    assert (again.status_code, again.json()["code"]) == (409, "already_linked")


def test_removing_a_project_hides_the_row_and_keeps_its_history(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    there = _company(client, user, sid2, name="나래건설")
    other = _link(client, user, sid, pid, sid2, there).json()["project_links"][1]["contact_id"]
    session.add(OutreachMessage(schedule_id=sid2, contact_id=other, direction="out", channel="sms", body="내일 타설",
                                origin="user", status="delivered"))
    session.commit()

    r = client.delete(_url(sid, f"/people/{pid}/projects/{sid2}"), headers=user)

    assert r.status_code == 200 and [p["schedule_id"] for p in r.json()["project_links"]] == [sid]
    row = _row(session, other)
    assert row is not None and row.hidden is True  # 지우지 않음
    assert session.scalar(select(OutreachMessage.id).where(OutreachMessage.contact_id == other)) is not None
    assert client.get(_url(sid2), headers=user).json()["companies"][0]["people"] == []
    gone = client.delete(_url(sid, f"/people/{pid}/projects/{sid2}"), headers=user)
    own = client.delete(_url(sid, f"/people/{pid}/projects/{sid}"), headers=user)
    assert (gone.status_code, own.status_code, own.json()["code"]) == (404, 422, "own_project")

    back = _link(client, user, sid, pid, sid2)  # 다시 등록하면 그 줄을 다시 보인다(협력사를 다시 고르지 않아도)
    assert back.status_code == 201 and back.json()["project_links"][1]["contact_id"] == other
    assert _row(session, other).hidden is False


def test_project_choices_list_every_manageable_project(client, user, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    _link(client, user, sid, pid, sid2, _company(client, user, sid2, name="나래건설"))

    r = client.get(_url(sid, f"/people/{pid}/projects"), headers=user)

    assert r.status_code == 200
    assert [(c["schedule_id"], c["linked"], c["current"], c["company_name"]) for c in r.json()] == [
        (sid, True, True, "가람건설"), (sid2, True, False, "나래건설")]


def test_permissions_only_manageable_projects(client, user, field_user, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]

    for r in (client.get(_url(sid, f"/people/{pid}/projects"), headers=field_user),
              _link(client, field_user, sid, pid, sid2, 1),
              client.delete(_url(sid, f"/people/{pid}/projects/{sid2}"), headers=field_user)):
        assert (r.status_code, r.json()["code"]) == (403, "field_no_contacts")
    missing = _link(client, user, sid, pid, 9999, 1)
    foreign_company = _link(client, user, sid, pid, sid2, _company(client, user, sid, name="같은 프로젝트 협력사"))
    assert (missing.status_code, foreign_company.status_code) == (404, 404)  # 다른 프로젝트의 협력사 id 는 없는 것과 같다


def test_only_projects_the_user_can_manage(client, user, session, sid, sid2, monkeypatch):
    """관리할 수 있는 프로젝트는 projects.manageable 한 곳 — 그 밖의 프로젝트는 있는 프로젝트·있는 협력사여도 없는 것과 같다."""
    from app.programs.contacts import projects

    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    there = _company(client, user, sid2, name="나래건설")
    only_here = lambda session, user: [r for r in projects.list_records(session) if r.id == sid]
    monkeypatch.setattr(projects, "manageable", only_here)

    assert _link(client, user, sid, pid, sid2, there).status_code == 404
    assert [c["schedule_id"] for c in client.get(_url(sid, f"/people/{pid}/projects"), headers=user).json()] == [sid]
    assert session.scalar(select(Contact.id).where(Contact.schedule_id == sid2)) is None


def test_manager_person_joins_a_new_project_only_by_an_admin(client, user, admin, session, sid, sid2):
    pid = _person(client, admin, sid, _company(client, admin, sid), access_level="manager")["id"]
    there = _company(client, user, sid2, name="나래건설")

    refused = _link(client, user, sid, pid, sid2, there)
    ok = _link(client, admin, sid, pid, sid2, there)

    assert (refused.status_code, _err(refused)) == (403, ADMIN_LEVEL)
    assert ok.status_code == 201
    other = ok.json()["project_links"][1]["contact_id"]
    assert _row(session, other).access_level == "manager"
    assert _audit(session)[-1] == (sid2, other, "admin", None, "manager")


# ── 함께 저장되는 칸 ──────────────────────────────────────────────────────────


def test_shared_fields_propagate_and_per_project_fields_do_not(client, user, admin, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid), note="가람 메모")["id"]
    there = _company(client, user, sid2, name="나래건설")
    other = _link(client, user, sid, pid, sid2, there, role_title="소장").json()["project_links"][1]["contact_id"]

    r = client.patch(_url(sid, f"/people/{pid}"), json={
        "name": "김공정2", "phone": NEW_NUMBER, "gender": "male", "language": "vi", "voice_mode": "manual",
        "voice_id": "voice.a1", "can_call": False, "role_title": "공무팀장", "note": "바뀐 메모",
        "hours": {"days": [2], "start": "09:00", "end": "17:00"}}, headers=user)
    level = client.patch(_url(sid2, f"/people/{other}"), json={"access_level": "manager"}, headers=admin)

    assert r.status_code == 200 and level.status_code == 200
    src, dup = _row(session, pid), _row(session, other)
    for column in ("name", "phone", "gender", "language", "voice_mode", "voice_id", "can_sms", "can_kakao", "can_call",
                   "access_level"):
        assert getattr(src, column) == getattr(dup, column), column
    assert (dup.name, dup.can_call, dup.access_level) == ("김공정2", False, "manager")
    assert (dup.role_title, dup.note, dup.hours_json, dup.company_id) == ("소장", "", None, there)  # 그대로
    assert (src.role_title, src.note) == ("공무팀장", "바뀐 메모")
    assert [(a[0], a[1], a[4]) for a in _audit(session)] == [(sid2, other, "manager"), (sid, pid, "manager")]
    note_only = client.patch(_url(sid2, f"/people/{other}"), json={"note": "나래 메모"}, headers=user)
    assert note_only.status_code == 200 and _row(session, pid).note == "바뀐 메모"


def test_do_not_contact_propagates_and_clearing_needs_an_admin(client, user, admin, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    other = _link(client, user, sid, pid, sid2, _company(client, user, sid2)).json()["project_links"][1]["contact_id"]

    on = client.patch(_url(sid2, f"/people/{other}"), json={"do_not_contact": True, "dnc_reason": "본인 요청"}, headers=user)
    assert on.status_code == 200
    assert (_row(session, pid).do_not_contact, _row(session, pid).dnc_reason) == (True, "본인 요청")
    assert outreach.is_do_not_contact(session, SENTINEL_PHONE)

    refused = client.patch(_url(sid, f"/people/{pid}"), json={"do_not_contact": False}, headers=user)
    assert (refused.status_code, refused.json()["code"]) == (403, "admin_only")
    cleared = client.patch(_url(sid, f"/people/{pid}"), json={"do_not_contact": False}, headers=admin)
    assert cleared.status_code == 200
    assert (_row(session, other).do_not_contact, outreach.is_do_not_contact(session, SENTINEL_PHONE)) == (False, False)


def test_clearing_needs_an_admin_even_when_only_a_linked_row_shows_it(client, user, session, sid, sid2):
    """같은 사람의 다른 줄(예전에 번호가 갈라진 줄)만 수신 거부여도 풀기는 관리자만 — 아무것도 바뀌지 않는다."""
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    other = _link(client, user, sid, pid, sid2, _company(client, user, sid2)).json()["project_links"][1]["contact_id"]
    row = _row(session, other)
    row.phone, row.do_not_contact = "01000000198", True
    session.commit()

    r = client.patch(_url(sid, f"/people/{pid}"), json={"do_not_contact": False}, headers=user)

    assert (r.status_code, r.json()["code"]) == (403, "admin_only")
    assert _row(session, other).do_not_contact is True


def test_hidden_linked_rows_still_get_shared_fields(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    other = _link(client, user, sid, pid, sid2, _company(client, user, sid2)).json()["project_links"][1]["contact_id"]
    client.delete(_url(sid, f"/people/{pid}/projects/{sid2}"), headers=user)

    client.patch(_url(sid, f"/people/{pid}"), json={"name": "새 이름"}, headers=user)

    assert (_row(session, other).name, _row(session, other).hidden) == ("새 이름", True)


# ── 같은 번호가 그 프로젝트에 이미 있음 ─────────────────────────────────────────────


def test_same_number_in_the_target_offers_linking_without_the_number(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    there = _company(client, user, sid2, name="나래건설")
    existing = _person(client, user, sid2, there, name="김공정(나래)", role_title="반장", note="나래 메모")["id"]

    clash = _link(client, user, sid, pid, sid2, there)

    assert clash.status_code == 409 and clash.json()["code"] == "same_number_there"
    assert clash.json()["detail"] == {"contact_id": existing}
    assert SENTINEL_DIGITS not in clash.text and "0199" not in clash.text
    linked = _link(client, user, sid, pid, sid2, link_contact_id=existing)
    assert linked.status_code == 201, linked.json()
    row = _row(session, existing)
    assert (row.person_key, row.name, row.role_title, row.note) == (_row(session, pid).person_key, "김공정", "반장", "나래 메모")
    assert session.scalar(select(Contact.id).where(Contact.schedule_id == sid2, Contact.id != existing)) is None


def test_linking_needs_the_same_number_and_an_unlinked_row(client, user, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    there = _company(client, user, sid2, name="나래건설")
    stranger = _person(client, user, sid2, there, name="남", phone=NEW_NUMBER)["id"]

    r = _link(client, user, sid, pid, sid2, link_contact_id=stranger)

    assert (r.status_code, r.json()["code"]) == (422, "not_same_number")
    assert NEW_NUMBER not in r.text and "0198" not in r.text


def test_linking_keeps_do_not_contact_from_either_side(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    there = _company(client, user, sid2, name="나래건설")
    existing = _person(client, user, sid2, there, do_not_contact=True, dnc_reason="본인 요청")["id"]

    _link(client, user, sid, pid, sid2, link_contact_id=existing)

    assert (_row(session, pid).do_not_contact, _row(session, existing).do_not_contact) == (True, True)


# ── 들어오는 문: 이은 두 프로젝트의 같은 번호는 여전히 현장을 먼저 ─────────────────────────


def test_linked_rows_in_two_projects_still_require_the_site(client, admin, session, sid, sid2):
    session.add(NotifyConnection(name="기본", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="9999",
                                 account_id="acc", is_default=True, test_mode=False, inbound_mode="all"))
    session.commit()
    pid = _person(client, admin, sid, _company(client, admin, sid), access_level="manager")["id"]
    _link(client, admin, sid, pid, sid2, _company(client, admin, sid2))
    session.expire_all()

    scope = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))

    assert scope.caller_class == "contact_multi" and scope.site_required and scope.facts == "none"
    assert scope.pinned(sid2).facts == "all" and scope.pinned(sid2).schedule_ids == (sid2,)


# ── 예전 DB ─────────────────────────────────────────────────────────────────


def test_existing_contacts_table_gets_both_columns(tmp_path):
    """두 칸 전에 만든 contacts → init_db → access_level 은 trade, person_key 는 비어 있음(혼자인 사람)."""
    path = tmp_path / "data" / "chronos.db"
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "contacts"])
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE contacts (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER NOT NULL, "
                          "company_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, role_title VARCHAR(100) NOT NULL, "
                          "phone VARCHAR(20), can_sms BOOLEAN NOT NULL, can_kakao BOOLEAN NOT NULL, can_call BOOLEAN NOT NULL, "
                          "hours_json JSON, gender VARCHAR(10) NOT NULL, language VARCHAR(10) NOT NULL, "
                          "voice_mode VARCHAR(10) NOT NULL, voice_id VARCHAR(100), do_not_contact BOOLEAN NOT NULL, "
                          "dnc_reason VARCHAR(200), phone_invalid BOOLEAN NOT NULL, note TEXT NOT NULL, "
                          "hidden BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text("INSERT INTO contacts (schedule_id, company_id, name, role_title, can_sms, can_kakao, can_call, "
                          "gender, language, voice_mode, do_not_contact, phone_invalid, note, hidden, created_at, updated_at) "
                          "VALUES (1, 1, '옛 사람', '', 1, 1, 1, 'unknown', 'ko', 'auto', 0, 0, '', 0, "
                          "'2026-11-20 09:00:00', '2026-11-20 09:00:00')"))
    engine.dispose()

    init_db()
    close_db()

    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        old = session.scalars(select(Contact)).one()
        assert (old.access_level, old.person_key) == ("trade", None)
        session.add(Contact(schedule_id=1, company_id=1, name="새 사람"))
        session.commit()
        new = session.scalars(select(Contact).where(Contact.name == "새 사람")).one()
        assert new.access_level == "trade" and len(new.person_key) == 32
        assert "contact_access_changes" in {row[0] for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))}
    engine.dispose()
