"""들어온 문자 화면 API(계획 4 Task 85): 모르는 번호 묶음 · 확인할 보고 · 연락처 제안 · 긴급 보고 알림.

번호는 어떤 응답에도 전체 꼴로 나오지 않는다(가린 꼴과 peer_key 만). 묶음·차단·주소록에 넣기는 peer_key 로 가리킨다.
일정에 묶인 목록에는 다른 일정의 줄이 없다. 제안 수락은 주소록 서비스의 검사(사람 양식과 같은 것)를 지나 지금 일정에만 사람을 만든다.
현장 관리자는 모든 길이 403 field_no_contacts.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone
from app.programs.outreach import inbox_service
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

OTHER_DIGITS = "01000000198"  # 둘째 모르는 번호(가상)
NOW = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)  # KST 10:00
FIELD_NO = ("field_no_contacts", "현장 관리자는 연락처를 열 수 없습니다.")
UNKNOWN_KEYS = {"peer_key", "number_masked", "last_at", "messages", "calls", "last_line", "last_kind", "last_direction",
                "blocked", "known"}
REPORT_KEYS = {"id", "schedule_id", "medium", "kind", "text", "quote", "quote_found", "status", "contact_id", "contact_name",
               "peer_masked", "peer_key", "message_id", "call_id", "draft_id", "created_at", "reviewed_by", "reviewed_at"}
PROPOSAL_KEYS = {"id", "kind", "schedule_id", "name", "role_title", "company_name", "number_masked", "language", "contact_id",
                 "contact_name", "source", "created_at"}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(inbox_service, "_now", lambda: NOW)


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


def _clean(text: str) -> None:
    """응답 글에 가상 번호의 전체 꼴(숫자만·하이픈·가운데 8자리)이 없다."""
    for bad in (SENTINEL_DIGITS, SENTINEL_PHONE, "00000199", "0000-0199", OTHER_DIGITS, "00000198", "0000-0198"):
        assert bad not in text, bad


def _msg(session, number: str | None = SENTINEL_DIGITS, *, at: datetime = NOW, schedule_id=None, contact_id=None,
         **over) -> OutreachMessage:
    values = {"schedule_id": schedule_id, "contact_id": contact_id, "peer_number": number, "direction": "in",
              "channel": "sms", "origin": "peer", "status": "received", "caller_class": "unknown",
              "body": "현장 일정 좀 알려 주세요", "created_at": at, **over}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def _call(session, number: str | None = SENTINEL_DIGITS, *, at: datetime = NOW, **over) -> OutreachCall:
    values = {"schedule_id": None, "peer_number": number, "direction": "in", "origin": "peer", "status": "completed",
              "caller_class": "unknown", "summary_ko": "용건을 남김", "created_at": at, **over}
    row = OutreachCall(**values)
    session.add(row)
    session.commit()
    return row


def _company(session, sid: int, name: str = "가람철근") -> int:
    row = ContactCompany(schedule_id=sid, name=name, trade="철근")
    session.add(row)
    session.commit()
    return row.id


def _person(session, sid: int, phone_digits: str | None = "01000000197", **over) -> int:
    cid = _company(session, sid)
    row = Contact(**{"schedule_id": sid, "company_id": cid, "name": "김공정", "role_title": "공무", "phone": phone_digits,
                     **over})
    session.add(row)
    session.commit()
    return row.id


def _report(session, schedule_id: int | None, **over) -> ContactReport:
    values = {"schedule_id": schedule_id, "medium": "sms", "kind": "delay", "text": "철근 반입이 하루 늦습니다",
              "quote": "철근이 내일 들어와요", "quote_found": True, "status": "open", "created_at": NOW, **over}
    row = ContactReport(**values)
    session.add(row)
    session.commit()
    return row


def _proposal(session, schedule_id: int | None, **over) -> ContactProposal:
    values = {"schedule_id": schedule_id, "kind": "new", "name": "최반장", "role_title": "형틀 반장",
              "company_name": "새벽형틀", "phone": SENTINEL_DIGITS, "created_at": NOW, **over}
    row = ContactProposal(**values)
    session.add(row)
    session.commit()
    return row


def _people(session, sid: int) -> list[Contact]:
    session.expire_all()
    return list(session.scalars(select(Contact).where(Contact.schedule_id == sid).order_by(Contact.id)))


# ── 모르는 번호 ────────────────────────────────────────────────────────────


def test_unknown_list_has_no_full_number(client, user, session, sid):
    """일정 없는 줄을 번호로 묶는다 — 가린 번호·peer_key 만, 글 속 번호도 가림. 일정에 묶인 줄은 들지 않는다."""
    _msg(session, at=NOW - timedelta(minutes=30), body=f"제 번호는 {SENTINEL_PHONE} 입니다")
    _call(session, at=NOW - timedelta(minutes=20))
    _msg(session, at=NOW - timedelta(minutes=10), body=f"다시 연락 주세요 {SENTINEL_DIGITS}")
    _msg(session, OTHER_DIGITS, at=NOW - timedelta(minutes=5), body="누구신가요")
    pid = _person(session, sid)
    _msg(session, "01000000197", schedule_id=sid, contact_id=pid, caller_class="contact", body="일정에 묶인 줄")

    r = client.get("/api/outreach/unknown", headers=user)

    assert r.status_code == 200, r.json()
    _clean(r.text)
    items = r.json()
    assert [set(i) for i in items] == [UNKNOWN_KEYS, UNKNOWN_KEYS]
    newest, older = items
    assert (newest["peer_key"], newest["number_masked"]) == (phone.peer_key(OTHER_DIGITS), "010-****-0198")
    assert (older["peer_key"], older["number_masked"]) == (phone.peer_key(SENTINEL_DIGITS), "010-****-0199")
    assert (older["messages"], older["calls"], older["last_kind"], older["last_direction"]) == (2, 1, "message", "in")
    assert older["last_line"].startswith("다시 연락 주세요") and "[번호]" in older["last_line"]
    assert older["last_at"].startswith("2026-11-27T00:50:00") and (older["blocked"], older["known"]) == (False, False)
    assert "일정에 묶인 줄" not in r.text

    detail = client.get(f"/api/outreach/unknown/{older['peer_key']}", headers=user)

    assert detail.status_code == 200, detail.json()
    _clean(detail.text)
    body = detail.json()
    assert (body["peer_key"], body["number_masked"], body["blocked"], body["known"]) == (
        older["peer_key"], "010-****-0199", False, False)
    assert [(line["kind"], line["direction"]) for line in body["lines"]] == [("message", "in"), ("call", "in"),
                                                                              ("message", "in")]
    assert body["lines"][0]["text"] == "제 번호는 [번호] 입니다" and body["lines"][1]["text"] == "용건을 남김"
    assert set(body["lines"][0]) == {"kind", "id", "direction", "at", "text", "status", "message_kind", "events"}


def test_unknown_peer_not_found_is_404(client, user, session):
    _msg(session)

    r = client.get(f"/api/outreach/unknown/{phone.peer_key(OTHER_DIGITS)}", headers=user)

    assert (r.status_code, r.json()["code"]) == (404, "peer_not_found")


def test_rows_without_a_number_are_one_group_that_cannot_be_blocked_or_added(client, admin, session, sid):
    _msg(session, None, body="번호 없이 온 글")
    key = phone.peer_key(phone.NO_NUMBER)

    items = client.get("/api/outreach/unknown", headers=admin).json()

    assert [(i["peer_key"], i["number_masked"]) for i in items] == [(key, "번호 없음")]
    r = client.post(f"/api/schedules/{sid}/outreach/unknown/{key}/contact",
                    json={"name": "누군가", "company_name": "새협력"}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "peer_has_no_number")
    assert _people(session, sid) == []


def test_block_uses_peer_key(client, admin, user, session):
    """[차단]은 번호를 내리지 않고 peer_key 로 — 설정의 차단 목록 길(POST /api/notify/blocked)을 그대로 쓴다."""
    _msg(session, body="광고 문자")
    key = client.get("/api/outreach/unknown", headers=admin).json()[0]["peer_key"]

    refused = client.post("/api/notify/blocked", json={"peer_key": key, "reason": "광고"}, headers=user)
    done = client.post("/api/notify/blocked", json={"peer_key": key, "reason": "광고"}, headers=admin)

    assert (refused.status_code, refused.json()["code"]) == (403, "admin_only")
    assert done.status_code == 201, done.json()
    _clean(done.text)
    assert done.json()["number_masked"] == "010-****-0199"
    session.expire_all()
    assert list(session.scalars(select(BlockedNumber.number))) == [SENTINEL_DIGITS]
    after = client.get("/api/outreach/unknown", headers=admin)
    assert after.json()[0]["blocked"] is True
    assert client.get(f"/api/outreach/unknown/{key}", headers=admin).json()["blocked"] is True


def test_unknown_peer_can_be_added_to_this_project_only(client, user, session, sid, sid2):
    """[주소록에 넣기] — 번호는 서버가 peer_key 로 찾아 주소록 서비스로 지금 일정에 만든다(응답은 가린 꼴)."""
    _msg(session)
    key = phone.peer_key(SENTINEL_DIGITS)

    r = client.post(f"/api/schedules/{sid}/outreach/unknown/{key}/contact",
                    json={"name": "최반장", "role_title": "형틀 반장", "company_name": "새벽형틀"}, headers=user)

    assert r.status_code == 201, r.json()  # 주소록의 사람 추가와 같은 201
    _clean(r.text)
    assert (r.json()["name"], r.json()["phone_masked"]) == ("최반장", "010-****-0199")
    people = _people(session, sid)
    assert [(p.name, p.phone, p.can_sms) for p in people] == [("최반장", SENTINEL_DIGITS, True)]
    assert _people(session, sid2) == []
    assert client.get("/api/outreach/unknown", headers=user).json()[0]["known"] is True


ALREADY = ("already_in_book", "이 번호는 이미 이 프로젝트의 주소록에 있습니다.")


def _two_at_once(engine, monkeypatch, first, second) -> list:
    """두 요청이 「같은 번호가 이 일정 주소록에 있나」를 거의 같이 본다 — 확인 바로 뒤에서 서로를 1초까지 기다리게 해서,
    확인과 넣기가 한 쓰기 트랜잭션이 아니면 둘 다 「없음」을 보고 둘 다 넣는다. 결과(사람 id 또는 ApiError 코드) 둘."""
    gate, looked = threading.Barrier(2), inbox_service._in_book

    def slow_look(*args, **kwargs):
        found = looked(*args, **kwargs)
        try:
            gate.wait(1)
        except threading.BrokenBarrierError:
            pass
        return found

    monkeypatch.setattr(inbox_service, "_in_book", slow_look)
    out: list = [None, None]

    def run(i: int, call) -> None:
        with Session(engine) as mine:
            try:
                out[i] = call(mine).id
            except ApiError as exc:
                out[i] = exc.code

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate((first, second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return out


def test_adding_an_unknown_number_already_in_this_book_is_409(client, user, session, sid, sid2):
    """[주소록에 넣기]를 두 탭에서·시간 초과 뒤 다시 눌러도 같은 번호의 사람은 하나 — 둘째는 409(번호 없음).
    숨긴 사람·다른 일정의 사람은 세지 않는다."""
    _msg(session)
    key = phone.peer_key(SENTINEL_DIGITS)
    _person(session, sid2, SENTINEL_DIGITS)  # 다른 일정
    _person(session, sid, SENTINEL_DIGITS, hidden=True)  # 숨긴 사람
    url = f"/api/schedules/{sid}/outreach/unknown/{key}/contact"

    first = client.post(url, json={"name": "최반장", "company_name": "새벽형틀"}, headers=user)
    again = client.post(url, json={"name": "최반장", "company_name": "새벽형틀"}, headers=user)

    assert first.status_code == 201, first.json()
    assert (again.status_code, (again.json()["code"], again.json()["message"])) == (409, ALREADY)
    _clean(again.text)
    assert [p.name for p in _people(session, sid) if not p.hidden] == ["최반장"]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "새벽형틀")) == 1


@pytest.mark.parametrize("new_company", [False, True])
def test_two_tabs_adding_the_same_unknown_number_make_one_person(client, session, sid, monkeypatch, new_company):
    """새 협력사를 만드는 길은 주소록 서비스가 협력사를 commit 한 뒤 다시 확인한다 — 진 쪽은 자기 빈 협력사를 지운다."""
    _msg(session)
    key = phone.peer_key(SENTINEL_DIGITS)
    pick = {"company_name": "새벽형틀"} if new_company else {"company_id": _company(session, sid)}
    body = inbox_service.AddPeerIn(name="최반장", **pick)
    session.commit()

    out = _two_at_once(session.get_bind(), monkeypatch, lambda s: inbox_service.add_peer(s, sid, key, body),
                       lambda s: inbox_service.add_peer(s, sid, key, body))

    assert out.count("already_in_book") == 1 and None not in out, out
    assert [p.name for p in _people(session, sid)] == ["최반장"]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "새벽형틀")) == (
        1 if new_company else 0)


def test_accepting_a_proposal_whose_number_is_already_in_this_book_is_409(client, user, session, sid):
    pid = _person(session, sid, SENTINEL_DIGITS)
    proposal = _proposal(session, sid)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept", json={"company_name": "새벽형틀"},
                    headers=user)

    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (409, ALREADY)
    _clean(r.text)
    assert [p.id for p in _people(session, sid)] == [pid]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "새벽형틀")) == 0
    assert session.get(ContactProposal, proposal.id).status == "pending"


@pytest.mark.parametrize("new_company", [False, True])
def test_two_proposals_with_one_number_accepted_together_make_one_person(client, session, sid, monkeypatch, new_company):
    """같은 번호의 제안 둘(이 일정 것·모르는 번호의 것)을 두 사람이 같이 받음 — 사람 하나, 다른 하나는 409 이고 그 제안은 그대로."""
    mine, loose = _proposal(session, sid), _proposal(session, None, name="최반장2")
    who = session.scalar(select(User.id).where(User.role == "admin"))
    body = inbox_service.AcceptIn(**({"company_name": "새벽형틀"} if new_company else {"company_id": _company(session, sid)}))
    ids = (mine.id, loose.id)
    session.commit()

    out = _two_at_once(session.get_bind(), monkeypatch,
                       lambda s: inbox_service.accept(s, sid, ids[0], body, s.get(User, who)),
                       lambda s: inbox_service.accept(s, sid, ids[1], body, s.get(User, who)))

    assert out.count("already_in_book") == 1 and None not in out, out
    assert len(_people(session, sid)) == 1
    session.expire_all()
    statuses = sorted(session.get(ContactProposal, i).status for i in ids)
    assert statuses == ["accepted", "pending"]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "새벽형틀")) == (
        1 if new_company else 0)


@pytest.mark.parametrize("path", ["unknown", "proposal"])
def test_a_person_added_while_the_new_company_is_made_wins(client, user, session, sid, monkeypatch, path):
    """새 협력사는 주소록 서비스가 따로 commit 한다 — 그 틈에 다른 요청이 같은 번호의 사람을 넣으면 다시 확인해 409, 방금 만든 빈
    협력사는 지우고 제안은 「확인할 연락처」로 되돌린다."""
    _msg(session)
    proposal = _proposal(session, sid)
    theirs = _company(session, sid, "가람철근")  # 다른 요청의 사람은 자기 협력사에
    made = inbox_service.address_book.create_company
    engine = session.get_bind()

    def other_request_in_between(*args, **kwargs):
        company = made(*args, **kwargs)
        with Session(engine) as other:
            other.add(Contact(schedule_id=sid, company_id=theirs, name="먼저 넣은 사람", phone=SENTINEL_DIGITS))
            other.commit()
        return company

    monkeypatch.setattr(inbox_service.address_book, "create_company", other_request_in_between)
    url = (f"/api/schedules/{sid}/outreach/unknown/{phone.peer_key(SENTINEL_DIGITS)}/contact" if path == "unknown"
           else f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept")

    r = client.post(url, json={"name": "최반장", "company_name": "새벽형틀"}, headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "already_in_book")
    assert [p.name for p in _people(session, sid)] == ["먼저 넣은 사람"]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "새벽형틀")) == 0
    assert session.get(ContactProposal, proposal.id).status == "pending"


def test_the_contacts_service_calls_the_inbox_makes_still_fit(session, sid, user):
    """inbox_service 는 주소록 프로그램의 서비스를 부른다(계획 규칙의 예외 — 컨트롤러 판정). 그쪽 함수의 서명·돌려주는 꼴이
    바뀌면 여기서 깨지도록, inbox 가 쓰는 꼴 그대로 부른다."""
    from app.programs.contacts import service as address_book
    from app.programs.contacts.schemas import CompanyIn, PersonIn, PersonPatch

    draft = PersonIn(name="최반장", role_title="형틀 반장", company_id=0)
    address_book.check_texts(draft.model_dump())
    assert address_book.check_phone(SENTINEL_PHONE) == SENTINEL_DIGITS and address_book.check_phone(None) is None
    company = address_book.create_company(session, sid, CompanyIn(name="새벽형틀"))
    made = address_book.create_person(session, sid, draft.model_copy(update={"phone": SENTINEL_DIGITS, "company_id": company.id}))
    assert (made.name, made.phone_masked, made.company_id) == ("최반장", "010-****-0199", company.id)
    assert address_book.person(session, sid, made.id).id == made.id
    admin = session.scalar(select(User).where(User.role == "admin"))
    assert address_book.patch_person(session, sid, made.id, PersonPatch(language="en"), admin).language == "en"
    assert isinstance(address_book.COMPANY_NOT_FOUND, str)


# ── 확인할 보고 ────────────────────────────────────────────────────────────


def test_reports_are_project_scoped_and_unassigned_ones_have_their_own_list(client, user, session, sid, sid2):
    mine = _report(session, sid)
    theirs = _report(session, sid2, text="다른 현장 보고")
    loose = _report(session, None, medium="call", kind="message", text="모르는 번호의 메모")
    done = _report(session, sid, status="reviewed", text="확인한 보고")

    scoped = client.get(f"/api/schedules/{sid}/outreach/reports?status=open", headers=user)
    unassigned = client.get("/api/outreach/reports?unassigned=1", headers=user)
    every = client.get(f"/api/schedules/{sid}/outreach/reports?status=all", headers=user)

    assert scoped.status_code == 200, scoped.json()
    assert [r["id"] for r in scoped.json()] == [mine.id]
    assert set(scoped.json()[0]) == REPORT_KEYS
    assert "다른 현장 보고" not in scoped.text + unassigned.text + every.text
    assert [r["id"] for r in unassigned.json()] == [loose.id]
    assert sorted(r["id"] for r in every.json()) == sorted([mine.id, done.id])
    assert theirs.id not in [r["id"] for r in every.json()]
    assert client.get("/api/outreach/reports", headers=user).status_code == 422  # 일정 없는 보고만 이 길로


def test_report_lines_hide_numbers_and_link_the_held_draft(client, user, session, sid):
    pid = _person(session, sid)
    inbound = _msg(session, "01000000197", schedule_id=sid, contact_id=pid, caller_class="contact")
    held = OutreachMessage(schedule_id=sid, contact_id=pid, direction="out", channel="sms", origin="agent",
                           origin_name="AI 비서", kind="auto_reply", status="draft", body="월요일에 들어갑니다",
                           fail_reason="내용 확인 필요", reply_to_id=inbound.id)
    session.add(held)
    session.commit()
    review = _report(session, sid, kind="review", text="내용 확인 필요", quote="", quote_found=False,
                     message_id=inbound.id, contact_id=pid)
    raw = _report(session, sid, text=f"새 번호 {SENTINEL_PHONE} 로 연락", quote=f"제 번호 {SENTINEL_DIGITS}",
                  contact_id=pid)

    r = client.get(f"/api/schedules/{sid}/outreach/reports", headers=user)

    assert r.status_code == 200, r.json()
    _clean(r.text)
    by_id = {x["id"]: x for x in r.json()}
    assert (by_id[review.id]["kind"], by_id[review.id]["draft_id"], by_id[review.id]["contact_name"]) == (
        "review", held.id, "김공정")
    assert by_id[raw.id]["text"] == "새 번호 [번호] 로 연락" and by_id[raw.id]["draft_id"] is None
    assert by_id[raw.id]["medium"] == "sms" and by_id[raw.id]["quote_found"] is True


def test_unassigned_report_points_to_its_unknown_peer(client, user, session):
    inbound = _msg(session)
    loose = _report(session, None, message_id=inbound.id, kind="message")

    row = client.get("/api/outreach/reports?unassigned=1", headers=user).json()[0]

    assert (row["id"], row["peer_masked"], row["peer_key"]) == (loose.id, "010-****-0199", phone.peer_key(SENTINEL_DIGITS))


def test_review_marks_once_and_stays_in_its_project(client, user, session, sid, sid2):
    mine, theirs, loose = _report(session, sid), _report(session, sid2), _report(session, None)

    first = client.post(f"/api/schedules/{sid}/outreach/reports/{mine.id}/review", headers=user)
    again = client.post(f"/api/schedules/{sid}/outreach/reports/{mine.id}/review", headers=user)
    other = client.post(f"/api/schedules/{sid}/outreach/reports/{theirs.id}/review", headers=user)
    wrong_door = client.post(f"/api/outreach/reports/{mine.id}/review", headers=user)
    unassigned = client.post(f"/api/outreach/reports/{loose.id}/review", headers=user)

    assert first.status_code == 200, first.json()
    assert (first.json()["status"], first.json()["reviewed_by"]) == ("reviewed", "일반 사용자")
    assert (again.status_code, again.json()["code"]) == (409, "already_reviewed")
    assert (other.status_code, other.json()["code"]) == (404, "report_not_found")
    assert (wrong_door.status_code, wrong_door.json()["code"]) == (404, "report_not_found")
    assert unassigned.status_code == 200 and unassigned.json()["status"] == "reviewed"
    session.expire_all()
    assert session.get(ContactReport, theirs.id).status == "open"


def test_reports_of_a_missing_schedule_are_404(client, user):
    r = client.get("/api/schedules/9999/outreach/reports", headers=user)

    assert (r.status_code, r.json()["code"]) == (404, "not_found")


# ── 연락처 제안 ────────────────────────────────────────────────────────────


def test_proposals_list_this_project_and_unassigned_ones_with_masked_numbers(client, user, session, sid, sid2):
    mine = _proposal(session, sid, message_id=1)
    loose = _proposal(session, None, name="모르는분", call_id=2)
    _proposal(session, sid2, name="다른 현장 사람")
    _proposal(session, sid, status="rejected", name="버린 제안")

    r = client.get(f"/api/schedules/{sid}/contacts/proposals", headers=user)

    assert r.status_code == 200, r.json()
    _clean(r.text)
    assert [p["id"] for p in r.json()] == sorted([mine.id, loose.id], reverse=True)
    assert all(set(p) == PROPOSAL_KEYS for p in r.json())
    by_id = {p["id"]: p for p in r.json()}
    assert (by_id[mine.id]["number_masked"], by_id[mine.id]["source"], by_id[mine.id]["schedule_id"]) == (
        "010-****-0199", "sms", sid)
    assert (by_id[loose.id]["source"], by_id[loose.id]["schedule_id"]) == ("call", None)
    assert "다른 현장 사람" not in r.text and "버린 제안" not in r.text


def test_proposal_accept_creates_contact_in_this_project_only(client, user, session, sid, sid2):
    proposal = _proposal(session, sid)
    other_company = _company(session, sid2, "다른 현장 협력사")
    theirs = _proposal(session, sid2, name="다른 현장 사람")

    cross = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept",
                        json={"company_id": other_company}, headers=user)
    assert (cross.status_code, cross.json()["code"]) == (404, "not_found")  # 다른 일정의 협력사는 없는 것과 같다
    assert _people(session, sid) == []
    wrong_project = client.post(f"/api/schedules/{sid}/contacts/proposals/{theirs.id}/accept",
                                json={"company_name": "새벽형틀"}, headers=user)
    assert (wrong_project.status_code, wrong_project.json()["code"]) == (404, "proposal_not_found")

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept",
                    json={"company_name": "새벽형틀"}, headers=user)

    assert r.status_code == 200, r.json()
    _clean(r.text)
    assert (r.json()["name"], r.json()["phone_masked"], r.json()["role_title"]) == ("최반장", "010-****-0199", "형틀 반장")
    people = _people(session, sid)
    assert [(p.name, p.phone, p.can_sms, p.can_call) for p in people] == [("최반장", SENTINEL_DIGITS, True, True)]
    company = session.get(ContactCompany, people[0].company_id)
    assert (company.schedule_id, company.name) == (sid, "새벽형틀")
    assert [p.name for p in _people(session, sid2)] == []
    row = session.get(ContactProposal, proposal.id)
    assert (row.status, row.decided_by, row.decided_at is not None) == ("accepted", "일반 사용자", True)
    twice = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept",
                        json={"company_name": "새벽형틀"}, headers=user)
    assert (twice.status_code, twice.json()["code"]) == (409, "already_decided")
    assert len(_people(session, sid)) == 1


def test_a_proposal_decided_in_between_is_not_accepted_twice(client, user, session, sid, monkeypatch):
    """두 사람이 같은 제안을 거의 같이 받음 — 검사 뒤 UPDATE 앞에서 다른 요청이 먼저 정했으면 409, 사람은 하나도 더 생기지 않는다."""
    proposal = _proposal(session, sid)
    checked = inbox_service._checked_company

    def other_request_wins(*args, **kwargs):
        picked = checked(*args, **kwargs)
        session.execute(update(ContactProposal).where(ContactProposal.id == proposal.id).values(status="rejected"))
        session.commit()
        return picked

    monkeypatch.setattr(inbox_service, "_checked_company", other_request_wins)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept", json={"company_name": "새벽형틀"},
                    headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "already_decided")
    assert _people(session, sid) == []
    assert session.scalar(select(func.count()).select_from(ContactCompany)) == 0
    assert session.get(ContactProposal, proposal.id).status == "rejected"


def test_a_refused_person_after_a_new_company_puts_the_proposal_back(client, user, session, sid, monkeypatch):
    """새 협력사는 만들었는데 사람 만들기가 거절되면(드묾) 제안은 다시 「확인할 연락처」로 돌아간다(다시 받을 수 있다)."""
    from app.errors import ApiError

    proposal = _proposal(session, sid)

    def refuse(*args, **kwargs):
        raise ApiError(422, "invalid_phone", "주소록에 둘 수 없는 번호입니다.")

    monkeypatch.setattr(inbox_service.address_book, "create_person", refuse)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept", json={"company_name": "새벽형틀"},
                    headers=user)

    assert (r.status_code, r.json()["code"]) == (422, "invalid_phone")
    session.expire_all()
    row = session.get(ContactProposal, proposal.id)
    assert (row.status, row.decided_by, row.schedule_id) == ("pending", None, sid)


def test_unassigned_proposal_is_accepted_into_the_current_project(client, user, session, sid, sid2):
    loose = _proposal(session, None)
    company = _company(session, sid)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{loose.id}/accept",
                    json={"company_id": company, "name": "최반장(확인)"}, headers=user)

    assert r.status_code == 200, r.json()
    assert [(p.name, p.company_id) for p in _people(session, sid)] == [("최반장(확인)", company)]
    assert session.get(ContactProposal, loose.id).schedule_id == sid
    assert client.get(f"/api/schedules/{sid2}/contacts/proposals", headers=user).json() == []


@pytest.mark.parametrize(("over", "body", "code"), [
    ({"phone": "06000000000"}, {"company_name": "새벽형틀"}, "invalid_phone"),  # 주소록에 둘 수 없는 번호(정보이용료)
    ({"name": "최\u202e반장"}, {"company_name": "새벽형틀"}, "invalid_text"),  # 사람 양식과 같은 글자 검사
    ({"name": ""}, {"company_name": "새벽형틀"}, "invalid_proposal"),
    ({}, {}, "company_required"),
    ({}, {"company_id": 1, "company_name": "둘 다"}, "company_required"),
])
def test_proposal_accept_uses_the_address_book_checks(client, user, session, sid, over, body, code):
    proposal = _proposal(session, sid, **over)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept", json=body, headers=user)

    assert (r.status_code, r.json()["code"]) == (422, code)
    _clean(r.text)
    session.expire_all()
    assert _people(session, sid) == []
    assert session.scalar(select(func.count()).select_from(ContactCompany)) == 0
    assert session.get(ContactProposal, proposal.id).status == "pending"


def test_language_proposal_changes_the_contacts_language(client, user, session, sid, sid2):
    pid = _person(session, sid, language="ko")
    proposal = _proposal(session, sid, kind="language", contact_id=pid, language="en", name="", company_name="",
                         phone=None)
    odd = _proposal(session, sid, kind="language", contact_id=pid, language="ja", name="", company_name="", phone=None)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept", json={}, headers=user)
    bad = client.post(f"/api/schedules/{sid}/contacts/proposals/{odd.id}/accept", json={}, headers=user)

    assert r.status_code == 200, r.json()
    session.expire_all()
    assert session.get(Contact, pid).language == "en"
    assert (bad.status_code, bad.json()["code"]) == (422, "unsupported_language")
    assert session.get(ContactProposal, odd.id).status == "pending"


def test_reject_proposal(client, user, session, sid, sid2):
    proposal, theirs = _proposal(session, sid), _proposal(session, sid2)

    r = client.post(f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/reject", headers=user)
    other = client.post(f"/api/schedules/{sid}/contacts/proposals/{theirs.id}/reject", headers=user)

    assert (r.status_code, r.json()) == (200, {"id": proposal.id, "status": "rejected"})
    assert (other.status_code, other.json()["code"]) == (404, "proposal_not_found")
    session.expire_all()
    assert session.get(ContactProposal, proposal.id).status == "rejected"
    assert _people(session, sid) == []


# ── 긴급 보고 알림 ─────────────────────────────────────────────────────────


def test_alerts_are_open_emergencies_since_the_cursor_without_numbers(client, user, session, sid):
    pid = _person(session, sid, name=f"현장 {SENTINEL_PHONE}")
    old = _report(session, sid, kind="emergency", created_at=NOW - timedelta(hours=3))
    urgent = _report(session, sid, kind="emergency", contact_id=pid, text=f"사고 {SENTINEL_PHONE}",
                     created_at=NOW - timedelta(minutes=2))
    loose = _report(session, None, kind="emergency", medium="call", created_at=NOW - timedelta(minutes=1))
    _report(session, sid, kind="delay", created_at=NOW - timedelta(minutes=1))
    _report(session, sid, kind="emergency", status="reviewed", created_at=NOW - timedelta(minutes=1))

    first = client.get("/api/outreach/alerts", headers=user)
    later = client.get("/api/outreach/alerts", params={"since": (NOW - timedelta(seconds=90)).isoformat()}, headers=user)

    assert first.status_code == 200, first.json()
    _clean(first.text)
    body = first.json()
    assert body["now"].startswith("2026-11-27T01:00:00")
    assert [a["id"] for a in body["items"]] == [loose.id, urgent.id]
    assert old.id not in [a["id"] for a in body["items"]]
    assert set(body["items"][0]) == {"id", "schedule_id", "schedule_name", "medium", "contact_name", "created_at"}
    by_id = {a["id"]: a for a in body["items"]}
    assert (by_id[urgent.id]["schedule_name"], by_id[urgent.id]["contact_name"]) == ("시험 일정", "현장 [번호]")
    assert (by_id[loose.id]["schedule_id"], by_id[loose.id]["contact_name"]) == (None, None)
    assert "사고" not in first.text  # 토스트에는 글을 싣지 않는다
    assert [a["id"] for a in later.json()["items"]] == [loose.id]


# ── 역할·앱에 붙음 ─────────────────────────────────────────────────────────


def test_field_role_403(client, field_user, session, sid):
    report, proposal = _report(session, sid), _proposal(session, sid)
    key = phone.peer_key(SENTINEL_DIGITS)
    calls = [
        ("get", "/api/outreach/unknown"), ("get", f"/api/outreach/unknown/{key}"),
        ("post", f"/api/schedules/{sid}/outreach/unknown/{key}/contact"),
        ("get", f"/api/schedules/{sid}/outreach/reports"), ("post", f"/api/schedules/{sid}/outreach/reports/{report.id}/review"),
        ("get", "/api/outreach/reports?unassigned=1"), ("post", f"/api/outreach/reports/{report.id}/review"),
        ("get", f"/api/schedules/{sid}/contacts/proposals"),
        ("post", f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/accept"),
        ("post", f"/api/schedules/{sid}/contacts/proposals/{proposal.id}/reject"),
        ("get", "/api/outreach/alerts"),
    ]
    for method, url in calls:
        r = getattr(client, method)(url, headers=field_user, **({"json": {}} if method == "post" else {}))
        assert (r.status_code, (r.json()["code"], r.json()["message"])) == (403, FIELD_NO), url
    session.expire_all()
    assert session.get(ContactReport, report.id).status == "open"
    assert session.get(ContactProposal, proposal.id).status == "pending"


def test_inbox_routes_are_mounted_in_the_real_app(client, user):
    """새 파일의 라우터는 outreach 의 router.py 가 import 해야 앱에 붙는다 — 길이 앱의 뜻 없는 404 가 아니다."""
    paths = set(client.app.openapi()["paths"])
    assert {"/api/outreach/unknown", "/api/outreach/unknown/{peer_key}", "/api/outreach/reports",
            "/api/outreach/reports/{report_id}/review", "/api/outreach/alerts",
            "/api/schedules/{schedule_id}/outreach/reports", "/api/schedules/{schedule_id}/outreach/reports/{report_id}/review",
            "/api/schedules/{schedule_id}/outreach/unknown/{peer_key}/contact",
            "/api/schedules/{schedule_id}/contacts/proposals",
            "/api/schedules/{schedule_id}/contacts/proposals/{proposal_id}/accept",
            "/api/schedules/{schedule_id}/contacts/proposals/{proposal_id}/reject"} <= paths
    assert (client.get("/api/outreach/unknown", headers=user).status_code,
            client.get("/api/outreach/unknown", headers=user).json()) == (200, [])
