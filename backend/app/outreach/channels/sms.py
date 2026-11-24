"""문자 통로(Task 71) — 얇다. 나가는 문(gate.dispatch)이 차지한 줄 하나를 제공사에 **한 번** 보내고 결과 셋 가운데 하나를
돌려준다. 실제 문자가 나가는 길은 「문 → 이 통로 → provider」 하나뿐이고, deliver 를 부르는 코드는 문뿐이다.

- 결과: 제공사가 받음 → `Delivered("sent", provider_id)` · 깨끗한 거절(요청이 나가지 않았거나 409 밖의 4xx) →
  `Delivered("failed", fail_code)` · **요청이 나갔을 수 있는 모든 것**(`ProviderFailed.maybe_sent`, 뜻밖의 예외) →
  `Delivered("unsure")`. 끊김(`asyncio.CancelledError`)은 삼키지 않고 올린다 — 문이 「보냈는지 확인 필요」로 적는다.
  스스로 다시 보내지 않는다.
- fail_code 는 제공사 호출의 우리 code 그대로(gate.FAIL_TEXT 의 열쇠 — 문이 문장으로 옮긴다). 연결 단계의 시간 초과
  (`timeout` 이면서 나가지 않음)는 `network`. 제공사의 글·예외 글은 어디에도 옮기지 않는다(`fail_text` 는 늘 비어 있다).
  이 통로가 스스로 쓰는 code 셋(문에는 문장이 없어 「보내지 못했습니다」로 보인다): NOT_SENDABLE · NOT_REACHABLE · LOCAL_ERROR.
  문서에 없는 4xx 거절이면 제공사 호출이 거른 응답 모양(`ProviderFailed.shape`)만 `Delivered.shape` 로 넘긴다(문이 다시 거른다).
- 판정은 문이 이미 했다. 통로가 다시 보는 것은 둘뿐이다: ① 문이 차지한 줄인가(나가는 sms · 상태 sending · 글 있음) — 문
  밖에서 불려도 초안이 나가지 않게. ② **보내기 바로 전의 번호** — 문과 같은 규칙으로 읽고(연락처가 있으면 연락처의 지금
  번호, 없으면 peer_number — 정리된 꼴로 저장된 것만) `gate.may_reach` 를 다시 부른다(시험 모드·허용 번호·차단·수신 거부가
  그 사이 바뀌었으면 보내지 않는다). 수신 거부 확인 문자(kind dnc_confirm, 글이 gate.DNC_CONFIRM_TEXT)만은 문이 한 번
  지나보낸 것이므로 수신 거부 하나만으로는 막지 않는다 — 시험 모드·차단은 그대로 막는다(들어오는 문의 등급으로 가른다).
- 중복 방지 키는 줄의 `idempotency_key` — 줄마다 하나, 그 줄의 모든 시도에 같은 값.
- 보내기 전에 줄의 글을 제공사가 실을 수 있는 글(`sms_text.sms_safe` — EUC-KR 밖 기호를 바꾸거나 뺀 것)로 바꿔 적고(줄에는
  받는 사람이 본 글이 남는다), `length_kind` 를 적는다(그 글의 EUC-KR 바이트로 SMS_BYTES 까지 sms, 넘으면 long).
  실을 수 없는 글자가 남거나 빈 글·긴 글(`sms_text.problem`)이면 보내지 않는다(문이 앞 확인에서 먼저 막는다).
  `provider_cost` 는 비워 둔다(제공사가 메시지마다의 요금을 주지 않는다).
- DB 묶음(줄 읽기·length_kind 적기)은 스레드에서 새 세션으로 하고 commit·닫은 뒤에 제공사를 부른다.
- 이 모듈을 불러오면 `registry.register_channel("sms", CHANNEL)` — 객체는 프로세스에 하나(다시 불러와도 같은 객체).
"""

import asyncio
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.outreach import phone, provider, sms_text
from app.outreach.harness import door, gate, registry
from app.outreach.harness.types import Delivered
from app.store import outreach
from app.store.tables_outreach import Contact, OutreachMessage

logger = logging.getLogger(__name__)

SMS_BYTES = 90  # 이 바이트까지 한 건(sms). 제공사처럼 EUC-KR 바이트로 센다(한글 2·영문 1)
NOT_SENDABLE = "not_sendable"  # 문이 차지한 문자 줄이 아니다
NOT_REACHABLE = "not_reachable"  # 보내기 바로 전에 다시 보니 그 번호에 닿으면 안 된다(또는 번호가 없다·정리된 꼴이 아니다)
LOCAL_ERROR = "local_error"  # 보내기 전에 우리 DB 를 읽거나 쓰지 못했다
_CODES = {"timeout": "network"}  # 제공사 호출의 code → 문이 문장을 가진 code(나가지 않은 시간 초과는 연결 실패)


def length_kind(body: str) -> Literal["sms", "long"]:
    """글 한 건의 길이 종류: 실제로 나갈 글(sms_text.sms_safe)의 EUC-KR 바이트로 세어 SMS_BYTES 까지 sms, 넘으면 long."""
    return "sms" if sms_text.byte_size(body) <= SMS_BYTES else "long"


def _reachable(session: Session, row: OutreachMessage, number: str) -> bool:
    """보내기 바로 전에 다시: 문의 차례 1·2(gate.may_reach). 수신 거부 확인 문자는 수신 거부만으로는 막지 않는다 —
    들어오는 문의 등급이 do_not_contact 라는 것은 시험 모드 밖도 차단도 아니고 수신 거부뿐이라는 뜻이다."""
    if gate.may_reach(session, number):
        return True
    return (row.kind == "dnc_confirm" and row.body.strip() == gate.DNC_CONFIRM_TEXT
            and door.resolve(session, number, now=datetime.now(UTC)).caller_class == "do_not_contact")


def _prepare(row_id: int) -> Delivered | tuple[provider.Provider, provider.MessageRequest]:
    """줄을 읽어 보낼 것을 만든다(스레드에서, 새 세션). 보낼 수 없으면 실패 결과 — 아무것도 나가지 않았다."""
    try:
        with contextmanager(get_session)() as session:
            row = session.get(OutreachMessage, row_id)
            if (row is None or row.direction != "out" or row.status != "sending" or row.channel != "sms"
                    or sms_text.problem(row.body) is not None):  # 문의 앞 확인과 같은 검사(비었거나 실을 수 없는 글)
                return Delivered("failed", fail_code=NOT_SENDABLE)
            contact = session.get(Contact, row.contact_id) if row.contact_id is not None else None
            stored = contact.phone if contact is not None else row.peer_number
            number = phone.normalize(stored)
            if (number is None or stored != number or (row.contact_id is not None and contact is None)
                    or (contact is not None and contact.phone_invalid) or not _reachable(session, row, number)):
                return Delivered("failed", fail_code=NOT_REACHABLE)
            conn = outreach.connection(session)
            if conn is None or not conn.sender_number:
                return Delivered("failed", fail_code="bad_sender")
            row.body = sms_text.sms_safe(row.body)  # 줄에는 실제로 나가는 글을 남긴다
            request = provider.MessageRequest(channel="sms", to=number, sender=conn.sender_number, body=row.body,
                                              idempotency_key=row.idempotency_key)
            client = provider.client_for(conn)
            row.length_kind = length_kind(row.body)
            session.commit()
            return client, request
    except provider.ProviderFailed as exc:  # 저장된 키를 풀 수 없다 — 요청 전
        return Delivered("failed", fail_code=exc.code)
    except SQLAlchemyError as exc:
        logger.warning("문자 통로: 보내기 전에 줄을 읽거나 적지 못했습니다 (%s)", type(exc).__name__)
        return Delivered("failed", fail_code=LOCAL_ERROR)


class SmsChannel:
    """문자 통로(Channel). 나가는 문만 부른다."""

    name = "sms"

    async def deliver(self, row_id: int) -> Delivered:
        ready = await asyncio.to_thread(_prepare, row_id)
        if isinstance(ready, Delivered):
            return ready
        client, request = ready
        try:
            accepted = await client.send_message(request)
        except provider.ProviderFailed as exc:  # 글(message)은 옮기지 않는다 — code·「나갔을 수 있는가」·거른 응답 모양만
            code, unsure, shape = exc.code, exc.maybe_sent, exc.shape
        except Exception as exc:  # noqa: BLE001 — 무엇으로 끝났든 요청은 나갔을 수 있다. 예외 글에는 번호·키가 있을 수 있다
            logger.warning("문자 통로: 보내기가 예외로 끝났습니다 (%s)", type(exc).__name__)
            return Delivered("unsure")
        else:
            return Delivered("sent", provider_id=accepted.provider_id)
        return Delivered("unsure") if unsure else Delivered("failed", fail_code=_CODES.get(code, code), shape=shape)


# 프로세스에 하나. 모듈을 다시 불러와도 처음 만든 객체를 그대로 쓴다(같은 객체를 다시 등록하는 것은 괜찮다).
CHANNEL: SmsChannel = globals().get("CHANNEL") or SmsChannel()
registry.register_channel("sms", CHANNEL)
