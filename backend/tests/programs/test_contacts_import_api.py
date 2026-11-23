"""CSV 가져오기(미리 보기)·다른 프로젝트에서 복사(계획 4 Task 76).

- 가져오기는 주소록 입력과 같은 검사(service.check_phone·check_channels·check_hours·check_texts·check_voice)를 쓴다.
- 미리 보기는 아무것도 쓰지 않고, 넣기(dry_run=0)는 파일을 처음부터 다시 검사해 한 트랜잭션으로 넣는다.
- 번호는 가린 꼴만 나가고, 오류 글·로그에는 번호도 셀 값도 없다(로그는 셈만).
- 복사는 관리자만. 다른(셋째) 프로젝트의 id 는 없는 id 와 같은 404. 수신 거부는 번호 기준 그대로 따라간다."""

import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.outreach import phone
from app.programs.contacts import csv_import
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import Contact, ContactCompany, DoNotContactNumber
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE, assert_clean

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contacts"
HEADER = "협력사,이름,담당,전화번호\n"
LINE_TEXT = ("invalid_text", "이름·담당·공종에는 줄 바꿈이나 보이지 않는 제어 글자를 쓸 수 없습니다.")
FREE_TEXT = ("invalid_text", "메모·까닭에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다.")
NOT_STORABLE = ("invalid_phone", "주소록에 둘 수 없는 번호입니다.")
BAD_PHONE = ("invalid_phone", "전화번호 형식이 맞지 않습니다.")
ROW_KEYS = {"n", "company", "name", "role_title", "phone_shown", "phone_kind", "do_not_contact", "result", "reason",
            "code", "column", "skipped"}


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


def _csv(*lines: str, header: str = HEADER) -> bytes:
    return (header + "".join(line + "\n" for line in lines)).encode("utf-8")


def _import(client, headers, sid, content: bytes, *, dry_run: int = 1, skip=None, name: str = "list.csv"):
    data = {"skip": [str(n) for n in skip]} if skip else None
    return client.post(_url(sid, f"/import?dry_run={dry_run}"), files={"file": (name, content, "text/csv")},
                       data=data, headers=headers)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _company(client, headers, sid, name="대한골조", trade="골조") -> int:
    r = client.post(_url(sid, "/companies"), json={"name": name, "trade": trade}, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _person(client, headers, sid, company_id, **kw) -> dict:
    body = {"name": "박현장", "role_title": "골조 팀장", "company_id": company_id, "phone": "010-0000-0000", **kw}
    r = client.post(_url(sid, "/people"), json=body, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()


def _people(client, headers, sid) -> list[dict]:
    body = client.get(_url(sid, "?include_hidden=true"), headers=headers).json()
    return [p | {"company": c["name"]} for c in body["companies"] for p in c["people"]]


def _counts(session) -> tuple[int, int, int]:
    session.expire_all()
    return tuple(session.scalar(select(func.count()).select_from(t)) for t in (Contact, ContactCompany,
                                                                                DoNotContactNumber))


def _by_n(body: dict) -> dict[int, dict]:
    return {row["n"]: row for row in body["rows"]}


# ── 미리 보기 ───────────────────────────────────────────────────────────────────

def test_preview_writes_nothing(client, user, sid, session):
    _person(client, user, sid, _company(client, user, sid))
    before = _counts(session)

    r = _import(client, user, sid, _fixture("utf8.csv"))

    assert r.status_code == 200, r.json()
    assert _counts(session) == before  # 없는 협력사(우리설비·한빛전기)도 만들지 않는다
    assert {c["name"] for c in client.get(_url(sid), headers=user).json()["companies"]} == {"대한골조"}


def test_import_preview_masks_all_numbers(client, user, sid):
    content = _csv(
        f"우리설비,김설비,설비 소장,{SENTINEL_PHONE}",
        "우리설비,오배관,배관 기사,010-00-0199",  # 틀린 번호 — 앞 두 글자만
        f"우리설비,이름{SENTINEL_PHONE},공무,",  # 이름에 적힌 번호도 가린다
        "우리설비,정정보,공무,060-700-0199",
    )

    r = _import(client, user, sid, content)

    assert r.status_code == 200, r.json()
    assert SENTINEL_DIGITS not in r.text.replace("-", "") and "0000" not in r.text
    rows = _by_n(r.json())
    assert all(set(row) == ROW_KEYS for row in rows.values())
    assert (rows[2]["phone_shown"], rows[2]["phone_kind"], rows[2]["result"]) == ("010-****-0199", "mobile", "new")
    assert (rows[3]["phone_shown"], rows[3]["result"]) == (phone.mask_bad("010-00-0199"), "bad_phone")
    assert rows[3]["phone_shown"] == "01…"
    assert rows[4]["name"] == "이름[번호]" and rows[4]["result"] == "no_phone"
    assert rows[4]["phone_shown"] == phone.NO_NUMBER
    assert (rows[5]["result"], rows[5]["code"], rows[5]["reason"]) == ("bad_phone", *NOT_STORABLE)


def test_results_match_mockup_cases(client, user, sid):
    _person(client, user, sid, _company(client, user, sid))  # 대한골조 박현장 010-0000-0000

    r = _import(client, user, sid, _fixture("utf8.csv"))  # 머리줄 차례가 다르다(이름이 먼저)

    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["summary"] == {"new": 1, "no_phone": 1, "exists": 1, "bad": 1, "skipped": 0}
    got = [(row["n"], row["company"], row["name"], row["role_title"], row["phone_shown"], row["result"])
           for row in body["rows"]]
    assert got == [
        (2, "우리설비", "김설비", "설비 소장", "010-****-0222", "new"),
        (3, "우리설비", "오배관", "배관 기사", phone.NO_NUMBER, "no_phone"),
        (4, "대한골조", "박현장", "골조 팀장", "010-****-0000", "exists"),
        (5, "한빛전기", "이전기", "전기 과장", "01…", "bad_phone"),
    ]
    assert (body["rows"][3]["code"], body["rows"][3]["reason"]) == BAD_PHONE


def test_cp949_file_is_read(client, user, sid):
    r = _import(client, user, sid, _fixture("cp949.csv"), dry_run=0)

    assert r.status_code == 200, r.json()
    assert r.json()["summary"] == {"new": 2, "no_phone": 0, "exists": 0, "bad": 0, "skipped": 0}
    people = _people(client, user, sid)
    assert {(p["company"], p["name"], p["role_title"]) for p in people} == {
        ("한빛전기", "이전기", "전기 과장"), ("한빛전기", "최배선", "배선 기사")}


def test_import_uses_the_same_validators_as_the_form(client, user, sid, monkeypatch):
    r = _import(client, user, sid, _fixture("bad.csv"), dry_run=0)

    assert r.status_code == 200, r.json()
    rows = _by_n(r.json())
    assert (rows[2]["result"], rows[2]["phone_kind"]) == ("new", "landline")  # 유선 → 넣되 문자·카카오톡은 꺼짐
    assert (rows[3]["result"], rows[3]["code"], rows[3]["reason"]) == ("bad_phone", *NOT_STORABLE)  # 060
    assert (rows[4]["result"], rows[4]["code"], rows[4]["reason"], rows[4]["column"]) == ("bad_row", *LINE_TEXT, "이름")
    assert rows[4]["name"] is None and "\u202e" not in r.text and "\\u202e" not in r.text.lower()  # 걸린 값은 되돌리지 않음
    assert (rows[5]["result"], rows[5]["role_title"]) == ("new", "=1+2")  # 수식처럼 생긴 칸은 글 그대로
    assert (rows[6]["result"], rows[6]["code"], rows[6]["reason"], rows[6]["column"]) == ("bad_row", *FREE_TEXT, "메모")
    people = {p["name"]: p for p in _people(client, user, sid)}
    assert set(people) == {"최유선", "한수식"}
    assert (people["최유선"]["channels"], people["최유선"]["phone_kind"]) == (["call"], "landline")
    assert people["한수식"]["role_title"] == "=1+2" and people["한수식"]["channels"] == ["sms", "kakao", "call"]

    # 번호 규칙은 phone 모듈 한 곳 — 바꿔 끼우면 가져오기도 따라간다(주소록 입력과 같은 함수)
    monkeypatch.setattr(phone, "storable", lambda number: False)
    again = _by_n(_import(client, user, sid, _csv("가람건설,새사람,공무,010-0000-0190")).json())
    assert (again[2]["result"], again[2]["code"], again[2]["reason"]) == ("bad_phone", *NOT_STORABLE)


def test_row_checks_match_the_form_rules(client, user, sid):
    content = _csv(
        ",이름만,공무,",  # 협력사 비었음
        "가람건설,,공무,",  # 이름 비었음
        "가람건설," + "가" * 101 + ",공무,",  # 너무 긴 이름
        "가람건설,김성별,공무,,모름",  # 성별
        "가람건설,김언어,공무,,,일본어",  # 언어
        "가람\x01건설,김협력,공무,",  # 협력사 이름에 제어 글자
        "가람건설,김공종,공무,,,,골\u200b조",  # 공종(협력사 칸)에 폭 없는 글자
        "가람건설,김정상,공무,,여,영어,,\"두 줄\n메모\"",
        header="협력사,이름,담당,전화번호,성별,언어,공종,메모\n",
    )

    r = _import(client, user, sid, content, dry_run=0)

    assert r.status_code == 200, r.json()
    rows = _by_n(r.json())
    got = {n: (row["result"], row["code"], row["column"]) for n, row in rows.items()}
    assert got == {
        2: ("bad_row", "missing_value", "협력사"),
        3: ("bad_row", "missing_value", "이름"),
        4: ("bad_row", "too_long", "이름"),
        5: ("bad_row", "invalid_gender", "성별"),
        6: ("bad_row", "invalid_language", "언어"),
        7: ("bad_row", "invalid_text", "협력사"),
        8: ("bad_row", "invalid_text", "공종"),
        9: ("no_phone", None, None),
    }
    assert rows[4]["name"] is None and rows[5]["name"] == "김성별"
    assert "모름" not in r.text and "일본어" not in r.text and "\x01" not in r.text
    person = next(p for p in _people(client, user, sid) if p["name"] == "김정상")
    detail = client.get(_url(sid, f"/people/{person['id']}"), headers=user).json()
    assert (detail["gender"], detail["language"], detail["note"], detail["channels"]) == (
        "female", "en", "두 줄\n메모", [])


def test_exists_is_decided_on_the_normalised_number_and_on_company_and_name(client, user, sid, session):
    _person(client, user, sid, _company(client, user, sid), phone="010-0000-0000")
    content = _csv(
        "다른회사,다른이름,공무,+82 10-0000-0000",  # 같은 번호, 다른 꼴
        "대한골조,박현장,공무,",  # 같은 협력사·이름(번호 없음)
        "우리설비,김하나,공무,010-0000-0211",
        "우리설비,김둘,공무,01000000211",  # 이 파일 앞 행과 같은 번호
        "우리설비,김하나,공무,",  # 이 파일 앞 행과 같은 협력사·이름
    )

    rows = _by_n(_import(client, user, sid, content).json())

    assert [rows[n]["result"] for n in range(2, 7)] == ["exists", "exists", "new", "exists", "exists"]
    assert len({rows[n]["reason"] for n in (2, 3, 5, 6)}) == 4  # 까닭은 넷이 다 다르다(번호/이름 · 이 프로젝트/이 파일)


def test_skip_rows_and_commit(client, user, sid, session):
    _person(client, user, sid, _company(client, user, sid))
    preview = _import(client, user, sid, _fixture("utf8.csv")).json()
    new_row = next(row["n"] for row in preview["rows"] if row["result"] == "new")

    r = _import(client, user, sid, _fixture("utf8.csv"), dry_run=0, skip=[new_row])

    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["summary"] == {"new": 0, "no_phone": 1, "exists": 1, "bad": 1, "skipped": 1}
    assert [(row["n"], row["result"], row["skipped"]) for row in body["rows"]] == [
        (2, "new", True), (3, "no_phone", False), (4, "exists", False), (5, "bad_phone", False)]
    people = _people(client, user, sid)
    assert sorted((p["company"], p["name"], p["has_phone"]) for p in people) == [
        ("대한골조", "박현장", True), ("우리설비", "오배관", False)]

    # 넣기는 미리 보기를 믿지 않고 다시 검사한다 — 같은 파일을 또 넣으면 이미 있는 것은 건너뛴다
    again = _import(client, user, sid, _fixture("utf8.csv"), dry_run=0).json()
    assert again["summary"] == {"new": 1, "no_phone": 0, "exists": 2, "bad": 1, "skipped": 0}
    assert len(_people(client, user, sid)) == 3
    session.expire_all()
    companies = session.scalars(select(ContactCompany.name).where(ContactCompany.schedule_id == sid)).all()
    assert sorted(companies) == ["대한골조", "우리설비"]  # 오류 행의 협력사(한빛전기)는 만들지 않음, 우리설비는 한 번만


def test_commit_is_one_transaction(client, user, sid, session, monkeypatch):
    before = _counts(session)
    real = csv_import._add_person
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("멈춤")
        return real(*args, **kwargs)

    monkeypatch.setattr(csv_import, "_add_person", fail_second)

    with pytest.raises(RuntimeError):
        _import(client, user, sid, _fixture("cp949.csv"), dry_run=0)

    assert _counts(session) == before  # 협력사도 사람도 하나도 들어가지 않는다


def test_skip_must_be_row_numbers(client, user, sid):
    r = client.post(_url(sid, "/import?dry_run=1"), files={"file": ("a.csv", _csv("가람건설,김,공무,"), "text/csv")},
                    data={"skip": ["2", "셋"]}, headers=user)

    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")


def test_imported_number_that_is_do_not_contact_elsewhere_shows_so(client, user, sid, sid2, session):
    _person(client, user, sid2, _company(client, user, sid2), phone=SENTINEL_PHONE, do_not_contact=True)

    preview = _by_n(_import(client, user, sid, _csv(f"가람건설,김거부,공무,{SENTINEL_PHONE}")).json())
    _import(client, user, sid, _csv(f"가람건설,김거부,공무,{SENTINEL_PHONE}"), dry_run=0)

    assert (preview[2]["result"], preview[2]["do_not_contact"]) == ("new", True)
    assert _people(client, user, sid)[0]["do_not_contact"] is True


# ── 파일 검사 ───────────────────────────────────────────────────────────────────

def test_file_problems_are_refused_with_korean_reasons(client, user, sid, session):
    before = _counts(session)
    cases = [
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)), 422, "csv_not_text"),
        ("협력사,이름\n".encode("utf-16"), 422, "csv_not_text"),
        ("협력사,이름\n가람건설,김\x00이\n".encode(), 422, "csv_not_text"),  # UTF-8 로는 읽히지만 NUL — 글 파일이 아님
        (b"", 422, "csv_no_header"),
        ("이름,전화번호\n김,010-0000-0199\n".encode(), 422, "csv_missing_column"),
        ("협력사,이름,이름\n가,나,다\n".encode(), 422, "csv_duplicate_column"),
        ('협력사,이름\n"가람건설,김\n'.encode(), 422, "csv_unreadable"),
        (_csv(*(f"가람건설,김{i},공무," for i in range(501))), 422, "csv_too_many_rows"),
    ]
    for content, status, code in cases:
        r = _import(client, user, sid, content, dry_run=0)
        assert (r.status_code, r.json()["code"]) == (status, code), (code, r.json())
        assert r.json()["message"] and "0199" not in r.text and "가람" not in r.text
    assert _import(client, user, sid, _csv(*(f"가람건설,김{i},공무," for i in range(500)))).status_code == 200
    assert _import(client, user, sid, _csv("가람건설,김,공무,", ",,,", "")).json()["summary"]["no_phone"] == 1
    r = client.post(_url(sid, "/import"), data={"skip": "2"}, headers=user)
    assert (r.status_code, r.json()["code"]) == (422, "csv_missing_file")
    assert _counts(session) == before


def test_missing_column_names_the_columns(client, user, sid):
    r = _import(client, user, sid, "이름,전화번호\n".encode())

    assert r.json()["detail"] == {"missing": ["협력사"]}


def test_large_upload_is_refused_before_the_body_is_read(client, user, sid, monkeypatch):
    from starlette.requests import Request

    def never(*_args, **_kwargs):
        raise AssertionError("몸을 읽었다")

    monkeypatch.setattr(Request, "form", never)
    big = _csv(*("가람건설,김,공무," for _ in range(80_000)))
    assert len(big) > csv_import.MAX_BODY_BYTES

    r = _import(client, user, sid, big)

    assert (r.status_code, r.json()["code"]) == (413, "csv_too_large")
    assert r.json()["message"] == "CSV 파일은 1MB 까지 올릴 수 있습니다."


def test_file_just_over_one_megabyte_is_refused(client, user, sid):
    content = _csv(*("가람건설,김,공무," for _ in range(50_000)))[: csv_import.MAX_BYTES + 1]
    assert len(content) == csv_import.MAX_BYTES + 1

    r = _import(client, user, sid, content)

    assert (r.status_code, r.json()["code"]) == (413, "csv_too_large")


def test_import_logs_only_counts(client, user, sid, caplog):
    caplog.set_level(logging.DEBUG)
    content = _csv(f"우리설비,김비밀,설비 소장,{SENTINEL_PHONE}", "우리설비,오비밀,공무,010-12-34",
                   "우리설비,=HYPERLINK(1),공무,")

    _import(client, user, sid, content)
    _import(client, user, sid, content, dry_run=0)
    _import(client, user, sid, b"\x00\x01binary")

    assert_clean(caplog, "김비밀", "오비밀", "HYPERLINK", "우리설비", "설비 소장", "010-12-34")
    lines = [rec.getMessage() for rec in caplog.records if rec.name == csv_import.__name__]
    assert len(lines) == 2, lines  # 거절된 파일(글이 아님)은 줄을 남기지 않는다
    assert all("새 1" in line and "번호 없음 1" in line and "오류 1" in line for line in lines), lines


# ── 다른 프로젝트에서 복사 ─────────────────────────────────────────────────────────

def _source(client, admin, sid2) -> tuple[int, int]:
    company = _company(client, admin, sid2)
    refused = _person(client, admin, sid2, company, phone=SENTINEL_PHONE, do_not_contact=True, dnc_reason="본인 요청",
                      gender="male", language="en", hours={"days": [0, 1, 2], "start": "07:00", "end": "16:00"},
                      note="오전 통화")
    other = _person(client, admin, sid2, company, name="최반장", phone="02-2000-0198")
    return refused["id"], other["id"]


def test_copy_is_admin_only_and_keeps_dnc(client, admin, user, sid, sid2, session):
    refused, other = _source(client, admin, sid2)
    body = {"from_schedule_id": sid2, "contact_ids": [refused, other]}

    denied = client.post(_url(sid, "/copy"), json=body, headers=user)
    assert (denied.status_code, denied.json()["code"]) == (403, "admin_only")
    assert _people(client, admin, sid) == []

    sources = client.get(_url(sid, "/copy-sources"), headers=admin)
    assert sources.status_code == 200
    assert sources.json() == [{"schedule_id": sid2, "name": "시험 일정", "people": 2}]  # 이 일정은 빠진다
    listing = client.get(_url(sid, f"/copy-sources/{sid2}"), headers=admin)
    assert listing.status_code == 200 and SENTINEL_DIGITS not in listing.text.replace("-", "")
    shown = {p["name"]: p for c in listing.json()["companies"] for p in c["people"]}
    assert (shown["박현장"]["phone_masked"], shown["박현장"]["do_not_contact"], shown["박현장"]["already_here"]) == (
        "010-****-0199", True, False)
    assert shown["최반장"]["phone_kind"] == "landline"

    r = client.post(_url(sid, "/copy"), json=body, headers=admin)

    assert r.status_code == 200, r.json()
    assert r.json() == {"copied": 2, "skipped": 0, "refused": 0}
    copied = {p["name"]: p for p in _people(client, admin, sid)}
    assert set(copied) == {"박현장", "최반장"} and copied["박현장"]["company"] == "대한골조"
    assert copied["박현장"]["id"] not in (refused, other)
    detail = client.get(_url(sid, f"/people/{copied['박현장']['id']}"), headers=admin).json()
    assert (detail["do_not_contact"], detail["dnc_reason"], detail["gender"], detail["language"], detail["note"]) == (
        True, "본인 요청", "male", "en", "오전 통화")
    assert detail["hours"] == {"days": [0, 1, 2], "start": "07:00", "end": "16:00"}
    assert copied["최반장"]["channels"] == ["call"]
    session.expire_all()
    assert outreach.is_do_not_contact(session, SENTINEL_PHONE)
    assert session.scalar(select(DoNotContactNumber).where(DoNotContactNumber.number == SENTINEL_DIGITS)) is not None

    # 같은 번호가 이미 있으면 건너뛴다. 복사한 뒤에는 서로 이어지지 않는다
    assert client.post(_url(sid, "/copy"), json=body, headers=admin).json() == {"copied": 0, "skipped": 2, "refused": 0}
    client.patch(_url(sid, f"/people/{copied['최반장']['id']}"), json={"name": "최반장님"}, headers=admin)
    source = client.get(_url(sid2, f"/people/{other}"), headers=admin).json()
    assert source["name"] == "최반장"
    listing = client.get(_url(sid, f"/copy-sources/{sid2}"), headers=admin).json()
    assert all(p["already_here"] for c in listing["companies"] for p in c["people"])


def test_copy_into_an_existing_company_and_never_clears(client, admin, sid, sid2, session):
    refused, _ = _source(client, admin, sid2)
    here = _company(client, admin, sid)
    # 번호 기록 없이 표시만 있는 예전 줄 — 복사가 번호 기록을 남겨야 원래 줄이 풀려도 막힌 채다
    session.execute(DoNotContactNumber.__table__.delete())
    session.commit()
    # 이 프로젝트에는 같은 번호가 없고, 번호는 다른 곳에서 수신 거부다 — 복사해도 풀리지 않는다
    r = client.post(_url(sid, "/copy"), json={"from_schedule_id": sid2, "contact_ids": [refused, refused]},
                    headers=admin)

    assert r.json() == {"copied": 1, "skipped": 0, "refused": 0}
    people = _people(client, admin, sid)
    assert [(p["company_id"], p["do_not_contact"]) for p in people] == [(here, True)]
    session.expire_all()
    assert session.get(Contact, people[0]["id"]).do_not_contact is True
    source = session.get(Contact, refused)
    source.do_not_contact = False
    session.commit()
    assert outreach.is_do_not_contact(session, SENTINEL_PHONE)
    assert session.scalar(select(DoNotContactNumber).where(DoNotContactNumber.number == SENTINEL_DIGITS)) is not None


def test_non_admin_cannot_see_other_projects(client, user, admin, sid, sid2, field_user, session):
    refused, _ = _source(client, admin, sid2)
    sid3 = schedules.store(session, schedules.sample())
    third = _person(client, admin, sid3, _company(client, admin, sid3), phone="010-0000-0197")["id"]

    for method, rest, body in (("get", "/copy-sources", None), ("get", f"/copy-sources/{sid2}", None),
                               ("post", "/copy", {"from_schedule_id": sid2, "contact_ids": [refused]})):
        r = client.request(method.upper(), _url(sid, rest), json=body, headers=user)
        assert (r.status_code, r.json()["code"]) == (403, "admin_only"), rest
        assert "박현장" not in r.text
        r = client.request(method.upper(), _url(sid, rest), json=body, headers=field_user)
        assert (r.status_code, r.json()["code"]) == (403, "field_no_contacts"), rest
    r = _import(client, field_user, sid, _csv("가람건설,김,공무,"))
    assert (r.status_code, r.json()["code"]) == (403, "field_no_contacts")

    # 다른(셋째) 프로젝트의 사람 id 는 없는 id 와 같은 404 — 하나라도 그러면 아무것도 복사하지 않는다
    missing = client.post(_url(sid, "/copy"), json={"from_schedule_id": sid2, "contact_ids": [refused, 999_999]},
                          headers=admin)
    foreign = client.post(_url(sid, "/copy"), json={"from_schedule_id": sid2, "contact_ids": [refused, third]},
                          headers=admin)
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json() == {"code": "not_found", "message": "연락처를 찾을 수 없습니다.",
                                                "detail": None}
    assert _people(client, admin, sid) == []
    gone = [client.get(_url(sid, "/copy-sources/999999"), headers=admin),
            client.post(_url(sid, "/copy"), json={"from_schedule_id": 999_999, "contact_ids": [refused]},
                        headers=admin),
            client.get(_url(999_999, "/copy-sources"), headers=admin)]
    assert [g.status_code for g in gone] == [404, 404, 404]
    same = client.post(_url(sid2, "/copy"), json={"from_schedule_id": sid2, "contact_ids": [refused]}, headers=admin)
    assert (same.status_code, same.json()["code"]) == (422, "same_schedule")
    empty = client.post(_url(sid, "/copy"), json={"from_schedule_id": sid2, "contact_ids": []}, headers=admin)
    assert (empty.status_code, empty.json()["code"]) == (422, "invalid_request")
    assert json.dumps(_people(client, admin, sid)) == "[]"
