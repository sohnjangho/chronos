"""들어오는 문(Task 66) — 번호로 정하는 발신자 등급과 그 범위. 번호·이름·회사는 모두 가상이다(이름표의 SENTINEL_PHONE).

아래 도우미(connect·company·person·account·block·second_schedule)는 test_door_admit 도 같이 쓴다.
"""

import inspect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.outreach import phone
from app.outreach.harness import door
from app.outreach.harness.types import Caller, Candidate, Scope
from app.store import outreach as store
from app.store.contacts import NotFound
from app.store.tables import User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    NotifyConnection,
)
from tests import schedules
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=KST)  # 화요일 오전
OTHER_PHONE = "010-0000-0000"
REP_PHONE = "1588-0199"  # 대표번호
SAFE_PHONE = "0507-1234-0199"  # 050x 안심번호
LANDLINE = "02-2000-0199"
FOREIGN = "+12120000199"  # 제공사 호출 모듈이 주는 나라 밖 번호 꼴(+숫자)


def connect(session: Session, **kw) -> NotifyConnection:
    """기본 알림 연결. 따로 주지 않으면 시험 모드 끔·모두 받기(등급만 볼 때 다른 규칙이 끼지 않게)."""
    row = NotifyConnection(**{"name": "기본", "base_url": "https://kat.invalid", "secret_ciphertext": "x",
                              "secret_last4": "9999", "account_id": "acc", "is_default": True, "test_mode": False,
                              "inbound_mode": "all", **kw})
    session.add(row)
    session.flush()
    return row


def second_schedule(session: Session) -> int:
    return schedules.store(session, schedules.make([schedules.task("A", 3)]))


def company(session: Session, schedule_id: int, name: str = "가나건설", **kw) -> ContactCompany:
    row = ContactCompany(schedule_id=schedule_id, name=name, **kw)
    session.add(row)
    session.flush()
    return row


def person(session: Session, firm: ContactCompany, name: str = "김공정", number: str | None = SENTINEL_PHONE,
           **kw) -> Contact:
    row = Contact(schedule_id=firm.schedule_id, company_id=firm.id, name=name, phone=phone.normalize(number), **kw)
    session.add(row)
    session.flush()
    return row


def account(session: Session, role: str = "user", number: str | None = SENTINEL_PHONE, **kw) -> User:
    row = User(**{"login_id": f"door-{role}", "name": "이내부", "role": role, "phone": number, "password_hash": "x",
                  **kw})
    session.add(row)
    session.flush()
    return row


def block(session: Session, number: str) -> None:
    session.add(BlockedNumber(number=number, created_by="관리자"))
    session.flush()


def klass(session: Session, number: str | None = SENTINEL_PHONE) -> str:
    return door.resolve(session, number, now=NOW).caller_class


def pair(row: Contact) -> Candidate:
    return Candidate(row.schedule_id, row.id, row.company_id)


# ── 등급표 ──────────────────────────────────────────────────────────


def _arrange(session: Session, sid: int, setup: str) -> str | None:
    """등급표 한 줄의 상황을 만들고, 걸려 온 번호를 돌려준다."""
    if setup == "test_mode_not_allowed":
        connect(session, test_mode=True, allow_numbers_json=[OTHER_PHONE])
        person(session, company(session, sid))
        return SENTINEL_PHONE
    connect(session)
    if setup == "user_phone":
        account(session, "user")
    elif setup == "one_project":
        person(session, company(session, sid))
    elif setup == "two_projects":
        person(session, company(session, sid))
        person(session, company(session, second_schedule(session)))
    elif setup == "two_people_one_number":
        firm = company(session, sid)
        person(session, firm, "김공정")
        person(session, firm, "박현장")
    elif setup == "dnc_contact":
        person(session, company(session, sid), do_not_contact=True)
    elif setup == "admin_blocked":
        block(session, SENTINEL_DIGITS)
    elif setup == "no_number":
        return None
    return SENTINEL_PHONE


@pytest.mark.parametrize("setup,expected", [
    ("user_phone", "internal"), ("one_project", "contact"), ("two_projects", "contact_multi"),
    ("two_people_one_number", "shared"), ("dnc_contact", "do_not_contact"), ("nowhere", "unknown"),
    ("no_number", "withheld"), ("admin_blocked", "blocked"), ("test_mode_not_allowed", "outside_test"),
])
def test_class_table_row(session, sid, setup, expected):
    number = _arrange(session, sid, setup)
    assert door.resolve(session, number, now=NOW).caller_class == expected


def test_resolve_reads_only_the_number():
    """등급을 정하는 함수는 번호(와 시각)만 받는다 — 말·글·모델이 준 값을 넣을 자리가 없다."""
    assert list(inspect.signature(door.resolve).parameters) == ["session", "number", "now"]


def test_class_does_not_depend_on_the_time(session, sid):
    connect(session)
    person(session, company(session, sid))
    assert {door.resolve(session, SENTINEL_PHONE, now=NOW + timedelta(hours=h)).caller_class
            for h in (0, 9, 14, 100)} == {"contact"}


def test_every_written_form_of_a_number_gets_the_same_class(session, sid):
    connect(session)
    person(session, company(session, sid))
    forms = ["010-0000-0199", "01000000199", "+82 10-0000-0199", "+821000000199", "010 0000 0199", " 010.0000.0199 "]
    assert {klass(session, form) for form in forms} == {"contact"}


def test_contact_caller_carries_its_one_pair_and_no_account(session, sid):
    connect(session)
    row = person(session, company(session, sid))
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("contact", (pair(row),), None)


# ── 차례(위가 이긴다) ───────────────────────────────────────────────


def test_no_connection_counts_as_test_mode(session, sid):
    """알림 연결이 없으면 시험 모드(기본 켜짐)·허용 번호 없음으로 본다 — 닫힌 쪽."""
    account(session, "admin")
    person(session, company(session, sid))
    assert klass(session) == "outside_test"
    assert klass(session, None) == "outside_test"


def test_test_mode_beats_everything(session, sid):
    connect(session, test_mode=True, allow_numbers_json=[OTHER_PHONE])
    account(session, "admin")  # 내부 계정 번호라도
    person(session, company(session, sid))
    block(session, SENTINEL_DIGITS)
    store.mark_do_not_contact(session, SENTINEL_PHONE, reason="전화하지 마세요")
    assert klass(session) == "outside_test"
    assert klass(session, None) == "outside_test"  # 번호 없는 전화도 허용 번호가 아니다
    assert klass(session, FOREIGN) == "outside_test"


def test_test_mode_lets_allowed_numbers_through_in_any_written_form(session, sid):
    connect(session, test_mode=True, allow_numbers_json=["+82 10-0000-0199", 7, None, "메모"])
    person(session, company(session, sid))
    assert klass(session, "01000000199") == "contact"
    assert klass(session, OTHER_PHONE) == "outside_test"


def test_broken_allow_list_allows_nobody(session, sid):
    connect(session, test_mode=True, allow_numbers_json={"01000000199": True})
    person(session, company(session, sid))
    assert klass(session) == "outside_test"


def test_block_beats_do_not_contact_internal_and_contact(session, sid):
    connect(session)
    account(session, "admin")
    person(session, company(session, sid), do_not_contact=True)
    block(session, SENTINEL_DIGITS)
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    assert caller == Caller("blocked", (), None)


def test_dnc_beats_internal_and_contact(session, sid):
    connect(session)
    account(session, "admin")
    row = person(session, company(session, sid))
    store.mark_do_not_contact(session, SENTINEL_PHONE, reason="전화하지 마세요")
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    assert caller.caller_class == "do_not_contact" and caller.user_id is None
    assert caller.candidates == (pair(row),)  # 메모를 어느 대화에 둘지 알 수 있게 짝은 남는다


def test_dnc_class_comes_from_number_store_not_contact_rows(session, sid, monkeypatch):
    connect(session)
    store.mark_do_not_contact(session, OTHER_PHONE, reason="그만")  # 주소록에 없는 번호
    assert klass(session, OTHER_PHONE) == "do_not_contact"
    block(session, "01000000001")  # 관리자 차단은 수신 거부가 아니다
    assert klass(session, "010-0000-0001") == "blocked"

    person(session, company(session, sid), do_not_contact=True)
    asked = []

    def spy(_session, number):
        asked.append(number)
        return False

    monkeypatch.setattr(store, "is_do_not_contact", spy)
    assert klass(session) == "contact"  # 줄의 표시를 따로 훑지 않고 그 함수의 답을 따른다
    assert asked == [SENTINEL_DIGITS]
    monkeypatch.setattr(store, "is_do_not_contact", lambda _session, _number: True)
    assert klass(session, "010-0000-0002") == "do_not_contact"


def test_internal_beats_contact(session, sid):
    connect(session)
    user = account(session, "admin", "+82 10 0000 0199")  # 계정의 번호는 정리해서 견준다
    person(session, company(session, sid))
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("internal", (), user.id)


def test_field_account_number_is_not_internal(session, sid):
    connect(session)
    account(session, "field")
    assert klass(session) == "unknown"
    person(session, company(session, sid))
    assert klass(session) == "contact"  # 주소록에 있으면 연락처일 뿐이다


@pytest.mark.parametrize("status", ["pending", "rejected", "disabled"])
def test_account_that_cannot_log_in_is_not_internal(session, status):
    connect(session)
    account(session, "user", status=status)
    assert klass(session) == "unknown"


def test_account_number_with_a_note_matches_nobody(session):
    connect(session)
    account(session, "user", "010-0000-0199 (휴대폰)")
    assert klass(session) == "unknown"


# ── 주소록에서 찾기 ─────────────────────────────────────────────────


def test_hidden_contact_counts_as_unknown(session, sid):
    connect(session)
    person(session, company(session, sid), hidden=True)
    person(session, company(session, sid, "숨긴건설", hidden=True), "박현장")  # 숨긴 협력사의 사람도 숨김이다
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("unknown", (), None)


def test_hidden_in_one_project_visible_in_another_is_one_contact(session, sid):
    connect(session)
    person(session, company(session, sid), hidden=True)
    shown = person(session, company(session, second_schedule(session)))
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("contact", (pair(shown),), None)


def test_hidden_person_next_to_a_visible_one_does_not_make_the_number_shared(session, sid):
    connect(session)
    firm = company(session, sid)
    shown = person(session, firm, "김공정")
    person(session, firm, "박현장", hidden=True)
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("contact", (pair(shown),), None)


def test_hidden_do_not_contact_person_still_makes_the_number_do_not_contact(session, sid):
    connect(session)
    person(session, company(session, sid), hidden=True, do_not_contact=True)
    assert door.resolve(session, SENTINEL_PHONE, now=NOW) == Caller("do_not_contact", (), None)


def test_number_marked_wrong_for_a_contact_does_not_speak_for_that_contact(session, sid):
    """「잘못된 번호」로 표시된 연락처의 번호로 걸어 온 사람은 그 연락처가 아니다."""
    connect(session)
    person(session, company(session, sid), phone_invalid=True)
    assert klass(session) == "unknown"


def test_two_candidates_in_one_schedule_is_shared_not_contact(session, sid):
    connect(session)
    a = person(session, company(session, sid, "가나건설"), "김공정")
    b = person(session, company(session, sid, "다라설비"), "박현장")
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    assert caller == Caller("shared", (pair(a), pair(b)), None)


def test_shared_in_one_project_stays_shared_when_the_number_is_also_elsewhere(session, sid):
    connect(session)
    firm = company(session, sid)
    rows = [person(session, firm, "김공정"), person(session, firm, "박현장"),
            person(session, company(session, second_schedule(session)), "김공정")]
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    assert caller == Caller("shared", tuple(pair(row) for row in rows), None)


@pytest.mark.parametrize("number", [REP_PHONE, SAFE_PHONE, LANDLINE])
def test_representative_and_050_numbers_are_classified_normally(session, sid, number):
    connect(session)
    assert klass(session, number) == "unknown"  # 주소록에 없으면 모르는 번호 — withheld 가 아니다
    row = person(session, company(session, sid), number=number)
    assert door.resolve(session, number, now=NOW) == Caller("contact", (pair(row),), None)


@pytest.mark.parametrize("number", [None, "", "   ", phone.NO_NUMBER, "anonymous", "1234", "+82", "+", 0])
def test_only_a_missing_number_is_withheld(session, number):
    connect(session)
    assert klass(session, number) == "withheld"


def test_no_number_marker_is_never_a_block_key(session):
    """phone.NO_NUMBER 는 번호 없는 모든 상대가 같이 쓰는 값이다 — 차단 목록에 그 글이 있어도 열쇠로 보지 않는다."""
    connect(session)
    block(session, phone.NO_NUMBER)
    assert klass(session, phone.NO_NUMBER) == "withheld"
    assert klass(session, None) == "withheld"


def test_foreign_number_is_unknown_and_never_meets_a_domestic_key(session, sid):
    connect(session)
    person(session, company(session, sid), number=REP_PHONE)  # 15880199
    account(session, "admin", "+1 212 000 0199")
    block(session, "15880199")
    assert door.number_key("+15880199") == "+15880199"  # 숫자만 남기면 국내 대표번호와 같아진다 — 그렇게 하지 않는다
    assert klass(session, "+15880199") == "unknown"  # 대표번호의 차단·연락처에 걸리지 않는다
    assert klass(session, FOREIGN) == "unknown"  # 계정에 적힌 나라 밖 번호도 내부가 아니다
    assert klass(session, "+1 212-000-0199") == "unknown"


def test_number_key_forms():
    assert door.number_key("+82 10-0000-0199") == door.number_key(SENTINEL_PHONE) == SENTINEL_DIGITS
    assert door.number_key("+1 212 000 0199") == door.number_key(FOREIGN) == FOREIGN
    for nothing in (None, "", phone.NO_NUMBER, "anonymous", "+0", "+8299", "12120000199", 7):
        assert door.number_key(nothing) is None


@pytest.mark.parametrize("medium", ["sms", "call"])
def test_same_class_for_both_media(session, sid, medium):
    connect(session)
    person(session, company(session, sid))
    person(session, company(session, second_schedule(session)))
    for number in (SENTINEL_PHONE, OTHER_PHONE, None):
        admitted = door.admit(session, medium, number, now=NOW, body="안녕하세요")
        assert admitted.caller == door.resolve(session, number, now=NOW)


# ── 범위 ────────────────────────────────────────────────────────────


def test_scope_of_each_class(session, sid):
    connect(session)
    row = person(session, company(session, sid))
    contact = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert contact == Scope("contact", (sid,), (pair(row),), True, "trade")
    assert (contact.facts, contact.personal, contact.site_required) == ("trade", True, False)

    for number, cls in ((OTHER_PHONE, "unknown"), (None, "withheld")):
        scope = door.scope_of(session, door.resolve(session, number, now=NOW))
        assert scope == Scope(cls, (), (), False, "none") and scope.facts == "none"

    user = account(session, "user", OTHER_PHONE)
    sid2 = second_schedule(session)
    internal = door.scope_of(session, door.resolve(session, OTHER_PHONE, now=NOW))
    assert internal == Scope("internal", (sid, sid2), (), False, "all")  # 그 계정이 볼 수 있는 일정 = 모든 일정
    assert internal.site_required and door.resolve(session, OTHER_PHONE, now=NOW).user_id == user.id

    other = person(session, company(session, sid2))
    multi = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert multi == Scope("contact_multi", (sid, sid2), (pair(row), pair(other)), True, "trade")
    assert multi.site_required is True

    third = person(session, company(session, sid2), "박현장")
    shared = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert shared.caller_class == "shared" and shared.candidates == (pair(row), pair(other), pair(third))
    assert shared.grant_personal is False and shared.pinned(sid).personal is False


def test_scopes_are_built_closed(session, sid):
    connect(session)
    sid2 = second_schedule(session)
    person(session, company(session, sid))
    person(session, company(session, sid2))
    multi = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert (multi.facts, multi.personal) == ("none", False)  # 현장을 고르기 전에는 사실도 본인 요청도 없다
    assert (multi.pinned(sid2).facts, multi.pinned(sid2).personal) == ("trade", True)
    assert multi.pinned(sid2).schedule_ids == (sid2,)

    account(session, "admin", OTHER_PHONE)
    internal = door.scope_of(session, door.resolve(session, OTHER_PHONE, now=NOW))
    assert (internal.facts, internal.personal) == ("none", False)
    assert (internal.pinned(sid).facts, internal.pinned(sid).personal) == ("all", False)


def test_internal_scope_with_one_schedule_or_none(session, sid):
    connect(session)
    account(session, "user")
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    one = door.scope_of(session, caller)
    assert one == Scope("internal", (sid,), (), False, "all") and one.facts == "all"


def test_internal_scope_without_any_schedule_sees_nothing(session):
    connect(session)
    account(session, "user")
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    assert caller.caller_class == "internal"
    with pytest.raises(ValueError):
        Scope("internal", (), (), False, "none")  # 빈 internal 범위는 타입이 받지 않는다 — Scope 안의 등급만 unknown
    scope = door.scope_of(session, caller)
    assert scope == Scope("unknown", (), (), False, "none") and scope.facts == "none"
    assert caller == Caller("internal", (), caller.user_id) and caller.user_id is not None  # 누구인지는 그대로 내부


@pytest.mark.parametrize("change", [{"status": "disabled"}, {"role": "field"}, None])
def test_internal_scope_is_closed_when_the_account_is_no_longer_internal(session, sid, change):
    connect(session)
    user = account(session, "user")
    caller = door.resolve(session, SENTINEL_PHONE, now=NOW)
    if change is None:
        caller = Caller("internal", (), None)  # 계정 없는 「내부」는 아무것도 보지 못한다
    else:
        for key, value in change.items():
            setattr(user, key, value)
        session.flush()
    assert door.scope_of(session, caller) == Scope("unknown", (), (), False, "none")


def test_shared_number_in_one_company_gets_the_company_scope_without_personal(session, sid):
    connect(session)
    firm = company(session, sid)
    person(session, firm, "김공정")
    person(session, firm, "박현장")
    scope = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert (scope.grant_facts, scope.facts, scope.personal) == ("trade", "trade", False)
    assert scope.company_ids == (firm.id,)


def test_shared_number_across_two_companies_gets_nothing(session, sid):
    connect(session)
    person(session, company(session, sid, "가나건설"), "김공정")
    person(session, company(session, sid, "다라설비"), "박현장")
    scope = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert (scope.caller_class, scope.grant_facts, scope.facts) == ("shared", "none", "none")
    assert scope.grant_personal is False and scope.personal is False and scope.company_ids == ()


def test_shared_number_mixed_in_any_project_gets_nothing_anywhere(session, sid):
    connect(session)
    sid2 = second_schedule(session)
    person(session, company(session, sid, "가나건설"), "김공정")
    person(session, company(session, sid, "다라설비"), "박현장")
    person(session, company(session, sid2), "김공정")
    scope = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert scope.grant_facts == "none" and scope.pinned(sid2).facts == "none"


def test_do_not_contact_scope_keeps_the_pair_but_shows_nothing(session, sid):
    connect(session)
    row = person(session, company(session, sid), do_not_contact=True)
    scope = door.scope_of(session, door.resolve(session, SENTINEL_PHONE, now=NOW))
    assert scope == Scope("do_not_contact", (sid,), (pair(row),), False, "none")
    assert (scope.facts, scope.personal) == ("none", False)


@pytest.mark.parametrize("cls", ["unknown", "withheld", "blocked", "outside_test"])
def test_classes_without_a_scope_get_an_empty_one_whatever_the_caller_carries(session, sid, cls):
    connect(session)
    row = person(session, company(session, sid))
    scope = door.scope_of(session, Caller(cls, (pair(row),), 1))  # 손으로 만든 상대가 짝을 달고 와도
    assert scope == Scope(cls, (), (), False, "none")
    assert scope.contact_ids == () and scope.company_ids == ()


def test_scope_of_refuses_the_outbound_class(session, sid):
    connect(session)
    row = person(session, company(session, sid))
    with pytest.raises(ValueError):
        door.scope_of(session, Caller("outbound", (pair(row),), None))


def test_scope_takes_nothing_but_the_caller():
    """범위를 넓힐 인자가 없다 — 모델이 준 현장·협력사·연락처 id 가 들어올 자리가 없다."""
    assert list(inspect.signature(door.scope_of).parameters) == ["session", "caller"]


def test_outbound_scope_is_trade_and_pinned(session, sid):
    connect(session)
    row = person(session, company(session, sid))
    person(session, company(session, second_schedule(session)))  # 같은 번호가 다른 일정에 있어도
    scope = door.outbound_scope(session, sid, row.id)
    assert scope == Scope("outbound", (sid,), (pair(row),), True, "trade")
    assert (scope.facts, scope.personal, scope.site_required) == ("trade", True, False)  # "all" 이 아니다


def test_outbound_scope_of_another_projects_contact_is_not_found(session, sid):
    connect(session)
    sid2 = second_schedule(session)
    row = person(session, company(session, sid))
    with pytest.raises(NotFound):
        door.outbound_scope(session, sid2, row.id)
    stray = Contact(schedule_id=sid, company_id=company(session, sid2).id, name="박현장")  # 협력사가 다른 일정 것
    session.add(stray)
    session.flush()
    with pytest.raises(NotFound):
        door.outbound_scope(session, sid, stray.id)
    other = Contact(schedule_id=sid2, company_id=company(session, sid, "다라건설").id, name="최현장")  # 사람이 다른 일정 것
    session.add(other)
    session.flush()
    with pytest.raises(NotFound):
        door.outbound_scope(session, sid, other.id)
    with pytest.raises(NotFound):
        door.outbound_scope(session, sid, other.id + 1000)  # 없는 연락처
