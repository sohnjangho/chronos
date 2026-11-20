"""파일 분류 단계(설계 5-2): 축은 고정(종류·공종·현장·시기·출처), 값은 에이전트가 늘린다. 한 줄 요약·그림 설명.

- 뒤 작업 줄(files.jobs)이 파일마다 임베딩을 해 본 뒤(성공·실패·뜻 검색 꺼짐 모두) after_index 를 부른다. 분류는 뜻 검색과
  따로다: 숨기지 않았고 요약이 아직 없고 status 가 extracted·indexed 인 파일만 한 번 분류한다. 에이전트(light, 그림이면 「그림 읽기」 vision)가
  지금 있는 값 목록을 받고 축마다 값을 고른다(strict JSON). 맞는 값이 없을 때만 새 값을 만든다 — 뜻 판단은 에이전트,
  코드는 앞뒤 공백·중복만 정리한다. 새 값은 axis_values.is_new(자료함의 「새」).
- 시기는 코드가 정한다: 뽑은 글의 날짜(YYYY-MM-DD·YYYY.MM.DD·YYYY년 M월)에서 가장 많이 나온 달, 없으면 올린 달(한국 시각).
- 사람이 이미 값을 넣은 축은 에이전트가 바꾸지 않는다. 바로 저장한다. 요약은 늘 채운다(비면 파일 이름) — 「분류됨」의 표시는
  요약이다. status 는 indexed 일 때만 classified 로, extracted 는 그대로(뒤에 임베딩되면 jobs 가 classified 로). 붙인 대화마다
  card{kind: "file_saved", file_id, name, axes} 사건 줄을 남긴다.
- 그림(MAX_IMAGE_BYTES 까지)은 원본을 data URI 로 보내고, 받은 설명(DESCRIPTION_CHARS 자)을 조각 하나로 저장해
  낱말 색인에 넣고, 이미 임베딩된 파일이면 뜻 검색(지금 모델 — 다시 넣기 중이면 새 모델에도)에도 넣는다(아니면 jobs 가 넣는다). 더 크면 설명 없이 이름으로만 분류하고 BIG_IMAGE.
- LLM 이 실패하거나 모양이 틀리면 status 는 indexed 그대로, reason FAILED, 카드 없음(파일은 그대로 쓸 수 있다).
- 값 합치기 제안은 files.merge_suggest. LLM 호출 앞뒤의 DB 읽기·쓰기(그림 바이트 읽기 포함)는 asyncio.to_thread 로 새 세션에서
  (files.jobs 와 같은 규칙). LLM 을 부르는 동안 쓰기를 쥐지 않는다.
"""

import asyncio
import base64
import logging
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agent.events import json_safe
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


_VALUES = {"type": "array", "items": {"type": "string"}}


def _schema(with_description: bool) -> dict:
    axes = {"type": "object", "properties": dict.fromkeys(AGENT_AXES, _VALUES), "required": list(AGENT_AXES),
            "additionalProperties": False}
    properties: dict = {"axes": axes, "summary": {"type": "string"}}
    if with_description:
        properties["description"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def prompts() -> tuple[str, str]:
    """(분류 지시, 합치기 지시) — 한 파일의 「# 합치기」 앞뒤."""
    classify_text, merge_text = _PROMPT_FILE.read_text(encoding="utf-8").split("\n# 합치기\n", 1)
    return classify_text.strip(), merge_text.strip()


def db():
    """새 세션(with 로 닫는다) — 뒤 작업의 DB 묶음마다 하나."""
    return contextmanager(get_session)()


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


def big_image(row: FileRow) -> bool:
    """그림이 커서 설명 없이 분류한 파일인가(reason BIG_IMAGE 를 되살릴 때 — jobs 가 「뜻 검색 준비 안 됨」을 지울 때)."""
    return row.kind == "image" and row.size > MAX_IMAGE_BYTES and bool(row.summary)


def _read(file_id: int) -> _Work:
    with db() as session:
        return _read_in(session, file_id)


def _read_in(session: Session, file_id: int) -> _Work:
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
    instructions, _ = prompts()
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
    with db() as session:
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
    """고른 값·요약·설명을 저장하고 붙인 대화마다 카드 줄. (결과, 지금 뜻 검색에 넣을 설명 조각 id, 설명 글)."""
    picked = {axis: clean(getattr(answer.axes, key)) for key, axis in AGENT_AXES.items()}
    picked[PERIOD] = [work.period]
    with db() as session:
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
        row.summary = " ".join(json_safe(answer.summary).split())[:SUMMARY_CHARS] or row.name[:SUMMARY_CHARS]
        embedded = row.status == "indexed"  # extracted 는 그대로 — 뒤에 임베딩되면 jobs 가 classified 로
        if embedded:
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
        return Classified(axes, row.summary, new_values), chunk_id if embedded else None, text_


def _models(active_model) -> list[str]:
    """설명 조각을 넣을 모델: 지금 모델, 다시 넣기 중이면 그 새 모델도."""
    with db() as session:
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
            with db() as session:
                [found] = await embed(session, [description], model=model)
            point = vectors.Point(chunk_id, file_id, found)
            await asyncio.to_thread(store.upsert, store.collection_for(model, len(found)), [point])
    except Exception as exc:  # noqa: BLE001 — 분류는 끝났다. 종류만 남긴다
        logger.warning("그림 설명 임베딩 실패: 파일 %d (%s)", file_id, type(exc).__name__)


async def classify(session: Session, file_id: int) -> Classified:
    """파일 하나를 분류해 바로 저장한다(맨 위 설명). session 은 LLM 연결 찾기·호출 기록에만 쓴다(읽기·쓰기는 스레드의
    새 세션). 실패하면 FAILED 를 남기고 ClassifyFailed."""
    work = await asyncio.to_thread(_read, file_id)
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
    """숨기지 않았고 요약이 아직 없고(한 번만 — 다시 시작·늦은 임베딩 때 다시 부르지 않는다) 글을 뽑은 파일."""
    with db() as session:
        row = session.get(FileRow, file_id)
        return (row is not None and row.deleted_at is None and not row.summary
                and row.status in ("extracted", "indexed"))


async def after_index(file_id: int) -> None:
    """뒤 작업 줄이 파일의 임베딩을 해 본 뒤(뜻 검색이 꺼졌거나 실패해도). 예외를 내지 않는다."""
    try:
        if not await asyncio.to_thread(_waiting_for_classification, file_id):
            return
        with db() as session:
            await classify(session, file_id)
    except ClassifyFailed:
        return
    except Exception as exc:  # noqa: BLE001 — 일꾼이 임베딩 실패로 잘못 알지 않게. 종류만 남긴다
        logger.warning("분류 단계 오류: 파일 %d (%s)", file_id, type(exc).__name__)
