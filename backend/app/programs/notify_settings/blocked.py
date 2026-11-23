"""차단 목록(계획 4 Task 70). 번호는 정리한 꼴로 저장하고 가린 꼴로만 내보낸다.

「모르는 번호」 묶음에서는 번호 대신 peer_key 로 차단한다 — 문자·통화 기록의 서로 다른 상대 번호 가운데 peer_key 가 같은
것을 찾는다(번호를 화면에 내리지 않는다). 「번호 없음」은 모든 번호 없는 상대가 같은 열쇠라 차단하지 않는다.
번호 검사는 phone.normalize 만(정보 이용 060 도 막을 수 있다).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone
from app.programs.notify_settings.schemas import BlockedOut, BlockIn
from app.store.tables import User
from app.store.tables_outreach import BlockedNumber, OutreachCall, OutreachMessage


def _out(row: BlockedNumber) -> BlockedOut:
    return BlockedOut(id=row.id, number_masked=phone.mask(row.number), reason=row.reason, created_by=row.created_by,
                      created_at=row.created_at)


def list_blocked(session: Session) -> list[BlockedOut]:
    rows = session.scalars(select(BlockedNumber).order_by(BlockedNumber.created_at.desc(), BlockedNumber.id.desc()))
    return [_out(r) for r in rows]


def _from_number(raw: str) -> str:
    number = phone.normalize(raw)
    if number is None:
        raise ApiError(422, "invalid_number", "번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.", {"field": "number"})
    return number


def _from_peer(session: Session, key: str) -> str:
    if key == phone.peer_key(phone.NO_NUMBER):
        raise ApiError(422, "peer_has_no_number", "번호가 없는 상대는 차단할 수 없습니다.")
    for model in (OutreachMessage, OutreachCall):
        stmt = select(model.peer_number).where(model.peer_number.is_not(None)).distinct()
        for number in session.scalars(stmt):
            if number != phone.NO_NUMBER and phone.peer_key(number) == key:
                return phone.normalize(number) or number
    raise ApiError(404, "peer_not_found", "그 상대를 찾을 수 없습니다.")


def add(session: Session, data: BlockIn, user: User) -> BlockedOut:
    if (data.number is None) == (data.peer_key is None):
        raise ApiError(422, "number_or_peer_key", "번호와 상대 열쇠(peer_key) 가운데 하나만 보내 주세요.")
    number = _from_peer(session, data.peer_key) if data.peer_key is not None else _from_number(data.number)
    existing = session.scalar(select(BlockedNumber).where(BlockedNumber.number == number))
    if existing is not None:
        raise ApiError(409, "already_blocked", "이미 차단한 번호입니다.", {"id": existing.id})
    row = BlockedNumber(number=number, reason=data.reason.strip(), created_by=user.name)
    session.add(row)
    session.commit()
    return _out(row)


def remove(session: Session, blocked_id: int) -> None:
    row = session.get(BlockedNumber, blocked_id)
    if row is None:
        raise ApiError(404, "blocked_not_found", "차단 항목을 찾을 수 없습니다.")
    session.delete(row)
    session.commit()
