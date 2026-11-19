"""모든 API가 쓰는 오류 응답: {"code", "message", "detail"}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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


def error_response(status_code: int, code: str, message: str, detail: Any = None):
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail},
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


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
