"""워크플로우 실행 기록 읽기. 쓰기는 에이전트 루프(app/agent/workflow_log.py)가 한다."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.store.schedules import NotFound
from app.store.tables import ChatSession, WorkflowRun, WorkflowStep

__all__ = ["NotFound", "get_run", "list_runs", "owner_of", "step_counts", "steps_of"]


def list_runs(session: Session, *, user_id: int | None) -> list[WorkflowRun]:
    """실행 기록, 새것부터. user_id 를 주면 그 사용자의 대화에서 나온 것만."""
    query = select(WorkflowRun).order_by(WorkflowRun.id.desc())
    if user_id is not None:
        query = query.join(ChatSession, ChatSession.id == WorkflowRun.chat_session_id).where(
            ChatSession.user_id == user_id
        )
    return list(session.scalars(query))


def get_run(session: Session, run_id: int) -> WorkflowRun:
    """실행 기록 한 줄. 없으면 NotFound."""
    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFound(run_id)
    return run


def owner_of(session: Session, run: WorkflowRun) -> int | None:
    """그 실행을 낸 대화의 사용자 id."""
    return session.scalar(select(ChatSession.user_id).where(ChatSession.id == run.chat_session_id))


def steps_of(session: Session, run_id: int) -> list[WorkflowStep]:
    """단계, n 순."""
    return list(session.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run_id).order_by(WorkflowStep.n)))


def step_counts(session: Session, run_ids: list[int]) -> dict[int, int]:
    """실행마다 단계 수."""
    if not run_ids:
        return {}
    query = (
        select(WorkflowStep.run_id, func.count())
        .where(WorkflowStep.run_id.in_(run_ids))
        .group_by(WorkflowStep.run_id)
    )
    return {run_id: n for run_id, n in session.execute(query)}
