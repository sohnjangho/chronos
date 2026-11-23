"""연락(outreach) 시험이 같이 쓰는 가상 값과 로그 검사. conftest 의 pytest_plugins 로 올린다.

값은 모두 가상이다(계획 4 이름표): 번호 010-0000-0199, 키 kat-test-key-ZZZZ9999.
"""

import re

from app.info.generic import key_survives

SENTINEL_PHONE = "010-0000-0199"
SENTINEL_KEY = "kat-test-key-ZZZZ9999"
SENTINEL_DIGITS = "01000000199"  # SENTINEL_PHONE 의 숫자만
_NOT_DIGIT = re.compile(r"[^0-9]")


def _leaks(line: str, texts: tuple[str, ...]) -> list[str]:
    found = []
    digits = _NOT_DIGIT.sub("", line)
    # 어느 꼴로 적혔든(줄표·빈칸·점·+82) 숫자만 남기면 이 숫자가 남는다. 가린 꼴(010-****-0199)은 걸리지 않는다.
    if SENTINEL_DIGITS in digits or SENTINEL_DIGITS[1:] in digits:
        found.append("SENTINEL_PHONE")
    found += [text for text in (SENTINEL_KEY, *texts) if text and key_survives(line, text)]
    return found


def assert_clean(caplog, *texts: str) -> None:
    """잡힌 로그(메시지·예외 글 포함)에 SENTINEL_PHONE(어느 꼴이든)·SENTINEL_KEY·texts 가 없다.

    texts 는 그 시험이 더 막는 값(Account ID 등). 키는 인코딩·섞인 꼴까지 본다(app.info.generic.key_survives).
    """
    lines = caplog.text.splitlines()
    for record in caplog.records:
        lines.append(record.getMessage())
        lines += (record.exc_text or "").splitlines()
    leaks = {leak for line in lines for leak in _leaks(line, texts)}
    assert not leaks, f"로그에 지워야 할 값이 남았습니다: {sorted(leaks)}"
