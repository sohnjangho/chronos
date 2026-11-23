"""연락 상대의 근무시간 — 순수 계산(DB·시계 없음, 시각은 부르는 쪽이 준다).

- `hours` 가 비면(None·{}) 프로젝트 달력의 근무일(`WorkCalendar.is_workday`) + 08:00~18:00.
- `hours = {"days": [0..6](월=0), "start": "HH:MM", "end": "HH:MM"}` 이면 그 요일·시각. 프로젝트 공휴일은 그래도 쉰다.
- 끝이 시작보다 이르거나 같으면 자정을 넘는 근무(같으면 꼭 하루). 근무 시간대는 시작한 날에 속한다
  — 시작한 날이 근무일이어야 하고, 끝자락이 다음 날(공휴일이어도) 새벽에 걸칠 수 있다.
- 시작 시각은 안, 끝 시각은 밖. 받은 시각은 KST 로 바꿔 본다(시간대가 없으면 UTC — SQLite 규칙).
  돌려주는 시각은 모두 KST 시간대가 붙어 있다.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.calendar import WorkCalendar
from app.core.model import CalendarSpec

KST = ZoneInfo("Asia/Seoul")
DEFAULT_START = time(8, 0)
DEFAULT_END = time(18, 0)

_DAY = timedelta(days=1)
_MAX_DAYS = 732  # 다음 근무 시작을 찾아 훑는 한도(약 2년)
_WEEKDAYS = "월화수목금토일"


def _to_kst(at: datetime) -> datetime:
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(KST)


def _rule(hours: dict | None, calendar: CalendarSpec) -> tuple[Callable[[date], bool], time, time]:
    """(그날 근무가 시작되나, 시작, 끝)."""
    if not hours:
        return WorkCalendar(calendar).is_workday, DEFAULT_START, DEFAULT_END
    days = frozenset(hours["days"])
    holidays = frozenset(calendar.holidays)
    return (
        lambda d: d.weekday() in days and d not in holidays,
        time.fromisoformat(hours["start"]),
        time.fromisoformat(hours["end"]),
    )


def _period(d: date, start: time, end: time) -> tuple[datetime, datetime]:
    begin = datetime.combine(d, start, tzinfo=KST)
    finish = datetime.combine(d, end, tzinfo=KST)
    if end <= start:  # 자정을 넘는 근무
        finish += _DAY
    return begin, finish


def _current(hours: dict | None, calendar: CalendarSpec, k: datetime) -> tuple[datetime, datetime] | None:
    """k(KST) 가 들어 있는 근무 시간대. 어제 시작해 자정을 넘은 것도 본다."""
    works, start, end = _rule(hours, calendar)
    for day in (k.date() - _DAY, k.date()):
        if works(day):
            begin, finish = _period(day, start, end)
            if begin <= k < finish:
                return begin, finish
    return None


def is_working(hours: dict | None, calendar: CalendarSpec, now: datetime) -> bool:
    return _current(hours, calendar, _to_kst(now)) is not None


def next_start(hours: dict | None, calendar: CalendarSpec, now: datetime) -> datetime:
    """지금 근무 중이면 now(KST), 아니면 그 뒤 첫 근무 시작. 약 2년 안에 없으면 ValueError."""
    k = _to_kst(now)
    if _current(hours, calendar, k) is not None:
        return k
    works, start, end = _rule(hours, calendar)
    for i in range(_MAX_DAYS):
        day = k.date() + i * _DAY
        begin = _period(day, start, end)[0]
        if works(day) and begin > k:
            return begin
    raise ValueError("근무 시간대를 찾지 못했습니다")


def clamp(hours: dict | None, calendar: CalendarSpec, at: datetime) -> datetime:
    """근무시간 안이면 그대로(KST), 아니면 그 뒤 첫 근무 시작."""
    return next_start(hours, calendar, at)


def label(hours: dict | None, calendar: CalendarSpec, now: datetime) -> str:
    """「근무 중 · 18:00 까지」 / 「근무 밖 · 월 08:00 부터」."""
    k = _to_kst(now)
    current = _current(hours, calendar, k)
    if current is not None:
        return f"근무 중 · {current[1]:%H:%M} 까지"
    begin = next_start(hours, calendar, k)
    return f"근무 밖 · {_WEEKDAYS[begin.weekday()]} {begin:%H:%M} 부터"
