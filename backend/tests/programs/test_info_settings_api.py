"""정보 API 연결(관리자): 저장·고침·지움·연결 시험. 키는 끝 4자리만 보이고, 시험은 두 서비스를 따로 알린다.

기상청은 부르지 않는다(app.info.kma.TRANSPORT 를 가짜로). 값은 모두 가상이다.
"""

import logging

import pytest

from app.info import kma
from app.security.crypto import decrypt
from app.store.tables import InfoConnection
from tests.kma_doubles import (
    KEY,
    KEY_ENCODED,
    KmaMock,
    asos_day,
    fcst,
    gateway_body,
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
                    "secret_last4": KEY[-4:], "status": "unknown", "checked_at": None}
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
