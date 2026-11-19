from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.questionnaire import service
from app.programs.questionnaire.schemas import AnswerIn, QuestionnaireView, SubmitOut
from app.security.deps import current_user

# 로그인한 사람은 누구나 읽고 답하고 제출할 수 있다(작업 공간 하나).
router = APIRouter(
    prefix="/api/questionnaires", tags=["questionnaires"], dependencies=[Depends(current_user)]
)

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{qid}")
def get_questionnaire(qid: int, session: SessionDep) -> QuestionnaireView:
    return service.get_view(session, qid)


@router.patch("/{qid}/answers")
def patch_answer(qid: int, body: AnswerIn, session: SessionDep) -> QuestionnaireView:
    return service.answer(session, qid, body)


@router.post("/{qid}/submit")
def submit_questionnaire(qid: int, session: SessionDep) -> SubmitOut:
    return service.submit(session, qid)
