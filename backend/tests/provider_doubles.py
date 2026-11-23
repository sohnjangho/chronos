"""한국AI통신 REST 시험용 가짜(Task 69). conftest 의 pytest_plugins 로 올린다. 실제 제공사·DNS 를 쓰지 않는다.

- KatMock — `httpx.MockTransport`. 공개 문서(docs.koreaaitel.com, 2026-11-23)의 경로·칸 이름으로 답하는 가짜 서버.
  `KatClient(conn, transport=KatMock())` 로 끼운다. 값은 모두 가상이다.
- FakeProvider — `Provider` 를 메모리로 구현한 것. fixture `fake_provider` 가 `provider.client_for` 를 이것으로 바꾼다
  (그래서 쓰는 쪽은 `from app.outreach import provider` 뒤 `provider.client_for(row)` 로 불러야 한다).
- autouse `no_provider_dns` — `provider.RESOLVE` 를 공인 IP 하나로 답하는 가짜로 바꾼다(시험이 DNS 를 쓰지 않게).
- autouse `no_real_provider` — 시험에서는 실제 전송으로 나갈 수 없다: transport 없이 `KatClient` 를 만들거나(`client_for`
  포함) `diagnostics.make_client()` 를 transport 없이 부르면 바로 `RealProviderCall`(AssertionError) 이 난다.
  진단 쪽은 모듈 속성 `diagnostics.make_client` 를 감싼 것이라 `from … import make_client` 로 먼저 잡아 둔 이름에는
  듣지 않는다 — 진단을 부르는 코드는 `diagnostics.make_client(...)` 로 부를 것.
"""

import json
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
NO_TRANSPORT = ("시험에서 실제 제공사로 나가려 했습니다 — KatClient(conn, transport=KatMock()) 로 만들거나 "
                "fixture fake_provider 를 쓰세요(진단은 make_client(transport=…)).")


class RealProviderCall(AssertionError):
    """시험이 가짜 없이 제공사 클라이언트를 만들었다."""


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class KatMock(httpx.MockTransport):
    """가짜 한국AI통신. `requests` 에 받은 요청이 쌓인다. `override(request)` 가 응답을 돌려주면 그것이 먼저다(None 이면 기본).

    기본 동작: 키가 틀리면 401, 계정 경로가 틀리면 404, 발신번호 2개(승인 1·대기 1), 보내기는 201 `queued`
    (같은 IdempotencyKey 는 처음 것 그대로), 목록은 최신순·page 는 0부터·pageSize 100 초과는 400.
    """

    def __init__(self, *, key: str = SENTINEL_KEY, account: str = KAT_ACCOUNT, override=None) -> None:
        self.key, self.account, self.override = key, account, override
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
    """시험은 이름 풀이(DNS)를 쓰지 않는다 — KatClient 가 푸는 모든 호스트가 공인 IP 하나로 풀린다. 물은 호스트 목록."""
    asked: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        asked.append(host)
        return [PUBLIC_IP]

    monkeypatch.setattr(provider, "RESOLVE", resolve)
    return asked


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch) -> None:
    """시험에서는 실제 전송을 고를 수 없다(모듈 머리 글). 가짜 transport 를 준 것은 그대로 지나간다."""

    def refuse() -> None:
        raise RealProviderCall(NO_TRANSPORT)

    real_make_client = diagnostics.make_client

    def make_client(*, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
        if transport is None:
            raise RealProviderCall(NO_TRANSPORT)
        return real_make_client(transport=transport)

    monkeypatch.setattr(provider, "_default_transport", refuse)
    monkeypatch.setattr(diagnostics, "make_client", make_client)


@pytest.fixture
def fake_provider(monkeypatch) -> FakeProvider:
    """`provider.client_for` 가 어느 연결 줄이든 이 FakeProvider 를 돌려주게 한다."""
    fake = FakeProvider()
    monkeypatch.setattr(provider, "client_for", lambda row: fake)
    return fake
