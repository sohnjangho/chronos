"""개발 콘솔 차단 시험이 쓰는 임시 DB 와 대본 LLM: 운영 DB 와 따로인 임시 SQLite 에서 진짜 코드를 네트워크 없이 돌린다."""

import asyncio
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.agent import loop
from app.agent.context import UiContext
from app.llm.client import LlmClient
from app.llm.names import to_llm_name
from app.security.crypto import encrypt
from app.store import settings as settings_store
from app.store.tables import (
    Base,
    ChatSession,
    LlmConnection,
    User,
    WorkflowRun,
    WorkflowStep,
)

LOOP_TOOL = "schedule.read"  # 일정 없는 대화에서 부르면 늘 실패하는 읽기 도구("대상 일정이 없습니다.")
HARNESS_CHAT_ID = 2**62  # 임시 DB 의 대화 id — 운영 대화의 멈춤 표시(app.agent.turns)와 겹치지 않게


class ScriptedLiner:
    """네트워크 없이 대본대로 답하는 가짜 Liner. 앞의 tool_turns 번은 tool 을 arguments(JSON 글)로 부르고, 그 뒤는 글로
    답한다(루프의 한도가 빠져도 시험이 끝나게). replies 를 주면 그 답 글(JSON)을 차례로 낸다(도구 안 생성 호출)."""

    def __init__(self, tool_turns: int = 0, *, tool: str = LOOP_TOOL, arguments: str = "{}",
                 replies: list[str] | None = None) -> None:
        self.tool_turns, self.tool, self.arguments = tool_turns, tool, arguments
        self.replies = list(replies or [])
        self.bodies: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        n = len(self.bodies)
        message: dict[str, Any] = {"role": "assistant", "content": "하네스 시험을 마칩니다."}
        if self.replies:
            message["content"] = self.replies[min(n, len(self.replies)) - 1]
        elif n <= self.tool_turns:
            call = {"id": f"call_{n}", "type": "function",
                    "function": {"name": to_llm_name(self.tool), "arguments": self.arguments}}
            message = {"role": "assistant", "content": None, "tool_calls": [call]}
        body = {"model": "harness-script", "choices": [{"index": 0, "message": message}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
        return httpx.Response(200, json=body)


@contextmanager
def temp_session(cfg: dict[str, Any] | None = None) -> Iterator[tuple[Session, User]]:
    """임시 SQLite 세션과 관리자 한 명. cfg 를 주면 에이전트 설정을 옮긴다. 나가면 파일째 지운다."""
    with tempfile.TemporaryDirectory(prefix="chronos-harness-") as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'harness.db'}")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as s:
                if cfg is not None:
                    settings_store.set_agent_config(s, cfg)
                user = User(login_id="harness", name="하네스 시험", role="admin", password_hash="-")
                s.add(user)
                s.flush()
                yield s, user
        finally:
            engine.dispose()


def add_llm_connection(s: Session) -> None:
    """대본 LLM 이 받을 기본 연결(키는 보내지 않는다 — transport 가 가짜)."""
    s.add(LlmConnection(name="하네스 대본", provider="liner", base_url="https://harness.invalid",
                        secret_ciphertext=encrypt("harness-not-sent"), secret_last4="sent", is_default=True, status="ok"))
    s.flush()


async def _drain(events: Any) -> list[Any]:
    return [e async for e in events]


def run_isolated_turn(cfg: dict[str, Any], llm: ScriptedLiner, text: str = "하네스 차단 시험") -> dict[str, Any]:
    """임시 DB 에 지금 에이전트 설정을 옮기고 loop.run_turn 한 턴(text)을 끝까지 돌려 관측값을 돌려준다."""
    with temp_session(cfg) as (s, user):
        add_llm_connection(s)
        s.add(ChatSession(id=HARNESS_CHAT_ID, user_id=user.id, title=""))
        s.commit()
        rollbacks = [0]
        real_rollback = s.rollback

        def counted_rollback() -> None:  # 루프가 실패한 도구 뒤에 부르는 session.rollback 을 센다
            rollbacks[0] += 1
            real_rollback()

        s.rollback = counted_rollback  # type: ignore[method-assign]
        client = LlmClient(s, transport=httpx.MockTransport(llm.handle))
        turn = loop.run_turn(s, user, HARNESS_CHAT_ID, text, UiContext(), llm=client)
        events = asyncio.run(_drain(turn))
        error = next((e.data for e in events if e.type == "error"), None)
        return {
            "rollback_calls": rollbacks[0],
            "run_status": s.scalar(select(WorkflowRun.status)),
            "step_statuses": list(s.scalars(select(WorkflowStep.status).order_by(WorkflowStep.n))),
            "step_inputs": list(s.scalars(select(WorkflowStep.input_json).order_by(WorkflowStep.n))),
            "step_count": s.scalar(select(func.count()).select_from(WorkflowStep)),
            "error": error,
        }
