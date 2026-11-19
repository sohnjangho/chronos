"""ask.fill_answers — 질문지를 연 채 사용자가 대화로 답하면 그 질문의 칸을 채운다.

답 규칙은 질문지 저장(app.store.questionnaires.answer)과 같다. 하나라도 틀리면 이번에 넣은 답은 모두 되돌린다.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.store import questionnaires as store
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

NOT_FOUND_MESSAGE = "질문지를 찾을 수 없습니다."


class AnswerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(description="질문 id")
    value: str | None = Field(description="선택지의 value 또는 직접 적은 답. null 이면 답을 지운다")


class FillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questionnaire_id: int = Field(description="열려 있는 질문지 id")
    answers: list[AnswerItem] = Field(min_length=1, max_length=15, description="채울 답 1~15개")


class FillOut(BaseModel):
    filled: int


@tool(
    "ask.fill_answers",
    "열려 있는 질문지에 사용자가 대화로 말한 답을 채운다. 선택지가 있는 질문은 그 선택지의 value 를, "
    "직접 입력은 사용자의 말을 넣는다. null 은 답을 지운다. 제출한 질문지에는 쓸 수 없다.",
    program="questionnaire",
    mutates=True,
)
def fill_answers(args: FillIn, ctx: ToolContext) -> FillOut:
    try:
        before = dict(store.get(ctx.session, args.questionnaire_id).answers_json)
    except store.NotFound:
        raise ToolError(NOT_FOUND_MESSAGE) from None
    try:
        for item in args.answers:
            store.answer(ctx.session, args.questionnaire_id, item.question_id, item.value)
    except store.QuestionnaireError as e:
        record = store.get(ctx.session, args.questionnaire_id)
        if record.answers_json != before:  # 앞에서 넣은 답을 되돌린다
            record.answers_json = before
            ctx.session.commit()
        raise ToolError(e.message) from None
    count = len(args.answers)
    ctx.emit(AgentEvent("card", {"kind": "answers_filled", "questionnaire_id": args.questionnaire_id, "count": count}))
    return FillOut(filled=count)
