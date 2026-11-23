"""일정 오류 코드 → 화면에 보여줄 한국어 설명 (일정 API 와 에이전트 도구가 같이 쓴다)."""

from app.core.cpm import ScheduleError

# 현장 관리자(field)가 일정 쓰기·승인 결정·상신을 하려 할 때(security.deps.require_editor 와 도구가 같이 쓴다, F4)
FIELD_READ_ONLY_MESSAGE = "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."

SCHEDULE_ERROR_MESSAGES = {
    "cycle": "선후 관계가 고리를 이룹니다.",
    "dangling_ref": "없는 액티비티를 가리키는 관계가 있습니다.",
    "bad_duration": "기간이 올바르지 않습니다.",
    "empty": "액티비티가 없습니다.",
    "no_workdays": "일할 수 있는 날이 없는 달력입니다.",
    "duplicate_id": "같은 ID의 액티비티가 있습니다.",
}


def schedule_error_message(error: ScheduleError) -> str:
    return SCHEDULE_ERROR_MESSAGES[error.code]
