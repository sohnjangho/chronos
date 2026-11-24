"""로그인 토큰: Settings.secret_key 로 서명한 사용자 id(와 기기 세션 id), 12시간 동안 유효.

기기 세션 id(sid)는 app.store.devices.UserDevice 의 줄 — 관리자가 그 줄을 닫으면 토큰이 살아 있어도 401 이다.
sid 가 없는 토큰(기기 세션 전에 받은 것)은 그대로 받고, 접속 신호(POST /api/me/presence)가 sid 가 든 새 토큰을 준다.
"""

from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import Settings

TOKEN_MAX_AGE_SECONDS = 12 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Settings().secret_key, salt="chronos-auth")


def issue_token(user_id: int, device_id: int | None = None) -> str:
    claims: dict[str, int] = {"uid": user_id}
    if device_id is not None:
        claims["sid"] = device_id
    return _serializer().dumps(claims)


def read_claims(token: str) -> tuple[int, int | None] | None:
    """서명이 맞고 만료 전이면 (사용자 id, 기기 세션 id 또는 None), 아니면 None."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except BadData:
        return None
    if not isinstance(data, dict):
        return None
    uid, sid = data.get("uid"), data.get("sid")
    if not isinstance(uid, int):
        return None
    return uid, sid if isinstance(sid, int) else None


def read_token(token: str) -> int | None:
    """서명이 맞고 만료 전이면 사용자 id, 아니면 None."""
    claims = read_claims(token)
    return claims[0] if claims else None
