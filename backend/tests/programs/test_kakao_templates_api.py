"""카카오톡 채널·문안 상태 API(계획 4 Task 101). 쓰지 않고 읽기만 — 발송·등록·켜기는 없다.

- 목록 읽는 길이 확인되지 않은 지금: `sync` 는 501, `GET …/kakao` 는 `available: false`(제공사를 부르지 않는다).
- 확인된 뒤의 꼴은 가짜(`provider.KAKAO_LISTING_CONFIRMED` 를 시험 안에서만 참으로 + 가짜 목록)로 시험한다.
- 모든 응답의 JSON 을 끝까지 훑어 키·Account ID·번호가 없음을 본다. 실제 제공사·망을 부르지 않는다.
"""

import json
import sqlite3
import unicodedata
from contextlib import closing

import pytest

from app.config import Settings
from app.main import app
from app.outreach import kakao, provider
from app.outreach.harness import events, registry
from app.outreach.harness.types import Ref
from app.outreach.provider import KakaoChannelInfo, KakaoTemplateInfo
from app.programs.notify_settings import diagnose
from app.programs.notify_settings import router as router_mod
from app.programs.notify_settings import templates as templates_mod
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import KakaoTemplate, NotifyConnection
from tests.harness_doubles import FakeChannel
from tests.helpers import auth
from tests.outreach.harness.test_gate import message, person, reread, send, trail
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)
from tests.provider_doubles import KAT_ACCOUNT, KatMock, RunawayFake

pytestmark = pytest.mark.usefixtures("time_guard")

BASE = "/api/notify/connections"
NEW = {"name": "한국AI통신", "secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT}
REPLY = "답은 이 번호로 문자 주세요: 070-0000-0123"
BODY = "#{이름}님, #{날짜} 타설 예정입니다. 가능 여부를 알려 주세요.\n" + REPLY


class Lister:
    """kakao_channels·kakao_templates 만 있는 제공사 가짜(부름 수 상한). during 은 부를 때마다 불린다(DB 잠금 확인)."""

    LIMIT = 40

    def __init__(self, channels=(), templates=None, fail: Exception | None = None) -> None:
        self.channels = list(channels)
        self.templates = dict(templates or {})
        self.fail = fail
        self.calls: list[str] = []
        self.during = None

    async def _answer(self, what: str, value):
        self.calls.append(what)
        if len(self.calls) > self.LIMIT:
            raise RunawayFake("카카오 목록 가짜를 너무 많이 불렀습니다")
        if self.during is not None:
            self.during()
        if self.fail is not None:
            raise self.fail
        return list(value)

    async def kakao_channels(self):
        return await self._answer("channels", self.channels)

    async def kakao_templates(self, channel: str):
        return await self._answer(channel, self.templates.get(channel, []))


def chan(n: int = 1, **over) -> KakaoChannelInfo:
    return KakaoChannelInfo(**{"id": f"ch-{n}", "name": f"크로노스 현장 {n}", "status": "connected", **over})


def tpl(n: int, status: str = "approved", body: str = BODY) -> KakaoTemplateInfo:
    return KakaoTemplateInfo(id=f"tpl-{n}", body=body, status=status)


@pytest.fixture
def field(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def conn_id(client, admin, fake_provider) -> int:
    r = client.post(BASE, json=NEW, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def lister(monkeypatch) -> Lister:
    """목록 읽는 길이 확인된 것처럼(이 시험 안에서만) + 어느 연결이든 이 가짜를 쓴다."""
    fake = Lister([chan(1)], {"ch-1": [tpl(1), tpl(2, "reviewing"), tpl(3, "reviewing")]})
    monkeypatch.setattr(provider, "KAKAO_LISTING_CONFIRMED", True)
    monkeypatch.setattr(provider, "client_for", lambda row: fake)
    return fake


def strings(value) -> list[str]:
    """JSON 의 모든 글(키 포함)."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return [str(value)]


def assert_no_secrets(response) -> None:
    for text in strings(response.json()):
        digits = "".join(c for c in text if c.isdigit())
        assert SENTINEL_KEY not in text and KAT_ACCOUNT not in text and KAT_ACCOUNT[-8:] not in text, text
        assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits, text


def sync(client, admin, cid: int):
    r = client.post(f"{BASE}/{cid}/kakao/sync", headers=admin)
    assert_no_secrets(r)
    return r


def view(client, admin, cid: int) -> dict:
    r = client.get(f"{BASE}/{cid}/kakao", headers=admin)
    assert r.status_code == 200, r.text
    assert_no_secrets(r)
    return r.json()


def patch_template(client, admin, cid: int, tid: int, **body):
    r = client.patch(f"{BASE}/{cid}/kakao/templates/{tid}", json=body, headers=admin)
    assert_no_secrets(r)
    return r


def by_template(view_json: dict) -> dict[str, dict]:
    return {t["provider_template_id"]: t for t in view_json["templates"]}


# ── 걸려 있음 ───────────────────────────────────────────────────────


def test_routes_are_mounted_in_the_real_app(client, admin, conn_id):
    paths = app.openapi()["paths"]  # 붙은 라우터의 길(FastAPI 는 라우터를 감싸 붙여 app.routes 에 바로 보이지 않는다)
    for method, path in (("post", "/api/notify/connections/{conn_id}/kakao/sync"),
                         ("get", "/api/notify/connections/{conn_id}/kakao"),
                         ("patch", "/api/notify/connections/{conn_id}/kakao/templates/{tid}"),
                         ("get", "/api/notify/templates")):
        assert method in paths.get(path, {}), (method, path)
    assert client.post(f"{BASE}/{conn_id}/kakao/sync", headers=admin).status_code == 501
    assert client.patch(f"{BASE}/{conn_id}/kakao/templates/1", json={}, headers=admin).status_code == 404
    assert client.patch(f"{BASE}/{conn_id}/kakao/templates/1", json={}, headers=admin).json()["code"] == "template_not_found"
    assert client.get(f"{BASE}/{conn_id}/kakao", headers=admin).status_code == 200
    assert client.get("/api/notify/templates", headers=admin).status_code == 200
    assert hasattr(router_mod, "templates_router")


def test_database_only_routes_are_plain_functions():
    import inspect

    assert inspect.iscoroutinefunction(templates_mod.sync_kakao)
    assert not [name for name in ("get_kakao", "patch_template", "list_templates")
                if inspect.iscoroutinefunction(getattr(templates_mod, name))]


# ── 지금: 목록 읽는 길이 확인되지 않음 ──────────────────────────────


def test_unavailable_mode_answers_available_false_and_501_on_sync(client, admin, monkeypatch):
    mock = KatMock()
    monkeypatch.setattr(provider, "_default_transport", lambda: mock)
    created = client.post(BASE, json=NEW, headers=admin)
    assert created.status_code == 201, created.text
    cid, asked = created.json()["id"], len(mock.requests)

    r = sync(client, admin, cid)

    assert r.status_code == 501
    assert r.json()["code"] == "kakao_listing_unconfirmed"
    assert r.json()["message"] == "채널·문안 목록을 읽는 길을 확인하지 못했습니다."
    assert len(mock.requests) == asked  # 제공사를 부르지 않았다
    assert view(client, admin, cid) == {"available": False, "reason": provider.KAKAO_NOT_CONFIRMED, "channels": [],
                                        "templates": [], "synced_at": None, "ready": False}


def test_client_that_says_not_confirmed_is_also_501(client, admin, conn_id, monkeypatch):
    """길이 확인됐다고 표시돼 있어도 클라이언트가 「확인하지 못함」이면 같은 501(실제 KatClient — 요청 없음)."""
    mock = KatMock()
    monkeypatch.setattr(provider, "KAKAO_LISTING_CONFIRMED", True)
    monkeypatch.setattr(provider, "client_for", lambda row: provider.KatClient(
        provider.ProviderConn(base_url=row.base_url, account_id=row.account_id, key=SENTINEL_KEY), transport=mock))
    r = sync(client, admin, conn_id)
    assert r.status_code == 501 and r.json()["code"] == "kakao_listing_unconfirmed" and mock.requests == []


# ── 확인된 뒤의 꼴(가짜) ────────────────────────────────────────────


def test_sync_reads_channels_and_template_states(client, admin, conn_id, lister):
    r = sync(client, admin, conn_id)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["available"] is True and out["ready"] is False and out["truncated"] is False
    assert out["channels"] == [{"id": "ch-1", "name": "크로노스 현장 1", "status": "connected"}]
    rows = by_template(out)
    assert {k: v["status"] for k, v in rows.items()} == {"tpl-1": "approved", "tpl-2": "reviewing", "tpl-3": "reviewing"}
    first = rows["tpl-1"]
    assert first["variables"] == ["이름", "날짜"] and first["reply_line"] is True and first["channel"] == "ch-1"
    assert first["use"] is None and first["usable"] is False and first["fallback_body"] is None
    assert "070-****-0123" in first["body"] and out["synced_at"] is not None
    assert lister.calls == ["channels", "ch-1"]
    assert view(client, admin, conn_id) | {"truncated": False} == out


def test_sync_with_no_channel_is_empty_not_error(client, admin, conn_id, lister):
    lister.channels, lister.templates = [], {}
    r = sync(client, admin, conn_id)
    assert r.status_code == 200
    assert (r.json()["channels"], r.json()["templates"], r.json()["available"]) == ([], [], True)


def test_sync_keeps_our_use_mapping_and_marks_missing_dormant(client, admin, conn_id, lister, session):
    first = by_template(sync(client, admin, conn_id).json())
    r = patch_template(client, admin, conn_id, first["tpl-1"]["id"], use="체크인 요청",
                       fallback_body="[문자] #{이름}님 #{날짜} 타설 확인 부탁드립니다.")
    assert r.status_code == 200, r.text
    assert r.json()["use"] == "체크인 요청" and r.json()["usable"] is True

    lister.templates = {"ch-1": [tpl(1, body=BODY.replace("타설", "거푸집")), tpl(3, "approved")]}
    again = by_template(sync(client, admin, conn_id).json())

    assert again["tpl-1"]["use"] == "체크인 요청" and again["tpl-1"]["fallback_body"].startswith("[문자]")
    assert "거푸집" in again["tpl-1"]["body"] and again["tpl-1"]["id"] == first["tpl-1"]["id"]
    assert again["tpl-2"]["status"] == "dormant" and again["tpl-3"]["status"] == "approved"
    session.expire_all()
    assert session.query(KakaoTemplate).count() == 3  # 줄을 지우지도 겹쳐 만들지도 않는다


def test_truncated_sync_marks_nothing_dormant(client, admin, conn_id, lister, monkeypatch):
    sync(client, admin, conn_id)
    monkeypatch.setattr(kakao, "MAX_TEMPLATES", 1)
    lister.templates = {"ch-1": [tpl(3, "approved"), tpl(4)]}
    out = sync(client, admin, conn_id).json()
    rows = by_template(out)
    assert out["truncated"] is True and "tpl-4" not in rows
    assert rows["tpl-1"]["status"] == "approved" and rows["tpl-2"]["status"] == "reviewing"  # 다 읽지 못해 그대로


def test_provider_failure_writes_nothing(client, admin, conn_id, lister):
    sync(client, admin, conn_id)
    lister.fail = provider.ProviderFailed("server", "제공사 서버에서 오류가 났습니다.", 500)
    lister.templates = {}
    r = sync(client, admin, conn_id)
    assert r.status_code == 502 and r.json()["code"] == "kakao_sync_failed"
    assert r.json()["detail"] == {"reason": "server"}
    assert len(view(client, admin, conn_id)["templates"]) == 3  # 앞서 맞춘 것 그대로


def test_sync_refuses_while_diagnosis_runs(client, admin, conn_id, lister, monkeypatch):
    monkeypatch.setattr(diagnose, "_RUNNING", {conn_id})
    r = sync(client, admin, conn_id)
    assert r.status_code == 409 and r.json()["code"] == "diagnosis_running" and lister.calls == []


def test_sync_holds_no_write_lock_while_reading(client, admin, conn_id, lister):
    seen: list[str] = []

    def during() -> None:
        with closing(sqlite3.connect(Settings().data_dir / "chronos.db", timeout=0.1)) as other:
            other.execute("BEGIN IMMEDIATE")  # 누가 쓰기를 쥐고 있으면 0.1초 뒤 「database is locked」
            other.rollback()
            seen.append("free")

    lister.during = during
    assert sync(client, admin, conn_id).status_code == 200
    assert seen == ["free", "free"]


def test_missing_connection_is_404(client, admin, lister):
    for method, path in (("POST", f"{BASE}/987/kakao/sync"), ("GET", f"{BASE}/987/kakao"),
                         ("PATCH", f"{BASE}/987/kakao/templates/1")):
        r = client.request(method, path, json={"use": None} if method == "PATCH" else None, headers=admin)
        assert r.status_code == 404 and r.json()["code"] == "connection_not_found", (method, path)


def test_kakao_sync_keeps_no_raw_body(client, admin, conn_id, lister, session, caplog):
    """제공사 글은 지운 뒤에만 저장한다: 키·Account ID·번호(끝 4자리 밖)·보이지 않는 글자가 DB·응답·로그에 없다."""
    raw = f"#{{이름}}님 {SENTINEL_PHONE} 키 {SENTINEL_KEY} 계정 {KAT_ACCOUNT}\u202e 답은 이 번호로 문자 주세요"
    lister.channels = [chan(1, name=f"현장 {SENTINEL_PHONE} {SENTINEL_KEY}")]
    lister.templates = {"ch-1": [tpl(1, body=raw)]}
    assert sync(client, admin, conn_id).status_code == 200
    session.expire_all()
    stored = json.dumps([[t.body, t.variables_json] for t in session.query(KakaoTemplate)], ensure_ascii=False)
    stored += json.dumps(session.get(NotifyConnection, conn_id).kakao_channels_json, ensure_ascii=False)
    digits = "".join(c for c in stored if c.isdigit())
    assert SENTINEL_KEY not in stored and KAT_ACCOUNT not in stored and "\u202e" not in stored
    assert SENTINEL_DIGITS not in digits and "010-****-0199" in stored
    assert_clean(caplog, KAT_ACCOUNT)


# ── 쓰지 않음: 승인된 문안이 있어도 준비되지 않음 ──────────────────


async def test_after_sync_with_approved_templates_kakao_stays_off(client, admin, user, conn_id, lister, session, sid):
    """승인된 문안을 맞추고 쓰는 곳을 이어도 ready 는 거짓이고, 문은 카카오톡 줄을 문자로 보낸다(kakao_not_ready)."""
    tid = by_template(sync(client, admin, conn_id).json())["tpl-1"]["id"]
    assert patch_template(client, admin, conn_id, tid, use="체크인 요청").status_code == 200

    assert view(client, admin, conn_id)["ready"] is False
    assert kakao.ready(session) is False
    assert client.get("/api/notify/status", headers=user).json()["kakao_ready"] is False
    listed = client.get("/api/notify/templates", headers=user).json()
    assert listed["ready"] is False and listed["reason"] == kakao.NOT_READY

    conn = session.get(NotifyConnection, conn_id)
    conn.test_mode = False
    row = message(session, person(session, sid), channel="kakao", body="", template_id=tid,
                  template_vars_json={"이름": "박현장", "날짜": "11월 30일"})
    session.commit()
    fake = FakeChannel()
    with registry.pinned({"sms": fake.lane("sms")}):  # 문자만 — 카카오톡 통로는 등록되지 않은 그대로
        out = await send(row)
    row = reread(session, row)
    assert out.code == "accepted" and [d.channel for d in fake.delivered] == ["sms"] and row.channel == "sms"
    assert trail(session, row)[0] == ("kakao_not_ready", "noted")
    assert events.of(session, Ref("message", row.id))[1]["detail"] == "sms"


# ── 고치기: use·fallback_body 만 ───────────────────────────────────


def test_patch_changes_only_use_and_fallback(client, admin, conn_id, lister, session):
    tid = by_template(sync(client, admin, conn_id).json())["tpl-2"]["id"]
    for bad in ({"status": "approved"}, {"body": "다른 글"}, {"use": 3}, {"fallback_body": ["x"]}):
        r = patch_template(client, admin, conn_id, tid, **bad)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request", bad

    decomposed = unicodedata.normalize("NFD", "가나다")
    r = patch_template(client, admin, conn_id, tid, fallback_body=f"줄\n바꿈\t탭 {decomposed}")
    assert r.status_code == 200 and r.json()["fallback_body"] == "줄\n바꿈\t탭 가나다"
    assert r.json()["status"] == "reviewing" and r.json()["usable"] is False  # 쓰는 곳을 이어도 승인 전이면 쓸 수 없음

    r = patch_template(client, admin, conn_id, tid, use="  ")
    assert r.status_code == 200 and r.json()["use"] is None and r.json()["fallback_body"] == "줄\n바꿈\t탭 가나다"
    assert patch_template(client, admin, conn_id, tid, fallback_body=None).json()["fallback_body"] is None


@pytest.mark.parametrize("field_name,value,code", [
    ("fallback_body", "숨은\x07글자", "invalid_text"), ("fallback_body", "방향\u202e바꿈", "invalid_text"),
    ("fallback_body", "폭없는\u200b빈칸", "invalid_text"), ("use", "줄\n바꿈", "invalid_text"),
    ("fallback_body", "가" * 1001, "too_long"), ("use", "가" * 51, "too_long"),
])
def test_patch_refuses_bad_text_naming_the_field(client, admin, conn_id, lister, field_name, value, code):
    tid = by_template(sync(client, admin, conn_id).json())["tpl-1"]["id"]
    r = patch_template(client, admin, conn_id, tid, **{field_name: value + SENTINEL_PHONE})
    assert r.status_code == 422 and r.json()["code"] == code and r.json()["detail"]["field"] == field_name
    assert value not in r.text and SENTINEL_PHONE not in r.text  # 보낸 값을 되돌려 싣지 않는다


def test_template_of_another_connection_is_the_same_404(client, admin, conn_id, lister, fake_provider):
    tid = by_template(sync(client, admin, conn_id).json())["tpl-1"]["id"]
    other = client.post(BASE, json={**NEW, "name": "둘째"}, headers=admin).json()["id"]
    wrong = patch_template(client, admin, other, tid, use="체크인 요청")
    missing = patch_template(client, admin, conn_id, 98765, use="체크인 요청")
    assert wrong.status_code == missing.status_code == 404
    assert wrong.json() == missing.json() and wrong.json()["code"] == "template_not_found"


# ── 누가 ────────────────────────────────────────────────────────────


def test_templates_admin_only_and_list_for_users(client, admin, user, field, conn_id, lister):
    rows = by_template(sync(client, admin, conn_id).json())
    tid = rows["tpl-1"]["id"]
    patch_template(client, admin, conn_id, tid, use="체크인 요청", fallback_body="[문자] #{이름}님 확인 부탁드립니다.")
    patch_template(client, admin, conn_id, rows["tpl-2"]["id"], use="일정 변경 알림")
    lister.templates = {"ch-1": [tpl(1), tpl(3, "reviewing")]}
    assert by_template(sync(client, admin, conn_id).json())["tpl-2"]["status"] == "dormant"
    for method, path in (("POST", f"{BASE}/{conn_id}/kakao/sync"), ("GET", f"{BASE}/{conn_id}/kakao"),
                         ("PATCH", f"{BASE}/{conn_id}/kakao/templates/{tid}")):
        r = client.request(method, path, json={"use": "x"} if method == "PATCH" else None, headers=user)
        assert r.status_code == 403 and r.json()["code"] == "admin_only", (method, path)
    calls = len(lister.calls)

    r = client.get("/api/notify/templates", headers=user)
    assert r.status_code == 200
    assert_no_secrets(r)
    listed = r.json()
    assert set(listed) == {"ready", "reason", "templates"} and listed["ready"] is False
    assert {t["use"]: set(t) for t in listed["templates"]}["체크인 요청"] == {
        "id", "use", "body", "variables", "fallback_body", "status", "usable"}
    assert "ch-1" not in r.text and "tpl-" not in r.text  # 채널·제공사 문안 id(계정 자료)는 싣지 않는다
    assert [t["use"] for t in listed["templates"]] == ["체크인 요청"]  # 쓰는 곳이 없는 것·없어진(dormant) 것은 빼고
    assert client.get("/api/notify/templates", headers=field).status_code == 403
    assert client.get("/api/notify/templates").status_code == 401
    assert len(lister.calls) == calls  # 읽기는 제공사를 부르지 않는다
