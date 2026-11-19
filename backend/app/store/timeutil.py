"""시각 표기. SQLite 는 시간대 없이 저장하므로 읽은 값을 UTC 로 붙여 내보낸다."""

from datetime import UTC, datetime


def as_utc(dt: datetime) -> datetime:
    """시간대가 없으면 UTC 로 보고 붙인다. 있으면 UTC 로 바꾼다."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
