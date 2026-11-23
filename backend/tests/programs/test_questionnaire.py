"""질문지 API: 묶음·진행, 답 고르기·적기·지우기, 제출(답과 가정)."""

import pytest
from pydantic import ValidationError

from app.store import questionnaires as store
from app.store.questionnaires import Prefilled, Question
from app.store.tables import QuestionnaireRecord

STRUCTURE = {
    "id": "structure",
    "group": "범위",
    "question": "건물의 구조 형식은 무엇인가요?",
    "why": "층당 골조 기간이 구조 형식에 따라 달라집니다.",
    "options": [
        {"value": "rc", "label": "철근콘크리트", "hint": "중층 사무동에 가장 흔합니다.", "recommended": True},
        {"value": "steel", "label": "철골", "hint": None, "recommended": False},
        {"value": "src", "label": "철골철근콘크리트", "hint": None, "recommended": False},
    ],
    "allow_free": True,
    "assumption": "철근콘크리트 구조로 가정합니다.",
}
FINISH = {
    "id": "finish_date",
    "group": "날짜",
    "question": "준공 목표일이 정해져 있나요?",
    "why": "",
    "options": [],
    "allow_free": True,
    "assumption": "착공 후 18개월 뒤를 준공으로 가정합니다.",
}
FLOORS = {
    "id": "floors_above",
    "group": "범위",
    "question": "지상 몇 층인가요?",
    "why": "골조 기간이 층수에 비례합니다.",
    "options": [
        {"value": "5", "label": "5층", "hint": None, "recommended": True},
        {"value": "10", "label": "10층", "hint": None, "recommended": False},
    ],
    "allow_free": True,
    "assumption": "지상 5층으로 가정합니다.",
}
WORK_WEEK = {
    "id": "work_week",
    "group": "달력",
    "question": "주 며칠 일하나요?",
    "why": "작업 달력을 정합니다.",
    "options": [
        {"value": "5", "label": "주 5일", "hint": None, "recommended": False},
        {"value": "6", "label": "주 6일", "hint": "건설 현장 기본", "recommended": True},
    ],
    "allow_free": False,
    "assumption": "주 6일로 가정합니다.",
}
PREFILLED = [{"label": "분야", "value": "건설", "source": "프롬프트"}]


def _create(session, questions: list[dict]) -> int:
    return store.create(
        session,
        purpose="generate",
        title="일정 만들기 질문지",
        questions=[Question.model_validate(x) for x in questions],
        prefilled=[Prefilled.model_validate(x) for x in PREFILLED],
        domain="construction",
        level="L3",
    )


@pytest.fixture
def qid(session) -> int:
    """구조(범위) · 준공일(날짜, 선택지 없음) · 층수(범위). 아무것도 답하지 않음."""
    return _create(session, [STRUCTURE, FINISH, FLOORS])


@pytest.fixture
def qid_no_free(session) -> int:
    """주 근무일 하나. 직접 입력은 받지 않는다."""
    return _create(session, [WORK_WEEK])


def _get(client, headers, qid):
    r = client.get(f"/api/questionnaires/{qid}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()


def _answer(client, headers, qid, question_id, value):
    return client.patch(f"/api/questionnaires/{qid}/answers", json={"question_id": question_id, "value": value}, headers=headers)


def _question(body, question_id):
    return next(x for g in body["groups"] for x in g["questions"] if x["id"] == question_id)


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_get_groups_and_progress(client, admin, qid):
    body = _get(client, admin, qid)
    assert (body["id"], body["title"], body["purpose"], body["status"], body["round"]) == (qid, "일정 만들기 질문지", "generate", "open", 1)
    assert body["progress"] == {"answered": 0, "total": 3}
    assert body["prefilled"] == PREFILLED
    assert [(g["name"], g["answered"], g["total"]) for g in body["groups"]] == [("범위", 0, 2), ("날짜", 0, 1)]
    assert [[x["id"] for x in g["questions"]] for g in body["groups"]] == [["structure", "floors_above"], ["finish_date"]]
    expected = {k: v for k, v in STRUCTURE.items() if k != "group"}
    assert _question(body, "structure") == {**expected, "answer": None}


def test_answer_option_and_free_text(client, admin, qid):
    r = _answer(client, admin, qid, "structure", "rc")
    assert r.status_code == 200, r.json()
    assert _question(r.json(), "structure")["answer"] == {"value": "rc", "label": "철근콘크리트"}
    assert r.json()["progress"] == {"answered": 1, "total": 3} and r.json()["groups"][0]["answered"] == 1
    r = _answer(client, admin, qid, "finish_date", "2028년 6월 말")
    assert _question(r.json(), "finish_date")["answer"] == {"value": "2028년 6월 말", "label": "2028년 6월 말"}
    r = _answer(client, admin, qid, "structure", "목구조")  # 선택지에 없지만 직접 입력이 된다
    assert _question(r.json(), "structure")["answer"] == {"value": "목구조", "label": "목구조"}
    assert _get(client, admin, qid)["progress"] == {"answered": 2, "total": 3}


def test_answer_not_an_option_when_free_text_disallowed(client, admin, qid_no_free):
    r = _answer(client, admin, qid_no_free, "work_week", "4")
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("invalid_answer", "고를 수 있는 답이 아닙니다.")
    assert _question(_get(client, admin, qid_no_free), "work_week")["answer"] is None
    r = _answer(client, admin, qid_no_free, "work_week", "6")
    assert _question(r.json(), "work_week")["answer"] == {"value": "6", "label": "주 6일"}


def test_unknown_question_422(client, admin, qid):
    r = _answer(client, admin, qid, "budget", "많음")
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("unknown_question", "없는 질문입니다.")


def test_null_clears_answer(client, admin, qid):
    _answer(client, admin, qid, "structure", "rc")
    r = _answer(client, admin, qid, "structure", None)
    assert r.status_code == 200 and _question(r.json(), "structure")["answer"] is None
    assert r.json()["progress"] == {"answered": 0, "total": 3}
    assert _answer(client, admin, qid, "floors_above", None).status_code == 200  # 답 없는 것을 지워도 된다


def test_submit_lists_answers_and_assumptions(client, admin, qid):
    _answer(client, admin, qid, "structure", "rc")
    r = client.post(f"/api/questionnaires/{qid}/submit", headers=admin)
    assert r.status_code == 200, r.json()
    assert r.json() == {
        "id": qid,
        "status": "submitted",
        "answers": [{"question_id": "structure", "question": STRUCTURE["question"], "value": "rc", "label": "철근콘크리트"}],
        "assumed": [
            {"question_id": "finish_date", "question": FINISH["question"], "assumption": FINISH["assumption"]},
            {"question_id": "floors_above", "question": FLOORS["question"], "assumption": FLOORS["assumption"]},
        ],
    }
    assert _get(client, admin, qid)["status"] == "submitted"


def test_closed_after_submit(client, admin, qid):
    assert client.post(f"/api/questionnaires/{qid}/submit", headers=admin).status_code == 200
    for r in (_answer(client, admin, qid, "structure", "rc"), client.post(f"/api/questionnaires/{qid}/submit", headers=admin)):
        assert r.status_code == 409
        assert (r.json()["code"], r.json()["message"]) == ("questionnaire_closed", "이미 제출한 질문지입니다.")
    assert _question(_get(client, admin, qid), "structure")["answer"] is None


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


def test_free_text_length(client, admin, qid):
    assert _answer(client, admin, qid, "finish_date", "가" * 500).status_code == 200
    for value in ("가" * 501, "", "   "):
        r = _answer(client, admin, qid, "finish_date", value)
        assert (r.status_code, r.json()["code"]) == (422, "invalid_answer"), value
    assert _question(_get(client, admin, qid), "finish_date")["answer"]["value"] == "가" * 500


def test_free_text_is_trimmed(client, admin, qid):
    r = _answer(client, admin, qid, "finish_date", "  2028-06-30 ")
    assert _question(r.json(), "finish_date")["answer"] == {"value": "2028-06-30", "label": "2028-06-30"}


def test_submit_with_nothing_answered_assumes_everything(client, admin, qid):
    r = client.post(f"/api/questionnaires/{qid}/submit", headers=admin)
    assert r.json()["answers"] == [] and [x["question_id"] for x in r.json()["assumed"]] == ["structure", "finish_date", "floors_above"]


def test_unknown_questionnaire_404(client, admin):
    for r in (
        client.get("/api/questionnaires/999", headers=admin),
        _answer(client, admin, 999, "structure", "rc"),
        client.post("/api/questionnaires/999/submit", headers=admin),
    ):
        assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_login_required(client, qid):
    assert client.get(f"/api/questionnaires/{qid}").status_code == 401
    assert _answer(client, {}, qid, "structure", "rc").status_code == 401
    assert client.post(f"/api/questionnaires/{qid}/submit").status_code == 401


def test_any_logged_in_user_can_answer_and_submit(client, user, qid):
    assert _answer(client, user, qid, "structure", "steel").status_code == 200
    r = client.post(f"/api/questionnaires/{qid}/submit", headers=user)
    assert r.status_code == 200 and r.json()["answers"][0]["label"] == "철골"


def test_value_key_is_required(client, admin, qid):
    r = client.patch(f"/api/questionnaires/{qid}/answers", json={"question_id": "structure"}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")


def test_view_carries_the_chat_session_it_came_from(client, admin, session, qid):
    """질문지 화면이 제출 뒤 이어 갈 대화를 안다(대화 밖에서 열었을 때). 대화 없이 만든 질문지는 null."""
    from_chat = store.create(
        session, purpose="generate", title="t", questions=[Question.model_validate(FINISH)], prefilled=[], domain=None, level=None, chat_session_id=42
    )
    assert _get(client, admin, from_chat)["chat_session_id"] == 42
    assert _answer(client, admin, from_chat, "finish_date", "2028년 6월 말").json()["chat_session_id"] == 42
    assert _get(client, admin, qid)["chat_session_id"] is None


# ── 저장 함수 ───────────────────────────────────────────────────────


def test_store_submit_records_the_time_and_status(session, qid):
    result = store.submit(session, qid)
    assert [x.question_id for x in result.assumed] == ["structure", "finish_date", "floors_above"]
    row = session.get(QuestionnaireRecord, qid)
    assert row.status == "submitted" and row.submitted_at is not None


def test_store_errors(session, qid):
    with pytest.raises(store.NotFound):
        store.get(session, 999)
    with pytest.raises(store.QuestionnaireError) as e:
        store.answer(session, qid, "budget", "x")
    assert e.value.code == "unknown_question"
    store.submit(session, qid)
    with pytest.raises(store.QuestionnaireError) as e:
        store.answer(session, qid, "structure", "rc")
    assert e.value.code == "questionnaire_closed"


def test_store_create_refuses_a_bad_question_set(session):
    with pytest.raises(ValueError, match="structure"):
        _create(session, [STRUCTURE, STRUCTURE])
    assert session.query(QuestionnaireRecord).count() == 0


def test_store_create_without_commit(session):
    qid = store.create(
        session, purpose="delay", title="지연 등록", questions=[Question.model_validate(FINISH)], prefilled=[], domain=None, level=None, commit=False
    )
    session.rollback()
    assert session.get(QuestionnaireRecord, qid) is None


def test_store_create_accepts_prefilled_dicts_and_models(client, admin, session):
    prefilled = [{"label": "분야", "value": "건설", "source": "프롬프트"}, Prefilled(label="정밀도", value="L3 관리", source="분야 지식")]
    qid = store.create(
        session, purpose="generate", title="t", questions=[Question.model_validate(FINISH)], prefilled=prefilled, domain=None, level=None
    )
    assert _get(client, admin, qid)["prefilled"] == [
        {"label": "분야", "value": "건설", "source": "프롬프트"},
        {"label": "정밀도", "value": "L3 관리", "source": "분야 지식"},
    ]


def test_store_create_rejects_a_bad_prefilled_dict(session):
    with pytest.raises(ValidationError):
        store.create(
            session, purpose="generate", title="t", questions=[Question.model_validate(FINISH)], prefilled=[{"label": "분야"}], domain=None, level=None
        )
    assert session.query(QuestionnaireRecord).count() == 0


def test_a_closed_questionnaire_reads_as_closed_and_takes_no_answers(client, admin, session, qid):
    """재확인 2(#45): 현장 관리자의 새 일정 질문을 닫은 질문지(status closed)는 읽히고(closed) 답·제출은 받지 않는다."""
    session.get(QuestionnaireRecord, qid).status = "closed"
    session.commit()
    assert client.get(f"/api/questionnaires/{qid}", headers=admin).json()["status"] == "closed"
    assert client.post(f"/api/questionnaires/{qid}/submit", headers=admin).status_code == 409
