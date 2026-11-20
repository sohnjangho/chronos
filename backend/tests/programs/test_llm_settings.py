import logging
from functools import partial

import httpx
import pytest
from sqlalchemy import select

from app.llm import connections
from app.security.crypto import decrypt
from app.security.tokens import issue_token
from app.store.tables import LlmAssignment, LlmConnection, User
from tests.helpers import auth

LINER = "https://platform.liner.com/api/v1"
MODELS_BODY = {"data": [{"id": "liner-mark"}, {"id": "liner-claude-router"}]}
_real_probe = connections.probe


def _use_handler(monkeypatch, handler):
    """probe 가 실제 네트워크 대신 handler 를 부르게 한다."""
    monkeypatch.setattr(
        connections, "probe", partial(_real_probe, transport=httpx.MockTransport(handler))
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """가짜를 고르지 않은 시험이 probe 를 부르면 실패시킨다."""
    calls = []

    def refuse(request):
        calls.append(request)
        return httpx.Response(599)

    _use_handler(monkeypatch, refuse)
    yield
    assert not calls, "가짜 probe 없이 연결 시험을 불렀습니다."


@pytest.fixture
def fake_probe_ok(monkeypatch):
    """모델 목록을 돌려주는 가짜 서버. 받은 요청을 모은 목록을 준다."""
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=MODELS_BODY)

    _use_handler(monkeypatch, handler)
    return requests


@pytest.fixture
def fake_probe_status(monkeypatch, status):
    _use_handler(monkeypatch, lambda request: httpx.Response(status))


@pytest.fixture
def conn_id(client, admin, fake_probe_ok):
    r = client.post(
        "/api/llm/connections",
        json={"name": "Liner 기본", "provider": "liner", "base_url": LINER, "secret": "abcd1234efgh5678"},
        headers=admin,
    )
    return r.json()["id"]


def _create(client, admin, name, secret="abcd1234efgh5678"):
    r = client.post(
        "/api/llm/connections",
        json={"name": name, "provider": "liner", "base_url": LINER, "secret": secret},
        headers=admin,
    )
    assert r.status_code == 201
    return r.json()


# 계획서의 시험
def test_secret_is_encrypted_and_masked(client, admin, session, fake_probe_ok):
    r = client.post("/api/llm/connections", json={"name": "Liner 기본", "provider": "liner", "base_url": LINER, "secret": "abcd1234efgh5678"}, headers=admin)
    body = r.json(); assert body["secret_last4"] == "5678" and "secret" not in body and "abcd1234" not in r.text
    row = session.query(LlmConnection).one(); assert "abcd1234" not in row.secret_ciphertext and decrypt(row.secret_ciphertext) == "abcd1234efgh5678"


def test_test_endpoint_returns_models(client, admin, fake_probe_ok):
    r = client.post("/api/llm/connections/test", json={"provider": "liner", "base_url": LINER, "secret": "k"}, headers=admin)
    assert r.json()["ok"] is True and "liner-mark" in r.json()["models"]


@pytest.mark.parametrize("status,code", [(401, "bad_key"), (429, "rate_limited")])
def test_error_is_explained(client, admin, fake_probe_status, status, code):
    assert client.post("/api/llm/connections/test", json={"provider": "liner", "base_url": LINER, "secret": "k"}, headers=admin).json()["error"]["code"] == code


def test_host_change_requires_secret(client, admin, conn_id):
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"base_url": "https://other.example/v1"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "secret_required"
    assert r.json()["message"] == "다른 서버 주소로 바꾸면 API 키를 다시 넣어 주세요."


def test_user_role_forbidden_but_status_allowed(client, user):
    assert client.get("/api/llm/connections", headers=user).status_code == 403
    assert client.get("/api/llm/status", headers=user).json() == {"ready": False, "default_connection": None}


def test_key_never_in_logs(client, admin, caplog, fake_probe_ok):
    client.post("/api/llm/connections", json={"name": "n", "provider": "liner", "base_url": LINER, "secret": "abcd1234efgh5678"}, headers=admin)
    assert "abcd1234efgh5678" not in caplog.text


# 저장·응답
def test_save_probes_and_records_result(client, admin, session, fake_probe_ok):
    body = _create(client, admin, "Liner 기본")
    assert body["status"] == "ok" and body["model_count"] == 2 and body["error"] is None
    assert body["checked_at"] is not None and body["latency_ms"] >= 0
    assert fake_probe_ok[0].url == httpx.URL(f"{LINER}/models")
    assert fake_probe_ok[0].headers["Authorization"] == "Bearer abcd1234efgh5678"


def test_liner_base_url_defaults(client, admin, fake_probe_ok):
    r = client.post(
        "/api/llm/connections",
        json={"name": "기본 주소", "provider": "liner", "secret": "abcd1234efgh5678"},
        headers=admin,
    )
    assert r.status_code == 201 and r.json()["base_url"] == LINER


def test_openai_compatible_needs_base_url(client, admin):
    r = client.post(
        "/api/llm/connections/test",
        json={"provider": "openai_compatible", "secret": "k"},
        headers=admin,
    )
    assert r.status_code == 422 and r.json()["code"] == "base_url_required"


def test_non_http_base_url_rejected(client, admin):
    r = client.post(
        "/api/llm/connections/test",
        json={"provider": "liner", "base_url": "ftp://platform.liner.com", "secret": "abcd1234efgh5678"},
        headers=admin,
    )
    assert r.status_code == 422 and "abcd1234" not in r.text


@pytest.mark.parametrize("status", [401])
def test_failed_probe_still_saves(client, admin, fake_probe_status, status):
    r = client.post(
        "/api/llm/connections",
        json={"name": "틀린 키", "provider": "liner", "base_url": LINER, "secret": "wrongkey12345678"},
        headers=admin,
    )
    body = r.json()
    assert r.status_code == 201 and body["status"] == "failed"
    assert body["error"] == {"code": "bad_key", "message": "API 키가 맞지 않습니다."}
    assert client.get("/api/llm/status", headers=admin).json() == {"ready": False, "default_connection": "틀린 키"}


def test_list_shows_only_last4(client, admin, conn_id):
    r = client.get("/api/llm/connections", headers=admin)
    assert [c["secret_last4"] for c in r.json()] == ["5678"]
    assert "abcd1234" not in r.text and "secret_ciphertext" not in r.text


def test_short_secret_is_not_revealed(client, admin, fake_probe_ok):
    body = _create(client, admin, "짧은 키", secret="abc")
    assert body["secret_last4"] == ""


# 기본 연결 규칙
def test_first_connection_is_default(client, admin, fake_probe_ok):
    first = _create(client, admin, "첫째")
    second = _create(client, admin, "둘째")
    assert first["is_default"] is True and second["is_default"] is False
    assert client.get("/api/llm/status", headers=admin).json() == {"ready": True, "default_connection": "첫째"}


def test_patch_can_move_default(client, admin, fake_probe_ok):
    first = _create(client, admin, "첫째")
    second = _create(client, admin, "둘째")
    r = client.patch(f"/api/llm/connections/{second['id']}", json={"is_default": True}, headers=admin)
    assert r.status_code == 200 and r.json()["is_default"] is True
    flags = {c["id"]: c["is_default"] for c in client.get("/api/llm/connections", headers=admin).json()}
    assert flags == {first["id"]: False, second["id"]: True}


def test_delete_default_promotes_oldest(client, admin, fake_probe_ok):
    first = _create(client, admin, "첫째")
    second = _create(client, admin, "둘째")
    third = _create(client, admin, "셋째")
    assert client.delete(f"/api/llm/connections/{first['id']}", headers=admin).status_code == 204
    flags = {c["id"]: c["is_default"] for c in client.get("/api/llm/connections", headers=admin).json()}
    assert flags == {second["id"]: True, third["id"]: False}


def test_delete_last_connection_leaves_none(client, admin, conn_id):
    assert client.delete(f"/api/llm/connections/{conn_id}", headers=admin).status_code == 204
    assert client.get("/api/llm/connections", headers=admin).json() == []
    assert client.get("/api/llm/status", headers=admin).json() == {"ready": False, "default_connection": None}


def test_unknown_connection_404(client, admin):
    r = client.delete("/api/llm/connections/999", headers=admin)
    assert r.status_code == 404 and r.json()["code"] == "connection_not_found"


# 고치기·다시 시험
def test_patch_name_only_does_not_probe(client, admin, conn_id, fake_probe_ok):
    before = len(fake_probe_ok)
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"name": "새 이름"}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "새 이름" and r.json()["error"] is None
    assert len(fake_probe_ok) == before


def test_host_change_with_secret_reprobes(client, admin, conn_id, fake_probe_ok):
    r = client.patch(
        f"/api/llm/connections/{conn_id}",
        json={"base_url": "https://other.example/v1/", "secret": "zzzz9999yyyy4321"},
        headers=admin,
    )
    body = r.json()
    assert r.status_code == 200 and body["base_url"] == "https://other.example/v1"
    assert body["secret_last4"] == "4321" and "zzzz9999" not in r.text
    assert fake_probe_ok[-1].url == httpx.URL("https://other.example/v1/models")
    assert fake_probe_ok[-1].headers["Authorization"] == "Bearer zzzz9999yyyy4321"


@pytest.mark.parametrize(
    "base_url",
    ["http://platform.liner.com/api/v1", "https://platform.liner.com:8443/api/v1"],
)
def test_origin_change_requires_secret(client, admin, conn_id, base_url):
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"base_url": base_url}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "secret_required"


@pytest.mark.parametrize(
    "base_url",
    ["https://platform.liner.com/api/v2", "https://PLATFORM.liner.com:443/api/v2"],
)
def test_same_origin_change_reuses_stored_secret(client, admin, conn_id, fake_probe_ok, base_url):
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"base_url": base_url}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert fake_probe_ok[-1].headers["Authorization"] == "Bearer abcd1234efgh5678"


def test_same_origin_change_with_unreadable_key_is_409(client, session, conn_id, monkeypatch):
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    admin_id = session.scalars(select(User.id).where(User.login_id == "admin")).one()
    r = client.patch(
        f"/api/llm/connections/{conn_id}",
        json={"base_url": "https://platform.liner.com/api/v2"},
        headers=auth(issue_token(admin_id)),
    )
    assert r.status_code == 409 and r.json()["code"] == "secret_unreadable"


def test_patch_is_default_false_rejected(client, admin, conn_id):
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"is_default": False}, headers=admin)
    assert r.status_code == 422


def test_failed_retest_keeps_model_list(client, admin, conn_id, monkeypatch):
    _use_handler(monkeypatch, lambda request: httpx.Response(401))
    r = client.post(f"/api/llm/connections/{conn_id}/test", headers=admin)
    assert r.json()["error"]["code"] == "bad_key"
    models = client.get(f"/api/llm/connections/{conn_id}/models", headers=admin).json()
    assert models == {"models": ["liner-mark", "liner-claude-router"]}
    [conn] = client.get("/api/llm/connections", headers=admin).json()
    assert conn["status"] == "failed" and conn["model_count"] == 2


def test_retest_uses_stored_secret(client, admin, conn_id, fake_probe_ok):
    r = client.post(f"/api/llm/connections/{conn_id}/test", headers=admin)
    assert r.status_code == 200 and r.json()["ok"] is True and "abcd1234" not in r.text
    assert fake_probe_ok[-1].headers["Authorization"] == "Bearer abcd1234efgh5678"


def test_retest_after_secret_key_change_is_409(client, session, conn_id, monkeypatch):
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    admin_id = session.scalars(select(User.id).where(User.login_id == "admin")).one()
    r = client.post(f"/api/llm/connections/{conn_id}/test", headers=auth(issue_token(admin_id)))
    assert r.status_code == 409
    assert r.json()["code"] == "secret_unreadable"
    assert r.json()["message"] == "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요."


def test_models_endpoint_returns_last_list(client, admin, user, conn_id):
    r = client.get(f"/api/llm/connections/{conn_id}/models", headers=admin)
    assert r.json() == {"models": ["liner-mark", "liner-claude-router"]}
    assert client.get(f"/api/llm/connections/{conn_id}/models", headers=user).status_code == 403


# 쓰임새별 배정
def test_assignments_default_without_connection(client, admin):
    items = client.get("/api/llm/assignments", headers=admin).json()["items"]
    assert items == [
        {"purpose": "light", "connection_id": None, "model": "liner-claude-router", "routing_strategy": "cost"},
        {"purpose": "normal", "connection_id": None, "model": "liner-claude-router", "routing_strategy": "balanced"},
        {"purpose": "hard", "connection_id": None, "model": "liner-claude-router", "routing_strategy": "quality"},
        {"purpose": "longdoc", "connection_id": None, "model": "liner-mark", "routing_strategy": None},
    ]


def test_assignments_default_point_at_default_connection(client, admin, conn_id):
    items = client.get("/api/llm/assignments", headers=admin).json()["items"]
    assert {i["connection_id"] for i in items} == {conn_id}


def test_put_assignments_stores(client, admin, conn_id):
    item = {"purpose": "hard", "connection_id": conn_id, "model": "liner-mark", "routing_strategy": None}
    r = client.put("/api/llm/assignments", json={"items": [item]}, headers=admin)
    assert r.status_code == 200
    items = {i["purpose"]: i for i in client.get("/api/llm/assignments", headers=admin).json()["items"]}
    assert items["hard"] == item and items["light"]["model"] == "liner-claude-router"


def test_put_assignments_unknown_purpose(client, admin, conn_id):
    item = {"purpose": "huge", "connection_id": conn_id, "model": "m", "routing_strategy": None}
    r = client.put("/api/llm/assignments", json={"items": [item]}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_put_assignments_unknown_connection(client, admin, conn_id):
    item = {"purpose": "hard", "connection_id": 999, "model": "m", "routing_strategy": None}
    r = client.put("/api/llm/assignments", json={"items": [item]}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert r.json()["message"] == "없는 연결을 골랐습니다."


def test_assignments_admin_only(client, user):
    assert client.get("/api/llm/assignments", headers=user).status_code == 403
    assert client.put("/api/llm/assignments", json={"items": []}, headers=user).status_code == 403


def test_delete_connection_drops_its_assignments(client, admin, session, fake_probe_ok):
    first = _create(client, admin, "첫째")
    second = _create(client, admin, "둘째")
    item = {"purpose": "hard", "connection_id": second["id"], "model": "x", "routing_strategy": None}
    client.put("/api/llm/assignments", json={"items": [item]}, headers=admin)
    client.delete(f"/api/llm/connections/{second['id']}", headers=admin)
    session.expire_all()
    assert session.query(LlmAssignment).count() == 0
    items = {i["purpose"]: i for i in client.get("/api/llm/assignments", headers=admin).json()["items"]}
    assert items["hard"]["connection_id"] == first["id"]


# 키 문자 검증
BAD_SECRET_MESSAGE = "API 키에 쓸 수 없는 문자가 있습니다. 공백이나 줄바꿈이 섞이지 않았는지 확인해 주세요."


def _secret_requests(conn_id, secret):
    return [
        ("post", "/api/llm/connections/test", {"provider": "liner", "secret": secret}),
        ("post", "/api/llm/connections", {"name": "n", "provider": "liner", "secret": secret}),
        ("patch", f"/api/llm/connections/{conn_id}", {"secret": secret}),
    ]


@pytest.mark.parametrize(
    "secret", ["abcd1234\nefgh5678", "abcd1234 efgh5678", "키abcd1234efgh5678", "   ", "a" * 513]
)
def test_bad_secret_rejected_everywhere(client, admin, conn_id, secret):
    for method, url, body in _secret_requests(conn_id, secret):
        r = getattr(client, method)(url, json=body, headers=admin)
        assert r.status_code == 422, url
        assert r.json()["code"] == "invalid_secret" and r.json()["message"] == BAD_SECRET_MESSAGE
        assert "abcd1234" not in r.text and "efgh5678" not in r.text


def test_secret_whitespace_is_stripped(client, admin, fake_probe_ok):
    r = client.post(
        "/api/llm/connections",
        json={"name": "n", "provider": "liner", "secret": "  abcd1234efgh5678\n"},
        headers=admin,
    )
    assert r.status_code == 201 and r.json()["secret_last4"] == "5678"
    assert fake_probe_ok[-1].headers["Authorization"] == "Bearer abcd1234efgh5678"


def test_user_cannot_test_or_create(client, user):
    body = {"name": "n", "provider": "liner", "secret": "abcd1234efgh5678"}
    assert client.post("/api/llm/connections/test", json=body, headers=user).status_code == 403
    assert client.post("/api/llm/connections", json=body, headers=user).status_code == 403


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:pw@platform.liner.com/api/v1",
        "https://platform.liner.com/api/v1?key=x",
        "https://platform.liner.com/api/v1#frag",
    ],
)
def test_userinfo_query_fragment_url_rejected(client, admin, base_url):
    r = client.post(
        "/api/llm/connections/test",
        json={"provider": "liner", "base_url": base_url, "secret": "abcd1234efgh5678"},
        headers=admin,
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert "사용자 정보나 물음표(?)" in r.text and "pw@" not in r.text


# 키가 기록에 남지 않는다
def test_key_never_in_debug_logs(client, admin, caplog, fake_probe_ok):
    caplog.set_level(logging.DEBUG)
    conn = _create(client, admin, "n")
    client.post(f"/api/llm/connections/{conn['id']}/test", headers=admin)
    client.post("/api/llm/connections", json={"provider": "liner", "secret": "abcd1234efgh5678"}, headers=admin)
    assert "abcd1234efgh5678" not in caplog.text
