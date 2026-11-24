"""로그인 토큰: Settings.secret_key 로 서명한 사용자 id(와 기기 세션 id), 12시간 동안 유효.

기기 세션 id(sid)는 app.store.devices.UserDevice 의 줄 — 관리자가 그 줄을 닫으면 토큰이 살아 있어도 401 이다.
sid 가 없는 토큰(기기 세션 전에 받은 것)은 받지 않는다(401 session_upgraded — 한 번 다시 로그인). 그래서 여기서는 sid 없는
토큰을 만들지 않는다: 기기를 모르고 부르면(시험·스크립트) 이름 없는 기기 줄을 하나 열어 묶는다.
"""

from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app import db
from app.config import Settings
from app.store import devices

TOKEN_MAX_AGE_SECONDS = 12 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Settings().secret_key, salt="chronos-auth")


def _unnamed_device(user_id: int) -> int | None:
    engine = db.current_engine()
    if engine is None:  # DB 를 열기 전(로그인 확인 없이 머리글만 보는 시험) — 이 토큰은 어떤 API 도 통과하지 못한다
        return None
    with Session(engine) as session:
        return devices.open_device(session, user_id, None, "desktop", "").id


def issue_token(user_id: int, device_id: int | None = None) -> str:
    """device_id 가 없으면 이름 없는 기기 줄을 열어 묶는다(로그인은 늘 자기 기기 줄을 넘긴다)."""
    claims: dict[str, int] = {"uid": user_id}
    sid = device_id if device_id is not None else _unnamed_device(user_id)
    if sid is not None:
        claims["sid"] = sid
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
