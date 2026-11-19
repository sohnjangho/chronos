from datetime import datetime

from pydantic import BaseModel


class RunOut(BaseModel):
    id: int
    chat_session_id: int
    title: str  # 요청 40자(질문지로 시작한 턴은 "질문지 답")
    status: str  # running | done | failed | stopped
    started_at: datetime
    ended_at: datetime | None
    tokens: int  # 턴의 LLM 입력 + 출력 토큰(도구 안에서 부른 LLM 은 빠짐)
    cost: float | None
    step_count: int


class StepOut(BaseModel):
    n: int
    tool: str
    program: str | None
    why: str  # 호출 앞의 에이전트 글(200자)
    status: str  # running | done | failed | stopped
    input_json: str  # JSON 글. 관리자가 아니면 2,000자에서 자름
    output_json: str | None  # JSON 글(실패면 {"error": …}). 관리자가 아니면 2,000자에서 자름
    ms: int | None
    model: str | None
    tokens: int
    cost: float | None


class RunDetail(RunOut):
    request: str
    steps: list[StepOut]
