"""통화 안전(H1) — 하네스 쪽 두 겹과 수신 거부 말 규칙.

- 한 현장으로 정해진 통화에서 상대가 다른 현장 이름을 대면 도구는 그 현장 것을 조용히 주지 않고 고정 안내 하나만 준다(S-17).
- 우리가 건 통화는 confirm_person(is_person=True) 전에는 그 사람의 요청·일정을 주지 않는다(S-18).
- 수신 거부 말 규칙은 들어오는 문자와 통화가 같이 쓴다(door.is_stop) — 통화는 「그만」 같은 한 낱말 규칙을 쓰지 않는다(S-04).

번호·이름·회사는 모두 가상이다(test_tools 의 도우미).
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.outreach.harness import door, tools
from app.store.tables_outreach import ContactReport, OutreachCall
from tests.outreach.harness.test_tools import (
    MARK_A,
    PHONE,
    SITE_A,
    SITE_B,
    WORK,
    connect,
    firm,
    inbound,
    log,
    message,
    outbound,
    project,
    trail,
    who,
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


async def test_other_site_report_is_kept_without_a_schedule(session):
    """다른 실제 현장의 일을 알리면 이 현장 보고로 붙이지 않되 버리지도 않는다 — 일정 없는 보고 한 줄."""
    _, box, row = await _confirmed(session)

    r = await box.call("report_from_contact", {"kind": "delay", "text": "하루 늦어요", "quote": "하루 늦어요", "site": SITE_B})

    assert r == {"refused": OTHER}
    session.expire_all()
    assert [(x.schedule_id, x.kind, x.text, x.call_id) for x in session.scalars(select(ContactReport))] == [
        (None, "delay", "하루 늦어요", row.id)]
    assert trail(session, row)[-1] == ("tool:report_from_contact", "allowed")


async def test_report_naming_a_part_of_this_site_is_filed_here(session):
    w, box, _ = await _confirmed(session)

    await box.call("report_from_contact", {"kind": "delay", "text": "B동 하루 늦어요", "quote": "하루 늦어요", "site": "B동"})

    session.expire_all()
    assert [x.schedule_id for x in session.scalars(select(ContactReport))] == [w.a]


@pytest.mark.parametrize("site", [SITE_A, "가람현장", " 가람  현장 ", "가람", "가람 ", "", "가람 아파트", "우리 현장", "B동", "3층",
                                  "다른 현장"])
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


# ── 고침 1: 흔한 거부 말(문자·통화 같은 규칙, 문장마다) ───────────────────


@pytest.mark.parametrize("text", [
    "앞으로 전화하지 마세요", "다시는 연락 주지 마십시오", "문자 마요", "전화 하지 마세요.", "연락하지 말아 주세요",
    "저한테 다시는 전화하지 마세요", "수신거부 부탁드릴게요", "수신 거부 부탁드려요", "수신 거부 처리해 주세요", "수신거부 해 주세요",
    "수신거부 해줘", "수신거부 할게", "수신거부 할게요", "네. 수신거부요.", "알겠습니다\n다시는 전화하지 마세요!",
    "네 알겠어요. 앞으로 문자하지 마세요",
])
def test_common_opt_out_phrases_count_for_text_and_speech(text):
    assert door.is_stop(text) and door.is_stop(text, single_words=False)


@pytest.mark.parametrize("text", [
    "전화하지 마시고 문자 주세요", "수신거부요?", "다시는 전화하지 마세요?", "수신 거부 해 주세요? 어떻게요", "수신거부 아닙니다",
    "그만 말씀하세요", "전화 주세요", "걱정 마세요", "연락 주세요. 마세요라고 하신 건 아니고요",
])
def test_near_misses_are_not_opt_out(text):
    assert not door.is_stop(text) and not door.is_stop(text, single_words=False)


def test_text_door_hears_the_common_phrases(session):
    world(session)
    connect(session)
    assert door.admit(session, "sms", PHONE, now=WORK, body="다시는 연락하지 마세요").verdict == "stop"
    assert door.admit(session, "sms", PHONE, now=WORK, body="전화하지 마시고 문자 주세요").verdict != "stop"
    assert door.admit(session, "sms", PHONE, now=WORK, body="수신거부요?").verdict != "stop"


# ── 고침 1: 확인 전에는 사람 목록이 없다 ──────────────────────────────────


async def test_find_contact_before_identity_lists_nobody_but_still_redirects(session, fake_channel):
    w = world(session)
    connect(session)
    kim = who(session, w.rebar_a, "김철근", "01000000133", role_title="철근 기사")
    box, row = outbound(session, w.park)

    listed = await box.call("find_contact", {"query": "철근"})
    sent = await box.call("find_contact", {"query": "김철근", "redirect": True})
    await box.call("confirm_person", {"is_person": True})
    after = await box.call("find_contact", {"query": "김철근"})

    assert listed == {"redirected": False}
    assert sent == {"redirected": True}  # 「담당은 그 사람」은 그대로 된다 — 목록만 주지 않는다
    session.expire_all()
    follow = session.scalars(select(OutreachCall).where(OutreachCall.prev_call_id == row.id)).all()
    assert [f.contact_id for f in follow] == [kim.id]
    assert [item["name"] for item in after["items"]] == ["김철근"]
    assert "김철근" not in str(listed) + str(sent)


# ── 고침 2: 거부 말은 문장 전체 · 때·남 얘기는 빼고 ─────────────────────────


@pytest.mark.parametrize("text", [
    "소장님한테 전화하지 마세요", "현장에 전화 주지 마세요", "지금은 전화하지 마세요", "오늘은 연락하지 마세요",
    "지금 운전 중이니 전화하지 마세요", "연락 주지 마세요. 지금 운전 중이라", "당분간 문자하지 마세요", "이따 전화하지 마세요",
    "내일은 연락 주지 마세요", "아직 전화하지 마세요", "잠깐 전화하지 마세요", "김반장에게 문자하지 마세요",
])
def test_temporary_or_third_party_requests_are_not_opt_out(text):
    assert not door.is_stop(text) and not door.is_stop(text, single_words=False)


@pytest.mark.parametrize("text", [
    "전화하지 마세요", "앞으로 연락하지 마세요", "다시는 전화 주지 마세요", "이제 연락하지 말아 주세요", "저한테 전화하지 마세요",
    "제게 문자하지 마십시오", "이 번호로 전화하지 마세요", "더 이상 연락하지 마세요", "이제 더는 전화하지 마세요",
    "앞으로 저한테 다시는 연락하지 마세요",
])
def test_whole_sentence_opt_out_phrases(text):
    assert door.is_stop(text) and door.is_stop(text, single_words=False)


def test_text_door_keeps_the_explicit_forms(session):
    world(session)
    connect(session)
    for body in ("수신거부", "수신 거부 해 주세요", "수신거부요", "앞으로 연락하지 마세요"):
        assert door.admit(session, "sms", PHONE, now=WORK, body=body).verdict == "stop", body
    assert door.admit(session, "sms", PHONE, now=WORK, body="지금은 전화하지 마세요").verdict != "stop"


# ── 고침 2: 겹치는 현장 이름 ─────────────────────────────────────────────


def _block_two(session):
    """가람 현장과 이름이 겹치는 실제 현장 「가람 2단지」(사람 한 명)."""
    sid = project(session, "가람 2단지", "표식-이", date(2029, 1, 1))
    return sid, who(session, firm(session, sid, "이단지철근", "철근"), "정이단", "01000000111")


@pytest.mark.parametrize("site", ["가람 2단지 B동", "가람2단지 현장 3층", "가람 2단지", "나래 가람", "가람 나래 현장"])
async def test_more_specific_or_mixed_site_is_refused_and_report_kept(session, site):
    w = world(session)
    connect(session)
    _block_two(session)
    box, _ = outbound(session, w.park)
    await box.call("confirm_person", {"is_person": True})

    fact = await box.call("schedule_fact", {"activity": "철근 배근", "site": site})
    await box.call("report_from_contact", {"kind": "delay", "text": "하루 늦어요", "quote": "하루 늦어요", "site": site})

    assert fact == {"refused": OTHER}, site
    session.expire_all()
    assert [x.schedule_id for x in session.scalars(select(ContactReport))] == [None]


@pytest.mark.parametrize("site", ["가람", "가람 현장 B동", "가람 아파트 3층"])
async def test_this_site_still_answers_next_to_a_longer_name(session, site):
    w = world(session)
    connect(session)
    _block_two(session)
    box, _ = outbound(session, w.park)
    await box.call("confirm_person", {"is_person": True})

    fact = await box.call("schedule_fact", {"activity": "철근 배근", "site": site})

    assert [item["name"] for item in fact["items"]] == [f"{MARK_A} 철근 배근"], site


@pytest.mark.parametrize(("site", "answered"), [("가람 2단지 B동", True), ("2단지 3층", True), ("가람 2단지", True),
                                                ("가람", False), ("가람 현장", False), ("나래", False)])
async def test_reverse_direction_on_the_longer_site(session, site, answered):
    """「가람 2단지」 통화에서는 그 이름 안의 「가람」이 다른 현장이 아니다 — 「가람」만 말하면 다른 실제 현장."""
    world(session)
    connect(session)
    _, jung = _block_two(session)
    box, _ = outbound(session, jung)
    await box.call("confirm_person", {"is_person": True})

    fact = await box.call("schedule_fact", {"activity": "철근 배근", "site": site})

    if answered:
        assert [item["name"] for item in fact["items"]] == ["표식-이 철근 배근"], site
    else:
        assert fact == {"refused": "이 통화는 가람 2단지 현장 건입니다"}, site


# ── 수신거부 앞의 대답 말 · 「원해요」 ──────────────────────────────────────


@pytest.mark.parametrize("text", ["네, 수신거부요", "예 수신거부", "아 수신거부할게요", "수신거부 원해요", "응, 수신 거부 해 주세요",
                                  "넵 수신거부요."])
def test_acknowledgement_before_the_explicit_word(text):
    assert door.is_stop(text) and door.is_stop(text, single_words=False)


@pytest.mark.parametrize("text", ["네, 수신거부요?", "수신거부요?", "수신거부 아닙니다", "네 수신거부 아닙니다", "아니 수신거부",
                                  "네네 수신거부 어떻게 해요"])
def test_acknowledgement_does_not_open_questions_or_negations(text):
    assert not door.is_stop(text) and not door.is_stop(text, single_words=False)
