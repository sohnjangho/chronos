"""질문지 화면: 묶음별로 보여 주기, 답 넣기·지우기, 제출."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.questionnaire.schemas import (
    AnswerIn,
    AnswerOut,
    GroupOut,
    Progress,
    QuestionnaireView,
    QuestionOut,
    SubmitOut,
)
from app.store import questionnaires as store
from app.store.tables import QuestionnaireRecord

_STATUS = {"questionnaire_closed": 409, "unknown_question": 422, "invalid_answer": 422}


@contextmanager
def _explained() -> Iterator[None]:
    """저장 단계의 실패를 API 오류로."""
    try:
        yield
    except store.NotFound:
        raise ApiError(404, "not_found", "질문지를 찾을 수 없습니다.") from None
    except store.QuestionnaireError as e:
        raise ApiError(_STATUS[e.code], e.code, e.message) from None


def _view(record: QuestionnaireRecord) -> QuestionnaireView:
    groups: dict[str, list[QuestionOut]] = {}  # 처음 나온 차례
    for q in store.questions_of(record):
        value = record.answers_json.get(q.id)
        answer = None if value is None else AnswerOut(value=value, label=store.answer_label(q, value))
        groups.setdefault(q.group, []).append(
            QuestionOut(
                id=q.id,
                question=q.question,
                why=q.why,
                options=q.options,
                allow_free=q.allow_free,
                assumption=q.assumption,
                answer=answer,
            )
        )
    group_out = [
        GroupOut(name=name, answered=sum(x.answer is not None for x in items), total=len(items), questions=items)
        for name, items in groups.items()
    ]
    return QuestionnaireView(
        id=record.id,
        title=record.title,
        purpose=record.purpose,
        status=record.status,
        round=record.round,
        progress=Progress(answered=sum(g.answered for g in group_out), total=sum(g.total for g in group_out)),
        prefilled=record.prefilled_json,
        groups=group_out,
    )


def get_view(session: Session, qid: int) -> QuestionnaireView:
    with _explained():
        return _view(store.get(session, qid))


def answer(session: Session, qid: int, body: AnswerIn) -> QuestionnaireView:
    with _explained():
        store.answer(session, qid, body.question_id, body.value)
        return _view(store.get(session, qid))


def submit(session: Session, qid: int) -> SubmitOut:
    with _explained():
        result = store.submit(session, qid)
    return SubmitOut(id=qid, status="submitted", answers=result.answers, assumed=result.assumed)
