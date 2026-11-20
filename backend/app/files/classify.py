"""파일 분류 단계(설계 5-2): 축은 고정(종류·공종·현장·시기·출처), 값은 에이전트가 늘린다. 한 줄 요약·그림 설명·합치기 제안.

- 뒤 작업 줄(files.jobs)이 파일을 indexed 로 만든 뒤 after_index 를 부른다. 에이전트(light, 그림이면 「그림 읽기」 vision)가
  지금 있는 값 목록을 받고 축마다 값을 고른다(strict JSON). 맞는 값이 없을 때만 새 값을 만든다 — 뜻 판단은 에이전트,
  코드는 앞뒤 공백·중복만 정리한다. 새 값은 axis_values.is_new(자료함의 「새」).
- 시기는 코드가 정한다: 뽑은 글의 날짜(YYYY-MM-DD·YYYY.MM.DD·YYYY년 M월)에서 가장 많이 나온 달, 없으면 올린 달(한국 시각).
- 사람이 이미 값을 넣은 축은 에이전트가 바꾸지 않는다. 바로 저장하고 status classified, 그 파일을 붙인 대화마다
  card{kind: "file_saved", file_id, name, axes} 사건 줄을 남긴다.
- 그림(MAX_IMAGE_BYTES 까지)은 원본을 data URI 로 보내고, 받은 설명(DESCRIPTION_CHARS 자)을 조각 하나로 저장해
  낱말 색인과 뜻 검색(지금 모델 — 다시 넣기 중이면 새 모델에도)에 넣는다. 더 크면 설명 없이 이름으로만 분류하고 BIG_IMAGE.
- LLM 이 실패하거나 모양이 틀리면 status 는 indexed 그대로, reason FAILED, 카드 없음(파일은 그대로 쓸 수 있다).
- 합치기 제안(suggest_if_due): 하루 한 번 축마다 값·파일 수를 에이전트에게 보이고(30개 넘는 축은 알린다) 합칠 묶음을
  받아 코드가 있는 값인지 확인한 뒤 <data_dir>/files/merge_suggestions.json 에 둔다. 읽을 때 이미 없어진 값의 제안은 뺀다.
- LLM 을 부르기 전에는 읽기만 한다. 쓰기는 asyncio.to_thread 로 새 세션에서(files.jobs 와 같은 규칙).
"""

import asyncio
import base64
import json
import logging
import re
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agent.events import json_safe
from app.config import Settings
from app.db import get_session
from app.files import kinds, vectors
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.llm.embeddings import embed
from app.store import chats, files
from app.store.tables import (
    AxisValue,
    ChatSession,
    ChatSessionFile,
    FileAxis,
    FileChunk,
    FileRow,
    ReindexJob,
    ScheduleRecord,
)

logger = logging.getLogger(__name__)

AXES = ("종류", "공종", "현장", "시기", "출처")
AGENT_AXES = {"kind": "종류", "trade": "공종", "site": "현장", "source": "출처"}  # 시기는 코드가 정한다
PERIOD = "시기"
FAILED = "분류하지 못했습니다"
BIG_IMAGE = "그림이 커서 설명을 만들지 않았습니다"
DESCRIPTION_LOCATOR = "그림 설명"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
SUMMARY_CHARS = 120
DESCRIPTION_CHARS = 600
VALUE_CHARS = 100  # axis_values.value 칸 길이
MAX_PER_AXIS = 5
SAMPLE_CHARS = 4000  # 지시에 넣을 뽑은 글
PERIOD_CHUNKS = 50  # 시기를 셀 앞 조각 수
LISTED_VALUES = 200  # 지시에 넣을 축마다 값 수(파일 많은 차례)
LISTED_SCHEDULES = 50
CROWDED = 30
SUGGEST_EVERY = timedelta(days=1)
MAX_SUGGESTIONS = 20
TIMEOUT_S = 120
SEOUL = ZoneInfo("Asia/Seoul")
_PROMPT_FILE = Path(__file__).resolve().parent.parent / "agent" / "prompts" / "classify_file.md"
_DATE = re.compile(r"(?<!\d)(20\d{2})\s*(?:[-./]|년)\s*(\d{1,2})(?!\d)")

TRANSPORT: httpx.AsyncBaseTransport | None = None  # 시험이 가짜 LLM 을 끼운다(없으면 LlmClient 기본)


class ClassifyFailed(Exception):
    """분류하지 못했다(LLM 실패·모양이 틀린 답·없는 파일). 파일에는 FAILED 를 남겼다."""


@dataclass(frozen=True)
class Classified:
    axes: dict[str, list[str]]  # 다섯 축 모두(값이 없으면 빈 목록)
    summary: str
    new_values: list[tuple[str, str]]  # 에이전트가 새로 만든 (축, 값)


class _Axes(BaseModel):
    kind: list[str]
    trade: list[str]
    site: list[str]
    source: list[str]


class _Answer(BaseModel):
    axes: _Axes
    summary: str
    description: str | None = None


class _Suggestion(BaseModel):
    axis: str
    from_: list[str] = Field(alias="from")
    to: str
    why: str


class _Suggestions(BaseModel):
    items: list[_Suggestion]


_VALUES = {"type": "array", "items": {"type": "string"}}
_MERGE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"axis": {"type": "string", "enum": list(AGENT_AXES.values())}, "from": _VALUES,
                       "to": {"type": "string"}, "why": {"type": "string"}},
        "required": ["axis", "from", "to", "why"], "additionalProperties": False,
    }}},
    "required": ["items"], "additionalProperties": False,
}


def _schema(with_description: bool) -> dict:
    axes = {"type": "object", "properties": dict.fromkeys(AGENT_AXES, _VALUES), "required": list(AGENT_AXES),
            "additionalProperties": False}
    properties: dict = {"axes": axes, "summary": {"type": "string"}}
    if with_description:
        properties["description"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _prompts() -> tuple[str, str]:
    """(분류 지시, 합치기 지시) — 한 파일의 「# 합치기」 앞뒤."""
    classify_text, merge_text = _PROMPT_FILE.read_text(encoding="utf-8").split("\n# 합치기\n", 1)
    return classify_text.strip(), merge_text.strip()


def _db():
    return contextmanager(get_session)()


def _now() -> datetime:
    return datetime.now(UTC)


def clean(values: list[str], limit: int | None = MAX_PER_AXIS) -> list[str]:
    """앞뒤 공백을 떼고 빈 값·중복을 뺀다(차례 그대로). 뜻은 보지 않는다."""
    out: list[str] = []
    for value in values:
        value = json_safe(value).strip()[:VALUE_CHARS].strip()
        if value and value not in out:
            out.append(value)
    return out if limit is None else out[:limit]


def value_counts(session: Session) -> dict[str, list[tuple[str, int, bool]]]:
    """축마다 [(값, 그 값을 가진 보이는 파일 수, 새 값인가)] — 파일 많은 차례, 같으면 값 차례. 다섯 축 모두."""
    visible = select(FileRow.id).where(FileRow.deleted_at.is_(None))
    count = func.count(FileAxis.file_id.distinct())
    query = (
        select(AxisValue.axis, AxisValue.value, AxisValue.is_new, count)
        .outerjoin(FileAxis, (FileAxis.axis == AxisValue.axis) & (FileAxis.value == AxisValue.value)
                   & FileAxis.file_id.in_(visible))
        .group_by(AxisValue.axis, AxisValue.value, AxisValue.is_new)
        .order_by(count.desc(), AxisValue.value)
    )
    out: dict[str, list[tuple[str, int, bool]]] = {axis: [] for axis in AXES}
    for axis, value, is_new, n in session.execute(query):
        out.setdefault(axis, []).append((value, n, bool(is_new)))
    return out


# ── 분류 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Work:
    file_id: int
    message: str
    image: str | None  # data URI(그림을 보낼 때만)
    big_image: bool
    period: str


def _period(text_: str, uploaded_at: datetime) -> str:
    months = Counter(f"{y}-{int(m):02d}" for y, m in _DATE.findall(text_) if 1 <= int(m) <= 12)
    if months:
        return min(months, key=lambda month: (-months[month], month))
    when = uploaded_at if uploaded_at.tzinfo else uploaded_at.replace(tzinfo=UTC)  # SQLite 는 시간대 없이 돌려준다
    return when.astimezone(SEOUL).strftime("%Y-%m")


def _hints(session: Session, file_id: int) -> list[str]:
    chat_ids = select(ChatSessionFile.session_id).where(ChatSessionFile.file_id == file_id)
    chats_ = list(session.scalars(select(ChatSession).where(ChatSession.id.in_(chat_ids))))
    chat_schedules = [s for s in (c.schedule_id for c in chats_) if s is not None]
    names = list(session.scalars(select(ScheduleRecord.name).order_by(ScheduleRecord.id.desc()).limit(LISTED_SCHEDULES)))
    attached = list(session.scalars(select(ScheduleRecord.name).where(ScheduleRecord.id.in_(chat_schedules))))
    return [
        f"올린 곳: {'대화 첨부' if chats_ else '자료함'}",
        f"붙인 대화의 일정: {', '.join(attached) or '(없음)'}",
        f"등록된 일정 이름(현장 후보): {', '.join(names) or '(없음)'}",
    ]


def _read(session: Session, file_id: int) -> _Work:
    row = files.get(session, file_id)
    pieces = [c.text for c in files.chunks_of(session, file_id)[:PERIOD_CHUNKS]]
    body = "\n".join(pieces)
    send_image = row.kind == "image" and row.size <= MAX_IMAGE_BYTES
    image = None
    if send_image:
        media = kinds.MEDIA_TYPES.get(f".{row.ext}", "image/png")
        image = f"data:{media};base64,{base64.b64encode(files.raw_path(row.sha256).read_bytes()).decode()}"
    listed = []
    counts = value_counts(session)
    for key, axis in AGENT_AXES.items():
        values = [v for v, _, _ in counts[axis][:LISTED_VALUES]]
        listed.append(f"- {key}({axis}): {', '.join(values) or '(없음)'}")
    message = "\n".join([
        f"파일: {row.name} (형식 {row.kind}, {row.pages or 1}쪽)", *_hints(session, file_id),
        "지금 있는 값:", *listed,
        "그림: 함께 보냄" if send_image else ("그림: 커서 보내지 않음 — 이름으로만 고른다" if row.kind == "image" else ""),
        "뽑은 글(앞부분):", body[:SAMPLE_CHARS] or "(글 없음)",
    ])
    return _Work(file_id, message, image, row.kind == "image" and not send_image, _period(body, row.uploaded_at))


async def _ask(session: Session, work: _Work) -> _Answer:
    instructions, _ = _prompts()
    content: str | list[dict] = work.message
    if work.image is not None:
        content = [{"type": "text", "text": work.message}, {"type": "image_url", "image_url": {"url": work.image}}]
    messages = [{"role": "system", "content": instructions}, {"role": "user", "content": content}]
    purpose = "vision" if work.image is not None else "light"
    try:
        reply = await LlmClient(session, transport=TRANSPORT).chat(
            purpose, messages, json_schema=_schema(work.image is not None), timeout_s=TIMEOUT_S)
        return _Answer.model_validate(reply.parsed)
    except (LlmNotReady, LlmFailed, ValidationError) as exc:
        logger.warning("분류 실패: 파일 %d (%s)", work.file_id, type(exc).__name__)
        raise ClassifyFailed(work.file_id) from None


def _mark_failed(file_id: int) -> None:
    with _db() as session:
        row = session.get(FileRow, file_id)
        if row is not None and row.reason is None:
            row.reason = FAILED
            session.commit()


def _add_description(session: Session, file_id: int, description: str) -> int:
    seq = session.scalar(select(func.max(FileChunk.seq)).where(FileChunk.file_id == file_id))
    piece = FileChunk(file_id=file_id, seq=0 if seq is None else seq + 1, locator=DESCRIPTION_LOCATOR, text=description)
    session.add(piece)
    session.flush()
    session.execute(text("INSERT INTO file_chunks_fts(rowid, text) VALUES (:id, :text)"), {"id": piece.id, "text": description})
    return piece.id


def _save(work: _Work, answer: _Answer) -> tuple[Classified, int | None, str]:
    """고른 값·요약·설명을 저장하고 붙인 대화마다 카드 줄. (결과, 설명 조각 id, 설명 글)."""
    picked = {axis: clean(getattr(answer.axes, key)) for key, axis in AGENT_AXES.items()}
    picked[PERIOD] = [work.period]
    with _db() as session:
        row = session.get(FileRow, work.file_id)
        if row is None:
            raise ClassifyFailed(work.file_id)
        kept = files.axes_of(session, work.file_id)  # 사람이 이미 넣은 축은 그대로
        known = {tuple(r) for r in session.execute(select(AxisValue.axis, AxisValue.value))}
        axes, new_values = {}, []
        for axis in AXES:
            axes[axis] = kept.get(axis) or picked[axis]
            if axis in kept:
                continue
            for value in picked[axis]:
                session.add(FileAxis(file_id=row.id, axis=axis, value=value))
                if (axis, value) not in known:
                    session.add(AxisValue(axis=axis, value=value, is_new=axis != PERIOD))  # 코드가 만든 달은 「새」 아님
                    if axis != PERIOD:
                        new_values.append((axis, value))
        text_ = json_safe(answer.description or "").strip()[:DESCRIPTION_CHARS] if work.image is not None else ""
        chunk_id = _add_description(session, row.id, text_) if text_ else None
        row.summary = json_safe(answer.summary).strip()[:SUMMARY_CHARS]
        row.status = "classified"
        if row.reason == FAILED:
            row.reason = None
        if work.big_image and row.reason is None:
            row.reason = BIG_IMAGE
        shown = {axis: values for axis, values in axes.items() if values}
        card = {"type": "card", "data": {"kind": "file_saved", "file_id": row.id, "name": row.name, "axes": shown}}
        linked = list(session.scalars(select(ChatSessionFile.session_id).where(ChatSessionFile.file_id == row.id)))
        for chat_id in linked:
            chats.add_message(session, chat_id, "event", card)
        session.commit()
        return Classified(axes, row.summary, new_values), chunk_id, text_


def _models(active_model) -> list[str]:
    """설명 조각을 넣을 모델: 지금 모델, 다시 넣기 중이면 그 새 모델도."""
    with _db() as session:
        model = active_model(session)
        running = session.scalar(select(ReindexJob.model).where(ReindexJob.status == "running").order_by(ReindexJob.id).limit(1))
    return [model] + ([running] if running and running != model else [])


async def _embed_description(file_id: int, chunk_id: int, description: str) -> None:
    """설명 조각을 뜻 검색에 넣는다. 안 되면 경고만(낱말 검색으로는 찾고, 다음 다시 넣기 때 들어간다)."""
    from app.files import jobs  # jobs 가 이 모듈을 부르므로 여기서

    store = vectors.STORE
    if store is None:
        return
    try:
        for model in await asyncio.to_thread(_models, jobs.active_model):
            with _db() as session:
                [found] = await embed(session, [description], model=model)
            point = vectors.Point(chunk_id, file_id, found)
            await asyncio.to_thread(store.upsert, store.collection_for(model, len(found)), [point])
    except Exception as exc:  # noqa: BLE001 — 분류는 끝났다. 종류만 남긴다
        logger.warning("그림 설명 임베딩 실패: 파일 %d (%s)", file_id, type(exc).__name__)


async def classify(session: Session, file_id: int) -> Classified:
    """파일 하나를 분류해 바로 저장한다(맨 위 설명). session 은 읽기만 한다. 실패하면 FAILED 를 남기고 ClassifyFailed."""
    work = _read(session, file_id)
    try:
        answer = await _ask(session, work)
    except ClassifyFailed:
        await asyncio.to_thread(_mark_failed, file_id)
        raise
    result, chunk_id, description = await asyncio.to_thread(_save, work, answer)
    if chunk_id is not None:
        await _embed_description(file_id, chunk_id, description)
    return result


def _waiting_for_classification(file_id: int) -> bool:
    with _db() as session:
        row = session.get(FileRow, file_id)
        return row is not None and row.status == "indexed" and row.deleted_at is None


async def after_index(file_id: int) -> None:
    """뒤 작업 줄이 파일을 indexed 로 만든 뒤. 숨긴 파일·indexed 가 아닌 파일은 건너뛴다. 예외를 내지 않는다."""
    try:
        if not await asyncio.to_thread(_waiting_for_classification, file_id):
            return
        with _db() as session:
            await classify(session, file_id)
    except ClassifyFailed:
        return
    except Exception as exc:  # noqa: BLE001 — 일꾼이 임베딩 실패로 잘못 알지 않게. 종류만 남긴다
        logger.warning("분류 단계 오류: 파일 %d (%s)", file_id, type(exc).__name__)


# ── 값 합치기 제안 ───────────────────────────────────────────────────


def _suggestions_path():
    return Settings().data_dir / "files" / "merge_suggestions.json"


def _load() -> dict:
    path = _suggestions_path()
    if not path.exists():
        return {"made_at": None, "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _store(items: list[dict]) -> None:
    path = _suggestions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    tmp.write_text(json.dumps({"made_at": _now().isoformat(), "items": items}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def suggestions(session: Session) -> tuple[datetime | None, list[dict]]:
    """(만든 때, [{axis, from, to, why}]) — 이미 없어진 값(합쳤거나 지움)이 든 제안은 뺀다."""
    data = _load()
    have = {tuple(r) for r in session.execute(select(AxisValue.axis, AxisValue.value))}
    items = [i for i in data["items"] if all((i["axis"], v) in have for v in i["from"])]
    return (datetime.fromisoformat(data["made_at"]) if data["made_at"] else None), items


def _merge_message(counts: dict[str, list[tuple[str, int, bool]]]) -> str:
    lines = ["축마다 지금 있는 값(파일 수):"]
    for axis in AGENT_AXES.values():
        values = counts[axis]
        crowded = f" — {CROWDED}개를 넘었습니다" if len(values) > CROWDED else ""
        listed = ", ".join(f"{v}({n})" for v, n, _ in values) or "(없음)"
        lines.append(f"- {axis}: {len(values)}개{crowded}: {listed}")
    return "\n".join(lines)


def _checked(parsed: object, counts: dict[str, list[tuple[str, int, bool]]]) -> list[dict]:
    """있는 값만 합치는 제안. 남길 값과 같은 값은 from 에서 뺀다."""
    try:
        answer = _Suggestions.model_validate(parsed)
    except ValidationError:
        return []
    out = []
    for item in answer.items:
        have = {v for v, _, _ in counts.get(item.axis, [])}
        to = clean([item.to], 1)
        sources = [v for v in clean(item.from_, None) if v not in to]
        if item.axis in AGENT_AXES.values() and to and sources and all(v in have for v in sources):
            out.append({"axis": item.axis, "from": sources, "to": to[0], "why": json_safe(item.why).strip()[:200]})
    return out[:MAX_SUGGESTIONS]


def _counts() -> dict[str, list[tuple[str, int, bool]]]:
    with _db() as session:
        return value_counts(session)


async def suggest_merges() -> None:
    """합칠 묶음을 에이전트에게 받아 저장한다. 견줄 값(한 축에 둘 이상)이 없으면 부르지 않는다. LLM 이 실패하면 옛 제안을 둔다."""
    counts = await asyncio.to_thread(_counts)
    items: list[dict] = []
    if any(len(counts[axis]) >= 2 for axis in AGENT_AXES.values()):
        _, instructions = _prompts()
        messages = [{"role": "system", "content": instructions}, {"role": "user", "content": _merge_message(counts)}]
        try:
            with _db() as session:
                reply = await LlmClient(session, transport=TRANSPORT).chat(
                    "light", messages, json_schema=_MERGE_SCHEMA, timeout_s=TIMEOUT_S)
            items = _checked(reply.parsed, counts)
        except (LlmNotReady, LlmFailed) as exc:
            logger.warning("합치기 제안 실패 (%s)", type(exc).__name__)
            items = (await asyncio.to_thread(_load))["items"]
    await asyncio.to_thread(_store, items)


async def suggest_if_due() -> None:
    """뒤 작업 일꾼이 5분마다 부른다: 마지막 제안이 SUGGEST_EVERY 보다 오래됐으면 새로 만든다. 예외를 내지 않는다."""
    try:
        made = (await asyncio.to_thread(_load))["made_at"]
        if made is not None and _now() - datetime.fromisoformat(made) < SUGGEST_EVERY:
            return
        await suggest_merges()
    except Exception as exc:  # noqa: BLE001 — 일꾼은 멈추지 않는다
        logger.warning("합치기 제안 단계 오류 (%s)", type(exc).__name__)
