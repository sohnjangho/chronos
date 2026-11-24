"""내 사진 배경 — 로그인한 본인 것만(경로에 사람 id 가 없다). 한 사람에 한 장, 새로 올리면 덮어쓴다.

PUT 본문은 그림 바이트 그대로. 형식은 머리글이 아니라 앞 바이트로 본다(JPG·PNG·WebP), 10MB 까지(Content-Length 로 먼저,
읽으며 다시 잰다), 가로·세로 8000 까지. 응답에 파일 이름·경로·EXIF 를 싣지 않는다(형식·크기만).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.errors import ApiError
from app.programs.wallpaper.image import sniff
from app.security.deps import current_user
from app.store import wallpapers
from app.store.tables import User

router = APIRouter(prefix="/api/me/wallpaper", tags=["wallpaper"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 8000


def _too_large() -> ApiError:
    return ApiError(413, "wallpaper_too_large", "사진이 너무 큽니다. 10MB 까지 올릴 수 있습니다.")


async def _read_limited(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:  # 읽기 전에 막는다
        raise _too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


@router.put("")
async def put_wallpaper(request: Request, session: SessionDep, user: UserDep) -> dict[str, Any]:
    data = await _read_limited(request)
    found = sniff(data)
    if found is None:
        raise ApiError(415, "wallpaper_bad_type", "JPG·PNG·WebP 사진만 올릴 수 있습니다.")
    mime, width, height = found
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ApiError(422, "wallpaper_too_wide", "사진이 너무 큽니다. 가로·세로 8000픽셀까지 올릴 수 있습니다.")
    at = await run_in_threadpool(wallpapers.put, session, user, mime, width, height, data)
    return {"type": mime, "width": width, "height": height, "bytes": len(data), "updated_at": at}


@router.get("")
def get_wallpaper(session: SessionDep, user: UserDep) -> Response:
    row = wallpapers.get(session, user)
    if row is None:
        raise ApiError(404, "wallpaper_none", "올린 사진이 없습니다.")
    return Response(
        content=row.data,
        media_type=row.mime,
        headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("", status_code=204)
def delete_wallpaper(session: SessionDep, user: UserDep) -> None:
    wallpapers.delete(session, user)
