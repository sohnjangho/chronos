"""값 합치기 제안(설계 5-2): 하루 한 번 축마다 값·파일 수를 에이전트에게 보이고(30개 넘는 축은 알린다) 합칠 묶음을 받는다.

- 뜻이 같은지는 에이전트가 판단하고, 코드는 있는 값인지·남길 값과 다른지만 본다(MAX_SUGGESTIONS 개까지). 시기 축은 빼고 본다.
- <data_dir>/files/merge_suggestions.json 에 둔다(새 표는 만들지 않는다). 읽을 때 이미 없어진 값(합쳤거나 지움)이 든 제안은
  뺀다. 파일이 깨졌으면 빈 것으로 본다. LLM 이 실패하거나 모양이 틀린 답이면 옛 제안을 그대로 둔다.
- 뒤 작업 일꾼(files.jobs)이 5분마다 suggest_if_due 를 부른다. 쓰기·읽기는 asyncio.to_thread 로 새 세션에서.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import json_safe
from app.config import Settings
from app.files import classify
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.store.tables import AxisValue

logger = logging.getLogger(__name__)

CROWDED = 30
SUGGEST_EVERY = timedelta(days=1)
MAX_SUGGESTIONS = 20
_FROM = {"type": "array", "items": {"type": "string"}}


def _schema() -> dict:
    """strict JSON 모양(classify 를 import 하는 동안 읽지 않게 함수로 — files.jobs ↔ classify ↔ store.files 가 서로 부른다)."""
    item = {
        "type": "object",
        "properties": {"axis": {"type": "string", "enum": list(classify.AGENT_AXES.values())}, "from": _FROM,
                       "to": {"type": "string"}, "why": {"type": "string"}},
        "required": ["axis", "from", "to", "why"], "additionalProperties": False,
    }
    return {"type": "object", "properties": {"items": {"type": "array", "items": item}}, "required": ["items"],
            "additionalProperties": False}


Counts = dict[str, list[tuple[str, int, bool]]]


class _Suggestion(BaseModel):
    axis: str
    from_: list[str] = Field(alias="from")
    to: str
    why: str


class _Suggestions(BaseModel):
    items: list[_Suggestion]


class _Stored(BaseModel):
    made_at: datetime | None
    items: list[dict]


def _now() -> datetime:
    return datetime.now(UTC)


def _path() -> Path:
    return Settings().data_dir / "files" / "merge_suggestions.json"


def _load() -> _Stored:
    """저장한 제안. 없거나 깨졌으면 빈 것(made_at None — 다음 확인 때 새로 만든다)."""
    try:
        return _Stored.model_validate(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):  # 없음 · JSON 아님 · 모양 틀림(ValidationError 도 ValueError)
        return _Stored(made_at=None, items=[])


def _store(items: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    tmp.write_text(json.dumps({"made_at": _now().isoformat(), "items": items}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def suggestions(session: Session) -> tuple[datetime | None, list[dict]]:
    """(만든 때, [{axis, from, to, why}]) — 이미 없어진 값이 든 제안은 뺀다."""
    stored = _load()
    have = {tuple(r) for r in session.execute(select(AxisValue.axis, AxisValue.value))}
    items = []
    for raw in stored.items:
        try:
            item = _Suggestion.model_validate(raw)
        except ValidationError:  # 손으로 고친 파일 등 — 그 줄만 버린다
            continue
        if item.from_ and all((item.axis, v) in have for v in item.from_):
            items.append(item.model_dump(by_alias=True))
    return stored.made_at, items


def _message(counts: Counts) -> str:
    lines = ["축마다 지금 있는 값(파일 수):"]
    for axis in classify.AGENT_AXES.values():
        values = counts[axis]
        crowded = f" — {CROWDED}개를 넘었습니다" if len(values) > CROWDED else ""
        listed = ", ".join(f"{v}({n})" for v, n, _ in values) or "(없음)"
        lines.append(f"- {axis}: {len(values)}개{crowded}: {listed}")
    return "\n".join(lines)


def _checked(parsed: object, counts: Counts) -> list[dict] | None:
    """있는 값만 합치는 제안(남길 값과 같은 값은 from 에서 뺀다). 모양이 틀린 답이면 None."""
    try:
        answer = _Suggestions.model_validate(parsed)
    except ValidationError:
        return None
    out = []
    for item in answer.items:
        have = {v for v, _, _ in counts.get(item.axis, [])}
        to = classify.clean([item.to], 1)
        sources = [v for v in classify.clean(item.from_, None) if v not in to]
        if item.axis in classify.AGENT_AXES.values() and to and sources and all(v in have for v in sources):
            out.append({"axis": item.axis, "from": sources, "to": to[0], "why": json_safe(item.why).strip()[:200]})
    return out[:MAX_SUGGESTIONS]


def _counts() -> Counts:
    with classify.db() as session:
        return classify.value_counts(session)


async def _ask(counts: Counts) -> list[dict] | None:
    """에이전트에게 묶음을 받는다. 실패·모양 틀림이면 None."""
    messages = [{"role": "system", "content": classify.prompts()[1]}, {"role": "user", "content": _message(counts)}]
    try:
        with classify.db() as session:
            reply = await LlmClient(session, transport=classify.TRANSPORT).chat(
                "light", messages, json_schema=_schema(), timeout_s=classify.TIMEOUT_S)
    except (LlmNotReady, LlmFailed) as exc:
        logger.warning("합치기 제안 실패 (%s)", type(exc).__name__)
        return None
    items = _checked(reply.parsed, counts)
    if items is None:
        logger.warning("합치기 제안 실패 (모양이 틀린 답)")
    return items


async def suggest_merges() -> None:
    """합칠 묶음을 받아 저장한다. 견줄 값(한 축에 둘 이상)이 없으면 부르지 않는다. 실패하면 옛 제안을 둔다(만든 때만 새로)."""
    counts = await asyncio.to_thread(_counts)
    items: list[dict] | None = []
    if any(len(counts[axis]) >= 2 for axis in classify.AGENT_AXES.values()):
        items = await _ask(counts)
    if items is None:
        items = (await asyncio.to_thread(_load)).items
    await asyncio.to_thread(_store, items)


async def suggest_if_due() -> None:
    """마지막 제안이 SUGGEST_EVERY 보다 오래됐으면(없거나 깨졌으면) 새로 만든다. 예외를 내지 않는다."""
    try:
        made = (await asyncio.to_thread(_load)).made_at
        if made is not None and _now() - made < SUGGEST_EVERY:
            return
        await suggest_merges()
    except Exception as exc:  # noqa: BLE001 — 일꾼은 멈추지 않는다
        logger.warning("합치기 제안 단계 오류 (%s)", type(exc).__name__)
