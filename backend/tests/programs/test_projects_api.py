"""프로젝트 관리 API(11-24): 이름·AI 가 부를 이름·현장 주소·한 줄 소개·발주처·시공사.

- 로그인한 사람은 누구나 읽는다(일정 목록과 같다). 고치기는 현장 관리자를 뺀 사람만(일정 고치기와 같은 require_editor).
- 글은 NFC·앞뒤 빈칸 없이, 칸마다 길이 상한, 줄 바꿈·보이지 않는 글자 없이, **번호 없이**(에이전트가 통화·문자에서 읽는다).
- 이름을 바꿔도 버전·주소록·연락 기록은 그대로다(모두 schedule_id 로 가리킨다).
번호·이름은 모두 가상이다.
"""

import logging
import unicodedata

import pytest
from sqlalchemy import select

from app.main import app
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import ProjectProfile, ScheduleRecord, ScheduleVersion, User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    OutreachCall,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_PHONE

URL = "/api/projects"
FIELD_READ_ONLY = "field_read_only"


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def _named(session, sid: int, name: str) -> None:
    session.get(ScheduleRecord, sid).name = name
    session.commit()


def test_router_is_mounted():
    """app/programs/projects/router.py 가 자동 등록으로 붙는다(main 을 고치지 않는다)."""
    paths = app.openapi()["paths"]
    assert set(paths[URL]) == {"get"} and set(paths[f"{URL}/{{schedule_id}}"]) == {"get", "patch"}


def test_list_gives_every_project_with_an_empty_profile_and_the_spoken_name(client, user, session, sid):
    _named(session, sid, "가람 물류센터 신축 2026-11-23")
    other = schedules.store(session, schedules.sample())

    r = client.get(URL, headers=user)

    assert r.status_code == 200
    assert [p["id"] for p in r.json()] == [sid, other]
    first = r.json()[0]
    assert first == {"id": sid, "name": "가람 물류센터 신축 2026-11-23", "spoken_name": "", "spoken": "가람 물류센터 신축",
                     "site_address": "", "summary": "", "client_builder": "", "updated_at": None, "updated_by": "",
                     "same_name": False, "same_as": None}


def test_patch_saves_profile_and_rename_and_the_agent_name_follows(client, user, session, sid):
    r = client.patch(f"{URL}/{sid}", headers=user, json={
        "name": "가람 물류센터 신축", "spoken_name": " 가람 물류센터 ", "site_address": "경기도 가상시 물류로 12",
        "summary": "지상 4층 물류센터 신축, 골조 공사 중", "client_builder": "가상물류 · 가람건설"})

    assert r.status_code == 200, r.json()
    body = r.json()
    assert (body["name"], body["spoken_name"], body["spoken"]) == ("가람 물류센터 신축", "가람 물류센터", "가람 물류센터")
    assert body["updated_by"] == "일반 사용자" and body["updated_at"] is not None
    session.expire_all()
    assert session.get(ScheduleRecord, sid).name == "가람 물류센터 신축"
    row = session.get(ProjectProfile, sid)
    assert (row.site_address, row.summary, row.client_builder) == ("경기도 가상시 물류로 12", "지상 4층 물류센터 신축, 골조 공사 중",
                                                                   "가상물류 · 가람건설")
    assert client.get(f"{URL}/{sid}", headers=user).json() == body


def test_patch_changes_only_the_fields_sent(client, user, session, sid):
    client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람", "summary": "소개"})
    r = client.patch(f"{URL}/{sid}", headers=user, json={"summary": ""})

    assert (r.json()["spoken_name"], r.json()["summary"], r.json()["name"]) == ("가람", "", "시험 일정")


def test_text_is_stored_as_nfc(client, user, session, sid):
    decomposed = unicodedata.normalize("NFD", "가람 물류센터")
    r = client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": decomposed, "name": decomposed})

    assert r.json()["spoken_name"] == "가람 물류센터" == r.json()["name"]


@pytest.mark.parametrize(("field", "limit"), [("spoken_name", 40), ("site_address", 120), ("summary", 200),
                                              ("client_builder", 80), ("name", 120)])
def test_length_limits(client, user, sid, field, limit):
    ok = client.patch(f"{URL}/{sid}", headers=user, json={field: "가" * limit})
    over = client.patch(f"{URL}/{sid}", headers=user, json={field: "가" * (limit + 1)})

    assert ok.status_code == 200
    assert over.status_code == 422 and over.json()["code"] == "text_too_long"
    assert over.json()["detail"] == {"field": field, "max": limit}


@pytest.mark.parametrize("field", ["name", "spoken_name", "site_address", "summary", "client_builder"])
@pytest.mark.parametrize("bad", ["가람\n물류", "가람\u200b물류", "가람\u202e물류", "가람\x00"])
def test_control_and_invisible_characters_are_refused(client, user, sid, field, bad):
    r = client.patch(f"{URL}/{sid}", headers=user, json={field: bad})

    assert r.status_code == 422 and r.json()["code"] == "invalid_text" and r.json()["detail"] == {"field": field}


@pytest.mark.parametrize("field", ["name", "spoken_name", "site_address", "summary", "client_builder"])
@pytest.mark.parametrize("number", [SENTINEL_PHONE, "1588-0000"])
def test_phone_numbers_are_refused_without_echoing_them(client, user, session, sid, field, number):
    r = client.patch(f"{URL}/{sid}", headers=user, json={field: f"문의 {number}"})

    assert r.status_code == 422 and r.json()["code"] == "phone_in_text" and r.json()["detail"] == {"field": field}
    assert number not in r.text
    session.expire_all()
    assert session.get(ProjectProfile, sid) is None and session.get(ScheduleRecord, sid).name == "시험 일정"


def test_empty_name_and_null_and_unknown_fields_are_refused(client, user, sid):
    assert client.patch(f"{URL}/{sid}", headers=user, json={"name": "  "}).json()["code"] == "invalid_name"
    assert client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": None}).status_code == 422
    assert client.patch(f"{URL}/{sid}", headers=user, json={"domain": "x"}).status_code == 422


def test_unknown_project_is_404(client, user):
    assert client.get(f"{URL}/999", headers=user).status_code == 404
    assert client.patch(f"{URL}/999", headers=user, json={"summary": "x"}).status_code == 404


def test_login_is_required(client, sid):
    assert client.get(URL).status_code == 401
    assert client.patch(f"{URL}/{sid}", json={"summary": "x"}).status_code == 401


def test_field_manager_reads_but_cannot_change(client, field_user, session, sid):
    assert client.get(URL, headers=field_user).status_code == 200
    r = client.patch(f"{URL}/{sid}", headers=field_user, json={"spoken_name": "가람"})

    assert r.status_code == 403 and r.json()["code"] == FIELD_READ_ONLY
    session.expire_all()
    assert session.get(ProjectProfile, sid) is None


def test_admin_can_change(client, admin, sid):
    assert client.patch(f"{URL}/{sid}", headers=admin, json={"spoken_name": "가람"}).status_code == 200


def test_change_is_logged_with_field_names_only(client, user, sid, caplog):
    with caplog.at_level(logging.INFO, logger="app.programs.projects.service"):
        client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람 비밀이름", "summary": "소개 글"})

    lines = [r.getMessage() for r in caplog.records if r.name == "app.programs.projects.service"]
    assert len(lines) == 1 and "spoken_name" in lines[0] and "summary" in lines[0] and str(sid) in lines[0]
    assert "비밀이름" not in lines[0] and "소개 글" not in lines[0]


def test_rename_keeps_versions_contacts_and_outreach_rows(client, user, session, sid):
    company = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(company)
    session.flush()
    person = Contact(schedule_id=sid, company_id=company.id, name="박현장", phone="01000000199")
    session.add(person)
    session.flush()
    session.add(OutreachMessage(schedule_id=sid, contact_id=person.id, direction="out", channel="sms", origin="user",
                                origin_name="김공정", body="내일 타설", status="draft"))
    session.add(OutreachCall(schedule_id=sid, contact_id=person.id, direction="out", origin="user", origin_name="김공정",
                             purpose="타설 확인"))
    session.commit()
    before = session.scalar(select(ScheduleRecord.current_version).where(ScheduleRecord.id == sid))

    client.patch(f"{URL}/{sid}", headers=user, json={"name": "가람 물류센터 신축"})

    session.expire_all()
    assert session.get(ScheduleRecord, sid).current_version == before
    assert session.scalars(select(ScheduleVersion.n).where(ScheduleVersion.schedule_id == sid)).all() == [before]
    assert [c.name for c in session.scalars(select(Contact).where(Contact.schedule_id == sid))] == ["박현장"]
    assert session.scalars(select(OutreachMessage.schedule_id)).all() == [sid]
    assert session.scalars(select(OutreachCall.schedule_id)).all() == [sid]
    assert [s["name"] for s in client.get("/api/schedules", headers=user).json()] == ["가람 물류센터 신축"]


def test_deleting_the_schedule_removes_its_profile(client, admin, session, sid):
    client.patch(f"{URL}/{sid}", headers=admin, json={"spoken_name": "가람"})

    r = client.delete(f"/api/schedules/{sid}", headers=admin)

    assert r.status_code == 200, r.json()
    session.expire_all()
    assert session.get(ProjectProfile, sid) is None


@pytest.mark.parametrize("taken", ["가람 물류센터", "가람물류센터", "가람 물류센터 신축", "가람 물류센터 현장", "가람 물류센터 공사",
                                   "\u1100\u1161\u1105\u1161\u11b7 물류센터"])  # 끝의 현장·공사 · 풀어 쓴(NFD) 한글도 같은 이름
def test_spoken_name_already_used_by_another_project_is_refused(client, user, session, sid, taken):
    """다른 프로젝트의 부를 이름이나 다듬은 이름과 같으면(빈칸·대소문자 무시) 409 — AI 가 두 현장을 같은 이름으로 부르지 않게."""
    other = schedules.store(session, schedules.sample())
    _named(session, other, "가람 물류센터 신축 2026-11-23")
    client.patch(f"{URL}/{other}", headers=user, json={"spoken_name": "가람 물류센터"})

    r = client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": taken})

    assert r.status_code == 409 and r.json()["code"] == "spoken_name_taken" and r.json()["detail"] == {"field": "spoken_name"}
    assert "「가람 물류센터 신축 2026-11-23」" in r.json()["message"]  # 어느 프로젝트와 겹치는지
    session.expire_all()
    assert session.get(ProjectProfile, sid) is None


def test_keeping_its_own_spoken_name_is_fine(client, user, sid):
    client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람"})
    assert client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람", "summary": "소개"}).status_code == 200


@pytest.mark.parametrize("name", ["가람 물류센터 2026-12-01", "가람 물류센터 현장 (v2)", "가람 물류센터 신축 공사"])
def test_renaming_to_a_name_another_project_is_called_by_is_refused(client, user, session, sid, name):
    """이름 고치기도 같은 기준: 새 이름의 다듬은 꼴이 다른 프로젝트의 부를 이름·다듬은 이름과 같으면 409."""
    other = schedules.store(session, schedules.sample())
    _named(session, other, "가람 물류센터 신축 2026-11-23")
    client.patch(f"{URL}/{other}", headers=user, json={"spoken_name": "가람 물류센터"})

    r = client.patch(f"{URL}/{sid}", headers=user, json={"name": name})

    assert r.status_code == 409 and r.json()["code"] == "name_taken" and r.json()["detail"] == {"field": "name"}
    assert "「가람 물류센터 신축 2026-11-23」" in r.json()["message"] and "날짜·판 표시를 뗀 이름" in r.json()["message"]
    session.expire_all()
    assert session.get(ScheduleRecord, sid).name == "시험 일정"


def test_renaming_with_its_own_distinct_spoken_name_still_checks_the_cleaned_name(client, user, session, sid):
    other = schedules.store(session, schedules.sample())
    _named(session, other, "나래 아파트")
    r = client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람", "name": "나래 아파트 2026-11-23"})
    assert r.status_code == 409 and r.json()["code"] == "name_taken"


def test_existing_duplicates_are_flagged_in_the_list(client, user, session, sid):
    """예전에 겹쳐 들어온 것(다시 올린 일정) — 둘 다 표시. 한쪽에 다른 부를 이름을 적으면 그쪽은 풀리지만, 다른 쪽은 아직 그
    다듬은 이름과 겹친다(현장 맞추기는 다듬은 이름도 본다 — 「가람 물류센터」라고 하면 둘이 같다). 이름까지 바꾸면 모두 풀린다."""
    other = schedules.store(session, schedules.sample())
    third = schedules.store(session, schedules.sample())
    _named(session, sid, "가람 물류센터 2026-11-23")
    _named(session, other, "가람 물류센터 (v2)")
    _named(session, third, "나래 아파트")

    flags = {p["id"]: p["same_name"] for p in client.get(URL, headers=user).json()}
    assert flags == {sid: True, other: True, third: False}
    same_as = {p["id"]: p["same_as"] for p in client.get(URL, headers=user).json()}
    assert same_as == {sid: "가람 물류센터 (v2)", other: "가람 물류센터 2026-11-23", third: None}
    assert client.get(f"{URL}/{sid}", headers=user).json()["same_name"] is True

    client.patch(f"{URL}/{other}", headers=user, json={"spoken_name": "가람 2단지"})
    flags = {p["id"]: p["same_name"] for p in client.get(URL, headers=user).json()}
    assert flags == {sid: True, other: False, third: False}

    client.patch(f"{URL}/{other}", headers=user, json={"name": "가람 2단지 물류센터"})
    flags = {p["id"]: p["same_name"] for p in client.get(URL, headers=user).json()}
    assert flags == {sid: False, other: False, third: False}


def test_clearing_the_spoken_name_is_allowed_but_warns_when_the_cleaned_name_collides(client, user, session, sid):
    """부를 이름을 비우면 다듬은 이름으로 부른다 — 그것이 겹치면 거절하지 않고 같은 이름 표시로 알린다."""
    other = schedules.store(session, schedules.sample())
    _named(session, sid, "가람 물류센터 2026-11-23")
    _named(session, other, "가람 물류센터 (v2)")
    client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": "가람 1단지"})

    r = client.patch(f"{URL}/{sid}", headers=user, json={"spoken_name": ""})

    assert r.status_code == 200 and r.json()["same_name"] is True and r.json()["same_as"] == "가람 물류센터 (v2)"
