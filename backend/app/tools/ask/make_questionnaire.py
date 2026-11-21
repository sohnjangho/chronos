"""ask.questionnaire — 에이전트가 만든 질문을 사용자에게 띄운다.

질문이 두 개 이하면 대화 안의 작은 카드(card 사건)로, 세 개 이상이면 질문지를 만들어 창을 연다.
답하지 않은 질문은 질문마다 적은 가정(assumption)으로 넘어간다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.agent.events import AgentEvent
from app.domains.loader import is_valid_domain_id
from app.store import questionnaires as store
from app.store.questionnaires import Prefilled, Question
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

CARD_LIMIT = 2  # 이 수 이하면 대화 안의 카드로 묻는다


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["generate", "delay", "report", "recovery", "clarify"] = Field(
        description="무엇을 하려고 묻는가: 일정 만들기·지연 등록·보고서·만회 계획·확인"
    )
    title: str = Field(min_length=1, max_length=60, description="질문지 제목")
    domain: str | None = Field(
        default=None,
        description="분야 id (예: construction, manufacturing, rnd, permitting, procurement, general 등). 모르면 null",
    )
    level: Literal["L1", "L2", "L3", "L4", "L5"] | None = Field(default=None, description="정밀도. 모르면 null")
    questions: list[Question] = Field(min_length=1, max_length=15, description="물을 질문 1~15개")
    prefilled: list[Prefilled] = Field(
        default_factory=list, max_length=30, description="이미 채운 정보와 출처(질문지 위에 보인다)"
    )
    round: Literal[1, 2] = Field(default=1, description="몇 번째 묻는가(최대 두 번)")


class CardOut(BaseModel):
    mode: Literal["card"] = "card"
    questions: list[Question]


class OpenedOut(BaseModel):
    mode: Literal["questionnaire"] = "questionnaire"
    id: int
    total: int


class AskOut(RootModel[CardOut | OpenedOut]):
    """card 면 {mode, questions}, 질문지면 {mode, id, total}."""


def _problems(args: AskIn) -> list[str]:
    problems = []
    if args.domain is not None and not is_valid_domain_id(args.domain):
        problems.append(f"올바르지 않은 분야입니다: {args.domain}")
    if args.purpose == "generate" and args.domain is None and len(args.questions) > CARD_LIMIT:
        problems.append(
            "분야(주제)가 아직 확정되지 않았습니다(domain=null). 먼저 1~2개 질문(카드 모드)으로 어떤 일정인지 확인한 뒤, 다음 턴에 해당 분야에 맞춘 질문지를 여세요."
        )
    return problems + store.question_problems(args.questions)


@tool(
    "ask.questionnaire",
    "모자란 정보를 사용자에게 묻는다. 질문은 직접 만든다: 질문 문구, 묻는 이유, 선택지 0~4개"
    "(권하는 것 하나에 recommended), 직접 입력 허용 여부, 답하지 않으면 할 가정(assumption). "
    "같은 묶음(group)끼리 한 탭에 모인다. 질문이 두 개 이하면 대화 안의 카드로, 세 개 이상이면 질문지 창을 연다. "
    "필수 질문은 없다. 답하지 않은 질문은 적어 둔 가정대로 진행하고 결과에 '가정한 것'으로 남긴다.",
    program="questionnaire",
)
def make_questionnaire(args: AskIn, ctx: ToolContext) -> AskOut:
    problems = _problems(args)
    if problems:
        raise ToolError(" / ".join(problems))
    if len(args.questions) <= CARD_LIMIT:
        questions = [q.model_dump(mode="json") for q in args.questions]
        ctx.emit(AgentEvent("card", {"kind": "mini_questions", "title": args.title, "questions": questions}))
        return AskOut(CardOut(questions=args.questions))
    qid = store.create(
        ctx.session,
        purpose=args.purpose,
        title=args.title,
        questions=args.questions,
        prefilled=args.prefilled,
        domain=args.domain,
        level=args.level,
        chat_session_id=ctx.chat_session_id,
        round=args.round,
    )
    ctx.emit(AgentEvent("questionnaire", {"id": qid}))
    ctx.emit(AgentEvent("open_window", {"program": "questionnaire", "params": {"id": str(qid)}}))
    return AskOut(OpenedOut(id=qid, total=len(args.questions)))
