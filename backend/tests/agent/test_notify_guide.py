"""연락 지침(prompts/guides/notify.md)과 맥락의 알림 줄(app.outreach.policy — 계획 4 Task 80).

지침은 연락 낱말이나 「연락처」 창에서 골라 붙는다. 맥락 줄은 채널마다 권한(승인 받기·위임)과 시험 모드 한 줄뿐 —
번호·키·Account ID 는 없다. 알림 연결이 없으면 줄도 없다. 네트워크 없이 쿼리 한두 번으로 만든다.
"""

import pytest
from sqlalchemy import event, select

from app.agent import context
from app.agent.context import UiContext
from app.outreach import policy
from app.store.tables import User
from app.store.tables_outreach import NotifyConnection
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY

NO_UI = UiContext(None, None, None)
ACCOUNT = "acct-test-0001"


def _conn(session, **over) -> NotifyConnection:
    values = {"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": SENTINEL_KEY,
              "secret_last4": "9999", "account_id": ACCOUNT, "sender_number": SENTINEL_DIGITS,
              "allow_numbers_json": [SENTINEL_DIGITS], "handoff_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "test_mode": True, **over}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _admin(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


# ── 지침 고르기·내용 ─────────────────────────────────────────────────────


def test_guide_is_picked_for_contact_words_and_program():
    assert "notify" in context.select_guides("박현장 팀장에게 문자 보내 줘", NO_UI, False)
    assert context.select_guides("박현장 팀장에게 문자 보내 줘", NO_UI, False) == ["notify"]  # 전체가 아니라 이것만
    assert context.select_guides("골조 지연을 담당자에게 알려 줘", NO_UI, False) == ["delay", "notify"]
    for text in ("가람철근 담당자에게 알려 줘", "김공정한테 전화 좀 해 줘", "카카오 알림톡으로 보내", "통화 결과 어때?",
                 "연락 됐어?"):
        assert "notify" in context.select_guides(text, NO_UI, False), text
    assert "notify" in context.select_guides("이거 정리해 줘", UiContext("contacts", 1, None), False)


def test_guide_is_not_picked_for_a_plain_delay():
    assert context.select_guides("골조가 4일 밀렸어", NO_UI, has_files=False) == ["delay"]


def test_guide_says_drafts_only_and_names_the_tools():
    guide = (context.GUIDES_DIR / "notify.md").read_text(encoding="utf-8")
    assert guide in context.system_prompt(["notify"])
    for part in ("contacts__list", "notify__draft_message", "notify__draft_call", "notify__status", "초안",
                 "초안을 만들었습니다. [보내기]를 눌러 주세요", "보냈다고 말하지 않는다", "시험 모드", "허용 번호",
                 "확인 필요", "다시 보내지 않는다", "번호", "body_ko", "금액", "날짜"):
        assert part in guide, part
    assert guide.index("contacts__list") < guide.index("notify__draft_message")
    assert len(guide) < 2000  # 짧게


# ── policy ──────────────────────────────────────────────────────────────


def test_policy_without_a_connection(session):
    assert policy.for_agent(session) == policy.AgentPolicy(ready=False, test_mode=True, sms="approve",
                                                           kakao="approve", call="approve")
    assert policy.line(session) is None


def test_policy_reads_the_default_connection(session):
    _conn(session, is_default=False, agent_sms="delegate")  # 기본 연결이 아니면 보지 않는다
    assert policy.line(session) is None
    _conn(session, agent_call="delegate", status="failed", test_mode=False)
    assert policy.for_agent(session) == policy.AgentPolicy(ready=False, test_mode=False, sms="approve",
                                                           kakao="approve", call="delegate")


@pytest.mark.parametrize("value", ["", "DELEGATE", "maybe"])
def test_unknown_permission_values_read_as_approve(session, value):
    _conn(session, agent_sms=value)
    assert policy.for_agent(session).sms == "approve"


def test_context_line_has_no_number_or_key(session):
    _conn(session, agent_call="delegate")
    line = policy.line(session)
    assert line == "- 알림: 문자 승인 받기 · 카카오톡 승인 받기 · 전화 위임 · 시험 모드 켜짐"
    text = context.situation(session, _admin(session), NO_UI)
    assert line in text
    digits = "".join(ch for ch in text if ch.isdigit())
    assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits
    assert SENTINEL_KEY not in text and ACCOUNT not in text and "9999" not in text


def test_line_says_when_the_connection_is_not_ready_and_test_mode_is_off(session):
    _conn(session, agent_sms="delegate", status="unknown", test_mode=False)
    assert policy.line(session) == "- 알림: 문자 위임 · 카카오톡 승인 받기 · 전화 승인 받기 · 시험 모드 꺼짐 · 연결 확인 전"


def test_situation_has_no_line_without_a_connection_or_for_field_role(session):
    assert "- 알림" not in context.situation(session, _admin(session), NO_UI)
    _conn(session)
    field = User(login_id="site1", name="박현장", role="field", password_hash="x")
    session.add(field)
    session.commit()
    assert "- 알림" not in context.situation(session, field, NO_UI)


def test_line_costs_at_most_two_queries(session):
    _conn(session)
    session.expire_all()
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        seen.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        policy.line(session)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert 1 <= len(seen) <= 2
