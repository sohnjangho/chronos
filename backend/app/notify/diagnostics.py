"""한국AI통신 REST 연결 진단(계획 4 Task 59, 0단계 P1~P4). 설정 화면의 「연결 진단」과 실측 스크립트가 같이 쓴다.

- 부르는 쪽은 `run_checks` 만 쓴다(요청 상한 8번을 단계끼리 나눠 쓰도록). 단계 함수(`check_*`)는 공유 상한
  `calls: Calls` 를 꼭 받는다. 클라이언트는 `make_client()` 로 만든다(trust_env=False·리다이렉트 안 따름·15초).
- 함수는 찍지 않고, 환경 변수를 읽지 않고, 끝내지 않는다. 예외도 던지지 않는다(실패는 `ok=False`). `run_checks` 는 언제나
  P1~P4 네 줄을 돌려준다 — 고르지 않은 걸음은 `skipped=True`(code `skipped_not_requested`).
- 걸음(`DiagnosticStep`)의 `label`·`detail` 은 화면에 그대로 보이는 한국어 문장이다. 기계가 읽을 것은 따로 있다:
  `code`(아래 낱말) · `maybe_sent`(시험 문자가 갔을 수 있다 — 다시 누르면 두 번째 문자가 간다) · `pending`(접수는 됐고 전송
  확인만 아직 — 실패가 아니다) · `notes`(HTTP 상태·바이트 수·제공사 말 그대로·구조 — 화면은 접어 보인다).
  code: `ok` · `skipped_not_requested`(고르지 않은 걸음) · `skipped_no_send`(시험 문자를 청하지 않음) · `skipped_no_numbers`
  (발신·받는 번호 없음) · `skipped_no_message`(조회할 문자가 없음) · `request_limit` · `still_queued`(pending) ·
  `delivery_failed` · `untrusted_client` · `bad_base_url` · `resolve_failed` · 그리고 제공사 호출과 같은 `bad_key` ·
  `bad_account` · `bad_sender` · `rate_limited` · `overseas_ip` · `timeout` · `network` · `bad_request` · `server` · `unknown`.
- 제공사 오류 코드·우리 실패 코드의 한국어 글(`MESSAGES`·`VENDOR`·`FAILURES`·`http_failure`)과 「나갔는가」(`Exchange`)는 이
  모듈에 한 벌만 있고 제공사 호출(app.outreach.provider)이 그대로 가져다 쓴다.
- 요청 전에 막는 것: 클라이언트가 환경(프록시 변수 등)을 믿으면(`trust_env` 참) · 주소가 https 가 아니거나 사용자 정보(@)가
  있거나 localhost·내부망이면 · 키·Account ID 가 비었거나 8자보다 짧거나 쓸 수 없는 글자면 · 호스트 이름을 풀어(5초 안,
  `RESOLVE` 바꿔 끼울 수 있음) 공인 IP 만 나오지 않으면. 이때 모든 단계가 실패(요청 0번).
  주소의 호스트는 고정하지 않는다(관리자가 설정에서 바꿀 수 있고, 저장할 때의 검사는 뒤 작업).
- `detail`·`notes` 는 이미 지운 글이다: 키·Account ID 와 번호는 app.outreach.redact.scrub(연락 전체가 쓰는 한 곳 — 인코딩·
  대소문자·섞인 꼴, 번호 모양)으로, 여기서는 더해서 알려 준 번호(발신·수신 — 대표번호 꼴 포함, 구분·+82·%인코딩 꼴),
  8자리 이상 숫자 묶음, 40자 넘는 토큰을 지우고 한 줄로 자른다. 응답은 칸 이름(구조)만 남기고, 발신번호는 숫자 없이
  순번·상태만 남긴다.
- 실제 문자는 `send_test_sms is True`(글 "true"·1 은 아님)이고 공유 상한에 2번(POST + 상태 조회 1번)이 남았을 때만 1건.
  기본 「연결 테스트」는 보내지 않는다.
- 요청 상한 8번(`Calls`; P1 1 + P2 1 + P3 4 + P4 1 = 7). 요청마다 15초(연결 5초) 제한 — 보내고 본문을 다 읽기까지 합쳐서도
  15초(본문을 조금씩 흘리는 서버에 붙잡히지 않는다)·리다이렉트 안 따름. 응답 본문은 1MB 까지만 읽고 압축된 응답은 풀지 않는다.
  단계를 돌리면 키·Account ID 가 로그 거르개에 오른다(redact.add_secrets). 경로에 넣는 Account ID·messageId 는 %인코딩한다.
  DB 에 쓰지 않는다.
- 시험 문자(P2)의 `maybe_sent`: 요청 본문이 나갔고 깨끗한 거절(409 밖의 4xx)이 아니면 참 — 5xx·409·3xx, 읽을 수 없거나
  id 가 없는 2xx, 본문이 나간 뒤의 시간 초과·끊김. 이때 `detail` 끝에 `MAYBE_SENT` 글이 붙는다. 진단이 도중에 끊기면
  (취소·부른 쪽의 전체 시간 제한) 걸음이 돌아오지 않으므로 넘겨 준 `Calls.maybe_sent` 를 본다.
- 한국 밖 IP 에서 문자를 보내면 403 `overseas_ip_blocked` 가 온다고 문서에 있다.

본 문서(2026-11-23, https://docs.koreaaitel.com):
- api-reference — 인증 `Authorization: Bearer <API Key>`, 기본 주소 https://api.koreaaitel.com
- api-reference/claw-ops-api/sender-numbers/list-sender-numbers — `GET /v1/accounts/{accountId}/sender-numbers`
  → `{senderNumbers: [{number, status: approved|pending}]}`
- api-reference/claw-ops-api/messages/send-message — `POST …/messages` 본문 `To`·`From`·`Body`·`Type`(sms|lms|mms|ata|bms)·
  `IdempotencyKey`(같은 키로 다시 보내면 보내지 않고 1회차 결과) → 201, 칸 `messageId`·`status`·`failureCode`…
  오류 본문 `{error, code}`(400·401·403·422·429, 429 는 `Retry-After`)
- api-reference/claw-ops-api/messages/get-message — `GET …/messages/{messageId}`, `status` queued|sent|failed|received,
  `failureCode`(실패 사유 코드 — 분기는 이것으로)
- messages(안내) — `GET …/messages?status=received&pageSize=20` → `{data: [...], meta: {page, pageSize, total}}`
"""

import asyncio
import ipaddress
import json
import re
import socket
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus

import httpx

from app.info.generic import base_url_problem as _info_url_problem
from app.outreach import redact

DEFAULT_BASE_URL = "https://api.koreaaitel.com"
MAX_REQUESTS = 8
TIMEOUT_S = 15.0
CONNECT_TIMEOUT_S = 5.0  # 연결 제한은 전체보다 짧게 — 닿지 않는 호스트에서 「연결 시간 초과」가 먼저 난다(보낸 것이 없음이 분명해진다)
MAX_BODY_BYTES = 1_000_000  # 응답 본문은 여기까지만 읽는다
RESOLVE_TIMEOUT_S = 5.0  # 이름 풀이에 쓰는 시간
MIN_SECRET = 8  # 이보다 짧은 키·Account ID 는 지우기가 보통 글을 망가뜨린다
POLL_TIMES = 4
POLL_GAP_S = 5
SMS_TEXT = "[ChronOS] 실측 문자입니다."
FINAL = ("sent", "failed")
LABELS = {"P1": "인증 + 발신번호 목록", "P2": "시험 문자 1건 보내기", "P3": "보낸 문자 상태 조회", "P4": "받은 문자 목록"}
UNTRUSTED_CLIENT = "프록시 설정을 따르는 연결로는 진단하지 않습니다(프로그램 설정 문제입니다)."
UNTRUSTED_CLIENT_NOTE = "untrusted_client · 클라이언트는 trust_env=False 로 만들어야 합니다 — make_client() 를 쓰세요"
MAYBE_SENT = "보냈는지 알 수 없음 — 문자가 갔을 수도 안 갔을 수도 있습니다. 다시 누르면 두 번째 문자가 갈 수 있습니다"
_SEP = r"(?:[\s.\-()+]|%20|%2D|%2E|%28|%29|%2B)*"  # 번호 사이 구분(%인코딩 꼴 포함)
_DIGITS_RE = re.compile(r"\d{8,}")  # 7자리 넘는(8자리 이상) 숫자 묶음
_TOKEN_RE = re.compile(r"[A-Za-z0-9%+/=_\-]{40,}")
_BAD_URL_CHAR = re.compile(r"[\s%\\;,&=]")  # 기본 주소에 올 수 없는 글자

RESOLVE_FAILED = "주소의 호스트 이름을 찾지 못했습니다(이름을 풀지 못했거나 시간이 너무 걸렸습니다)."
RESOLVED_INSIDE = "주소의 호스트가 내부망으로 이어져 부르지 않았습니다."
NO_ROOM = "남은 요청 횟수가 모자라 시험 문자를 보내지 않았습니다(보낸 뒤 결과를 확인할 수 없습니다)."
NOT_REQUESTED = "이번에는 확인하지 않았습니다."
NO_SEND = "시험 문자를 보내지 않았습니다 — [시험 문자]를 누를 때만 보냅니다."
NO_NUMBERS = "발신번호와 받을 번호가 모두 있어야 시험 문자를 보냅니다."
NO_MESSAGE = "보낸 시험 문자가 없어 확인하지 않았습니다."
OUT_OF_REQUESTS = "한 번의 진단에 쓸 수 있는 요청 횟수를 다 썼습니다."
ACCEPTED = "시험 문자가 접수됐습니다."
STILL_QUEUED = "접수됨 — 통신사로 넘어가기를 기다리는 중입니다. 다시 보내지 않아도 됩니다."
_SENDER_WORDS = {"approved": "승인", "pending": "심사 중"}  # 발신번호 상태(그 밖은 「그 밖」)
_STATUS_WORDS = {"queued": "접수됨", "sent": "전송됨", "failed": "실패"}  # 문자 상태

# ── 제공사 말 → 우리 코드·한국어 글. 제공사 호출(app.outreach.provider)과 이 표 한 벌을 같이 쓴다 ──
MESSAGES = {
    "bad_key": "제공사가 키를 받아들이지 않았습니다. 설정 → 알림 연결에서 키를 확인해 주세요.",
    "bad_account": "이 계정으로는 쓸 수 없습니다. Account ID 와 구독 상태를 확인해 주세요.",
    "bad_sender": "발신번호가 등록·승인되지 않았습니다.",
    "rate_limited": "요청이 너무 잦습니다. 잠시 뒤 다시 해 주세요.",
    "overseas_ip": "제공사는 한국 안의 IP 주소에서 온 요청만 받습니다. 이 서버가 나가는 IP 가 한국 밖으로 보입니다.",
    "timeout": "제공사 응답이 시간 안에 오지 않았습니다.",
    "network": "제공사와 통신하지 못했습니다(연결하지 못했거나 도중에 끊겼습니다).",
    "bad_request": "제공사가 요청을 받아들이지 않았습니다.",
    "server": "제공사 서버에서 오류가 났습니다.",
    "unknown": "제공사 응답을 읽지 못했습니다.",
}
VENDOR = {  # 제공사 오류 code(문서) → (우리 code, 글)
    "from_not_registered": ("bad_sender", MESSAGES["bad_sender"]),
    "invalid_phone": ("bad_request", "받는 번호가 올바르지 않습니다."),
    "INVALID_PHONE_NUMBER": ("bad_request", "받는 번호가 올바르지 않습니다."),
    "UNSUPPORTED_COUNTRY": ("bad_request", "지원하지 않는 나라의 번호입니다."),
    "body_too_long": ("bad_request", "글이 너무 깁니다."),
    "recipient_blocked": ("bad_request", "제공사의 수신 거부 목록에 있는 번호입니다."),
    "quota_exceeded": ("bad_request", "이번 달 발송 한도를 넘었습니다."),
    "content_blocked": ("bad_request", "제공사가 내용을 차단했습니다."),
    "overseas_ip_blocked": ("overseas_ip", MESSAGES["overseas_ip"]),
    "kakao_variable_missing": ("bad_request", "알림톡 문안의 변수가 빠졌습니다."),
    "kakao_variable_unknown": ("bad_request", "알림톡 문안에 없는 변수가 있습니다."),
}
FAILURES = {  # failureCode(get-message 문서) → 글
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
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)  # 나가기 전에 끝남
_EMBEDDING_V6 = tuple(ipaddress.ip_network(n) for n in ("::/96", "64:ff9b::/96", "fec0::/10"))

Sleep = Callable[[float], Awaitable[None]]
Resolver = Callable[[str, int], list[str]]


def _system_resolve(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


# 호스트 → IP 글 목록. 스레드에서 부르고 RESOLVE_TIMEOUT_S 안에 끝나야 한다. 시험은 바꿔 끼운다(DNS 를 쓰지 않음).
RESOLVE: Resolver = _system_resolve


@dataclass(frozen=True)
class DiagnosticConn:
    """진단에 쓸 연결 값. 키·번호는 이 값과 요청에만 있고 결과·repr 에는 없다."""

    base_url: str
    key: str = field(repr=False)
    account_id: str = field(repr=False)
    sender: str = field(default="", repr=False)  # 발신번호(P1 에서 승인 여부를 봄, P2 의 From)
    test_to: str = field(default="", repr=False)  # 시험 문자를 받을 번호(P2 의 To)


@dataclass
class DiagnosticStep:
    id: str  # "P1" … "P4"
    label: str
    ok: bool
    detail: str  # 한 줄. 실패면 짧은 코드로 시작(unauthorized · http_401 · bad_base_url · still_queued · ConnectError …)
    latency_ms: int | None = None  # 이 단계 요청 시간의 합(기다린 시간 빼고)
    skipped: bool = False  # 돌리지 않음(ok 도 False — 화면은 skipped 를 먼저 본다)
    notes: list[str] = field(default_factory=list)  # 접어 보일 기계 출력(구조·조회마다 상태·오류 글)
    code: str = ""  # 기계가 읽는 낱말(모듈 머리 글의 목록). 문장을 뜯어 읽지 말고 이것을 본다
    maybe_sent: bool = False  # P2: 시험 문자가 갔을 수 있다(다시 누르면 두 번째 문자가 간다)
    pending: bool = False  # P3: 접수는 됐고 전송 확인만 아직(실패가 아니다)


class Calls:
    """한 번의 진단에서 보낸 요청 수. 상한에 닿으면 더 보내지 않는다."""

    def __init__(self, limit: int = MAX_REQUESTS) -> None:
        self.limit = limit
        self.sent = 0
        self._post: Exchange | None = None  # 시험 문자를 보낸 요청
        self._settled: bool | None = None  # P2 가 끝나며 정한 값

    @property
    def maybe_sent(self) -> bool:
        """시험 문자가 갔을 수 있는가. P2 가 끝났으면 그 걸음의 `maybe_sent`, 도중에 끊겼으면 요청 본문이 나갔는가."""
        if self._settled is not None:
            return self._settled
        return self._post is not None and self._post.wrote


class _Fail(Exception):
    """걸음 하나의 실패. code 는 기계가 읽는 낱말, detail 은 사람이 읽는 문장."""

    def __init__(self, code: str, detail: str, *, maybe_sent: bool = False, pending: bool = False) -> None:
        super().__init__(code)
        self.code, self.detail, self.maybe_sent, self.pending = code, detail, maybe_sent, pending


def timeouts() -> httpx.Timeout:
    """요청 하나의 시간 제한: 단계마다 15초, 연결만 5초."""
    return httpx.Timeout(TIMEOUT_S, connect=CONNECT_TIMEOUT_S)


def make_client(*, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """진단·제공사 호출에 쓸 클라이언트. 환경(프록시 변수)을 믿지 않고, 리다이렉트를 따르지 않고, 15초(연결 5초) 제한."""
    return httpx.AsyncClient(timeout=timeouts(), trust_env=False, follow_redirects=False, transport=transport)


def encoded(response: httpx.Response) -> bool:
    """압축(Content-Encoding)돼 온 응답인가."""
    return response.headers.get("content-encoding", "").strip().lower() not in ("", "identity")


async def read_body(response: httpx.Response, limit: int) -> bytes | None:
    """흘려 받는 응답의 본문을 limit 바이트까지 읽는다. 넘으면 그만 읽고 None. 압축(Content-Encoding)돼 있으면 읽지도 풀지도
    않고 None — 작은 압축 조각 하나가 수십 MB 로 풀릴 수 있다(요청에 `Accept-Encoding: identity` 를 싣는다)."""
    if encoded(response):
        return None
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        raw += chunk
        if len(raw) > limit:
            return None
    return bytes(raw)


class Exchange:
    """요청 한 번의 경과와 「나갔는가」. 제공사 호출(app.outreach.provider)과 연결 진단이 이 하나를 쓴다.

    `wrote` 는 전송이 요청 본문을 읽기 시작했다는 뜻이다(연결을 마치고 쓰기에 들어갔다) — 도중에 끊겨도 남는다."""

    def __init__(self, sends: bool) -> None:
        self.sends, self.wrote, self.unsent, self.packed = sends, False, False, False
        self.status: int | None = None  # 받은 상태(응답을 받지 못했으면 None)
        self.retry_after: str | None = None
        self.raw: bytes | None = None  # 읽은 본문. 상한 초과·압축·읽다 끊김이면 None
        self.error: str | None = None  # 통신 실패의 종류(MESSAGES 의 열쇠): timeout | network | unknown

    async def run(self, http: httpx.AsyncClient, method: str, url: str, *, headers: dict, params: dict | None = None,
                  content: bytes | None = None, max_bytes: int) -> None:
        """보내고 본문을 max_bytes 까지 읽는다. 예외는 그대로 올린다 — 부른 쪽이 `fail(exc)` 로 종류만 남긴다."""
        async def payload(data: bytes):
            self.wrote = True
            yield data

        request = http.build_request(method, url, headers=headers, params=params, timeout=timeouts(),
                                     content=None if content is None else payload(content))
        response = await http.send(request, stream=True, follow_redirects=False)
        try:
            self.status, self.retry_after = response.status_code, response.headers.get("retry-after")
            self.packed = encoded(response)
            self.raw = await read_body(response, max_bytes)
        finally:
            await response.aclose()

    def fail(self, exc: BaseException) -> None:
        """통신 예외의 종류만 남긴다(글에는 주소·머리글이 있을 수 있다)."""
        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            self.error = "timeout"
        else:
            self.error = "network" if isinstance(exc, httpx.TransportError) else "unknown"
        self.unsent = isinstance(exc, NOT_SENT)

    @property
    def maybe_sent(self) -> bool:
        """보내기였고 갔을 수 있다: 응답 없이 끝났는데 본문은 나갔거나, 받은 상태가 깨끗한 거절(409 밖의 4xx)이 아니다.
        (잘 접수된 2xx 에도 참이다 — 실패를 알릴 때만 본다.)"""
        if not self.sends:
            return False
        if self.status is None:
            return self.wrote and not self.unsent
        return not (400 <= self.status < 500 and self.status != 409)


def http_failure(status: int, vendor: object, *, on_item: bool = False, item: str = "메시지") -> tuple[str, str]:
    """2xx 가 아닌 응답 → (우리 code, 한국어 글). vendor 는 오류 본문의 code — 문서에 있는 코드면 그 글이 먼저다."""
    if isinstance(vendor, str) and vendor in VENDOR:
        return VENDOR[vendor]
    if 300 <= status < 400:
        return "bad_request", "제공사가 다른 주소로 넘기는 응답을 보내 따라가지 않았습니다. 기본 주소를 확인해 주세요."
    if status == 404 and on_item:
        return "bad_request", f"제공사에서 그 {item}를 찾을 수 없습니다."
    if status == 404:
        return "bad_account", "제공사 주소를 찾지 못했습니다. Account ID 와 기본 주소를 확인해 주세요."
    code = {401: "bad_key", 403: "bad_account", 429: "rate_limited"}.get(status)
    if code is None:
        code = "server" if status >= 500 else "bad_request" if 400 <= status < 500 else "unknown"
    return code, MESSAGES[code]


def base_url_problem(base_url: object) -> str | None:
    """주소가 안 되는 까닭(한국어) 또는 None. 꼴만 본다(이름 풀이 없음). 호스트 목록으로 고정하지 않는다.

    주소는 scheme·호스트·포트뿐이어야 한다(경로는 없거나 「/」). 질의(?)·조각(#)·경로가 있으면 뒤에 붙이는
    `/v1/accounts/…` 가 그 속으로 들어가 다른 곳을 부르게 되므로 거절한다. 빈칸·%·역빗금·「;,&=」도 거절(호스트 이름이 달라진다).
    연결 진단과 제공사 호출(app.outreach.provider)이 이 함수 하나를 쓴다."""
    if not isinstance(base_url, str) or not base_url.strip():
        return "주소가 비어 있습니다."
    if "@" in base_url:
        return "주소에 사용자 정보(@)를 넣을 수 없습니다."
    if _BAD_URL_CHAR.search(base_url):
        return "주소에 빈칸이나 % · \\ · ; · , · & · = 를 넣을 수 없습니다."
    try:
        url = httpx.URL(base_url)
    except httpx.InvalidURL:
        return "주소 꼴이 틀렸습니다."
    if url.scheme != "https" or not url.host:
        return "주소는 https:// 로 시작해야 합니다."
    if "?" in base_url or "#" in base_url or url.path not in ("", "/"):
        return "주소에는 경로·질의(?)·조각(#)을 넣을 수 없습니다(https://호스트 까지만)."
    if _info_url_problem(base_url) is not None:
        return "localhost 나 내부망(사설·루프백·링크로컬) 주소는 쓸 수 없습니다."
    return None


def _preflight(conn: DiagnosticConn, http: object) -> tuple[str, str] | None:
    """요청 전에 막을 까닭 (code, 문장) 또는 None."""
    try:
        if getattr(http, "trust_env", True) is not False:
            return "untrusted_client", UNTRUSTED_CLIENT
        problem = base_url_problem(conn.base_url)
        if problem:
            return "bad_base_url", problem
        for value, code, name in ((conn.key, "bad_key", "API 키"), (conn.account_id, "bad_account", "Account ID")):
            if not isinstance(value, str) or not value.strip():
                return code, f"{name}가 비어 있습니다."
            if not value.isascii() or not value.isprintable():
                return code, f"{name}에 쓸 수 없는 글자가 있습니다."
            if len(value) < MIN_SECRET:
                return code, f"{name}가 너무 짧습니다({MIN_SECRET}자 이상)."
        return None
    except Exception:  # noqa: BLE001 — 진단은 던지지 않는다
        return "unknown", "연결 값을 읽지 못했습니다."


# 이름 풀이 뒤 검사 — app/info/generic.py 의 _resolved·_public 과 같은 규칙(그쪽은 비공개 이름이고 정보 API 글·전역
# RESOLVE 에 묶여 있어 가져오지 않고 옮겨 씀). 그쪽처럼 풀린 IP 로 붙지는(pin) 않는다.
def _ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in _EMBEDDING_V6):
        return False
    return ip.is_global and not ip.is_multicast


async def resolve_problem(conn: DiagnosticConn, resolve: Resolver | None) -> str | None:
    """호스트 이름을 풀어 모든 IP 가 공인일 때만 None. IP 꼴 호스트는 base_url_problem 이 이미 봤다.
    conn 은 `.base_url` 만 읽는다(제공사 호출의 ProviderConn 도 받는다)."""
    try:
        url = httpx.URL(conn.base_url)
        if _ip_literal(url.host) is not None:
            return None
        fn = resolve if resolve is not None else RESOLVE
        addresses = await asyncio.wait_for(asyncio.to_thread(fn, url.host, url.port or 443), RESOLVE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — OSError·시간 초과·무엇이든: 글은 남기지 않는다
        return RESOLVE_FAILED
    if not isinstance(addresses, list) or not addresses or not all(_public(str(a)) for a in addresses):
        return RESOLVED_INSIDE
    return None


_resolve_problem = resolve_problem  # 예전 이름


async def _check(conn: DiagnosticConn, http: object, resolve: Resolver | None) -> tuple[str, str] | None:
    """요청 전 검사 전부: 클라이언트·주소 꼴·키 → 이름 풀이. 걸리면 (code, 문장)."""
    found = _preflight(conn, http)
    if found is not None:
        return found
    problem = await _resolve_problem(conn, resolve)
    if problem is None:
        return None
    return ("resolve_failed" if problem == RESOLVE_FAILED else "bad_base_url"), problem


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def segment(value: object) -> str:
    """경로 한 칸. 모두 %인코딩하고, 「.」·「..」 은 %2E 로(위로 올라가지 않게). 제공사 호출도 이것을 쓴다."""
    q = quote(str(value), safe="")
    return q.replace(".", "%2E") if q and set(q) <= {"."} else q


_segment = segment  # 예전 이름


def _number_patterns(number: str) -> list[re.Pattern[str]]:
    """번호 하나를 국내 꼴·+82 꼴로, 사이에 구분(하이픈·점·빈칸·괄호·+·%20·%2D·%2E)이 있어도 찾는 정규식들."""
    d = _digits(number)
    if not d:
        return []
    forms = {d}
    if d.startswith("82"):
        forms.add("0" + d[2:])
    elif d.startswith("0"):
        forms.add("82" + d[1:])
    return [re.compile(r"(?:\+|%2B)?" + _SEP.join(f), re.IGNORECASE) for f in forms]


def scrub(text: object, *, secrets: list[str], numbers: list[str], limit: int = 200) -> str:
    """키·Account ID·번호(redact.scrub), 알려 준 번호·긴 숫자 묶음·긴 토큰을 지우고 한 줄로 자른다."""
    plus_forms = [quote_plus(s) for s in secrets if isinstance(s, str) and " " in s]  # 빈칸이 + 로 바뀐 꼴
    out = redact.scrub(str(text), [*secrets, *plus_forms])
    for rx in (rx for n in numbers if isinstance(n, str) and n for rx in _number_patterns(n)):
        out = rx.sub("…", out)
    for rx in (_DIGITS_RE, _TOKEN_RE):
        out = rx.sub("…", out)
    return re.sub(r"\s+", " ", out).strip()[:limit]


def structure(obj: object, depth: int = 0) -> str:
    """dict/list 의 칸 이름만 펼쳐 한 줄로 보인다(값은 빼고)."""
    if depth > 5:
        return "…"
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{k}: {structure(v, depth + 1)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return f"[{len(obj)}× {structure(obj[0], depth + 1)}]" if obj else "[]"
    return type(obj).__name__


class _Run:
    """단계 하나의 요청·기록. 글은 모두 지워서 남긴다."""

    def __init__(self, conn: DiagnosticConn, http: httpx.AsyncClient, calls: Calls) -> None:
        redact.add_secrets(conn.key, conn.account_id)  # httpx 요청 줄(주소에 Account ID)이 남기 전에 로그 거르개에 올린다
        self.conn, self.http, self.calls = conn, http, calls
        self.base = f"{conn.base_url.rstrip('/')}/v1/accounts/{_segment(conn.account_id)}"
        self.ms = 0
        self.notes: list[str] = []
        self.message_id: str | None = None

    def clean(self, text: object, limit: int = 200) -> str:
        return scrub(text, secrets=[self.conn.key, self.conn.account_id],
                     numbers=[self.conn.sender, self.conn.test_to], limit=limit)

    def note(self, text: object) -> None:
        self.notes.append(self.clean(text, 500))

    async def call(self, method: str, path: str, label: str, *, params: dict | None = None, payload: dict | None = None,
                   on_item: bool = False) -> dict:
        """요청 한 번 → 2xx 의 JSON 객체. 그 밖은 _Fail(code, 문장, maybe_sent). 기계 글(상태·크기·제공사 말)은 notes 에."""
        if self.calls.sent >= self.calls.limit:
            raise _Fail("request_limit", OUT_OF_REQUESTS)
        self.calls.sent += 1
        exchange = Exchange(sends=method == "POST")
        if exchange.sends:
            self.calls._post, self.calls._settled = exchange, None
        headers = {"Authorization": f"Bearer {self.conn.key}", "Accept": "application/json", "Accept-Encoding": "identity"}
        content = None
        if payload is not None:
            content = json.dumps(payload).encode()
            headers |= {"Content-Type": "application/json", "Content-Length": str(len(content))}
        start, kind = time.perf_counter(), None
        try:
            async with asyncio.timeout(TIMEOUT_S):  # 보내기 + 본문 읽기 전체의 상한(읽기 제한은 조각마다 다시 센다)
                await exchange.run(self.http, method, self.base + path, headers=headers, params=params, content=content,
                                   max_bytes=MAX_BODY_BYTES)
        except Exception as e:  # noqa: BLE001 — 통신 예외의 글에는 주소(Account ID)·키가 있을 수 있어 종류만 남긴다
            exchange.fail(e)
            kind = type(e).__name__
        ms = int((time.perf_counter() - start) * 1000)
        self.ms += ms
        status, raw = exchange.status, exchange.raw
        size = "읽지 않음(상한 초과·압축·끊김)" if raw is None else f"{len(raw)}B"
        seen = f"HTTP {status} · {ms}ms · {size}" if status is not None else f"응답 없음 · {ms}ms"
        self.note(f"[{self.calls.sent}] {method} {label}: {seen}" + (f" · {kind}" if kind else ""))
        if status is None:
            raise _Fail(exchange.error, MESSAGES[exchange.error], maybe_sent=exchange.maybe_sent)
        try:
            data = json.loads(raw) if raw is not None and exchange.error is None else None
        except (ValueError, RecursionError):
            data = None
        if not 200 <= status < 300:  # 본문을 읽다 끊겼어도 받은 상태로 가른다
            vendor, error = (data.get("code"), data.get("error")) if isinstance(data, dict) else (None, None)
            self.note(f"오류 code={vendor} · error={error}")
            if status == 429:
                self.note(f"Retry-After={exchange.retry_after}")
            code, message = http_failure(status, vendor, on_item=on_item)
            raise _Fail(code, message, maybe_sent=exchange.maybe_sent)
        if exchange.error is not None:  # 2xx 를 받고 본문을 읽다 끊겼다
            raise _Fail(exchange.error, MESSAGES[exchange.error], maybe_sent=exchange.maybe_sent)
        if not isinstance(data, dict):  # 읽지 않았거나(상한·압축) JSON 객체가 아니다
            raise _Fail("unknown", MESSAGES["unknown"], maybe_sent=exchange.maybe_sent)
        return data

    def result(self, step_id: str, detail: str) -> DiagnosticStep:
        return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=True, detail=self.clean(detail),
                              latency_ms=self.ms if self.calls.sent else None, notes=self.notes, code="ok")

    def failed(self, step_id: str, exc: Exception) -> DiagnosticStep:
        if isinstance(exc, _Fail):
            code, detail, maybe, pending = exc.code, exc.detail, exc.maybe_sent, exc.pending
        else:  # 우리 쪽 오류 — 종류는 접어 보이는 줄에만
            self.note(f"예외: {type(exc).__name__}")
            code, detail, maybe, pending = "unknown", MESSAGES["unknown"], step_id == "P2" and self.calls.maybe_sent, False
        text = self.clean(detail) + (f" {MAYBE_SENT}" if maybe else "")
        return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=False, detail=text, notes=self.notes, code=code,
                              latency_ms=self.ms if self.calls.sent else None, maybe_sent=maybe, pending=pending)


def _plain(step_id: str, code: str, detail: str, *, skipped: bool = False) -> DiagnosticStep:
    notes = [UNTRUSTED_CLIENT_NOTE] if code == "untrusted_client" else []
    return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=False, detail=detail, skipped=skipped, code=code, notes=notes)


async def _guarded(step_id: str, conn: DiagnosticConn, http: httpx.AsyncClient, calls: Calls,
                   body: Callable[[_Run], Awaitable[DiagnosticStep]], resolve: Resolver | None,
                   prechecked: bool) -> tuple[DiagnosticStep, _Run | None]:
    """요청 전 검사 → 단계 몸통. 어떤 예외도 밖으로 내보내지 않는다. run_checks 가 이미 검사했으면 건너뜀."""
    problem = None if prechecked else await _check(conn, http, resolve)
    if problem:
        return _plain(step_id, *problem), None
    try:
        run = _Run(conn, http, calls)
    except Exception:  # noqa: BLE001
        return _plain(step_id, "unknown", "연결 값을 읽지 못했습니다."), None
    try:
        return await body(run), run
    except Exception as e:  # noqa: BLE001
        return run.failed(step_id, e), run


async def check_senders(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls,
                        resolve: Resolver | None = None, _prechecked: bool = False) -> DiagnosticStep:
    """P1: 인증 + 발신번호 목록. 고른 발신번호(`conn.sender`)가 승인됐는지도 본다."""

    async def body(run: _Run) -> DiagnosticStep:
        data = await run.call("GET", "/sender-numbers", "sender-numbers")
        run.note(f"구조: {structure(data)}")
        rows = data.get("senderNumbers")
        if not isinstance(rows, list):
            run.note("senderNumbers 칸이 목록이 아님")
            raise _Fail("unknown", MESSAGES["unknown"])
        mine, counts = None, Counter()
        for i, row in enumerate(rows, 1):
            row = row if isinstance(row, dict) else {}
            same = bool(conn.sender) and _digits(row.get("number")) == _digits(conn.sender)
            mine = row.get("status") if same else mine
            counts[_SENDER_WORDS.get(row.get("status"), "그 밖")] += 1
            if i <= 20:
                run.note(f"#{i} status={row.get('status')}{' (= 고른 발신번호)' if same else ''}")
        if not conn.sender:
            ours = "발신번호는 아직 고르지 않음"
        elif mine is None:
            ours = "고른 발신번호가 목록에 없음"
        else:
            ours = {"approved": "고른 발신번호는 승인됨", "pending": "고른 발신번호는 심사 중"}.get(mine, "고른 발신번호는 아직 쓸 수 없음")
        tally = " · ".join(f"{word} {counts[word]}" for word in ("승인", "심사 중", "그 밖") if counts[word])
        return run.result("P1", f"인증됨 · 발신번호 {len(rows)}개" + (f"({tally})" if tally else "") + f" · {ours}")

    return (await _guarded("P1", conn, http, calls, body, resolve, _prechecked))[0]


async def check_send_sms(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: object = False,
                         calls: Calls, resolve: Resolver | None = None,
                         _prechecked: bool = False) -> tuple[DiagnosticStep, str | None]:
    """P2: `conn.test_to` 로 실제 문자 1건. `send_test_sms is True` 일 때만 보낸다. (결과, 제공사 messageId|None).
    실패한 결과의 `maybe_sent` 가 참이면 문자가 갔을 수 있다(모듈 머리 글)."""
    if send_test_sms is not True:
        return _plain("P2", "skipped_no_send", NO_SEND, skipped=True), None
    if not conn.sender or not conn.test_to:
        return _plain("P2", "skipped_no_numbers", NO_NUMBERS, skipped=True), None
    if calls.limit - calls.sent < 2:  # POST + 상태 조회 1번
        return _plain("P2", "request_limit", NO_ROOM, skipped=True), None

    async def body(run: _Run) -> DiagnosticStep:
        payload = {"To": conn.test_to, "From": conn.sender, "Body": SMS_TEXT, "Type": "sms",
                   "IdempotencyKey": f"chronos-probe-{uuid.uuid4().hex}"}
        data = await run.call("POST", "/messages", "messages", payload=payload)
        run.note(f"구조: {structure(data)}")
        mid = data.get("messageId")
        run.note(f"status={data.get('status')} · failureCode={data.get('failureCode')} · "
                 f"messageId {'받음' if isinstance(mid, str) and mid else '없음'}")
        if not isinstance(mid, str) or not mid:
            raise _Fail("unknown", MESSAGES["unknown"], maybe_sent=True)  # 2xx 인데 id 가 없다 — 접수됐을 수 있다
        run.message_id = mid
        return run.result("P2", ACCEPTED)

    step, run = await _guarded("P2", conn, http, calls, body, resolve, _prechecked)
    calls._settled = step.maybe_sent
    return step, (run.message_id if run is not None and step.ok else None)


async def check_message_status(conn: DiagnosticConn, http: httpx.AsyncClient, message_id: str | None, *,
                               sleep: Sleep = asyncio.sleep, calls: Calls, resolve: Resolver | None = None,
                               _prechecked: bool = False) -> DiagnosticStep:
    """P3: 보낸 문자의 상태를 5초 간격 최대 4번. sent·failed 가 되면 멈춘다. sent 면 성공, failed 면 실패(`delivery_failed`).
    끝까지 queued 면 실패가 아니라 `pending`(code `still_queued`) — 접수는 됐고 전송 확인만 아직이다."""
    if not message_id:
        return _plain("P3", "skipped_no_message", NO_MESSAGE, skipped=True)

    async def body(run: _Run) -> DiagnosticStep:
        seen: list[str] = []
        failure = None
        for i in range(POLL_TIMES):
            if i:
                await sleep(POLL_GAP_S)
            data = await run.call("GET", f"/messages/{_segment(message_id)}", "messages/{id}", on_item=True)
            status, failure = str(data.get("status")), data.get("failureCode")
            run.note(f"{i + 1}/{POLL_TIMES} status={status} · failureCode={failure}")
            if not seen or seen[-1] != status:
                seen.append(status)
            if status in FINAL:
                break
        path = " → ".join(_STATUS_WORDS.get(word, "알 수 없는 상태") for word in seen)
        if seen[-1] == "sent":
            return run.result("P3", path)
        if seen[-1] == "failed":
            why = FAILURES.get(failure) if isinstance(failure, str) else None
            raise _Fail("delivery_failed", f"{path} — {why or FAILURES['unknown']}")
        if seen[-1] == "queued":
            raise _Fail("still_queued", STILL_QUEUED, pending=True)
        raise _Fail("unknown", MESSAGES["unknown"])

    return (await _guarded("P3", conn, http, calls, body, resolve, _prechecked))[0]


async def check_received(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls,
                         resolve: Resolver | None = None, _prechecked: bool = False) -> DiagnosticStep:
    """P4: 받은 문자 목록 — 구조와 건수만(본문·번호는 남기지 않음)."""

    async def body(run: _Run) -> DiagnosticStep:
        data = await run.call("GET", "/messages", "messages?status=received",
                              params={"status": "received", "pageSize": "20"})
        run.note(f"구조: {structure(data)}")
        rows = data.get("data")
        if not isinstance(rows, list):
            run.note("data 칸이 목록이 아님")
            raise _Fail("unknown", MESSAGES["unknown"])
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        kinds = Counter(f"{x.get('direction')}/{x.get('status')}" for x in rows if isinstance(x, dict))
        run.note(f"meta.total={meta.get('total')} · " + (" · ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "비어 있음"))
        return run.result("P4", f"받은 문자 {len(rows)}건")

    return (await _guarded("P4", conn, http, calls, body, resolve, _prechecked))[0]


def _step_numbers(steps: Iterable[object]) -> list[int]:
    """1~4 또는 "P1"~"P4"(대소문자 무관). 모르는 값은 버린다."""
    picked = {str(s).strip().upper().removeprefix("P") for s in steps}
    return sorted(int(t) for t in picked if t in ("1", "2", "3", "4"))


async def run_checks(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: object = False,
                     steps: Iterable[int | str] = (1, 2, 3, 4), sleep: Sleep = asyncio.sleep,
                     calls: Calls | None = None, resolve: Resolver | None = None) -> list[DiagnosticStep]:
    """부르는 쪽이 쓰는 단 하나의 입구. 고른 단계를 차례로, 요청 상한을 함께 쓴다. 언제나 P1~P4 네 줄을 돌려준다 —
    고르지 않은 단계는 `skipped=True`(code `skipped_not_requested`).

    기본(연결 테스트)은 문자를 보내지 않는다 — P2·P3 은 `skipped=True`(ok 도 False)로 돌아온다.
    요청 전 검사(클라이언트·주소·키·이름 풀이)에 걸리면 요청 없이 고른 단계 모두 실패. `resolve` 는 시험용(기본 RESOLVE).
    도중에 끊겨도(취소) 시험 문자가 갔을 수 있는지는 넘겨 준 `calls.maybe_sent` 에 남는다.
    """
    numbers = _step_numbers(steps)
    problem = await _check(conn, http, resolve)
    calls = calls if calls is not None else Calls()
    out: list[DiagnosticStep] = []
    mid: str | None = None
    for n in (1, 2, 3, 4):
        if n not in numbers:
            out.append(_plain(f"P{n}", "skipped_not_requested", NOT_REQUESTED, skipped=True))
        elif problem:
            out.append(_plain(f"P{n}", *problem))
        elif n == 1:
            out.append(await check_senders(conn, http, calls=calls, _prechecked=True))
        elif n == 2:
            result, mid = await check_send_sms(conn, http, send_test_sms=send_test_sms, calls=calls, _prechecked=True)
            out.append(result)
        elif n == 3:
            out.append(await check_message_status(conn, http, mid, sleep=sleep, calls=calls, _prechecked=True))
        else:
            out.append(await check_received(conn, http, calls=calls, _prechecked=True))
    return out
