"""지시문(prompts/system.md)의 프로그램 목록: 화면 프로그램 id 와 이름(Task 16b — 일정판이 넷으로 나뉨)."""

import typing

from app.agent import context
from app.tools.ui.open_window import OpenWindowIn


def test_the_prompt_names_every_program_the_agent_can_open():
    prompt = context.system_prompt()
    ids = typing.get_args(OpenWindowIn.model_fields["program"].annotation)
    assert ids and all(f"`{i}`" in prompt for i in ids)
    for line in ("`schedule-table` 스케줄", "`gantt` 간트차트", "`cpm` CPM", "`progress` 공정률", "`contacts` 연락처"):
        assert line in prompt


def test_the_old_schedule_board_is_gone_from_the_prompt():
    prompt = context.system_prompt()
    assert "일정판" not in prompt and "`schedule`" not in prompt


# ── A5: 지금 상황에 이 대화의 승인 건 상태 ──────────────────────────


def _approval(session, chat_id, status, version=None, title="일정 고침"):
    from app.store.tables import Approval

    row = Approval(kind="change", title=title, base_version=1, summary_json={}, snapshot_json={}, requested_by="admin",
                   chat_session_id=chat_id, status=status, version=version)
    session.add(row)
    session.flush()
    return row.id


def test_situation_shows_the_current_state_of_this_chats_approvals(session):
    from sqlalchemy import select

    from app.store import chats
    from app.store.tables import User

    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    chat, other = (chats.create_chat(session, user_id=admin.id).id for _ in range(2))
    _approval(session, other, "pending")  # 다른 대화의 건은 보이지 않는다
    done = _approval(session, chat, "approved", version=3)
    no = _approval(session, chat, "rejected")
    wait = _approval(session, chat, "pending")
    session.commit()
    text = context.build_context(session, admin, chat, context.UiContext())[0]["content"]
    assert f"- 이 대화의 승인 건: 승인 {done} 승인됨(버전 3) · 승인 {no} 거부됨 · 승인 {wait} 대기" in text
    assert "승인 건의 상태는 '지금 상황'의 값만 말한다" in text


def test_situation_has_no_approval_line_without_approvals(session):
    from sqlalchemy import select

    from app.store import chats
    from app.store.tables import User

    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    chat = chats.create_chat(session, user_id=admin.id).id
    session.commit()
    assert "이 대화의 승인 건" not in context.situation(session, admin, context.UiContext(), chat_session_id=chat)


# ── A11: 답 표현(분야 이름·자원 단위·한 달 날씨 통계) ─────────────────


def test_the_prompt_asks_for_korean_domain_names_and_condition_units():
    prompt = context.system_prompt([])
    assert "분야는 한국어 이름으로 말한다" in prompt and "자원 단위는 조건·도구 결과의 단위 그대로" in prompt


def test_the_weather_guide_says_a_month_statistic_is_not_a_yearly_average():
    guide = context.system_prompt(["weather"])
    assert "「연 평균」이라고 쓰지 않는다" in guide and "2016~2025년 12월 평균" in guide
