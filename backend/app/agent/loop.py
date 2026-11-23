"""에이전트 루프: 대화 메시지 하나를 받아 LLM(normal, 그림 턴이면 vision — image_turn)과 도구를 오가며(ReAct) 사건을 흘려보낸다.

한 턴의 흐름: 사용자 메시지 저장 → 메시지 조립(context.build_context) → LLM 에 도구 목록과 함께 묻기 →
도구 호출이 오면 단계마다 workflow·tool_start → 도구 실행(도구가 내는 사건은 바로 흘려보냄) → tool_end·workflow
→ 결과를 붙여 다시 묻기 → 도구 호출이 없으면 text 로 끝. 끝에는 [workflow] [usage] [error] done.
LLM 이나 도구를 기다리는 동안 PING_INTERVAL_S 마다 ping 을 낸다(연결 유지).

트랜잭션: LLM 을 부르기 전과 도구를 부르기 전에 늘 commit 한다(쓰기를 쥔 채 네트워크를 기다리지 않는다).
실패한 도구가 남긴 쓰기는 버린다(rollback). 도구가 낸 card·questionnaire·approval 사건은 도구가 끝난 뒤
같은 commit 에서 event 메시지로 저장한다(도구가 LLM 을 기다리는 동안 쓰지 않는다).
멈춤은 app.agent.turns 의 표시를 단계 사이에서 보고, 도구에도 ToolContext.stop_requested 로 넘긴다.
사용량은 턴 동안 이 대화에 생긴 llm_calls 줄의 합이다(도구 안의 LLM 호출 포함).
"""

import asyncio
import json
import logging
import math
import re
import time
import traceback
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import aclosing
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agent import image_turn, turns
from app.agent.context import (
    UiContext,
    arguments_text,
    build_context,
    result_text,
    wire,
)
from app.agent.events import AgentEvent, json_safe
from app.agent.trace import TraceLog, context_parts
from app.agent.workflow_log import TITLE_LIMIT, WorkflowLog
from app.llm import assignments
from app.llm.client import LlmClient, LlmFailed, LlmNotReady, LlmReply, Usage
from app.store import approvals, chats, questionnaires, skills
from app.store import settings as settings_store
from app.store.llm_usage import UsageSum, last_call_id, usage_since
from app.store.tables import User
from app.tools import registry
from app.tools.context import ToolContext

logger = logging.getLogger(__name__)

MAX_STEPS = 12  # 한 턴의 LLM 호출 수 한도
PING_INTERVAL_S = 15.0  # 이만큼 아무 사건이 없으면 ping
SAVED_EVENTS = frozenset({"card", "questionnaire", "approval"})  # event 메시지로 저장하는 도구 사건
QUESTIONNAIRE_TITLE = "질문지 답"
REJECTED_TITLE = "승인 거부 뒤 다시 짜기"
_TITLES = {"questionnaire_submitted": QUESTIONNAIRE_TITLE, "approval_rejected": REJECTED_TITLE}  # 글이 아닌 시작
PING = AgentEvent("ping", {})
CUT_NOTE = " (답이 길어 잘렸습니다)"  # max_tokens 에 걸려 잘린 글 답 끝에 붙인다
_MAX_SQL_INT = 2**63 - 1
# 공정표 카드의 [일정 초안으로 가져오기]가 보내는 글(frontend ScheduleFileCard.tsx). 이 턴의 그 파일 schedule.import 는
# 모델이 confirmed 를 빼도 가져오기로 부른다(I1). 한 턴에 같은 파일은 한 번만 가져오고, 같은 확인은 한 번만 한다(I1·I2).
IMPORT_BUTTON = re.compile(r"네, 확인했으니 이 파일\(#(\d+)\)을 일정 초안으로 가져와 줘\.?")
IMPORT_AGAIN = "이번 턴에 이 파일(#{})은 이미 가져왔습니다. 다시 부르지 말고 받은 결과를 사용자에게 알리세요."
CHECK_AGAIN = (
    "이번 턴에 이 파일(#{})은 이미 확인해 결과를 받았습니다(공정표면 요약 카드도 떴습니다). 다시 부르지 말고 그 결과를 "
    "사용자에게 말한 뒤 턴을 끝내세요 — 가져오기는 사용자가 [일정 초안으로 가져오기]를 누르거나 가져오라고 한 뒤입니다."
)


@dataclass(frozen=True)
class _Outcome:
    status: str  # workflow_runs.status: done | failed | stopped
    error: dict | None = None  # error 사건의 data


DONE = _Outcome("done")
STOPPED = _Outcome("stopped", {"code": "stopped", "message": "중단했습니다."})
STEP_LIMIT = _Outcome("failed", {"code": "step_limit", "message": "단계 한도에 닿아 멈췄습니다."})
NOT_READY = _Outcome("failed", {
    "code": "llm_not_ready",
    "message": "LLM 연결이 필요합니다. 설정에서 연결해 주세요.",
    "action": {"open": "settings", "params": {"section": "llm"}},
})
VISION_NOT_READY = _Outcome("failed", {**NOT_READY.error, "message": image_turn.NOT_READY_MESSAGE})  # 그림 턴
INTERNAL = _Outcome("failed", {"code": "internal_error", "message": "처리 중 문제가 생겼습니다."})


def _llm_failed(e: LlmFailed) -> _Outcome:
    return _Outcome("failed", {"code": "llm_failed", "message": e.error.message, "reason": e.error.code})


def _log_failure(what: str, chat_id: int, exc: BaseException) -> None:
    """예외 글에는 SQL 값·대화 글이 들어 있을 수 있어 종류와 위치(추적의 코드 줄)만 남긴다."""
    where = "".join(traceback.format_tb(exc.__traceback__))
    logger.error("%s: chat=%s (%s)\n%s", what, chat_id, type(exc).__name__, where)


def _count(n: int) -> int:
    return min(max(n, 0), _MAX_SQL_INT)


def _money(cost: float | None) -> float | None:
    return cost if cost is not None and math.isfinite(cost) else None


def _tokens(usage: Usage) -> int:
    return _count(_count(usage.input_tokens) + _count(usage.output_tokens))


def _storable(data: dict) -> dict:
    """DB JSON 칸에 넣을 수 있는 사본(서로게이트 정리, JSON 이 아닌 값은 글로)."""
    return json.loads(json.dumps(json_safe(data), ensure_ascii=False, default=str))


@dataclass(frozen=True)
class _Call:
    id: str
    name: str
    arguments: dict | None
    arguments_text: str  # LLM 에 다시 보낼 인자 글


def default_llm(session: Session) -> LlmClient:
    """루프가 쓰는 LLM. 시험은 이 함수를 바꿔 가짜 Liner 를 넣는다(루프는 `loop.default_llm` 으로 부른다)."""
    return LlmClient(session)


async def _next_event(task: asyncio.Future, queue: asyncio.Queue, interval: float) -> AgentEvent | None:
    """task 를 기다리며 큐에 들어온 사건 하나를 돌려준다. interval 초 동안 아무것도 없으면 PING,
    task 가 끝났고 남은 사건이 없으면 None. task 는 취소하지 않는다."""
    if queue.empty() and not task.done():
        getter = asyncio.ensure_future(queue.get())
        try:
            await asyncio.wait({task, getter}, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
        finally:
            getter.cancel()  # 이미 끝났으면 아무 일도 없다(꺼내지 못한 사건은 큐에 남는다)
        if getter.done() and not getter.cancelled():
            return getter.result()
        if queue.empty() and not task.done():
            return PING
    return None if queue.empty() else queue.get_nowait()


def _user_content(session: Session, text: str | None, questionnaire_id: int | None, approval_id: int | None) -> dict:
    if approval_id is not None:  # 거부하고 다시 짜게 한 승인 건(대화 API 가 확인했다)
        row = approvals.get(session, approval_id)
        return {"kind": "approval_rejected", "approval_id": approval_id, "title": row.title, "note": row.note}
    if questionnaire_id is None:
        return {"kind": "text", "text": json_safe(text or "")}
    result = questionnaires.results(questionnaires.get(session, questionnaire_id))
    return {
        "kind": "questionnaire_submitted",
        "questionnaire_id": questionnaire_id,
        "answers": [a.model_dump() for a in result.answers],
        "assumed": [a.model_dump() for a in result.assumed],
    }


class _Turn:
    def __init__(self, session: Session, user: User, chat_session_id: int, ui: UiContext, llm: LlmClient) -> None:
        self.session = session
        self.user = user
        self.chat_id = chat_session_id
        self.ui = ui
        self.llm = llm
        self.outcome = DONE
        self.messages: list[dict] = []
        self.programs = {s.name: s.program for s in registry.list_tools(enabled_only=False)}
        self.schedule_id: int | None = None
        self.log: WorkflowLog | None = None
        self.calls_before: int | None = None  # 턴을 시작할 때의 마지막 llm_calls.id
        self.usage: UsageSum | None = None
        self.task: asyncio.Future | None = None  # 지금 기다리는 LLM 호출 또는 도구
        self.queue: asyncio.Queue = asyncio.Queue()
        self.collected: list[AgentEvent] = []  # 이번 도구가 낸, 저장할 사건
        self.step_n = 0
        self.calls_seen = 0
        self.trace: TraceLog | None = None  # 실행 추적(app.agent.trace)
        self.llm_ev, self.llm_t0, self.last_text = None, 0.0, ""  # 지금 llm 사건·그 시작·마지막 답 글
        self.chat_model: assignments.Assignment | None = None  # 이 대화에서 고른 모델(대화 호출에만, 설계 5-5)
        self.vision = image_turn.Vision()  # 그림 턴: 그림 읽기(vision) 모델·image_url (app.agent.image_turn)
        self.max_steps_cfg = MAX_STEPS
        self.tool_output_limit = 4000
        self.history_limit = 30
        self.enable_skill_match = True
        self.enable_self_reflection = True
        self.asked_questionnaire = False
        self.waiting_for_user = False
        self.import_file: str | None = None  # 이 턴이 가져오기 단추로 온 파일 id(IMPORT_BUTTON)
        self.import_seen: set[tuple] = set()  # 이 턴에 성공한 schedule.import: ("checked", 파일, 시트) | ("imported", 파일)
        self.refused: str | None = None  # 지금 도구를 실행하지 않은 까닭(같은 가져오기·확인 되풀이)

    # ── 시작·끝 ──

    def begin(self, text: str | None, questionnaire_id: int | None, approval_id: int | None,
              file_ids: Sequence[int] = ()) -> None:
        """사용자 메시지를 저장하고(대화 제목·일정·붙인 파일도) commit 한 뒤 LLM 에 보낼 메시지를 만든다."""
        cfg = settings_store.get_agent_config(self.session)
        self.max_steps_cfg = int(cfg["max_steps"])
        self.tool_output_limit = int(cfg["tool_output_limit"])
        self.history_limit = int(cfg["history_limit"])
        self.enable_skill_match = bool(cfg["enable_skill_match"])
        self.enable_self_reflection = bool(cfg["enable_self_reflection"])
        self.calls_before = last_call_id(self.session)
        button = IMPORT_BUTTON.fullmatch((text or "").strip())
        self.import_file = button.group(1) if button else None
        chat = chats.get_chat(self.session, self.chat_id)
        picked = image_turn.picked(self.session, file_ids)
        content = _user_content(self.session, text, questionnaire_id, approval_id) | image_turn.refs(picked)
        title = _TITLES.get(content["kind"]) or content["text"].strip()[:TITLE_LIMIT]
        if not chat.title:
            chat.title = title
        if self.ui.schedule_id is not None:
            chat.schedule_id = self.ui.schedule_id
        self.schedule_id = chat.schedule_id
        self.chat_model = assignments.chat_model(self.session, self.chat_id)
        request = wire("user", content)["content"]  # 모델이 읽는 글 그대로
        self.log = WorkflowLog(self.session, self.chat_id, title=title, request=request)
        message = chats.add_message(self.session, self.chat_id, "user", content)
        image_turn.attach(self.session, self.chat_id, picked)
        self.session.commit()
        self.trace = TraceLog(self.session, self.chat_id, message.id)
        ui = UiContext(self.ui.program, self.schedule_id, self.ui.selected_activity)
        self.messages = build_context(self.session, self.user, self.chat_id, ui, history_limit=self.history_limit)
        self.matched_skill = skills.match_skill(self.session, text or "") if self.enable_skill_match else None
        if self.matched_skill is not None and self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] += "\n\n" + skills.skill_prompt_block(self.matched_skill)
            skills.record_use(self.session, self.matched_skill.id)
        self.vision.start(self.messages, picked)
        tools = registry.as_llm_tools()
        parts = context_parts(self.session, self.user, self.chat_id, ui, tools, history_limit=self.history_limit)
        self.trace.context(parts, len(self.messages) - 1, len(tools))
        self.trace.skill(self.matched_skill)

    def close_log(self) -> None:
        """턴의 사용량(llm_calls 합)을 읽고 실행 기록을 닫는다."""
        if self.calls_before is not None:
            self.usage = usage_since(self.session, self.chat_id, self.calls_before)
        if self.log is not None:
            u = self.usage
            tokens = _count(u.input_tokens + u.output_tokens) if u else 0
            wf_status = "waiting" if self.outcome.status == "done" and self.waiting_for_user else self.outcome.status
            self.log.finish(wf_status, tokens=tokens, cost=_money(u.cost) if u else None)
        if self.trace is not None:
            self.trace.end(self.outcome.status, (self.outcome.error or {}).get("message", self.last_text))
        self.session.commit()

    def abort(self, outcome: _Outcome) -> None:
        """턴이 중간에 끊겼다(연결 끊김·취소·예상 못 한 오류): 기다리던 것을 멈추고, 남은 쓰기를 버리고, 기록을 닫는다.

        await 하지 않는다(취소 중에는 기다리는 곳마다 다시 취소된다).
        """
        self.cancel_task()
        self.outcome = outcome
        try:
            self.session.rollback()
            self.close_log()
        except Exception as exc:  # noqa: BLE001 — 기록을 닫지 못해도 원래 예외를 가리지 않는다(종류·위치만 남김)
            _log_failure("워크플로우 기록을 닫지 못했습니다", self.chat_id, exc)

    def final_events(self) -> list[AgentEvent]:
        events = [self.log.event()] if self.log is not None and self.log.run_id is not None else []
        if self.usage is not None and self.usage.calls:
            u = self.usage
            usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "cost": u.cost, "calls": u.calls}
            events.append(AgentEvent("usage", usage))
        if self.outcome.error is not None:
            events.append(AgentEvent("error", self.outcome.error))
        return [*events, AgentEvent("done", {})]

    # ── 단계 ──

    async def events(self, max_steps: int) -> AsyncIterator[AgentEvent]:
        try:
            if getattr(self, "matched_skill", None) is not None:
                yield AgentEvent("notice", {"text": f"저장된 스킬 「{self.matched_skill.name}」을 적용했습니다."})
            for _ in range(max_steps):
                if self.stopping():
                    return
                for event in self.vision.flush(self.session, self.messages):  # 끼울 그림·그림 읽기 안내
                    yield event
                while True:  # 그림을 보낸 호출이 거절되면 그림을 글로 바꿔 한 번 더(image_turn.Vision.fallback)
                    self.llm_ev = self.trace.llm_start(image_turn.for_trace(self.messages), self.vision.purpose)
                    self.session.commit()  # llm 사건(ms 없음)을 호출 전에 쓴다
                    self.llm_t0 = time.perf_counter()
                    with assignments.using_chat_model(self.chat_model):  # 이 호출 작업에만(도구 안 호출은 배정 그대로)
                        self.start(self.llm.chat(self.vision.purpose, self.messages, tools=registry.as_llm_tools(),
                                                 chat_session_id=self.chat_id))
                    while (event := await self.waiting()) is not None:
                        yield event
                    reply = self.reply()
                    if reply is not None or not self.vision.fallback(self.messages, self.outcome.error):
                        break
                    self.outcome = DONE
                    if self.stopping():
                        return
                if reply is None:
                    return
                text = json_safe(reply.text)
                if not reply.tool_calls:
                    if reply.finish_reason == "length":
                        text = f"{text}{CUT_NOTE}" if text else CUT_NOTE.strip()
                    self.answer(text)
                    if text:
                        yield AgentEvent("text", {"text": text})
                    return
                calls = self.record_calls(reply, text)
                if text:
                    yield AgentEvent("text", {"text": text})
                for call in calls:
                    if self.stopping():
                        return
                    for event in self.start_tool(call, reply, text):
                        yield event
                    self.refused = self._import_again(call)
                    if call.name == "ask.questionnaire" and self.asked_questionnaire:
                        self.start(self._reject_duplicate_questionnaire())
                    elif self.refused is not None:
                        self.start(self._refuse(self.refused))
                    else:
                        self.start(registry.call(call.name, call.arguments, self.tool_context()))
                    while (event := await self.waiting()) is not None:
                        yield event
                    for event in self.end_tool(call):
                        yield event
            self.outcome = STEP_LIMIT
        finally:
            self.cancel_task()

    def stopping(self) -> bool:
        if turns.stop_requested(self.chat_id):
            self.outcome = STOPPED
            return True
        return False

    def start(self, work: Coroutine) -> None:
        """LLM 호출이나 도구를 따로 돌린다(기다리는 동안 사건·ping 을 내보내려고)."""
        self.queue = asyncio.Queue()
        self.task = asyncio.ensure_future(work)

    async def waiting(self) -> AgentEvent | None:
        event = await _next_event(self.task, self.queue, PING_INTERVAL_S)
        if event is not None and event.type in SAVED_EVENTS:
            self.collected.append(event)
        return event

    def reply(self) -> LlmReply | None:
        """끝난 LLM 호출의 답. 부를 수 없었거나 실패했으면 outcome 을 정하고 None."""
        task, self.task = self.task, None
        answer = None
        try:
            answer = task.result()
        except LlmNotReady as e:
            self.outcome = VISION_NOT_READY if self.vision.on and e.reason == "no_connection" else NOT_READY
        except LlmFailed as e:
            self.outcome = _llm_failed(e)
        error = self.outcome.error["message"] if answer is None else None
        self.trace.llm_end(self.llm_ev, answer, error, int((time.perf_counter() - self.llm_t0) * 1000))
        return answer

    def tool_context(self) -> ToolContext:
        return ToolContext(
            session=self.session, user=self.user, schedule_id=self.schedule_id,
            emit=lambda event: self.queue.put_nowait(event), chat_session_id=self.chat_id,
            stop_requested=lambda: turns.stop_requested(self.chat_id),
        )

    def save(self, role: str, content: dict) -> None:
        """메시지를 저장 목록에 더하고 다음 요청 메시지에도 붙인다(commit 은 부르는 쪽)."""
        content = json_safe(content)
        chats.add_message(self.session, self.chat_id, role, content)
        self.messages.append(wire(role, content))

    def answer(self, text: str) -> None:
        self.last_text = text
        if text:
            self.save("assistant", {"kind": "text", "text": text})
            self.session.commit()

    def record_calls(self, reply: LlmReply, text: str) -> list[_Call]:
        calls = []
        for c in reply.tool_calls:
            self.calls_seen += 1
            arguments, text_args = json_safe(c.arguments), json_safe(arguments_text(c.arguments, c.raw_arguments))
            if self._button_import(json_safe(c.name), arguments):  # 단추로 온 가져오기(I1): 기록에도 실제로 부를 인자
                arguments = {**arguments, "confirmed": True}
                text_args = json.dumps(arguments, ensure_ascii=False)
            calls.append(_Call(json_safe(c.id) or f"call_{self.calls_seen}", json_safe(c.name), arguments, text_args))
        tool_calls = [{"id": c.id, "name": c.name, "arguments": c.arguments_text} for c in calls]
        self.save("assistant", {"kind": "tool_calls", "text": text, "tool_calls": tool_calls})
        self.session.commit()
        return calls

    def start_tool(self, call: _Call, reply: LlmReply, why: str) -> list[AgentEvent]:
        program = self.programs.get(call.name)
        self.step_n = self.log.step_started(
            tool=call.name, program=program, why=why, arguments=call.arguments_text,
            model=json_safe(reply.model), tokens=_tokens(reply.usage), cost=_money(reply.usage.cost),
        )
        self.trace.attach_run(self.log.run_id)
        self.session.commit()
        start = {"run_id": self.log.run_id, "n": self.step_n, "call_id": call.id, "tool": call.name,
                 "program": program, "arguments": call.arguments_text}
        return [self.log.event(), AgentEvent("tool_start", start)]

    def end_tool(self, call: _Call) -> list[AgentEvent]:
        """도구 결과를 기록한다: 단계 닫기, 모아 둔 사건을 event 메시지로, tool 메시지 — 한 번에 commit."""
        result = self.task.result()
        self.task = None
        result = self.vision.after_tool(call.name, result)  # 붙이지 않은 그림은 결과에 까닭(image_note)
        if not result.ok:
            self.session.rollback()  # 실패한 도구가 남긴 쓰기는 저장하지 않는다
        if result.ok and call.name in ("schedule.create_project", "out.submit_change") and isinstance(result.output, dict):
            created_sid = result.output.get("schedule_id")
            if isinstance(created_sid, int):
                self.schedule_id = created_sid
        if call.name == "ask.questionnaire" and result.ok:
            self.asked_questionnaire = True
            self.waiting_for_user = True
        elif call.name in ("out.submit_change", "scenario.submit", "rules.propose") and result.ok and isinstance(result.output, dict):
            applied = result.output.get("applied")
            if applied is False:
                self.waiting_for_user = True
            elif applied is True:
                self.waiting_for_user = False
        elif call.name in ("generate.run", "generate.extract_conditions", "schedule.create_project") and result.ok:
            self.waiting_for_user = False
        if call.name == "schedule.import" and result.ok and isinstance(call.arguments, dict) and isinstance(result.output, dict):
            fid = str(call.arguments.get("file_id"))
            checked = result.output.get("step") == "checked"
            self.import_seen.add(("checked", fid, call.arguments.get("sheet")) if checked else ("imported", fid))
        stopped = result.ok and turns.stop_requested(self.chat_id)  # 도는 동안 멈춤을 눌렀다
        self.log.step_finished(self.step_n, result, stopped)
        for event in self.collected:
            chats.add_message(self.session, self.chat_id, "event", _storable({"type": event.type, "data": event.data}))
        self.collected = []
        tool_content = result_text(result, limit=self.tool_output_limit)
        if not result.ok and self.enable_self_reflection:
            reflection = (
                "이번 턴에 이미 질문(카드 또는 질문지)을 보냈습니다. 도구를 더 호출하지 말고 사용자에게 답을 요청하며 턴을 마치세요."
                if call.name == "ask.questionnaire" and self.asked_questionnaire
                else self.refused or f"도구 `{call.name}` 실패 — 오류 원인을 확인해 인자를 고치거나 대안 도구를 사용하세요."
            )
            tool_content = json.dumps(
                {"error": json_safe(result.error) or "도구 실행에 실패했습니다.", "reflection": reflection},
                ensure_ascii=False,
            )
        self.save("tool", {"kind": "tool_result", "tool_call_id": call.id, "name": call.name, "ok": result.ok,
                           "content": tool_content})
        self.session.commit()
        end = {"run_id": self.log.run_id, "n": self.step_n, "call_id": call.id, "tool": call.name,
               "ok": result.ok, "ms": result.ms, "error": json_safe(result.error)}
        return [AgentEvent("tool_end", end), self.log.event()]

    async def _reject_duplicate_questionnaire(self) -> registry.ToolResult:
        return registry.ToolResult(
            ok=False,
            output=None,
            error="이번 턴에 이미 질문(카드 또는 질문지)을 보냈습니다. 사용자의 답을 기다린 뒤 다음 턴에 진행하세요.",
            ms=0,
        )

    def _button_import(self, name: str, arguments: object) -> bool:
        """가져오기 단추로 온 턴의 그 파일 schedule.import 인데 confirmed 가 true 가 아니다(I1)."""
        return (self.import_file is not None and name == "schedule.import" and isinstance(arguments, dict)
                and str(arguments.get("file_id")) == self.import_file and arguments.get("confirmed") is not True)

    def _import_again(self, call: _Call) -> str | None:
        """이 턴에 이미 가져온 파일을 다시 가져오거나 같은 확인을 다시 하면 실행하지 않을 까닭(I1·I2). 아니면 None."""
        if call.name != "schedule.import" or not isinstance(call.arguments, dict):
            return None
        fid = str(call.arguments.get("file_id"))
        if ("imported", fid) in self.import_seen:
            return IMPORT_AGAIN.format(fid)
        if call.arguments.get("confirmed") is not True and ("checked", fid, call.arguments.get("sheet")) in self.import_seen:
            return CHECK_AGAIN.format(fid)
        return None

    async def _refuse(self, why: str) -> registry.ToolResult:
        return registry.ToolResult(ok=False, output=None, error=why, ms=0)

    def cancel_task(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()


async def run_turn(
    session: Session,
    user: User,
    chat_session_id: int,
    text: str | None,
    ui: UiContext,
    *,
    llm: LlmClient | None = None,
    max_steps: int | None = None,
    questionnaire_id: int | None = None,
    approval_id: int | None = None,
    file_ids: Sequence[int] = (),
) -> AsyncIterator[AgentEvent]:
    """한 턴을 돌며 사건을 내보낸다. 마지막 사건은 늘 done({}).

    text·questionnaire_id(제출된 질문지의 답·가정으로 이어 가기)·approval_id(거부하고 다시 짜게 한 승인 건으로
    이어 가기) 가운데 하나를 준다. file_ids 는 text 와 함께 이번 메시지에 붙인 파일(그림이 있으면 그림 턴 — image_turn).
    대화가 이 사용자의 것인지, 질문지·승인 건이 맞는지, 이미 도는 턴이 있는지는 부르는 쪽(대화 API)이 확인한다.
    턴을 시작하다 실패해도 error(internal_error)·done 으로 끝난다.
    스트림이 닫히거나(연결 끊김) 취소되면 실행을 stopped 로 닫고 그대로 끝난다(더 내보내지 않는다).
    """
    turn = _Turn(session, user, chat_session_id, ui, llm or default_llm(session))
    try:
        turn.begin(text, questionnaire_id, approval_id, file_ids)
        steps = max_steps if max_steps is not None else turn.max_steps_cfg
        async with aclosing(turn.events(steps)) as events:
            async for event in events:
                yield event
        turn.close_log()
    except (GeneratorExit, asyncio.CancelledError):
        turn.abort(STOPPED)
        raise
    except Exception as exc:  # noqa: BLE001 — 예상 못 한 오류도 화면에 error·done 으로 끝을 알린다(종류·위치만 남김)
        _log_failure("에이전트 턴 실패", chat_session_id, exc)
        turn.abort(INTERNAL)
    for event in turn.final_events():
        yield event
