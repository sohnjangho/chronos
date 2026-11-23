"""알림 연결 API(계획 4 Task 70). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

키는 끝 4자리만 · 번호는 가린 꼴만 · 주소를 바꾸면 키를 다시 · 상한은 validate_limits 하나로 · 진단은 저장된 키로, 실제 문자는
send 가 참일 때 확인한 목록의 첫 허용 번호로만 · 나간 뒤 결과를 모르면 「확인 필요」로 남기고 다시 보내지 않음 · 진단은
연결마다 하나씩 · 제공사 호출 동안 DB 를 쥐지 않는다. 실제 제공사를 부르지 않는다.
"""

import ast
import asyncio
import inspect
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, select

from app import db
from app.db import get_session
from app.main import app
from app.notify import diagnostics
from app.notify.diagnostics import DiagnosticStep
from app.outreach import provider, redact
from app.outreach.provider import ProviderFailed
from app.programs.notify_settings import diagnose as diagnose_mod
from app.programs.notify_settings import router as router_mod
from app.programs.notify_settings.schemas import ConnectionTestIn, DiagnoseIn
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import NotifyConnection, OutreachMessage
from tests.helpers import auth
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)
from tests.provider_doubles import KAT_ACCOUNT, KAT_SENDER, KatMock

BASE = "/api/notify/connections"
NEW = {"name": "한국AI통신", "secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}
NEW_KEY = "kat-test-key-NEWW8888"
LANDLINE = "02-2000-0199"
OTHER_MOBILE = "010-0000-0198"
PREMIUM = "060-700-0199"
PKG = Path(__file__).resolve().parents[2] / "app" / "programs" / "notify_settings"
SENDER_0 = {"index": 0, "number_masked": "070-****-0123", "kind": "internet", "label": "발신번호 1"}


def create(client, admin, **over) -> dict:
    r = client.post(BASE, json={**NEW, **over}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def patch(client, admin, conn_id: int, **body):
    return client.patch(f"{BASE}/{conn_id}", json=body, headers=admin)


def with_numbers(client, admin, *numbers: str) -> dict:
    conn = create(client, admin)
    r = patch(client, admin, conn["id"], allow_numbers_add=list(numbers))
    assert r.status_code == 200, r.text
    return r.json()


def send_body(conn: dict, **over) -> dict:
    return {"steps": ["P2", "P3"], "send": True, "allow_numbers_version": conn["allow_numbers_version"], **over}


def diagnose(client, admin, conn_id: int, body: dict):
    return client.post(f"{BASE}/{conn_id}/diagnose", json=body, headers=admin)


def steps(*ids: str, ok: bool = True, detail: str = "HTTP 200") -> list[DiagnosticStep]:
    return [DiagnosticStep(id=i, label=diagnostics.LABELS[i], ok=ok, detail=detail, latency_ms=3,
                           code="ok" if ok else "server") for i in ids]


class Spy:
    """run_checks 대역 — 덩어리(P1 · P2+P3 · P4)마다 불린다. 넘어온 값을 적고 정해 둔 걸음 가운데 그 덩어리 것을 돌려준다."""

    def __init__(self, result=None) -> None:
        self.calls: list[dict] = []
        self.result = result

    async def __call__(self, conn, http, *, send_test_sms=False, steps=(1, 2, 3, 4), **_kw):
        self.calls.append({"conn": conn, "send": send_test_sms, "steps": list(steps), "trust_env": http.trust_env})
        if self.result is not None:
            return self.result
        return [DiagnosticStep(id=s, label=diagnostics.LABELS[s], ok=True, detail="HTTP 200", latency_ms=3, code="ok")
                for s in steps]

    @property
    def chunks(self) -> list[list[str]]:
        return [c["steps"] for c in self.calls]


@pytest.fixture
def spy(monkeypatch) -> Spy:
    found = Spy()
    monkeypatch.setattr(diagnostics, "run_checks", found)
    return found


@pytest.fixture
def kat(monkeypatch) -> KatMock:
    """실제 KatClient·진단 걸음 + 가짜 서버(전송 층). 진단 클라이언트도 이 가짜로 — transport 를 받는 꼴 그대로."""
    mock = KatMock()
    monkeypatch.setattr(provider, "_default_transport", lambda: mock)
    real_make = diagnostics.make_client
    monkeypatch.setattr(diagnostics, "make_client", lambda *, transport=None: real_make(transport=transport or mock))
    monkeypatch.setattr(diagnostics, "POLL_GAP_S", 0)
    return mock


def posts(mock: KatMock) -> int:
    return sum(1 for r in mock.requests if r.method == "POST")


@pytest.fixture
def field(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


# ── 만들기·보기 ─────────────────────────────────────────────────────


def test_create_shows_last4_only(client, admin, fake_provider, session):
    r = client.post(BASE, json=NEW, headers=admin)
    assert r.status_code == 201
    body = r.json()
    assert SENTINEL_KEY not in r.text and KAT_ACCOUNT not in r.text
    assert body["secret_last4"] == "9999" and body["account_id_masked"] == "…3c4d"
    assert body["senders"] == [SENDER_0] and body["sender_index"] == 0
    assert body["sender_number_masked"] == "070-****-0123"
    assert body["status"] == "ok" and body["error"] is None and fake_provider.log == ["check"]
    row = session.get(NotifyConnection, body["id"])
    assert SENTINEL_KEY not in row.secret_ciphertext and row.sender_number == "07000000123"
    listed = client.get(BASE, headers=admin)
    assert listed.status_code == 200 and SENTINEL_KEY not in listed.text and [c["id"] for c in listed.json()] == [body["id"]]


def test_account_id_is_hidden_from_request_repr():
    body = ConnectionTestIn(secret=SENTINEL_KEY, account_id=KAT_ACCOUNT)
    assert KAT_ACCOUNT not in repr(body) and SENTINEL_KEY not in repr(body)


def test_defaults_are_safe(client, admin, fake_provider):
    b = create(client, admin)
    assert b["test_mode"] is True and b["agent_call"] == "approve" and b["inbound_mode"] == "off"
    assert b["agent_sms"] == "approve" and b["agent_kakao"] == "approve" and b["kakao_channel"] is None
    assert b["is_default"] is True and b["allow_numbers"] == [] and b["test_sms_index"] is None
    assert b["used_today"] == {"sms": 0, "call": 0}
    assert b["limits"] == {**outreach.limits(None).__dict__}
    second = create(client, admin, name="둘째")
    assert second["is_default"] is False and second["used_today"] is None
    assert [c["used_today"] for c in client.get(BASE, headers=admin).json()] == [{"sms": 0, "call": 0}, None]


def test_create_rejects_bad_inputs_without_echo(client, admin, fake_provider):
    for over, code in (({"secret": "short"}, "invalid_secret"), ({"secret": "kat key with space"}, "invalid_secret"),
                       ({"account_id": "AC 0000 0000"}, "invalid_account_id"),
                       ({"base_url": "http://api.koreaaitel.com"}, "bad_base_url"),
                       ({"base_url": "https://127.0.0.1"}, "bad_base_url")):
        r = client.post(BASE, json={**NEW, **over}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == code, (over, r.text)
        assert SENTINEL_KEY not in r.text
    assert fake_provider.log == []


def test_too_long_inputs_name_the_field(client, admin, fake_provider):
    for over, field, limit in (({"name": "가" * 101}, "name", 100), ({"account_id": "A" * 101}, "account_id", 100),
                               ({"base_url": "https://a" + "b" * 500 + ".com"}, "base_url", 500)):
        r = client.post(BASE, json={**NEW, **over}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "too_long", (field, r.text)
        assert r.json()["detail"] == {"field": field, "max": limit} and "bbbbbb" not in r.text
    r = client.post(BASE, json={**NEW, "name": "   "}, headers=admin)
    assert r.status_code == 422 and r.json() == {"code": "required", "message": "이름을 넣어 주세요.",
                                                 "detail": {"field": "name"}}
    cid = create(client, admin)["id"]
    for body, field, limit in (({"kakao_channel": "@" * 101}, "kakao_channel", 100),
                               ({"allow_numbers_add": [SENTINEL_PHONE] * 51}, "allow_numbers_add", 50),
                               ({"allow_numbers_add": ["0" * 41]}, "allow_numbers_add", 40),
                               ({"allow_numbers_remove": [0] * 51, "allow_numbers_version": "x"},
                                "allow_numbers_remove", 50),
                               ({"handoff_number": "1" * 41}, "handoff_number", 40)):
        r = patch(client, admin, cid, **body)
        assert r.status_code == 422 and r.json()["code"] == "too_long", (field, r.text)
        assert r.json()["detail"] == {"field": field, "max": limit}
        assert "0000000000" not in r.text and "1111111111" not in r.text


def test_allow_numbers_are_masked_and_removed_by_index(client, admin, fake_provider, session):
    b = with_numbers(client, admin, SENTINEL_PHONE, LANDLINE, OTHER_MOBILE, "+82 10-0000-0199")  # 마지막은 첫 번호와 같다
    assert SENTINEL_DIGITS not in json.dumps(b, ensure_ascii=False)
    assert b["allow_numbers"] == [
        {"index": 0, "number_masked": "010-****-0199", "kind": "mobile", "can_test_sms": True},
        {"index": 1, "number_masked": "02-****-0199", "kind": "landline", "can_test_sms": False},
        {"index": 2, "number_masked": "010-****-0198", "kind": "mobile", "can_test_sms": True},
    ]
    assert b["test_sms_index"] == 0
    cid, version = b["id"], b["allow_numbers_version"]
    assert SENTINEL_DIGITS not in version and len(version) >= 16

    r = patch(client, admin, cid, allow_numbers_remove=[0])
    assert r.status_code == 422 and r.json()["code"] == "allow_version_required"
    r = patch(client, admin, cid, allow_numbers_remove=[3], allow_numbers_version=version)
    assert r.status_code == 422 and r.json()["code"] == "invalid_index"
    r = patch(client, admin, cid, allow_numbers_remove=[0], allow_numbers_version=version)
    assert r.status_code == 200
    after = r.json()
    assert [a["number_masked"] for a in after["allow_numbers"]] == ["02-****-0199", "010-****-0198"]
    assert after["test_sms_index"] is None  # 첫 번호가 유선 — 시험 문자를 받을 수 없다
    r = patch(client, admin, cid, allow_numbers_remove=[0], allow_numbers_version=version)  # 낡은 판
    assert r.status_code == 409 and r.json()["code"] == "allow_list_changed"
    session.expire_all()
    assert session.get(NotifyConnection, cid).allow_numbers_json == ["0220000199", "01000000198"]


def test_bad_numbers_are_refused_without_echo(client, admin, fake_provider):
    cid = create(client, admin)["id"]
    for raw in (PREMIUM, "010-0000-01995", "abc"):
        r = patch(client, admin, cid, allow_numbers_add=[SENTINEL_PHONE, raw])
        assert r.status_code == 422 and r.json()["code"] == "invalid_number", r.text
        assert r.json()["detail"] == {"field": "allow_numbers_add", "index": 1}
        assert "0607000199" not in r.text and "700-0199" not in r.text and "01995" not in r.text
    r = patch(client, admin, cid, handoff_number=PREMIUM)
    assert r.status_code == 422 and r.json()["detail"] == {"field": "handoff_number"}
    r = patch(client, admin, cid, handoff_number=LANDLINE)
    assert r.status_code == 200 and r.json()["handoff_number_masked"] == "02-****-0199"
    assert patch(client, admin, cid, handoff_number=None).json()["handoff_number_masked"] is None
    assert patch(client, admin, cid).json()["allow_numbers"] == []  # 거절된 요청은 아무것도 바꾸지 않았다


def test_patch_fields_strict_booleans_kakao_and_sender_index(client, admin, fake_provider):
    fake_provider.senders = ["07000000123", "07100000123"]  # 끝 4자리가 같아도 순번 이름표로 가른다
    cid = create(client, admin)["id"]
    r = patch(client, admin, cid, test_mode=False, agent_sms="delegate", agent_call="delegate", inbound_mode="known",
              sender_index=1, name="새 이름")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["test_mode"], b["agent_sms"], b["agent_call"], b["inbound_mode"], b["name"]) == (
        False, "delegate", "delegate", "known", "새 이름")
    assert b["sender_index"] == 1 and [s["label"] for s in b["senders"]] == ["발신번호 1", "발신번호 2"]
    assert [s["index"] for s in b["senders"]] == [0, 1] and b["senders"][0]["kind"] == "internet"
    for bad in ({"test_mode": "true"}, {"test_mode": 1}, {"sender_index": "1"}, {"agent_sms": "always"}):
        r = patch(client, admin, cid, **bad)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request", bad
    r = patch(client, admin, cid, sender_index=2)
    assert r.status_code == 422 and r.json()["code"] == "invalid_index"
    for bad in ({"agent_kakao": "delegate"}, {"kakao_channel": "@chronos"}):
        r = patch(client, admin, cid, **bad)
        assert r.status_code == 422 and r.json()["code"] == "kakao_not_ready", bad
    assert patch(client, admin, cid, kakao_channel=None, agent_kakao="approve").status_code == 200
    assert fake_provider.log == ["check"]  # 위 고침들은 제공사를 다시 부르지 않았다


def test_is_default_moves(client, admin, fake_provider):
    first, second = create(client, admin), create(client, admin, name="둘째")
    assert patch(client, admin, second["id"], is_default=True).json()["is_default"] is True
    rows = {c["id"]: c["is_default"] for c in client.get(BASE, headers=admin).json()}
    assert rows == {first["id"]: False, second["id"]: True}


# ── 연결 테스트 ───────────────────────────────────────────────────────


def test_probe_result_is_masked(client, admin, fake_provider):
    r = client.post(f"{BASE}/test", json={"secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}, headers=admin)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "latency_ms": 1, "senders": [SENDER_0], "error": None}
    assert SENTINEL_KEY not in r.text and "07000000123" not in r.text
    assert client.get(BASE, headers=admin).json() == []  # 저장하지 않았다
    cid = create(client, admin)["id"]
    fake_provider.senders = ["07000000456"]
    again = client.post(f"{BASE}/{cid}/test", headers=admin).json()
    assert [s["number_masked"] for s in again["senders"]] == ["070-****-0456"]
    shown = client.get(BASE, headers=admin).json()[0]
    assert shown["senders"][0]["number_masked"] == "070-****-0456" and shown["sender_index"] == 0


def test_test_only_secrets_leave_the_registry(client, admin, fake_provider):
    other_account = "AC00000000OTHER1"
    r = client.post(f"{BASE}/test", json={"secret": NEW_KEY, "account_id": other_account}, headers=admin)
    assert r.status_code == 200
    assert NEW_KEY not in redact.secrets() and other_account not in redact.secrets()
    create(client, admin)  # 저장된 연결이 쓰는 값은 남는다
    client.post(f"{BASE}/test", json={"secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}, headers=admin)
    assert SENTINEL_KEY in redact.secrets() and KAT_ACCOUNT in redact.secrets()


def test_bad_key_error_has_no_key(client, admin, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    mock = KatMock(key="kat-test-key-OTHER0000")
    monkeypatch.setattr(provider, "_default_transport", lambda: mock)  # 실제 KatClient, 가짜 서버가 401
    r = client.post(f"{BASE}/test", json={"secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}, headers=admin)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]["code"] == "bad_key"
    assert SENTINEL_KEY not in r.text and KAT_ACCOUNT not in r.text and mock.requests
    saved = client.post(BASE, json=NEW, headers=admin)
    assert saved.status_code == 201 and saved.json()["status"] == "failed" and saved.json()["error"]["code"] == "bad_key"
    assert SENTINEL_KEY not in saved.text
    assert_clean(caplog, KAT_ACCOUNT)


def test_overseas_ip_and_timeouts_are_explained(client, admin, fake_provider, monkeypatch):
    fake_provider.fail = ProviderFailed("overseas_ip", "x")
    err = client.post(f"{BASE}/test", json={"secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}, headers=admin).json()
    assert err["error"]["code"] == "overseas_ip" and "나라 밖 IP 에서는 보낼 수 없습니다" in err["error"]["message"]

    async def stuck():
        await asyncio.sleep(5)

    fake_provider.fail = None
    monkeypatch.setattr(fake_provider, "check", stuck)
    from app.programs.notify_settings import service

    monkeypatch.setattr(service, "CHECK_CEILING_S", 0.05)
    err = client.post(f"{BASE}/test", json={"secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}, headers=admin).json()
    assert err["ok"] is False and err["error"]["code"] == "timeout"


def test_changing_base_url_needs_the_key_again(client, admin, fake_provider):
    cid = create(client, admin)["id"]
    r = patch(client, admin, cid, base_url="https://api.koreaaitel.com")  # 같은 서버로 보여도
    assert r.status_code == 422 and r.json() == {"code": "secret_required",
                                                 "message": "주소를 바꾸면 API 키를 다시 넣어 주세요.", "detail": None}
    r = patch(client, admin, cid, base_url="https://api2.koreaaitel.com", secret=NEW_KEY)
    assert r.status_code == 200 and r.json()["base_url"] == "https://api2.koreaaitel.com"
    assert r.json()["secret_last4"] == "8888" and fake_provider.log == ["check", "check"]


def test_unreadable_stored_key_is_409(client, admin, fake_provider, session, spy):
    cid = create(client, admin)["id"]
    session.get(NotifyConnection, cid).secret_ciphertext = "garbage"
    session.commit()
    r = diagnose(client, admin, cid, {})
    assert r.status_code == 409 and r.json()["code"] == "secret_unreadable" and spy.calls == []


# ── 권한·길 꼴 ────────────────────────────────────────────────────────


def test_user_cannot_manage(client, user, admin, fake_provider):
    cid = create(client, admin)["id"]
    for method, path, body in (("get", BASE, None), ("post", f"{BASE}/test", NEW), ("post", BASE, NEW),
                               ("patch", f"{BASE}/{cid}", {"name": "x"}), ("post", f"{BASE}/{cid}/test", None),
                               ("delete", f"{BASE}/{cid}", None), ("get", f"{BASE}/{cid}/limits", None),
                               ("put", f"{BASE}/{cid}/limits", {}), ("post", f"{BASE}/{cid}/limits/reset", None),
                               ("get", f"{BASE}/{cid}/diagnosis", None)):
        r = client.request(method.upper(), path, json=body, headers=user)
        assert r.status_code == 403 and r.json()["code"] == "admin_only", (method, path)
    assert client.get(BASE).status_code == 401


def test_diagnose_is_admin_only(client, user, admin, fake_provider, spy):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    r = diagnose(client, user, b["id"], send_body(b))
    assert r.status_code == 403 and spy.calls == []


def test_database_only_routes_are_plain_functions():
    plain = ("list_connections", "delete_connection", "get_limits", "put_limits", "reset_limits", "last_diagnosis",
             "notify_status", "list_blocked", "block_number", "unblock_number")
    assert not [name for name in plain if inspect.iscoroutinefunction(getattr(router_mod, name))]


def test_status_for_users_but_not_field(client, admin, user, field, fake_provider):
    empty = client.get("/api/notify/status", headers=user).json()
    assert empty == {"ready": False, "test_mode": True, "allow_count": 0,
                     "agent": {"sms": "approve", "kakao": "approve", "call": "approve"}, "inbound_mode": "off",
                     "kakao_ready": False}
    b = with_numbers(client, admin, SENTINEL_PHONE, LANDLINE)
    patch(client, admin, b["id"], agent_sms="delegate", inbound_mode="all")
    got = client.get("/api/notify/status", headers=user).json()
    assert got["ready"] is True and got["allow_count"] == 2 and got["agent"]["sms"] == "delegate"
    assert got["inbound_mode"] == "all" and got["kakao_ready"] is False
    r = client.get("/api/notify/status", headers=field)
    assert r.status_code == 403 and r.json()["code"] == "field_no_contacts"


# ── 지우기 ───────────────────────────────────────────────────────────


def test_delete_with_history_is_409(client, admin, session, fake_provider):
    cid = create(client, admin)["id"]
    session.add(OutreachMessage(direction="out", channel="sms", origin="user", peer_number=SENTINEL_DIGITS))
    session.commit()
    r = client.delete(f"{BASE}/{cid}", headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "has_history"
    assert r.json()["message"] == "연락 기록이 있어 지울 수 없습니다"
    spare = create(client, admin, name="예비")["id"]  # 기본이 아닌 연결은 기록과 상관없이 지운다
    assert client.delete(f"{BASE}/{spare}", headers=admin).status_code == 204
    session.query(OutreachMessage).delete()
    session.commit()
    assert client.delete(f"{BASE}/{cid}", headers=admin).status_code == 204
    assert client.get(BASE, headers=admin).json() == []
    assert client.delete(f"{BASE}/{cid}", headers=admin).json()["code"] == "connection_not_found"


def test_deleting_default_promotes_oldest_and_keeps_shared_secret(client, admin, fake_provider):
    first = create(client, admin)["id"]
    second = create(client, admin, name="둘째")["id"]
    third = create(client, admin, name="셋째", secret=NEW_KEY)["id"]
    assert client.delete(f"{BASE}/{first}", headers=admin).status_code == 204
    rows = {c["id"]: c["is_default"] for c in client.get(BASE, headers=admin).json()}
    assert rows == {second: True, third: False}
    assert SENTINEL_KEY in redact.secrets()  # 둘째가 같은 키를 쓴다
    assert client.delete(f"{BASE}/{third}", headers=admin).status_code == 204
    assert NEW_KEY not in redact.secrets() and KAT_ACCOUNT in redact.secrets()


# ── 비밀 등록부 ──────────────────────────────────────────────────────


def test_secrets_are_registered_before_diagnosis_and_old_key_dropped_on_replace(client, admin, fake_provider,
                                                                                monkeypatch, caplog):
    cid = create(client, admin)["id"]
    assert SENTINEL_KEY in redact.secrets() and KAT_ACCOUNT in redact.secrets()
    r = patch(client, admin, cid, secret=NEW_KEY)
    assert r.status_code == 200 and r.json()["secret_last4"] == "8888"
    assert NEW_KEY in redact.secrets() and SENTINEL_KEY not in redact.secrets()

    redact.forget_secrets()  # 프로세스를 새로 띄운 것처럼 — 진단이 스스로 올려야 한다
    seen = []
    real_run = diagnostics.run_checks

    async def run(conn, http, **kw):
        seen.append(NEW_KEY in redact.secrets() and KAT_ACCOUNT in redact.secrets())
        return await real_run(conn, http, **kw)

    mock = KatMock(key=NEW_KEY)
    real_make = diagnostics.make_client
    monkeypatch.setattr(diagnostics, "run_checks", run)
    monkeypatch.setattr(diagnostics, "make_client", lambda *, transport=None: real_make(transport=transport or mock))
    caplog.set_level(logging.INFO)
    out = diagnose(client, admin, cid, {"steps": ["P1"]})
    assert out.status_code == 200 and out.json()["steps"][0]["ok"] is True, out.text
    assert seen == [True] and mock.requests and KAT_ACCOUNT in str(mock.requests[0].url)
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "httpx"]
    assert lines and not any(KAT_ACCOUNT in line or NEW_KEY in line for line in lines)


def test_clients_are_called_by_module_attribute():
    names = {"client_for", "make_client", "run_checks"}
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ("app.outreach.provider", "app.notify.diagnostics"):
                assert not names & {a.name for a in node.names}, f"{path.name}: {ast.unparse(node)}"
    source = "\n".join(p.read_text() for p in PKG.glob("*.py"))
    assert "provider.client_for(" in source and "diagnostics.make_client(" in source
    assert "diagnostics.run_checks(" in source


# ── 상한 ─────────────────────────────────────────────────────────────


def test_limits_read_update_validate_and_reset(client, admin, fake_provider, session):
    cid = create(client, admin)["id"]
    got = client.get(f"{BASE}/{cid}/limits", headers=admin).json()
    assert got["values"] == got["defaults"] and got["defaults"]["per_contact_sms_daily"] == 5
    assert got["ranges"]["max_call_seconds"] == [30, 7200] and set(got["ranges"]) == set(outreach.LIMIT_RANGES)
    assert set(got["values"]) == set(got["defaults"]) == set(outreach.LIMIT_RANGES)
    r = client.put(f"{BASE}/{cid}/limits", json={"per_contact_sms_daily": 3}, headers=admin)
    assert r.status_code == 200 and r.json()["values"]["per_contact_sms_daily"] == 3
    assert r.json()["defaults"]["per_contact_sms_daily"] == 5
    session.expire_all()
    assert outreach.limits(session.get(NotifyConnection, cid)).per_contact_sms_daily == 3
    for bad, field in (({"max_call_seconds": 10}, "max_call_seconds"), ({"daily_sms_total": "50"}, "daily_sms_total"),
                       ({"daily_sms_total": True}, "daily_sms_total"),
                       ({"per_contact_sms_daily": 60}, "per_contact_sms_daily")):
        r = client.put(f"{BASE}/{cid}/limits", json=bad, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "invalid_limits" and field in r.json()["detail"], bad
    r = client.put(f"{BASE}/{cid}/limits", json={"nope": 1, SENTINEL_KEY: 2, "daily_calls_total": -1}, headers=admin)
    assert r.status_code == 422 and SENTINEL_KEY not in r.text and "nope" not in r.text  # 모르는 칸은 이름을 싣지 않는다
    assert r.json()["detail"] == {"unknown_fields": 2, "daily_calls_total": "0~10,000 사이로 넣어 주세요."}
    assert client.put(f"{BASE}/{cid}/limits", json=[1], headers=admin).status_code == 422
    assert client.get(BASE, headers=admin).json()[0]["limits"]["per_contact_sms_daily"] == 3
    r = client.post(f"{BASE}/{cid}/limits/reset", headers=admin)
    assert r.status_code == 200 and r.json()["values"] == r.json()["defaults"]
    session.expire_all()
    assert session.get(NotifyConnection, cid).limits_json is None


def test_limits_are_saved_in_one_write_transaction(client, admin, fake_provider):
    cid = create(client, admin)["id"]
    seen: list[str] = []

    def record(conn, cursor, statement, *_args):
        seen.append(statement.strip().split()[0].upper() + (" IMMEDIATE" if "IMMEDIATE" in statement.upper() else ""))

    engine = db._engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert client.put(f"{BASE}/{cid}/limits", json={"daily_calls_total": 7}, headers=admin).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    begin = seen.index("BEGIN IMMEDIATE")
    assert "UPDATE" in seen[begin:] and "SELECT" in seen[begin:seen.index("UPDATE", begin)]  # 읽기와 쓰기가 한 덩어리


def test_limits_are_stored_only_in_limits_json(client, admin, fake_provider, session):
    cid = create(client, admin)["id"]
    client.put(f"{BASE}/{cid}/limits", json={"per_contact_sms_daily": 3}, headers=admin)
    client.put(f"{BASE}/{cid}/limits", json={"daily_calls_total": 7}, headers=admin)
    session.expire_all()
    assert session.get(NotifyConnection, cid).limits_json == {"per_contact_sms_daily": 3, "daily_calls_total": 7}


def test_limits_api_uses_validate_limits_only(client, admin, fake_provider, monkeypatch):
    cid = create(client, admin)["id"]
    seen = []
    real = outreach.validate_limits

    def spy_validate(values):
        seen.append(dict(values))
        return real(values)

    monkeypatch.setattr(outreach, "validate_limits", spy_validate)
    client.put(f"{BASE}/{cid}/limits", json={"per_contact_sms_daily": 3}, headers=admin)
    client.put(f"{BASE}/{cid}/limits", json={"max_call_seconds": 1}, headers=admin)
    assert seen == [{"per_contact_sms_daily": 3}, {"per_contact_sms_daily": 3, "max_call_seconds": 1}]
    source = "\n".join(p.read_text() for p in PKG.glob("*.py"))
    assert source.count("LIMIT_RANGES") == 1  # 화면에 범위를 알려 주는 한 곳뿐 — 범위 검사는 없다


def test_patch_connection_does_not_accept_limits(client, admin, fake_provider, session):
    cid = create(client, admin)["id"]
    for body in ({"limits": {"per_contact_sms_daily": 3}}, {"per_contact_sms_daily": 3}):
        r = patch(client, admin, cid, **body)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    session.expire_all()
    assert session.get(NotifyConnection, cid).limits_json is None


# ── 진단 ─────────────────────────────────────────────────────────────


def test_diagnose_runs_with_stored_key_and_returns_step_lines(client, admin, fake_provider, spy):
    cid = create(client, admin)["id"]
    r = diagnose(client, admin, cid, {"steps": ["P1", "P4"]})
    assert r.status_code == 200, r.text
    assert spy.chunks == [["P1"], ["P4"]]
    for call in spy.calls:
        assert call["conn"].key == SENTINEL_KEY and call["conn"].account_id == KAT_ACCOUNT
        assert call["send"] is False and call["trust_env"] is False and call["conn"].test_to == ""
    body = r.json()
    assert body["sent_real"] is False and body["sent_unknown"] is False and body["state"] == "done"
    assert [s["id"] for s in body["steps"]] == ["P1", "P2", "P3", "P4"]  # 늘 넷 — 고르지 않은 것은 skipped
    assert [(s["ok"], s["skipped"], s["code"]) for s in body["steps"]] == [
        (True, False, "ok"), (False, True, "skipped_not_requested"), (False, True, "skipped_not_requested"),
        (True, False, "ok")]
    assert set(body["steps"][0]) == {"id", "label", "ok", "skipped", "detail", "latency_ms", "notes", "code",
                                     "maybe_sent", "pending"}
    assert body["by"] and body["sends"] == []
    assert client.get(f"{BASE}/{cid}/diagnosis", headers=admin).json() == body
    diagnose(client, admin, cid, {})
    assert spy.chunks[2:] == [["P1"], ["P2", "P3"], ["P4"]]
    for bad in ({"steps": ["P9"]}, {"send": "true"}, {"send": 1}, {"steps": []}, {"confirm_resend": "yes"}):
        assert diagnose(client, admin, cid, bad).status_code == 422, bad


def test_diagnosis_is_null_before_first_run(client, admin, fake_provider):
    cid = create(client, admin)["id"]
    r = client.get(f"{BASE}/{cid}/diagnosis", headers=admin)
    assert r.status_code == 200 and r.json() is None
    assert client.get(f"{BASE}/999/diagnosis", headers=admin).json()["code"] == "connection_not_found"


def test_diagnose_real_send_only_when_requested_and_only_to_first_allowed_number(client, admin, fake_provider, spy):
    cid = create(client, admin)["id"]
    r = diagnose(client, admin, cid, {"steps": ["P2", "P3"], "send": True})
    assert r.status_code == 422 and r.json()["message"] == "허용 번호를 먼저 넣어 주세요" and spy.calls == []
    landline = patch(client, admin, cid, allow_numbers_add=[LANDLINE, SENTINEL_PHONE]).json()
    r = diagnose(client, admin, cid, send_body(landline))
    assert r.status_code == 422 and r.json()["code"] == "test_number_not_mobile" and spy.calls == []

    b = with_numbers(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    diagnose(client, admin, b["id"], {"steps": ["P2", "P3"]})
    assert spy.calls[-1]["send"] is False and spy.calls[-1]["conn"].test_to == ""
    r = diagnose(client, admin, b["id"], send_body(b))
    assert r.status_code == 200 and r.json()["sent_real"] is True
    last = spy.calls[-1]
    assert last["send"] is True and last["conn"].test_to == SENTINEL_DIGITS and last["conn"].sender == "07000000123"


def test_send_is_bound_to_the_confirmed_allow_list(client, admin, fake_provider, spy):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    r = diagnose(client, admin, b["id"], {"steps": ["P2"], "send": True})
    assert r.status_code == 422 and r.json()["code"] == "allow_version_required"
    changed = patch(client, admin, b["id"], allow_numbers_remove=[0], allow_numbers_add=[OTHER_MOBILE],
                    allow_numbers_version=b["allow_numbers_version"]).json()
    r = diagnose(client, admin, b["id"], send_body(b))  # 확인한 뒤 목록이 바뀌었다
    assert r.status_code == 409 and r.json()["code"] == "allow_list_changed" and spy.calls == []
    assert diagnose(client, admin, b["id"], send_body(changed)).status_code == 200
    assert spy.calls[-1]["conn"].test_to == "01000000198"


def test_diagnose_send_needs_a_sender(client, admin, fake_provider, spy):
    fake_provider.senders = []
    b = with_numbers(client, admin, SENTINEL_PHONE)
    assert b["test_sms_index"] is None
    r = diagnose(client, admin, b["id"], send_body(b, steps=["P2"]))
    assert r.status_code == 422 and r.json()["code"] == "no_sender" and spy.calls == []


def test_stored_diagnosis_has_no_key_or_number(client, admin, session, fake_provider, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    leak = f"{SENTINEL_KEY} {KAT_ACCOUNT} {SENTINEL_PHONE} 07000000123"
    bad = [DiagnosticStep(id="P2", label="x", ok=False, detail=f"http_500 · {leak}", notes=[leak])]
    monkeypatch.setattr(diagnostics, "run_checks", Spy(result=bad))
    r = diagnose(client, admin, b["id"], send_body(b, steps=["P2"]))
    session.expire_all()
    stored = json.dumps(session.get(NotifyConnection, b["id"]).last_diagnosis_json, ensure_ascii=False)
    for text in (r.text, stored, client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).text):
        assert SENTINEL_KEY not in text and KAT_ACCOUNT not in text
        assert SENTINEL_DIGITS not in text.replace("-", "") and "07000000123" not in text
    assert json.loads(stored)["real"] is False and "ran_at" in json.loads(stored)


def _hang_on(mock: KatMock, method: str, path_part: str, times: int = 1):
    """그 요청을 times 번까지 5초 붙든다(상한이 먼저 끊는다). 그 뒤로는 기본 답."""
    left = [times]

    def override(request: httpx.Request):
        if request.method == method and path_part in request.url.path and left[0] > 0:
            left[0] -= 1

            async def held():
                await asyncio.sleep(5)

            return held()
        return None

    mock.override = override


def test_ceiling_marks_send_unknown_and_refuses_a_second_send(client, admin, kat, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    monkeypatch.setattr(diagnose_mod, "DIAGNOSE_CEILING_S", 0.3)
    _hang_on(kat, "POST", "/messages")
    r = diagnose(client, admin, b["id"], send_body(b))
    assert r.status_code == 200 and posts(kat) == 1
    body = r.json()
    assert body["sent_real"] is False and body["sent_unknown"] is True
    p2, p3 = body["steps"][1], body["steps"][2]
    assert (p2["code"], p2["maybe_sent"], p2["ok"]) == ("timeout", True, False) and "보냈는지 알 수 없음" in p2["detail"]
    assert p3["code"] == "timeout" and body["steps"][0]["code"] == "skipped_not_requested"
    assert [s["outcome"] for s in body["sends"]] == ["unknown"] and not diagnose_mod._RUNNING
    assert client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).json()["sent_unknown"] is True

    again = diagnose(client, admin, b["id"], send_body(b))
    assert again.status_code == 409 and again.json()["code"] == "sent_unknown_pending" and posts(kat) == 1
    assert "휴대전화에 문자가 왔는지 먼저 확인해 주세요" in again.json()["message"]
    assert diagnose(client, admin, b["id"], {"steps": ["P1"]}).status_code == 200  # 보내지 않는 진단은 막지 않는다
    again = diagnose(client, admin, b["id"], send_body(b))  # 진단을 다시 돌려도 기록은 이어진다
    assert again.status_code == 409 and posts(kat) == 1
    monkeypatch.setattr(diagnose_mod, "DIAGNOSE_CEILING_S", 30)
    sure = diagnose(client, admin, b["id"], send_body(b, confirm_resend=True))
    assert sure.status_code == 200 and sure.json()["sent_real"] is True and posts(kat) == 2
    assert [s["outcome"] for s in sure.json()["sends"]] == ["unknown", "accepted"]


def test_ceiling_keeps_finished_steps_and_unknown_only_after_the_post(client, admin, kat, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    monkeypatch.setattr(diagnose_mod, "DIAGNOSE_CEILING_S", 0.3)
    _hang_on(kat, "GET", "/messages")  # P4(받은 문자 목록)에서 멈춘다
    body = diagnose(client, admin, b["id"], {}).json()
    assert body["steps"][0]["ok"] is True and body["steps"][3]["code"] == "timeout"
    assert body["sent_unknown"] is False

    _hang_on(kat, "GET", "/sender-numbers")  # 보내기 전(P1)에 멈춘다 — 문자는 나가지 않았다
    body = diagnose(client, admin, b["id"], send_body(b, steps=["P1", "P2", "P3"])).json()
    assert posts(kat) == 0 and body["sent_unknown"] is False and body["steps"][1]["maybe_sent"] is False
    assert [s["outcome"] for s in body["sends"]] == ["not_sent"]


@pytest.mark.parametrize("reply", [
    httpx.Response(500, json={"code": "internal", "error": "x"}),
    httpx.Response(502, text="bad gateway"),
    httpx.Response(504, text="timeout"),
    httpx.Response(409, json={"code": "conflict", "error": "x"}),
    httpx.Response(201, json={"status": "queued"}),  # messageId 없음
    httpx.Response(200, text="not json"),
], ids=["500", "502", "504", "409", "201-no-id", "200-not-json"])
def test_outcome_unknown_after_the_post_is_not_a_plain_failure(client, admin, kat, reply):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    kat.override = lambda request: reply if request.method == "POST" else None
    body = diagnose(client, admin, b["id"], send_body(b)).json()
    assert body["sent_real"] is False and body["sent_unknown"] is True and body["steps"][1]["maybe_sent"] is True
    assert [s["outcome"] for s in body["sends"]] == ["unknown"] and posts(kat) == 1


def test_a_clean_rejection_is_not_unknown(client, admin, kat):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    kat.override = lambda request: (httpx.Response(400, json={"code": "invalid_phone", "error": "x"})
                                    if request.method == "POST" else None)
    body = diagnose(client, admin, b["id"], send_body(b)).json()
    assert body["sent_unknown"] is False and body["steps"][1]["maybe_sent"] is False
    assert [s["outcome"] for s in body["sends"]] == ["not_sent"]
    assert diagnose(client, admin, b["id"], send_body(b)).status_code == 200  # 분명히 안 갔으면 막지 않는다


def _stored(session, cid: int, record: dict) -> None:
    session.get(NotifyConnection, cid).last_diagnosis_json = record
    session.commit()


def test_a_send_left_unfinished_reads_as_unknown_and_blocks_resend(client, admin, session, fake_provider, spy):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    now = datetime.now(UTC)
    fresh = (now - timedelta(seconds=5)).isoformat()
    _stored(session, b["id"], {"state": "sending", "ran_at": fresh, "by": "관리자", "steps": [], "real": False,
                                "sent_unknown": False, "sends": [{"at": fresh, "by": "관리자", "outcome": "sending"}]})
    got = client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).json()
    assert got["state"] == "sending" and got["sent_unknown"] is False and got["by"] == "관리자"

    old = (now - timedelta(seconds=200)).isoformat()  # 상한(150초)보다 오래 — 요청이 끝나지 않은 채 남았다
    _stored(session, b["id"], {"state": "sending", "ran_at": old, "by": "관리자", "steps": [], "real": False,
                                "sent_unknown": False, "sends": [{"at": old, "by": "관리자", "outcome": "sending"}]})
    got = client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).json()
    assert got["state"] == "done" and got["sent_unknown"] is True and [s["id"] for s in got["steps"]] == [
        "P1", "P2", "P3", "P4"]
    assert got["steps"][1]["code"] == "not_finished" and got["steps"][1]["maybe_sent"] is True
    assert [s["outcome"] for s in got["sends"]] == ["unknown"]
    r = diagnose(client, admin, b["id"], send_body(b))
    assert r.status_code == 409 and r.json()["code"] == "sent_unknown_pending" and spy.calls == []

    stale = (now - timedelta(minutes=11)).isoformat()  # 10분이 지나면 다시 보낼 수 있다
    _stored(session, b["id"], {"state": "done", "ran_at": stale, "by": "관리자", "steps": [], "real": False,
                                "sent_unknown": True, "sends": [{"at": stale, "by": "관리자", "outcome": "unknown"}]})
    assert diagnose(client, admin, b["id"], send_body(b)).status_code == 200 and spy.calls


def test_sending_record_is_written_before_the_send(client, admin, session, fake_provider, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    seen = []

    async def look(conn, http, **kw):
        other = next(get_session())
        try:
            seen.append(other.get(NotifyConnection, b["id"]).last_diagnosis_json)
        finally:
            other.close()
        return steps(*kw["steps"])

    monkeypatch.setattr(diagnostics, "run_checks", look)
    diagnose(client, admin, b["id"], send_body(b))
    assert seen[0]["state"] == "sending" and seen[0]["sends"][-1]["outcome"] == "sending" and seen[0]["by"]


def test_test_sms_log_is_kept_capped_and_has_no_number(client, admin, session, fake_provider, spy):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    old = [{"at": (datetime.now(UTC) - timedelta(hours=30 - i)).isoformat(), "by": "예전", "outcome": "accepted"}
           for i in range(20)]
    _stored(session, b["id"], {"state": "done", "ran_at": old[-1]["at"], "by": "예전", "steps": [], "real": True,
                                "sent_unknown": False, "sends": old})
    body = diagnose(client, admin, b["id"], send_body(b)).json()
    assert len(body["sends"]) == 20 and body["sends"][-1]["outcome"] == "accepted" and body["sends"][-1]["by"]
    assert body["sends"][0]["at"] == client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).json()["sends"][0]["at"]
    assert diagnose(client, admin, b["id"], {"steps": ["P1"]}).json()["sends"][-1]["outcome"] == "accepted"
    session.expire_all()
    stored = json.dumps(session.get(NotifyConnection, b["id"]).last_diagnosis_json["sends"], ensure_ascii=False)
    assert SENTINEL_DIGITS not in stored.replace("-", "") and KAT_SENDER not in stored


async def test_one_diagnosis_at_a_time(client, admin, fake_provider, monkeypatch):
    cid = create(client, admin)["id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(conn, http, **kw):
        entered.set()
        async with asyncio.timeout(3):
            await release.wait()
        return steps(*kw["steps"])

    monkeypatch.setattr(diagnostics, "run_checks", hold)
    url = f"{BASE}/{cid}/diagnose"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        first = asyncio.create_task(ac.post(url, json={"steps": ["P1"]}, headers=admin))
        async with asyncio.timeout(3):
            await entered.wait()
        second = await ac.post(url, json={"steps": ["P1"]}, headers=admin)
        release.set()
        async with asyncio.timeout(3):
            done = await first
    assert second.status_code == 409 and second.json()["code"] == "diagnosis_running"
    assert done.status_code == 200 and not diagnose_mod._RUNNING


async def test_running_marker_is_cleared_on_cancel_and_error(client, admin, fake_provider, monkeypatch):
    cid = create(client, admin)["id"]
    started = asyncio.Event()

    async def hang(conn, http, **kw):
        started.set()
        await asyncio.sleep(5)

    monkeypatch.setattr(diagnostics, "run_checks", hang)
    session = next(get_session())
    task = asyncio.create_task(diagnose_mod.run(session, cid, DiagnoseIn(), "관리자"))
    async with asyncio.timeout(2):
        await started.wait()
    assert cid in diagnose_mod._RUNNING
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cid not in diagnose_mod._RUNNING

    async def boom(conn, http, **kw):
        raise RuntimeError("x")

    monkeypatch.setattr(diagnostics, "run_checks", boom)
    with pytest.raises(RuntimeError):
        await diagnose_mod.run(session, cid, DiagnoseIn(), "관리자")
    assert cid not in diagnose_mod._RUNNING
    session.close()


def test_no_db_write_is_held_during_diagnosis(client, admin, fake_provider, monkeypatch):
    cid = create(client, admin)["id"]
    wrote = []

    async def other_writer(conn, http, **kw):
        other = next(get_session())
        try:
            other.get(NotifyConnection, cid).name = "진단 중에 바꿈"
            other.commit()  # 경로가 쓰기를 쥐고 있으면 여기서 막힌다
            wrote.append(True)
        finally:
            other.close()
        return steps("P1")

    monkeypatch.setattr(diagnostics, "run_checks", other_writer)
    r = diagnose(client, admin, cid, {"steps": ["P1"]})
    assert r.status_code == 200 and wrote == [True]
    assert client.get(BASE, headers=admin).json()[0]["name"] == "진단 중에 바꿈"  # 경로가 옛 값으로 덮지 않았다


def test_no_key_or_number_in_logs_after_startup(client, admin, kat, caplog):
    caplog.set_level(logging.DEBUG)
    leak = f"{SENTINEL_KEY} {SENTINEL_PHONE} {KAT_ACCOUNT}"
    kat.override = lambda request: httpx.Response(500, json={"code": leak, "error": leak})
    b = client.post(BASE, json=NEW, headers=admin).json()
    assert b["status"] == "failed" and b["error"]["code"] == "server"  # 500 본문까지 읽었다
    assert patch(client, admin, b["id"], allow_numbers_add=[SENTINEL_PHONE]).status_code == 200
    r = diagnose(client, admin, b["id"], {})
    assert r.status_code == 200 and len(kat.requests) >= 3
    assert r.json()["steps"][0]["ok"] is False and SENTINEL_KEY not in r.text and KAT_ACCOUNT not in r.text
    assert SENTINEL_DIGITS not in r.text.replace("-", "")
    assert_clean(caplog, KAT_ACCOUNT)


def test_rows_are_read_again_after_provider_call(client, admin, fake_provider, monkeypatch, session):
    """키를 바꾸는 PATCH 가 제공사를 부르는 사이에 다른 요청이 고친 칸을 덮지 않는다."""
    cid = create(client, admin)["id"]
    real_check = fake_provider.check

    async def check_and_meanwhile():
        other = next(get_session())
        try:
            row = other.get(NotifyConnection, cid)
            row.inbound_mode = "all"
            row.allow_numbers_json = [SENTINEL_DIGITS]  # 그사이 다른 요청이 허용 번호를 더했다
            other.commit()
        finally:
            other.close()
        return await real_check()

    monkeypatch.setattr(fake_provider, "check", check_and_meanwhile)
    r = patch(client, admin, cid, secret=NEW_KEY, allow_numbers_add=[OTHER_MOBILE])
    assert r.status_code == 200 and r.json()["inbound_mode"] == "all"
    session.expire_all()
    row = session.scalars(select(NotifyConnection)).one()
    assert row.secret_last4 == "8888" and row.allow_numbers_json == [SENTINEL_DIGITS, "01000000198"]


BAD_VERSIONS = ["판", "😀" * 3, "v" * 10_000, "", "\ud800abc"]  # 영문이 아닌 글·이모지·아주 긴 글·빈 글·짝 없는 서로게이트


def raw(client, method: str, path: str, headers: dict, body: dict):
    """JSON 을 \\uXXXX 로 적어 보낸다(짝 없는 서로게이트도 실제 클라이언트처럼 보낼 수 있게)."""
    return client.request(method, path, content=json.dumps(body), headers={**headers, "content-type": "application/json"})


def test_malformed_allow_version_is_a_stale_version_on_patch(client, admin, fake_provider, session):
    b = with_numbers(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    for bad in BAD_VERSIONS:
        r = raw(client, "PATCH", f"{BASE}/{b['id']}", admin, {"allow_numbers_remove": [0], "allow_numbers_version": bad})
        assert r.status_code in (409, 422), (bad[:5], r.status_code, r.text[:200])
        assert r.json()["code"] == ("too_long" if len(bad) > 100 else "allow_list_changed")
        assert (bad not in r.text) if bad else True
    for bad in (123, ["x"], {"v": 1}):
        r = patch(client, admin, b["id"], allow_numbers_remove=[0], allow_numbers_version=bad)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    r = patch(client, admin, b["id"], allow_numbers_remove=[0], allow_numbers_version=None)
    assert r.status_code == 422 and r.json()["code"] == "allow_version_required"
    session.expire_all()
    assert session.get(NotifyConnection, b["id"]).allow_numbers_json == [SENTINEL_DIGITS, "01000000198"]


def test_malformed_allow_version_is_a_stale_version_on_test_sms(client, admin, fake_provider, session, spy):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    for bad in BAD_VERSIONS:
        r = raw(client, "POST", f"{BASE}/{b['id']}/diagnose", admin, send_body(b, allow_numbers_version=bad))
        assert r.status_code == 409 and r.json()["code"] == "allow_list_changed", (bad[:5], r.status_code, r.text[:200])
        assert (bad not in r.text) if bad else True
    for bad in (123, ["x"], {"v": 1}):
        r = diagnose(client, admin, b["id"], send_body(b, allow_numbers_version=bad))
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    r = diagnose(client, admin, b["id"], send_body(b, allow_numbers_version=None))
    assert r.status_code == 422 and r.json()["code"] == "allow_version_required"
    assert spy.calls == []  # 아무것도 보내지 않았다
    session.expire_all()
    assert session.get(NotifyConnection, b["id"]).last_diagnosis_json is None  # 「보내는 중」 기록도 남기지 않았다
