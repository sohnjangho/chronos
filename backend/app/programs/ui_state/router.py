"""내 화면 상태(열어 둔 창·탭) — 로그인한 본인 것만. GET 은 화면 형태 전부, PUT 은 한 형태를 덮어쓴다.

본문은 32KB 까지, 모양은 schemas 대로(모르는 칸·프로그램·자유 글은 422). 번호 꼴(숫자 8자리 이상)이 어디든 섞이면 422 —
화면 상태에 전화번호가 남지 않게. 오류 글에 보낸 값은 싣지 않는다.
"""

import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.errors import ApiError
from app.programs.ui_state.schemas import MODELS, Mode
from app.security.deps import current_user
from app.store import ui_states
from app.store.tables import User

router = APIRouter(prefix="/api/me/ui-state", tags=["ui-state"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]

MAX_BYTES = 32 * 1024
_PHONE_LIKE = re.compile(r"\d(?:[\s.\-]?\d){7,}")


def _bad(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def parse_state(mode: str, raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BYTES:
        raise _bad("ui_state_too_large", "화면 상태가 너무 큽니다.")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        raise _bad("bad_ui_state", "화면 상태를 읽을 수 없습니다.") from None
    if _PHONE_LIKE.search(text):
        raise _bad("ui_state_phone", "화면 상태에는 번호를 둘 수 없습니다.")
    try:
        model = MODELS[mode].model_validate(data)
    except ValidationError:
        raise _bad("bad_ui_state", "화면 상태의 모양이 맞지 않습니다.") from None
    return model.model_dump(exclude_none=True)


@router.get("")
def get_states(session: SessionDep, user: UserDep) -> dict[str, dict[str, Any]]:
    return ui_states.get_all(session, user)


@router.put("/{mode}")
async def put_state(mode: Mode, request: Request, session: SessionDep, user: UserDep) -> dict[str, str]:
    state = parse_state(mode, await request.body())
    at = await run_in_threadpool(ui_states.put, session, user, mode, state)
    return {"mode": mode, "updated_at": at}
