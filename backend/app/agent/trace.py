"""실행 추적 기록: 에이전트 턴 하나(turn_id = 그 턴의 사용자 메시지 id)의 사건을 trace_events 에 남긴다.

사건 kind: context(맥락 조립 — 재료마다 글자 수) · llm(루프의 모델 호출 — 보낸 메시지·답·모델·토큰·시간) ·
end(턴의 끝 상태). 도구 단계는 workflow_steps 에 있고(run_id 로 잇는다), 도구 안의 LLM 호출은 llm_calls 에 있다.

- 루프의 세션에 더하기만 한다. commit 은 루프가 한다. llm 사건은 ms 없이 먼저 더해 호출 전 commit 에 실린다
  (호출 중에도 다른 연결에서 보인다). 끝나면 llm_end 가 ms·답을 채운다.
- input_text = 보낸 메시지 JSON(메시지마다 content·도구 인자를 4,000자, 전체를 60,000자에서 자름).
  output_text = {"text": 답 글, "tool_calls": [{"id", "name", "arguments"}]} JSON.
- 키는 담지 않는다(키는 LlmClient 가 머리글로만 보낸다). UTF-8 로 쓸 수 없는 글자는 '?' 로 바꾼다.
- 기록하다 실패하면 경고(메서드 이름과 예외 종류)만 남기고 턴은 그대로 간다.
"""

import functools
import json
import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.agent import context
from app.agent.context import CUT_NOTE, UiContext, arguments_text
from app.domains.loader import levels_prompt
from app.llm.client import LlmReply
from app.store.chats import recent_messages
from app.store.tables import TraceEvent, User

logger = logging.getLogger(__name__)

CONTEXT_PARTS = ("지시문", "분야 지식", "정밀도", "지금 상황", "붙인 파일", "날짜 도우미", "대화", "도구 목록")
TEXT_LIMIT = 60_000  # input_text·output_text 전체 한도
MESSAGE_LIMIT = 4_000  # 메시지 하나의 content(도구 인자도) 한도
CONTEXT_LABEL = "컨텍스트 조립"
_LABEL_LIMIT = 100
_MODEL_LIMIT = 200
_ERROR_LIMIT = 200
_MAX_SQL_INT = 2**63 - 1


def _safe(text: str) -> str:
    """UTF-8 로 쓸 수 없는 글자(짝 없는 서로게이트)를 '?' 로."""
    return text.encode("utf-8", "replace").decode("utf-8")


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + CUT_NOTE


def _count(n: int) -> int:
    return min(max(int(n), 0), _MAX_SQL_INT)


def _short(message: dict) -> dict:
    """메시지 하나의 사본: content 와 도구 호출 인자를 MESSAGE_LIMIT 에서 자른다."""
    out = dict(message)
    if isinstance(out.get("content"), str):
        out["content"] = _cut(out["content"], MESSAGE_LIMIT)
    if out.get("tool_calls"):
        out["tool_calls"] = [
            {**c, "function": {**c["function"], "arguments": _cut(str(c["function"].get("arguments", "")),
                                                                  MESSAGE_LIMIT)}}
            for c in out["tool_calls"]
        ]
    return out


def messages_text(messages: list[dict]) -> str:
    """보낸 메시지 → input_text."""
    return _safe(_cut(json.dumps([_short(m) for m in messages], ensure_ascii=False), TEXT_LIMIT))


def reply_text(reply: LlmReply) -> str:
    """받은 답 → output_text: 답 글과 도구 호출(점 표기 이름, 모델에 다시 보낼 인자 글을 MESSAGE_LIMIT 에서 자름)."""
    calls = [{"id": c.id, "name": c.name, "arguments": _cut(arguments_text(c.arguments, c.raw_arguments), MESSAGE_LIMIT)}
             for c in reply.tool_calls]
    return _safe(_cut(json.dumps({"text": reply.text, "tool_calls": calls}, ensure_ascii=False), TEXT_LIMIT))


def _warn(what: str, exc: Exception) -> None:
    """기록 실패는 경고만: 예외 글에는 값이 들어 있을 수 있어 종류만 남긴다."""
    logger.warning("실행 추적을 남기지 못했습니다: %s (%s)", what, type(exc).__name__)


def _quiet(method: Callable) -> Callable:
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — 추적 기록은 턴을 바꾸지 않는다
            _warn(method.__name__, exc)
            return None

    return wrapper


class TraceLog:
    """턴 하나의 추적. 만든 때가 턴(과 맥락 조립)의 시작이다."""

    def __init__(self, session: Session, chat_session_id: int, turn_id: int) -> None:
        self.session = session
        self.chat_session_id = chat_session_id
        self.turn_id = turn_id
        self.run_id: int | None = None
        self._events: list[TraceEvent] = []
        self._started = datetime.now(UTC)
        self._t0 = time.perf_counter()

    def _ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def _add(self, kind: str, **fields) -> TraceEvent:
        event = TraceEvent(chat_session_id=self.chat_session_id, turn_id=self.turn_id, run_id=self.run_id,
                           seq=len(self._events) + 1, kind=kind, **fields)
        self.session.add(event)
        self._events.append(event)
        return event

    @_quiet
    def context(self, parts: list[dict], history_count: int, tool_count: int) -> None:
        """맥락 조립 사건. ms = 턴 시작부터 지금까지(메시지 조립과 재료 세기)."""
        body = {"parts": parts, "history_count": history_count, "tool_count": tool_count}
        self._add("context", label=CONTEXT_LABEL, started_at=self._started, ms=self._ms(),
                  input_text=json.dumps(body, ensure_ascii=False))

    @_quiet
    def llm_start(self, messages: list[dict], purpose: str) -> TraceEvent:
        """모델 호출 사건을 ms 없이 더한다(부르는 쪽이 호출 전에 commit 한다)."""
        return self._add("llm", label=purpose[:_LABEL_LIMIT], started_at=datetime.now(UTC),
                         input_text=messages_text(messages))

    @_quiet
    def llm_end(self, ev: TraceEvent | None, reply: LlmReply | None, error: str | None, ms: int) -> None:
        """호출 결과를 채운다. 답이 없으면 실패(ok False, error 안내 글)."""
        if ev is None:
            return
        ev.ms = ms
        if reply is None:
            ev.ok = False
            ev.error = _safe(error or "")[:_ERROR_LIMIT]
            return
        ev.model = _safe(reply.model)[:_MODEL_LIMIT]
        ev.input_tokens = _count(reply.usage.input_tokens)
        ev.output_tokens = _count(reply.usage.output_tokens)
        cost = reply.usage.cost
        ev.cost = cost if cost is not None and math.isfinite(cost) else None
        ev.output_text = reply_text(reply)

    @_quiet
    def attach_run(self, run_id: int) -> None:
        """실행 기록이 생겼다: 이 턴의 지난 사건과 앞으로의 사건에 run_id."""
        if run_id is None or run_id == self.run_id:
            return
        self.run_id = run_id
        for event in self._events:
            event.run_id = run_id

    @_quiet
    def skill(self, matched: object | None) -> None:
        """스킬 매칭 결과 기록(맞는 스킬이 있으면 이름·단계를 output_text 에 남긴다)."""
        if matched is None:
            self._add("skill", label="스킬 찾기", started_at=datetime.now(UTC), ms=0, input_text="일치하는 스킬 없음",
                      output_text="")
            return
        out = json.dumps({"id": matched.id, "name": matched.name, "steps": matched.steps_json}, ensure_ascii=False)
        self._add("skill", label=f"스킬 적용: {matched.name}"[:_LABEL_LIMIT], started_at=datetime.now(UTC), ms=0,
                  input_text=matched.name, output_text=_cut(out, TEXT_LIMIT))

    @_quiet
    def end(self, status: Literal["done", "failed", "stopped"], text: str | None) -> None:
        """끝 사건: label 은 상태, output_text 는 마지막 답 글(실패·멈춤이면 그 안내), ms 는 턴 전체 시간."""
        ok = status == "done"
        text = _safe(text or "")
        self._add("end", label=status, started_at=datetime.now(UTC), ms=self._ms(), ok=ok,
                  error=None if ok else (text or status)[:_ERROR_LIMIT], output_text=_cut(text, TEXT_LIMIT))


def context_parts(
    session: Session, user: User, chat_session_id: int, ui: UiContext, tools: list[dict],
    *, history_limit: int = context.HISTORY_LIMIT,
) -> list[dict]:
    """모델에 보내는 맥락의 재료마다 글자 수: [{name, chars}] CONTEXT_PARTS 차례.

    지시문·분야 지식·정밀도·지금 상황·날짜 도우미는 system 메시지의 조각이다(지시문 = system.md 와 지시문 조각).
    대화 = 기록 메시지 JSON, 도구 목록 = 도구 정의 JSON 의 글자 수. 세다가 실패하면 경고만 남기고 [].
    """
    try:
        return _count_parts(session, user, chat_session_id, ui, tools, history_limit=history_limit)
    except Exception as exc:  # noqa: BLE001 — 추적 기록은 턴을 바꾸지 않는다
        _warn("context_parts", exc)
        return []


def _count_parts(
    session: Session, user: User, chat_session_id: int, ui: UiContext, tools: list[dict],
    *, history_limit: int = context.HISTORY_LIMIT,
) -> list[dict]:
    rows = recent_messages(session, chat_session_id, history_limit)
    active_domains = context.detect_active_domains(session, ui, rows)
    knowledge = context.packs_text(active_domains)
    levels = levels_prompt()
    attached = context.files_line(session, chat_session_id)  # 지금 상황 끝의 「이 대화에 붙인 파일」 줄
    older = context.compact_older_note(session, chat_session_id, rows)
    last_text = " ".join(context._date_texts(rows))
    guides = context.select_guides(last_text, ui, has_files=attached is not None)
    chars = {
        "지시문": len(context.system_prompt(guides, active_domains=active_domains)) - len(knowledge) - len(levels),
        "분야 지식": len(knowledge),
        "정밀도": len(levels),
        "지금 상황": len(context.situation(session, user, ui, chat_session_id=chat_session_id)) + (len(older) + 2 if older else 0),
        "붙인 파일": len(attached) + 1 if attached else 0,
        "날짜 도우미": len("\n".join(context.date_helper(rows, context.today()))),
        "대화": len(json.dumps(context.history(rows), ensure_ascii=False)),
        "도구 목록": len(json.dumps(tools, ensure_ascii=False)),
    }
    return [{"name": name, "chars": chars[name]} for name in CONTEXT_PARTS]
