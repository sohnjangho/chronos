"""음성 진단 동안 SDK 로거의 줄을 지우고 준비 표시 파일을 끄는 문맥(계획 4 Task 60 — diagnostics_voice.py 에서 옮김)."""

import logging
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager

_SESSION_FAILED = re.compile(r"Session start failed for (\S+?): ")  # SDK(clawops.agent)가 AI 음성 모델 세션을 열지 못한 줄
_HTTP = re.compile(r"\bHTTP (\d{3})\b")
_MODEL_ERROR = "OpenAI error:"  # SDK(OpenAIRealtime)가 모델의 오류 사건을 받으면 남기는 줄의 머리 — 세션은 그대로 돈다
_marker = {"holders": 0, "saved": None}  # 겹쳐 도는 진단이 있어도 준비 표시 환경 변수를 처음 값으로 되돌린다


@contextmanager
def _quiet_sdk(clean: Callable[[object, int], str], logger_names: tuple[str, ...], ready_env: str,
               watch: Callable[[logging.LogRecord], None] | None = None) -> Iterator[None]:
    """진단 동안: SDK 로거의 줄을 지운 글로 바꾸고(예외는 종류 이름만), SDK 의 준비 표시 파일을 끈다. 끝나면 되돌린다.
    `watch` 는 지우기 **전의** 줄을 한 번 본다(진단이 알아야 할 사건 — 남기지 않고 읽기만, 던져도 삼킨다)."""

    def guard(record: logging.LogRecord) -> bool:
        if watch is not None:
            try:
                watch(record)
            except Exception:  # noqa: BLE001, S110 — 로그를 남긴 SDK 코드로 올리지 않는다
                pass
        try:
            text = record.getMessage()
            if record.exc_info and record.exc_info[0] is not None:
                text += f" ({record.exc_info[0].__name__})"
            text = clean(text, 300)
        except Exception:  # noqa: BLE001 — 로그를 남긴 SDK 코드로 올리지 않는다
            text = "(음성 SDK 로그 줄을 지우지 못해 숨겼습니다)"
        record.msg, record.args, record.exc_info, record.exc_text, record.stack_info = text, None, None, None, None
        return True

    loggers = [logging.getLogger(name) for name in logger_names]
    for logger in loggers:
        logger.addFilter(guard)
    if _marker["holders"] == 0:
        _marker["saved"] = os.environ.get(ready_env)
    _marker["holders"] += 1
    os.environ[ready_env] = ""
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(guard)
        _marker["holders"] -= 1
        if _marker["holders"] == 0:
            os.environ.pop(ready_env, None)
            if _marker["saved"] is not None:
                os.environ[ready_env] = _marker["saved"]


def _http_status(error: object) -> int | None:
    """예외(와 그 원인 사슬, 다섯 단계까지)에서 HTTP 상태만 — websockets 의 response.status_code · status_code · code · status."""
    for _ in range(5):
        if error is None:
            return None
        for found in (getattr(getattr(error, "response", None), "status_code", None),
                      *(getattr(error, name, None) for name in ("status_code", "code", "status"))):
            if type(found) is int and 100 <= found <= 599:
                return found
        error = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    return None


def session_failure(record: logging.LogRecord) -> tuple[str, int | None] | None:
    """「Session start failed for <통화 id>: <예외>」 줄이면 (통화 id, HTTP 상태), 아니면 None. 앱의 로그 거르개가 먼저 글로 바꿔
    예외를 종류만 남겼을 수 있어, 예외가 있으면 그 사슬에서, 없으면 줄 글과 exc_text 의 「HTTP nnn」에서 상태를 읽는다."""
    try:
        text = record.getMessage()
    except Exception:  # noqa: BLE001 — 읽지 못하는 줄은 보지 않는다
        return None
    found = _SESSION_FAILED.match(text)
    if found is None:
        return None
    error = record.exc_info[1] if isinstance(record.exc_info, tuple) else None
    status = _http_status(error)
    if status is None:
        code = _HTTP.search(f"{text}\n{record.exc_text or ''}")
        status = int(code.group(1)) if code else None
    return found.group(1), status


def model_error(record: logging.LogRecord) -> bool:
    """「OpenAI error: …」 줄인가(OpenAIRealtime 이 모델의 오류 사건을 받은 줄 — 세션 설정이 거절돼도 이것뿐이다). 글은 남기지 않는다."""
    try:
        return record.getMessage().startswith(_MODEL_ERROR)
    except Exception:  # noqa: BLE001 — 읽지 못하는 줄은 보지 않는다
        return False
