"""일정 생성 도구(generate.extract_conditions · generate.run)."""

from app.llm.client import LlmClient
from app.tools.context import ToolContext


def client_for(ctx: ToolContext) -> LlmClient:
    """도구가 쓰는 LLM. 시험은 이 함수를 바꿔 가짜 Liner 를 넣는다(도구는 `package.client_for` 로 부른다)."""
    return LlmClient(ctx.session)
