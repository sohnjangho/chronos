"""차단 목록 API(계획 4 Task 70). 번호는 가린 꼴만 · 「모르는 번호」 묶음에서 peer_key 로 바로 차단(번호를 내리지 않음) ·
관리자만. 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md."""

from sqlalchemy import select

from app.outreach import phone
from app.store.tables_outreach import BlockedNumber, OutreachCall, OutreachMessage
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

URL = "/api/notify/blocked"
PREMIUM = "060-700-0199"


def test_blocked_list_is_masked_and_admin_only(client, admin, user):
    r = client.post(URL, json={"number": SENTINEL_PHONE, "reason": "광고 전화"}, headers=admin)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["number_masked"] == "010-****-0199" and row["reason"] == "광고 전화" and row["created_by"]
    assert set(row) == {"id", "number_masked", "reason", "created_by", "created_at"}
    listed = client.get(URL, headers=admin)
    assert listed.status_code == 200 and [b["id"] for b in listed.json()] == [row["id"]]
    assert SENTINEL_DIGITS not in listed.text.replace("-", "") and SENTINEL_DIGITS not in r.text.replace("-", "")
    for method, path, body in (("GET", URL, None), ("POST", URL, {"number": "010-0000-0198"}),
                               ("DELETE", f"{URL}/{row['id']}", None)):
        got = client.request(method, path, json=body, headers=user)
        assert got.status_code == 403 and got.json()["code"] == "admin_only"
    assert client.get(URL).status_code == 401


def test_block_by_number_rules(client, admin, session):
    r = client.post(URL, json={"number": PREMIUM}, headers=admin)  # 060 도 막을 수 있다
    assert r.status_code == 201 and r.json()["number_masked"] == "060-****-0199"
    for raw in ("abc", "010-0000-01995"):
        bad = client.post(URL, json={"number": raw}, headers=admin)
        assert bad.status_code == 422 and bad.json()["code"] == "invalid_number" and "01995" not in bad.text
    client.post(URL, json={"number": SENTINEL_PHONE}, headers=admin)
    again = client.post(URL, json={"number": "+82 10 0000 0199"}, headers=admin)  # 꼴이 달라도 같은 번호
    assert again.status_code == 409 and again.json()["code"] == "already_blocked"
    assert set(session.scalars(select(BlockedNumber.number))) == {"0607000199", SENTINEL_DIGITS}
    for body in ({}, {"number": SENTINEL_PHONE, "peer_key": "0123456789ab"}, {"reason": "x"}):
        got = client.post(URL, json=body, headers=admin)
        assert got.status_code == 422 and got.json()["code"] == "number_or_peer_key", body
    assert client.post(URL, json={"number": "010-0000-0198", "reason": "x" * 201}, headers=admin).status_code == 422


def test_block_by_peer_key_never_returns_number(client, admin, session):
    session.add(OutreachMessage(direction="in", channel="sms", origin="peer", peer_number=SENTINEL_DIGITS))
    session.add(OutreachCall(direction="in", origin="peer", peer_number="0220000199"))
    session.add(OutreachMessage(direction="in", channel="sms", origin="peer", peer_number=phone.NO_NUMBER))
    session.commit()
    r = client.post(URL, json={"peer_key": phone.peer_key(SENTINEL_DIGITS), "reason": "모르는 번호"}, headers=admin)
    assert r.status_code == 201 and r.json()["number_masked"] == "010-****-0199"
    assert SENTINEL_DIGITS not in r.text
    call = client.post(URL, json={"peer_key": phone.peer_key("0220000199")}, headers=admin)  # 통화 기록에서도 찾는다
    assert call.status_code == 201 and call.json()["number_masked"] == "02-****-0199"
    assert set(session.scalars(select(BlockedNumber.number))) == {SENTINEL_DIGITS, "0220000199"}
    none = client.post(URL, json={"peer_key": phone.peer_key(phone.NO_NUMBER)}, headers=admin)
    assert none.status_code == 422 and none.json()["code"] == "peer_has_no_number"
    missing = client.post(URL, json={"peer_key": phone.peer_key("010-0000-0198")}, headers=admin)
    assert missing.status_code == 404 and missing.json()["code"] == "peer_not_found"
    assert client.post(URL, json={"peer_key": "not-a-key"}, headers=admin).status_code == 422
    again = client.post(URL, json={"peer_key": phone.peer_key(SENTINEL_DIGITS)}, headers=admin)
    assert again.status_code == 409 and SENTINEL_DIGITS not in again.text


def test_reason_rules(client, admin):
    for bad in ("광고\u202e전화", "a\u0007b", "x\u2066y"):
        r = client.post(URL, json={"number": SENTINEL_PHONE, "reason": bad}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "invalid_text" and r.json()["detail"] == {"field": "reason"}
    r = client.post(URL, json={"number": "010-0000-0198", "reason": "x" * 201}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "too_long" and r.json()["detail"] == {"field": "reason", "max": 200}
    r = client.post(URL, json={"number": "010-0000-01981", "reason": "x"}, headers=admin)  # 41자 넘는 번호 아님 — 꼴이 틀림
    assert r.status_code == 422 and r.json()["code"] == "invalid_number"
    r = client.post(URL, json={"number": "1" * 41}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"] == {"field": "number", "max": 40} and "1111111111" not in r.text
    r = client.post(URL, json={"number": SENTINEL_PHONE, "reason": f"{SENTINEL_PHONE} 에서 광고\n두 번째 줄"},
                    headers=admin)
    assert r.status_code == 201 and SENTINEL_DIGITS not in r.text.replace("-", "")
    assert "광고" in r.json()["reason"]
    assert SENTINEL_DIGITS not in client.get(URL, headers=admin).text.replace("-", "")


def test_peer_key_searches_only_unknown_number_rows(client, admin, session):
    session.add(OutreachMessage(direction="in", channel="sms", origin="peer", peer_number=SENTINEL_DIGITS, schedule_id=1))
    session.commit()
    r = client.post(URL, json={"peer_key": phone.peer_key(SENTINEL_DIGITS)}, headers=admin)
    assert r.status_code == 404 and r.json()["code"] == "peer_not_found"


def test_concurrent_duplicate_block_is_409(client, admin, monkeypatch):
    from app.programs.notify_settings import blocked

    first = client.post(URL, json={"number": SENTINEL_PHONE}, headers=admin).json()
    real = blocked._existing
    calls = []

    def blind(session, number):  # 다른 요청이 사이에 넣은 것처럼 — 처음 검사는 못 보고 저장에서 부딪힌다
        calls.append(number)
        return None if len(calls) == 1 else real(session, number)

    monkeypatch.setattr(blocked, "_existing", blind)
    r = client.post(URL, json={"number": "+82 10 0000 0199"}, headers=admin)
    assert r.status_code == 409 and r.json() == {"code": "already_blocked", "message": "이미 차단한 번호입니다.",
                                                 "detail": {"id": first["id"]}}


def test_unblock(client, admin):
    row = client.post(URL, json={"number": SENTINEL_PHONE}, headers=admin).json()
    assert client.delete(f"{URL}/{row['id']}", headers=admin).status_code == 204
    assert client.get(URL, headers=admin).json() == []
    gone = client.delete(f"{URL}/{row['id']}", headers=admin)
    assert gone.status_code == 404 and gone.json()["code"] == "blocked_not_found"
