"""차단 목록(계획 4 Task 70). 번호는 정리한 꼴로 저장하고 가린 꼴로만 내보낸다.

「모르는 번호」 묶음에서는 번호 대신 peer_key 로 차단한다 — 일정 없는 문자·통화 줄(그 묶음이 나오는 곳)의 상대 번호를
최근 것부터 PEER_SCAN_ROWS 줄까지 보고 peer_key 가 같은 것을 찾는다(번호를 화면에 내리지 않는다). 「번호 없음」은 모든 번호
없는 상대가 같은 열쇠라 차단하지 않는다. 번호 검사는 phone.normalize 만(정보 이용 060 도 막을 수 있다).
까닭(reason)은 보이지 않는 제어 글자·글 방향 글자를 받지 않고(주소록 메모와 같은 규칙), 내보낼 때 번호 꼴을 가린다.
"""

import unicodedata

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone, redact
from app.programs.notify_settings.schemas import BlockedOut, BlockIn
from app.programs.notify_settings.service import check_lengths
from app.store.tables import User
from app.store.tables_outreach import BlockedNumber, OutreachCall, OutreachMessage

PEER_SCAN_ROWS = 2000  # peer_key 를 찾을 때 표마다 보는 최근 줄 수
ALREADY = "이미 차단한 번호입니다."
BAD_REASON = "까닭에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다."
# 주소록 메모와 같은 막는 글자: 글 방향 바꾸기·표시(Bidi_Control 전부), 줄·문단 구분, 폭 없는 빈칸, 제어 글자(줄 바꿈·탭 빼고)
_HIDDEN = (frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))
           | {0x200E, 0x200F, 0x061C, 0x2028, 0x2029, 0x200B})


def _bad_char(char: str) -> bool:
    return ord(char) in _HIDDEN or (unicodedata.category(char) == "Cc" and char not in "\n\t")


def _out(row: BlockedNumber) -> BlockedOut:
    return BlockedOut(id=row.id, number_masked=phone.mask(row.number), reason=redact.hide_phones(row.reason),
                      created_by=row.created_by, created_at=row.created_at)


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
    seen: set[str] = set()
    for model in (OutreachMessage, OutreachCall):
        stmt = (select(model.peer_number).where(model.schedule_id.is_(None), model.peer_number.is_not(None))
                .order_by(model.id.desc()).limit(PEER_SCAN_ROWS))
        for number in session.scalars(stmt):
            if number in seen or number == phone.NO_NUMBER:
                continue
            seen.add(number)
            if phone.peer_key(number) == key:
                return phone.normalize(number) or number
    raise ApiError(404, "peer_not_found", "그 상대를 찾을 수 없습니다.")


def _existing(session: Session, number: str) -> BlockedNumber | None:
    return session.scalar(select(BlockedNumber).where(BlockedNumber.number == number))


def add(session: Session, data: BlockIn, user: User) -> BlockedOut:
    if (data.number is None) == (data.peer_key is None):
        raise ApiError(422, "number_or_peer_key", "번호와 상대 열쇠(peer_key) 가운데 하나만 보내 주세요.")
    check_lengths({"number": data.number, "reason": data.reason})
    if any(_bad_char(c) for c in data.reason):
        raise ApiError(422, "invalid_text", BAD_REASON, {"field": "reason"})
    number = _from_peer(session, data.peer_key) if data.peer_key is not None else _from_number(data.number)
    existing = _existing(session, number)
    if existing is not None:
        raise ApiError(409, "already_blocked", ALREADY, {"id": existing.id})
    row = BlockedNumber(number=number, reason=data.reason.strip(), created_by=user.name)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # 같은 번호를 동시에 막았다(유일 열쇠)
        session.rollback()
        found = _existing(session, number)
        raise ApiError(409, "already_blocked", ALREADY, {"id": found.id} if found else None) from None
    return _out(row)


def remove(session: Session, blocked_id: int) -> None:
    row = session.get(BlockedNumber, blocked_id)
    if row is None:
        raise ApiError(404, "blocked_not_found", "차단 항목을 찾을 수 없습니다.")
    session.delete(row)
    session.commit()
