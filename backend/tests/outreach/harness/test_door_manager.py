"""관리자 등급 연락처(11-24 PM): 원청 현장소장·감리처럼 access_level 이 manager 인 연락처는 **등록된 프로젝트의** 모든 협력사·
공종 일정을 듣는다(사실 수준 all). 다른 프로젝트는 여전히 보이지 않고, 여러 프로젝트에 등록된 사람은 현장을 먼저 골라야 한다.
trade(기본) 연락처는 그대로다. 받는 쪽(scope_of)과 거는 쪽(outbound_scope), 문자와 통화 모두. 번호·이름은 모두 가상이다."""

import json

import pytest

from app.outreach.harness import door
from tests.outreach.harness.test_tools import (
    ASK,
    MARK_A,
    MARK_B,
    PHONE,
    SITE_A,
    SITE_B,
    WORK,
    connect,
    inbound,
    outbound,
    who,
    world,
)

MEDIA = ["sms", "call"]


def _text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("medium", MEDIA)
async def test_manager_inbound_hears_other_companies_in_their_project(session, medium):
    w = world(session)
    connect(session)
    w.park.access_level = "manager"  # 가람철근 박현장 — 마감 작업(설비)은 자기 공종이 아니다
    box, _ = inbound(session, medium, PHONE)

    assert (box.scope.caller_class, box.scope.facts, box.scope.personal) == ("contact", "all", True)
    other = await box.call("schedule_fact", {"activity": f"{MARK_A} 마감 작업"})
    own = await box.call("schedule_fact", {"activity": f"{MARK_A} 철근 배근"})
    elsewhere = await box.call("schedule_fact", {"activity": f"{MARK_B} 마감 작업", "site": SITE_B})

    assert [item["name"] for item in other["items"]] == [f"{MARK_A} 마감 작업"]
    assert [item["name"] for item in own["items"]] == [f"{MARK_A} 철근 배근"]
    assert MARK_B not in _text(elsewhere) and "2028" not in _text(elsewhere)  # 등록되지 않은 프로젝트는 그대로 닫힘


@pytest.mark.parametrize("medium", MEDIA)
async def test_trade_contact_is_unchanged(session, medium):
    world(session)
    connect(session)
    box, _ = inbound(session, medium, PHONE)

    assert (box.scope.caller_class, box.scope.facts) == ("contact", "trade")
    other = await box.call("schedule_fact", {"activity": f"{MARK_A} 마감 작업"})

    assert "items" not in other and MARK_A not in _text(other)


async def test_manager_outbound_hears_other_companies_but_not_other_projects(session):
    w = world(session)
    connect(session)
    w.park.access_level = "manager"
    box, _ = outbound(session, w.park)

    assert (box.scope.caller_class, box.scope.schedule_ids, box.scope.facts) == ("outbound", (w.a,), "all")
    await box.call("confirm_person", {"is_person": True})  # 신원 확인 전에는 아무 사실도 가지 않는다(H1)
    other = await box.call("schedule_fact", {"activity": f"{MARK_A} 마감 작업"})
    elsewhere = await box.call("schedule_fact", {"activity": f"{MARK_B} 마감 작업", "site": SITE_B})

    assert [item["name"] for item in other["items"]] == [f"{MARK_A} 마감 작업"]
    assert MARK_B not in _text(elsewhere)


def test_trade_outbound_is_unchanged(session):
    w = world(session)
    assert door.outbound_scope(session, w.a, w.park.id).facts == "trade"


@pytest.mark.parametrize("medium", MEDIA)
async def test_manager_in_two_projects_must_name_the_site_then_hears_all_of_that_one(session, medium):
    """같은 사람(같은 번호)이 두 프로젝트에 등록 → contact_multi. 현장을 고르기 전에는 아무것도, 고른 뒤에는 그 프로젝트만 all."""
    w = world(session)
    connect(session)
    park_b = who(session, w.rebar_b, "박현장", PHONE, access_level="manager", person_key="park")
    w.park.access_level, w.park.person_key = "manager", "park"
    box, _ = inbound(session, medium, PHONE)
    assert (box.scope.caller_class, box.scope.site_required, box.scope.facts) == ("contact_multi", True, "none")

    before = await box.call("schedule_fact", {"activity": f"{MARK_B} 마감 작업"})
    pinned = await box.call("schedule_fact", {"activity": f"{MARK_B} 마감 작업", "site": SITE_B})
    other_site = await box.call("schedule_fact", {"activity": f"{MARK_A} 마감 작업", "site": SITE_A})

    assert before == {"ask": ASK, "sites": [SITE_A, SITE_B]}
    assert [item["name"] for item in pinned["items"]] == [f"{MARK_B} 마감 작업"]  # 나래 현장의 전기 공종 — 다른 협력사
    assert box.scope.schedule_ids == (w.b,) and box.scope.contact_ids == (park_b.id,) and box.scope.facts == "all"
    assert MARK_A not in _text(other_site)


def test_manager_in_one_project_only_is_trade_when_the_number_is_also_a_trade_contact_elsewhere(session):
    """Scope 는 일정마다 다른 수준을 담지 못한다 — 같은 번호가 한 곳에서만 관리자면 좁은 쪽(trade)."""
    w = world(session)
    connect(session)
    who(session, w.rebar_b, "박현장", PHONE)  # 나래 현장에서는 trade
    w.park.access_level = "manager"
    scope = door.scope_of(session, door.resolve(session, PHONE, now=WORK))

    assert scope.caller_class == "contact_multi" and scope.grant_facts == "trade"
    assert scope.pinned(w.a).facts == "trade"


def test_shared_number_is_not_widened_by_a_manager(session):
    w = world(session)
    connect(session)
    who(session, w.rebar_a, "김철근", PHONE, access_level="manager")  # 같은 번호를 같은 협력사 두 사람이 씀
    w.park.access_level = "manager"
    scope = door.scope_of(session, door.resolve(session, PHONE, now=WORK))

    assert scope.caller_class == "shared" and scope.facts == "trade"


def test_hidden_manager_row_does_not_widen(session):
    w = world(session)
    connect(session)
    w.park.access_level, w.park.hidden = "manager", True
    caller = door.resolve(session, PHONE, now=WORK)

    assert door.scope_of(session, caller).facts == "none"
