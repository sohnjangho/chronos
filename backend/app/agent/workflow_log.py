"""워크플로우 실행 기록 쓰기: 도구를 하나라도 부른 턴 = workflow_runs 한 줄, 도구 호출 하나 = workflow_steps 한 줄.

글만 답한 턴은 기록하지 않는다(실행 줄은 첫 도구 호출 때 만든다). commit 은 부르는 쪽(루프)이 한다.
화면에 보낼 단계 목록은 메모리에 따로 들고 있어, 되돌리기(rollback) 뒤에도 DB 를 다시 읽지 않는다.
"""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agent.events import AgentEvent, json_safe
from app.store.tables import WorkflowRun, WorkflowStep
from app.tools.registry import ToolResult

TITLE_LIMIT = 40
WHY_LIMIT = 200


class WorkflowLog:
    def __init__(self, session: Session, chat_session_id: int, *, title: str, request: str) -> None:
        self.session = session
        self.chat_session_id = chat_session_id
        self.title = title[:TITLE_LIMIT]
        self.request = request
        self.run_id: int | None = None
        self.status = "running"
        self._run: WorkflowRun | None = None
        self._steps: list[WorkflowStep] = []
        self._rows: list[dict] = []  # 화면에 보낼 {n, tool, program, status}

    def step_started(
        self, *, tool: str, program: str | None, why: str, arguments: str, model: str, tokens: int, cost: float | None
    ) -> int:
        """단계를 연다(status running). 첫 단계면 실행 줄도 만든다. 단계 번호(1부터)를 돌려준다."""
        if self._run is None:
            self._run = WorkflowRun(
                chat_session_id=self.chat_session_id, title=self.title, request=self.request, status="running"
            )
            self.session.add(self._run)
            self.session.flush()
            self.run_id = self._run.id
        n = len(self._steps) + 1
        step = WorkflowStep(
            run_id=self.run_id, n=n, tool=tool, program=program, why=why.strip()[:WHY_LIMIT], status="running",
            input_json=arguments, model=model, tokens=tokens, cost=cost,
        )
        self.session.add(step)
        self._steps.append(step)
        self._rows.append({"n": n, "tool": tool, "program": program, "status": "running"})
        return n

    def step_finished(self, n: int, result: ToolResult, stopped: bool = False) -> None:
        """단계를 닫는다: done(성공) 또는 failed(output 은 {"error": …}).

        stopped 면(도구가 도는 동안 멈춤을 눌렀으면) 성공한 결과도 stopped 로 둔다. 출력은 그대로 저장한다.
        """
        status = ("stopped" if stopped else "done") if result.ok else "failed"
        output = result.output if result.ok else {"error": result.error}
        step = self._steps[n - 1]
        step.status = status
        step.output_json = json.dumps(json_safe(output), ensure_ascii=False)
        step.ms = result.ms
        self._rows[n - 1]["status"] = status

    def finish(self, status: str, *, tokens: int, cost: float | None) -> None:
        """실행을 닫는다. 아직 running 인 단계는 stopped(멈춤) 또는 failed 로. 실행 줄이 없으면 아무것도 안 한다."""
        if self._run is None:
            return
        for step, row in zip(self._steps, self._rows, strict=True):
            if row["status"] == "running":
                row["status"] = step.status = "stopped" if status == "stopped" else "failed"
        self.status = status
        self._run.status = status
        self._run.ended_at = datetime.now(UTC)
        self._run.tokens = tokens
        self._run.cost = cost

    def event(self) -> AgentEvent:
        """workflow 사건: {run_id, status(실행), steps: [{n, tool, program, status}]}."""
        return AgentEvent("workflow", {"run_id": self.run_id, "status": self.status, "steps": [dict(r) for r in self._rows]})
