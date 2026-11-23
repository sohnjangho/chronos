"""음성 진단 동안 SDK 로거의 줄을 지우고 준비 표시 파일을 끄는 문맥(계획 4 Task 60 — diagnostics_voice.py 에서 옮김)."""

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager

_marker = {"holders": 0, "saved": None}  # 겹쳐 도는 진단이 있어도 준비 표시 환경 변수를 처음 값으로 되돌린다


@contextmanager
def _quiet_sdk(clean: Callable[[object, int], str], logger_names: tuple[str, ...], ready_env: str) -> Iterator[None]:
    """진단 동안: SDK 로거의 줄을 지운 글로 바꾸고(예외는 종류 이름만), SDK 의 준비 표시 파일을 끈다. 끝나면 되돌린다."""

    def guard(record: logging.LogRecord) -> bool:
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
