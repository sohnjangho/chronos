"""LLM 호출 실패를 화면에 보여줄 한국어 설명으로 바꾼다."""

from dataclasses import dataclass

import httpx

MESSAGES = {
    "bad_key": "API 키가 맞지 않습니다.",
    "bad_url": "주소에 연결할 수 없습니다.",
    "timeout": "응답이 너무 늦습니다.",
    "rate_limited": "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요.",
    "bad_request": "요청을 처리할 수 없습니다.",
    "server_error": "LLM 서버에 문제가 있습니다. 잠시 뒤 다시 해 주세요.",
    "unknown": "연결에 실패했습니다.",
}

_STATUS_CODES = {
    400: "bad_request",
    401: "bad_key",
    403: "bad_key",
    404: "bad_url",
    429: "rate_limited",
}
_SERVER_ERROR_FROM = 500


@dataclass(frozen=True)
class LlmError:
    code: str
    message: str


class InvalidBaseUrl(ValueError):
    """주소가 http(s) 가 아니거나 호스트가 없다."""


def _code(exc: BaseException) -> str:
    # TimeoutError: 호출 전체에 건 시간 제한(asyncio.timeout)을 넘겼다.
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status >= _SERVER_ERROR_FROM:
            return "server_error"
        return _STATUS_CODES.get(status, "unknown")
    if isinstance(
        exc, InvalidBaseUrl | httpx.InvalidURL | httpx.UnsupportedProtocol | httpx.ConnectError
    ):
        return "bad_url"
    return "unknown"


def explain(exc: BaseException) -> LlmError:
    code = _code(exc)
    return LlmError(code, MESSAGES[code])
