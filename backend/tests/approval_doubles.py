"""승인 시험용 자료: 작은 일정(A → B → D, A → C → D)·조건 dict·초안 만들기·도구 부르기 도우미."""

import asyncio

from app.agent.events import AgentEvent
from app.core.model import Activity, Relation, Resource, Schedule
from app.harness.assemble import assemble
from app.harness.checks import CheckReport
from app.harness.conditions import Condition
from app.store.drafts import create_draft
from app.store.tables import User
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.registry import ToolResult
from tests.schedules import make, task

CRANE = Resource("crane", "타워크레인", "대", 1)
OK = CheckReport(passed=[], violations=[], uncheckable=[])


def net(b: int = 4, c: int = 1, *, extra: tuple[Activity, ...] = (), extra_rels: tuple[Relation, ...] = (),
        crane_on: tuple[str, ...] = ()) -> Schedule:
    """A(3) → B(b) → D(1), A → C(c) → D. 2027-03-01(월) 시작, 주 5일, 타워크레인 1대.

    b=4, c=1 이면 A 3/1~3/3, B 3/4~3/9, C 3/4, D 3/10. 준공 3/10, 크리티컬 A·B·D, C 는 여유 3일.
    crane_on 에 든 액티비티는 타워크레인을 쓴다.
    """
    acts = [task(i, od, resources=("crane",) if i in crane_on else ()) for i, od in (("A", 3), ("B", b), ("C", c))]
    acts += [task("D", 1), *extra]
    rels = [Relation("A", "B"), Relation("A", "C"), Relation("B", "D"), Relation("C", "D"), *extra_rels]
    return make(acts, rels, [CRANE])


def crane(capacity: int) -> dict:
    return {"id": "in.resource_cap.crane", "layer": "input", "kind": "resource_cap",
            "params": {"resource_id": "crane", "capacity": capacity}, "text": f"타워크레인 {capacity}대",
            "source": "프롬프트"}


def finish_by(day: str) -> dict:
    return {"id": "in.finish_by", "layer": "input", "kind": "finish_by", "params": {"date": day},
            "text": f"준공 {day}까지", "source": "프롬프트"}


def note_only(text: str = "현장 사무실은 남쪽") -> dict:
    return {"id": "in.text_only", "layer": "input", "kind": "text_only", "params": {}, "text": text,
            "source": "프롬프트"}


def assembled(*stored: dict) -> list[dict]:
    """초안이 저장하는 모양: 기본 규칙 + 받은 조건을 조립한 목록(dict)."""
    return [c.to_dict() for c in assemble([], [], [Condition.from_dict(d) for d in stored])]


def make_draft(session, schedule: Schedule | None = None, conditions: tuple[dict, ...] = (),
               chat_session_id: int | None = None) -> int:
    return create_draft(
        session, chat_session_id=chat_session_id, domain="construction", level="L3",
        schedule=schedule or net(), conditions=[Condition.from_dict(d) for d in assembled(*conditions)],
        report=OK, assumptions=[],
    )


def submit(session, user: User, args: dict, *, chat_id: int | None = None) -> tuple[ToolResult, list[AgentEvent]]:
    """sync 시험에서 out.submit_change 를 부른다. 루프처럼 성공이면 commit, 실패면 rollback."""
    events: list[AgentEvent] = []
    ctx = ToolContext(session=session, user=user, schedule_id=None, emit=events.append, chat_session_id=chat_id)
    result = asyncio.run(registry.call("out.submit_change", args, ctx))
    if result.ok:
        session.commit()
    else:
        session.rollback()
    return result, events
