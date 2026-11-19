"""워크플로우 화면: 실행 기록 목록과 단계.

일반 사용자는 자기 대화에서 나온 실행만 보고, 단계 입출력은 2,000자까지만 본다. 관리자는 모두 본다.
"""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.workflow.schemas import RunDetail, RunOut, StepOut
from app.store import workflows as store
from app.store.tables import User, WorkflowRun, WorkflowStep
from app.store.timeutil import as_utc

IO_LIMIT = 2000
NOT_FOUND_MESSAGE = "실행 기록을 찾을 수 없습니다."


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _run_out(run: WorkflowRun, step_count: int) -> RunOut:
    return RunOut(
        id=run.id, chat_session_id=run.chat_session_id, title=run.title, status=run.status,
        started_at=as_utc(run.started_at), ended_at=as_utc(run.ended_at) if run.ended_at else None,
        tokens=run.tokens, cost=run.cost, step_count=step_count,
    )


def _cut(text: str | None, cut: bool) -> str | None:
    return text[:IO_LIMIT] if cut and text is not None else text


def _step_out(step: WorkflowStep, cut: bool) -> StepOut:
    return StepOut(
        n=step.n, tool=step.tool, program=step.program, why=step.why, status=step.status,
        input_json=_cut(step.input_json, cut), output_json=_cut(step.output_json, cut),
        ms=step.ms, model=step.model, tokens=step.tokens, cost=step.cost,
    )


def list_runs(session: Session, user: User) -> list[RunOut]:
    runs = store.list_runs(session, user_id=None if _is_admin(user) else user.id)
    counts = store.step_counts(session, [r.id for r in runs])
    return [_run_out(r, counts.get(r.id, 0)) for r in runs]


def get_run(session: Session, user: User, run_id: int) -> RunDetail:
    try:
        run = store.get_run(session, run_id)
    except store.NotFound:
        run = None
    if run is None or (not _is_admin(user) and store.owner_of(session, run) != user.id):
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    steps = store.steps_of(session, run_id)
    cut = not _is_admin(user)
    return RunDetail(
        **_run_out(run, len(steps)).model_dump(), request=run.request, steps=[_step_out(s, cut) for s in steps]
    )
