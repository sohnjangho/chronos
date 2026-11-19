"""모든 API가 쓰는 오류 응답: {"code", "message", "detail"}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

_HTTP_ERRORS = {
    404: ("not_found", "찾을 수 없습니다."),
    405: ("method_not_allowed", "허용되지 않는 요청입니다."),
}


class ApiError(Exception):
    """화면에 보여줄 한국어 message 와 기계가 읽을 code 를 함께 던진다."""

    def __init__(
        self, status_code: int, code: str, message: str, detail: Any = None
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def error_response(
    status_code: int,
    code: str,
    message: str,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail},
        headers=headers,
    )


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.detail)


async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    # 보낸 값(input)은 돌려주지 않는다 — 비밀번호가 섞일 수 있다.
    detail = [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return error_response(422, "invalid_request", "요청 형식이 올바르지 않습니다.", detail)


async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code, message = _HTTP_ERRORS.get(
        exc.status_code, ("http_error", "요청을 처리할 수 없습니다.")
    )
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # 오류 내용은 서버 기록에만 남긴다. 요청 본문·머리글은 남기지 않는다.
    logger.error(
        "처리하지 못한 오류: %s %s", request.method, request.url.path, exc_info=exc
    )
    return error_response(500, "internal_error", "서버에서 문제가 생겼습니다.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
