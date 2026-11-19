"""일정 오류 코드 → 한국어 설명 표 (일정 API 와 도구가 같이 쓴다)."""

from typing import get_args

from app.core.cpm import ErrorCode, ScheduleError
from app.store.messages import SCHEDULE_ERROR_MESSAGES, schedule_error_message


def test_every_schedule_error_code_has_a_message():
    assert set(SCHEDULE_ERROR_MESSAGES) == set(get_args(ErrorCode))


def test_schedule_error_message():
    assert schedule_error_message(ScheduleError("cycle", {})) == "선후 관계가 고리를 이룹니다."
