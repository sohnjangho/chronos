"""정보 API 연결(관리자): 저장·고침·지움·연결 시험. 키는 끝 4자리만 보이고, 시험은 두 서비스를 따로 알린다.

기상청은 부르지 않는다(app.info.kma.TRANSPORT 를 가짜로). 값은 모두 가상이다.
"""

import logging

import pytest

from app.info import generic, kma, templates
from app.security.crypto import decrypt
from app.store.tables import InfoConnection
from tests import info_doubles
from tests.kma_doubles import (
    KEY,
    KEY_ENCODED,
    KmaMock,
    asos_day,
    fcst,
    gateway_body,
    gateway_xml,
    ok_body,
)

URL = "/api/info/connections"
NOT_REGISTERED = "이 서비스키는 해당 기상청 서비스에 등록되지 않았습니다(공공데이터포털에서 활용신청을 확인해 주세요)."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """가짜를 고르지 않은 시험이 기상청을 부르면 599 로 실패한다."""
    monkeypatch.setattr(kma, "TRANSPORT", KmaMock())


def _create(client, admin, **over) -> dict:
    r = client.post(URL, json={"name": "기상청", "preset": "kma", "secret": KEY, **over}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_info_connection_crud_shows_last4_only(client, admin, session):
    made = _create(client, admin)
    assert made == {"id": made["id"], "name": "기상청", "preset": "kma", "base_url": kma.DEFAULT_BASE_URL,
                    "secret_last4": KEY[-4:], "status": "unknown", "checked_at": None,
                    "description": "", "usage": "", "key_in": "query", "key_name": "serviceKey", "test_path": ""}
    listed = client.get(URL, headers=admin)
    assert listed.json() == [made] and KEY not in listed.text and KEY_ENCODED not in listed.text
    assert decrypt(session.get(InfoConnection, made["id"]).secret_ciphertext) == KEY

    r = client.patch(f"{URL}/{made['id']}", json={"name": "기상청 새 키", "secret": KEY_ENCODED}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "기상청 새 키"
    assert r.json()["secret_last4"] == KEY_ENCODED[-4:] and KEY_ENCODED not in r.text

    assert client.delete(f"{URL}/{made['id']}", headers=admin).status_code == 204
    assert client.get(URL, headers=admin).json() == []
    assert client.delete(f"{URL}/{made['id']}", headers=admin).json()["code"] == "connection_not_found"


def test_only_admin(client, user):
    assert client.get(URL, headers=user).status_code == 403
    assert client.post(URL, json={"name": "x", "preset": "kma", "secret": KEY}, headers=user).status_code == 403


def test_secret_with_spaces_is_refused(client, admin):
    r = client.post(URL, json={"name": "기상청", "preset": "kma", "secret": "ab cd efgh 1234"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_secret" and "ab cd" not in r.text


def test_changing_the_key_resets_status(client, admin, monkeypatch):
    made = _create(client, admin)
    monkeypatch.setattr(kma, "TRANSPORT", KmaMock(asos=(200, ok_body([asos_day("2026-11-17", "5.0", "1.0")])),
                                                  fcst=(200, ok_body([fcst("20261121", "0600", "TMN", "-5.0")]))))
    body = client.post(f"{URL}/{made['id']}/test", headers=admin).json()
    assert body["ok"] is True and body["summary"] == "단기예보 OK · ASOS 일자료 OK"
    assert [(s["service"], s["ok"], s["error"]) for s in body["services"]] == [
        ("short_forecast", True, None), ("asos", True, None)]
    assert client.get(URL, headers=admin).json()[0]["status"] == "ok"
    r = client.patch(f"{URL}/{made['id']}", json={"secret": KEY_ENCODED}, headers=admin)
    assert (r.json()["status"], r.json()["checked_at"]) == ("unknown", None)


def test_connection_test_reports_each_service(client, admin, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    made = _create(client, admin)
    mock = KmaMock(asos=(403, gateway_body("30")), fcst=(200, ok_body([fcst("20261121", "0600", "TMN", "-5.0")])))
    monkeypatch.setattr(kma, "TRANSPORT", mock)
    r = client.post(f"{URL}/{made['id']}/test", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["summary"] == "단기예보 OK · ASOS 일자료 등록 안 됨"
    services = [(s["service"], s["label"], s["ok"], s["error"]) for s in body["services"]]
    assert services == [("short_forecast", "단기예보", True, None),
                        ("asos", "ASOS 일자료", False, {"code": "not_registered", "message": NOT_REGISTERED})]
    assert all(isinstance(s["latency_ms"], int) for s in body["services"])
    assert len(mock.of("AsosDalyInfoService")) == 1 and len(mock.of("VilageFcstInfoService")) == 1
    row = client.get(URL, headers=admin).json()[0]
    assert row["status"] == "failed" and row["checked_at"] is not None
    for secret in (KEY, KEY_ENCODED):
        assert secret not in r.text and secret not in caplog.text


def test_connection_test_unknown_id(client, admin):
    r = client.post(f"{URL}/999/test", headers=admin)
    assert r.status_code == 404 and r.json()["code"] == "connection_not_found"


# ── 범용 연결(preset generic) ───────────────────────────────────────

GEN = {"name": "공휴일", "preset": "generic", "base_url": info_doubles.BASE, "secret": info_doubles.KEY,
       "description": "공휴일·대체공휴일(연·월별)", "usage": "/getRestDeInfo?solYear=2026&_type=json",
       "key_name": "ServiceKey", "test_path": "/getRestDeInfo?solYear=2026&solMonth=12&_type=json"}


@pytest.fixture
def api(monkeypatch):
    """범용 연결의 가짜 서버(기본 정상 응답)와 늘 공인 IP 로 푸는 이름 풀이."""
    mock = info_doubles.ApiMock()
    monkeypatch.setattr(generic, "TRANSPORT", mock)
    monkeypatch.setattr(generic, "RESOLVE", info_doubles.public)
    return mock


def _gen(client, admin, **over) -> dict:
    r = client.post(URL, json={**GEN, **over}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_generic_connection_is_saved_with_its_notes(client, admin, session):
    made = _gen(client, admin, key_in="query")
    assert made == {"id": made["id"], "name": "공휴일", "preset": "generic", "base_url": info_doubles.BASE,
                    "secret_last4": info_doubles.KEY[-4:], "status": "unknown", "checked_at": None,
                    "description": GEN["description"], "usage": GEN["usage"], "key_in": "query",
                    "key_name": "ServiceKey", "test_path": GEN["test_path"]}
    listed = client.get(URL, headers=admin)
    assert listed.json() == [made] and info_doubles.KEY not in listed.text
    assert decrypt(session.get(InfoConnection, made["id"]).secret_ciphertext) == info_doubles.KEY


@pytest.mark.parametrize("missing", ["base_url", "description"])
def test_generic_needs_base_url_and_description(client, admin, missing):
    r = client.post(URL, json={**GEN, missing: "" if missing == "description" else None}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == f"{missing}_required"
    assert client.get(URL, headers=admin).json() == []


@pytest.mark.parametrize("url", ["http://localhost:8210", "http://127.0.0.1", "http://192.168.0.7/api",
                                 "http://169.254.169.254/latest", "http://[::1]/x", "http://2130706433"])
def test_internal_base_url_is_refused_at_save(client, admin, url):
    r = client.post(URL, json={**GEN, "base_url": url}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "base_url_not_allowed" and "내부망" in r.json()["message"]


@pytest.mark.parametrize(("field", "value"), [
    ("key_name", "Service Key"), ("key_name", "a" * 61), ("key_in", "body"), ("description", "가" * 501),
    ("usage", "가" * 3001), ("test_path", "가" * 501),
])
def test_field_shapes(client, admin, field, value):
    assert client.post(URL, json={**GEN, field: value}, headers=admin).status_code == 422


@pytest.mark.parametrize("path", ["getRestDeInfo", "//evil.example/x", "/a/../b", "/x?ServiceKey=abc"])
def test_bad_test_path_is_refused_at_save(client, admin, path):
    r = client.post(URL, json={**GEN, "test_path": path}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_test_path"


def test_generic_patch(client, admin, api):
    made = _gen(client, admin)
    client.post(f"{URL}/{made['id']}/test", headers=admin)
    r = client.patch(f"{URL}/{made['id']}", json={"description": "새 설명", "usage": "새 메모",
                                                  "test_path": "/getHoliDeInfo?solYear=2026"}, headers=admin)
    assert r.status_code == 200, r.text
    assert (r.json()["description"], r.json()["usage"], r.json()["test_path"]) == ("새 설명", "새 메모",
                                                                                 "/getHoliDeInfo?solYear=2026")
    assert r.json()["status"] == "ok"  # 설명만 고치면 시험 결과는 그대로
    r = client.patch(f"{URL}/{made['id']}", json={"key_in": "header", "key_name": "Authorization"}, headers=admin)
    assert (r.json()["key_in"], r.json()["key_name"], r.json()["status"]) == ("header", "Authorization", "unknown")
    assert client.patch(f"{URL}/{made['id']}", json={"description": " "}, headers=admin).json()["code"] == (
        "description_required")
    r = client.patch(f"{URL}/{made['id']}", json={"base_url": "https://apis.data.go.kr/other"}, headers=admin)
    assert r.json()["code"] == "secret_required"
    r = client.patch(f"{URL}/{made['id']}", json={"base_url": "http://10.0.0.2", "secret": "NEWkey123456"},
                     headers=admin)
    assert r.json()["code"] == "base_url_not_allowed"
    r = client.patch(f"{URL}/{made['id']}", json={"test_path": "/x?AUTHORIZATION=1"}, headers=admin)  # 지금 키 이름(대소문자 무시)
    assert r.json()["code"] == "invalid_test_path"


def test_generic_test_needs_a_test_path(client, admin, api):
    made = _gen(client, admin, test_path="")
    r = client.post(f"{URL}/{made['id']}/test", headers=admin)
    assert r.status_code == 422 and r.json() == {"code": "test_path_required", "message": "시험 경로를 넣어 주세요.",
                                                 "detail": None}
    assert api.requests == []


def test_generic_test_calls_the_test_path_once(client, admin, api, caplog):
    caplog.set_level(logging.DEBUG)
    api.answer = (200, {"echo": info_doubles.KEY, "items": ["가" * 400]})
    made = _gen(client, admin)
    r = client.post(f"{URL}/{made['id']}/test", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["http_status"] == 200 and body["summary"] == "공휴일 OK"
    assert [(s["service"], s["label"], s["ok"], s["error"]) for s in body["services"]] == [
        ("generic", "공휴일", True, None)]
    assert isinstance(body["services"][0]["latency_ms"], int)
    assert 0 < len(body["sample"]) <= 300 and '"items"' in body["sample"]
    [sent] = api.requests
    assert sent.method == "GET" and sent.url.path.endswith("/getRestDeInfo")
    assert f"ServiceKey={info_doubles.KEY_ENCODED}" in sent.url.query.decode()
    row = client.get(URL, headers=admin).json()[0]
    assert row["status"] == "ok" and row["checked_at"] is not None
    for secret in (info_doubles.KEY, info_doubles.KEY_ENCODED):
        assert secret not in r.text and secret not in caplog.text


def test_generic_test_explains_a_portal_envelope(client, admin, api):
    api.answer = (200, gateway_xml("30"))
    made = _gen(client, admin)
    body = client.post(f"{URL}/{made['id']}/test", headers=admin).json()
    assert body["ok"] is False and body["http_status"] == 200 and "returnReasonCode" in body["sample"]
    assert body["services"][0]["error"] == {"code": "not_registered",
                                            "message": kma.FAILED_MESSAGES["not_registered"].replace("기상청", "공휴일")}
    assert body["summary"] == "공휴일 등록 안 됨"
    assert client.get(URL, headers=admin).json()[0]["status"] == "failed"


def test_generic_test_on_a_host_resolving_inside_is_not_sent(client, admin, api, monkeypatch):
    monkeypatch.setattr(generic, "RESOLVE", lambda host, port: ["10.0.0.9"])
    made = _gen(client, admin)
    body = client.post(f"{URL}/{made['id']}/test", headers=admin).json()
    assert body["ok"] is False and body["services"][0]["error"]["code"] == "blocked_host"
    assert body["http_status"] is None and body["sample"] is None and api.requests == []


def test_kma_test_has_no_http_status_or_sample(client, admin, monkeypatch):
    made = _create(client, admin)
    monkeypatch.setattr(kma, "TRANSPORT", KmaMock(asos=(200, ok_body([])), fcst=(200, ok_body([]))))
    body = client.post(f"{URL}/{made['id']}/test", headers=admin).json()
    assert (body["http_status"], body["sample"]) == (None, None)


def test_templates_are_listed_for_admins_only(client, admin, user):
    assert client.get("/api/info/templates", headers=user).status_code == 403
    r = client.get("/api/info/templates", headers=admin)
    assert r.status_code == 200
    assert r.json() == [t.model_dump() for t in templates.load_templates()]
    assert all(set(t) == {"id", "label", "base_url", "key_in", "key_name", "description", "usage", "test_path",
                          "docs_url"} for t in r.json())


# ── 보안 검토 반영(1차) ─────────────────────────────────────────────

PASTED = {"raw": info_doubles.KEY, "encoded": info_doubles.KEY_ENCODED,
          "plus encoded": info_doubles.KEY.replace("+", "%2B")}


@pytest.mark.parametrize("field", ["usage", "description", "name", "test_path"])
@pytest.mark.parametrize("form", PASTED.values(), ids=PASTED.keys())
def test_a_key_pasted_into_the_notes_is_refused(client, admin, field, form):
    value = {"usage": f"예: {info_doubles.BASE}/getRestDeInfo?ServiceKey={form}&solYear=2026",
             "description": f"공휴일 {form}", "name": f"공휴일 {form}"[:100],
             "test_path": f"/getRestDeInfo?q={form}"}[field]
    r = client.post(URL, json={**GEN, field: value}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "key_in_text" and "키" in r.json()["message"]
    assert info_doubles.KEY not in r.text and info_doubles.KEY_ENCODED not in r.text


def test_patch_checks_the_notes_against_the_stored_and_the_new_key(client, admin):
    made = _gen(client, admin)
    r = client.patch(f"{URL}/{made['id']}", json={"usage": f"키 {info_doubles.KEY_ENCODED}"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "key_in_text"
    new_key = "NEWkeyABCDEF123456"
    client.patch(f"{URL}/{made['id']}", json={"usage": f"메모 {new_key}"}, headers=admin)
    r = client.patch(f"{URL}/{made['id']}", json={"secret": new_key}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "key_in_text"


@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Connection", "TE", "Upgrade",
                                  "Expect", "accept-encoding", "Cookie"])
def test_header_mode_refuses_hop_and_framing_header_names(client, admin, name):
    r = client.post(URL, json={**GEN, "key_in": "header", "key_name": name}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "key_name_not_allowed"
    made = _gen(client, admin, name=f"x{name}")
    r = client.patch(f"{URL}/{made['id']}", json={"key_in": "header", "key_name": name}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "key_name_not_allowed"


def test_header_names_are_fine_in_query_mode(client, admin):
    assert client.post(URL, json={**GEN, "key_in": "query", "key_name": "Host"}, headers=admin).status_code == 201


def test_generic_key_must_be_at_least_8_characters(client, admin):
    r = client.post(URL, json={**GEN, "secret": "abc1234"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "secret_too_short" and "abc1234" not in r.text
    made = _gen(client, admin)
    r = client.patch(f"{URL}/{made['id']}", json={"secret": "short"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "secret_too_short"


@pytest.mark.parametrize(("code", "expected"), [("30", "not_registered"), ("22", "rate_limited"),
                                                ("31", "key_expired"), ("00", None), ("03", None)])
def test_connection_test_reads_account_errors_in_the_result_code(client, admin, api, code, expected):
    api.answer = (200, {"response": {"header": {"resultCode": code, "resultMsg": "x"}}})
    made = _gen(client, admin)
    body = client.post(f"{URL}/{made['id']}/test", headers=admin).json()
    error = body["services"][0]["error"]
    assert body["ok"] is (expected is None) and body["http_status"] == 200 and body["sample"]
    assert (error or {}).get("code") == expected
    if expected:
        assert error["message"] == kma.FAILED_MESSAGES[expected].replace("기상청", "공휴일")
