"""그림 턴(설계 5-5): 이번 메시지에 붙인 파일을 대화에 잇고, 그림은 LLM 메시지에 image_url 로 끼우며,
그 턴의 루프 호출을 「그림 읽기」(vision) 배정으로 바꾼다. 에이전트 루프(app.agent.loop)가 부른다.

- 이번 메시지(MessageIn.file_ids)에 그림(kind image, 지우지 않은 것)이 있으면 그 턴의 모든 루프 호출이 vision 이고
  이번 사용자 메시지에 그림들을 붙인다. 대화 모델을 골랐어도 그 턴만 바뀐다(resolve("vision") 은 대화 모델을 따르지
  않는다). 도구 안의 LLM 호출은 배정 그대로다. 다음 턴부터는 그림 대신 글(「이 대화에 붙인 파일」 줄의 요약)만 간다.
- files.read 가 image true 를 돌려주면, 그 응답의 도구 결과를 다 붙인 뒤 그 그림을 user 메시지로 끼우고
  그 단계부터 턴 끝까지 vision 이다.
- vision 으로 바뀌면 notice 사건을 턴에 한 번 낸다(저장하지 않는다).
- 그림은 저장된 파일(브라우저가 긴 변 1568px 로 줄인 사본)을 data URI 로 그대로 보낸다. base64 길이가 IMAGE_MAX_BYTES 를
  넘거나(fits — 제공자 한도는 base64 기준) 원본을 읽지 못하면 그림 대신 글 한 줄. 같은 그림은 한 턴에 한 번만 붙인다.
- 그림을 보낸 호출이 거절되면(RETRY_CODES) 그림 조각을 글 한 줄로 바꿔 한 번만 다시 부르고(fallback), 그 턴에는
  그림을 더 붙이지 않는다. 붙이지 않은 그림은 files.read 결과의 image_note 에 까닭을 적는다.
- 끼운 그림은 DB 에 저장하지 않는다(보낼 메시지 목록에만). 실행 추적에는 data URI 대신 「(그림)」을 남긴다(for_trace).
"""

import base64
import logging
import math
from collections.abc import Iterable
from dataclasses import replace

from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.files import kinds
from app.llm.assignments import resolve
from app.store import files as file_store
from app.store.tables import ChatSessionFile, FileRow
from app.tools.registry import ToolResult

logger = logging.getLogger(__name__)

IMAGE_MAX_BYTES = 5 * 1024 * 1024  # base64 로 바꾼 길이가 이보다 크면 보내지 않는다(제공자 그림 한도)
READ_TOOL = "files.read"
NOTICE = "그림이 있어 그림 읽기 모델({model})로 답합니다."
NOT_READY_MESSAGE = "그림 읽기 모델 연결이 없습니다 — 설정 → 작업별 모델 배정에서 「그림 읽기」를 정해 주세요"
TRACE_IMAGE = "(그림)"
# 그림 때문일 수 있는 거절(400). 402(크레딧)·413 은 대화 호출에서 둘 다 unknown 이라 가르지 못해 다시 하지 않는다.
RETRY_CODES = frozenset({"bad_request"})
REFUSED = "모델이 그림을 받지 못해 보내지 않았습니다"
ALREADY_NOTE = "이 턴에 이미 붙인 그림입니다. 앞의 그림을 보세요."
REFUSED_NOTE = "모델이 그림을 받지 못해 붙이지 않았습니다. 설명 글(parts)을 쓰세요."


def fits(size: int) -> bool:
    """원본 size 바이트 그림의 base64 길이가 IMAGE_MAX_BYTES 안인가."""
    return 4 * math.ceil(size / 3) <= IMAGE_MAX_BYTES


def picked(session: Session, file_ids: Iterable[int]) -> list[FileRow]:
    """이번 메시지에 붙인 파일(같은 id 는 한 번, 보낸 차례). 없는 id 는 뺀다(대화 API 가 먼저 거른다)."""
    rows = [session.get(FileRow, file_id) for file_id in dict.fromkeys(file_ids)]
    return [row for row in rows if row is not None]


def refs(rows: list[FileRow]) -> dict:
    """사용자 메시지 content 에 더할 칸 {"files": [{file_id, name, kind}]}. 붙인 파일이 없으면 {}."""
    return {"files": [{"file_id": r.id, "name": r.name, "kind": r.kind} for r in rows]} if rows else {}


def attach(session: Session, chat_id: int, rows: list[FileRow]) -> None:
    """대화에 붙인다(이미 붙어 있으면 그대로). commit 은 부르는 쪽(사용자 메시지와 같은 commit)."""
    for row in rows:
        if session.get(ChatSessionFile, (chat_id, row.id)) is None:
            session.add(ChatSessionFile(session_id=chat_id, file_id=row.id))


def _note(file_id: int, name: str, why: str) -> dict:
    return {"type": "text", "text": f"(그림 #{file_id} {name}: {why})"}


def image_part(row: FileRow) -> dict:
    """그림 하나를 메시지 조각으로: image_url(data URI). 크거나 원본을 읽지 못하면 글 조각."""
    if not fits(row.size):
        return _note(row.id, row.name, "커서 보내지 않았습니다")
    try:
        data = file_store.raw_path(row.sha256).read_bytes()
    except OSError as exc:
        logger.warning("그림 원본을 읽지 못했습니다: file=%s (%s)", row.id, type(exc).__name__)
        return _note(row.id, row.name, "원본을 읽을 수 없어 보내지 않았습니다")
    media = kinds.MEDIA_TYPES.get(f".{row.ext}", "image/png")
    return {"type": "image_url", "image_url": {"url": f"data:{media};base64,{base64.b64encode(data).decode()}"}}


def for_trace(messages: list[dict]) -> list[dict]:
    """실행 추적에 남길 사본: 그림 조각의 data URI 를 「(그림)」으로 바꾼다."""
    out = []
    for m in messages:
        if isinstance(m.get("content"), list):
            parts = [{**p, "image_url": {"url": TRACE_IMAGE}} if p.get("type") == "image_url" else p for p in m["content"]]
            m = {**m, "content": parts}
        out.append(m)
    return out


class Vision:
    """한 턴의 그림 상태: 지금 vision 인가, 다음 호출 앞에 끼울 그림, 붙인 그림, 거절됐는가, 안내를 냈는가."""

    def __init__(self) -> None:
        self.on = False
        self.noticed = False
        self.refused = False  # 모델이 그림을 거절해 글로 바꿨다 — 이 턴에는 더 붙이지 않는다
        self.pending: list[int] = []  # files.read {image: true} 로 다시 볼 그림(file id)
        self.shown: set[int] = set()  # 이 턴에 붙였거나 붙일 그림(file id)
        self._sent: dict[str, tuple[int, str]] = {}  # 보낸 data URI → (file id, 이름). 거절되면 글로 바꾸려고

    @property
    def purpose(self) -> str:
        """루프 호출의 쓰임새."""
        return "vision" if self.on else "normal"

    def _part(self, row: FileRow) -> dict:
        self.shown.add(row.id)
        part = image_part(row)
        if part["type"] == "image_url":
            self._sent[part["image_url"]["url"]] = (row.id, row.name)
        return part

    def start(self, messages: list[dict], rows: list[FileRow]) -> None:
        """이번 메시지의 그림을 마지막 사용자 메시지에 붙이고 vision 으로 바꾼다. 그림이 없으면 그대로."""
        images = [r for r in rows if r.kind == "image" and r.deleted_at is None]
        if not images:
            return
        i = max(n for n, m in enumerate(messages) if m["role"] == "user")
        text = {"type": "text", "text": messages[i]["content"]}
        messages[i] = {**messages[i], "content": [text, *(self._part(r) for r in images)]}
        self.on = True

    def after_tool(self, name: str, result: ToolResult) -> ToolResult:
        """files.read 가 그림을 다시 보겠다고 했으면(image true) 끼울 그림으로 둔다. 이 턴에 이미 붙였거나 그림이
        거절된 턴이면 붙이지 않고, 모델이 볼 결과를 image false + image_note(까닭)로 바꿔 돌려준다."""
        if name != READ_TOOL or not result.ok or result.output.get("image") is not True:
            return result
        file_id = result.output["file_id"]
        note = REFUSED_NOTE if self.refused else ALREADY_NOTE if file_id in self.shown else None
        if note is not None:
            return replace(result, output={**result.output, "image": False, "image_note": note})
        self.shown.add(file_id)
        self.pending.append(file_id)
        return result

    def flush(self, session: Session, messages: list[dict]) -> list[AgentEvent]:
        """LLM 을 부르기 전: 끼울 그림을 user 메시지로 붙이고(→ vision), 처음 vision 이 되면 notice 하나."""
        for row in filter(None, (session.get(FileRow, file_id) for file_id in self.pending)):
            label = {"type": "text", "text": f"files__read 로 다시 연 그림 #{row.id} {row.name}"}
            messages.append({"role": "user", "content": [label, self._part(row)]})
            self.on = True
        self.pending = []
        if not self.on or self.noticed:
            return []
        self.noticed = True
        return [AgentEvent("notice", {"text": NOTICE.format(model=resolve(session, "vision").model)})]

    def fallback(self, messages: list[dict], error: dict | None) -> bool:
        """그림을 보낸 호출이 RETRY_CODES 로 거절됐으면 그림 조각을 글 한 줄로 바꾸고 True(한 턴에 한 번).
        그 밖이면 그대로 두고 False."""
        if self.refused or not self._sent or (error or {}).get("reason") not in RETRY_CODES:
            return False
        for i, m in enumerate(messages):
            if isinstance(m.get("content"), list):
                parts = [_note(*self._sent[p["image_url"]["url"]], REFUSED) if p.get("type") == "image_url" else p
                         for p in m["content"]]
                messages[i] = {**m, "content": parts}
        self.refused, self._sent = True, {}
        return True
