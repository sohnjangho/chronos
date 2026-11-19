"""로그인 토큰: Settings.secret_key 로 서명한 사용자 id, 12시간 동안 유효."""

from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import Settings

TOKEN_MAX_AGE_SECONDS = 12 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Settings().secret_key, salt="chronos-auth")


def issue_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_token(token: str) -> int | None:
    """서명이 맞고 만료 전이면 사용자 id, 아니면 None."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except BadData:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
