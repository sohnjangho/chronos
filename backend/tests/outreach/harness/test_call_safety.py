"""통화 안전(H1) — 하네스 쪽 두 겹과 수신 거부 말 규칙.

- 한 현장으로 정해진 통화에서 상대가 다른 현장 이름을 대면 도구는 그 현장 것을 조용히 주지 않고 고정 안내 하나만 준다(S-17).
- 우리가 건 통화는 confirm_person(is_person=True) 전에는 그 사람의 요청·일정을 주지 않는다(S-18).
- 수신 거부 말 규칙은 들어오는 문자와 통화가 같이 쓴다(door.is_stop) — 통화는 「그만」 같은 한 낱말 규칙을 쓰지 않는다(S-04).

번호·이름·회사는 모두 가상이다(test_tools 의 도우미).
"""

import pytest
from sqlalchemy import select

from app.outreach.harness import door, tools
from app.store.tables_outreach import ContactReport
from tests.outreach.harness.test_tools import (
    MARK_A,
    PHONE,
    SITE_A,
    SITE_B,
    WORK,
    connect,
    inbound,
    log,
    message,
    outbound,
    trail,
    world,
)

OTHER = "이 통화는 가람 현장 건입니다"
FIRST = "먼저 통화하시는 분이 맞는지 확인해 주세요"


# ── 수신 거부 말(문자·통화 같은 규칙) ─────────────────────────────────────


@pytest.mark.parametrize("text", ["수신거부", "수신 거부할게요.", "수신거부 해 주세요", "수신 거부 부탁드립니다!", "수신거부요"])
def test_opt_out_word_counts_for_text_and_speech(text):
    assert door.is_stop(text) and door.is_stop(text, single_words=False)


@pytest.mark.parametrize("text", ["그만", "STOP", "stop"])
def test_single_words_count_only_for_text(text):
    assert door.is_stop(text) and not door.is_stop(text, single_words=False)


@pytest.mark.parametrize("text", ["그만 말씀하세요", "수신거부 아닙니다", "수신거부는 어떻게 하나요", "", None])
def test_not_opt_out(text):
    assert not door.is_stop(text) and not door.is_stop(text, single_words=False)


def test_text_door_still_uses_the_same_rule(session):
    """들어오는 문의 문자 판정은 그대로(stop) — 그 규칙을 이제 공개 함수 하나가 정한다."""
    world(session)
    connect(session)
    assert door.admit(session, "sms", PHONE, now=WORK, body="수신거부").verdict == "stop"
    assert door.admit(session, "sms", PHONE, now=WORK, body="그만").verdict == "stop"
    assert door.admit(session, "sms", PHONE, now=WORK, body="그만 말씀하세요").verdict != "stop"


# ── 한 현장 통화에서 다른 현장 이름 ───────────────────────────────────────


async def _confirmed(session):
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park)
    assert await box.call("confirm_person", {"is_person": True}) == {"ok": True}
    return w, box, row


@pytest.mark.parametrize(("name", "args"), [
    ("schedule_fact", {"activity": "철근 배근", "site": SITE_B}),
    ("schedule_fact", {"activity": "철근 배근", "site": "나래"}),
    ("my_requests", {"site": "나래 현장"}),
    ("find_contact", {"query": "박현장", "site": SITE_B}),
])
async def test_other_site_on_an_outbound_call_gets_only_the_fixed_line(session, name, args):
    _, box, row = await _confirmed(session)

    r = await box.call(name, args)

    assert r == {"refused": OTHER}  # 다른 자료는 없다
    assert trail(session, row) == [("tool:confirm_person", "allowed"), ("scope_denied", "blocked")]  # 사건 꼭 하나
    assert log(session, row)[-1]["detail"].startswith(f"tool={name} ")


async def test_other_site_report_is_not_filed_under_this_site(session):
    _, box, row = await _confirmed(session)

    r = await box.call("report_from_contact", {"kind": "delay", "text": "하루 늦어요", "quote": "하루 늦어요", "site": SITE_B})

    assert r == {"refused": OTHER}
    assert session.scalars(select(ContactReport)).all() == []
    assert trail(session, row)[-1] == ("scope_denied", "blocked")


@pytest.mark.parametrize("site", [SITE_A, "가람현장", " 가람  현장 ", "가람", "가람 ", ""])
async def test_this_site_named_any_way_still_answers(session, site):
    _, box, _ = await _confirmed(session)

    r = await box.call("schedule_fact", {"activity": "철근 배근", "site": site})

    assert [item["name"] for item in r["items"]] == [f"{MARK_A} 철근 배근"], site


async def test_other_site_on_an_inbound_single_site_call_gets_the_fixed_line(session):
    world(session)
    connect(session)
    box, row = inbound(session, "call", PHONE)

    r = await box.call("schedule_fact", {"activity": "철근 배근", "site": SITE_B})

    assert r == {"refused": OTHER}
    assert trail(session, row) == [("scope_denied", "blocked")]


# ── 우리가 건 통화: 신원 확인 뒤에 개인 자료 ──────────────────────────────


async def test_outbound_personal_tools_wait_for_confirm_person(session):
    w = world(session)
    connect(session)
    message(session, w.park, status="accepted", sent_at=WORK, body="가람 쪽 요청")
    box, row = outbound(session, w.park)

    before = [await box.call("my_requests", {}), await box.call("schedule_fact", {"activity": "철근 배근"})]
    await box.call("confirm_person", {"is_person": True})
    mine = await box.call("my_requests", {})
    fact = await box.call("schedule_fact", {"activity": "철근 배근"})

    assert before == [{"refused": FIRST}] * 2
    assert [item["text"] for item in mine["items"]] == ["가람 쪽 요청"]
    assert [item["name"] for item in fact["items"]] == [f"{MARK_A} 철근 배근"]
    assert trail(session, row) == [("scope_denied", "blocked"), ("scope_denied", "blocked"), ("tool:confirm_person", "allowed"),
                                   ("tool:my_requests", "allowed"), ("tool:schedule_fact", "allowed")]


async def test_not_the_person_stays_refused(session):
    w = world(session)
    connect(session)
    box, _ = outbound(session, w.park)

    await box.call("confirm_person", {"is_person": False})
    after_no = await box.call("my_requests", {})
    await box.call("confirm_person", {"is_person": True})
    await box.call("confirm_person", {"is_person": False})  # 맞다고 했다가 아니라고 하면 다시 닫힌다
    after_retract = await box.call("schedule_fact", {"activity": "철근 배근"})

    assert after_no == after_retract == {"refused": FIRST}


async def test_confirm_that_could_not_be_written_does_not_open_the_gate(session, monkeypatch):
    w = world(session)
    connect(session)
    box, _ = outbound(session, w.park)
    real = tools.Toolbox._record

    def broken(self, session_, name, parsed, step):
        if name == "confirm_person":
            raise RuntimeError("쓰지 못함")
        return real(self, session_, name, parsed, step)

    monkeypatch.setattr(tools.Toolbox, "_record", broken)

    assert await box.call("confirm_person", {"is_person": True}) == {"error": tools.ERR_BUSY}
    assert await box.call("my_requests", {}) == {"refused": FIRST}


async def test_inbound_contact_call_keeps_todays_rule(session):
    """받는 통화는 문이 번호로 상대를 정했다 — confirm_person 없이 그대로 답한다."""
    w = world(session)
    connect(session)
    message(session, w.park, status="accepted", sent_at=WORK, body="가람 쪽 요청")
    box, _ = inbound(session, "call", PHONE)

    mine = await box.call("my_requests", {})

    assert [item["text"] for item in mine["items"]] == ["가람 쪽 요청"]
