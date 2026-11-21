"""ask.questionnaire — 에이전트가 만든 질문을 대화 카드나 질문지 창으로 띄운다."""

from dataclasses import dataclass

import pytest
from sqlalchemy import func, select

from app.agent.events import AgentEvent
from app.store.tables import QuestionnaireRecord
from app.tools.context import ToolContext
from app.tools.registry import call, list_tools


def q(qid: str, group: str = "범위", **extra) -> dict:
    """질문 하나. 선택지 두 개(첫째 추천), 직접 입력 허용."""
    return {
        "id": qid,
        "group": group,
        "question": f"{qid} 는 어떻게 할까요?",
        "why": "기간을 정하는 데 필요합니다.",
        "options": [
            {"value": "a", "label": "가", "hint": "흔한 경우", "recommended": True},
            {"value": "b", "label": "나", "hint": None, "recommended": False},
        ],
        "allow_free": True,
        "assumption": f"{qid} 는 가로 가정합니다.",
        **extra,
    }


def ask(questions: list[dict], **extra) -> dict:
    return {
        "purpose": "generate",
        "title": "일정 만들기 질문",
        "domain": "construction",
        "level": "L3",
        "questions": questions,
        **extra,
    }


def _rows(session) -> int:
    return session.scalar(select(func.count()).select_from(QuestionnaireRecord))


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


async def test_tool_card_for_two_or_fewer(ctx, events):
    r = await call("ask.questionnaire", ask([q("scope"), q("start_date", group="날짜")]), ctx)
    assert r.ok, r.error
    assert r.output == {"mode": "card", "questions": [q("scope"), q("start_date", group="날짜")]}
    assert events == [
        AgentEvent(
            "card",
            {"kind": "mini_questions", "title": "일정 만들기 질문", "questions": r.output["questions"]},
        )
    ]
    assert _rows(ctx.session) == 0


async def test_tool_creates_questionnaire_and_opens_window(ctx, events, session):
    questions = [q("scope"), q("structure"), q("finish_date", group="날짜")]
    r = await call("ask.questionnaire", ask(questions, prefilled=[{"label": "분야", "value": "건설", "source": "프롬프트"}]), ctx)
    assert r.ok, r.error
    qid = r.output["id"]
    assert r.output == {"mode": "questionnaire", "id": qid, "total": 3}
    assert events == [
        AgentEvent("questionnaire", {"id": qid}),
        AgentEvent("open_window", {"program": "questionnaire", "params": {"id": str(qid)}}),
    ]
    session.expire_all()
    row = session.get(QuestionnaireRecord, qid)
    assert (row.purpose, row.title, row.domain, row.level, row.round, row.status) == (
        "generate", "일정 만들기 질문", "construction", "L3", 1, "open"
    )
    assert row.chat_session_id is None and row.submitted_at is None and row.answers_json == {}
    assert row.questions_json == questions
    assert row.prefilled_json == [{"label": "분야", "value": "건설", "source": "프롬프트"}]


async def test_tool_rejects_duplicate_question_ids(ctx, events):
    r = await call("ask.questionnaire", ask([q("scope"), q("structure"), q("scope")]), ctx)
    assert r.ok is False and "scope" in r.error and "structure" not in r.error
    assert events == [] and _rows(ctx.session) == 0


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


def test_spec():
    spec = next(t for t in list_tools() if t.name == "ask.questionnaire")
    assert (spec.program, spec.mutates) == ("questionnaire", False) and spec.description


@pytest.mark.parametrize(
    ("bad", "words"),
    [
        pytest.param(
            {"options": [{"value": "a", "label": "가", "recommended": True}, {"value": "b", "label": "나", "recommended": True}]},
            ["추천"],
            id="two_recommended",
        ),
        pytest.param(
            {"options": [{"value": "a", "label": "가"}, {"value": "a", "label": "나"}]},
            ["선택지 값", "a"],
            id="duplicate_option_values",
        ),
        pytest.param({"options": [], "allow_free": False}, ["답할 방법"], id="no_way_to_answer"),
    ],
)
async def test_tool_rejects_a_bad_option_set(ctx, events, bad, words):
    r = await call("ask.questionnaire", ask([q("scope"), q("structure", **bad), q("floors")]), ctx)
    assert r.ok is False and "structure" in r.error and all(w in r.error for w in words), r.error
    assert events == [] and _rows(ctx.session) == 0


async def test_tool_rejects_a_bad_option_set_in_card_mode_too(ctx, events):
    r = await call("ask.questionnaire", ask([q("scope", options=[], allow_free=False)]), ctx)
    assert r.ok is False and "scope" in r.error and events == []


async def test_tool_reports_every_problem_at_once(ctx):
    bad = {"options": [{"value": "a", "label": "가", "recommended": True}, {"value": "b", "label": "나", "recommended": True}]}
    r = await call("ask.questionnaire", ask([q("scope"), q("scope"), q("floors", **bad)]), ctx)
    assert r.ok is False and "scope" in r.error and "floors" in r.error


async def test_tool_rejects_invalid_domain_and_accepts_custom_domains(ctx, events, session):
    bad = await call("ask.questionnaire", ask([q("scope")], domain="../farm"), ctx)
    assert (bad.ok, bad.error) == (False, "올바르지 않은 분야입니다: ../farm") and events == []

    for dom in ("rnd", "permitting", "procurement"):
        r = await call("ask.questionnaire", ask([q("scope")], domain=dom), ctx)
        assert r.ok, r.error


async def test_two_phase_guardrail_blocks_multi_question_sheet_when_domain_is_unknown(ctx, events):
    questions = [q("scope"), q("structure"), q("finish_date", group="날짜")]
    blocked = await call("ask.questionnaire", ask(questions, domain=None), ctx)
    assert blocked.ok is False and "분야(주제)가 아직 확정되지 않았습니다" in blocked.error
    assert events == [] and _rows(ctx.session) == 0

    card = await call("ask.questionnaire", ask([q("topic"), q("detail")], domain=None), ctx)
    assert card.ok and card.output["mode"] == "card"


async def test_domain_and_level_may_be_left_out(ctx, session):
    body = ask([q("scope"), q("structure"), q("floors")])
    del body["domain"], body["level"]
    r = await call("ask.questionnaire", {**body, "purpose": "clarify", "round": 2}, ctx)
    assert r.ok, r.error
    row = session.get(QuestionnaireRecord, r.output["id"])
    assert (row.domain, row.level, row.purpose, row.round) == (None, None, "clarify", 2)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"questions": []}, id="no_questions"),
        pytest.param({"questions": [q(f"q{i}") for i in range(16)]}, id="sixteen_questions"),
        pytest.param({"questions": [q("Scope")]}, id="bad_question_id"),
        pytest.param({"questions": [q("scope", options=[{"value": str(i), "label": str(i)} for i in range(5)])]}, id="five_options"),
        pytest.param({"questions": [q("scope", assumption="")]}, id="empty_assumption"),
        pytest.param({"questions": [q("scope", note="x")]}, id="unknown_question_field"),
        pytest.param({"level": "L6"}, id="bad_level"),
        pytest.param({"purpose": "chat"}, id="bad_purpose"),
        pytest.param({"round": 3}, id="third_round"),
        pytest.param({"title": ""}, id="empty_title"),
        pytest.param({"items": ["scope"]}, id="unknown_field"),
    ],
)
async def test_tool_input_is_checked(ctx, events, change):
    r = await call("ask.questionnaire", {**ask([q("scope"), q("structure"), q("floors")]), **change}, ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류"), r.error
    assert events == [] and _rows(ctx.session) == 0


@dataclass(frozen=True)
class ChatContext(ToolContext):
    """대화 id 를 가진 문맥(에이전트 루프가 나중에 줄 수 있는 모양)."""

    chat_session_id: int | None = None


async def test_chat_session_id_comes_from_the_context_when_it_has_one(ctx, session):
    chat_ctx = ChatContext(ctx.session, ctx.user, ctx.schedule_id, ctx.emit, chat_session_id=42)
    r = await call("ask.questionnaire", ask([q("scope"), q("structure"), q("floors")]), chat_ctx)
    assert session.get(QuestionnaireRecord, r.output["id"]).chat_session_id == 42


async def test_created_questionnaire_is_readable_through_the_api(ctx, client, admin):
    r = await call("ask.questionnaire", ask([q("scope"), q("structure"), q("finish_date", group="날짜")]), ctx)
    body = client.get(f"/api/questionnaires/{r.output['id']}", headers=admin).json()
    assert body["progress"] == {"answered": 0, "total": 3}
    assert [g["name"] for g in body["groups"]] == ["범위", "날짜"]


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"question": "   "}, id="question"),
        pytest.param({"assumption": " \n "}, id="assumption"),
        pytest.param({"group": "  "}, id="group"),
        pytest.param({"options": [{"value": "  ", "label": "가"}]}, id="option_value"),
        pytest.param({"options": [{"value": "a", "label": "\t"}]}, id="option_label"),
    ],
)
async def test_whitespace_only_text_is_rejected(ctx, events, bad):
    r = await call("ask.questionnaire", ask([q("scope"), q("structure", **bad), q("floors")]), ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류"), r.error
    assert events == [] and _rows(ctx.session) == 0


async def test_question_text_is_trimmed(ctx, session):
    padded = q(
        "structure",
        group=" 범위 ",
        question="  구조 형식은?  ",
        why=" 기간이 달라집니다. ",
        options=[{"value": " rc ", "label": " 철근콘크리트 ", "hint": " 흔함 ", "recommended": True}],
        assumption=" 철근콘크리트로 가정합니다. ",
    )
    r = await call("ask.questionnaire", ask([q("scope"), padded, q("floors")]), ctx)
    stored = session.get(QuestionnaireRecord, r.output["id"]).questions_json[1]
    assert (stored["group"], stored["question"], stored["why"], stored["assumption"]) == (
        "범위", "구조 형식은?", "기간이 달라집니다.", "철근콘크리트로 가정합니다."
    )
    assert stored["options"] == [{"value": "rc", "label": "철근콘크리트", "hint": "흔함", "recommended": True}]
