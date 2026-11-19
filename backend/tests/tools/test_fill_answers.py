"""도구 ask.fill_answers: 질문지를 연 채 대화로 답하면 그 칸을 채운다."""

import pytest

from app.agent.events import AgentEvent
from app.store import questionnaires as store
from app.store.questionnaires import Question
from app.tools.registry import call, list_tools

QUESTIONS = [
    Question(id="floors", group="범위", question="지상 몇 층인가요?", assumption="5층으로 가정합니다.",
             options=[{"value": "5", "label": "5층"}, {"value": "10", "label": "10층"}]),
    Question(id="week", group="달력", question="주 며칠 일하나요?", assumption="주 6일로 가정합니다.",
             options=[{"value": "5", "label": "주 5일"}, {"value": "6", "label": "주 6일"}], allow_free=False),
    Question(id="finish", group="날짜", question="준공 목표일은?", assumption="18개월 뒤로 가정합니다."),
]


@pytest.fixture
def qid(session) -> int:
    return store.create(session, purpose="generate", title="질문", questions=QUESTIONS, prefilled=[],
                        domain="construction", level="L3", chat_session_id=None)


def answers_of(session, qid) -> dict:
    session.expire_all()
    return store.get(session, qid).answers_json


def test_tool_is_registered_as_a_mutating_questionnaire_tool():
    spec = next(s for s in list_tools() if s.name == "ask.fill_answers")
    assert (spec.program, spec.mutates) == ("questionnaire", True)


async def test_fills_answers_and_tells_the_screen(ctx, events, session, qid):
    args = {"questionnaire_id": qid, "answers": [
        {"question_id": "floors", "value": "10"},
        {"question_id": "finish", "value": "  2028년 6월  "},
    ]}
    r = await call("ask.fill_answers", args, ctx)
    assert r.ok and r.output == {"filled": 2}
    assert answers_of(session, qid) == {"floors": "10", "finish": "2028년 6월"}
    assert events == [AgentEvent("card", {"kind": "answers_filled", "questionnaire_id": qid, "count": 2})]


async def test_null_clears_an_answer(ctx, session, qid):
    store.answer(session, qid, "floors", "5")
    r = await call("ask.fill_answers", {"questionnaire_id": qid, "answers": [{"question_id": "floors", "value": None}]}, ctx)
    assert r.ok and answers_of(session, qid) == {}


@pytest.mark.parametrize(
    "answers, message",
    [
        ([{"question_id": "nope", "value": "1"}], "없는 질문입니다."),
        ([{"question_id": "week", "value": "7"}], "고를 수 있는 답이 아닙니다."),
        ([{"question_id": "finish", "value": "   "}], "답은 1~500자로 적어 주세요."),
    ],
    ids=["unknown_question", "not_an_option", "blank_free_text"],
)
async def test_store_errors_become_tool_errors(ctx, events, session, qid, answers, message):
    r = await call("ask.fill_answers", {"questionnaire_id": qid, "answers": answers}, ctx)
    assert (r.ok, r.error) == (False, message) and events == []


async def test_closed_questionnaire_is_a_tool_error(ctx, events, session, qid):
    store.submit(session, qid)
    r = await call("ask.fill_answers", {"questionnaire_id": qid, "answers": [{"question_id": "floors", "value": "5"}]}, ctx)
    assert (r.ok, r.error) == (False, "이미 제출한 질문지입니다.") and events == []


async def test_unknown_questionnaire_is_a_tool_error(ctx):
    r = await call("ask.fill_answers", {"questionnaire_id": 999, "answers": [{"question_id": "floors", "value": "5"}]}, ctx)
    assert (r.ok, r.error) == (False, "질문지를 찾을 수 없습니다.")


async def test_a_failing_answer_leaves_earlier_answers_untouched(ctx, session, qid):
    store.answer(session, qid, "finish", "2028년")
    args = {"questionnaire_id": qid, "answers": [
        {"question_id": "floors", "value": "10"},
        {"question_id": "week", "value": "7"},
    ]}
    r = await call("ask.fill_answers", args, ctx)
    assert r.ok is False and answers_of(session, qid) == {"finish": "2028년"}


@pytest.mark.parametrize(
    "args",
    [
        {"questionnaire_id": 1, "answers": []},
        {"questionnaire_id": 1, "answers": [{"question_id": "a", "value": "1"}] * 16},
        {"questionnaire_id": 1, "answers": [{"question_id": "a"}]},
        {"questionnaire_id": 1, "answers": [{"question_id": "a", "value": "1", "extra": 1}]},
        {"questionnaire_id": 1, "answers": [{"question_id": "a", "value": "1"}], "extra": 1},
    ],
    ids=["empty", "too_many", "value_missing", "extra_in_answer", "extra_top"],
)
async def test_input_shape_is_strict(ctx, args):
    r = await call("ask.fill_answers", args, ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류")
