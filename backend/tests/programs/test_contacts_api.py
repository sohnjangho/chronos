"""주소록 API(계획 4 Task 72): 번호는 가린 꼴만 · 전체 번호는 reveal 한 곳(기록·캐시 금지) · 일정(프로젝트) 격리(다른
일정의 id 는 없는 id 와 같은 404) · 현장 관리자 403 · 입력 검사(번호 규칙은 phone 모듈 · 근무시간 · 성별·언어)."""

import json
import logging
from datetime import datetime

import pytest
from sqlalchemy import event, select

from app.core.model import CalendarSpec
from app.outreach import phone
from app.outreach.hours import KST
from app.programs.contacts import service
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactProposal,
    ContactReport,
    DoNotContactNumber,
    OutreachCall,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE, assert_clean

FIELD_NO = ("field_no_contacts", "현장 관리자는 연락처를 열 수 없습니다.")
BAD_PHONE = ("invalid_phone", "전화번호 형식이 맞지 않습니다.")
BAD_DAYS = ("invalid_hours", "근무 요일을 하나 이상 골라 주세요.")
BAD_TIME = ("invalid_hours", "시각은 HH:MM 으로 넣어 주세요.")
SAME_TIME = ("invalid_hours", "시작과 끝 시각이 같습니다. 끝나는 시각을 다르게 넣어 주세요.")
NOT_STORABLE = ("invalid_phone", "주소록에 둘 수 없는 번호입니다.")
SMS_ONLY_MOBILE = ("channel_not_possible", "문자는 휴대전화 번호로만 보낼 수 있습니다.")
NO_CALL = ("channel_not_possible", "이 번호로는 전화를 걸 수 없습니다.")
ADMIN_CLEARS = ("admin_only", "수신 거부는 관리자만 풀 수 있습니다(이 번호가 있는 모든 프로젝트에서 풀립니다).")
PREMIUM = "060-700-0199"  # 정보 이용 번호(가상) — phone.storable 이 거절
LANDLINE = "02-2000-0199"  # 유선(가상) — 문자 불가, 전화 가능
SAT_10 = datetime(2027, 3, 6, 10, 0, tzinfo=KST)  # 토요일 오전
BRIEF_KEYS = {"id", "name", "role_title", "company_id", "phone_masked", "has_phone", "phone_kind", "channels", "unread",
              "do_not_contact", "phone_invalid", "last_line", "hidden"}
DETAIL_KEYS = BRIEF_KEYS | {"hours", "working_now", "hours_label", "gender", "language", "voice_mode", "voice_id",
                            "dnc_reason", "note", "linked_activities"}


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/contacts{rest}"


def _company(client, headers, sid, **kw) -> int:
    r = client.post(_url(sid, "/companies"), json={"name": "가람건설", "trade": "골조", **kw}, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _person(client, headers, sid, company_id, **kw) -> dict:
    body = {"name": "김공정", "role_title": "공무", "company_id": company_id, "phone": SENTINEL_PHONE, **kw}
    r = client.post(_url(sid, "/people"), json=body, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()


def _message(session, sid, contact_id, body, direction="in", **kw) -> OutreachMessage:
    row = OutreachMessage(schedule_id=sid, contact_id=contact_id, direction=direction, channel="sms", body=body,
                          origin="peer" if direction == "in" else "user",
                          status="received" if direction == "in" else "delivered", **kw)
    session.add(row)
    session.commit()
    return row


def _people(body: dict) -> list[dict]:
    return [p for c in body["companies"] for p in c["people"]]


# ── 번호: 목록·상세·쓰기 응답은 가린 꼴만 ─────────────────────────────────────────────

def test_list_never_contains_full_number(client, user, session, sid):
    company = _company(client, user, sid)
    created = _person(client, user, sid, company)
    pid = created["id"]
    _message(session, sid, pid, f"제 번호는 {SENTINEL_PHONE} 입니다")

    responses = [
        client.get(_url(sid), headers=user),
        client.get(_url(sid, "?include_hidden=true"), headers=user),
        client.get(_url(sid, f"/people/{pid}"), headers=user),
        client.patch(_url(sid, f"/people/{pid}"), json={"note": "오전 통화"}, headers=user),
    ]

    assert all(r.status_code == 200 for r in responses), [r.json() for r in responses]
    for text in [json.dumps(created, ensure_ascii=False), *(r.text for r in responses)]:
        assert "0199" in text
        assert SENTINEL_DIGITS not in text and SENTINEL_PHONE not in text and "1000000199" not in text
    person = _people(responses[0].json())[0]
    assert (person["phone_masked"], person["has_phone"]) == ("010-****-0199", True)
    assert person["last_line"] == "제 번호는 [번호] 입니다"


def test_last_line_hides_numbers_before_cutting(client, user, session, sid):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    _message(session, sid, pid, "먼저 온 글")
    _message(session, sid, pid, "가" * 25 + SENTINEL_PHONE + " 로 연락 주세요")

    person = _people(client.get(_url(sid), headers=user).json())[0]

    assert person["last_line"] == ("가" * 25 + "[번호] 로 연락 주세요")[:30]
    assert "010" not in person["last_line"]  # 자른 뒤에 가리면 「010-0」 조각이 남는다


def test_person_without_number(client, user, sid):
    created = _person(client, user, sid, _company(client, user, sid), phone=None)

    assert (created["phone_masked"], created["has_phone"]) == (phone.NO_NUMBER, False)
    assert client.post(_url(sid, f"/people/{created['id']}/reveal"), headers=user).json() == {"phone": None}


# ── 보기(reveal): 한 곳 · 기록 · 캐시 금지 · 격리 ───────────────────────────────────

def test_reveal_is_scoped_logged_and_uncached(client, user, field_user, session, sid, sid2, caplog):
    caplog.set_level(logging.INFO)
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    uid = session.scalars(select(User).where(User.login_id == "user1")).one().id

    r = client.post(_url(sid, f"/people/{pid}/reveal"), headers=user)

    assert r.status_code == 200, r.json()
    assert r.json() == {"phone": SENTINEL_PHONE}
    assert r.headers["cache-control"] == "no-store"
    assert [m for m in caplog.messages if m.startswith("번호 보기")] == [f"번호 보기: 사용자 {uid} · 연락처 {pid}"]
    assert_clean(caplog)

    caplog.clear()
    other = client.post(_url(sid2, f"/people/{pid}/reveal"), headers=user)
    assert other.status_code == 404 and "0199" not in other.text
    assert client.get(_url(sid, f"/people/{pid}/reveal"), headers=user).status_code == 405
    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=field_user).status_code == 403
    assert not [m for m in caplog.messages if m.startswith("번호 보기")]  # 보지 못한 요청은 남기지 않는다


# ── 역할 ────────────────────────────────────────────────────────────────────────

def test_field_role_gets_403_everywhere(client, user, field_user, sid):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company)["id"]
    routes = [
        ("GET", _url(sid), None),
        ("GET", _url(sid, "?include_hidden=true"), None),
        ("POST", _url(sid, "/companies"), {"name": "나래전기"}),
        ("PATCH", _url(sid, f"/companies/{company}"), {"note": "메모"}),
        ("POST", _url(sid, "/people"), {"name": "이현장", "company_id": company}),
        ("GET", _url(sid, f"/people/{pid}"), None),
        ("PATCH", _url(sid, f"/people/{pid}"), {"note": "메모"}),
        ("POST", _url(sid, f"/people/{pid}/reveal"), None),
        ("POST", _url(sid, f"/people/{pid}/read"), None),
    ]

    for method, path, body in routes:
        r = client.request(method, path, json=body, headers=field_user)
        assert r.status_code == 403, (method, path, r.json())
        assert (r.json()["code"], r.json()["message"]) == FIELD_NO
        assert "0199" not in r.text


def test_login_is_required(client, sid):
    assert client.get(_url(sid)).status_code == 401


# ── 프로젝트 격리 ──────────────────────────────────────────────────────────────

def test_other_project_ids_are_404(client, user, session, sid, sid2):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company, note="처음 메모")["id"]
    company2 = _company(client, user, sid2, name="나래전기")
    cases = [  # (다른 일정 것인 id, 요청 만들기) — 같은 요청을 없는 id(99999)로도 보내 응답을 견준다
        (pid, lambda x: ("GET", _url(sid2, f"/people/{x}"), None)),
        (pid, lambda x: ("PATCH", _url(sid2, f"/people/{x}"), {"note": "바꿈"})),
        (pid, lambda x: ("POST", _url(sid2, f"/people/{x}/reveal"), None)),
        (pid, lambda x: ("POST", _url(sid2, f"/people/{x}/read"), None)),
        (company, lambda x: ("PATCH", _url(sid2, f"/companies/{x}"), {"note": "바꿈"})),
        (company, lambda x: ("POST", _url(sid2, "/people"), {"name": "이현장", "company_id": x})),
        (company2, lambda x: ("PATCH", _url(sid, f"/people/{pid}"), {"company_id": x})),  # 다른 일정 협력사로 옮기기
    ]

    for real, case in cases:
        method, path, body = case(real)
        other = client.request(method, path, json=body, headers=user)
        missing_method, missing_path, missing_body = case(99999)
        missing = client.request(missing_method, missing_path, json=missing_body, headers=user)
        assert other.status_code == 404, (method, path, other.json())
        assert other.json() == missing.json()  # 있는지 알려 주지 않는다
    assert client.get(_url(99999), headers=user).status_code == 404

    session.expire_all()
    row = session.get(Contact, pid)
    assert (row.schedule_id, row.company_id, row.note) == (sid, company, "처음 메모")
    assert _people(client.get(_url(sid2), headers=user).json()) == []


# ── 입력 검사 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["010-0000-019", "01O-0000-0199", "010-0000-0199 (휴대폰)"])
def test_bad_phone_error_does_not_echo_value(client, user, session, sid, raw, caplog):
    caplog.set_level(logging.DEBUG)
    company = _company(client, user, sid)

    created = client.post(_url(sid, "/people"), json={"name": "김공정", "company_id": company, "phone": raw},
                          headers=user)
    pid = _person(client, user, sid, company)["id"]
    patched = client.patch(_url(sid, f"/people/{pid}"), json={"phone": raw}, headers=user)

    for r in (created, patched):
        assert r.status_code == 422, r.json()
        assert (r.json()["code"], r.json()["message"]) == BAD_PHONE
        assert "0000" not in r.text and "019" not in r.text and "휴대폰" not in r.text
    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=user).json() == {"phone": SENTINEL_PHONE}
    assert len(_people(client.get(_url(sid), headers=user).json())) == 1
    assert_clean(caplog, raw)


def test_too_long_phone_is_422_without_value(client, user, sid):
    company = _company(client, user, sid)
    r = client.post(_url(sid, "/people"), json={"name": "김공정", "company_id": company, "phone": SENTINEL_PHONE * 4},
                    headers=user)
    assert r.status_code == 422 and "0000" not in r.text


def test_phone_rule_comes_from_the_phone_module(client, user, sid, monkeypatch):
    """주소록은 둘 수 있는 번호 규칙을 따로 두지 않는다 — phone.storable 이 받으면 받고, 거절하면 거절한다."""
    company = _company(client, user, sid)
    monkeypatch.setattr(phone, "storable", lambda number: phone.kind(number) == "premium")  # 규칙을 거꾸로

    accepted = client.post(_url(sid, "/people"), json={"name": "정보이용", "company_id": company, "phone": PREMIUM},
                           headers=user)
    refused = client.post(_url(sid, "/people"), json={"name": "김공정", "company_id": company, "phone": SENTINEL_PHONE},
                          headers=user)

    assert accepted.status_code == 201 and accepted.json()["has_phone"] is True
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_phone")


def test_premium_number_is_refused_like_a_bad_number(client, user, sid, caplog):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company)["id"]

    created = client.post(_url(sid, "/people"), json={"name": "정보이용", "company_id": company, "phone": PREMIUM},
                          headers=user)
    patched = client.patch(_url(sid, f"/people/{pid}"), json={"phone": PREMIUM}, headers=user)

    for r in (created, patched):
        assert r.status_code == 422, r.json()
        assert (r.json()["code"], r.json()["message"]) == NOT_STORABLE
        assert "0199" not in r.text and "700" not in r.text
    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=user).json() == {"phone": SENTINEL_PHONE}
    assert_clean(caplog, PREMIUM)


@pytest.mark.parametrize(("raw", "kind", "dashed", "channels"), [
    ("02-2000-0199", "landline", "02-2000-0199", ["kakao", "call"]),
    ("031-200-0199", "landline", "031-200-0199", ["kakao", "call"]),
    ("070-0000-0199", "internet", "070-0000-0199", ["kakao", "call"]),
    ("1588-0199", "rep", "1588-0199", ["kakao", "call"]),
    ("0507-2000-0199", "safe", "0507-2000-0199", ["kakao", "call"]),
    ("080-200-0199", "tollfree", "080-200-0199", ["kakao", "call"]),
    (SENTINEL_PHONE, "mobile", SENTINEL_PHONE, ["sms", "kakao", "call"]),
])
def test_every_storable_kind_is_kept_with_its_kind_and_channels(client, user, sid, raw, kind, dashed, channels):
    pid = _person(client, user, sid, _company(client, user, sid), phone=raw)["id"]

    listed = _people(client.get(_url(sid), headers=user).json())[0]
    detail = client.get(_url(sid, f"/people/{pid}"), headers=user).json()

    assert (listed["phone_kind"], detail["phone_kind"]) == (kind, kind)
    assert (listed["channels"], detail["channels"]) == (channels, channels)
    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=user).json() == {"phone": dashed}


@pytest.mark.parametrize(("raw", "dashed"), [("+82 1588 0199", "1588-0199"), ("02-1588-0000", "1588-0000"),
                                             ("1588-0199", "1588-0199")])
def test_representative_number_is_shown_with_a_dash_and_masked_to_its_prefix(client, user, sid, raw, dashed):
    pid = _person(client, user, sid, _company(client, user, sid), phone=raw)["id"]

    listed = _people(client.get(_url(sid), headers=user).json())[0]

    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=user).json() == {"phone": dashed}
    assert (listed["phone_kind"], listed["phone_masked"]) == ("rep", f"{dashed[:4]}-****")
    assert dashed[-4:] not in listed["phone_masked"]  # 가린 꼴은 앞 4자리(국번)만 — 끝 4자리는 보이지 않는다


def test_representative_dash_does_not_depend_on_the_mask_shape(client, user, sid, monkeypatch):
    pid = _person(client, user, sid, _company(client, user, sid), phone="1588-0199")["id"]
    monkeypatch.setattr(phone, "mask", lambda number: "대표번호")  # 줄표로 나눌 수 없는 가린 꼴

    assert client.post(_url(sid, f"/people/{pid}/reveal"), headers=user).json() == {"phone": "1588-0199"}


def _leaves(value) -> list[str]:
    """JSON 의 모든 키와 값(글로)."""
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in (str(k), *_leaves(v))]
    if isinstance(value, list):
        return [leaf for v in value for leaf in _leaves(v)]
    return [str(value)]


REFUSED_NUMBERS = [  # 번호 칸이 들어간 몸 — 422 몸 어디에도 그 숫자가 없어야 한다
    {"phone": PREMIUM},  # 둘 수 없는 060
    {"phone": "010-0000-019"},  # 틀린 꼴
    {"phone": "01O-0000-0199"},  # 숫자 아닌 글자
    {"phone": LANDLINE, "can_sms": True},  # 휴대전화가 아닌데 문자
    {"phone": SENTINEL_PHONE * 4},  # 너무 김(pydantic 검증 오류)
    {"phone": 1000000199},  # 글이 아님(pydantic 검증 오류)
]


@pytest.mark.parametrize("body", REFUSED_NUMBERS, ids=[str(b["phone"])[:16] for b in REFUSED_NUMBERS])
def test_no_422_body_carries_the_submitted_number(client, user, sid, body):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company, phone="010-0000-0198")["id"]
    digits = "".join(c for c in str(body["phone"]) if c.isdigit())

    created = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, **body}, headers=user)
    patched = client.patch(_url(sid, f"/people/{pid}"), json=body, headers=user)

    for r in (created, patched):
        assert r.status_code == 422, r.json()
        for leaf in _leaves(r.json()):  # code · message · detail(loc·msg·type) 모두
            leaf_digits = "".join(c for c in leaf if c.isdigit())
            assert digits not in leaf_digits and digits[-4:] not in leaf_digits and digits[1:] not in leaf_digits, leaf


# ── 채널은 번호 종류를 따른다(phone.can_sms · phone.can_call) ────────────────────

def test_person_without_number_gets_no_sms_or_call(client, user, sid):
    created = _person(client, user, sid, _company(client, user, sid), phone=None)

    assert (created["phone_kind"], created["channels"]) == (None, ["kakao"])


@pytest.mark.parametrize("body", [{"phone": LANDLINE, "can_sms": True}, {"phone": None, "can_sms": True}])
def test_sms_on_a_number_that_cannot_take_texts_is_422(client, user, sid, body):
    company = _company(client, user, sid)
    landline = _person(client, user, sid, company, name="박유선", phone=LANDLINE)["id"]
    mobile = _person(client, user, sid, company)["id"]

    created = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, **body}, headers=user)
    asked = client.patch(_url(sid, f"/people/{landline}"), json={"can_sms": True}, headers=user)
    moved = client.patch(_url(sid, f"/people/{mobile}"), json=body, headers=user)

    for r in (created, asked, moved):
        assert r.status_code == 422, r.json()
        assert (r.json()["code"], r.json()["message"]) == SMS_ONLY_MOBILE
        assert "0199" not in r.text
    detail = client.get(_url(sid, f"/people/{mobile}"), headers=user).json()
    assert (detail["phone_kind"], detail["channels"]) == ("mobile", ["sms", "kakao", "call"])


def test_call_flag_follows_phone_can_call(client, user, sid, monkeypatch):
    company = _company(client, user, sid)
    monkeypatch.setattr(phone, "can_call", lambda number: False)

    asked = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, "phone": SENTINEL_PHONE,
                                                    "can_call": True}, headers=user)
    defaulted = _person(client, user, sid, company)

    assert (asked.status_code, asked.json()["code"], asked.json()["message"]) == (422, *NO_CALL)
    assert defaulted["channels"] == ["sms", "kakao"]


def test_new_number_resets_channel_flags_but_same_number_does_not(client, user, sid):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]

    def patch(body: dict) -> list[str]:
        r = client.patch(_url(sid, f"/people/{pid}"), json=body, headers=user)
        assert r.status_code == 200, r.json()
        return r.json()["channels"]

    assert patch({"can_call": False}) == ["sms", "kakao"]
    assert patch({"phone": SENTINEL_DIGITS}) == ["sms", "kakao"]  # 같은 번호 — 손으로 끈 것을 그대로
    assert patch({"phone": LANDLINE}) == ["kakao", "call"]  # 새 번호 — 번호 종류대로
    assert patch({"phone": "010-0000-0198", "can_call": False}) == ["sms", "kakao"]  # 보낸 칸은 보낸 대로
    assert patch({"phone": None}) == ["kakao"]


# ── 수신 거부는 번호 기준(store.outreach 의 세 함수) ───────────────────────────────

def test_do_not_contact_is_read_by_number(client, user, session, sid, sid2):
    company, company2 = _company(client, user, sid), _company(client, user, sid2, name="나래전기")
    marked = _person(client, user, sid, company, name="가번호")["id"]  # 번호 기준 표시만
    elsewhere = _person(client, user, sid, company, name="나다른", phone="010-0000-0198")["id"]
    flagged = _person(client, user, sid2, company2, name="다른일정", phone="010-0000-0198")["id"]
    clean = _person(client, user, sid, company, name="라없음", phone="010-0000-0197")["id"]
    no_number = _person(client, user, sid, company, name="마번호없음", phone=None, do_not_contact=True)["id"]
    outreach.mark_do_not_contact(session, SENTINEL_PHONE, reason="번호 기준")
    session.get(Contact, flagged).do_not_contact = True  # 다른 일정의 연락처 표시만(번호 기준 줄 없음)
    session.commit()

    listed = {p["id"]: p["do_not_contact"] for p in _people(client.get(_url(sid), headers=user).json())}
    detailed = {pid: client.get(_url(sid, f"/people/{pid}"), headers=user).json()["do_not_contact"] for pid in listed}

    assert listed == detailed == {marked: True, elsewhere: True, clean: False, no_number: True}
    session.expire_all()
    for pid, shown in listed.items():
        row = session.get(Contact, pid)
        assert shown == (row.do_not_contact or (row.phone is not None and outreach.is_do_not_contact(session, row.phone)))


def test_setting_do_not_contact_marks_the_number(client, user, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    other = _person(client, user, sid2, _company(client, user, sid2), name="다른일정")["id"]
    created = _person(client, user, sid, _company(client, user, sid, name="나래전기"), name="새사람",
                      phone="010-0000-0198", do_not_contact=True, dnc_reason="처음부터")

    r = client.patch(_url(sid, f"/people/{pid}"), json={"do_not_contact": True, "dnc_reason": "본인 요청"}, headers=user)

    assert r.status_code == 200 and r.json()["do_not_contact"] is True
    assert created["do_not_contact"] is True
    session.expire_all()
    reasons = dict(session.execute(select(DoNotContactNumber.number, DoNotContactNumber.reason)).all())
    assert reasons == {SENTINEL_DIGITS: "본인 요청", "01000000198": "처음부터"}
    assert session.get(Contact, pid).do_not_contact is True
    assert client.get(_url(sid2, f"/people/{other}"), headers=user).json()["do_not_contact"] is True  # 같은 번호


def test_clearing_do_not_contact_is_admin_only_and_clears_everywhere(client, user, admin, session, sid, sid2):
    pid = _person(client, user, sid, _company(client, user, sid), do_not_contact=True, dnc_reason="본인 요청")["id"]
    other = _person(client, user, sid2, _company(client, user, sid2), name="다른일정", do_not_contact=True)["id"]
    plain = _person(client, user, sid, _company(client, user, sid, name="나래전기"), name="보통",
                    phone="010-0000-0198")["id"]
    number_only = _person(client, user, sid, _company(client, user, sid, name="다온설비"), name="번호만",
                          phone="010-0000-0197")["id"]
    outreach.mark_do_not_contact(session, "010-0000-0197", reason="번호 기준")
    session.commit()

    refused = [client.patch(_url(sid, f"/people/{x}"), json={"do_not_contact": False}, headers=user)
               for x in (pid, number_only)]
    no_op = client.patch(_url(sid, f"/people/{plain}"), json={"do_not_contact": False}, headers=user)

    for r in refused:
        assert r.status_code == 403, r.json()
        assert (r.json()["code"], r.json()["message"]) == ADMIN_CLEARS
    assert no_op.status_code == 200
    session.expire_all()
    assert outreach.is_do_not_contact(session, SENTINEL_PHONE) and outreach.is_do_not_contact(session, "010-0000-0197")

    cleared = [client.patch(_url(sid, f"/people/{x}"), json={"do_not_contact": False}, headers=admin)
               for x in (pid, number_only)]

    assert [(r.status_code, r.json()["do_not_contact"], r.json()["dnc_reason"]) for r in cleared] == [(200, False, None)] * 2
    session.expire_all()
    assert not outreach.is_do_not_contact(session, SENTINEL_PHONE)
    assert not outreach.is_do_not_contact(session, "010-0000-0197")
    assert client.get(_url(sid2, f"/people/{other}"), headers=user).json()["do_not_contact"] is False


def test_list_query_count_does_not_grow_with_people(client, user, session, sid):
    company = _company(client, user, sid)
    statements: list[str] = []

    def count(*args) -> None:
        statements.append(args[2])

    def add(numbers: range) -> None:
        for i in numbers:
            _person(client, user, sid, company, name=f"사람{i}", phone=f"010-0000-{1000 + i}", do_not_contact=i % 2 == 0)

    def list_queries() -> int:
        statements.clear()
        event.listen(session.get_bind(), "before_cursor_execute", count)
        try:
            assert client.get(_url(sid), headers=user).status_code == 200
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", count)
        return len(statements)

    add(range(2))
    few = list_queries()
    add(range(2, 12))

    assert list_queries() == few


def test_new_number_clears_wrong_number_flag(client, user, session, sid):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    session.get(Contact, pid).phone_invalid = True
    session.commit()

    note = client.patch(_url(sid, f"/people/{pid}"), json={"note": "메모"}, headers=user).json()
    same = client.patch(_url(sid, f"/people/{pid}"), json={"phone": SENTINEL_DIGITS}, headers=user).json()
    new = client.patch(_url(sid, f"/people/{pid}"), json={"phone": "010-0000-0198"}, headers=user).json()

    assert (note["phone_invalid"], same["phone_invalid"], new["phone_invalid"]) == (True, True, False)
    assert new["phone_masked"] == "010-****-0198"


def test_empty_phone_clears_number(client, user, sid):
    pid = _person(client, user, sid, _company(client, user, sid))["id"]
    for value in ("", None):
        r = client.patch(_url(sid, f"/people/{pid}"), json={"phone": SENTINEL_PHONE}, headers=user)
        r = client.patch(_url(sid, f"/people/{pid}"), json={"phone": value}, headers=user)
        assert r.status_code == 200 and r.json()["has_phone"] is False


def test_hours_gender_language_roundtrip(client, user, admin, sid):
    company = _company(client, user, sid)
    sent = {"hours": {"days": [4, 0, 2, 0], "start": "07:30", "end": "17:00"}, "gender": "female", "language": "vi",
            "voice_mode": "manual", "voice_id": "voice-a", "can_kakao": False, "do_not_contact": True,
            "dnc_reason": "본인 요청", "note": "오전 통화 선호"}
    pid = _person(client, user, sid, company, **sent)["id"]

    detail = client.get(_url(sid, f"/people/{pid}"), headers=user).json()

    assert set(detail) == DETAIL_KEYS
    assert detail["hours"] == {"days": [0, 2, 4], "start": "07:30", "end": "17:00"}
    assert {k: detail[k] for k in sent if k != "hours" and k != "can_kakao"} == {
        k: v for k, v in sent.items() if k not in ("hours", "can_kakao")}
    assert detail["channels"] == ["sms", "call"]

    back = client.patch(_url(sid, f"/people/{pid}"),
                        json={"hours": None, "gender": "male", "language": "ko", "voice_mode": "auto", "voice_id": None,
                              "can_kakao": True, "do_not_contact": False, "dnc_reason": None}, headers=admin).json()
    assert (back["hours"], back["gender"], back["language"], back["voice_mode"], back["voice_id"]) == (
        None, "male", "ko", "auto", None)
    assert (back["channels"], back["do_not_contact"], back["dnc_reason"]) == (["sms", "kakao", "call"], False, None)


@pytest.mark.parametrize("bad", [{"gender": "other"}, {"gender": "남"}, {"language": "jp"}, {"language": "KO"},
                                 {"voice_mode": "pick"}, {"name": None}, {"name": ""}, {"company_id": None},
                                 {"can_kakao": None}, {"note": None}, {"phone_invalid": False}, {"schedule_id": 2}])
def test_fixed_sets_and_required_fields(client, user, sid, bad):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company)["id"]

    patched = client.patch(_url(sid, f"/people/{pid}"), json=bad, headers=user)
    created = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, **bad}, headers=user)

    assert (patched.status_code, created.status_code) == (422, 422), (patched.json(), created.json())


HOURS_BAD = [
    ({"days": [], "start": "08:00", "end": "18:00"}, BAD_DAYS),
    ({"days": [7], "start": "08:00", "end": "18:00"}, BAD_DAYS),
    ({"days": [-1, 0], "start": "08:00", "end": "18:00"}, BAD_DAYS),
    ({"days": [0], "start": "8시", "end": "18:00"}, BAD_TIME),
    ({"days": [0], "start": "08:00", "end": "25:00"}, BAD_TIME),
    ({"days": [0], "start": "8:00", "end": "18:00"}, BAD_TIME),
    ({"days": [0], "start": "08:00", "end": "24:00"}, BAD_TIME),
    ({"days": [0], "start": "08:00", "end": "18:60"}, BAD_TIME),
    ({"days": [0], "start": "08:00:00", "end": "18:00"}, BAD_TIME),
    ({"days": [0], "start": "09:00", "end": "09:00"}, SAME_TIME),
]


@pytest.mark.parametrize(("hours", "why"), HOURS_BAD, ids=[json.dumps(h, ensure_ascii=False) for h, _ in HOURS_BAD])
def test_empty_days_and_bad_times_are_rejected(client, user, session, sid, hours, why):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company, hours={"days": [0, 1], "start": "08:00", "end": "17:00"})["id"]

    created = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, "hours": hours},
                          headers=user)
    patched = client.patch(_url(sid, f"/people/{pid}"), json={"hours": hours}, headers=user)

    for r in (created, patched):
        assert r.status_code == 422, r.json()
        assert (r.json()["code"], r.json()["message"]) == why
    session.expire_all()
    assert session.get(Contact, pid).hours_json == {"days": [0, 1], "start": "08:00", "end": "17:00"}


@pytest.mark.parametrize("hours", [{"days": [0], "start": "08:00"}, {"days": ["월"], "start": "08:00", "end": "18:00"},
                                   {"days": [True], "start": "08:00", "end": "18:00"},
                                   {"days": [0], "start": 8, "end": "18:00"},
                                   {"days": [0], "start": "08:00", "end": "18:00", "tz": "UTC"}])
def test_malformed_hours_are_422(client, user, sid, hours):
    company = _company(client, user, sid)
    r = client.post(_url(sid, "/people"), json={"name": "이현장", "company_id": company, "hours": hours}, headers=user)
    assert r.status_code == 422, r.json()


def test_hours_null_means_project_default(client, user, sid):
    company = _company(client, user, sid)
    created = _person(client, user, sid, company, hours=None)
    overnight = _person(client, user, sid, company, name="박야간", hours={"days": [0], "start": "22:00", "end": "06:00"})

    assert created["hours"] is None
    assert overnight["hours"] == {"days": [0], "start": "22:00", "end": "06:00"}


# ── 숨김 ───────────────────────────────────────────────────────────────────────

def test_hidden_person_leaves_list_but_keeps_history(client, user, session, sid):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company)["id"]
    _message(session, sid, pid, "자재 반입 확인했습니다")

    hidden = client.patch(_url(sid, f"/people/{pid}"), json={"hidden": True}, headers=user)

    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    assert _people(client.get(_url(sid), headers=user).json()) == []
    shown = _people(client.get(_url(sid, "?include_hidden=true"), headers=user).json())
    assert [(p["id"], p["hidden"], p["last_line"]) for p in shown] == [(pid, True, "자재 반입 확인했습니다")]
    assert client.get(_url(sid, f"/people/{pid}"), headers=user).status_code == 200
    assert session.scalars(select(OutreachMessage).where(OutreachMessage.contact_id == pid)).one().body
    client.patch(_url(sid, f"/people/{pid}"), json={"hidden": False}, headers=user)
    assert [p["id"] for p in _people(client.get(_url(sid), headers=user).json())] == [pid]


def test_company_create_patch_and_hide(client, user, sid):
    r = client.post(_url(sid, "/companies"), json={"name": "가람건설", "trade": "골조", "note": "본사"}, headers=user)
    assert r.status_code == 201
    company = r.json()
    assert company == {"id": company["id"], "name": "가람건설", "trade": "골조", "note": "본사", "hidden": False}
    _person(client, user, sid, company["id"])

    patched = client.patch(_url(sid, f"/companies/{company['id']}"), json={"name": "가람종합건설", "hidden": True},
                           headers=user)

    assert patched.status_code == 200
    assert (patched.json()["name"], patched.json()["hidden"]) == ("가람종합건설", True)
    assert client.get(_url(sid), headers=user).json()["companies"] == []
    everyone = client.get(_url(sid, "?include_hidden=true"), headers=user).json()["companies"]
    assert [(c["name"], len(c["people"])) for c in everyone] == [("가람종합건설", 1)]
    for bad in ({"name": None}, {"name": ""}, {"trade": None}, {"hidden": None}, {"schedule_id": 1}):
        assert client.patch(_url(sid, f"/companies/{company['id']}"), json=bad, headers=user).status_code == 422
    assert client.post(_url(sid, "/companies"), json={"trade": "골조"}, headers=user).status_code == 422


# ── 목록 묶음·셈 ────────────────────────────────────────────────────────────────

def test_list_groups_by_company_and_counts_this_project_only(client, user, session, sid, sid2):
    electric = _company(client, user, sid, name="나래전기", trade="전기")
    frame = _company(client, user, sid, name="가람건설")
    _company(client, user, sid, name="다온설비")
    _person(client, user, sid, electric, name="이전기")
    _person(client, user, sid, frame, name="김공정", can_sms=False)
    session.add_all([
        ContactProposal(schedule_id=sid, kind="new"),
        ContactProposal(schedule_id=sid, kind="new", status="accepted"),
        ContactProposal(schedule_id=sid2, kind="new"),
        ContactProposal(schedule_id=None, kind="new"),
        ContactReport(schedule_id=sid, medium="sms", kind="delay"),
        ContactReport(schedule_id=sid, medium="call", kind="delay", status="reviewed"),
        ContactReport(schedule_id=sid2, medium="sms", kind="delay"),
    ])
    session.commit()

    body = client.get(_url(sid), headers=user).json()

    assert (body["proposals_pending"], body["reports_open"]) == (1, 1)
    assert [(c["name"], [p["name"] for p in c["people"]]) for c in body["companies"]] == [
        ("가람건설", ["김공정"]), ("나래전기", ["이전기"]), ("다온설비", [])]
    assert set(body["companies"][0]) == {"id", "name", "trade", "note", "hidden", "people"}
    first = body["companies"][0]["people"][0]
    assert set(first) == BRIEF_KEYS
    assert (first["channels"], first["unread"], first["last_line"], first["company_id"]) == (
        ["kakao", "call"], 0, None, frame)


# ── 읽음 ───────────────────────────────────────────────────────────────────────

def test_unread_counts_inbound_and_read_clears_only_this_person(client, user, session, sid, sid2):
    company = _company(client, user, sid)
    a = _person(client, user, sid, company)["id"]
    b = _person(client, user, sid, company, name="이현장", phone=None)["id"]
    _message(session, sid, a, "첫 답")
    _message(session, sid, a, "둘째 답")
    _message(session, sid, a, "보낸 글", direction="out")
    _message(session, sid, b, "다른 사람 답")
    stray = _message(session, sid2, a, "다른 일정 줄")

    before = {p["id"]: p["unread"] for p in _people(client.get(_url(sid), headers=user).json())}
    first = client.post(_url(sid, f"/people/{a}/read"), headers=user)
    again = client.post(_url(sid, f"/people/{a}/read"), headers=user)
    after = {p["id"]: p["unread"] for p in _people(client.get(_url(sid), headers=user).json())}

    assert before == {a: 2, b: 1}
    assert (first.json(), again.json()) == ({"read": 2}, {"read": 0})
    assert after == {a: 0, b: 1}
    session.expire_all()
    assert session.get(OutreachMessage, stray.id).read_at is None


# ── 근무시간 ────────────────────────────────────────────────────────────────────

def test_working_now_uses_project_calendar_when_hours_empty(client, user, session, sid, monkeypatch):
    monkeypatch.setattr(service, "_now", lambda: SAT_10)
    sid6 = schedules.store(session, schedules.make([schedules.task("A", 3)], cal=CalendarSpec(days_per_week=6)))
    five = _person(client, user, sid, _company(client, user, sid))["id"]
    six = _person(client, user, sid6, _company(client, user, sid6))["id"]
    weekend = _person(client, user, sid, _company(client, user, sid, name="나래전기"), name="박주말",
                      hours={"days": [5], "start": "09:00", "end": "12:00"})["id"]

    got = {pid: client.get(_url(s, f"/people/{pid}"), headers=user).json() for s, pid in
           ((sid, five), (sid6, six), (sid, weekend))}

    assert (got[five]["working_now"], got[five]["hours_label"]) == (False, "근무 밖 · 월 08:00 부터")
    assert (got[six]["working_now"], got[six]["hours_label"]) == (True, "근무 중 · 18:00 까지")
    assert (got[weekend]["working_now"], got[weekend]["hours_label"]) == (True, "근무 중 · 12:00 까지")


# ── 맡은 작업 ───────────────────────────────────────────────────────────────────

def test_linked_activities_come_from_this_persons_messages_and_calls(client, user, session, sid):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company)["id"]
    other = _person(client, user, sid, company, name="이현장")["id"]
    _message(session, sid, pid, "B 일정 확인 부탁드립니다", direction="out", activity_id="B")
    _message(session, sid, pid, "지운 작업", direction="out", activity_id="GONE")
    _message(session, sid, other, "A 확인", direction="out", activity_id="A")
    session.add(OutreachCall(schedule_id=sid, contact_id=pid, origin="user", activity_id="A"))
    session.add(OutreachCall(schedule_id=sid, contact_id=pid, origin="user", activity_id="B"))
    session.commit()

    detail = client.get(_url(sid, f"/people/{pid}"), headers=user).json()

    assert detail["linked_activities"] == [{"id": "A", "name": "작업 A"}, {"id": "B", "name": "작업 B"}]
    assert client.get(_url(sid, f"/people/{other}"), headers=user).json()["linked_activities"] == [
        {"id": "A", "name": "작업 A"}]
