"""여러 명에게 한 번에(계획 4 Task 103): POST …/outreach/batches · GET …/outreach/batches/{id}.

- 받는 사람마다 메시지 줄을 하나씩 만들고(batch_id 같음) **한 사람씩** 나가는 문(gate.dispatch)에 넣는다. 한 사람의 실패·거절·
  「확인 필요」는 다른 사람을 멈추거나 다시 보내게 하지 않고, 보냄으로 보이지 않는다.
- 한 번 누름 = 한 묶음: 화면이 준 request_key 로 줄의 중복 방지 키를 정해 두므로(고유 칸), 같은 요청이 다시 오면(두 번 누름·
  답을 못 받고 다시 보냄) 저장된 결과만 돌려주고 다시 보내지 않는다.
- 연락처는 모두 먼저 그 일정 것인지 본다(하나라도 아니면 404, 아무것도 만들지 않음). 번호는 응답·로그에 없다.
"""

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.outreach import hours
from app.outreach.harness import gate
from app.outreach.harness.types import Actor, Delivered, Outcome
from app.programs.outreach import batches_service, service
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    KakaoTemplate,
    NotifyConnection,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE, assert_clean

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
BODY = "내일 3층 타설 가능하신가요?"
USER_NAME = "일반 사용자"  # conftest 의 user1
KEY = "dialog-key-0001"
PERSON_404 = ("not_found", "연락처를 찾을 수 없습니다.")
BATCH_404 = ("not_found", "묶음을 찾을 수 없습니다.")
OTHER_NUMBERS = ("01000000201", "01000000202", "01000000203", "01000000204")  # 가상 번호


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(service, "_now", lambda: WORK)


@pytest.fixture
def conn(session) -> NotifyConnection:
    row = NotifyConnection(name="시험 연결", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="9999",
                           account_id="acct-test", sender_number="07000000000", is_default=True, status="ok",
                           test_mode=False)
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


def _company(session, sid: int, name: str = "가람철근", trade: str = "철근") -> int:
    row = ContactCompany(schedule_id=sid, name=name, trade=trade)
    session.add(row)
    session.commit()
    return row.id


def _person(session, sid: int, name: str, phone: str | None, company_id: int | None = None, **over) -> int:
    company_id = company_id or _company(session, sid)
    who = Contact(schedule_id=sid, company_id=company_id, name=name, role_title="공무", phone=phone, **over)
    session.add(who)
    session.commit()
    return who.id


def _people(session, sid: int, n: int) -> list[int]:
    company = _company(session, sid)
    numbers = (SENTINEL_DIGITS, *OTHER_NUMBERS)
    return [_person(session, sid, f"가상{i}", numbers[i % len(numbers)] if i < len(numbers) else f"010000003{i:02d}",
                    company) for i in range(n)]


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/outreach/batches{rest}"


def _post(client, headers, sid, contact_ids, key=KEY, **kw):
    body = {"contact_ids": contact_ids, "channel": "sms", "body": BODY, "request_key": key, **kw}
    return client.post(_url(sid), json=body, headers=headers)


def _count(session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(OutreachMessage))


def _rows(session, batch_id: int) -> list[OutreachMessage]:
    session.expire_all()
    return list(session.scalars(select(OutreachMessage).where(OutreachMessage.batch_id == batch_id)
                                .order_by(OutreachMessage.id)))


@pytest.fixture
def spy(monkeypatch):
    """진짜 문을 그대로 부르되 (kind, row_id, actor) 를 적는다."""
    calls: list[tuple[str, int, Actor]] = []
    real = gate.dispatch

    async def recording(kind, row_id, actor, *, now=None):
        calls.append((kind, row_id, actor))
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", recording)
    return calls


# ── 한 사람씩 문을 지난다 ─────────────────────────────────────────────────


def test_each_recipient_goes_through_gate_separately(client, user, session, sid, conn, fake_channel, spy):
    company = _company(session, sid)
    ok = _person(session, sid, "김공정", SENTINEL_DIGITS, company)
    refused = _person(session, sid, "정배선", OTHER_NUMBERS[0], company, do_not_contact=True)
    unsure = _person(session, sid, "이설비", OTHER_NUMBERS[1], company)
    # 통로에 닿는 것은 김공정·이설비 둘 — 둘째로 닿은 이설비의 통로만 「모름」
    fake_channel.during = lambda row_id: setattr(
        fake_channel, "result", Delivered("unsure") if len(fake_channel.delivered) == 2 else None)

    r = _post(client, user, sid, [ok, refused, unsure])

    assert r.status_code == 200, r.json()
    body = r.json()
    assert set(body) == {"batch_id", "results", "replayed", "in_progress"}
    assert body["replayed"] is False and body["in_progress"] is False
    assert [(x["contact_id"], x["name"], x["outcome"]["code"]) for x in body["results"]] == [
        (ok, "김공정", "accepted"), (refused, "정배선", "do_not_contact"), (unsure, "이설비", "unsure")]
    assert body["results"][0]["outcome"]["message"] == "보냈습니다"
    assert body["results"][1]["outcome"]["message"] == "수신 거부한 번호입니다"
    assert body["results"][2]["outcome"]["message"] == gate.UNSURE
    rows = _rows(session, body["batch_id"])
    assert [r.contact_id for r in rows] == [ok, refused, unsure]
    assert {r.batch_id for r in rows} == {body["batch_id"]} and body["batch_id"] == rows[0].id
    assert [r.status for r in rows] == ["accepted", "draft", "unconfirmed"]
    assert {(r.origin, r.origin_name, r.direction, r.channel, r.body) for r in rows} == {
        ("user", USER_NAME, "out", "sms", BODY)}
    # 문은 사람마다 한 번씩, 그 일정에 방금 만든 줄로, 로그인한 사람의 Actor 로
    assert [(kind, row_id) for kind, row_id, _ in spy] == [("message", r.id) for r in rows]
    assert {(a.kind, a.name, a.role) for _, _, a in spy} == {("user", USER_NAME, "user")}
    # 통로는 지나간 두 사람에게만, 한 번씩(「모름」을 다시 보내지 않음)
    assert [d.row_id for d in fake_channel.delivered] == [rows[0].id, rows[2].id]
    # 판정 사건은 줄마다 제 것
    assert [[e["rule"] for e in r.harness_json] for r in rows] == [
        ["channel_choice", "delivery"], ["blocked_or_dnc"], ["channel_choice", "delivery"]]


def test_one_recipients_error_does_not_stop_the_others_and_is_never_shown_as_sent(client, user, session, sid, conn,
                                                                                  fake_channel, monkeypatch, caplog):
    ids = _people(session, sid, 3)
    real = gate.dispatch
    calls: list[int] = []

    async def breaking(kind, row_id, actor, *, now=None):
        calls.append(row_id)
        if len(calls) == 2:
            raise RuntimeError(f"뜻밖의 오류 {SENTINEL_PHONE}")
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", breaking)
    caplog.set_level(logging.DEBUG)

    r = _post(client, user, sid, ids)

    assert r.status_code == 200, r.json()
    codes = [x["outcome"]["code"] for x in r.json()["results"]]
    assert codes == ["accepted", "unsure", "accepted"]
    assert r.json()["results"][1]["outcome"]["message"] == gate.UNSURE
    assert len(calls) == 3 and len(fake_channel.delivered) == 2
    assert SENTINEL_DIGITS not in r.text and SENTINEL_PHONE not in r.text
    assert_clean(caplog)


def test_failed_recipient_is_failed_and_others_still_go(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 3)
    fake_channel.during = lambda row_id: setattr(
        fake_channel, "result", Delivered("failed", fail_code="bad_sender") if len(fake_channel.delivered) == 1 else None)

    r = _post(client, user, sid, ids)

    results = r.json()["results"]
    assert [x["outcome"]["code"] for x in results] == ["failed", "accepted", "accepted"]
    assert results[0]["outcome"]["message"] == gate.FAIL_TEXT["bad_sender"]
    assert len(fake_channel.delivered) == 3


# ── 크기·입력 ─────────────────────────────────────────────────────────────


def test_batch_of_21_is_422(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 21)
    before = _count(session)

    too_many = _post(client, user, sid, ids)
    none = _post(client, user, sid, [], key="dialog-key-0002")

    assert (too_many.status_code, none.status_code) == (422, 422)
    assert _count(session) == before and fake_channel.delivered == []
    assert _post(client, user, sid, ids[:20], key="dialog-key-0003").status_code == 200
    assert len(fake_channel.delivered) == 20


@pytest.mark.parametrize("change", [
    {"contact_ids": "same twice"},
    {"request_key": "짧음"},
    {"request_key": None},
    {"body": None},
    {"body": "보이지 않는\u202e글"},
    {"channel": "call"},
    {"send_mode": "delegated"},
    {"template_vars": {"이름": "가"}},
])
def test_bad_input_is_422_and_nothing_is_made(client, user, session, sid, conn, fake_channel, change):
    ids = _people(session, sid, 2)
    body = {"contact_ids": ids, "channel": "sms", "body": BODY, "request_key": KEY, **change}
    if change.get("contact_ids") == "same twice":
        body["contact_ids"] = [ids[0], ids[0]]
    body = {k: v for k, v in body.items() if v is not None}
    before = _count(session)

    r = client.post(_url(sid), json=body, headers=user)

    assert r.status_code == 422, r.json()
    assert _count(session) == before and fake_channel.delivered == []


def test_other_project_contact_in_batch_is_404_and_nothing_sent(client, user, session, sid, sid2, conn, fake_channel,
                                                                 spy):
    mine = _people(session, sid, 2)
    theirs = _person(session, sid2, "남의 사람", OTHER_NUMBERS[2])
    before = _count(session)

    r = _post(client, user, sid, [mine[0], theirs, mine[1]])
    missing = _post(client, user, sid, [mine[0], 999_999], key="dialog-key-0009")

    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (404, PERSON_404)
    assert (missing.status_code, (missing.json()["code"], missing.json()["message"])) == (404, PERSON_404)
    assert _count(session) == before
    assert spy == [] and fake_channel.delivered == []


def test_other_project_links_are_404_and_nothing_sent(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 2)
    before = _count(session)

    r = _post(client, user, sid, ids, activity_id="Z9999")

    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    assert _count(session) == before and fake_channel.delivered == []


def test_template_without_body_fills_the_text_and_missing_value_is_422(client, user, session, sid, conn, fake_channel):
    template = KakaoTemplate(connection_id=conn.id, channel="ch", provider_template_id="t1", use="체크인 요청",
                             body="#{작업} 체크인 부탁드립니다. 답은 이 번호로 문자 주세요.", status="approved",
                             variables_json=["작업"])
    session.add(template)
    session.commit()
    ids = _people(session, sid, 2)

    empty = client.post(_url(sid), json={"contact_ids": ids, "channel": "kakao", "template_id": template.id,
                                         "template_vars": {"작업": " "}, "request_key": KEY}, headers=user)
    r = client.post(_url(sid), json={"contact_ids": ids, "channel": "kakao", "template_id": template.id,
                                     "template_vars": {"작업": "3층 타설"}, "request_key": "dialog-key-0004"},
                    headers=user)

    assert (empty.status_code, empty.json()["code"]) == (422, "invalid_template")
    assert r.status_code == 200, r.json()
    rows = _rows(session, r.json()["batch_id"])
    assert {row.body for row in rows} == {"3층 타설 체크인 부탁드립니다. 답은 이 번호로 문자 주세요."}
    assert {(row.template_id, tuple(row.template_vars_json.items())) for row in rows} == {
        (template.id, (("작업", "3층 타설"),))}
    assert len(fake_channel.delivered) == 2


# ── 한 번 누름 = 한 묶음 ─────────────────────────────────────────────────


def test_same_request_twice_sends_once_and_returns_the_stored_results(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 3)
    first = _post(client, user, sid, ids)
    made = _count(session)

    again = _post(client, user, sid, ids)

    assert first.status_code == again.status_code == 200
    assert again.json()["replayed"] is True and again.json()["in_progress"] is False
    assert again.json()["batch_id"] == first.json()["batch_id"]
    assert again.json()["results"] == first.json()["results"]
    assert _count(session) == made and len(fake_channel.delivered) == 3


@pytest.mark.parametrize("change", [
    {"body": "다른 글"}, {"contact_ids": "fewer"}, {"activity_id": "A"}, {"channel": "kakao"},
])
def test_same_request_key_with_different_content_is_409_and_sends_nothing(client, user, session, sid, conn,
                                                                          fake_channel, change):
    ids = _people(session, sid, 2)
    _post(client, user, sid, ids)
    made = _count(session)
    kw = {k: v for k, v in change.items() if k != "contact_ids"}

    r = _post(client, user, sid, ids[:1] if change.get("contact_ids") else ids, **kw)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "key_reused", batches_service.KEY_REUSED)
    assert _count(session) == made and len(fake_channel.delivered) == 2


def test_a_repeated_request_is_answered_from_storage_even_if_the_book_changed(client, user, session, sid, conn,
                                                                             fake_channel):
    """다시 온 요청은 검사·만들기 전에 저장된 묶음을 본다 — 그 사이 연락처가 지워져도 404 가 아니라 저장된 결과."""
    ids = _people(session, sid, 2)
    first = _post(client, user, sid, ids)
    session.delete(session.get(Contact, ids[1]))
    session.commit()

    again = _post(client, user, sid, ids)

    assert again.status_code == 200, again.json()
    assert again.json()["replayed"] is True and again.json()["batch_id"] == first.json()["batch_id"]
    assert [(x["name"], x["outcome"]["code"]) for x in again.json()["results"]] == [
        ("가상0", "accepted"), (batches_service.GONE_NAME, "accepted")]
    assert len(fake_channel.delivered) == 2


def test_request_key_is_per_person_and_project(client, user, admin, session, sid, sid2, conn, fake_channel):
    mine = _people(session, sid, 1)
    other = _person(session, sid2, "다른 일정 사람", OTHER_NUMBERS[3])

    a = _post(client, user, sid, mine)
    b = _post(client, admin, sid, mine)  # 다른 사람이 같은 열쇠를 써도 그 사람의 묶음
    c = _post(client, user, sid2, [other])  # 다른 일정

    assert len({a.json()["batch_id"], b.json()["batch_id"], c.json()["batch_id"]}) == 3
    assert not (a.json()["replayed"] or b.json()["replayed"] or c.json()["replayed"])


def test_second_request_that_loses_the_insert_race_sends_nothing(client, user, session, sid, conn, fake_channel,
                                                                  monkeypatch):
    """두 요청이 함께 「아직 없음」을 본 경우: 늦게 넣는 쪽은 고유 키에 걸려 아무것도 만들지 않고 저장된 결과를 돌려준다."""
    ids = _people(session, sid, 2)
    first = _post(client, user, sid, ids)
    real = batches_service._stored
    looked: list[int] = []

    def first_look_misses(*args, **kwargs):  # 앞서 본 때에는 아직 없었다(그 사이 다른 요청이 넣음)
        looked.append(1)
        return None if len(looked) == 1 else real(*args, **kwargs)

    monkeypatch.setattr(batches_service, "_stored", first_look_misses)
    made = _count(session)

    second = _post(client, user, sid, ids)

    assert second.status_code == 200, second.json()
    assert second.json()["replayed"] is True and second.json()["batch_id"] == first.json()["batch_id"]
    assert _count(session) == made and len(fake_channel.delivered) == 2
    assert len(looked) == 2


class _ServerDied(BaseException):
    """요청을 돌리던 프로세스가 죽은 것 — 묶음 코드가 잡지 않는다."""


def test_server_dying_mid_batch_leaves_the_rest_as_drafts_and_a_retry_sends_nothing(client, user, session, sid, conn,
                                                                                     fake_channel, monkeypatch):
    ids = _people(session, sid, 3)
    real = gate.dispatch
    calls: list[int] = []

    async def dying(kind, row_id, actor, *, now=None):
        calls.append(row_id)
        if len(calls) == 2:
            raise _ServerDied
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", dying)
    me = session.scalars(select(User).where(User.login_id == "user1")).one()
    request = batches_service.BatchIn(contact_ids=ids, channel="sms", body=BODY, request_key=KEY)
    with pytest.raises(_ServerDied):  # 요청을 돌리던 것이 그 자리에서 끝남(앱 밖에서 서비스를 바로 불러 흉내)
        asyncio.run(batches_service.send(session, sid, request, me))
    monkeypatch.setattr(gate, "dispatch", real)
    session.expire_all()
    rows = sorted(session.scalars(select(OutreachMessage)), key=lambda r: r.id)
    assert [r.status for r in rows] == ["accepted", "draft", "draft"]

    retry = _post(client, user, sid, ids)

    assert retry.status_code == 200 and retry.json()["replayed"] is True
    results = retry.json()["results"]
    assert [x["outcome"]["code"] for x in results] == ["accepted", "not_sent", "not_sent"]
    assert results[1]["outcome"]["message"] == batches_service.NOT_SENT
    assert len(fake_channel.delivered) == 1
    session.expire_all()
    assert [session.get(OutreachMessage, r.id).status for r in rows] == ["accepted", "draft", "draft"]


def test_stored_results_say_what_each_row_is_now(client, user, session, sid, conn, fake_channel):
    company = _company(session, sid)
    ids = [_person(session, sid, n, num, company) for n, num in
           (("가", SENTINEL_DIGITS), ("나", OTHER_NUMBERS[0]), ("다", OTHER_NUMBERS[1]), ("라", OTHER_NUMBERS[2]))]
    r = _post(client, user, sid, ids)
    rows = _rows(session, r.json()["batch_id"])
    rows[0].status = "delivered"
    rows[1].status, rows[1].fail_reason = "failed", gate.FAIL_TEXT["network"]
    rows[2].status = "sending"
    rows[3].status, rows[3].fail_reason = "draft", "수신 거부한 번호입니다"
    for row in rows:  # 방금 만든 묶음(첫 요청이 아직 돌 수 있는 때)
        row.created_at = WORK - timedelta(seconds=10)
    session.commit()

    again = _post(client, user, sid, ids)

    assert [(x["outcome"]["code"], x["outcome"]["message"]) for x in again.json()["results"]] == [
        ("accepted", "보냈습니다"), ("failed", gate.FAIL_TEXT["network"]), ("in_progress", batches_service.IN_PROGRESS),
        ("not_sent", "수신 거부한 번호입니다")]
    assert again.json()["in_progress"] is True


@pytest.mark.parametrize(("age_s", "code"), [
    (10, "in_progress"), (20 * 15 - 1, "in_progress"), (20 * 15 + 1, "not_sent"),
])
def test_undispatched_drafts_are_in_progress_only_while_the_batch_is_young(client, user, session, sid, conn,
                                                                          fake_channel, age_s, code):
    """문에 아직 넣지 않은 초안(사건 없음): 묶음이 만들어진 지 20 × 제공사 시간 제한 안이면 「보내는 중일 수 있음」."""
    assert batches_service.IN_PROGRESS_S == 20 * 15
    ids = _people(session, sid, 2)
    r = _post(client, user, sid, ids)
    rows = _rows(session, r.json()["batch_id"])
    rows[1].status, rows[1].harness_json, rows[1].fail_reason = "draft", [], None
    for row in rows:
        row.created_at = WORK - timedelta(seconds=age_s)
    session.commit()

    again = _post(client, user, sid, ids)

    assert [x["outcome"]["code"] for x in again.json()["results"]] == ["accepted", code]
    assert again.json()["in_progress"] is (code == "in_progress")
    if code == "in_progress":
        assert again.json()["results"][1]["outcome"]["message"] == "보내는 중일 수 있습니다 — 잠시 뒤 다시 확인해 주세요"


def test_reasking_while_the_first_request_is_still_sending_says_in_progress(client, user, session, sid, conn,
                                                                            fake_channel, monkeypatch):
    """첫 요청이 첫 사람에게서 멈춰 있는 동안 같은 요청이 다시 옴 → 보내지 않고 「보내는 중일 수 있습니다」."""
    monkeypatch.setattr(service, "_now", lambda: datetime.now(UTC))
    ids = _people(session, sid, 3)
    started, release, calls = threading.Event(), threading.Event(), []

    async def held(kind, row_id, actor, *, now=None):
        calls.append(row_id)
        started.set()
        for _ in range(200):  # 길어야 10초
            if release.is_set():
                break
            await asyncio.sleep(0.05)
        return Outcome("accepted", "보냈습니다")

    monkeypatch.setattr(gate, "dispatch", held)
    first: list = []
    worker = threading.Thread(target=lambda: first.append(_post(client, user, sid, ids)))
    worker.start()
    try:
        assert started.wait(10)
        again = _post(client, user, sid, ids)
    finally:
        release.set()
        worker.join(15)

    assert again.status_code == 200, again.json()
    assert again.json()["replayed"] is True and again.json()["in_progress"] is True
    assert [x["outcome"]["code"] for x in again.json()["results"]] == ["in_progress"] * 3
    assert first[0].status_code == 200 and first[0].json()["in_progress"] is False
    assert len(calls) == 3 and _count(session) == 3


# ── 묶음 셈 ───────────────────────────────────────────────────────────────


def test_replied_count_uses_reply_links(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 3)
    r = _post(client, user, sid, ids)
    batch_id = r.json()["batch_id"]
    rows = _rows(session, batch_id)
    other = OutreachMessage(schedule_id=sid, contact_id=ids[2], direction="out", channel="sms", origin="user",
                            origin_name=USER_NAME, body="묶음 밖 글", status="accepted")
    session.add(other)
    session.commit()

    def reply(contact_id, reply_to_id):
        session.add(OutreachMessage(schedule_id=sid, contact_id=contact_id, direction="in", channel="sms", origin="peer",
                                    origin_name="상대", body="네", status="received", reply_to_id=reply_to_id))

    reply(ids[0], rows[0].id)
    reply(ids[0], rows[0].id)  # 같은 사람 두 번 = 한 명
    reply(ids[1], None)  # 이어지지 않은 답은 세지 않음
    reply(ids[2], other.id)  # 묶음 밖 글에 단 답도
    session.commit()

    got = client.get(_url(sid, f"/{batch_id}"), headers=user)

    assert got.status_code == 200, got.json()
    assert got.json() == {"total": 3, "sent": 3, "replied": 1}


def test_sent_counts_only_rows_that_went_out(client, user, session, sid, conn, fake_channel):
    company = _company(session, sid)
    ok = _person(session, sid, "가", SENTINEL_DIGITS, company)
    refused = _person(session, sid, "나", OTHER_NUMBERS[0], company, do_not_contact=True)
    r = _post(client, user, sid, [ok, refused])

    got = client.get(_url(sid, f"/{r.json()['batch_id']}"), headers=user)

    assert got.json() == {"total": 2, "sent": 1, "replied": 0}


def test_batch_of_another_project_or_unknown_is_404(client, user, session, sid, sid2, conn, fake_channel):
    ids = _people(session, sid, 1)
    batch_id = _post(client, user, sid, ids).json()["batch_id"]

    other = client.get(_url(sid2, f"/{batch_id}"), headers=user)
    unknown = client.get(_url(sid, "/987654"), headers=user)

    assert (other.status_code, (other.json()["code"], other.json()["message"])) == (404, BATCH_404)
    assert (unknown.status_code, (unknown.json()["code"], unknown.json()["message"])) == (404, BATCH_404)


# ── 권한·노출·앱 ─────────────────────────────────────────────────────────


def test_field_manager_cannot_send_a_batch(client, session, sid, conn, fake_channel):
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    ids = _people(session, sid, 1)
    before = _count(session)

    r = _post(client, auth(issue_token(row.id)), sid, ids)
    g = client.get(_url(sid, "/1"), headers=auth(issue_token(row.id)))

    assert (r.status_code, r.json()["code"], g.status_code) == (403, "field_no_contacts", 403)
    assert _count(session) == before and fake_channel.delivered == []
    assert client.post(_url(sid), json={}).status_code == 401


def test_no_phone_number_in_results_or_logs(client, user, session, sid, conn, fake_channel, caplog):
    caplog.set_level(logging.DEBUG)
    ids = _people(session, sid, 2)

    r = _post(client, user, sid, ids)
    again = _post(client, user, sid, ids)
    got = client.get(_url(sid, f"/{r.json()['batch_id']}"), headers=user)

    for text in (r.text, again.text, got.text):
        assert SENTINEL_DIGITS not in text and SENTINEL_PHONE not in text and SENTINEL_DIGITS[1:] not in text
    assert set(r.json()["results"][0]) == {"contact_id", "name", "outcome"}
    assert_clean(caplog)


def test_batch_routes_are_mounted_in_the_real_app(client, user, sid):
    """새 파일의 라우터는 outreach 의 router.py 가 import 해야 앱에 붙는다 — 길이 앱의 뜻 없는 404 가 아니다."""
    paths = set(client.app.openapi()["paths"])
    assert {"/api/schedules/{schedule_id}/outreach/batches",
            "/api/schedules/{schedule_id}/outreach/batches/{batch_id}"} <= paths
    missing = client.get(_url(sid, "/12345"), headers=user)
    assert (missing.status_code, (missing.json()["code"], missing.json()["message"])) == (404, BATCH_404)


# ── 고침 2: 결과 확인은 보내지 않는다(키로 찾기만) ─────────────────────────

NOT_REACHED = ("not_found", "이 묶음은 서버에 닿지 않았습니다 — 보내지 않았습니다")


def _check(client, headers, sid, key=KEY):
    return client.get(_url(sid, "/by-key"), params={"request_key": key}, headers=headers)


def test_check_by_key_returns_the_stored_results_and_never_dispatches(client, user, session, sid, conn, fake_channel,
                                                                      spy):
    ids = _people(session, sid, 2)
    first = _post(client, user, sid, ids)
    dispatched = len(spy)

    got = _check(client, user, sid)

    assert got.status_code == 200, got.json()
    assert got.json() == {**first.json(), "replayed": True}
    assert len(spy) == dispatched and len(fake_channel.delivered) == 2 and _count(session) == 2


def test_check_by_key_for_a_request_that_never_arrived_is_404_and_makes_nothing(client, user, session, sid, conn,
                                                                                fake_channel, spy):
    _people(session, sid, 2)
    before = _count(session)

    got = _check(client, user, sid, key="never-arrived-01")

    assert (got.status_code, (got.json()["code"], got.json()["message"])) == (404, NOT_REACHED)
    assert spy == [] and fake_channel.delivered == [] and _count(session) == before


def test_check_by_key_is_scoped_to_the_person_and_project(client, user, admin, session, sid, sid2, conn, fake_channel):
    ids = _people(session, sid, 1)
    _post(client, user, sid, ids)

    assert _check(client, admin, sid).status_code == 404  # 다른 사람
    assert _check(client, user, sid2).status_code == 404  # 다른 일정
    assert _check(client, user, sid).status_code == 200


@pytest.mark.parametrize("key", ["짧음", "", "a" * 65, "bad key!!"])
def test_check_by_key_needs_a_well_formed_key(client, user, sid, key):
    assert _check(client, user, sid, key=key).status_code == 422


def test_check_by_key_reports_in_progress_while_young(client, user, session, sid, conn, fake_channel):
    ids = _people(session, sid, 2)
    r = _post(client, user, sid, ids)
    rows = _rows(session, r.json()["batch_id"])
    rows[1].status, rows[1].harness_json = "draft", []
    for row in rows:
        row.created_at = WORK - timedelta(seconds=10)
    session.commit()

    got = _check(client, user, sid)

    assert got.json()["in_progress"] is True
    assert [x["outcome"]["code"] for x in got.json()["results"]] == ["accepted", "in_progress"]


@pytest.mark.parametrize(("age_s", "code"), [(10, "in_progress"), (20 * 15 + 1, "unsure")])
def test_row_stuck_sending_is_unsure_once_the_batch_is_old(client, user, session, sid, conn, fake_channel, age_s, code):
    ids = _people(session, sid, 1)
    r = _post(client, user, sid, ids)
    row = _rows(session, r.json()["batch_id"])[0]
    row.status, row.created_at = "sending", WORK - timedelta(seconds=age_s)
    session.commit()

    got = _check(client, user, sid)

    assert got.json()["results"][0]["outcome"]["code"] == code
    assert got.json()["in_progress"] is (code == "in_progress")


def test_check_route_is_mounted(client, user, sid):
    assert "/api/schedules/{schedule_id}/outreach/batches/by-key" in set(client.app.openapi()["paths"])
