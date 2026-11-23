"""A6: 저장된 스킬 — 관계없는 요청에 붙지 않게(기준 3점·흔한 말·숫자 낱말 빼기), 기록 도구는 요청했을 때만,
저장할 때 단계 정리(연달아 같은 도구 한 번 · 질문지·창 열기 빼기)."""

from sqlalchemy import select

from app.store import chats, skills
from app.store.tables import SkillRow, User, WorkflowRun, WorkflowStep

REQUEST = "지상 골조가 비 때문에 3일 늦어졌어. 영향 계산해서 기록해 줘"


def _admin(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


def _run(session, tools: list[str], request: str = REQUEST) -> int:
    chat = chats.create_chat(session, user_id=_admin(session).id)
    run = WorkflowRun(chat_session_id=chat.id, title="지연 기록", request=request, status="done")
    session.add(run)
    session.flush()
    for n, tool in enumerate(tools, 1):
        session.add(WorkflowStep(run_id=run.id, n=n, tool=tool, why=f"{n}번", status="done", input_json="{}"))
    session.commit()
    return run.id


def _saved(session, tools=("schedule.find", "delay.record"), **over) -> SkillRow:
    return skills.create_from_run(session, run_id=_run(session, list(tools)), user_id=_admin(session).id,
                                  name=over.pop("name", "골조 지연 기록"), **over)


def test_request_sharing_only_common_words_does_not_match(session):
    _saved(session)
    # 예전 기준(2점)이면 골조·지상 둘로 붙었다
    assert skills.match_skill(session, "D-3 미준비 자재가 지상 골조 작업에 미치는 영향 알려 줘") is None


def test_request_close_to_the_original_matches(session):
    saved = _saved(session)
    assert skills.match_skill(session, "지상 골조가 비 때문에 2일 늦어졌어. 영향 알려 줘") == saved


def test_common_and_number_words_never_score(session):
    """예전에 저장된 찾는 말(흔한 말·숫자로 시작하는 말)도 점수에 들지 않는다."""
    session.add(SkillRow(name="지연 영향", description="", triggers_json=["지상", "골조가", "때문에", "3일", "늦어졌어", "영향"],
                         steps_json=[{"tool": "delay.record", "why": ""}], created_by=_admin(session).id))
    session.commit()
    assert skills.match_skill(session, "3일 때문에 늦어졌어 영향 알려 줘") is None
    assert skills.match_skill(session, "지상 골조가 3일 늦어졌어") is None  # 지상·골조가 2점뿐


def test_default_triggers_skip_common_and_number_words(session):
    assert _saved(session).triggers_json == ["골조", "기록", "지상", "골조가", "기록해"]


def test_saved_steps_drop_repeats_questionnaires_and_window_opening(session):
    tools = ["ask.questionnaire", "schedule.find", "schedule.find", "schedule.find", "ui.open_window", "delay.record",
             "schedule.find"]
    assert [s["tool"] for s in _saved(session, tools).steps_json] == ["schedule.find", "delay.record", "schedule.find"]


def test_prompt_block_says_record_tools_only_when_asked(session):
    block = skills.skill_prompt_block(_saved(session))
    assert "요청이 같은 일일 때만 참고한다" in block
    assert "기록·저장·제출 도구는 사용자가 이번에 그렇게 해 달라고 했을 때만 부른다" in block
    assert "우선 따라 실행한다" not in block
