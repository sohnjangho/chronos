"""한국AI통신 REST 시험용 가짜(Task 69). conftest 의 pytest_plugins 로 올린다. 실제 제공사·DNS 를 쓰지 않는다.

- KatMock — `httpx.MockTransport`. 공개 문서(docs.koreaaitel.com, 2026-11-23)의 경로·칸 이름으로 답하는 가짜 서버.
  `KatClient(conn, transport=KatMock())` 로 끼운다. 값은 모두 가상이다.
- FakeProvider — `Provider` 를 메모리로 구현한 것. fixture `fake_provider` 가 `provider.client_for` 를 이것으로 바꾼다
  (그래서 쓰는 쪽은 `from app.outreach import provider` 뒤 `provider.client_for(row)` 로 불러야 한다).
- autouse `no_provider_dns` — `provider.RESOLVE` 와 `diagnostics.RESOLVE` 를 공인 IP 하나로 답하는 가짜로 바꾼다(시험이 DNS 를
  쓰지 않게). 돌려주는 값은 물은 호스트 목록.
- **소켓 막이** — 이 파일이 올라올 때 한 번 걸리고 실행이 끝날 때까지 그대로다(**모든 backend 시험**, 시험 몸통 밖 — 모듈을
  불러올 때·모듈/세션 범위 고정물 — 도 같다). `socket.socket.connect`·`connect_ex`·`socket.getaddrinfo` 가 내 컴퓨터
  (127.0.0.0/8·::1·localhost) 밖을 향하면 `RealProviderCall` 이 난다 — httpx·urllib·requests·aiohttp(음성 SDK)·asyncio 스트림·
  websockets·httpcore 어느 것으로 나가든 같다. **푸는 표시는 없다.** 내 컴퓨터 안(시험이 띄운 서버)은 표시 없이 열려 있다.
  `RealProviderCall` 은 `BaseException` 이라 `except Exception` 이 삼켜 다른 오류로 바꾸지 못한다.
- autouse `no_real_http` — 둘째 겹. httpx 의 실제 전송(`httpx.AsyncHTTPTransport.handle_async_request`·
  `httpx.HTTPTransport.handle_request`)이 내 컴퓨터 밖을 향해 불리면 소켓에 닿기 전에 `RealProviderCall` — 클라이언트를 어떻게
  만들었든(transport 없는 `KatClient`·`client_for`, `make_client()`, 손으로 만든 `httpx.AsyncClient`) 같다.
- fixture `http_refused` — httpx 로 나가는 모든 요청이 연결 거절(`httpx.ConnectError`)로 끝난다. 꺼진 서버(Qdrant 등)를
  소켓에 닿지 않고 흉내 낸다.
- 끝나지 않는 시험 막이 둘(2026-11-23 밤, 끝없이 다시 묻는 고리가 가짜를 붙잡고 메모리 5GB 를 잡았다): 가짜 서버는 요청을
  `limit` 번(기본 `MAX_FAKE_REQUESTS`)까지만 받고 그 뒤는 `RunawayFake`(BaseException) 를 올린다. fixture `time_guard` 는
  시험 하나가 `GUARD_S` 초 안에 끝나지 않으면 끊는다(`time_limit` — 도는 고리도, 기다리기만 하는 시험도). 어느 시험 파일이든
  `pytestmark = pytest.mark.usefixtures("time_guard")` 로 건다(「멈춤·끝없음·아주 큼」을 흉내 내는 파일은 꼭).
"""

import ipaddress
import json
import signal
import socket
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.notify import diagnostics
from app.outreach import provider
from app.outreach.provider import (
    Accepted,
    Check,
    Delivery,
    Inbound,
    MessageRequest,
    ProviderFailed,
    Received,
)
from tests.outreach_doubles import SENTINEL_KEY

KAT_BASE = "https://api.koreaaitel.com"
KAT_ACCOUNT = "AC00000000003c4d"
KAT_SENDER = "07000000123"
PUBLIC_IP = "93.184.216.34"
_T0 = datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)  # 지난 날짜(제공사 호출은 5분 넘게 앞선 시각을 조회 시각으로 바꾼다)
NO_TRANSPORT = ("시험에서 실제 HTTP 로 나가려 했습니다({method} {host}) — KatClient(conn, transport=KatMock()) 로 만들거나 "
                "fixture fake_provider 를 쓰세요(진단은 make_client(transport=…)). 내 컴퓨터 밖은 풀 수 없습니다.")
NO_NETWORK = "시험에서 내 컴퓨터 밖으로 {what} 했습니다({host}) — 가짜를 끼워 넣으세요. 풀 수 있는 표시는 없습니다."


MAX_FAKE_REQUESTS = 200  # 가짜 서버 하나가 받는 요청 수의 상한(시험 하나가 가짜를 부르는 것은 많아야 수십 번이다)
GUARD_S = 20.0  # time_guard 가 시험 하나에 주는 실제 시간(초)


class RealProviderCall(BaseException):
    """시험이 가짜 없이 실제 전송에 닿았다. Exception 이 아니다 — `except Exception` 이 삼키지 못하게."""


class RunawayFake(BaseException):
    """가짜 서버가 상한보다 많이 불렸다 — 부르는 쪽이 끝없이 돌고 있다. Exception 이 아니다(삼켜져 고리가 이어지지 않게)."""


def is_loopback(host: object) -> bool:
    """내 컴퓨터 안을 가리키는가(127.0.0.0/8 · ::1 · localhost)."""
    text = host.decode(errors="replace") if isinstance(host, bytes) else str(host)
    try:
        return ipaddress.ip_address(text.split("%")[0]).is_loopback
    except ValueError:
        return text.lower() == "localhost"


# ── 소켓 막이(이 파일이 올라올 때 한 번) ────────────────────────────
REAL_SOCKET = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex, "getaddrinfo": socket.getaddrinfo}


def _refuse_outside(sock: socket.socket, address: object) -> None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    host = address[0] if isinstance(address, tuple) and address else address
    if not is_loopback(host):
        raise RealProviderCall(NO_NETWORK.format(what="연결하려", host=host))


def guarded_connect(self: socket.socket, address: object) -> None:
    _refuse_outside(self, address)
    return REAL_SOCKET["connect"](self, address)


def guarded_connect_ex(self: socket.socket, address: object) -> int:
    _refuse_outside(self, address)
    return REAL_SOCKET["connect_ex"](self, address)


def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> list:
    if host is not None and not is_loopback(host):
        raise RealProviderCall(NO_NETWORK.format(what="이름을 풀려", host=host))
    return REAL_SOCKET["getaddrinfo"](host, *args, **kwargs)


socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = guarded_connect, guarded_connect_ex, guarded_getaddrinfo


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class KatMock(httpx.MockTransport):
    """가짜 한국AI통신. `requests` 에 받은 요청이 쌓인다. `override(request)` 가 응답을 돌려주면 그것이 먼저다(None 이면 기본).

    요청은 `limit` 번까지만 받는다 — 넘으면 RunawayFake(끝없이 부르는 코드가 시험을 붙잡지 못하게).

    기본 동작: 키가 틀리면 401, 계정 경로가 틀리면 404, 발신번호 2개(승인 1·대기 1), 보내기는 201 `queued`
    (같은 IdempotencyKey 는 처음 것 그대로), 목록은 최신순·page 는 0부터·pageSize 100 초과는 400.
    """

    def __init__(self, *, key: str = SENTINEL_KEY, account: str = KAT_ACCOUNT, override=None,
                 limit: int = MAX_FAKE_REQUESTS) -> None:
        self.key, self.account, self.override, self.limit = key, account, override, limit
        self.requests: list[httpx.Request] = []
        self.senders: list[dict] = [
            {"id": "SN0001", "number": KAT_SENDER, "type": "070", "verificationMethod": "own_provisioned",
             "status": "approved", "createdAt": _iso(_T0)},
            {"id": "SN0002", "number": "07000000456", "type": "070", "verificationMethod": "own_provisioned",
             "status": "pending", "createdAt": _iso(_T0)},
        ]
        self.messages: dict[str, dict] = {}  # 만든 차례대로
        self.keys: dict[str, str] = {}  # IdempotencyKey → messageId
        self.calls: dict[str, dict] = {}
        super().__init__(self._handle)

    # ── 시험이 상태를 만드는 손잡이 ──
    def _message(self, *, to: str, sender: str, body: str | None, direction: str, status: str, kind: str = "sms",
                 at: datetime | None = None, media: int = 0) -> dict:
        mid = f"MG{len(self.messages) + 1:06d}abcdef"
        at = at or _T0 + timedelta(seconds=len(self.messages))
        row = {"messageId": mid, "status": status, "failureCode": None, "failureMessage": None, "type": kind,
               "subject": None, "to": to, "from": sender, "body": body, "numMedia": media,
               "mediaUrl": [f"https://media.invalid/{mid}/{i}.jpg" for i in range(media)], "direction": direction,
               "accountId": self.account, "dateCreated": _iso(at), "dateUpdated": None}
        self.messages[mid] = row
        return row

    def add_inbound(self, sender: str, body: str, at: datetime, *, media: int = 0) -> str:
        """받은 문자 한 건(`status received`, `direction inbound`)을 둔다. messageId 를 돌려준다."""
        return self._message(to=KAT_SENDER, sender=sender, body=body, direction="inbound", status="received",
                             at=at, media=media)["messageId"]

    def set_status(self, message_id: str, status: str, failure: str | None = None, text: str | None = None) -> None:
        self.messages[message_id].update(status=status, failureCode=failure, failureMessage=text,
                                         dateUpdated=_iso(_T0 + timedelta(minutes=1)))

    def add_call(self, call_id: str, **fields: object) -> None:
        self.calls[call_id] = {"callId": call_id, "status": "completed", "to": "01000000199", "from": KAT_SENDER,
                               "direction": "outbound", "duration": 42, "accountId": self.account,
                               "answeredBy": None, "hangupCause": None, "hangupSource": "callee",
                               "callerIdRestricted": None, "recording": False, "recordingUrl": None,
                               "dateCreated": _iso(_T0), "dateUpdated": _iso(_T0 + timedelta(seconds=42)), **fields}

    def sent_bodies(self) -> list[dict]:
        """POST …/messages 로 받은 본문들(차례대로)."""
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    # ── 가짜 서버 ──
    @staticmethod
    def _error(status: int, code: str, error: str = "가짜 오류") -> httpx.Response:
        return httpx.Response(status, json={"error": error, "code": code})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if len(self.requests) >= self.limit:
            raise RunawayFake(f"가짜 서버가 {self.limit}번 넘게 불렸습니다 — 부르는 쪽이 끝나지 않습니다")
        self.requests.append(request)
        if self.override is not None and (scripted := self.override(request)) is not None:
            return scripted
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return self._error(401, "unauthorized")
        prefix = f"/v1/accounts/{self.account}/"
        if not request.url.path.startswith(prefix):
            return self._error(404, "not_found")
        parts = request.url.path[len(prefix):].split("/")
        if parts == ["sender-numbers"] and request.method == "GET":
            return httpx.Response(200, json={"senderNumbers": self.senders, "grace": [], "limit": None})
        if parts == ["messages"] and request.method == "POST":
            return self._send(json.loads(request.content))
        if parts == ["messages"] and request.method == "GET":
            return self._list(request.url.params)
        if len(parts) == 2 and parts[0] == "messages" and request.method == "GET":
            row = self.messages.get(parts[1])
            return httpx.Response(200, json=row) if row else self._error(404, "not_found")
        if len(parts) == 2 and parts[0] == "calls" and request.method == "GET":
            row = self.calls.get(parts[1])
            return httpx.Response(200, json=row) if row else self._error(404, "not_found")
        return self._error(404, "not_found")

    def _send(self, body: dict) -> httpx.Response:
        if not body.get("To") or not body.get("From"):
            return self._error(400, "invalid_input")
        key = body.get("IdempotencyKey")
        if key == "":
            return self._error(400, "invalid_input")
        if key in self.keys:
            return httpx.Response(201, json=self.messages[self.keys[key]])
        kakao = "Kakao" in body
        row = self._message(to=body["To"], sender=body["From"], body=None if kakao else body.get("Body"),
                            direction="outbound", status="queued", kind="ata" if kakao else "sms")
        if key:
            self.keys[key] = row["messageId"]
        return httpx.Response(201, json=row)

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        size, page = int(params.get("pageSize", "20")), int(params.get("page", "0"))
        if size > 100:
            return self._error(400, "invalid_input")
        rows = [m for m in self.messages.values() if params.get("status") in (None, m["status"])]
        rows.sort(key=lambda m: m["dateCreated"], reverse=True)  # 최신순 고정
        return httpx.Response(200, json={"data": rows[page * size:(page + 1) * size],
                                         "meta": {"page": page, "pageSize": size, "total": len(rows)}})


class FakeProvider:
    """메모리 `Provider`. 보낸 요청은 `sent`, 불린 차례는 `log`. `fail` 에 ProviderFailed 를 두면 모든 호출이 그것을 올린다.

    보내기는 실제 클라이언트와 같은 검사(`provider._message_body`)를 거친다 — 모자란 요청은 ProviderFailed(bad_request).
    같은 `idempotency_key` 로 다시 보내면 처음 것의 id 를 돌려주고 `sent` 에 다시 쌓지 않는다. 상태는 `statuses[id]`
    (없으면 accepted), 받은 문자는 `inbox`(received 가 since 이후 것만 오래된 차례로 — `truncated`·`skipped`·`redated` 는
    `received_flags` 에 둔 값), 통화는 `call_infos[id]`.
    """

    def __init__(self) -> None:
        self.sent: list[MessageRequest] = []
        self.log: list[str] = []
        self.fail: ProviderFailed | None = None
        self.senders: list[str] = [KAT_SENDER]
        self.statuses: dict[str, Delivery] = {}
        self.inbox: list[Inbound] = []
        self.call_infos: dict[str, dict] = {}
        self.received_flags: dict = {}  # Received 의 truncated·skipped·redated
        self._ids: dict[str, str] = {}

    def _called(self, name: str) -> None:
        self.log.append(name)
        if self.fail is not None:
            raise self.fail

    async def check(self) -> Check:
        self._called("check")
        return Check(ok=True, senders=list(self.senders), latency_ms=1)

    async def send_message(self, req: MessageRequest) -> Accepted:
        self._called("send_message")
        provider._message_body(req)
        if req.idempotency_key not in self._ids:
            self._ids[req.idempotency_key] = f"FAKE{len(self._ids) + 1:04d}"
            self.sent.append(req)
        return Accepted(provider_id=self._ids[req.idempotency_key])

    async def message_status(self, provider_id: str) -> Delivery:
        self._called("message_status")
        return self.statuses.get(provider_id, Delivery(state="accepted"))

    async def received(self, since: datetime | None) -> Received:
        self._called("received")
        floor = since.replace(tzinfo=UTC) if since is not None and since.tzinfo is None else since
        items = sorted((m for m in self.inbox if floor is None or m.at >= floor), key=lambda m: m.at)
        return Received(items=items, fetched_at=datetime.now(UTC), **self.received_flags)

    async def call_info(self, provider_call_id: str) -> dict:
        self._called("call_info")
        if provider_call_id not in self.call_infos:
            raise ProviderFailed("bad_request", "그 통화를 찾을 수 없습니다.", 404)
        return dict(self.call_infos[provider_call_id])


@pytest.fixture(autouse=True)
def no_provider_dns(monkeypatch) -> list[str]:
    """시험은 이름 풀이(DNS)를 쓰지 않는다 — 제공사 호출과 연결 진단이 푸는 모든 호스트가 공인 IP 하나로 풀린다. 물은 호스트 목록."""
    asked: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        asked.append(host)
        return [PUBLIC_IP]

    monkeypatch.setattr(provider, "RESOLVE", resolve)
    monkeypatch.setattr(diagnostics, "RESOLVE", resolve)
    return asked


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch) -> None:
    """시험에서는 httpx 의 실제 전송으로 내 컴퓨터 밖에 나갈 수 없다(모듈 머리 글). 가짜 transport 를 준 클라이언트와
    내 컴퓨터 안(127.0.0.1 의 시험 서버)으로 가는 요청은 그대로 지나간다."""
    real_async, real = httpx.AsyncHTTPTransport.handle_async_request, httpx.HTTPTransport.handle_request

    async def refuse_async(self, outgoing: httpx.Request) -> httpx.Response:
        if is_loopback(outgoing.url.host):
            return await real_async(self, outgoing)
        raise RealProviderCall(NO_TRANSPORT.format(method=outgoing.method, host=outgoing.url.host))

    def refuse(self, outgoing: httpx.Request) -> httpx.Response:
        if is_loopback(outgoing.url.host):
            return real(self, outgoing)
        raise RealProviderCall(NO_TRANSPORT.format(method=outgoing.method, host=outgoing.url.host))

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def http_refused(monkeypatch) -> None:
    """httpx 로 나가는 모든 요청이 연결 거절로 끝난다 — 꺼진 서버를 소켓에 닿지 않고 흉내 낸다."""
    async def refused_async(self, outgoing: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결 거절(시험이 끼운 것)")

    def refused(self, outgoing: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결 거절(시험이 끼운 것)")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refused_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refused)


@contextmanager
def time_limit(seconds: float):
    """안의 일이 seconds 초 안에 끝나지 않으면 끊는다(KeyboardInterrupt — pytest 가 멈춘 줄을 보이고 실행을 끝낸다).
    주 스레드에 진짜 SIGINT 를 보내므로 이벤트 루프에 돌아오지 않는 고리도, 막힌 시스템 호출(sleep·소켓)도, 아무도 풀어 주지
    않는 await 도 끊긴다. SIGALRM 은 쓰지 않는다(실행 전체에 건 `alarm` 을 지우지 않게). 주 스레드에서만 쓴다."""
    done, main = threading.Event(), threading.main_thread().ident
    before = signal.getsignal(signal.SIGINT)
    deaf = before in (signal.SIG_IGN, signal.SIG_DFL)  # 셸의 배경 작업으로 띄우면 SIGINT 를 무시한 채 시작한다
    if deaf:
        signal.signal(signal.SIGINT, signal.default_int_handler)

    def watch() -> None:
        if done.wait(seconds):
            return
        for _ in range(5):  # asyncio 는 첫 번째에 태스크 취소만 청한다 — 그래도 안 끝나면 다시
            signal.pthread_kill(main, signal.SIGINT)
            if done.wait(1.0):
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        yield
    finally:
        done.set()
        if deaf:
            signal.signal(signal.SIGINT, before)


@pytest.fixture
def time_guard():
    """시험 하나에 GUARD_S 초(실제 시간)만 준다."""
    with time_limit(GUARD_S):
        yield


@pytest.fixture
def fake_provider(monkeypatch) -> FakeProvider:
    """`provider.client_for` 가 어느 연결 줄이든 이 FakeProvider 를 돌려주게 한다."""
    fake = FakeProvider()
    monkeypatch.setattr(provider, "client_for", lambda row: fake)
    return fake
