from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.files import classify
from app.programs.files import service
from app.programs.files.schemas import (
    AxisValueOut,
    FileListOut,
    FileOut,
    MergeIn,
    MergeOut,
    MergeSuggestionsOut,
    PreviewOut,
    ReindexStartOut,
    ReindexStatusOut,
    UploadOut,
)
from app.security.deps import current_user, require_admin
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


@router.get("")
async def list_files(
    request: Request, session: SessionDep, q: str | None = None, page: Annotated[int, Query(ge=1)] = 1,
) -> FileListOut:
    """자료함 목록. 축 거르기는 축 이름 그대로 질의에(`?종류=시방서&공종=골조&공종=전기` — 같은 축은 하나라도,
    다른 축은 모두). q 는 이름·내용(뜻+낱말) 찾기. 한 쪽 PAGE_SIZE 개."""
    filters = {axis: values for axis in classify.AXES if (values := request.query_params.getlist(axis))}
    return await service.list_files(session, q, filters, page)


# /reindex·/axes·/merge… 는 /{file_id} 보다 먼저(경로 차례로 맞춘다).
@router.get("/axes")
def axes(session: SessionDep) -> dict[str, list[AxisValueOut]]:
    """축 다섯 개 모두 → [{value, count, is_new}] (파일 많은 차례)."""
    return service.axes(session)


@router.get("/merge-suggestions", dependencies=[Depends(require_admin)])
def merge_suggestions(session: SessionDep) -> MergeSuggestionsOut:
    """하루 한 번 에이전트가 만든 값 합치기 제안(관리자). 이미 합친 값의 제안은 빠진다."""
    return service.merge_suggestions(session)


@router.post("/merge", dependencies=[Depends(require_admin)])
def merge(session: SessionDep, body: MergeIn) -> MergeOut:
    """{axis, from: [값], to: 값} — from 값의 파일을 to 로 옮기고 from 값을 지운다(관리자)."""
    return service.merge(session, body)


@router.get("/reindex")
def reindex_status(session: SessionDep) -> ReindexStatusOut:
    """지금 검색 모델·배정 모델·마지막 다시 넣기(진행률)."""
    return service.reindex_status(session)


@router.post("/reindex", status_code=202, dependencies=[Depends(require_admin)])
def start_reindex(session: SessionDep) -> ReindexStartOut:
    """배정 모델로 다시 넣기를 (다시) 시작한다(관리자). 진행 중 409 already_running · 할 일 없음 409 nothing_to_do ·
    Qdrant 가 안 되거나 뜻 검색이 꺼졌으면 503."""
    return service.start_reindex(session)


@router.get("/{file_id}")
def get_file(session: SessionDep, file_id: int) -> FileOut:
    return service.get_file(session, file_id)


@router.patch("/{file_id}/axes")
def patch_axes(session: SessionDep, file_id: int, body: Annotated[dict[str, list[str]], Body()]) -> FileOut:
    """{축: [값]} — 보낸 축만 바꾼다(로그인한 누구나). 숨긴 파일 404."""
    return service.patch_axes(session, file_id, body)


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
