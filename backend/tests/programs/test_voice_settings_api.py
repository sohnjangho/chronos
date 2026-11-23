"""음성 설정 API와 음성 진단 길(계획 4 Task 90). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-90-contract.md.

음성 모델 키는 암호문과 끝 4자리만 · AI 전화 번호는 가린 꼴만 · 실제 전화는 관리자가 `call` 을 진짜 참으로 보냈을 때, 확인한 목록의
첫 허용 번호로만 · 걸기 전에 「거는 중」 기록 · 결과를 모르면 다시 걸지 않음 · 한 요청은 한 종류(연결·통화·받는 통화)만 · 진단은
연결마다 하나(연결 진단과도 겹치지 않음) · SDK 를 부르는 동안 DB 를 쥐지 않음. 실제 SDK·망·실제 시간을 쓰지 않는다 —
`run_voice_checks` 를 대역으로 바꾸거나 Task 60 의 대본 가짜 SDK(`FakeSdk`·대본 시계 `World`)를 끼운다.
"""

import ast
import asyncio
import inspect
import logging
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.db import get_session
from app.main import app
from app.notify import diagnostics
from app.notify import diagnostics_voice as dv
from app.notify.diagnostics import DiagnosticStep
from app.outreach import redact
from app.programs.notify_settings import diagnose as diagnose_mod
from app.programs.notify_settings import router as router_mod
from app.programs.notify_settings import voice
from app.security import crypto
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import NotifyConnection, VoiceSettings
from tests.helpers import auth
from tests.notify.test_diagnostics_voice import GOOD_CALL, FakeSdk, World
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)
from tests.provider_doubles import KAT_ACCOUNT, KAT_SENDER

pytestmark = pytest.mark.usefixtures("time_guard")

BASE = "/api/notify/connections"
NEW = {"name": "한국AI통신", "secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}
GOOGLE_KEY = "goog-test-key-QQQQ7777"
NEW_GOOGLE_KEY = "goog-test-key-NEWW6666"
AGENT = "070-0000-0144"  # AI 전화 번호(가상) — 문자 발신번호(KAT_SENDER)와 다르다
AGENT_DIGITS = "07000000144"
OTHER_MOBILE = "010-0000-0198"
PREMIUM = "060-700-0199"
ROW_KEYS = {"id", "label", "ok", "skipped", "detail", "latency_ms", "notes", "code", "maybe_sent", "pending", "data",
            "ran_at"}
IDS = [f"P{n}" for n in range(5, 15)]
FILE = Path(voice.__file__)
REAL_RUN = dv.run_voice_checks  # 대역을 끼우기 전의 진짜 진단 함수


# ── 도우미 ───────────────────────────────────────────────────────────


def connection(client, admin, *numbers: str) -> dict:
    r = client.post(BASE, json=NEW, headers=admin)
    assert r.status_code == 201, r.text
    if numbers:
        r = client.patch(f"{BASE}/{r.json()['id']}", json={"allow_numbers_add": list(numbers)}, headers=admin)
        assert r.status_code == 200, r.text
    return r.json()


def put(client, admin, cid: int, **body):
    return client.put(f"{BASE}/{cid}/voice", json=body, headers=admin)


def ready(client, admin, *numbers: str) -> dict:
    """알림 연결 + 허용 번호(기본은 가상 휴대전화 하나) + 음성 키 + AI 전화 번호."""
    conn = connection(client, admin, *(numbers or (SENTINEL_PHONE,)))
    r = put(client, admin, conn["id"], secret=GOOGLE_KEY, agent_number=AGENT)
    assert r.status_code == 200, r.text
    return conn


def diag(client, admin, cid: int, body: dict):
    return client.post(f"{BASE}/{cid}/voice/diagnose", json=body, headers=admin)


def last(client, admin, cid: int):
    return client.get(f"{BASE}/{cid}/voice/diagnosis", headers=admin)


def call_body(conn: dict, **over) -> dict:
    return {"call": True, "allow_numbers_version": conn["allow_numbers_version"], **over}


def inbound_body(conn: dict, **over) -> dict:
    return {"inbound": True, "allow_numbers_version": conn["allow_numbers_version"], **over}


def row(n: int, code: str = "ok", detail: str = "확인했습니다.", **kw) -> dv.VoiceStep:
    return dv.VoiceStep(id=f"P{n}", label=dv.LABELS[f"P{n}"], ok=code == "ok", detail=detail, code=code, **kw)


class Spy:
    """`run_voice_checks` 대역. 넘어온 값을 적고, 고른 걸음은 정해 둔 줄(없으면 OK 줄)을, 나머지는 「확인하지 않음」을 돌려준다."""

    def __init__(self, rows: dict[int, dv.VoiceStep] | None = None, during=None) -> None:
        self.calls: list[dict] = []
        self.rows = rows or {}
        self.during = during  # 진단이 도는 사이에 부를 것(동기 함수) — 인자는 이번 호출의 기록

    async def __call__(self, conn, voice_diag, **kw) -> list[DiagnosticStep]:
        seen = {"conn": conn, "voice": voice_diag, **kw, "steps": list(kw.get("steps", ()))}
        self.calls.append(seen)
        if self.during is not None:
            found = self.during(seen)
            if inspect.isawaitable(found):
                await found
        return [self.rows.get(n) or row(n) if n in seen["steps"]
                else row(n, "skipped_not_requested", diagnostics.NOT_REQUESTED, skipped=True) for n in range(5, 15)]

    @property
    def chunks(self) -> list[list[int]]:
        return [c["steps"] for c in self.calls]


@pytest.fixture
def spy(monkeypatch) -> Spy:
    found = Spy()
    monkeypatch.setattr(dv, "run_voice_checks", found)
    return found


@pytest.fixture
def world() -> World:
    return World()


def scripted(monkeypatch, world: World, sdk: FakeSdk) -> None:
    """실제 `run_voice_checks` 를 대본 가짜 SDK·대본 시계로 돌린다."""
    async def run(conn, voice_diag, **kw):
        return await REAL_RUN(conn, voice_diag, sdk=sdk, sleep=world.sleep, clock=world.clock, **kw)

    monkeypatch.setattr(dv, "run_voice_checks", run)


def stored(session, cid: int) -> dict | None:
    session.expire_all()
    found = session.get(VoiceSettings, cid)
    return found.last_diagnosis_json if found is not None else None


def texts(value: object):
    """JSON 의 모든 글(열쇠와 값)."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item)
    elif isinstance(value, str):
        yield value


def assert_no_leak(payload: object, *more: str) -> None:
    """응답·저장된 JSON 을 끝까지 걸어, 어느 글에도 키·Account ID·번호(어느 꼴이든)가 없다. 가린 번호는 걸리지 않는다."""
    for text in texts(payload):
        for secret in (SENTINEL_KEY, GOOGLE_KEY, NEW_GOOGLE_KEY, KAT_ACCOUNT, *more):
            assert secret not in text, f"비밀이 남았습니다: {text[:80]}"
        if _is_time(text):
            continue
        digits = "".join(ch for ch in text if ch.isdigit())
        for number in (SENTINEL_DIGITS, SENTINEL_DIGITS[1:], AGENT_DIGITS, AGENT_DIGITS[1:], KAT_SENDER, KAT_SENDER[1:]):
            assert number not in digits, f"번호가 남았습니다: {text[:80]}"


def _is_time(text: str) -> bool:
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return len(text) >= 19


@pytest.fixture
def field(session) -> dict[str, str]:
    found = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(found)
    session.commit()
    return auth(issue_token(found.id))


# ── 음성 설정 ────────────────────────────────────────────────────────


def test_defaults_before_anything_is_saved(client, admin, fake_provider, session):
    conn = connection(client, admin, SENTINEL_PHONE)
    r = client.get(f"{BASE}/{conn['id']}/voice", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "connection_id": conn["id"], "provider": "google", "has_secret": False, "secret_last4": "", "model": "",
        "agent_number_masked": None, "agent_number_kind": "", "voice_male_contact": None,
        "voice_female_contact": None, "voice_unknown": None, "voices_by_language": {}, "status": "unknown",
        "checked_at": None, "sdk_installed": body["sdk_installed"], "test_call_index": None,
        "key_notice": {"code": "google_free_tier", "message": voice.FREE_TIER_NOTICE},
        "call_limits": {"calls_per_request": 2, "ring_seconds": dv.RING_TIMEOUT_S, "call_seconds": dv.CALL_CUT_S,
                        "inbound_wait_default": 90, "inbound_wait_min": 10, "inbound_wait_max": dv.MAX_WAIT_INBOUND_S},
    }
    assert isinstance(body["sdk_installed"], bool) and "구글" in voice.FREE_TIER_NOTICE
    assert session.get(VoiceSettings, conn["id"]) is None  # 읽기만으로 줄을 만들지 않는다
    assert last(client, admin, conn["id"]).json() is None


def test_voice_key_is_encrypted_and_last4_only(client, admin, fake_provider, session):
    cid = connection(client, admin)["id"]
    r = put(client, admin, cid, secret=GOOGLE_KEY)
    assert r.status_code == 200, r.text
    assert r.json()["has_secret"] is True and r.json()["secret_last4"] == "7777"
    assert GOOGLE_KEY not in r.text and "QQQQ" not in r.text
    saved = session.get(VoiceSettings, cid)
    assert GOOGLE_KEY not in saved.secret_ciphertext and crypto.decrypt(saved.secret_ciphertext) == GOOGLE_KEY
    assert saved.secret_last4 == "7777" and saved.provider == "google"
    again = client.get(f"{BASE}/{cid}/voice", headers=admin)
    assert again.json() == r.json() and GOOGLE_KEY not in again.text
    assert GOOGLE_KEY not in repr(voice.VoiceUpdate(secret=GOOGLE_KEY))


def test_voice_key_is_registered_as_secret_and_old_one_dropped(client, admin, fake_provider, spy):
    cid = connection(client, admin)["id"]
    other = client.post(BASE, json={**NEW, "name": "둘째"}, headers=admin).json()["id"]
    assert put(client, admin, cid, secret=GOOGLE_KEY, agent_number=AGENT).status_code == 200
    assert GOOGLE_KEY in redact.secrets()
    assert put(client, admin, cid, secret=NEW_GOOGLE_KEY).status_code == 200
    assert NEW_GOOGLE_KEY in redact.secrets() and GOOGLE_KEY not in redact.secrets()
    # 다른 연결의 음성 설정이 같은 키를 쓰면 내리지 않는다
    assert put(client, admin, other, secret=NEW_GOOGLE_KEY).status_code == 200
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200
    assert {GOOGLE_KEY, NEW_GOOGLE_KEY} <= set(redact.secrets())
    # 알림 연결의 키는 음성 키를 바꿔도 그대로 올라 있다
    assert SENTINEL_KEY in redact.secrets() and KAT_ACCOUNT in redact.secrets()

    redact.forget_secrets()  # 프로세스를 새로 띄운 것처럼 — 진단이 SDK 를 쓰기 전에 스스로 올려야 한다
    seen = []
    spy.during = lambda call: seen.append({GOOGLE_KEY, SENTINEL_KEY, KAT_ACCOUNT} <= set(redact.secrets()))
    assert diag(client, admin, cid, {}).status_code == 200
    assert seen == [True]


def test_put_changes_only_what_was_sent(client, admin, fake_provider, session):
    cid = connection(client, admin)["id"]
    first = put(client, admin, cid, secret=GOOGLE_KEY, model="gemini-live-test", voice_male_contact="Kore",
                voices_by_language={"en": {"voice_unknown": "Puck"}, "zh-cn": {"voice_male_contact": "Aoede"}})
    assert first.status_code == 200, first.text
    second = put(client, admin, cid, voice_female_contact=" Charon ", agent_number=AGENT)
    body = second.json()
    assert body["model"] == "gemini-live-test" and body["secret_last4"] == "7777"
    assert body["voice_male_contact"] == "Kore" and body["voice_female_contact"] == "Charon" and body["voice_unknown"] is None
    assert body["voices_by_language"] == {"en": {"voice_unknown": "Puck"}, "zh-cn": {"voice_male_contact": "Aoede"}}
    saved = session.get(VoiceSettings, cid)
    assert saved.voices_by_language_json == body["voices_by_language"] and saved.voice_female_contact == "Charon"
    cleared = put(client, admin, cid, voice_male_contact=None, voice_female_contact="", voices_by_language={}, model="")
    assert cleared.json()["voice_male_contact"] is None and cleared.json()["voice_female_contact"] is None
    assert cleared.json()["voices_by_language"] == {} and cleared.json()["model"] == ""
    assert put(client, admin, cid).json() == cleared.json()  # 빈 본문은 아무것도 바꾸지 않는다


def test_agent_number_is_validated_masked_and_its_own_setting(client, admin, fake_provider, session):
    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    for bad in ("12345", "abc", PREMIUM, "+1 212 555 0100", "0" * 41):
        r = put(client, admin, cid, agent_number=bad)
        assert r.status_code == 422 and r.json()["code"] in ("invalid_number", "too_long"), r.text
        assert r.json()["detail"]["field"] == "agent_number" and bad not in r.text
    assert session.get(VoiceSettings, cid) is None  # 틀린 입력은 줄도 만들지 않는다
    r = put(client, admin, cid, agent_number=AGENT)
    body = r.json()
    assert body["agent_number_masked"] == "070-****-0144" and body["agent_number_kind"] == "internet"
    assert body["test_call_index"] == 0  # 첫 허용 번호 + AI 전화 번호가 있다
    assert_no_leak(body)
    session.expire_all()
    assert session.get(VoiceSettings, cid).agent_number == AGENT_DIGITS
    assert session.get(NotifyConnection, cid).sender_number == KAT_SENDER  # 문자 발신번호는 건드리지 않는다
    for empty in (None, ""):
        assert put(client, admin, cid, agent_number=AGENT).status_code == 200
        gone = put(client, admin, cid, agent_number=empty).json()
        assert gone["agent_number_masked"] is None and gone["agent_number_kind"] == "" and gone["test_call_index"] is None


def test_provider_change_needs_the_key_again(client, admin, fake_provider, session):
    cid = connection(client, admin)["id"]
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200
    r = put(client, admin, cid, provider="openai")
    assert r.status_code == 422 and r.json()["code"] == "secret_required"
    session.expire_all()
    assert session.get(VoiceSettings, cid).provider == "google"  # 아무것도 바꾸지 않았다
    r = put(client, admin, cid, provider="openai", secret=NEW_GOOGLE_KEY)
    assert r.status_code == 200 and r.json()["provider"] == "openai" and r.json()["secret_last4"] == "6666"
    assert r.json()["key_notice"] is None and GOOGLE_KEY not in redact.secrets()
    same = put(client, admin, cid, provider="openai", model="rt-test")  # 같은 공급자면 키를 다시 묻지 않는다
    assert same.status_code == 200 and same.json()["secret_last4"] == "6666"
    r = put(client, admin, cid, provider="dashboard")  # 대시보드는 키 없이 저장된다 — 옛 키는 지운다
    assert r.status_code == 200 and r.json()["provider"] == "dashboard"
    assert r.json()["has_secret"] is False and r.json()["secret_last4"] == "" and r.json()["key_notice"] is None
    session.expire_all()
    assert session.get(VoiceSettings, cid).secret_ciphertext is None and NEW_GOOGLE_KEY not in redact.secrets()


@pytest.mark.parametrize(("body", "code", "field"), [
    ({"secret": "short"}, "invalid_secret", None),
    ({"secret": "goog key with space"}, "invalid_secret", None),
    ({"secret": "goog-키-한글-0123"}, "invalid_secret", None),
    ({"secret": GOOGLE_KEY + "x" * 500}, "too_long", "secret"),
    ({"model": "gemini live"}, "invalid_model", None),
    ({"model": f"m-{SENTINEL_PHONE}/x"}, "invalid_model", None),
    ({"model": "m" * 81}, "too_long", "model"),
    ({"voice_unknown": SENTINEL_PHONE}, "invalid_voice", "voice_unknown"),
    ({"voice_male_contact": "a01000000199"}, "invalid_voice", "voice_male_contact"),
    ({"voice_female_contact": "Kore" + chr(0x202E)}, "invalid_voice", "voice_female_contact"),  # 글 방향을 바꾸는 글자
    ({"voice_unknown": "v" * 101}, "too_long", "voice_unknown"),
    ({"voices_by_language": {SENTINEL_PHONE: {"voice_unknown": "Kore"}}}, "invalid_language", "voices_by_language"),
    ({"voices_by_language": {"en": {"voice_other": "Kore"}}}, "invalid_language", "voices_by_language"),
    ({"voices_by_language": {"en": "Kore"}}, "invalid_language", "voices_by_language"),
    ({"voices_by_language": {"en": {"voice_unknown": SENTINEL_PHONE}}}, "invalid_voice", "voices_by_language"),
    ({"voices_by_language": {"en": {"voice_unknown": 7}}}, "invalid_voice", "voices_by_language"),
    ({"voices_by_language": {f"l{i:02d}": {} for i in range(21)}}, "too_long", "voices_by_language"),
    ({"provider": "azure"}, "invalid_request", None),
    ({"model": 7}, "invalid_request", None),
    ({"max_call_seconds": 60}, "invalid_request", None),
    ({"status": "ok"}, "invalid_request", None),
])
def test_bad_settings_are_refused_by_field_without_echo(client, admin, fake_provider, session, body, code, field):
    cid = connection(client, admin)["id"]
    assert put(client, admin, cid, secret=GOOGLE_KEY, model="kept").status_code == 200
    r = put(client, admin, cid, **body)
    assert r.status_code == 422 and r.json()["code"] == code, r.text
    if field is not None:
        assert r.json()["detail"]["field"] == field
    assert_no_leak(r.json())
    assert "x" * 50 not in r.text and "m" * 50 not in r.text and "v" * 50 not in r.text
    session.expire_all()
    saved = session.get(VoiceSettings, cid)
    assert saved.model == "kept" and crypto.decrypt(saved.secret_ciphertext) == GOOGLE_KEY


def test_changing_key_model_or_number_resets_status_but_keeps_the_call_log(client, admin, fake_provider, spy):
    conn = ready(client, admin)
    cid = conn["id"]
    assert diag(client, admin, cid, call_body(conn)).status_code == 200
    before = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert before["status"] == "ok" and before["checked_at"] is not None
    same = put(client, admin, cid, secret=GOOGLE_KEY, agent_number=AGENT, model="", voice_unknown="Kore").json()
    assert same["status"] == "ok" and same["checked_at"] == before["checked_at"]  # 같은 값·음성 칸은 되돌리지 않는다
    for change in ({"model": "other-model"}, {"agent_number": "070-0000-0145"}, {"secret": NEW_GOOGLE_KEY}):
        assert diag(client, admin, cid, {}).status_code == 200
        assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "ok"
        changed = put(client, admin, cid, **change).json()
        assert changed["status"] == "unknown" and changed["checked_at"] is None, change
        shown = last(client, admin, cid).json()
        assert [s["code"] for s in shown["steps"]] == ["skipped_not_requested"] * 10
        assert all(s["ran_at"] is None for s in shown["steps"])
        assert [c["outcome"] for c in shown["calls"]] == ["placed"]


def test_user_cannot_manage_voice(client, user, field, admin, fake_provider, spy):
    conn = ready(client, admin)
    urls = (("GET", "/voice", None), ("PUT", "/voice", {"model": "x"}), ("POST", "/voice/diagnose", {}),
            ("GET", "/voice/diagnosis", None))
    for method, tail, body in urls:
        for who in (user, field):
            r = client.request(method, f"{BASE}/{conn['id']}{tail}", json=body, headers=who)
            assert r.status_code == 403 and r.json()["code"] == "admin_only", (method, tail)
        r = client.request(method, f"{BASE}/{conn['id']}{tail}", json=body)
        assert r.status_code == 401 and r.json()["code"] == "unauthorized", (method, tail)
        r = client.request(method, f"{BASE}/9999{tail}", json=body, headers=admin)
        assert r.status_code == 404 and r.json()["code"] == "connection_not_found", (method, tail)
    r = client.post(f"{BASE}/{conn['id']}/voice/diagnose", json=call_body(conn), headers=user)
    assert r.status_code == 403 and spy.calls == []


def test_settings_cannot_change_while_a_diagnosis_runs(client, admin, fake_provider, session):
    cid = ready(client, admin)["id"]
    diagnose_mod._RUNNING.add(cid)
    try:
        r = put(client, admin, cid, model="other")
    finally:
        diagnose_mod._RUNNING.discard(cid)
    assert r.status_code == 409 and r.json()["code"] == "diagnosis_running"
    assert session.get(VoiceSettings, cid).model == ""
    assert put(client, admin, cid, model="other").status_code == 200


def test_deleting_the_connection_removes_its_voice_settings(client, admin, fake_provider, session):
    cid = ready(client, admin)["id"]
    assert client.delete(f"{BASE}/{cid}", headers=admin).status_code == 204
    session.expire_all()
    assert session.get(VoiceSettings, cid) is None


# ── 음성 진단: 무엇을 돌리는가 ───────────────────────────────────────


def test_voice_diagnose_uses_stored_keys_and_returns_step_lines(client, admin, fake_provider, spy, session):
    conn = ready(client, admin)
    cid = conn["id"]
    assert put(client, admin, cid, model="gemini-live-test").status_code == 200
    r = diag(client, admin, cid, {})
    assert r.status_code == 200, r.text
    body = r.json()
    assert spy.chunks == [[5, 9, 11]]
    seen = spy.calls[0]
    assert seen["conn"].key == SENTINEL_KEY and seen["conn"].account_id == KAT_ACCOUNT
    assert seen["conn"].base_url == "https://api.koreaaitel.com"
    assert (seen["voice"].provider, seen["voice"].key, seen["voice"].model) == ("google", GOOGLE_KEY, "gemini-live-test")
    assert seen["agent_number"] == AGENT_DIGITS and seen["call_to"] is None and seen["worker_connected"] is False
    assert isinstance(seen["steps"], list) and type(spy.calls[0]["budget"]) is dv.VoiceBudget
    prep = voice._prepare_sync(session, cid, voice.VoiceDiagnoseIn(**call_body(conn)))
    assert prep.call_to == SENTINEL_DIGITS and prep.agent_number == AGENT_DIGITS
    for secret in (SENTINEL_KEY, GOOGLE_KEY, KAT_ACCOUNT, SENTINEL_DIGITS, AGENT_DIGITS):
        assert secret not in repr(prep)  # 평문 값은 repr(로그·오류 글)에 나오지 않는다
    assert body["state"] == "done" and body["part"] == "connection" and body["by"]
    assert body["called_real"] is False and body["call_unknown"] is False and body["calls"] == []
    assert [s["id"] for s in body["steps"]] == IDS and all(set(s) == ROW_KEYS for s in body["steps"])
    ran = {s["id"]: s for s in body["steps"]}
    assert all(ran[i]["ok"] and ran[i]["ran_at"] == body["ran_at"] and ran[i]["label"] == dv.LABELS[i]
               for i in ("P5", "P9", "P11"))
    assert all(ran[i]["skipped"] and ran[i]["code"] == "skipped_not_requested" and ran[i]["ran_at"] is None
               and ran[i]["detail"] == diagnostics.NOT_REQUESTED for i in IDS if i not in ("P5", "P9", "P11"))
    assert all(s["pending"] is False for s in body["steps"])
    assert last(client, admin, cid).json() == body
    saved = stored(session, cid)
    assert saved["state"] == "done" and saved["real"] is False and len(saved["steps"]) == 10
    shown = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert shown["status"] == "ok" and shown["checked_at"] == body["ran_at"]
    assert_no_leak(body)
    assert_no_leak(saved)


def test_real_call_only_when_requested_and_only_to_first_allowed_number(client, admin, fake_provider, spy, session):
    conn = ready(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    cid, version = conn["id"], conn["allow_numbers_version"]
    # 진짜 참이 아닌 값·깃발 없는 통화 걸음·번호를 실은 본문은 아무것도 돌리지 않는다
    for body, code in (({"call": "true", "allow_numbers_version": version}, "invalid_request"),
                       ({"call": 1, "allow_numbers_version": version}, "invalid_request"),
                       ({"call": "yes", "allow_numbers_version": version}, "invalid_request"),
                       ({"call": None, "allow_numbers_version": version}, "invalid_request"),
                       ({"steps": ["P6"]}, "steps_not_in_part"),
                       ({"steps": ["P5", "P10"], "allow_numbers_version": version}, "steps_not_in_part"),
                       ({"steps": ["P6"], "inbound": True, "allow_numbers_version": version}, "steps_not_in_part"),
                       ({"steps": ["P12"], "call": True, "allow_numbers_version": version}, "steps_not_in_part"),
                       ({"call": True, "inbound": True, "allow_numbers_version": version}, "one_part_only"),
                       (call_body(conn, to=OTHER_MOBILE), "invalid_request"),
                       (call_body(conn, call_to=OTHER_MOBILE), "invalid_request"),
                       (call_body(conn, number=OTHER_MOBILE), "invalid_request"),
                       (call_body(conn, confirm_recall="true"), "invalid_request"),
                       ({"steps": ["P6", 6]}, "invalid_request"), ({"steps": []}, "invalid_request"),
                       ({"steps": ["P4"]}, "invalid_request"), ({"steps": [6]}, "invalid_request")):
        r = diag(client, admin, cid, body)
        assert r.status_code == 422 and r.json()["code"] == code, (body, r.text)
    assert spy.calls == [] and stored(session, cid) is None
    assert diag(client, admin, cid, {"steps": ["P6"]}).json()["detail"] == {"steps": ["P6"]}

    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200, r.text
    assert spy.chunks == [[5, 6, 7, 8, 11]]  # P5·P11 은 같은 연결에서 함께, P10 은 고를 때만
    assert spy.calls[0]["call_to"] == SENTINEL_DIGITS and spy.calls[0]["agent_number"] == AGENT_DIGITS
    body = r.json()
    assert body["part"] == "call" and body["called_real"] is True and body["call_unknown"] is False
    assert [c["outcome"] for c in body["calls"]] == ["placed"]
    assert_no_leak(body)

    spy.calls.clear()
    r = diag(client, admin, cid, call_body(conn, steps=["P7", "P10", "P7"]))
    assert r.status_code == 200 and spy.chunks == [[5, 6, 7, 11], [10]]  # P7 은 P6 과 한 통화
    assert {c["call_to"] for c in spy.calls} == {SENTINEL_DIGITS}
    assert spy.calls[0]["budget"] is spy.calls[1]["budget"]  # 통화 상한은 덩어리를 이어서 센다
    spy.calls.clear()
    assert diag(client, admin, cid, call_body(conn, steps=["P10"])).status_code == 200
    assert spy.chunks == [[5, 10, 11]]


def test_calls_are_refused_before_anything_runs(client, admin, fake_provider, spy, session):
    bare = connection(client, admin)
    assert put(client, admin, bare["id"], secret=GOOGLE_KEY, agent_number=AGENT).status_code == 200
    for make in (call_body, inbound_body):
        r = diag(client, admin, bare["id"], make(bare))
        assert r.status_code == 422 and r.json()["code"] == "no_allow_numbers"

    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200
    for make in (call_body, inbound_body):
        r = diag(client, admin, cid, {k: v for k, v in make(conn).items() if k != "allow_numbers_version"})
        assert r.status_code == 422 and r.json()["code"] == "allow_version_required"
        for stale in ("0" * 24, "", "판-한글"):
            r = diag(client, admin, cid, make(conn, allow_numbers_version=stale))
            assert r.status_code == 409 and r.json()["code"] == "allow_list_changed", stale
        r = diag(client, admin, cid, make(conn))
        assert r.status_code == 422 and r.json()["code"] == "no_agent_number"
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["test_call_index"] is None
    assert put(client, admin, cid, agent_number=AGENT).status_code == 200

    # 목록이 확인한 뒤에 바뀌면(첫 번호가 달라짐) 걸지 않는다
    client.patch(f"{BASE}/{cid}", json={"allow_numbers_remove": [0], "allow_numbers_add": [OTHER_MOBILE],
                                        "allow_numbers_version": conn["allow_numbers_version"]}, headers=admin)
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 409 and r.json()["code"] == "allow_list_changed"

    # 걸 수 없는 번호가 첫 칸에 있으면(저장소를 직접 고친 경우) 걸지 않는다
    session.expire_all()
    session.get(NotifyConnection, cid).allow_numbers_json = ["0607000199"]
    session.commit()
    fresh = client.get(BASE, headers=admin).json()[-1]
    for make in (call_body, inbound_body):
        r = diag(client, admin, cid, make(fresh))
        assert r.status_code == 422 and r.json()["code"] == "test_number_not_callable"
        assert_no_leak(r.json())
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["test_call_index"] is None
    assert spy.calls == [] and stored(session, cid) is None and stored(session, bare["id"]) is None


def test_call_is_bound_to_the_list_as_it_is_when_the_call_is_recorded(client, admin, fake_provider, spy, monkeypatch,
                                                                       session):
    conn = ready(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    real = voice._prepare_sync

    def prepare_then_someone_edits(own_session, conn_id, data):
        prep = real(own_session, conn_id, data)
        other = next(get_session())  # 검사를 지난 바로 뒤에 다른 요청이 첫 허용 번호를 바꿨다
        try:
            other.get(NotifyConnection, cid).allow_numbers_json = ["01000000198", SENTINEL_DIGITS]
            other.commit()
        finally:
            other.close()
        return prep

    monkeypatch.setattr(voice, "_prepare_sync", prepare_then_someone_edits)
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 409 and r.json()["code"] == "allow_list_changed"
    assert spy.calls == [] and stored(session, cid) is None and not diagnose_mod._RUNNING and not voice._VOICE_RUNNING


def test_inbound_steps_only_when_requested(client, admin, fake_provider, spy):
    conn = ready(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    cid = conn["id"]
    for body, code in (({"inbound": "true", "allow_numbers_version": conn["allow_numbers_version"]}, "invalid_request"),
                       ({"inbound": 1, "allow_numbers_version": conn["allow_numbers_version"]}, "invalid_request"),
                       ({"steps": ["P12"]}, "steps_not_in_part"), ({"steps": ["P14"]}, "steps_not_in_part"),
                       (inbound_body(conn, wait_inbound_s=9), "invalid_wait"),
                       (inbound_body(conn, wait_inbound_s=181), "invalid_wait"),
                       (inbound_body(conn, wait_inbound_s="90"), "invalid_request"),
                       (inbound_body(conn, wait_inbound_s=True), "invalid_request")):
        r = diag(client, admin, cid, body)
        assert r.status_code == 422 and r.json()["code"] == code, (body, r.text)
    assert diag(client, admin, cid, {}).status_code == 200 and spy.chunks == [[5, 9, 11]]  # 기본은 받지 않는다
    spy.calls.clear()

    r = diag(client, admin, cid, inbound_body(conn))
    assert r.status_code == 200, r.text
    assert spy.chunks == [[5, 11, 12, 13], [14]]
    assert all(c["call_to"] == SENTINEL_DIGITS and c["wait_inbound_s"] == 90 for c in spy.calls)
    body = r.json()
    assert body["part"] == "inbound" and body["called_real"] is False and body["calls"] == []  # 받는 것은 건 것이 아니다
    # 화면은 [받기]와 [거절]을 따로 보낸다
    spy.calls.clear()
    assert diag(client, admin, cid, inbound_body(conn, steps=["P12", "P13"], wait_inbound_s=10)).status_code == 200
    assert diag(client, admin, cid, inbound_body(conn, steps=["P14"], wait_inbound_s=180)).status_code == 200
    assert spy.chunks == [[5, 11, 12, 13], [5, 11, 14]]
    assert [c["wait_inbound_s"] for c in spy.calls] == [10, 180]


def test_missing_sdk_is_reported_not_installed_and_nothing_is_installed(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)
    cid = conn["id"]

    def no_sdk(name, *args):
        raise ImportError(f"No module named {name!r}")

    def no_install(*args, **kw):
        raise AssertionError("아무것도 설치하거나 띄우지 않는다")

    monkeypatch.setattr(dv.importlib, "import_module", no_sdk)
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: None)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, no_install)
    monkeypatch.setattr(os, "system", no_install)
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["sdk_installed"] is False
    r = diag(client, admin, cid, {})
    assert r.status_code == 200, r.text
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["ok"] is False and rows["P5"]["code"] == "sdk_not_installed"
    assert rows["P5"]["detail"] == dv.NOT_INSTALLED
    assert rows["P9"]["skipped"] and rows["P9"]["code"] == "skipped_no_sdk"
    assert rows["P11"]["skipped"] and rows["P11"]["code"] == "skipped_not_connected"
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"
    # 실제 통화를 눌러도 같은 까닭으로 멈춘다(걸리지 않음)
    r = diag(client, admin, cid, call_body(conn))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["code"] == "sdk_not_installed" and rows["P6"]["code"] == "skipped_not_connected"
    assert r.json()["called_real"] is False and [c["outcome"] for c in r.json()["calls"]] == ["not_placed"]
    imported = {a.name.split(".")[0] for node in ast.walk(ast.parse(FILE.read_text())) if isinstance(node, ast.Import)
                for a in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(ast.parse(FILE.read_text()))
                 if isinstance(node, ast.ImportFrom)}
    assert not imported & {"subprocess", "pip", "ensurepip", "venv", "clawops", "koreaaitel", "sys", "os"}


def test_sdk_installed_is_read_without_importing_the_sdk(monkeypatch):
    asked = []
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: asked.append(name) or object())
    assert voice.sdk_installed() is True and asked == ["clawops"]  # 꼭대기 이름만 — 하위 모듈을 물으면 SDK 가 불려 온다

    def broken(name):
        raise ValueError("clawops.__spec__ is None")

    monkeypatch.setattr(voice.importlib.util, "find_spec", broken)
    assert voice.sdk_installed() is False


def test_other_providers_are_stored_and_the_module_reports_a_missing_extra(client, admin, fake_provider, monkeypatch,
                                                                            world, spy):
    conn = ready(client, admin)
    cid = conn["id"]
    # 고른 모델의 묶음이 없으면 진단 모듈이 스스로 그 까닭을 낸다(API 는 선택지를 숨기지 않는다)
    sdk = FakeSdk(world, extra_missing=True)
    scripted(monkeypatch, world, sdk)
    r = diag(client, admin, cid, {})
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["code"] == "sdk_extra_missing" and rows["P5"]["detail"] == dv.EXTRA_MISSING
    assert sdk.agents == []

    monkeypatch.setattr(dv, "run_voice_checks", spy)
    assert put(client, admin, cid, provider="openai", secret=NEW_GOOGLE_KEY, model="rt-test").status_code == 200
    assert diag(client, admin, cid, {}).status_code == 200
    assert (spy.calls[-1]["voice"].provider, spy.calls[-1]["voice"].key) == ("openai", NEW_GOOGLE_KEY)
    assert put(client, admin, cid, provider="dashboard").status_code == 200
    for body in ({}, call_body(conn), inbound_body(conn)):
        r = diag(client, admin, cid, body)
        assert r.status_code == 422 and r.json()["code"] == "voice_provider_not_supported"
    assert len(spy.calls) == 1


def test_diagnose_needs_readable_keys(client, admin, fake_provider, spy, session):
    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    r = diag(client, admin, cid, {})
    assert r.status_code == 422 and r.json()["code"] == "voice_key_required"
    assert put(client, admin, cid, agent_number=AGENT).status_code == 200  # 줄은 있지만 키가 없다
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 422 and r.json()["code"] == "voice_key_required"
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200
    session.expire_all()
    session.get(VoiceSettings, cid).secret_ciphertext = "not-a-fernet-token"
    session.commit()
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 409 and r.json()["code"] == "voice_secret_unreadable"
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200  # 읽을 수 없는 옛 키 위에 다시 넣을 수 있다
    session.expire_all()
    session.get(NotifyConnection, cid).secret_ciphertext = "not-a-fernet-token"
    session.commit()
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 409 and r.json()["code"] == "secret_unreadable"
    assert spy.calls == [] and stored(session, cid) is None


def test_stored_voice_diagnosis_has_no_key_or_number(client, admin, session, fake_provider, monkeypatch):
    conn = ready(client, admin)
    cid = conn["id"]
    leak = f"{SENTINEL_KEY} {GOOGLE_KEY} {KAT_ACCOUNT} {SENTINEL_PHONE} {AGENT} {AGENT_DIGITS} +82 10 0000 0199 {KAT_SENDER}"
    bad = {n: dv.VoiceStep(id=f"P{n}", label=leak, ok=False, detail=f"실패 · {leak}", notes=[leak, leak], code=leak,
                           data={"readable": True, "tool_calls": 2, "note": leak, leak: 1, "roles": {"user": 1, leak: leak, f"k {leak}": 3},
                                 "deep": {"a": {"b": leak}}, "list": [leak]})
           for n in (5, 6, 7, 8, 11)}
    monkeypatch.setattr(dv, "run_voice_checks", Spy(bad))
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200, r.text
    for payload in (r.json(), stored(session, cid), last(client, admin, cid).json(),
                    client.get(f"{BASE}/{cid}/voice", headers=admin).json()):
        assert_no_leak(payload)
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P6"]["label"] == dv.LABELS["P6"] and "실패" in rows["P6"]["detail"]  # 이름표는 우리 것만
    assert rows["P6"]["data"]["readable"] is True and rows["P6"]["data"]["tool_calls"] == 2
    assert rows["P6"]["data"]["roles"] == {"user": 1} and "deep" not in rows["P6"]["data"]
    saved = stored(session, cid)
    assert saved["real"] is False and set(saved) == {"state", "part", "ran_at", "by", "steps", "real", "call_unknown",
                                                      "calls"}
    assert all(set(c) == {"at", "by", "outcome"} for c in saved["calls"])


def test_every_response_and_error_is_free_of_key_account_and_numbers(client, admin, fake_provider, spy, session):
    conn = connection(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    cid = conn["id"]
    url = f"{BASE}/{cid}/voice"
    answers = [
        client.get(url, headers=admin),
        client.put(url, json={"secret": GOOGLE_KEY, "agent_number": AGENT, "model": "m-1"}, headers=admin),
        client.put(url, json={"secret": SENTINEL_KEY + " x"}, headers=admin),
        client.put(url, json={"secret": GOOGLE_KEY, "agent_number": SENTINEL_PHONE + "9"}, headers=admin),
        client.put(url, json={"secret": [GOOGLE_KEY]}, headers=admin),
        client.put(url, json={"agent_number": {"n": SENTINEL_PHONE}}, headers=admin),
        client.put(url, json={"model": GOOGLE_KEY + "!"}, headers=admin),
        client.put(url, json={"provider": GOOGLE_KEY}, headers=admin),
        client.put(url, json={"voices_by_language": {"en": {GOOGLE_KEY: SENTINEL_PHONE}}}, headers=admin),
        client.put(url, json={"provider": "openai"}, headers=admin),
        client.post(f"{url}/diagnose", json={"steps": [SENTINEL_PHONE]}, headers=admin),
        client.post(f"{url}/diagnose", json={"call": SENTINEL_PHONE}, headers=admin),
        client.post(f"{url}/diagnose", json=call_body(conn, allow_numbers_version=SENTINEL_PHONE), headers=admin),
        client.post(f"{url}/diagnose", json=call_body(conn, allow_numbers_version="x" * 101), headers=admin),
        client.post(f"{url}/diagnose", json=inbound_body(conn, wait_inbound_s=1000000199), headers=admin),
        client.post(f"{url}/diagnose", json={}, headers=admin),
        client.post(f"{url}/diagnose", json=call_body(conn), headers=admin),
        client.post(f"{url}/diagnose", json=inbound_body(conn), headers=admin),
        client.get(f"{url}/diagnosis", headers=admin),
        client.get(url, headers=admin),
    ]
    statuses = [a.status_code for a in answers]
    assert statuses == [200, 200, 422, 422, 422, 422, 422, 422, 422, 422, 422, 422, 409, 422, 422, 200, 200, 200, 200,
                        200], statuses
    for answer in answers:
        assert_no_leak(answer.json())
        assert set(answer.json()) >= {"code", "message", "detail"} or answer.status_code == 200
    assert_no_leak(stored(session, cid))
    assert answers[-1].json()["agent_number_masked"] == "070-****-0144"


# ── 대본 가짜 SDK 로 끝까지 ──────────────────────────────────────────


def test_test_call_with_the_scripted_sdk_dials_the_first_allowed_number_once(client, admin, fake_provider, monkeypatch,
                                                                             world, session, caplog):
    caplog.set_level(logging.DEBUG)
    conn = ready(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    cid = conn["id"]
    sdk = FakeSdk(world, calls=[GOOD_CALL])
    scripted(monkeypatch, world, sdk)
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200, r.text
    assert sdk.dialed == [(SENTINEL_DIGITS, dv.RING_TIMEOUT_S)]  # 첫 허용 번호로 한 통만
    assert sdk.agent.kw["from_"] == AGENT_DIGITS and sdk.agent.kw["api_key"] == SENTINEL_KEY
    assert sdk.agent.kw["builtin_tools"] == "none" and sdk.agent.disconnects == 1
    body = r.json()
    rows = {s["id"]: s for s in body["steps"]}
    assert [rows[i]["code"] for i in ("P5", "P6", "P7", "P8", "P11")] == ["ok"] * 5
    assert rows["P6"]["data"] == {"first_response_ms": 400, "cut": False} and rows["P8"]["data"] == {"tool_calls": 1}
    assert rows["P7"]["data"] == {"events": 3, "roles": {"assistant": 2, "user": 1}}
    assert rows["P5"]["data"] == {"sdk_version": "9.9.9"} and isinstance(rows["P5"]["latency_ms"], int)
    assert body["called_real"] is True and body["call_unknown"] is False
    assert [c["outcome"] for c in body["calls"]] == ["placed"]
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "ok"
    assert_no_leak(body)
    assert_no_leak(stored(session, cid), "안녕하세요", "제 번호는")
    assert_clean(caplog, KAT_ACCOUNT, GOOGLE_KEY, AGENT_DIGITS)

    # 받지 않은 전화: 걸렸고 끝났다(모름이 아니다) — 다시 걸 수 있다
    sdk.calls.append(((20000, "call_failed", "no-answer"),))
    r = diag(client, admin, cid, call_body(conn))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P6"]["code"] == "no_answer" and rows["P7"]["code"] == "skipped_no_call"
    assert r.json()["called_real"] is True and [c["outcome"] for c in r.json()["calls"]] == ["placed", "placed"]
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"
    assert len(sdk.dialed) == 2 and {to for to, _ in sdk.dialed} == {SENTINEL_DIGITS}


def test_inbound_check_with_the_scripted_sdk_takes_only_the_first_allowed_number(client, admin, fake_provider,
                                                                                 monkeypatch, world, caplog):
    caplog.set_level(logging.DEBUG)
    conn = ready(client, admin, SENTINEL_PHONE, OTHER_MOBILE)
    cid = conn["id"]
    sdk = FakeSdk(world, inbound=[(1000, OTHER_MOBILE), (3000, SENTINEL_PHONE)])
    scripted(monkeypatch, world, sdk)
    r = diag(client, admin, cid, inbound_body(conn, steps=["P12", "P13"], wait_inbound_s=30))
    assert r.status_code == 200, r.text
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert [rows[i]["code"] for i in ("P5", "P11", "P12", "P13")] == ["ok"] * 4
    assert rows["P13"]["data"] == {"readable": True, "restricted": False}
    assert [i.rejected for i in sdk.incoming] == [True, False] and len(sdk.accepted) == 1  # 둘째 허용 번호도 받지 않는다
    assert sdk.dialed == [] and r.json()["called_real"] is False and r.json()["calls"] == []
    r = diag(client, admin, cid, inbound_body(conn, steps=["P14"], wait_inbound_s=30))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P14"]["code"] == "ok" and rows["P12"]["code"] == "ok"  # 앞 단추의 결과는 그대로 남는다
    assert rows["P12"]["ran_at"] != r.json()["ran_at"] and rows["P14"]["ran_at"] == r.json()["ran_at"]
    assert len(sdk.accepted) == 1 and sdk.dialed == []
    assert_no_leak(r.json())
    assert_clean(caplog, KAT_ACCOUNT, GOOGLE_KEY, AGENT_DIGITS)


def test_worker_connected_is_passed_truthfully(client, admin, fake_provider, monkeypatch, world, spy):
    conn = ready(client, admin)
    cid = conn["id"]
    assert voice.worker_connected(AGENT_DIGITS) is False  # 아직 일꾼이 없다
    assert diag(client, admin, cid, {}).status_code == 200 and spy.calls[-1]["worker_connected"] is False
    asked = []
    monkeypatch.setattr(voice, "worker_connected", lambda number: asked.append(number) or True)
    assert diag(client, admin, cid, {}).status_code == 200
    assert spy.calls[-1]["worker_connected"] is True and asked == [AGENT_DIGITS]
    # 진단 모듈은 SDK 를 건드리지 않고 끝낸다 — 통화도 걸리지 않고, 앞서 확인한 상태도 그대로다
    sdk = FakeSdk(world)
    scripted(monkeypatch, world, sdk)
    r = diag(client, admin, cid, call_body(conn))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["code"] == "worker_connected" and rows["P6"]["code"] == "skipped_not_connected"
    assert sdk.agents == [] and sdk.dialed == [] and [c["outcome"] for c in r.json()["calls"]] == ["not_placed"]
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "ok"


# ── 실제 통화의 안전 장치 ────────────────────────────────────────────


def test_calling_record_is_written_before_the_call(client, admin, fake_provider, monkeypatch, session):
    conn = ready(client, admin)
    cid = conn["id"]
    seen = []

    def peek(_call) -> None:
        other = next(get_session())
        try:
            seen.append(other.get(VoiceSettings, cid).last_diagnosis_json)
        finally:
            other.close()

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=peek))
    assert diag(client, admin, cid, {}).status_code == 200  # 걸지 않는 진단은 미리 적지 않는다
    assert seen == [None]
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200
    before = seen[1]
    assert before["state"] == "calling" and before["part"] == "call" and before["by"]
    assert [c["outcome"] for c in before["calls"]] == ["calling"] and before["calls"][0]["by"] == before["by"]
    assert len(before["steps"]) == 10  # 앞 진단의 걸음 줄은 지우지 않는다
    assert_no_leak(before)
    after = stored(session, cid)
    assert after["state"] == "done" and [c["outcome"] for c in after["calls"]] == ["placed"]
    assert after["calls"][0]["at"] == before["calls"][0]["at"]


def test_call_of_unknown_outcome_blocks_an_immediate_repeat(client, admin, fake_provider, monkeypatch, session):
    conn = ready(client, admin)
    cid = conn["id"]
    unsure = Spy({6: row(6, "dial_timeout", f"{dv.DIAL_TIMEOUT} {dv.MAYBE_PLACED}", maybe_sent=True),
                  7: row(7, "skipped_no_call", dv.NO_CALL, skipped=True, maybe_sent=True)})
    monkeypatch.setattr(dv, "run_voice_checks", unsure)
    r = diag(client, admin, cid, call_body(conn, steps=["P6", "P7", "P8", "P10"]))
    body = r.json()
    assert r.status_code == 200 and body["call_unknown"] is True and body["called_real"] is False
    assert [c["outcome"] for c in body["calls"]] == ["unknown"]
    rows = {s["id"]: s for s in body["steps"]}
    assert rows["P6"]["maybe_sent"] is True and rows["P6"]["ok"] is False
    assert unsure.chunks == [[5, 6, 7, 8, 11]]  # 끝이 확인되지 않은 통화 뒤에는 둘째 통화를 걸지 않는다
    assert rows["P10"]["skipped"] and rows["P10"]["code"] == "skipped_stopped" and rows["P10"]["detail"] == dv.STOPPED

    again = diag(client, admin, cid, call_body(conn))
    assert again.status_code == 409 and again.json()["code"] == "call_unknown_pending"
    assert len(unsure.calls) == 1 and [c["outcome"] for c in stored(session, cid)["calls"]] == ["unknown"]
    assert diag(client, admin, cid, {}).status_code == 200  # 걸지 않는 진단은 막지 않는다
    assert diag(client, admin, cid, inbound_body(conn)).status_code == 200
    assert last(client, admin, cid).json()["calls"][-1]["outcome"] == "unknown"

    fine = Spy()
    monkeypatch.setattr(dv, "run_voice_checks", fine)
    confirmed = diag(client, admin, cid, call_body(conn, confirm_recall=True))
    assert confirmed.status_code == 200 and confirmed.json()["called_real"] is True
    assert [c["outcome"] for c in confirmed.json()["calls"]] == ["unknown", "placed"]
    assert diag(client, admin, cid, call_body(conn)).status_code == 200  # 결과를 아는 통화 뒤에는 막지 않는다


def test_a_call_still_alive_by_the_budget_is_unknown_even_if_the_rows_look_fine(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)

    def still_alive(seen) -> None:
        seen["budget"].maybe_live = True  # 진단 모듈이 「건 통화가 끝난 것이 확인되지 않았다」고 남겼다

    alive = Spy(during=still_alive)
    monkeypatch.setattr(dv, "run_voice_checks", alive)
    r = diag(client, admin, conn["id"], call_body(conn, steps=["P6", "P10"]))
    assert r.json()["call_unknown"] is True and r.json()["called_real"] is False
    assert [c["outcome"] for c in r.json()["calls"]] == ["unknown"] and alive.chunks == [[5, 6, 11]]
    assert diag(client, admin, conn["id"], call_body(conn)).status_code == 409


def test_unknown_call_stops_blocking_after_ten_minutes(client, admin, fake_provider, spy, session):
    conn = ready(client, admin)
    cid = conn["id"]
    now = datetime.now(UTC)
    for minutes, expected in ((9, 409), (11, 200)):
        found = session.get(VoiceSettings, cid)
        at = (now - timedelta(minutes=minutes)).isoformat()
        found.last_diagnosis_json = {"state": "done", "part": "call", "ran_at": at, "by": "관리자", "steps": [],
                                     "real": False, "call_unknown": True,
                                     "calls": [{"at": at, "by": "관리자", "outcome": "unknown"}]}
        session.commit()
        r = diag(client, admin, cid, call_body(conn))
        assert r.status_code == expected, (minutes, r.text)
        session.expire_all()


def test_a_call_left_unfinished_reads_as_unknown_and_blocks_a_repeat(client, admin, fake_provider, spy, session):
    conn = ready(client, admin)
    cid = conn["id"]
    assert diag(client, admin, cid, {}).status_code == 200
    kept = stored(session, cid)["steps"]

    def leave(minutes: float) -> None:
        at = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        found = session.get(VoiceSettings, cid)
        found.last_diagnosis_json = {"state": "calling", "part": "call", "ran_at": at, "by": "관리자", "steps": kept,
                                     "real": False, "call_unknown": False,
                                     "calls": [{"at": at, "by": "관리자", "outcome": "calling"}]}
        session.commit()
        session.expire_all()

    leave(1)  # 서버가 걸다가 죽었다 — 아직 상한 안: 도는 중으로 보인다
    shown = last(client, admin, cid).json()
    assert shown["state"] == "running" and shown["part"] == "call" and shown["steps"] == []
    assert shown["call_unknown"] is False and [c["outcome"] for c in shown["calls"]] == ["calling"]
    assert diag(client, admin, cid, call_body(conn)).status_code == 409

    leave(voice.STALE_CALL_S / 60 + 1)  # 상한이 지났다 — 「모름」으로 읽힌다
    shown = last(client, admin, cid).json()
    assert shown["state"] == "done" and shown["call_unknown"] is True and shown["called_real"] is False
    rows = {s["id"]: s for s in shown["steps"]}
    assert rows["P6"]["code"] == "not_finished" and rows["P6"]["maybe_sent"] is True and rows["P6"]["ok"] is False
    assert rows["P5"]["code"] == "ok" and len(shown["steps"]) == 10
    assert [c["outcome"] for c in shown["calls"]] == ["unknown"]
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 409 and r.json()["code"] == "call_unknown_pending" and spy.chunks == [[5, 9, 11]]
    assert diag(client, admin, cid, call_body(conn, confirm_recall=True)).status_code == 200


def test_ceiling_keeps_finished_steps_and_marks_the_rest(client, admin, fake_provider, monkeypatch, session):
    conn = ready(client, admin)
    cid = conn["id"]
    asked = []
    monkeypatch.setattr(voice, "_ceiling", lambda steps, wait: asked.append((steps, wait)) or 0.3)

    async def hang_on_second(seen) -> None:
        if 10 in seen["steps"]:
            seen["budget"].maybe_live = True  # 둘째 통화를 건 뒤 멈췄다
            await asyncio.wait_for(asyncio.Event().wait(), 5)

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=hang_on_second))
    r = diag(client, admin, cid, call_body(conn, steps=["P6", "P7", "P8", "P10"]))
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {s["id"]: s for s in body["steps"]}
    assert [rows[i]["code"] for i in ("P5", "P6", "P7", "P8", "P11")] == ["ok"] * 5  # 끝난 걸음은 그대로
    assert rows["P10"]["code"] == "timeout" and rows["P10"]["ok"] is False and rows["P10"]["skipped"] is False
    assert rows["P10"]["maybe_sent"] is True and dv.MAYBE_PLACED in rows["P10"]["detail"]
    assert body["call_unknown"] is True and [c["outcome"] for c in body["calls"]] == ["unknown"]
    assert asked == [((5, 6, 7, 8, 11), 90), ((10,), 90)] and not diagnose_mod._RUNNING
    assert diag(client, admin, cid, call_body(conn)).status_code == 409  # 다시 걸어 보지 않는다

    async def hang(_seen) -> None:
        await asyncio.wait_for(asyncio.Event().wait(), 5)

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=hang))
    r = diag(client, admin, cid, {})  # 걸지 않는 진단이 상한에 걸리면 「모름」이 아니다
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert [rows[i]["code"] for i in ("P5", "P9", "P11")] == ["timeout"] * 3
    assert not any(rows[i]["maybe_sent"] for i in ("P5", "P9", "P11")) and rows["P6"]["code"] == "ok"
    assert "넘겨" in rows["P5"]["detail"] and client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"


def test_ceilings_come_from_the_diagnostics_caps():
    link = diagnostics.RESOLVE_TIMEOUT_S + dv.CONNECT_TIMEOUT_S
    close = 2 * dv.HANGUP_TIMEOUT_S + dv.END_GRACE_S
    cut = dv.HANGUP_TIMEOUT_S + dv.END_GRACE_S
    assert voice._ceiling((5, 9, 11), 90) == link + close + voice.MARGIN_S == 50
    assert voice._ceiling((5, 6, 7, 8, 11), 90) == voice._ceiling((10,), 90) == link + dv.CALL_CUT_S + cut + close + 10 == 120
    assert voice._ceiling((5, 11, 12, 13), 90) == link + 90 + dv.INBOUND_START_S + dv.INBOUND_HOLD_S + cut + close + 10 == 185
    assert voice._ceiling((14,), 180) == link + 180 + dv.REJECT_GRACE_S + cut + close + 10 == 243
    assert voice.STALE_CALL_S >= 2 * voice._ceiling((10,), 90)  # 「거는 중」 기록은 통화 요청의 상한보다 오래 기다린 뒤에 「모름」


def test_failed_link_does_not_try_the_second_call(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)
    cid = conn["id"]
    down = Spy({5: row(5, "bad_key", "API 키가 맞지 않습니다."),
                **{n: row(n, "skipped_not_connected", dv.NOT_LINKED, skipped=True) for n in (6, 7, 8, 11)}})
    monkeypatch.setattr(dv, "run_voice_checks", down)
    r = diag(client, admin, cid, call_body(conn, steps=["P6", "P10"]))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert down.chunks == [[5, 6, 11]]
    assert rows["P10"]["skipped"] and rows["P10"]["code"] == "skipped_not_connected"
    assert r.json()["called_real"] is False and [c["outcome"] for c in r.json()["calls"]] == ["not_placed"]
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"
    assert diag(client, admin, cid, call_body(conn)).status_code == 200  # 걸리지 않은 것은 다시 눌러도 된다


def test_inbound_call_that_could_not_be_cut_stops_the_reject_check(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)
    stuck = Spy({12: row(12, "cut_unconfirmed", dv.CUT_UNCONFIRMED)})
    monkeypatch.setattr(dv, "run_voice_checks", stuck)
    r = diag(client, admin, conn["id"], inbound_body(conn))
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert stuck.chunks == [[5, 11, 12, 13]] and rows["P14"]["code"] == "skipped_stopped"
    assert r.json()["call_unknown"] is False and r.json()["calls"] == []


def test_call_log_is_kept_capped_and_has_no_number(client, admin, fake_provider, spy, session):
    conn = ready(client, admin)
    cid = conn["id"]
    for _ in range(voice.CALLS_KEPT + 2):
        assert diag(client, admin, cid, call_body(conn)).status_code == 200
    saved = stored(session, cid)
    assert len(saved["calls"]) == voice.CALLS_KEPT and {c["outcome"] for c in saved["calls"]} == {"placed"}
    assert_no_leak(saved)
    shown = last(client, admin, cid).json()["calls"]
    assert len(shown) == voice.CALLS_KEPT and shown == sorted(shown, key=lambda c: c["at"])


@pytest.mark.parametrize(("rows", "body", "status"), [
    ({}, "connection", "ok"),
    ({5: ("bad_key", False)}, "connection", "failed"),
    ({11: ("bad_number", False)}, "connection", "failed"),
    ({5: ("sdk_extra_missing", False)}, "call", "failed"),
    ({6: ("no_answer", False)}, "call", "failed"),
    ({6: ("skipped_no_number", True)}, "call", "ok"),
    ({9: ("not_supported", True)}, "p9", "unknown"),
    ({12: ("no_inbound", False)}, "inbound", "ok"),
])
def test_status_follows_connection_binding_and_call(client, admin, fake_provider, monkeypatch, rows, body, status):
    conn = ready(client, admin)
    cid = conn["id"]
    made = {n: row(n, code, "결과입니다.", skipped=skipped) for n, (code, skipped) in rows.items()}
    monkeypatch.setattr(dv, "run_voice_checks", Spy(made))
    sent = {"connection": {}, "p9": {"steps": ["P9"]}, "call": call_body(conn), "inbound": inbound_body(conn)}[body]
    assert diag(client, admin, cid, sent).status_code == 200
    shown = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert shown["status"] == status and (shown["checked_at"] is not None)


def test_step_rows_carry_over_and_a_good_call_clears_an_old_failure(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)
    cid = conn["id"]
    monkeypatch.setattr(dv, "run_voice_checks", Spy({6: row(6, "busy", "통화 중이었습니다.")}))
    first = diag(client, admin, cid, {}).json()
    second = diag(client, admin, cid, call_body(conn)).json()
    rows = {s["id"]: s for s in second["steps"]}
    assert rows["P9"]["ran_at"] == first["ran_at"] != second["ran_at"]  # 다른 단추의 결과는 남는다
    assert rows["P5"]["ran_at"] == rows["P6"]["ran_at"] == rows["P11"]["ran_at"] == second["ran_at"]
    assert rows["P10"]["ran_at"] is None and rows["P12"]["code"] == "skipped_not_requested"
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"
    monkeypatch.setattr(dv, "run_voice_checks", Spy())
    third = diag(client, admin, cid, call_body(conn)).json()
    assert {s["id"]: s for s in third["steps"]}["P6"]["code"] == "ok"
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "ok"


# ── 한 번에 하나 · DB 를 쥐지 않음 ───────────────────────────────────


async def test_one_diagnosis_at_a_time_across_both_kinds(client, admin, fake_provider, monkeypatch):
    conn = ready(client, admin)
    cid = conn["id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(_seen) -> None:
        entered.set()
        async with asyncio.timeout(3):
            await release.wait()

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=hold))
    url = f"{BASE}/{cid}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        first = asyncio.create_task(ac.post(f"{url}/voice/diagnose", json=call_body(conn), headers=admin))
        async with asyncio.timeout(3):
            await entered.wait()
        second = await ac.post(f"{url}/voice/diagnose", json={}, headers=admin)
        rest = await ac.post(f"{url}/diagnose", json={"steps": ["P1"]}, headers=admin)  # 연결 진단(P1~P4)도 겹치지 않는다
        change = await ac.put(f"{url}/voice", json={"model": "other"}, headers=admin)
        shown = await ac.get(f"{url}/voice/diagnosis", headers=admin)
        release.set()
        async with asyncio.timeout(3):
            done = await first
        after = await ac.get(f"{url}/voice/diagnosis", headers=admin)
    for answer in (second, rest, change):
        assert answer.status_code == 409 and answer.json()["code"] == "diagnosis_running"
    assert shown.json()["state"] == "running" and shown.json()["part"] == "call" and shown.json()["steps"] == []
    assert [c["outcome"] for c in shown.json()["calls"]] == ["calling"]
    assert done.status_code == 200 and not diagnose_mod._RUNNING and not voice._VOICE_RUNNING
    assert after.json()["state"] == "done" and after.json() == done.json()

    diagnose_mod._RUNNING.add(cid)  # 연결 진단이 도는 중이면 음성 진단을 받지 않는다
    try:
        r = diag(client, admin, cid, call_body(conn))
    finally:
        diagnose_mod._RUNNING.discard(cid)
    assert r.status_code == 409 and r.json()["code"] == "diagnosis_running"


async def test_running_marker_is_cleared_on_cancel_and_error(client, admin, fake_provider, monkeypatch):
    cid = ready(client, admin)["id"]
    started = asyncio.Event()

    async def hang(_seen) -> None:
        started.set()
        await asyncio.wait_for(asyncio.Event().wait(), 5)

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=hang))
    session = next(get_session())
    task = asyncio.create_task(voice.run(session, cid, voice.VoiceDiagnoseIn(), "관리자"))
    async with asyncio.timeout(2):
        await started.wait()
    assert cid in diagnose_mod._RUNNING and cid in voice._VOICE_RUNNING
    reader = next(get_session())
    shown = voice.last(reader, cid)  # 걸지 않는 진단도 도는 동안은 「도는 중」으로 읽힌다(미리 적은 기록이 없어도)
    reader.close()
    assert shown.state == "running" and shown.part == "connection" and shown.steps == [] and shown.by == "관리자"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cid not in diagnose_mod._RUNNING and cid not in voice._VOICE_RUNNING

    def boom(_seen) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=boom))
    with pytest.raises(RuntimeError):
        await voice.run(session, cid, voice.VoiceDiagnoseIn(), "관리자")
    assert cid not in diagnose_mod._RUNNING and cid not in voice._VOICE_RUNNING
    session.close()


def test_no_db_write_is_held_during_voice_diagnosis_and_rows_are_read_again(client, admin, fake_provider, monkeypatch,
                                                                            session):
    conn = ready(client, admin)
    cid = conn["id"]
    wrote = []

    def other_writer(_seen) -> None:
        other = next(get_session())
        try:
            other.get(VoiceSettings, cid).voice_unknown = "Kore"
            other.get(NotifyConnection, cid).name = "진단 중에 바꿈"
            other.commit()  # 경로가 쓰기를 쥐고 있으면 여기서 막힌다
            wrote.append(True)
        finally:
            other.close()

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=other_writer))
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200 and wrote == [True]
    shown = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert shown["voice_unknown"] == "Kore" and shown["status"] == "ok"  # 경로가 옛 값으로 덮지 않았다
    assert client.get(BASE, headers=admin).json()[0]["name"] == "진단 중에 바꿈"


def test_result_of_a_deleted_connection_is_returned_but_not_saved(client, admin, fake_provider, monkeypatch, session):
    conn = ready(client, admin)
    cid = conn["id"]

    def delete(_seen) -> None:
        other = next(get_session())
        try:
            other.delete(other.get(VoiceSettings, cid))
            other.commit()
        finally:
            other.close()

    monkeypatch.setattr(dv, "run_voice_checks", Spy(during=delete))
    r = diag(client, admin, cid, {})
    assert r.status_code == 200 and r.json()["state"] == "done" and len(r.json()["steps"]) == 10
    assert session.get(VoiceSettings, cid) is None


# ── 모듈의 꼴 ────────────────────────────────────────────────────────


def test_voice_routes_answer_in_the_real_app(client):
    """`app/main.py` 는 프로그램의 router.py 가 내보낸 라우터만 붙인다 — 그 한 줄이 빠지면 네 길이 모두 404 가 된다."""
    assert router_mod.voice_router is voice.router
    for method, tail in (("GET", "/voice"), ("PUT", "/voice"), ("POST", "/voice/diagnose"), ("GET", "/voice/diagnosis")):
        r = client.request(method, f"{BASE}/1{tail}", json={})
        assert r.status_code == 401 and r.json()["code"] == "unauthorized", (method, tail, r.status_code)  # 404 가 아니다


def test_routes_are_mounted_admin_only_and_database_routes_are_plain_functions():
    paths = {(method.upper(), path) for path, ops in app.openapi()["paths"].items() if "/voice" in path for method in ops}
    assert paths == {("GET", "/api/notify/connections/{conn_id}/voice"), ("PUT", "/api/notify/connections/{conn_id}/voice"),
                     ("POST", "/api/notify/connections/{conn_id}/voice/diagnose"),
                     ("GET", "/api/notify/connections/{conn_id}/voice/diagnosis")}
    assert not [n for n in ("get_voice", "put_voice", "last_voice_diagnosis") if inspect.iscoroutinefunction(getattr(voice, n))]
    assert inspect.iscoroutinefunction(voice.run_voice_diagnosis)
    source = FILE.read_text()
    assert "diagnostics_voice.run_voice_checks(" in source and "print(" not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "app.notify.diagnostics_voice":
            assert "run_voice_checks" not in {a.name for a in node.names}  # 모듈 속성으로 불러야 시험 대역이 듣는다
    # 요청 본문에 번호를 받는 칸이 없다 — 거는 번호는 저장된 첫 허용 번호뿐
    assert set(voice.VoiceDiagnoseIn.model_fields) == {"steps", "call", "inbound", "allow_numbers_version",
                                                       "confirm_recall", "wait_inbound_s"}


def test_real_sdk_is_never_loaded_by_these_tests(client, admin, fake_provider):
    conn = ready(client, admin)
    r = diag(client, admin, conn["id"], call_body(conn))  # 대역 없이 — 진단 모듈이 시험에서는 실제 SDK 를 쓰지 않는다
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["code"] in ("sdk_blocked_in_tests", "sdk_not_installed")
    assert r.json()["called_real"] is False and [c["outcome"] for c in r.json()["calls"]] == ["not_placed"]
