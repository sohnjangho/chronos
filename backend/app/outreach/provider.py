"""한국AI통신 REST 호출(계획 4 Task 69) — 문자·알림톡 보내기, 상태, 받은 문자, 통화 조회. 실제 발송·조회는 여기서만 나간다.

- 주소는 `{base_url}/v1/accounts/{account_id}/…` 로만 만든다(Account ID·id 는 %인코딩한 한 칸). 머리글 `Authorization: Bearer`.
  리다이렉트를 따르지 않고, 이름 풀이를 넣어 한 번에 15초(`TIMEOUT_S`), 다시 시도하지 않는다(다시 보내기는 나가는 문이
  중복 방지 키로 정한다). 요청마다 새 클라이언트(`diagnostics.make_client` — trust_env=False, 연결 제한 5초). 응답 본문은
  `MAX_BYTES`(1MB)까지만 읽는다. `Accept-Encoding: identity` 를 싣고, 그래도 압축돼 온 응답은 풀지 않고 읽지 못한 것으로 본다.
- 요청 전에 막는 것(요청 0번, `maybe_sent=False`): 기본 주소가 https://호스트[:포트] 꼴이 아니거나(경로·질의·조각·빈칸·@)
  localhost·내부망이면 `bad_request`, 호스트가 내부망 IP 로 풀리면 `bad_request`, 풀지 못하면 `network`, 키·Account ID 가
  비었거나 8자보다 짧거나 쓸 수 없는 글자면 `bad_key`·`bad_account`, 보낼 것이 모자라거나 보낼 꼴로 만들 수 없거나 중복
  방지 키가 `^[A-Za-z0-9_-]{8,64}$` 이 아니면 `bad_request`. 주소·이름 풀이 검사와 경로 칸 인코딩은 연결 진단
  (app.notify.diagnostics)과 같은 함수다. 풀린 IP 로 붙지는 않는다(https 인증서 확인이 이름을 지킨다).
- 키: 풀린 키는 이 프로세스 안에만 있다. `KatClient` 를 만들면 키·Account ID 가 로그 거르개에 오른다(`register_secrets` → `redact.add_secrets`).
  이 모듈이 올리는 것은 `ProviderFailed` 뿐이고(한 줄의 읽기 오류도 그 줄만 건너뛴다) 글은 이 파일의 표에서만 온다:
  통신 예외·제공사 오류 본문·실패 글(`failureMessage`)은 어디에도 옮기지 않는다(예외는 이어 붙이지도 않는다).
  제공사가 준 id 는 꼴이 맞고 키·Account ID·전화번호가 아닐 때만, 코드는 낱말(`^[A-Za-z_]{1,40}$`)일 때만 받는다. 문서의
  코드는 대소문자를 가리지 않고 읽는다(`diagnostics.vendor_entry`). 로그에는 종류·코드·상태만 남긴다 — 문서에 없는 4xx
  거절만 응답 모양(`_rejection_shape`: 낱말 코드, 검사 오류의 칸 이름·종류 낱말 5개까지, 번호를 가리고 키가 없는 80자
  이하의 숫자 없는 `error` 글)을 로그 줄과 글 끝 「(제공사 응답: …)」에 옮긴다. 값·숫자·요청 본문은 옮기지 않는다.
- **`maybe_sent`(보내기만)**: 문자가 갔는지 알 수 없으면 참. 거짓인 것은 둘뿐이다 — 한 바이트도 나가기 전의 실패(요청 전
  거절·이름 풀이·연결·TLS·연결 줄 기다림)와 제공사가 409 밖의 4xx 로 거절한 것(본문을 읽다 끊겨도 받은 상태로 가른다).
  그 밖은 모두 참: 쓰는 중·읽는 중의 시간 초과와 끊김, 읽을 수 없거나 id 가 없는 2xx, 3xx, **모든 5xx**(관문이 대신
  답했을 수 있다)와 409(같은 키가 처리되는 중). 「나갔는가」는 예외 종류만이 아니라 **전송이 요청 본문을 읽기 시작했는가**로
  정한다 — 연결 단계에서 걸린 시간 초과는 어느 쪽 제한이 먼저 걸렸든 「안 나감」이다.
- **끊김(`asyncio.CancelledError`)은 그대로 올라간다.** 보내기가 끊겼으면 부른 쪽이 「보냈는지 모름」으로 다뤄야 한다.
- **받은 문자(`received`)**: 제공사에 날짜 거르기가 없어 최신순 쪽을 `RECEIVED_MAX_PAGES` 쪽까지 읽고 여기서 거른다
  (`at >= since`). 다음 쪽으로 갈지는 그 쪽의 **끝 줄**로 정한다. 한 쪽이 응답 상한을 넘으면 그 자리부터 절반 크기로 한 번
  다시 읽는다(요청은 많아야 `RECEIVED_MAX_REQUESTS` 번). 건너뛴 줄 수는 `skipped`. 시각이 조회 시각보다 5분 넘게 앞선 줄은
  조회 시각으로 바꾸고 센다(`redated`). **다음 since 는 `Received.next_since`(조회 시각 − `SINCE_MARGIN_S` 10분)만 쓴다** —
  `max(at)` 이나 더 짧은 여유는 제공사 시계가 늦거나 줄이 늦게 붙을 때 문자를 영영 놓친다. 겹침은 `provider_id` 로 막는다.
  `truncated` 면 쪽 상한 뒤에 더 오래된 줄이 남아 있다: 다시 읽어도 같은 최신 줄만 오므로 **할 수 있는 일은 사람에게 알리는
  것뿐**이다. 본문은 줄 나눔을 `\n` 으로 맞추고 제어 글자·방향 덮어쓰기·꼬리표 글자·짝 없는 서로게이트를 뺀 뒤 4,000자까지
  (`body_cut`).

문서로 확인한 것(2026-11-23, https://docs.koreaaitel.com):
- api-reference — 인증, 기본 주소 https://api.koreaaitel.com
- api-reference/claw-ops-api/messages/send-message — `POST …/messages`: `To`·`From`·`Body`·`Type`(빼면 본문 길이로 sms/lms)·
  `IdempotencyKey`(빈 글은 400)·`Kakao{ChannelId, TemplateId, Variables}`(알림톡 — `Body`·`Type` 을 넣지 않는다)·
  `Fallback{Body, Disabled}`(빼면 알림톡 실패 때 문안 그대로 문자가 나간다) → 201 `messageId`·`status`·`failureCode`.
  오류 `{error, code}`: 400 `from_not_registered`·`invalid_phone`…, 401, 403(`overseas_ip_blocked`), 422 `quota_exceeded`·
  `recipient_blocked`·`content_blocked`, 429 `rate_limited`(+ `Retry-After`)
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
- 틀린 키와 틀린 Account ID 를 제공사가 어떻게 가르는지 문서에 없다: 401 → `bad_key`, 403 과 계정 경로의 404 → `bad_account`.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import httpx

from app.info import generic
from app.notify import diagnostics
from app.outreach import phone, redact
from app.security import crypto
from app.store.tables_outreach import NotifyConnection

logger = logging.getLogger(__name__)

TIMEOUT_S = diagnostics.TIMEOUT_S  # 요청 하나에 쓰는 전체 시간(이름 풀이 포함)
MAX_BYTES = 1_000_000  # 응답 본문은 여기까지만 읽는다
# 한 쪽 50줄: 가장 긴 문자(2,000자)가 \uXXXX 꼴(한 자 6바이트)로 50줄 와도 0.6MB 라 MAX_BYTES 에 걸리지 않는다(100줄이면 넘는다).
RECEIVED_PAGE_SIZE = 50  # 제공사 상한은 100
RECEIVED_MAX_PAGES = 4  # received 한 번에 읽는 줄은 RECEIVED_PAGE_SIZE × 이 값(200)까지
RECEIVED_MAX_REQUESTS = RECEIVED_MAX_PAGES * 2 + 1  # 한 쪽이 상한을 넘어 절반 크기로 다시 읽을 때의 요청 수 상한
SINCE_MARGIN_S = 600  # 다음 since = 조회 시각 − 이 값. 제공사 시계가 늦거나 줄이 늦게 붙어도 놓치지 않을 만큼(겹침은 id 로 막는다)
INBOUND_BODY_MAX = 4000  # 받은 문자 본문(글자 수)
FUTURE_SLACK = timedelta(minutes=5)  # 받은 문자의 시각이 이보다 더 앞서 있으면 조회 시각으로 바꾼다
RETRY_AFTER_MAX = 600
RESOLVE: diagnostics.Resolver | None = None  # 호스트 → IP 목록. None 이면 diagnostics.RESOLVE. 시험이 바꿔 끼운다
STATUS_MAP: dict[str, str] = {"queued": "accepted", "sent": "delivered", "failed": "failed", "received": "received"}  # P0 확인

MAYBE_SENT = " 보냈는지는 알 수 없습니다(이미 나갔을 수 있습니다)."
# 한국어 글의 표는 연결 진단과 한 벌을 같이 쓴다(app.notify.diagnostics 에 있다)
_MESSAGES = diagnostics.MESSAGES  # 우리 code → 글
_VENDOR = diagnostics.VENDOR  # 제공사 오류 code(문서) → (우리 code, 글)
_FAILURES = diagnostics.FAILURES  # failureCode(get-message 문서) → 글
_ITEMS = {"messages": "메시지", "calls": "통화"}
# call_info 가 돌려주는 칸(번호·계정·주소·자유 글은 뺀다): 낱말 · 참거짓 · 시각 + callId · duration
_CALL_WORDS = ("status", "direction", "answeredBy", "hangupCause", "hangupSource")
_CALL_FLAGS = ("callerIdRestricted", "recording")
_CALL_TIMES = ("dateCreated", "dateUpdated")
_NOT_SENT = diagnostics.NOT_SENT  # 나가기 전에 끝남(예외 종류)
_CODE = re.compile(r"[A-Za-z_]{1,40}")  # 제공사 오류 code 가운데 옮겨 적어도 되는 꼴
_FAILURE_CODE = re.compile(r"[a-z_]{1,40}")  # get-message 의 failureCode(저장되는 fail_code)는 소문자 낱말만
_FIELD = re.compile(r"[A-Za-z_.]{1,40}")  # 검사 오류(422)의 칸 이름·종류 낱말 가운데 옮겨 적어도 되는 꼴
_ERROR_TEXT = re.compile(r"(?:[^\W\d_]|[ .,:;'!?()\[\]/-]){1,80}")  # 오류 글: 글자·빈칸·문장부호뿐(숫자 없음)
SHAPE_MAX = 5  # 응답 모양에 옮기는 칸 이름·종류 낱말 수
_WORD = re.compile(r"[a-z][a-z_\-]{0,39}")  # 통화 상태 말(in-progress · no-answer …)
_ID = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9_.:\-]{1,100}")  # 글자·숫자가 하나는 있어야 한다
_IDEMPOTENCY = re.compile(r"[A-Za-z0-9_-]{8,64}")
_NUMBER = re.compile(r"[0-9+\-\s().]{3,25}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?")
_NOT_DIGIT = re.compile(r"[^0-9]")
_LINE_BREAK = re.compile(r"\r\n?|[\u2028\u2029]")  # 줄 나눔은 \n 하나로
# 받은 글에서 빼는 것: 줄 바꿈·탭 밖의 C0·DEL·C1 제어 글자, 글 방향을 덮어쓰는 글자, 짝 없는 서로게이트(DB 에 넣을 때 깨진다),
# 꼬리표 글자(U+E0000~E007F)
_UNPRINTABLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\ud800-\udfff\U000e0000-\U000e007f]")


def _now() -> datetime:
    """지금(UTC). 시험이 바꿔 끼운다."""
    return datetime.now(UTC)


def _default_transport() -> httpx.AsyncBaseTransport | None:
    """transport 를 주지 않은 클라이언트가 쓸 것 — None 이면 httpx 의 실제 전송. 시험에서는 이것이 막혀 있다."""
    return None


@dataclass(frozen=True)
class ProviderConn:
    """제공사 연결 값. 키·Account ID 는 이 값과 요청에만 있고 repr 에는 없다."""

    base_url: str
    account_id: str = field(repr=False)
    key: str = field(repr=False)


class ProviderFailed(Exception):
    """제공사를 부르지 못했거나 불렀지만 실패했다. message 는 한국어이고 키·번호·Account ID 가 없다.

    code: bad_key | bad_account | bad_sender | rate_limited | overseas_ip | timeout | network | bad_request | server | unknown.
    http_status 는 받은 상태 그대로(응답을 받지 못했으면 None). maybe_sent 가 참이면 문자가 갔는지 알 수 없다(모듈 머리 글).
    retry_after_s 는 429 의 Retry-After 초(600 까지, 없거나 읽을 수 없으면 None).
    """

    def __init__(self, code: str, message: str, http_status: int | None = None, *, maybe_sent: bool = False,
                 retry_after_s: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status, self.maybe_sent = code, message, http_status, maybe_sent
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class MessageRequest:
    """보낼 것 하나. channel 은 sms | kakao. kakao 면 kakao_channel(채널 id)·template_code(문안 id)가 있어야 하고
    body 는 쓰지 않는다(문안대로 나간다). fallback_sms 가 거짓이면 알림톡이 실패해도 문자로 대신 보내지 않는다.
    idempotency_key 는 `^[A-Za-z0-9_-]{8,64}$`."""

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
    """받은 문자 한 건. from_number(보낸 쪽)·to_number(받은 우리 번호)는 국내 번호면 phone.normalize 꼴, 나라 밖 번호면
    `+숫자`, 번호로 볼 수 없으면 phone.NO_NUMBER. at 은 UTC. body_cut 은 본문을 INBOUND_BODY_MAX 에서 잘랐다는 표시."""

    provider_id: str
    from_number: str = field(repr=False)
    body: str = field(repr=False)
    at: datetime
    has_media: bool
    to_number: str = field(default=phone.NO_NUMBER, repr=False)
    body_cut: bool = False


@dataclass(frozen=True)
class Received:
    """받은 문자 조회 한 번. items 는 오래된 것부터, fetched_at 은 조회를 시작한 시각. truncated 면 쪽 상한 뒤에 더 오래된
    줄이 남았거나 한 응답이 청한 쪽 크기보다 많은 줄을 실어 와 뒤를 버렸다(다시 읽어도 같은 줄만 온다 — 사람에게 알릴 것). skipped 는 읽을 수 없어 건너뛴 줄 수, redated 는 시각이
    앞서 있어 조회 시각으로 바꾼 줄 수."""

    items: list[Inbound]
    fetched_at: datetime
    truncated: bool = False
    skipped: int = 0
    redated: int = 0

    @property
    def next_since(self) -> datetime:
        """다음 조회에 줄 since. 일꾼은 이 값만 쓴다(스스로 여유를 정하지 않는다)."""
        return self.fetched_at - timedelta(seconds=SINCE_MARGIN_S)


@dataclass(frozen=True)
class Check:
    """연결 확인. senders 는 승인된 발신번호(phone.normalize 꼴, 그 꼴이 아니면 숫자만)."""

    ok: bool
    senders: list[str] = field(repr=False)
    latency_ms: int


# 카카오 채널·문안 목록(Task 101 — 읽기만). 경로(`GET …/kakao/channels?status=connected`, `GET …/kakao/templates?channelId=…`)는
# Task 69 보고에 적혀 있지만 응답 칸(문안 본문·상태 말·쪽 나눔)은 저장소의 문서 기록에 없다 → 짐작하지 않고 「확인하지 못함」.
# 확인되면 이 값을 참으로 하고 KatClient.kakao_* 둘만 채운다(쪽 상한을 두고, 상태 말은 approved|reviewing|rejected 로 바꿔서).
KAKAO_LISTING_CONFIRMED = False
KAKAO_NOT_CONFIRMED = "채널·문안 목록을 읽는 길을 확인하지 못했습니다."


@dataclass(frozen=True)
class KakaoChannelInfo:
    id: str
    name: str
    status: str  # 제공사 말 그대로(예: connected)


@dataclass(frozen=True)
class KakaoTemplateInfo:
    id: str  # 제공사의 문안 id(보낼 때의 template_code)
    body: str = field(repr=False)
    status: str  # approved | reviewing | rejected


class Provider(Protocol):
    """제공사가 하는 일 다섯. 실패는 모두 ProviderFailed."""

    async def check(self) -> Check: ...

    async def send_message(self, req: MessageRequest) -> Accepted: ...

    async def message_status(self, provider_id: str) -> Delivery: ...

    async def received(self, since: datetime | None) -> Received: ...

    async def call_info(self, provider_call_id: str) -> dict: ...


# ── 키 지우기·값 고르기 ─────────────────────────────────────────────

def register_secrets(*values: str) -> None:
    """키·Account ID 를 로그 거르개에 올린다(redact.add_secrets — 더하기만 하고 다른 곳의 install 에 밀려나지 않는다).
    8자보다 짧은 값은 오르지 않는다(보통 글을 망가뜨린다 — 그런 값으로는 부르지도 않는다)."""
    redact.add_secrets(*values)


def _holds_secret(text: str, secrets: list[str]) -> bool:
    return any(generic.key_survives(text, s) for s in secrets)


def _safe(pattern: re.Pattern[str], value: object, secrets: list[str]) -> str | None:
    """제공사가 준 코드·낱말: 꼴이 맞고 키·Account ID 가 들어 있지 않을 때만 그 값."""
    if isinstance(value, str) and pattern.fullmatch(value) and not _holds_secret(value, secrets):
        return value
    return None


def _safe_id(value: object, secrets: list[str]) -> str | None:
    """제공사가 준 id: 꼴이 맞고 키·Account ID 가 아니고 전화번호도 아닐 때만. 숫자가 길게 이어진 것만으로는 막지 않는다."""
    found = _safe(_ID, value, secrets)
    return found if found is not None and phone.normalize(found) is None else None


def _peer_number(raw: object) -> str:
    """제공사가 준 번호 → 국내 번호면 phone.normalize 꼴, 나라 밖(+82·+0 이 아닌 +) 번호면 `+숫자`, 그 밖은 phone.NO_NUMBER.
    나라 밖 번호를 숫자만 남기면 국내 번호와 같은 열쇠가 될 수 있다(+1 588 0199 ≠ 1588-0199)."""
    if not isinstance(raw, str):
        return phone.NO_NUMBER
    local = phone.normalize(raw)
    if local is not None:
        return local
    text, digits = raw.strip(), _NOT_DIGIT.sub("", raw)
    if text.startswith("+") and _NUMBER.fullmatch(text) and not digits.startswith(("82", "0")) and 7 <= len(digits) <= 15:
        return "+" + digits
    return phone.NO_NUMBER


def _when(value: object) -> datetime | None:
    """ISO 8601 글 → UTC 시각(tz 가 없으면 UTC 로 본다). 읽을 수 없으면 None."""
    try:
        at = datetime.fromisoformat(value)
        return (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _retry_after(value: object) -> int | None:
    text = value.strip() if isinstance(value, str) else ""
    if not (text.isascii() and text.isdigit()):
        return None
    return RETRY_AFTER_MAX if len(text) > 9 else min(int(text), RETRY_AFTER_MAX)  # 터무니없이 큰 값도 상한으로


class _BodyNotRead(ProviderFailed):
    """2xx 인데 본문이 응답 상한을 넘어 읽지 않았다. 받은 문자 조회가 쪽을 줄여 한 번 다시 읽는 데 쓴다(압축돼 와서 읽지 않은
    것은 여기 들지 않는다 — 쪽을 줄여도 같다)."""


def _failed(code: str, label: str, *, message: str | None = None, status: int | None = None, maybe_sent: bool = False,
            retry_after_s: int | None = None, kind: type[ProviderFailed] = ProviderFailed,
            shape: str | None = None) -> ProviderFailed:
    """실패 하나를 만들고 종류(와 있으면 거른 응답 모양)만 로그에 남긴다."""
    logger.warning("제공사 호출 실패: %s code=%s status=%s maybe_sent=%s%s", label, code, status, maybe_sent,
                   f" 응답={shape}" if shape else "")
    return kind(code, (message or _MESSAGES[code]) + (MAYBE_SENT if maybe_sent else ""), status,
                maybe_sent=maybe_sent, retry_after_s=retry_after_s)


def _rejection_shape(data: object, secrets: list[str]) -> str | None:
    """오류 본문 → 옮겨 적어도 되는 모양 한 줄 또는 None. 꼴이 맞고 키·Account ID 가 없는 것만: 낱말 code, 검사 오류
    (`detail: [{loc, type}]`·`errors: [{field}]`)의 칸 이름(loc 의 글 조각을 「.」로 이은 것)·종류 낱말을 SHAPE_MAX 개까지,
    번호를 가린 뒤 숫자 없는 80자 이하의 `error` 글. 값(input·msg·message)과 그 밖의 칸은 보지 않는다."""
    if not isinstance(data, dict):
        return None
    fields: list[str] = []
    types: list[str] = []
    for name in ("detail", "errors"):
        items = data.get(name)
        for item in items if isinstance(items, list) else ():
            if not isinstance(item, dict):
                continue
            loc = item.get("loc")
            where = ".".join(p for p in loc if isinstance(p, str)) if isinstance(loc, list) else item.get("field")
            for found, into in ((_safe(_FIELD, where, secrets), fields), (_safe(_FIELD, item.get("type"), secrets), types)):
                if found and found not in into and len(into) < SHAPE_MAX:
                    into.append(found)
    error = data.get("error")
    error = _safe(_ERROR_TEXT, redact.hide_phones(error), secrets) if isinstance(error, str) else None
    parts = [f"code={code}"] if (code := _safe(_CODE, data.get("code"), secrets)) else []
    parts += [f"fields={','.join(fields)}"] if fields else []
    parts += [f"types={','.join(types)}"] if types else []
    parts += [f"error={error}"] if error else []
    return "; ".join(parts) or None


def _http_failure(status: int, data: object, label: str, *, on_item: bool, maybe_sent: bool, retry_after: object,
                  secrets: list[str]) -> ProviderFailed:
    """2xx 가 아닌 응답 → ProviderFailed. code·글은 연결 진단과 같은 `diagnostics.http_failure`. data 는 읽은 오류 본문
    (JSON 이 아니면 None). 4xx 인데 code 가 문서에 없으면 거른 모양(`_rejection_shape`)을 로그 줄과 글 끝에 옮긴다."""
    vendor = data.get("code") if isinstance(data, dict) else None
    code, message = diagnostics.http_failure(status, vendor, on_item=on_item, item=_ITEMS.get(label, "메시지"))
    shape = None
    if 400 <= status < 500 and diagnostics.vendor_entry(vendor) is None:
        shape = _rejection_shape(data, secrets)
        message = f"{message}(제공사 응답: {shape})" if shape else message
    return _failed(code, label, message=message, status=status, maybe_sent=maybe_sent,
                   retry_after_s=_retry_after(retry_after) if status == 429 else None, shape=shape)


# ── 제공사 칸 이름을 아는 세 함수(P0-R 뒤 여기만 고친다) ────────────


def _message_body(req: MessageRequest) -> dict:
    """보내기 본문. 모자라거나 보낼 꼴이 아니면 ProviderFailed(bad_request) — 요청 전. 가짜(FakeProvider)도 이것을 거친다."""
    if not all(isinstance(v, str) and v for v in (req.to, req.sender)):
        raise ProviderFailed("bad_request", "받는 번호와 발신번호가 모두 있어야 보냅니다.")
    if not isinstance(req.idempotency_key, str) or not _IDEMPOTENCY.fullmatch(req.idempotency_key):
        raise ProviderFailed("bad_request", "중복 방지 키가 없거나 쓸 수 없는 꼴입니다(영문·숫자·_·- 8~64자).")
    body: dict = {"To": req.to, "From": req.sender, "IdempotencyKey": req.idempotency_key}
    if req.channel == "sms":
        if not isinstance(req.body, str) or not req.body:
            raise ProviderFailed("bad_request", "보낼 글이 비어 있습니다.")
        return {**body, "Body": req.body}  # Type 은 뺀다 — 제공사가 길이로 sms/lms 를 고른다
    if req.channel == "kakao":
        if not all(isinstance(v, str) and v for v in (req.kakao_channel, req.template_code)):
            raise ProviderFailed("bad_request", "알림톡은 채널과 문안이 있어야 보냅니다.")
        variables = {} if req.template_vars is None else req.template_vars
        if not isinstance(variables, dict) or not all(isinstance(x, str) for kv in variables.items() for x in kv):
            raise ProviderFailed("bad_request", "알림톡 변수는 이름과 값이 모두 글이어야 합니다.")
        body["Kakao"] = {"ChannelId": req.kakao_channel, "TemplateId": req.template_code, "Variables": dict(variables)}
        if not req.fallback_sms:
            body["Fallback"] = {"Disabled": True}  # 빼면 제공사가 문자로 대신 보낸다
        elif isinstance(req.fallback_body, str) and req.fallback_body:
            body["Fallback"] = {"Body": req.fallback_body}
        return body
    raise ProviderFailed("bad_request", "이 통로로는 보낼 수 없습니다.")


def _parse_delivery(data: dict, secrets: list[str], status: int) -> Delivery:
    """메시지 하나 → Delivery. 모르는 상태 말은 짐작하지 않고 실패(unknown)."""
    word = data.get("status")
    state = STATUS_MAP.get(word) if isinstance(word, str) else None
    if state not in ("accepted", "delivered", "failed"):
        raise _failed("unknown", "messages", status=status)
    if state != "failed":
        return Delivery(state=state)
    code = _safe(_FAILURE_CODE, data.get("failureCode"), secrets) or "unknown"
    text = _FAILURES.get(code) or f"보내지 못했습니다(제공사 코드 {code})."
    return Delivery(state="failed", fail_code=code, fail_text=text, fell_back=False)  # P0 확인: 대신 나간 문자를 알 칸이 없다


def _parse_inbound(row: object, secrets: list[str]) -> Inbound | None:
    """받은 문자 한 줄 → Inbound(시각은 제공사가 준 그대로). 읽을 수 없는 줄(받은 것이 아님·id·시각 없음)은 None."""
    if not isinstance(row, dict) or row.get("direction", "inbound") != "inbound":
        return None
    provider_id, at = _safe_id(row.get("messageId"), secrets), _when(row.get("dateCreated"))
    if provider_id is None or at is None:
        return None
    body = _UNPRINTABLE.sub("", _LINE_BREAK.sub("\n", row["body"])) if isinstance(row.get("body"), str) else ""
    for secret in secrets:
        body = generic.scrub(body, secret)
    if _holds_secret(body, secrets):
        body = ""
    media, urls = row.get("numMedia"), row.get("mediaUrl")
    return Inbound(provider_id=provider_id, from_number=_peer_number(row.get("from")), body=body[:INBOUND_BODY_MAX], at=at,
                   has_media=(type(media) is int and media > 0) or (isinstance(urls, list) and bool(urls)),
                   to_number=_peer_number(row.get("to")), body_cut=len(body) > INBOUND_BODY_MAX)


# ── 호출 ────────────────────────────────────────────────────────────


class KatClient:
    """한국AI통신 REST. 만들면 키·Account ID 가 로그 거르개에 오른다. transport 는 시험용(httpx.MockTransport)."""

    def __init__(self, conn: ProviderConn, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.conn = conn
        self._transport = transport if transport is not None else _default_transport()
        self._secrets = [s for s in (conn.key, conn.account_id) if isinstance(s, str) and s]
        register_secrets(*self._secrets)

    def _unusable(self) -> ProviderFailed | None:
        """연결 값 때문에 부를 수 없는 까닭(요청 전)."""
        if diagnostics.base_url_problem(self.conn.base_url) is not None:
            return ProviderFailed("bad_request", "기본 주소를 쓸 수 없습니다. https://호스트 꼴의 공개 주소여야 합니다.")
        for value, code, name in ((self.conn.key, "bad_key", "키"), (self.conn.account_id, "bad_account", "Account ID")):
            if not isinstance(value, str) or len(value) < diagnostics.MIN_SECRET or not value.isascii() \
                    or not value.isprintable():
                return ProviderFailed(code, f"{name} 값이 비었거나 너무 짧거나 쓸 수 없는 글자가 있습니다. "
                                            "설정 → 알림 연결에서 다시 넣어 주세요.")
        return None

    def _request_parts(self, resource: str, item_id: object, on_item: bool,
                       body: dict | None) -> tuple[str, dict, bytes | None]:
        """요청 전 검사를 하고 (주소, 머리글, 본문)을 만든다. 안 되면 ProviderFailed — 아무것도 나가지 않았다."""
        refused = self._unusable()
        if refused is not None:
            raise refused
        if on_item and (not isinstance(item_id, str) or not item_id):
            raise ProviderFailed("bad_request", f"{_ITEMS[resource]} id 가 비어 있습니다.")
        url = f"{self.conn.base_url.rstrip('/')}/v1/accounts/{diagnostics.segment(self.conn.account_id)}/{resource}"
        url += f"/{diagnostics.segment(item_id)}" if on_item else ""
        headers = {"Authorization": f"Bearer {self.conn.key}", "Accept": "application/json", "Accept-Encoding": "identity"}
        if body is None:
            return url, headers, None
        content = json.dumps(body).encode()  # 요청을 만들기 전에 글로 바꾼다 — _message_body 가 글만 남겼으므로 실패하지 않는다
        return url, {**headers, "Content-Type": "application/json", "Content-Length": str(len(content))}, content

    async def _call(self, method: str, resource: str, item_id: object = None, *, on_item: bool = False,
                    params: dict | None = None, body: dict | None = None) -> tuple[int, dict]:
        """요청 한 번 → (상태, 2xx 의 JSON 객체). 그 밖은 ProviderFailed. 예외는 종류만 본다(글에 주소·머리글이 있다)."""
        url, headers, content = self._request_parts(resource, item_id, on_item, body)
        exchange, problem = diagnostics.Exchange(sends=method == "POST"), None  # 「나갔는가」는 진단과 같은 구현
        try:
            async with asyncio.timeout(TIMEOUT_S):
                problem = await diagnostics.resolve_problem(self.conn, RESOLVE)
                if problem is None:
                    async with diagnostics.make_client(transport=self._transport) as http:
                        await exchange.run(http, method, url, headers=headers, params=params, content=content,
                                           max_bytes=MAX_BYTES)
        except Exception as e:  # noqa: BLE001 — 어떤 예외 글도 밖으로 내지 않는다(끊김 CancelledError 는 그대로 올라간다)
            exchange.fail(e)
        del url, headers, content, body  # 키·번호가 든 것은 여기서 버린다(지역 변수까지 찍는 traceback 에 남지 않게)
        status, code, maybe_sent = exchange.status, exchange.error, exchange.maybe_sent
        if code is not None and status is None:  # except 밖에서 올린다 — 원래 예외(주소·키가 든)를 이어 붙이지 않으려고
            raise _failed(code, resource, maybe_sent=maybe_sent)
        if problem is not None:
            if problem == diagnostics.RESOLVE_FAILED:
                raise _failed("network", resource, message="기본 주소의 호스트 이름을 찾지 못했습니다.")
            raise _failed("bad_request", resource, message="기본 주소가 내부망으로 풀려 부르지 않았습니다.")
        try:
            data = json.loads(exchange.raw) if exchange.raw is not None and code is None else None
        except (ValueError, RecursionError):
            data = None
        if not 200 <= status < 300:  # 본문을 읽다 끊겼어도 받은 상태로 가른다
            raise _http_failure(status, data, resource, on_item=on_item,
                                maybe_sent=maybe_sent, retry_after=exchange.retry_after, secrets=self._secrets)
        if code is not None:  # 2xx 를 받고 본문을 읽다 끊겼다 — 보내기였으면 갔을 수 있다
            raise _failed(code, resource, status=status, maybe_sent=maybe_sent)
        if not isinstance(data, dict):  # 읽을 수 없거나 읽지 않은(상한·압축) 2xx
            raise _failed("unknown", resource, status=status, maybe_sent=maybe_sent,
                          kind=_BodyNotRead if exchange.raw is None and not exchange.packed else ProviderFailed)
        return status, data

    async def check(self) -> Check:
        """인증 + 발신번호 목록. 승인된 번호만 돌려준다."""
        start = time.perf_counter()
        status, data = await self._call("GET", "sender-numbers")
        latency_ms = int((time.perf_counter() - start) * 1000)
        rows = data.get("senderNumbers")
        if not isinstance(rows, list):
            raise _failed("unknown", "sender-numbers", status=status)
        numbers = [row["number"] for row in rows if isinstance(row, dict) and row.get("status") == "approved"
                   and isinstance(row.get("number"), str) and _NUMBER.fullmatch(row["number"])]
        senders = [phone.normalize(n) or _NOT_DIGIT.sub("", n) for n in numbers]  # 저장된 번호와 같은 열쇠
        return Check(ok=True, senders=list(dict.fromkeys(s for s in senders if s)), latency_ms=latency_ms)

    async def send_message(self, req: MessageRequest) -> Accepted:
        """한 건 보내기(문자 또는 알림톡). 접수되면 제공사 id. 201 의 status 가 failed 여도 id 를 돌려준다(상태 조회가 알린다).
        실패의 maybe_sent 가 참이면 보냈는지 알 수 없다. 끊기면(CancelledError) 그대로 올라간다 — 그것도 「모름」이다."""
        status, data = await self._call("POST", "messages", body=_message_body(req))
        provider_id = _safe_id(data.get("messageId"), self._secrets)
        if provider_id is None:
            raise _failed("unknown", "messages", status=status, maybe_sent=True)
        return Accepted(provider_id=provider_id)

    async def message_status(self, provider_id: str) -> Delivery:
        status, data = await self._call("GET", "messages", provider_id, on_item=True)
        return _parse_delivery(data, self._secrets, status)

    async def received(self, since: datetime | None) -> Received:
        """받은 문자를 오래된 것부터. since(tz 없으면 UTC) 와 같거나 뒤인 것만 — 겹침은 부른 쪽이 provider_id 로 막는다.
        since 가 None 이면 가장 최근 한 쪽만. 다음 since 는 돌려준 값의 next_since 를 쓴다(모듈 머리 글)."""
        fetched_at = _now()
        floor = since.replace(tzinfo=UTC) if since is not None and since.tzinfo is None else since
        found: dict[str, Inbound] = {}
        size, offset, skipped, redated, more, asked, cut = RECEIVED_PAGE_SIZE, 0, 0, 0, False, 0, False
        while offset < RECEIVED_PAGE_SIZE * RECEIVED_MAX_PAGES:
            if asked >= RECEIVED_MAX_REQUESTS:  # 굳은 상한 — 아래 멈춤 조건이 어긋나도 끝없이 묻지 않는다
                raise _failed("unknown", "messages")
            asked += 1
            try:
                status, data = await self._call("GET", "messages", params={
                    "status": "received", "pageSize": str(size), "page": str(offset // size)})
            except _BodyNotRead:
                if size < RECEIVED_PAGE_SIZE:
                    raise
                size = RECEIVED_PAGE_SIZE // 2  # 한 쪽이 응답 상한을 넘었다 — 같은 자리부터 절반 크기로 한 번만 다시
                continue
            rows = data.get("data")
            if not isinstance(rows, list):
                raise _failed("unknown", "messages", status=status)
            if len(rows) > size:  # pageSize 를 듣지 않은 응답 — 청한 만큼만 읽고 버린 것이 있음을 알린다
                rows, cut = rows[:size], True
            last: datetime | None = None  # 이 쪽에서 읽힌 마지막 줄의 시각
            for row in rows:
                try:
                    message = _parse_inbound(row, self._secrets)
                except Exception:  # noqa: BLE001 — 한 줄의 오류는 그 줄만 건너뛴다
                    message = None
                if message is None:
                    skipped += 1
                    continue
                last = message.at
                if message.provider_id in found:
                    continue
                if message.at > fetched_at + FUTURE_SLACK:
                    message, redated = replace(message, at=fetched_at), redated + 1
                if floor is None or message.at >= floor:
                    found[message.provider_id] = message
            offset += size
            more = floor is not None and len(rows) >= size and (last is None or last >= floor)
            if not more:
                break
        if more or cut or skipped or redated:
            logger.warning("받은 문자 조회: 쪽 상한 뒤에도 남음=%s 건너뜀=%d 시각 바꿈=%d", more or cut, skipped, redated)
        return Received(items=sorted(found.values(), key=lambda m: m.at), fetched_at=fetched_at, truncated=more or cut,
                        skipped=skipped, redated=redated)

    async def call_info(self, provider_call_id: str) -> dict:
        """통화 하나의 칸 가운데 번호·계정·주소가 아닌 것만: callId · duration(초) · _CALL_WORDS(제공사 말 그대로) ·
        _CALL_FLAGS · _CALL_TIMES(ISO 글). 없거나 꼴이 다른 값은 None."""
        status, data = await self._call("GET", "calls", provider_call_id, on_item=True)
        call_id, duration = data.get("callId"), data.get("duration")
        if call_id is not None and _safe_id(call_id, self._secrets) is None:
            raise _failed("unknown", "calls", status=status)
        out: dict = {"callId": call_id, "duration": duration if type(duration) is int and 0 <= duration <= 86_400 else None}
        out |= {name: _safe(_WORD, data.get(name), self._secrets) for name in _CALL_WORDS}
        out |= {name: data.get(name) if type(data.get(name)) is bool else None for name in _CALL_FLAGS}
        for name in _CALL_TIMES:
            value = data.get(name)
            out[name] = value if isinstance(value, str) and _TIME.fullmatch(value) and _when(value) is not None else None
        return out

    async def kakao_channels(self) -> list[KakaoChannelInfo]:
        """연결된 카카오 채널. 응답 칸을 확인하기 전에는 부르지 않는다 — ProviderFailed("not_confirmed")."""
        raise ProviderFailed("not_confirmed", KAKAO_NOT_CONFIRMED)

    async def kakao_templates(self, channel: str) -> list[KakaoTemplateInfo]:
        """그 채널의 알림톡 문안. 위와 같다(확인 전에는 요청 0번)."""
        raise ProviderFailed("not_confirmed", KAKAO_NOT_CONFIRMED)


def client_for(row: NotifyConnection) -> Provider:
    """저장된 연결 줄로 제공사 클라이언트를 만든다(키를 푼다). 시험이 바꿔 끼우는 한 곳 — `provider.client_for(row)` 로 부른다."""
    try:
        key = crypto.decrypt(row.secret_ciphertext)
    except crypto.SecretUnreadable:
        key = None
    if key is None:
        raise ProviderFailed("bad_key", "저장된 키를 읽을 수 없습니다. 설정 → 알림 연결에서 키를 다시 넣어 주세요.")
    return KatClient(ProviderConn(base_url=row.base_url, account_id=row.account_id, key=key))
