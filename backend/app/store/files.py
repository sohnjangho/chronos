"""파일 저장(계획 3): 받은 파일 한 벌(sha256)·글 조각·낱말 검색(FTS5)·대화 연결·숨김·완전 삭제.

원본은 <data_dir>/files/<sha[:2]>/<sha>. 같은 내용을 다시 받으면 저장·글 뽑기·뒤 작업을 다시 하지 않고 그 줄을 돌려준다
(숨긴 파일이면 다시 보이게 한다). 글을 뽑은 파일은 뒤 작업 줄(files.jobs.enqueue — 임베딩·분류)에 넣는다.
이 모듈의 쓰기 함수는 commit 한다.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from sqlalchemy import bindparam, delete, literal_column, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.files import chunk as chunking
from app.files import extract as extracting
from app.files import jobs, kinds
from app.store.schedules import NotFound
from app.store.tables import ChatSessionFile, FileAxis, FileChunk, FileRow, User

__all__ = [
    "ChunkHit", "NotAllowed", "NotFound", "Refused", "axes_of", "chunks_of", "get", "keyword_search", "link",
    "purge", "raw_path", "save_upload", "session_files", "soft_delete",
]

MAX_QUERY_TOKENS = 20
_HEAD = 16  # kind_of 가 볼 앞 바이트


class Refused(Exception):
    """받지 않는 파일. message 는 화면에 보일 안내 글."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotAllowed(Exception):
    """올린 사람도 관리자도 아니다."""


@dataclass(frozen=True)
class ChunkHit:
    file_id: int
    chunk_id: int
    seq: int
    locator: str
    text: str
    file_name: str
    score: float  # 클수록 잘 맞는다(-bm25)


def raw_path(sha256: str) -> Path:
    return Settings().data_dir / "files" / sha256[:2] / sha256


def _clean_name(name: str) -> str:
    """경로를 떼고 NFC 로 맞춘다(맥은 한글 이름을 NFD 로 보내기도 한다)."""
    return unicodedata.normalize("NFC", PurePath(name.replace("\\", "/")).name)[:255]


def _write_raw(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def _fill(session: Session, row: FileRow, path: Path) -> None:
    """글을 뽑아 조각·낱말 색인을 넣고 status·reason·pages 를 정한다(flush 까지)."""
    try:
        got = extracting.extract(path, row.kind)
    except extracting.ExtractError as e:
        row.status, row.reason = "failed", e.reason
        return
    pieces = [FileChunk(file_id=row.id, seq=c.seq, locator=c.locator, text=c.text) for c in chunking.chunks(got.text_parts)]
    session.add_all(pieces)
    session.flush()
    if pieces:
        session.execute(text("INSERT INTO file_chunks_fts(rowid, text) VALUES (:id, :text)"),
                        [{"id": p.id, "text": p.text} for p in pieces])
    row.pages = got.pages
    row.status, row.reason = "extracted", (extracting.SCANNED if got.scanned else None)


def _existing(session: Session, sha256: str) -> FileRow | None:
    row = session.scalar(select(FileRow).where(FileRow.sha256 == sha256))
    if row is not None and row.deleted_at is not None:
        row.deleted_at = None  # 숨긴 파일을 다시 올리면 다시 보인다
        session.commit()
    return row


def save_upload(session: Session, data: bytes, name: str, user: User) -> FileRow:
    """파일 하나를 받는다: 저장 → 글 뽑기 → 조각·색인. 받지 않는 파일이면 Refused. 읽지 못하면 status failed."""
    name = _clean_name(name)
    kind = kinds.kind_of(name, data[:_HEAD])
    if kind is None:
        raise Refused(kinds.refusal(name))
    sha256 = hashlib.sha256(data).hexdigest()
    if (found := _existing(session, sha256)) is not None:
        return found
    path = raw_path(sha256)
    _write_raw(path, data)
    row = FileRow(sha256=sha256, name=name, ext=kinds.ext_of(name).lstrip("."), kind=kind, size=len(data),
                  status="received", uploaded_by=user.id)
    session.add(row)
    try:
        session.flush()
    except IntegrityError:  # 같은 내용이 동시에 들어왔다
        session.rollback()
        return _existing(session, sha256)
    _fill(session, row, path)
    session.commit()
    if row.status == "extracted":
        jobs.enqueue(row.id)
    return row


def get(session: Session, file_id: int) -> FileRow:
    """파일 한 줄(숨긴 것도). 없으면 NotFound."""
    row = session.get(FileRow, file_id)
    if row is None:
        raise NotFound(file_id)
    return row


def chunks_of(session: Session, file_id: int) -> list[FileChunk]:
    return list(session.scalars(select(FileChunk).where(FileChunk.file_id == file_id).order_by(FileChunk.seq)))


def axes_of(session: Session, file_id: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for axis in session.scalars(select(FileAxis).where(FileAxis.file_id == file_id).order_by(FileAxis.axis, FileAxis.value)):
        out.setdefault(axis.axis, []).append(axis.value)
    return out


def link(session: Session, chat_id: int, file_id: int) -> None:
    """대화에 파일을 붙인다. 이미 붙어 있으면 그대로."""
    if session.get(ChatSessionFile, (chat_id, file_id)) is None:
        session.add(ChatSessionFile(session_id=chat_id, file_id=file_id))
        session.commit()


def session_files(session: Session, chat_id: int) -> list[FileRow]:
    """대화에 붙인 파일(숨긴 것도), 붙인 차례대로."""
    query = (
        select(FileRow)
        .join(ChatSessionFile, ChatSessionFile.file_id == FileRow.id)
        .where(ChatSessionFile.session_id == chat_id)
        .order_by(ChatSessionFile.attached_at, literal_column("chat_session_files.rowid"))
    )
    return list(session.scalars(query))


def _match(query: str) -> str:
    """사용자 글 → FTS5 질의. 낱말마다 앞부분 일치("C24"*), 낱말끼리 OR. FTS 문법 글자는 버린다."""
    tokens = re.findall(r"\w+", query)[:MAX_QUERY_TOKENS]
    return " OR ".join(f'"{t}"*' for t in tokens)


def keyword_search(session: Session, query: str, limit: int, file_ids: list[int] | None = None) -> list[ChunkHit]:
    """숨기지 않은 파일의 조각에서 낱말 검색(bm25 순). file_ids 를 주면 그 파일들 안에서만."""
    match = _match(query)
    if not match or file_ids == []:
        return []
    sql = (
        "SELECT c.id, c.file_id, c.seq, c.locator, c.text, f.name, bm25(file_chunks_fts) AS rank "
        "FROM file_chunks_fts JOIN file_chunks c ON c.id = file_chunks_fts.rowid JOIN files f ON f.id = c.file_id "
        "WHERE file_chunks_fts MATCH :match AND f.deleted_at IS NULL"
    )
    params: dict = {"match": match, "limit": limit}
    if file_ids is not None:
        sql += " AND c.file_id IN :ids"
        params["ids"] = file_ids
    statement = text(sql + " ORDER BY rank LIMIT :limit")
    if file_ids is not None:
        statement = statement.bindparams(bindparam("ids", expanding=True))
    rows = session.execute(statement, params).all()
    return [ChunkHit(r[1], r[0], r[2], r[3], r[4], r[5], -r[6]) for r in rows]


def soft_delete(session: Session, file_id: int, user: User) -> None:
    """숨긴다(원본·조각은 남긴다). 올린 사람이나 관리자만 — 아니면 NotAllowed."""
    row = get(session, file_id)
    if user.role != "admin" and row.uploaded_by != user.id:
        raise NotAllowed(file_id)
    if row.deleted_at is None:
        row.deleted_at = datetime.now(UTC)
        session.commit()


def purge(session: Session, file_id: int) -> None:
    """완전히 지운다: 원본·조각·낱말 색인·분류 값·대화 연결·파일 줄. 권한은 부르는 쪽이 본다(관리자)."""
    row = get(session, file_id)
    path = raw_path(row.sha256)
    session.execute(text("DELETE FROM file_chunks_fts WHERE rowid IN (SELECT id FROM file_chunks WHERE file_id = :f)"),
                    {"f": file_id})
    session.execute(delete(FileChunk).where(FileChunk.file_id == file_id))
    session.execute(delete(FileAxis).where(FileAxis.file_id == file_id))
    session.execute(delete(ChatSessionFile).where(ChatSessionFile.file_id == file_id))
    session.delete(row)
    session.commit()
    path.unlink(missing_ok=True)
