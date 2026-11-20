from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.files import service
from app.programs.files.schemas import FileOut, PreviewOut, UploadOut
from app.security.deps import current_user
from app.store.tables import User

# 로그인한 누구나(보는 범위는 지금 회사 전체). 지우기는 올린 사람·관리자, 완전히 지우기는 관리자(service).
# 몸 크기·로그인은 guard.UploadGuard 가 몸을 읽기 전에 본다. 글 뽑기는 CPU 를 쓰므로 스레드에서 돈다.
router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.post("")
async def upload(request: Request, session: SessionDep, user: UserDep) -> UploadOut:
    """multipart: 파일 칸 `files`(반복), 선택 `chat_id`. 파일 칸은 MAX_FILES + 1 개까지만 푼다(넘으면 400)."""
    async with request.form(max_files=service.MAX_FILES + 1, max_fields=service.MAX_FIELDS) as form:
        files = [v for v in form.getlist("files") if not isinstance(v, str)]
        chat_id = form.get("chat_id")
        return await run_in_threadpool(service.upload, session, user, files, chat_id)


@router.get("/{file_id}")
def get_file(session: SessionDep, file_id: int) -> FileOut:
    return service.get_file(session, file_id)


@router.get("/{file_id}/raw")
def raw(session: SessionDep, file_id: int) -> FileResponse:
    return service.raw(session, file_id)


@router.get("/{file_id}/preview")
def preview(session: SessionDep, file_id: int, page: Annotated[int, Query(ge=1)] = 1) -> PreviewOut:
    return service.preview(session, file_id, page)


@router.delete("/{file_id}", status_code=204)
def delete(session: SessionDep, user: UserDep, file_id: int, purge: bool = False) -> Response:
    service.delete(session, user, file_id, purge)
    return Response(status_code=204)
