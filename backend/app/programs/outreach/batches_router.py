from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.outreach import batches_service
from app.programs.outreach.batches_service import (
    KEY_PATTERN,
    BatchIn,
    BatchSendOut,
    BatchStatsOut,
)
from app.security.deps import require_contacts
from app.store.tables import User

# 「여러 명에게 한 번에」 API(Task 103). 관리자·사용자만(현장 관리자 403 field_no_contacts) — 한 사람 보내기와 같은 권한.
# 받는 사람마다 나가는 문(gate.dispatch)을 따로 지나고, 막힌 것도 결과라 200. 응답에 번호는 없다.
# 이 라우터는 app/programs/outreach/router.py 가 import 해서 앱에 붙는다(main 은 router.py 만 읽는다).
batches_router = APIRouter(prefix="/api/schedules", tags=["outreach"], dependencies=[Depends(require_contacts)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(require_contacts)]
BATCHES = "/{schedule_id}/outreach/batches"


@batches_router.post(BATCHES)
async def send_batch(schedule_id: int, body: BatchIn, session: SessionDep, user: UserDep) -> BatchSendOut:
    """1~20명에게 같은 글 → {batch_id, results: [{contact_id, name, outcome}], replayed}. 같은 request_key 는 다시 보내지 않는다."""
    return await batches_service.send(session, schedule_id, body, user)


@batches_router.get(BATCHES + "/by-key")  # /{batch_id} 보다 앞에(그 길은 정수만 받는다)
def batch_by_key(schedule_id: int, request_key: Annotated[str, Query(pattern=KEY_PATTERN)], session: SessionDep,
                 user: UserDep) -> BatchSendOut:
    """결과 확인만 — 이 사람·일정의 요청 번호로 저장된 묶음 결과. 없으면 404(서버에 닿지 않음). 만들거나 보내지 않는다."""
    return batches_service.check(session, schedule_id, request_key, user)


@batches_router.get(BATCHES + "/{batch_id}")
def batch_stats(schedule_id: int, batch_id: int, session: SessionDep) -> BatchStatsOut:
    """그 묶음의 {total, sent, replied}. 다른 일정·없는 묶음은 404."""
    return batches_service.stats(session, schedule_id, batch_id)
