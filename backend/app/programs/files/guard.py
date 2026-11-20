"""POST /api/files 의 몸을 읽기 전에 막는 ASGI 미들웨어.

FastAPI 는 multipart 몸을 의존성(current_user)보다 먼저 읽는다. 그래서 여기서 먼저 본다:
로그인 토큰 서명이 없거나 틀리면 401, Content-Length 가 없으면 411, 한도(10개 × 50MB + 여유 1MB)를 넘으면 413.
사용자가 DB 에 있는지·관리자인지는 라우터의 의존성이 다시 본다.
"""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import error_response
from app.programs.files.service import MAX_BYTES, MAX_FILES
from app.security.tokens import read_token

PATH = "/api/files"
MAX_BODY_BYTES = MAX_FILES * MAX_BYTES + 1024 * 1024  # multipart 머리·경계 여유

UNAUTHORIZED = "다시 로그인해 주세요."
NO_LENGTH = "올리는 크기를 알 수 없습니다. 다시 올려 주세요."
TOO_BIG_BODY = "한 번에 올릴 수 있는 크기를 넘었습니다(파일당 50MB · 10개까지)"


def _problem(headers: Headers) -> tuple[int, str, str] | None:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or read_token(token.strip()) is None:
        return 401, "unauthorized", UNAUTHORIZED
    length = headers.get("content-length", "")
    if not length.isdigit():
        return 411, "length_required", NO_LENGTH
    if int(length) > MAX_BODY_BYTES:
        return 413, "file_too_large", TOO_BIG_BODY
    return None


class UploadGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"].rstrip("/") == PATH:
            problem = _problem(Headers(scope=scope))
            if problem is not None:
                await error_response(*problem)(scope, receive, send)
                return
        await self.app(scope, receive, send)
