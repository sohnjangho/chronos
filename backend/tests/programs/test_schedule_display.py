"""일정 보기의 분야 표시 설정(Task 40): 그 일정 분야 묶음의 display, 모르는 분야면 기본값."""

import pytest

from app.store.schedules import create_schedule
from tests.schedules import sample


def _store(session, domain: str) -> int:
    return create_schedule(session, name=f"{domain} 시험 일정", domain=domain, level="L3", schedule=sample(),
                           conditions=[], by_kind="agent", by_name="에이전트", note="처음 만듦")


@pytest.fixture
def sid_manufacturing(session) -> int:
    return _store(session, "manufacturing")


def test_view_carries_domain_display(client, admin, sid_manufacturing):
    assert client.get(f"/api/schedules/{sid_manufacturing}", headers=admin).json()["display"] == {
        "gantt_group_by": "resource", "deadline_label": "납기", "extra_columns": ["resources"]}


def test_construction_display_comes_from_its_pack(client, admin, sid):
    """기한 세로선 이름은 「준공 기한」(계산한 준공일로 읽히지 않게)."""
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["display"] == {
        "gantt_group_by": "wbs", "deadline_label": "준공 기한", "extra_columns": []}


def test_unknown_domain_gets_the_default_display(client, admin, session):
    sid = _store(session, "shipbuilding")
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["display"] == {
        "gantt_group_by": "wbs", "deadline_label": "완료 기한", "extra_columns": []}


def test_write_answers_carry_display_too(client, admin, sid_manufacturing):
    r = client.patch(f"/api/schedules/{sid_manufacturing}/activities/A", json={"od": 4, "base_version": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["display"]["gantt_group_by"] == "resource"
