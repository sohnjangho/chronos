"""대화의 LLM 사용량 읽기(llm_calls 표). 기록은 app.llm.client 가 호출마다 한 줄씩 한다.

에이전트 턴의 사용량 = 턴을 시작할 때의 마지막 llm_calls.id 뒤에 생긴, 그 대화(chat_session_id)의 줄 합.
루프가 부른 호출과 도구 안에서 부른 호출(생성 도구 등)이 모두 들어간다. 실패한 호출도 한 번으로 센다(토큰 0).
"""

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.store.tables import LlmCall


@dataclass(frozen=True)
class UsageSum:
    input_tokens: int
    output_tokens: int
    cost: float | None  # 비용을 알린 호출이 없으면 None(가격표 어림은 넣지 않는다)
    calls: int


def last_call_id(session: Session) -> int:
    """지금 llm_calls 의 가장 큰 id(없으면 0)."""
    return session.scalar(select(func.max(LlmCall.id))) or 0


def usage_since(session: Session, chat_session_id: int, after_id: int) -> UsageSum:
    """그 대화에서 after_id 뒤에 생긴 호출의 합."""
    query = select(
        func.coalesce(func.sum(LlmCall.input_tokens), 0),
        func.coalesce(func.sum(LlmCall.output_tokens), 0),
        func.sum(case((LlmCall.cost_estimated.is_(True), None), else_=LlmCall.cost)),
        func.count(),
    ).where(LlmCall.chat_session_id == chat_session_id, LlmCall.id > after_id)
    input_tokens, output_tokens, cost, calls = session.execute(query).one()
    return UsageSum(int(input_tokens), int(output_tokens), cost, int(calls))
