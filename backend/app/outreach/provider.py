"""한국AI통신 REST 호출(계획 4 Task 69) — 문자·알림톡 보내기, 상태, 받은 문자, 통화 조회. 실제 발송·조회는 여기서만 나간다.

- 주소는 `{base_url}/v1/accounts/{account_id}/…` 로만 만든다(Account ID·id 는 %인코딩한 한 칸). 머리글 `Authorization: Bearer`.
  리다이렉트를 따르지 않고, 이름 풀이를 넣어 한 번에 15초(`TIMEOUT_S`), 다시 시도하지 않는다(다시 보내기는 나가는 문이
  중복 방지 키로 정한다). 요청마다 새 클라이언트(`diagnostics.make_client` — trust_env=False).
- 요청 전에 막는 것(요청 0번): 주소가 https 가 아니거나 사용자 정보(@)·localhost·내부망이면 `bad_request`, 호스트가 내부망
  IP 로 풀리면 `bad_request`, 풀지 못하면 `network`, 키·Account ID 가 비었거나 8자보다 짧거나 쓸 수 없는 글자면
  `bad_key`·`bad_account`, 보낼 것이 모자라면 `bad_request`. 주소·이름 풀이 검사는 연결 진단(app.notify.diagnostics)과
  같은 함수다. 진단처럼 풀린 IP 로 붙지는 않는다(https 인증서 확인이 이름을 지킨다).
- 키: 풀린 키는 이 프로세스 안에만 있다. `KatClient` 를 만들면 키·Account ID 가 로그 거르개에 오른다(`register_secrets` —
  `redact.install` 을 부르는 곳은 이 모듈 하나). 실패는 `ProviderFailed(code, message)` 뿐이고 글은 이 파일의 표에서만 온다:
  통신 예외·제공사 오류 본문·실패 글(`failureMessage`)은 어디에도 옮기지 않는다(예외는 이어 붙이지도 않는다).
  제공사가 준 id·코드는 꼴이 맞고 키·Account ID 가 들어 있지 않을 때만 받는다. 로그에는 종류·코드·상태만 남긴다.
- `maybe_sent`: 보내기(POST)가 나간 뒤 끊기거나 시간이 넘었거나 2xx 인데 읽지 못하면 참 — 보냈는지 알 수 없다.

문서로 확인한 것(2026-11-23, https://docs.koreaaitel.com):
- api-reference — 인증, 기본 주소 https://api.koreaaitel.com
- api-reference/claw-ops-api/messages/send-message — `POST …/messages`: `To`·`From`·`Body`·`Type`(빼면 본문 길이로 sms/lms)·
  `IdempotencyKey`(빈 글은 400)·`Kakao{ChannelId, TemplateId, Variables}`(알림톡 — `Body`·`Type` 을 넣지 않는다)·
  `Fallback{Body, Disabled}`(빼면 알림톡 실패 때 문안 그대로 문자가 나간다) → 201 `messageId`·`status`·`failureCode`.
  오류 `{error, code}`: 400 `from_not_registered`·`invalid_phone`…, 401, 403(`overseas_ip_blocked`), 422 `quota_exceeded`·
  `recipient_blocked`·`content_blocked`, 429 `rate_limited`
- api-reference/claw-ops-api/messages/get-message — `GET …/messages/{messageId}`: `status` queued|sent|failed|received,
  `failureCode` 18가지(아래 `_FAILURES` 의 글은 이 쪽의 설명), 시각은 ISO 8601 UTC(`Z`). 요금 칸 없음
- api-reference/claw-ops-api/messages/list-messages · messages(안내) — `GET …/messages?status=received&pageSize=&page=`:
  `{data, meta}`, 최신순 고정, page 는 0부터, pageSize 100 초과는 400, **날짜 거르기 없음**. `sent` 는 「통신사로부터 발송 성공
  리포트를 받은」 상태
- kakao-alimtalk — 「대체 문자는 알림톡과 별도의 메시지 한 건으로 기록」
- api-reference/claw-ops-api/sender-numbers/list-sender-numbers — `{senderNumbers: [{number, status: approved|pending}]}`
- api-reference/claw-ops-api/calls/get-call — `GET …/calls/{callId}`: `status`·`direction`·`duration`·`hangupCause`…

문서에 없어 정해 둔 것(`# P0 확인` — P0-R 뒤 `_message_body`·`_parse_delivery`·`_parse_inbound` 와 `STATUS_MAP` 만 고친다):
- `sent` → `delivered`: 단말 도착이라는 말은 문서에 없다(통신사 성공 리포트). 실측(P3)이 다르면 `STATUS_MAP` 한 줄.
- `fell_back` 은 늘 False: 대신 나간 문자는 따로 된 메시지인데 원래 알림톡에서 그것을 알 칸이 문서에 없다.
- 받은 문자의 시각 거르기는 여기서 한다(`dateCreated >= since`, 최신순 쪽을 `RECEIVED_MAX_PAGES` 까지).
- 틀린 키와 틀린 Account ID 를 제공사가 어떻게 가르는지 문서에 없다: 401 → `bad_key`, 403 과 계정 경로의 404 → `bad_account`.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

import httpx

from app.info import generic
from app.notify import diagnostics
from app.notify.diagnostics import (  # 진단과 같은 검사·경로 칸 인코딩(옮겨 적지 않는다)
    _resolve_problem,
    _segment,
)
from app.outreach import phone, redact
from app.security import crypto
from app.store.tables_outreach import NotifyConnection

logger = logging.getLogger(__name__)

TIMEOUT_S = diagnostics.TIMEOUT_S  # 요청 하나에 쓰는 전체 시간(이름 풀이 포함)
RECEIVED_PAGE_SIZE = 100  # 제공사 상한
RECEIVED_MAX_PAGES = 3  # received 한 번이 쓰는 요청 수의 상한
RESOLVE: diagnostics.Resolver | None = None  # 호스트 → IP 목록. None 이면 diagnostics.RESOLVE. 시험이 바꿔 끼운다
STATUS_MAP: dict[str, str] = {"queued": "accepted", "sent": "delivered", "failed": "failed", "received": "received"}  # P0 확인

MAYBE_SENT = " 보냈는지는 알 수 없습니다(이미 나갔을 수 있습니다)."
_MESSAGES = {
    "bad_key": "제공사가 키를 받아들이지 않았습니다. 설정 → 알림 연결에서 키를 확인해 주세요.",
    "bad_account": "이 계정으로는 쓸 수 없습니다. Account ID 와 구독 상태를 확인해 주세요.",
    "bad_sender": "발신번호가 등록·승인되지 않았습니다.",
    "rate_limited": "요청이 너무 잦습니다. 잠시 뒤 다시 해 주세요.",
    "timeout": "제공사 응답이 시간 안에 오지 않았습니다.",
    "network": "제공사에 연결하지 못했습니다.",
    "bad_request": "제공사가 요청을 받아들이지 않았습니다.",
    "server": "제공사 서버 오류입니다. 잠시 뒤 다시 해 주세요.",
    "unknown": "제공사 응답을 읽지 못했습니다.",
}
_VENDOR = {  # 제공사 오류 code(문서) → (우리 code, 글)
    "from_not_registered": ("bad_sender", _MESSAGES["bad_sender"]),
    "invalid_phone": ("bad_request", "받는 번호가 올바르지 않습니다."),
    "INVALID_PHONE_NUMBER": ("bad_request", "받는 번호가 올바르지 않습니다."),
    "UNSUPPORTED_COUNTRY": ("bad_request", "지원하지 않는 나라의 번호입니다."),
    "body_too_long": ("bad_request", "글이 너무 깁니다."),
    "recipient_blocked": ("bad_request", "제공사의 수신 거부 목록에 있는 번호입니다."),
    "quota_exceeded": ("bad_request", "이번 달 발송 한도를 넘었습니다."),
    "content_blocked": ("bad_request", "제공사가 내용을 차단했습니다."),
    "overseas_ip_blocked": ("network", "한국 밖 IP 에서 온 요청이라 제공사가 거절했습니다. 서버가 나가는 IP 를 확인해 주세요."),
    "kakao_variable_missing": ("bad_request", "알림톡 문안의 변수가 빠졌습니다."),
    "kakao_variable_unknown": ("bad_request", "알림톡 문안에 없는 변수가 있습니다."),
}
_FAILURES = {  # failureCode(get-message 문서) → 글
    "invalid_number": "없는 번호입니다(비가입·결번·서비스 정지).",
    "recipient_opted_out": "받는 사람이 수신을 거부한 상태입니다.",
    "spam_blocked": "통신사가 스팸으로 보고 차단했습니다.",
    "number_ported": "번호이동된 번호입니다.",
    "handset_off": "단말기 전원이 꺼져 있습니다.",
    "out_of_coverage": "단말기가 서비스 지역 밖에 있습니다.",
    "handset_storage_full": "단말기 저장 공간이 부족합니다.",
    "timeout": "결과를 기다리는 시간이 지났습니다.",
    "invalid_data": "발송 데이터에 오류가 있습니다.",
    "invalid_message": "메시지 형식에 오류가 있습니다.",
    "message_too_large": "메시지 크기가 허용 범위를 넘었습니다.",
    "rate_limited": "전송량이 허용 한도를 넘었습니다.",
    "invalid_sender": "발신번호 형식에 오류가 있습니다.",
    "sender_not_registered": "등록되지 않은 발신번호입니다.",
    "sender_blocked": "차단된 발신번호입니다.",
    "service_not_permitted": "서비스 권한 문제로 보내지 못했습니다.",
    "carrier_error": "통신사에서 오류가 났습니다.",
    "unknown": "실패한 까닭을 확인할 수 없습니다.",
}
_ITEMS = {"messages": "메시지", "calls": "통화"}
_CALL_FIELDS = ("callId", "status", "direction", "duration", "answeredBy", "hangupCause", "hangupSource",
                "callerIdRestricted", "recording", "dateCreated", "dateUpdated")  # 번호·계정·주소·자유 글은 뺀다
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)  # 나가기 전에 끝남
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_ID = re.compile(r"[A-Za-z0-9_.:\-]{1,100}")
_NUMBER = re.compile(r"[0-9+\-\s().]{3,25}")
_NOT_DIGIT = re.compile(r"[^0-9]")


@dataclass(frozen=True)
class ProviderConn:
    """제공사 연결 값. 키·Account ID 는 이 값과 요청에만 있고 repr 에는 없다."""

    base_url: str
    account_id: str = field(repr=False)
    key: str = field(repr=False)


class ProviderFailed(Exception):
    """제공사를 부르지 못했거나 불렀지만 실패했다. message 는 한국어이고 키·번호·Account ID 가 없다.

    code: bad_key | bad_account | bad_sender | rate_limited | timeout | network | bad_request | server | unknown.
    maybe_sent 가 참이면 보내기 요청이 나간 뒤라 문자가 갔는지 알 수 없다(거짓이면 가지 않았다).
    """

    def __init__(self, code: str, message: str, http_status: int | None = None, *, maybe_sent: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status, self.maybe_sent = code, message, http_status, maybe_sent


@dataclass(frozen=True)
class MessageRequest:
    """보낼 것 하나. channel 은 sms | kakao. kakao 면 kakao_channel(채널 id)·template_code(문안 id)가 있어야 하고
    body 는 쓰지 않는다(문안대로 나간다). fallback_sms 가 거짓이면 알림톡이 실패해도 문자로 대신 보내지 않는다."""

    channel: str
    to: str = field(repr=False)
    sender: str = field(repr=False)
    body: str = field(repr=False)
    idempotency_key: str
    kakao_channel: str | None = None
    template_code: str | None = None
    template_vars: dict[str, str] | None = field(default=None, repr=False)
    fallback_sms: bool = False
    fallback_body: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Accepted:
    provider_id: str


@dataclass(frozen=True)
class Delivery:
    """보낸 메시지의 지금 상태. fail_code 는 제공사의 failureCode(없으면 unknown), fail_text 는 우리 글."""

    state: Literal["accepted", "delivered", "failed"]
    fail_code: str | None = None
    fail_text: str | None = None
    fell_back: bool = False


@dataclass(frozen=True)
class Inbound:
    """받은 문자 한 건. from_number 는 phone.normalize 꼴(사람 번호가 아니면 숫자만), at 은 UTC."""

    provider_id: str
    from_number: str = field(repr=False)
    body: str = field(repr=False)
    at: datetime
    has_media: bool


@dataclass(frozen=True)
class Check:
    """연결 확인. senders 는 승인된 발신번호(숫자만)."""

    ok: bool
    senders: list[str] = field(repr=False)
    latency_ms: int


class Provider(Protocol):
    """제공사가 하는 일 다섯. 실패는 모두 ProviderFailed."""

    async def check(self) -> Check: ...

    async def send_message(self, req: MessageRequest) -> Accepted: ...

    async def message_status(self, provider_id: str) -> Delivery: ...

    async def received(self, since: datetime | None) -> list[Inbound]: ...

    async def call_info(self, provider_call_id: str) -> dict: ...


# ── 키 지우기 ───────────────────────────────────────────────────────

_SECRETS: tuple[str, ...] = ()  # 이 프로세스가 쓴 키·Account ID(로그 줄마다 읽히므로 통째로 바꿔 넣는다)


def _known_secrets() -> list[str]:
    return list(_SECRETS)


def register_secrets(*values: str) -> None:
    """키·Account ID 를 로그 거르개(redact)에 올린다. 8자보다 짧은 값은 올리지 않는다(보통 글을 망가뜨린다 — 쓰지도 않는다)."""
    global _SECRETS
    fresh = [v for v in values if isinstance(v, str) and len(v) >= diagnostics.MIN_SECRET]
    _SECRETS = tuple(dict.fromkeys((*_SECRETS, *fresh)))
    redact.install(_known_secrets)


def _holds_secret(text: str, secrets: list[str]) -> bool:
    return any(generic.key_survives(text, s) for s in secrets)


def _safe(pattern: re.Pattern[str], value: object, secrets: list[str]) -> str | None:
    """제공사가 준 id·코드: 꼴이 맞고 키·Account ID 가 들어 있지 않을 때만 그 값."""
    if isinstance(value, str) and pattern.fullmatch(value) and not _holds_secret(value, secrets):
        return value
    return None


def _failed(code: str, label: str, *, message: str | None = None, status: int | None = None,
            maybe_sent: bool = False) -> ProviderFailed:
    """실패 하나를 만들고 종류만 로그에 남긴다."""
    logger.warning("제공사 호출 실패: %s code=%s status=%s maybe_sent=%s", label, code, status, maybe_sent)
    return ProviderFailed(code, (message or _MESSAGES[code]) + (MAYBE_SENT if maybe_sent else ""), status,
                          maybe_sent=maybe_sent)


def _http_failure(status: int, vendor: str | None, label: str, on_item: bool) -> ProviderFailed:
    """2xx 가 아닌 응답 → ProviderFailed. vendor 는 오류 본문의 code(받을 수 있는 꼴일 때만)."""
    if vendor in _VENDOR:
        code, message = _VENDOR[vendor]
    elif 300 <= status < 400:
        code, message = "bad_request", "제공사가 다른 주소로 넘기는 응답을 보내 따라가지 않았습니다. 기본 주소를 확인해 주세요."
    elif status == 401:
        code, message = "bad_key", None
    elif status == 403:
        code, message = "bad_account", None
    elif status == 404 and on_item:
        code, message = "bad_request", f"제공사에서 그 {_ITEMS[label]}를 찾을 수 없습니다."
    elif status == 404:
        code, message = "bad_account", "제공사 주소를 찾지 못했습니다. Account ID 와 기본 주소를 확인해 주세요."
    elif status == 429:
        code, message = "rate_limited", None
    elif status >= 500:
        code, message = "server", None
    elif 400 <= status < 500:
        code, message = "bad_request", (f"{_MESSAGES['bad_request']}(제공사 코드 {vendor})" if vendor else None)
    else:
        code, message = "unknown", None
    return _failed(code, label, message=message, status=status)


# ── 제공사 칸 이름을 아는 세 함수(P0-R 뒤 여기만 고친다) ────────────


def _message_body(req: MessageRequest) -> dict:
    """보내기 본문. 모자라면 ProviderFailed(bad_request) — 요청 전."""
    if not (req.to and req.sender and req.idempotency_key):
        raise ProviderFailed("bad_request", "받는 번호·발신번호·중복 방지 키가 모두 있어야 보냅니다.")
    body: dict = {"To": req.to, "From": req.sender, "IdempotencyKey": req.idempotency_key}
    if req.channel == "sms":
        if not req.body:
            raise ProviderFailed("bad_request", "보낼 글이 비어 있습니다.")
        return {**body, "Body": req.body}  # Type 은 뺀다 — 제공사가 길이로 sms/lms 를 고른다
    if req.channel == "kakao":
        if not (req.kakao_channel and req.template_code):
            raise ProviderFailed("bad_request", "알림톡은 채널과 문안이 있어야 보냅니다.")
        body["Kakao"] = {"ChannelId": req.kakao_channel, "TemplateId": req.template_code,
                         "Variables": dict(req.template_vars or {})}
        if not req.fallback_sms:
            body["Fallback"] = {"Disabled": True}  # 빼면 제공사가 문자로 대신 보낸다
        elif req.fallback_body:
            body["Fallback"] = {"Body": req.fallback_body}
        return body
    raise ProviderFailed("bad_request", "이 통로로는 보낼 수 없습니다.")


def _parse_delivery(data: dict, secrets: list[str]) -> Delivery:
    """메시지 하나 → Delivery. 모르는 상태 말은 짐작하지 않고 실패(unknown)."""
    status = data.get("status")
    state = STATUS_MAP.get(status) if isinstance(status, str) else None
    if state not in ("accepted", "delivered", "failed"):
        raise _failed("unknown", "messages", status=200)
    if state != "failed":
        return Delivery(state=state)
    code = _safe(_CODE, data.get("failureCode"), secrets) or "unknown"
    text = _FAILURES.get(code) or f"보내지 못했습니다(제공사 코드 {code})."
    return Delivery(state="failed", fail_code=code, fail_text=text, fell_back=False)  # P0 확인: 대신 나간 문자를 알 칸이 없다


def _parse_inbound(row: object, secrets: list[str]) -> Inbound | None:
    """받은 문자 한 줄 → Inbound. 읽을 수 없는 줄(받은 것이 아님·id·번호·시각 없음)은 None."""
    if not isinstance(row, dict) or row.get("direction", "inbound") != "inbound":
        return None
    provider_id = _safe(_ID, row.get("messageId"), secrets)
    raw = row.get("from")
    number = (phone.normalize(raw) or _NOT_DIGIT.sub("", raw)) if isinstance(raw, str) and _NUMBER.fullmatch(raw) else ""
    try:
        at = datetime.fromisoformat(row.get("dateCreated"))
    except (TypeError, ValueError):
        return None
    if provider_id is None or not number:
        return None
    body = row.get("body") if isinstance(row.get("body"), str) else ""
    for secret in secrets:
        body = generic.scrub(body, secret)
    media = row.get("numMedia")
    has_media = (isinstance(media, int) and media > 0) or bool(row.get("mediaUrl"))
    return Inbound(provider_id=provider_id, from_number=number, body="" if _holds_secret(body, secrets) else body,
                   at=(at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(UTC), has_media=has_media)


# ── 호출 ────────────────────────────────────────────────────────────


class KatClient:
    """한국AI통신 REST. 만들면 키·Account ID 가 로그 거르개에 오른다. transport 는 시험용(httpx.MockTransport)."""

    def __init__(self, conn: ProviderConn, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.conn = conn
        self._transport = transport
        self._secrets = [s for s in (conn.key, conn.account_id) if isinstance(s, str) and s]
        register_secrets(*self._secrets)

    def _unusable(self) -> ProviderFailed | None:
        """연결 값 때문에 부를 수 없는 까닭(요청 전)."""
        if diagnostics.base_url_problem(self.conn.base_url) is not None:
            return ProviderFailed("bad_request", "기본 주소를 쓸 수 없습니다. https:// 로 시작하는 공개 주소여야 합니다.")
        for value, code, name in ((self.conn.key, "bad_key", "키"), (self.conn.account_id, "bad_account", "Account ID")):
            if not isinstance(value, str) or len(value) < diagnostics.MIN_SECRET or not value.isascii() \
                    or not value.isprintable():
                return ProviderFailed(code, f"{name} 값이 비었거나 너무 짧거나 쓸 수 없는 글자가 있습니다. "
                                            "설정 → 알림 연결에서 다시 넣어 주세요.")
        return None

    async def _call(self, method: str, resource: str, item_id: object = None, *, on_item: bool = False,
                    **kw: object) -> dict:
        """요청 한 번 → 2xx 의 JSON 객체. 그 밖은 ProviderFailed. 예외는 종류만 본다(글에 주소·머리글이 있다)."""
        refused = self._unusable()
        if refused is not None:
            raise refused
        if on_item and (not isinstance(item_id, str) or not item_id):
            raise ProviderFailed("bad_request", f"{_ITEMS[resource]} id 가 비어 있습니다.")
        url = f"{self.conn.base_url.rstrip('/')}/v1/accounts/{_segment(self.conn.account_id)}/{resource}"
        url += f"/{_segment(item_id)}" if on_item else ""
        code = problem = response = None
        started = unsent = False
        try:
            async with asyncio.timeout(TIMEOUT_S):
                problem = await _resolve_problem(self.conn, RESOLVE)  # .base_url 만 읽는다
                if problem is None:
                    async with diagnostics.make_client(transport=self._transport) as http:
                        started = True
                        response = await http.request(method, url, headers={
                            "Authorization": f"Bearer {self.conn.key}", "Accept": "application/json"}, **kw)
        except (httpx.TimeoutException, TimeoutError) as e:
            code, unsent = "timeout", isinstance(e, _NOT_SENT)
        except httpx.TransportError as e:
            code, unsent = "network", isinstance(e, _NOT_SENT)
        except Exception:  # noqa: BLE001 — 어떤 예외 글도 밖으로 내지 않는다
            code = "unknown"
        sends = method == "POST"
        if code is not None:  # except 밖에서 올린다 — 원래 예외(주소·키가 든)를 이어 붙이지 않으려고
            raise _failed(code, resource, maybe_sent=sends and started and not unsent)
        if problem is not None:
            if problem == diagnostics.RESOLVE_FAILED:
                raise _failed("network", resource, message="기본 주소의 호스트 이름을 찾지 못했습니다.")
            raise _failed("bad_request", resource, message="기본 주소가 내부망으로 풀려 부르지 않았습니다.")
        try:
            data = response.json()
        except (ValueError, RecursionError):
            data = None
        if not 200 <= response.status_code < 300:
            vendor = _safe(_CODE, data.get("code"), self._secrets) if isinstance(data, dict) else None
            raise _http_failure(response.status_code, vendor, resource, on_item)
        if not isinstance(data, dict):
            raise _failed("unknown", resource, status=response.status_code, maybe_sent=sends)
        return data

    async def check(self) -> Check:
        """인증 + 발신번호 목록. 승인된 번호만 돌려준다."""
        start = time.perf_counter()
        data = await self._call("GET", "sender-numbers")
        latency_ms = int((time.perf_counter() - start) * 1000)
        rows = data.get("senderNumbers")
        if not isinstance(rows, list):
            raise _failed("unknown", "sender-numbers", status=200)
        senders = [_NOT_DIGIT.sub("", row["number"]) for row in rows
                   if isinstance(row, dict) and row.get("status") == "approved"
                   and isinstance(row.get("number"), str) and _NUMBER.fullmatch(row["number"])]
        return Check(ok=True, senders=list(dict.fromkeys(senders)), latency_ms=latency_ms)

    async def send_message(self, req: MessageRequest) -> Accepted:
        """한 건 보내기(문자 또는 알림톡). 접수되면 제공사 id. 201 의 status 가 failed 여도 id 를 돌려준다(상태 조회가 알린다)."""
        data = await self._call("POST", "messages", json=_message_body(req))
        provider_id = _safe(_ID, data.get("messageId"), self._secrets)
        if provider_id is None:
            raise _failed("unknown", "messages", status=201, maybe_sent=True)
        return Accepted(provider_id=provider_id)

    async def message_status(self, provider_id: str) -> Delivery:
        return _parse_delivery(await self._call("GET", "messages", provider_id, on_item=True), self._secrets)

    async def received(self, since: datetime | None) -> list[Inbound]:
        """받은 문자를 오래된 것부터. since(tz 없으면 UTC) 와 같거나 뒤인 것만 — 겹침은 부른 쪽이 provider_id 로 막는다.

        제공사에 날짜 거르기가 없어 최신순 쪽을 since 보다 오래된 줄이 나올 때까지 읽는다(RECEIVED_MAX_PAGES 까지).
        since 가 None 이면 가장 최근 한 쪽만."""
        floor = since.replace(tzinfo=UTC) if since is not None and since.tzinfo is None else since
        found: dict[str, Inbound] = {}
        skipped, more = 0, False
        for page in range(RECEIVED_MAX_PAGES):
            data = await self._call("GET", "messages", params={
                "status": "received", "pageSize": str(RECEIVED_PAGE_SIZE), "page": str(page)})
            rows = data.get("data")
            if not isinstance(rows, list):
                raise _failed("unknown", "messages", status=200)
            older = False
            for message in (_parse_inbound(row, self._secrets) for row in rows):
                if message is None:
                    skipped += 1
                elif floor is not None and message.at < floor:
                    older = True
                else:
                    found.setdefault(message.provider_id, message)
            more = floor is not None and not older and len(rows) >= RECEIVED_PAGE_SIZE  # since 가 없으면 한 쪽만
            if not more:
                break
        if more:
            logger.warning("받은 문자가 %d쪽을 넘어 더 오래된 것은 읽지 못했습니다", RECEIVED_MAX_PAGES)
        if skipped:
            logger.warning("받은 문자 목록에서 읽을 수 없는 줄 %d개를 건너뛰었습니다", skipped)
        return sorted(found.values(), key=lambda m: m.at)

    async def call_info(self, provider_call_id: str) -> dict:
        """통화 하나의 문서에 있는 칸 가운데 번호·계정·주소가 아닌 것만(_CALL_FIELDS). 없는 칸은 None."""
        data = await self._call("GET", "calls", provider_call_id, on_item=True)
        out: dict = {}
        for name in _CALL_FIELDS:
            value = data.get(name)
            if isinstance(value, str):
                value = redact.scrub(value, self._secrets)[:100]
            out[name] = value if isinstance(value, str | int | float | bool) else None
        return out


def client_for(row: NotifyConnection) -> Provider:
    """저장된 연결 줄로 제공사 클라이언트를 만든다(키를 푼다). 시험이 바꿔 끼우는 한 곳 — `provider.client_for(row)` 로 부른다."""
    try:
        key = crypto.decrypt(row.secret_ciphertext)
    except crypto.SecretUnreadable:
        key = None
    if key is None:
        raise ProviderFailed("bad_key", "저장된 키를 읽을 수 없습니다. 설정 → 알림 연결에서 키를 다시 넣어 주세요.")
    return KatClient(ProviderConn(base_url=row.base_url, account_id=row.account_id, key=key))
