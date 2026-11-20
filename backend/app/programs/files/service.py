"""파일 API: 받기(한도 검사 뒤 저장·글 뽑기·대화 연결)·한 줄 읽기·원본·보기·숨김·완전 삭제.

받기는 먼저 모든 파일의 개수·크기·형식을 보고, 하나라도 어긋나면 아무것도 저장하지 않는다.
응답은 글 뽑기까지 끝낸 상태(extracted·failed)다. 보는 범위는 지금 회사 전체(로그인한 누구나).
"""

from typing import BinaryIO

from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.errors import ApiError
from app.files import chunk, jobs, kinds
from app.llm import assignments
from app.programs.files.schemas import (
    FileOut,
    PreviewOut,
    ReindexJobOut,
    ReindexStartOut,
    ReindexStatusOut,
    UploadItem,
    UploadOut,
)
from app.store import chats, files
from app.store.tables import FileChunk, FileRow, ReindexJob, User

MAX_FILES = 10
MAX_FIELDS = 5  # 파일 아닌 칸(chat_id)
MAX_BYTES = 50 * 1024 * 1024
PREVIEW_CHARS = 20_000

TOO_BIG = "파일이 너무 큽니다(50MB까지)"
TOO_MANY = "한 번에 10개까지 올릴 수 있습니다"
NOT_FOUND = "파일을 찾을 수 없습니다."
DELETED = "지워진 파일입니다"
CHAT_NOT_FOUND = "대화를 찾을 수 없습니다."
NO_FILES = "올릴 파일을 골라 주세요."
BAD_CHAT_ID = "chat_id 가 올바르지 않습니다."
DELETE_FORBIDDEN = "올린 사람이나 관리자만 지울 수 있습니다."
PURGE_FORBIDDEN = "관리자만 완전히 지울 수 있습니다."
NOTHING_TO_REINDEX = "지금 검색에 쓰는 모델이 배정된 임베딩 모델과 같아 다시 넣을 것이 없습니다."


def _size(f: BinaryIO) -> int:
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size


def _check(uploads: list[UploadFile]) -> None:
    if not uploads:
        raise ApiError(422, "invalid_request", NO_FILES)
    if len(uploads) > MAX_FILES:
        raise ApiError(422, "too_many_files", TOO_MANY)
    for u in uploads:
        name = u.filename or ""
        head = u.file.read(16)
        u.file.seek(0)
        if kinds.kind_of(name, head) is None:
            raise ApiError(422, "file_refused", kinds.refusal(name), {"name": name})
        if _size(u.file) > MAX_BYTES:
            raise ApiError(413, "file_too_large", TOO_BIG, {"name": name})


def _own_chat(session: Session, user: User, chat_id: int) -> None:
    try:
        chat = chats.get_chat(session, chat_id)
    except chats.NotFound:
        chat = None
    if chat is None or chat.user_id != user.id:
        raise ApiError(404, "not_found", CHAT_NOT_FOUND)


def _chat_id(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not raw.isdigit():
        raise ApiError(422, "invalid_request", BAD_CHAT_ID)
    return int(raw)


def upload(session: Session, user: User, uploads: list[UploadFile], raw_chat_id: object) -> UploadOut:
    _check(uploads)
    chat_id = _chat_id(raw_chat_id)
    if chat_id is not None:
        _own_chat(session, user, chat_id)
    items = []
    for u in uploads:
        try:
            row = files.save_upload(session, u.file.read(), u.filename or "", user)
        except files.Refused as e:  # _check 가 이미 보았으므로 오지 않는다
            raise ApiError(422, "file_refused", e.message, {"name": u.filename}) from None
        if chat_id is not None:
            files.link(session, chat_id, row.id)
        items.append(UploadItem(file_id=row.id, name=row.name, kind=row.kind, status=row.status, reason=row.reason))
    return UploadOut(items=items)


def _row(session: Session, file_id: int, *, visible: bool = False) -> FileRow:
    try:
        row = files.get(session, file_id)
    except files.NotFound:
        raise ApiError(404, "not_found", NOT_FOUND) from None
    if visible and row.deleted_at is not None:
        raise ApiError(404, "deleted", DELETED)
    return row


def get_file(session: Session, file_id: int) -> FileOut:
    row = _row(session, file_id)
    return FileOut(
        file_id=row.id, name=row.name, ext=row.ext, kind=row.kind, size=row.size, status=row.status, reason=row.reason,
        uploaded_by=row.uploaded_by, uploaded_at=row.uploaded_at, pages=row.pages, summary=row.summary,
        deleted=row.deleted_at is not None, axes=files.axes_of(session, row.id),
    )


def raw(session: Session, file_id: int) -> FileResponse:
    row = _row(session, file_id, visible=True)
    path = files.raw_path(row.sha256)
    if not path.exists():
        raise ApiError(404, "not_found", NOT_FOUND)
    media = kinds.MEDIA_TYPES.get(f".{row.ext}", "application/octet-stream")
    return FileResponse(path, media_type=media, filename=row.name, content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff"})


def _join(pieces: list[FileChunk]) -> str:
    """같은 위치의 이어진 조각은 겹친 앞 글을 지우고 잇는다. 위치가 바뀌면 줄을 바꾼다."""
    out, last = [], None
    for p in pieces:
        out.append(p.text[chunk.OVERLAP:] if p.locator == last else ("\n" if out else "") + p.text)
        last = p.locator
    return "".join(out)


def _page_pieces(row: FileRow, pieces: list[FileChunk], page: int) -> list[FileChunk]:
    if row.kind == "pdf":
        return [p for p in pieces if p.locator == f"{page}쪽"]
    if row.kind == "sheet":
        sheets = list(dict.fromkeys(p.locator.rsplit(" 행 ", 1)[0] for p in pieces))
        if page > len(sheets):
            return []
        return [p for p in pieces if p.locator.rsplit(" 행 ", 1)[0] == sheets[page - 1]]
    return pieces if page == 1 else []


def preview(session: Session, file_id: int, page: int) -> PreviewOut:
    row = _row(session, file_id, visible=True)
    paged = row.kind in ("pdf", "sheet")
    body = _join(_page_pieces(row, files.chunks_of(session, row.id), page))
    return PreviewOut(file_id=row.id, kind=row.kind, page=page, pages=(row.pages or 1) if paged else 1,
                      text=body[:PREVIEW_CHARS], truncated=len(body) > PREVIEW_CHARS)


def delete(session: Session, user: User, file_id: int, purge: bool) -> None:
    _row(session, file_id)
    if purge:
        if user.role != "admin":
            raise ApiError(403, "admin_only", PURGE_FORBIDDEN)
        files.purge(session, file_id)
        jobs.forget(file_id)  # 뜻 검색(Qdrant) 점도 지운다
        return
    try:
        files.soft_delete(session, file_id, user)
    except files.NotAllowed:
        raise ApiError(403, "forbidden", DELETE_FORBIDDEN) from None


def _latest_job(session: Session) -> ReindexJob | None:
    return session.scalar(select(ReindexJob).order_by(ReindexJob.id.desc()).limit(1))


def reindex_status(session: Session) -> ReindexStatusOut:
    job = _latest_job(session)
    return ReindexStatusOut(
        active_model=jobs.active_model(session), assigned_model=assignments.resolve(session, "embedding").model,
        job=ReindexJobOut.model_validate(job) if job is not None else None,
    )


def start_reindex(session: Session) -> ReindexStartOut:
    """배정된 임베딩 모델로 다시 넣기를 (다시) 시작한다 — 실패한 바꾸기를 이어 하거나 지금 모델로 다시 넣을 때."""
    assigned = assignments.resolve(session, "embedding").model
    job = _latest_job(session)
    status = job.status if job is not None else None
    if status not in ("running", "failed") and assigned == jobs.active_model(session):
        raise ApiError(409, "nothing_to_do", NOTHING_TO_REINDEX)
    try:
        return ReindexStartOut(**jobs.enqueue_reindex(assigned))
    except jobs.ReindexRefused as e:
        if e.code == "running":
            raise ApiError(409, "already_running", e.message) from None
        raise ApiError(503, "reindex_unavailable", e.message) from None
