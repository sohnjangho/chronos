"""한국AI통신 REST 연결 진단(계획 4 Task 59, 0단계 P1~P4). 설정 화면의 「연결 진단」과 실측 스크립트가 같이 쓴다.

- 부르는 쪽은 `run_checks` 만 쓴다(요청 상한 8번을 단계끼리 나눠 쓰도록). 단계 함수(`check_*`)는 공유 상한
  `calls: Calls` 를 꼭 받는다. 클라이언트는 `make_client()` 로 만든다(trust_env=False·리다이렉트 안 따름·15초).
- 함수는 찍지 않고, 환경 변수를 읽지 않고, 끝내지 않는다. 예외도 던지지 않는다(실패는 `ok=False`, 예외는 종류만).
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
  시험 문자가 2xx 로 접수됐는데 본문을 읽지 못했으면 그냥 실패가 아니라 `MAYBE_SENT`(보냈는지 알 수 없음)로 알린다. 단계를 돌리면 키·Account ID 가 로그 거르개에 오른다(redact.add_secrets). 경로에 넣는 Account ID·
  messageId 는 %인코딩한다. DB 에 쓰지 않는다.
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
UNTRUSTED_CLIENT = "untrusted_client · 클라이언트는 trust_env=False 로 만들어야 합니다 — make_client() 를 쓰세요"
MAYBE_SENT = "보냈는지 알 수 없음 — 문자가 갔을 수도 안 갔을 수도 있습니다. 다시 누르면 두 번째 문자가 갈 수 있습니다"
_SEP = r"(?:[\s.\-()+]|%20|%2D|%2E|%28|%29|%2B)*"  # 번호 사이 구분(%인코딩 꼴 포함)
_DIGITS_RE = re.compile(r"\d{8,}")  # 7자리 넘는(8자리 이상) 숫자 묶음
_TOKEN_RE = re.compile(r"[A-Za-z0-9%+/=_\-]{40,}")
_BAD_URL_CHAR = re.compile(r"[\s%\\;,&=]")  # 기본 주소에 올 수 없는 글자

RESOLVE_FAILED = "resolve_failed · 주소의 호스트 이름을 풀지 못했습니다(이름 풀이 실패 또는 시간 초과)"
RESOLVED_INSIDE = "bad_base_url · 호스트가 내부망 IP 로 풀리거나 공인 IP 가 없어 부르지 않았습니다"
NO_ROOM = "request_limit · 남은 요청이 2번보다 적어 보내지 않음(보낸 뒤 상태를 볼 수 없음)"
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


class Calls:
    """한 번의 진단에서 보낸 요청 수. 상한에 닿으면 더 보내지 않는다."""

    def __init__(self, limit: int = MAX_REQUESTS) -> None:
        self.limit = limit
        self.sent = 0


class _Fail(Exception):
    pass


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


def _preflight(conn: DiagnosticConn, http: object) -> str | None:
    """요청 전에 막을 까닭(실패 detail) 또는 None."""
    try:
        if getattr(http, "trust_env", True) is not False:
            return UNTRUSTED_CLIENT
        problem = base_url_problem(conn.base_url)
        if problem:
            return f"bad_base_url · {problem}"
        for value, name in ((conn.key, "키"), (conn.account_id, "Account ID")):
            if not isinstance(value, str) or not value.strip():
                return f"bad_connection · {name}가 비어 있습니다"
            if not value.isascii() or not value.isprintable():
                return f"bad_connection · {name}에 쓸 수 없는 글자가 있습니다"
            if len(value) < MIN_SECRET:
                return f"bad_connection · {name}가 너무 짧습니다({MIN_SECRET}자 이상)"
        return None
    except Exception as e:  # noqa: BLE001 — 진단은 던지지 않는다
        return type(e).__name__


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


async def _check(conn: DiagnosticConn, http: object, resolve: Resolver | None) -> str | None:
    """요청 전 검사 전부: 클라이언트·주소 꼴·키 → 이름 풀이."""
    return _preflight(conn, http) or await _resolve_problem(conn, resolve)


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
        self.posted = False
        self.message_id: str | None = None

    def clean(self, text: object, limit: int = 200) -> str:
        return scrub(text, secrets=[self.conn.key, self.conn.account_id],
                     numbers=[self.conn.sender, self.conn.test_to], limit=limit)

    def note(self, text: object) -> None:
        self.notes.append(self.clean(text, 500))

    async def call(self, method: str, path: str, label: str, **kw: object) -> httpx.Response:
        if self.calls.sent >= self.calls.limit:
            raise _Fail("request_limit")
        self.calls.sent += 1
        self.posted = self.posted or method == "POST"
        start = time.perf_counter()
        request = self.http.build_request(method, self.base + path, timeout=timeouts(), headers={
            "Authorization": f"Bearer {self.conn.key}", "Accept": "application/json", "Accept-Encoding": "identity"}, **kw)
        try:
            async with asyncio.timeout(TIMEOUT_S):  # 보내기 + 본문 읽기 전체의 상한(읽기 제한은 조각마다 다시 센다)
                response = await self.http.send(request, stream=True, follow_redirects=False)
                try:
                    raw = await read_body(response, MAX_BODY_BYTES)
                finally:
                    await response.aclose()
        except TimeoutError:
            raise httpx.ReadTimeout("요청 하나의 시간 제한을 넘겼습니다") from None
        ms = int((time.perf_counter() - start) * 1000)
        self.ms += ms
        size = "읽지 않음(상한 초과 또는 압축)" if raw is None else f"{len(raw)}B"
        self.note(f"[{self.calls.sent}] {method} {label}: HTTP {response.status_code} · {ms}ms · {size}")
        if raw is None and response.is_success:
            if method == "POST":  # 접수됐을 수 있다 — 설정 길(notify_settings)이 이 글로 sent_unknown 을 정한다
                raise _Fail(f"body_unreadable · {MAYBE_SENT}")
            raise _Fail("body_unreadable · 응답 본문이 너무 크거나 압축돼 있어 읽지 않았습니다")
        retry_after = response.headers.get("retry-after")
        return httpx.Response(response.status_code, content=raw or b"",
                              headers={"retry-after": retry_after} if retry_after is not None else None)

    def expect(self, r: httpx.Response, *ok: int) -> dict:
        """기대한 상태면 JSON(dict)을, 아니면 오류 본문의 `code`(없으면 http_<상태>)로 실패."""
        if r.status_code in ok:
            try:
                data = r.json()
            except ValueError:
                raise _Fail("not_json") from None
            if not isinstance(data, dict):
                raise _Fail("not_object")
            return data
        code, error = None, None
        try:
            body = r.json()
            if isinstance(body, dict):
                code, error = body.get("code"), body.get("error")
        except ValueError:
            pass
        self.note(f"오류 code={code} · error={error}")
        if r.status_code == 429:
            self.note(f"Retry-After={r.headers.get('retry-after')}")
        raise _Fail(code if isinstance(code, str) and code else f"http_{r.status_code}")

    def result(self, step_id: str, ok: bool, detail: str) -> DiagnosticStep:
        return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=ok, detail=self.clean(detail),
                              latency_ms=self.ms if self.calls.sent else None, notes=self.notes)

    def failed(self, step_id: str, exc: Exception) -> DiagnosticStep:
        # 통신 예외의 글에는 주소(Account ID)·키가 있을 수 있어 종류만 남긴다.
        if isinstance(exc, _Fail):
            return self.result(step_id, False, str(exc))
        detail = type(exc).__name__
        unsent = (httpx.ConnectError, httpx.ConnectTimeout, httpx.UnsupportedProtocol)
        if self.posted and isinstance(exc, httpx.TransportError) and not isinstance(exc, unsent):
            return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=False, detail=f"{detail} · {MAYBE_SENT}",
                                  latency_ms=self.ms or None, notes=self.notes)
        return self.result(step_id, False, detail)


def _plain(step_id: str, detail: str, *, skipped: bool = False) -> DiagnosticStep:
    return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=False, detail=detail, skipped=skipped)


async def _guarded(step_id: str, conn: DiagnosticConn, http: httpx.AsyncClient, calls: Calls,
                   body: Callable[[_Run], Awaitable[DiagnosticStep]], resolve: Resolver | None,
                   prechecked: bool) -> tuple[DiagnosticStep, _Run | None]:
    """요청 전 검사 → 단계 몸통. 어떤 예외도 밖으로 내보내지 않는다. run_checks 가 이미 검사했으면 건너뜀."""
    problem = None if prechecked else await _check(conn, http, resolve)
    if problem:
        return _plain(step_id, problem), None
    try:
        run = _Run(conn, http, calls)
    except Exception as e:  # noqa: BLE001
        return _plain(step_id, type(e).__name__), None
    try:
        return await body(run), run
    except Exception as e:  # noqa: BLE001
        return run.failed(step_id, e), run


async def check_senders(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls,
                        resolve: Resolver | None = None, _prechecked: bool = False) -> DiagnosticStep:
    """P1: 인증 + 발신번호 목록. 고른 발신번호(`conn.sender`)가 승인됐는지도 본다."""

    async def body(run: _Run) -> DiagnosticStep:
        data = run.expect(await run.call("GET", "/sender-numbers", "sender-numbers"), 200)
        run.note(f"구조: {structure(data)}")
        rows = data.get("senderNumbers")
        if not isinstance(rows, list):
            raise _Fail("no_senderNumbers")
        mine = None
        for i, row in enumerate(rows[:20], 1):
            row = row if isinstance(row, dict) else {}
            same = bool(conn.sender) and _digits(row.get("number")) == _digits(conn.sender)
            mine = row.get("status") if same else mine
            run.note(f"#{i} status={row.get('status')}{' (= 고른 발신번호)' if same else ''}")
        counts = Counter(str(r.get("status")) for r in rows if isinstance(r, dict))
        if not conn.sender:
            ours = "발신번호를 고르지 않음"
        elif mine is None:
            ours = "고른 발신번호가 목록에 없음"
        else:
            ours = "고른 발신번호 승인됨" if mine == "approved" else f"고른 발신번호 {mine}"
        tally = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        return run.result("P1", True, f"발신번호 {len(rows)}개 · {tally} · {ours}" if tally else f"발신번호 0개 · {ours}")

    return (await _guarded("P1", conn, http, calls, body, resolve, _prechecked))[0]


async def check_send_sms(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: object = False,
                         calls: Calls, resolve: Resolver | None = None,
                         _prechecked: bool = False) -> tuple[DiagnosticStep, str | None]:
    """P2: `conn.test_to` 로 실제 문자 1건. `send_test_sms is True` 일 때만 보낸다. (결과, 제공사 messageId|None)."""
    if send_test_sms is not True:
        return _plain("P2", "보내지 않음 — send_test_sms=True 일 때만 보냄", skipped=True), None
    if not conn.sender or not conn.test_to:
        return _plain("P2", "발신번호와 받을 번호가 모두 있어야 보냄", skipped=True), None
    if calls.limit - calls.sent < 2:  # POST + 상태 조회 1번
        return _plain("P2", NO_ROOM, skipped=True), None

    async def body(run: _Run) -> DiagnosticStep:
        payload = {"To": conn.test_to, "From": conn.sender, "Body": SMS_TEXT, "Type": "sms",
                   "IdempotencyKey": f"chronos-probe-{uuid.uuid4().hex}"}
        r = await run.call("POST", "/messages", "messages", json=payload)
        data = run.expect(r, 200, 201)
        run.note(f"구조: {structure(data)}")
        mid = data.get("messageId")
        if not isinstance(mid, str) or not mid:
            raise _Fail("no_messageId")
        run.message_id = mid
        return run.result("P2", True, f"HTTP {r.status_code} · status={data.get('status')} · "
                                      f"failureCode={data.get('failureCode')} · messageId 받음")

    step, run = await _guarded("P2", conn, http, calls, body, resolve, _prechecked)
    return step, (run.message_id if run is not None and step.ok else None)


async def check_message_status(conn: DiagnosticConn, http: httpx.AsyncClient, message_id: str | None, *,
                               sleep: Sleep = asyncio.sleep, calls: Calls, resolve: Resolver | None = None,
                               _prechecked: bool = False) -> DiagnosticStep:
    """P3: 보낸 문자의 상태를 5초 간격 최대 4번. sent·failed 가 되면 멈춘다. 끝까지 queued 면 실패(still_queued)."""
    if not message_id:
        return _plain("P3", "보낸 시험 문자가 없음(P2 를 함께 돌려야 함)", skipped=True)

    async def body(run: _Run) -> DiagnosticStep:
        seen: list[str] = []
        failure = None
        for i in range(POLL_TIMES):
            if i:
                await sleep(POLL_GAP_S)
            data = run.expect(await run.call("GET", f"/messages/{_segment(message_id)}", "messages/{id}"), 200)
            status, failure = str(data.get("status")), data.get("failureCode")
            run.note(f"{i + 1}/{POLL_TIMES} status={status} · failureCode={failure}")
            if not seen or seen[-1] != status:
                seen.append(status)
            if status in FINAL:
                break
        path = " → ".join(seen)
        if seen[-1] not in FINAL:
            raise _Fail(f"still_{seen[-1]} · {path}")
        return run.result("P3", True, path + (f" · failureCode={failure}" if failure else ""))

    return (await _guarded("P3", conn, http, calls, body, resolve, _prechecked))[0]


async def check_received(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls,
                         resolve: Resolver | None = None, _prechecked: bool = False) -> DiagnosticStep:
    """P4: 받은 문자 목록 — 구조와 건수만(본문·번호는 남기지 않음)."""

    async def body(run: _Run) -> DiagnosticStep:
        r = await run.call("GET", "/messages", "messages?status=received",
                           params={"status": "received", "pageSize": "20"})
        data = run.expect(r, 200)
        run.note(f"구조: {structure(data)}")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise _Fail("no_data")
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        kinds = Counter(f"{x.get('direction')}/{x.get('status')}" for x in rows if isinstance(x, dict))
        return run.result("P4", True, f"{len(rows)}건 · meta.total={meta.get('total')} · "
                          + (" · ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "비어 있음"))

    return (await _guarded("P4", conn, http, calls, body, resolve, _prechecked))[0]


def _step_numbers(steps: Iterable[object]) -> list[int]:
    """1~4 또는 "P1"~"P4"(대소문자 무관). 모르는 값은 버린다."""
    picked = {str(s).strip().upper().removeprefix("P") for s in steps}
    return sorted(int(t) for t in picked if t in ("1", "2", "3", "4"))


async def run_checks(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: object = False,
                     steps: Iterable[int | str] = (1, 2, 3, 4), sleep: Sleep = asyncio.sleep,
                     calls: Calls | None = None, resolve: Resolver | None = None) -> list[DiagnosticStep]:
    """부르는 쪽이 쓰는 단 하나의 입구. 고른 단계를 차례로, 요청 상한을 함께 쓴다.

    기본(연결 테스트)은 문자를 보내지 않는다 — P2·P3 은 `skipped=True`(ok 도 False)로 돌아온다.
    요청 전 검사(클라이언트·주소·키·이름 풀이)에 걸리면 요청 없이 고른 단계 모두 실패. `resolve` 는 시험용(기본 RESOLVE).
    """
    numbers = _step_numbers(steps)
    problem = await _check(conn, http, resolve)
    if problem:
        return [_plain(f"P{n}", problem) for n in numbers]
    calls = calls if calls is not None else Calls()
    out: list[DiagnosticStep] = []
    mid: str | None = None
    if 1 in numbers:
        out.append(await check_senders(conn, http, calls=calls, _prechecked=True))
    if 2 in numbers:
        result, mid = await check_send_sms(conn, http, send_test_sms=send_test_sms, calls=calls, _prechecked=True)
        out.append(result)
    if 3 in numbers:
        out.append(await check_message_status(conn, http, mid, sleep=sleep, calls=calls, _prechecked=True))
    if 4 in numbers:
        out.append(await check_received(conn, http, calls=calls, _prechecked=True))
    return out
