"""관리자 등급 연락처의 지시문(11-24 고침 1): 범위가 넓어진 상대에게 모델이 「다른 협력사의 일은 말하지 않습니다」를 듣고 거절하지
않게, 지시문의 범위 단락과 고정 줄을 **범위의 사실 수준(Scope.grant_facts)**으로 고른다. 글(들어온 문자)·음성(받는 통화·거는
통화) 모두, 두 등급 모두. 관리자 단락도 금액·계약·내부 평가·다른 협력사 사람은 그대로 닫는다. 번호·이름은 모두 가상이다."""

import pytest

from app.outreach.harness import door, rules_text
from app.outreach.text import instructions as text_instructions
from app.outreach.text.simulated import Reply
from app.outreach.voice import inbound as voice_inbound
from app.outreach.voice import instructions as voice_instructions
from app.outreach.voice import runner
from app.store.tables_outreach import VoiceSettings
from tests.outreach.harness.test_tools import PHONE
from tests.outreach.test_worker import text_in
from tests.outreach.text.test_responder import (  # noqa: F401 — 고정물
    answer,
    arrive,
    fresh_inbox,
    scripted,
    setup,
)
from tests.outreach.voice.test_inbound import (
    AT,
    world,  # noqa: F401 — 고정물
)
from tests.outreach.voice.test_runner import queued

TRADE_LINE = "그 밖의 작업과 다른 협력사의 일은 말하지 않습니다."
ALL_LINE = "이 현장 모든 협력사·공종 작업의 이름·날짜·상태를 schedule_fact 로 찾아 말할 수 있습니다."
CLOSED_LINE = "금액·계약, 내부 평가, 다른 협력사 사람의 연락처와 사정은 말하지 않습니다."
OLD_NO_MONEY = rules_text.FIXED["no_money"]  # 「다른 협력사의 사정」


def _is_manager(text: str) -> bool:
    return ALL_LINE in text and CLOSED_LINE in text and TRADE_LINE not in text and OLD_NO_MONEY not in text


def _is_trade(text: str) -> bool:
    return TRADE_LINE in text and OLD_NO_MONEY in text and ALL_LINE not in text


# ── 글을 짜는 함수 ──────────────────────────────────────────────────


@pytest.mark.parametrize("cls", ["contact", "contact_multi"])
def test_text_and_voice_inbound_pick_the_paragraph_by_facts(cls):
    for build in (lambda f: text_instructions.inbound(cls, "가람 현장", "박현장", "ko", None, facts=f),
                  lambda f: voice_instructions.inbound(cls, "가람 현장", "박현장", "ko", facts=f)):
        assert _is_trade(build("trade")) and _is_trade(build("none"))
        manager = build("all")
        assert _is_manager(manager)
        assert "금액·계약" in manager and "내부 평가" in manager and "다른 프로젝트" in manager


def test_outbound_picks_the_paragraph_by_facts():
    def build(facts):
        return voice_instructions.outbound("가람 현장", "박현장", "현장소장", "가람건설", "일정 확인", [], [], "ko", facts=facts)

    assert _is_trade(build("trade"))
    assert _is_manager(build("all"))


def test_other_classes_never_get_the_manager_paragraph():
    for cls in ("internal", "shared", "do_not_contact", "unknown", "withheld"):
        assert ALL_LINE not in rules_text.scope_paragraph(cls, "all")
        assert rules_text.fixed_lines(cls, "all") == tuple(rules_text.FIXED.values())


def test_multi_site_manager_still_asks_the_site_first():
    paragraph = rules_text.scope_paragraph("contact_multi", "all")
    assert "어느 현장 일인지 먼저 여쭤보고" in paragraph and "아무것도 말하지 않습니다" in paragraph


# ── 부르는 곳이 범위의 수준을 넘긴다 ─────────────────────────────────────


@pytest.mark.parametrize("level", ["trade", "manager"])
def test_inbound_call_spec_follows_the_contact_level(session, world, level):  # noqa: F811 — 고정물
    world.who.access_level = level
    session.commit()
    caller = door.resolve(session, world.who.phone, now=AT)

    spec, _ = voice_inbound._spec(session, caller)

    assert (_is_manager if level == "manager" else _is_trade)(spec.instructions)


@pytest.mark.parametrize("level", ["trade", "manager"])
def test_outbound_call_spec_follows_the_contact_level(session, world, level):  # noqa: F811 — 고정물
    world.who.access_level = level
    row = queued(session, world.who)
    settings = session.get(VoiceSettings, world.conn.id)

    spec = runner._spec(session, row, world.who, "01000000199", "07000000100", settings, world.conn)

    assert (_is_manager if level == "manager" else _is_trade)(spec.instructions)


@pytest.mark.parametrize("level", ["trade", "manager"])
async def test_text_reply_prompt_follows_the_contact_level(session, fake_provider, fake_channel, scripted, level):  # noqa: F811
    w = setup(session)
    w.park.access_level = level
    session.commit()
    sim = scripted(Reply("네, 확인했습니다"))
    await arrive(fake_provider, text_in(PHONE, "마감 작업 언제예요"))

    await answer()

    assert sim.seen_instructions
    assert (_is_manager if level == "manager" else _is_trade)(sim.seen_instructions[0])
