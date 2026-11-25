"""접속 기록 미들웨어(ASGI): 응답이 끝난 뒤 로그인한 사람의 요청을 한 줄 적는다(app.store.activity).

토큰 서명만 본다(사용자가 DB 에 있는지는 라우터가 본다). 길 틀은 라우팅이 scope["route"] 에 남긴 것을 쓴다.
기록은 스레드에서 짧은 세션으로 쓰고 실패는 삼킨다.
"""

import anyio
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import db
from app.security.tokens import read_claims
from app.store import activity


def _claims(scope: Scope) -> tuple[int, int | None] | None:
    scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return read_claims(token.strip())


class ActivityGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        status = {"code": 0}

        async def watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watch)
        finally:
            await self._note(scope, status["code"])

    async def _note(self, scope: Scope, code: int) -> None:
        route = getattr(scope.get("route"), "path", None)
        if not route or activity.skipped(route):
            return
        claims = _claims(scope)
        if claims is None:
            return
        sid = (scope.get("path_params") or {}).get("schedule_id")
        try:
            schedule_id = int(sid) if sid is not None else None
        except (TypeError, ValueError):
            schedule_id = None
        await anyio.to_thread.run_sync(lambda: activity.record_safely(
            db.current_engine(), user_id=claims[0], method=scope["method"], route=route, status=code,
            schedule_id=schedule_id, device_id=claims[1]))
