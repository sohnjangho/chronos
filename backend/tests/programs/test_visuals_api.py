"""보고서용 그림 API: POST /api/schedules/{id}/visuals {kind, version?} · GET /api/schedules/{id}/visuals/{vid}."""

from datetime import date

import pytest

from app.agent import context
from app.llm import visualization
from tests.llm_doubles import KEY, add_connection
from tests.visual_doubles import VisualMock, atlas_body, chart_html

GOOD = [["작업 A", "2027-03-01", "2027-03-03"], ["작업 B", "2027-03-04", "2027-03-05"]]


@pytest.fixture(autouse=True)
def setup(monkeypatch, session):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 1))
    monkeypatch.setattr(visualization, "MIN_GAP_S", 0.0)
    add_connection(session)


@pytest.fixture
def liner(monkeypatch):
    def use(*replies):
        t = VisualMock(*replies)
        monkeypatch.setattr(visualization, "TRANSPORT", t)
        return t
    return use


def test_make_and_read(client, user, sid, liner):
    liner(atlas_body(chart_html(GOOD, bounds=None)))
    r = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "summary"}, headers=user)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["kind"], v["version"], v["data_date"], v["verified"], v["passed"], v["total"]) == (
        "summary", 1, "2027-03-01", True, 6, 6)
    assert v["html"].startswith("<!DOCTYPE html>") and v["rows"] == GOOD and v["chart"] == "timeline"
    assert v["external"][-1].endswith("chart.umd.js") and KEY not in r.text
    again = client.get(f"/api/schedules/{sid}/visuals/{v['id']}", headers=user)
    assert again.status_code == 200 and again.json() == v


def test_fallback_has_no_html_but_the_table(client, user, sid, liner):
    liner(500)
    v = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "summary"}, headers=user).json()
    assert (v["html"], v["fallback"], v["note"], v["rows"]) == (None, True, "Liner 그림 실패(server_error) → 기본 그림", GOOD)


def test_errors(client, user, sid, liner):
    liner(atlas_body(chart_html(GOOD, bounds=None)))
    assert client.post("/api/schedules/99/visuals", json={"kind": "summary"}, headers=user).status_code == 404
    r = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "delay_impact"}, headers=user)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "no_data", "기록한 지연이 없습니다.")
    assert client.post(f"/api/schedules/{sid}/visuals", json={"kind": "pie"}, headers=user).status_code == 422
    assert client.get(f"/api/schedules/{sid}/visuals/5", headers=user).status_code == 404
    assert client.post(f"/api/schedules/{sid}/visuals", json={"kind": "summary"}).status_code == 401


def test_a_visual_of_another_schedule_is_not_found(client, user, sid, liner, session):
    from tests.schedules import sample, store

    liner(atlas_body(chart_html(GOOD, bounds=None)))
    v = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "summary"}, headers=user).json()
    other = store(session, sample())
    assert client.get(f"/api/schedules/{other}/visuals/{v['id']}", headers=user).status_code == 404


def test_s_curve_unit_is_passed_through(client, user, sid, liner):
    liner(500)
    week = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "s_curve", "unit": "week"}, headers=user)
    month = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "s_curve", "unit": "month"}, headers=user)
    assert week.status_code == month.status_code == 200
    assert week.json()["id"] != month.json()["id"]
    bad = client.post(f"/api/schedules/{sid}/visuals", json={"kind": "s_curve", "unit": "day"}, headers=user)
    assert bad.status_code == 422
