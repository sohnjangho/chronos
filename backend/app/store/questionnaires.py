"""질문지 저장: 에이전트가 만든 질문(Question)을 담고, 답을 고르거나 지우고, 제출한다.

질문은 에이전트가 그때그때 만든다(분야별로 정해 둔 질문은 없다). 필수 질문은 없고 제출은 언제든 된다.
답하지 않은 질문은 에이전트가 적어 둔 가정(assumption)으로 넘어간다.
답(answers_json)은 {질문 id: 값}. 값은 선택지의 value 이거나 직접 적은 글이다.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.store.schedules import NotFound
from app.store.tables import QuestionnaireRecord

MAX_FREE_TEXT = 500
CLOSED_MESSAGE = "이미 제출한 질문지입니다."
UNKNOWN_QUESTION_MESSAGE = "없는 질문입니다."
NOT_AN_OPTION_MESSAGE = "고를 수 있는 답이 아닙니다."
FREE_TEXT_MESSAGE = f"답은 1~{MAX_FREE_TEXT}자로 적어 주세요."


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=100, description="답으로 저장되는 값")
    label: str = Field(min_length=1, max_length=100, description="화면에 보이는 선택지 글")
    hint: str | None = Field(default=None, max_length=200, description="선택지 도움말")
    recommended: bool = Field(default=False, description="권하는 선택지면 true(질문마다 하나까지)")


class Question(BaseModel):
    """에이전트가 만든 질문 하나."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$", description="질문지 안에서 겹치지 않는 영문 id")
    group: str = Field(min_length=1, max_length=20, description="묶음 이름(예: 범위, 날짜)")
    question: str = Field(min_length=1, max_length=200, description="질문 문구")
    why: str = Field(default="", max_length=200, description="묻는 이유")
    options: list[QuestionOption] = Field(default_factory=list, max_length=4, description="선택지 0~4개")
    allow_free: bool = Field(default=True, description="직접 입력을 받는가")
    assumption: str = Field(
        min_length=1, max_length=200, description="답하지 않으면 이렇게 가정한다(사용자에게 보인다)"
    )


class Prefilled(BaseModel):
    """에이전트가 이미 채운 정보와 그 출처(프롬프트·문서·내 규칙·분야 지식 …)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60, description="무엇")
    value: str = Field(min_length=1, max_length=500, description="값")
    source: str = Field(min_length=1, max_length=30, description="출처")


class SubmittedAnswer(BaseModel):
    question_id: str
    question: str
    value: str
    label: str  # 선택지의 label, 직접 적은 답이면 그 글


class AssumedAnswer(BaseModel):
    question_id: str
    question: str
    assumption: str


class SubmitResult(BaseModel):
    answers: list[SubmittedAnswer]  # 질문 차례
    assumed: list[AssumedAnswer]  # 답하지 않은 질문, 질문 차례


class QuestionnaireError(Exception):
    """질문지 답·제출 실패. code: questionnaire_closed | unknown_question | invalid_answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


# ── 질문 묶음 검사 ──────────────────────────────────────────────────


def _duplicates(values: list[str]) -> list[str]:
    return [v for v, n in Counter(values).items() if n > 1]


def _option_problems(q: Question) -> list[str]:
    problems = []
    if sum(o.recommended for o in q.options) > 1:
        problems.append(f"질문 '{q.id}' 에 추천 선택지가 둘 이상입니다.")
    if dup := _duplicates([o.value for o in q.options]):
        problems.append(f"질문 '{q.id}' 의 선택지 값이 겹칩니다: {', '.join(dup)}")
    if not q.options and not q.allow_free:
        problems.append(f"질문 '{q.id}' 에 답할 방법이 없습니다. 선택지를 두거나 직접 입력을 받으세요.")
    return problems


def question_problems(questions: Sequence[Question]) -> list[str]:
    """질문 묶음의 문제를 한국어로(겹치는 id, 추천 둘 이상, 겹치는 선택지 값, 답할 방법 없음). 없으면 []."""
    problems = []
    if dup := _duplicates([q.id for q in questions]):
        problems.append(f"질문 id 가 겹칩니다: {', '.join(dup)}")
    for q in questions:
        problems += _option_problems(q)
    return problems


# ── 만들기·읽기 ─────────────────────────────────────────────────────


def create(
    session: Session,
    *,
    purpose: str,
    title: str,
    questions: Sequence[Question],
    prefilled: Sequence[Prefilled],
    domain: str | None,
    level: str | None,
    chat_session_id: int | None = None,
    round: int = 1,
    commit: bool = True,
) -> int:
    """질문지를 만들고 id 를 돌려준다. 질문 묶음에 문제가 있으면 ValueError(question_problems 를 이은 글)."""
    problems = question_problems(questions)
    if problems:
        raise ValueError(" / ".join(problems))
    record = QuestionnaireRecord(
        chat_session_id=chat_session_id,
        purpose=purpose,
        title=title,
        domain=domain,
        level=level,
        round=round,
        questions_json=[q.model_dump(mode="json") for q in questions],
        answers_json={},
        prefilled_json=[p.model_dump(mode="json") for p in prefilled],
        status="open",
    )
    session.add(record)
    session.flush()
    if commit:
        session.commit()
    return record.id


def get(session: Session, qid: int) -> QuestionnaireRecord:
    """질문지 한 줄. 없으면 NotFound."""
    record = session.get(QuestionnaireRecord, qid)
    if record is None:
        raise NotFound(qid)
    return record


def questions_of(record: QuestionnaireRecord) -> list[Question]:
    return [Question.model_validate(q) for q in record.questions_json]


def answer_label(question: Question, value: str) -> str:
    """답의 보이는 글: 선택지면 그 label, 직접 적은 답이면 그 글."""
    return next((o.label for o in question.options if o.value == value), value)


def results(record: QuestionnaireRecord) -> SubmitResult:
    """지금 답으로 본 답 목록과 가정 목록(질문 차례). 제출 전후 모두 쓸 수 있다."""
    answers, assumed = [], []
    for q in questions_of(record):
        value = record.answers_json.get(q.id)
        if value is None:
            assumed.append(AssumedAnswer(question_id=q.id, question=q.question, assumption=q.assumption))
        else:
            answers.append(
                SubmittedAnswer(question_id=q.id, question=q.question, value=value, label=answer_label(q, value))
            )
    return SubmitResult(answers=answers, assumed=assumed)


# ── 답하기·제출 ─────────────────────────────────────────────────────


def _open(session: Session, qid: int) -> QuestionnaireRecord:
    record = get(session, qid)
    if record.status != "open":
        raise QuestionnaireError("questionnaire_closed", CLOSED_MESSAGE)
    return record


def _checked(question: Question, value: str) -> str:
    """저장할 값. 선택지 value 면 그대로, 직접 입력이면 앞뒤 공백을 뗀 1~500자."""
    if any(o.value == value for o in question.options):
        return value
    if not question.allow_free:
        raise QuestionnaireError("invalid_answer", NOT_AN_OPTION_MESSAGE)
    text = value.strip()
    if not 1 <= len(text) <= MAX_FREE_TEXT:
        raise QuestionnaireError("invalid_answer", FREE_TEXT_MESSAGE)
    return text


def answer(session: Session, qid: int, question_id: str, value: str | None) -> None:
    """답 하나를 넣거나(value) 지운다(None). 제출한 질문지면 questionnaire_closed."""
    record = _open(session, qid)
    question = next((q for q in questions_of(record) if q.id == question_id), None)
    if question is None:
        raise QuestionnaireError("unknown_question", UNKNOWN_QUESTION_MESSAGE)
    answers = dict(record.answers_json)  # JSON 칸은 새 dict 를 넣어야 바뀐 것으로 저장된다
    if value is None:
        answers.pop(question_id, None)
    else:
        answers[question_id] = _checked(question, value)
    record.answers_json = answers
    session.commit()


def submit(session: Session, qid: int) -> SubmitResult:
    """제출한다(답하지 않은 질문이 있어도 된다). 다시 제출하면 questionnaire_closed."""
    record = _open(session, qid)
    result = results(record)
    record.status = "submitted"
    record.submitted_at = datetime.now(UTC)
    session.commit()
    return result
