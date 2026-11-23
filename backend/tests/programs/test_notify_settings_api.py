"""알림 연결 API(계획 4 Task 70). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

키는 끝 4자리만 · 번호는 가린 꼴만 · 주소를 바꾸면 키를 다시 · 상한은 validate_limits 하나로 · 진단은 저장된 키로, 실제 문자는
send 가 참일 때 첫 허용 번호로만 · 진단은 연결마다 하나씩 · 제공사 호출 동안 DB 를 쥐지 않는다. 실제 제공사를 부르지 않는다.
"""

import ast
import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db import get_session
from app.notify import diagnostics
from app.notify.diagnostics import DiagnosticStep
from app.outreach import provider, redact
from app.outreach.provider import ProviderFailed
from app.programs.notify_settings import diagnose as diagnose_mod
from app.programs.notify_settings.schemas import DiagnoseIn
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
from tests.provider_doubles import KAT_ACCOUNT, KatMock

BASE = "/api/notify/connections"
NEW = {"name": "한국AI통신", "secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}
NEW_KEY = "kat-test-key-NEWW8888"
LANDLINE = "02-2000-0199"
OTHER_MOBILE = "010-0000-0198"
PREMIUM = "060-700-0199"
PKG = Path(__file__).resolve().parents[2] / "app" / "programs" / "notify_settings"


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


def steps(*ids: str, ok: bool = True, detail: str = "HTTP 200") -> list[DiagnosticStep]:
    return [DiagnosticStep(id=i, label=diagnostics.LABELS[i], ok=ok, detail=detail, latency_ms=3) for i in ids]


class Spy:
    """run_checks 대역 — 넘어온 값을 적고 정해 둔 걸음을 돌려준다."""

    def __init__(self, result=None, check=None) -> None:
        self.calls: list[dict] = []
        self.result, self.check = result, check

    async def __call__(self, conn, http, *, send_test_sms=False, steps=(1, 2, 3, 4), **_kw):
        self.calls.append({"conn": conn, "send": send_test_sms, "steps": list(steps), "trust_env": http.trust_env})
        if self.check is not None:
            self.check(conn)
        return self.result if self.result is not None else [
            DiagnosticStep(id=s, label=diagnostics.LABELS[s], ok=True, detail="HTTP 200", latency_ms=3) for s in steps]


@pytest.fixture
def spy(monkeypatch) -> Spy:
    found = Spy()
    monkeypatch.setattr(diagnostics, "run_checks", found)
    return found


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
    assert body["senders"] == ["070-****-0123"] and body["sender_index"] == 0
    assert body["sender_number_masked"] == "070-****-0123"
    assert body["status"] == "ok" and body["error"] is None and fake_provider.log == ["check"]
    row = session.get(NotifyConnection, body["id"])
    assert SENTINEL_KEY not in row.secret_ciphertext and row.sender_number == "07000000123"
    listed = client.get(BASE, headers=admin)
    assert listed.status_code == 200 and SENTINEL_KEY not in listed.text and [c["id"] for c in listed.json()] == [body["id"]]


def test_defaults_are_safe(client, admin, fake_provider):
    b = create(client, admin)
    assert b["test_mode"] is True and b["agent_call"] == "approve" and b["inbound_mode"] == "off"
    assert b["agent_sms"] == "approve" and b["agent_kakao"] == "approve" and b["kakao_channel"] is None
    assert b["is_default"] is True and b["allow_numbers"] == [] and b["test_sms_index"] is None
    assert b["used_today"] == {"sms": 0, "call": 0}
    assert b["limits"] == {**outreach.limits(None).__dict__}
    assert create(client, admin, name="둘째")["is_default"] is False


def test_create_rejects_bad_inputs_without_echo(client, admin, fake_provider):
    for over, code in (({"secret": "short"}, "invalid_secret"), ({"secret": "kat key with space"}, "invalid_secret"),
                       ({"account_id": "AC 0000 0000"}, "invalid_account_id"),
                       ({"base_url": "http://api.koreaaitel.com"}, "bad_base_url"),
                       ({"base_url": "https://127.0.0.1"}, "bad_base_url")):
        r = client.post(BASE, json={**NEW, **over}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == code, (over, r.text)
        assert SENTINEL_KEY not in r.text
    assert fake_provider.log == []


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
    fake_provider.senders = ["07000000123", "07000000456"]
    cid = create(client, admin)["id"]
    r = patch(client, admin, cid, test_mode=False, agent_sms="delegate", agent_call="delegate", inbound_mode="known",
              sender_index=1, name="새 이름")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["test_mode"], b["agent_sms"], b["agent_call"], b["inbound_mode"], b["name"]) == (
        False, "delegate", "delegate", "known", "새 이름")
    assert b["sender_index"] == 1 and b["sender_number_masked"] == "070-****-0456"
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
    assert r.json() == {"ok": True, "latency_ms": 1, "senders": ["070-****-0123"], "error": None}
    assert SENTINEL_KEY not in r.text and "07000000123" not in r.text
    assert client.get(BASE, headers=admin).json() == []  # 저장하지 않았다
    cid = create(client, admin)["id"]
    fake_provider.senders = ["07000000456"]
    again = client.post(f"{BASE}/{cid}/test", headers=admin).json()
    assert again["senders"] == ["070-****-0456"]
    shown = client.get(BASE, headers=admin).json()[0]
    assert shown["senders"] == ["070-****-0456"] and shown["sender_index"] == 0  # 사라진 발신번호 대신 남은 첫 번호


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
    r = client.post(f"{BASE}/{cid}/diagnose", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "secret_unreadable" and spy.calls == []


# ── 권한 ─────────────────────────────────────────────────────────────


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
    cid = create(client, admin)["id"]
    r = client.post(f"{BASE}/{cid}/diagnose", json={"send": True}, headers=user)
    assert r.status_code == 403 and spy.calls == []


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
    monkeypatch.setattr(diagnostics, "make_client", lambda: real_make(transport=mock))
    caplog.set_level(logging.INFO)
    out = client.post(f"{BASE}/{cid}/diagnose", json={"steps": ["P1"]}, headers=admin)
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
    assert got["ranges"]["max_call_seconds"] == [30, 7200] and len(got["ranges"]) == 12
    r = client.put(f"{BASE}/{cid}/limits", json={"per_contact_sms_daily": 3}, headers=admin)
    assert r.status_code == 200 and r.json()["values"]["per_contact_sms_daily"] == 3
    assert r.json()["defaults"]["per_contact_sms_daily"] == 5
    session.expire_all()
    assert outreach.limits(session.get(NotifyConnection, cid)).per_contact_sms_daily == 3
    for bad, field in (({"max_call_seconds": 10}, "max_call_seconds"), ({"nope": 1}, "nope"),
                       ({"daily_sms_total": "50"}, "daily_sms_total"), ({"daily_sms_total": True}, "daily_sms_total"),
                       ({"per_contact_sms_daily": 60}, "per_contact_sms_daily")):
        r = client.put(f"{BASE}/{cid}/limits", json=bad, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "invalid_limits" and field in r.json()["detail"], bad
    assert client.put(f"{BASE}/{cid}/limits", json=[1], headers=admin).status_code == 422
    assert client.get(BASE, headers=admin).json()[0]["limits"]["per_contact_sms_daily"] == 3
    r = client.post(f"{BASE}/{cid}/limits/reset", headers=admin)
    assert r.status_code == 200 and r.json()["values"] == r.json()["defaults"]
    session.expire_all()
    assert session.get(NotifyConnection, cid).limits_json is None


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
    r = client.post(f"{BASE}/{cid}/diagnose", json={"steps": ["P1", "P4"]}, headers=admin)
    assert r.status_code == 200, r.text
    call = spy.calls[0]
    assert call["conn"].key == SENTINEL_KEY and call["conn"].account_id == KAT_ACCOUNT
    assert call["steps"] == ["P1", "P4"] and call["send"] is False and call["trust_env"] is False
    assert call["conn"].test_to == ""
    body = r.json()
    assert body["sent_real"] is False and body["sent_unknown"] is False and "ran_at" in body
    assert [s["id"] for s in body["steps"]] == ["P1", "P4"]
    assert set(body["steps"][0]) == {"id", "label", "ok", "skipped", "detail", "latency_ms", "notes"}
    assert client.get(f"{BASE}/{cid}/diagnosis", headers=admin).json() == body
    client.post(f"{BASE}/{cid}/diagnose", json={}, headers=admin)
    assert spy.calls[1]["steps"] == ["P1", "P2", "P3", "P4"]
    for bad in ({"steps": ["P9"]}, {"send": "true"}, {"send": 1}, {"steps": []}):
        assert client.post(f"{BASE}/{cid}/diagnose", json=bad, headers=admin).status_code == 422, bad


def test_diagnosis_is_null_before_first_run(client, admin, fake_provider):
    cid = create(client, admin)["id"]
    r = client.get(f"{BASE}/{cid}/diagnosis", headers=admin)
    assert r.status_code == 200 and r.json() is None
    assert client.get(f"{BASE}/999/diagnosis", headers=admin).json()["code"] == "connection_not_found"


def test_diagnose_real_send_only_when_requested_and_only_to_first_allowed_number(client, admin, fake_provider, spy):
    cid = create(client, admin)["id"]
    r = client.post(f"{BASE}/{cid}/diagnose", json={"steps": ["P2", "P3"], "send": True}, headers=admin)
    assert r.status_code == 422 and r.json()["message"] == "허용 번호를 먼저 넣어 주세요" and spy.calls == []
    patch(client, admin, cid, allow_numbers_add=[LANDLINE, SENTINEL_PHONE])
    r = client.post(f"{BASE}/{cid}/diagnose", json={"steps": ["P2", "P3"], "send": True}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "test_number_not_mobile" and spy.calls == []

    b = with_numbers(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2", "P3"]}, headers=admin)
    assert spy.calls[-1]["send"] is False and spy.calls[-1]["conn"].test_to == ""
    r = client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2", "P3"], "send": True}, headers=admin)
    assert r.status_code == 200 and r.json()["sent_real"] is True
    last = spy.calls[-1]
    assert last["send"] is True and last["conn"].test_to == SENTINEL_DIGITS and last["conn"].sender == "07000000123"


def test_diagnose_send_needs_a_sender(client, admin, fake_provider, spy):
    fake_provider.senders = []
    b = with_numbers(client, admin, SENTINEL_PHONE)
    assert b["test_sms_index"] is None
    r = client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2"], "send": True}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "no_sender" and spy.calls == []


def test_stored_diagnosis_has_no_key_or_number(client, admin, session, fake_provider, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    leak = f"{SENTINEL_KEY} {KAT_ACCOUNT} {SENTINEL_PHONE} 07000000123"
    bad = [DiagnosticStep(id="P2", label="x", ok=False, detail=f"http_500 · {leak}", notes=[leak])]
    monkeypatch.setattr(diagnostics, "run_checks", Spy(result=bad))
    r = client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2"], "send": True}, headers=admin)
    session.expire_all()
    stored = json.dumps(session.get(NotifyConnection, b["id"]).last_diagnosis_json, ensure_ascii=False)
    for text in (r.text, stored, client.get(f"{BASE}/{b['id']}/diagnosis", headers=admin).text):
        assert SENTINEL_KEY not in text and KAT_ACCOUNT not in text
        assert SENTINEL_DIGITS not in text.replace("-", "") and "07000000123" not in text
    assert json.loads(stored)["real"] is False and "ran_at" in json.loads(stored)


def test_diagnose_ceiling_marks_send_unknown_and_never_sends_twice(client, admin, fake_provider, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    calls = []

    async def slow(conn, http, **kw):
        calls.append(kw)
        await asyncio.sleep(5)  # 상한(0.05초)이 먼저 끊는다

    monkeypatch.setattr(diagnostics, "run_checks", slow)
    monkeypatch.setattr(diagnose_mod, "DIAGNOSE_CEILING_S", 0.05)
    r = client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2", "P3"], "send": True}, headers=admin)
    assert r.status_code == 200 and len(calls) == 1
    body = r.json()
    assert body["sent_real"] is False and body["sent_unknown"] is True
    p2, p3 = body["steps"]
    assert p2["id"] == "P2" and p2["ok"] is False and "보냈는지 알 수 없음" in p2["detail"]
    assert p3["detail"].startswith("timeout")
    assert not diagnose_mod._RUNNING


def test_diagnose_maybe_sent_step_is_reported_as_unknown(client, admin, fake_provider, monkeypatch):
    b = with_numbers(client, admin, SENTINEL_PHONE)
    maybe = steps("P2", ok=False, detail=f"ReadTimeout · {diagnostics.MAYBE_SENT}")
    monkeypatch.setattr(diagnostics, "run_checks", Spy(result=maybe))
    body = client.post(f"{BASE}/{b['id']}/diagnose", json={"steps": ["P2"], "send": True}, headers=admin).json()
    assert body["sent_unknown"] is True and body["sent_real"] is False


def test_one_diagnosis_at_a_time(client, admin, fake_provider, spy):
    cid = create(client, admin)["id"]
    diagnose_mod._RUNNING.add(cid)
    try:
        r = client.post(f"{BASE}/{cid}/diagnose", json={}, headers=admin)
        assert r.status_code == 409 and r.json()["code"] == "diagnosis_running" and spy.calls == []
    finally:
        diagnose_mod._RUNNING.discard(cid)
    assert client.post(f"{BASE}/{cid}/diagnose", json={}, headers=admin).status_code == 200
    assert not diagnose_mod._RUNNING


async def test_running_marker_is_cleared_on_cancel_and_error(client, admin, fake_provider, monkeypatch):
    cid = create(client, admin)["id"]
    started = asyncio.Event()

    async def hang(conn, http, **kw):
        started.set()
        await asyncio.sleep(5)

    monkeypatch.setattr(diagnostics, "run_checks", hang)
    session = next(get_session())
    task = asyncio.create_task(diagnose_mod.run(session, cid, DiagnoseIn()))
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
        await diagnose_mod.run(session, cid, DiagnoseIn())
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
    r = client.post(f"{BASE}/{cid}/diagnose", json={"steps": ["P1"]}, headers=admin)
    assert r.status_code == 200 and wrote == [True]
    assert client.get(BASE, headers=admin).json()[0]["name"] == "진단 중에 바꿈"  # 경로가 옛 값으로 덮지 않았다


def test_no_key_or_number_in_logs_after_startup(client, admin, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    leak = f"{SENTINEL_KEY} {SENTINEL_PHONE} {KAT_ACCOUNT}"
    mock = KatMock(override=lambda request: httpx.Response(500, json={"code": leak, "error": leak}))
    monkeypatch.setattr(provider, "_default_transport", lambda: mock)
    real_make = diagnostics.make_client
    monkeypatch.setattr(diagnostics, "make_client", lambda: real_make(transport=mock))
    b = client.post(BASE, json=NEW, headers=admin).json()
    assert b["status"] == "failed" and patch(client, admin, b["id"], allow_numbers_add=[SENTINEL_PHONE]).status_code == 200
    r = client.post(f"{BASE}/{b['id']}/diagnose", json={}, headers=admin)
    assert r.status_code == 200 and mock.requests
    assert SENTINEL_KEY not in r.text and KAT_ACCOUNT not in r.text
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
