"""Task 69 — 한국AI통신 REST 호출(app.outreach.provider). 실제 제공사·DNS 를 쓰지 않는다(KatMock = httpx.MockTransport).

응답 모양은 공개 문서(docs.koreaaitel.com, 2026-11-23)의 칸 이름을 따른 가상 값이다.
"""

import asyncio
import gzip
import json
import logging
import signal
import socket
import time
import traceback
import unicodedata
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpcore
import httpx
import pytest

from app.info.generic import key_survives
from app.notify import diagnostics
from app.outreach import phone, provider, redact, sms_text
from app.outreach.provider import (
    RECEIVED_MAX_PAGES,
    RECEIVED_MAX_REQUESTS,
    RECEIVED_PAGE_SIZE,
    STATUS_MAP,
    Accepted,
    KatClient,
    MessageRequest,
    ProviderConn,
    ProviderFailed,
    Received,
)
from app.security import crypto
from app.store.tables_outreach import NotifyConnection
from tests import provider_doubles
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)
from tests.provider_doubles import (
    KAT_ACCOUNT,
    KAT_BASE,
    KAT_SENDER,
    FakeProvider,
    KatMock,
    RealProviderCall,
    RunawayFake,
    time_limit,
)

pytestmark = pytest.mark.usefixtures("time_guard")  # 멈춤·끝없음·큰 응답을 흉내 내는 시험들 — 하나가 20초를 넘기면 끊는다

CONN = ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=SENTINEL_KEY)
T0 = datetime(2026, 11, 23, 3, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=1)  # 시험 속 「지금」
ECHO = f"key={SENTINEL_KEY} acct={KAT_ACCOUNT} to={SENTINEL_PHONE} raw={SENTINEL_DIGITS}"  # 제공사가 되돌려 보낸다고 치는 글
GOOD = {"messageId": "MG1", "direction": "inbound", "from": SENTINEL_DIGITS, "to": KAT_SENDER, "body": "네", "numMedia": 0,
        "mediaUrl": [], "dateCreated": "2026-11-23T03:00:00.123Z"}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    """제공사 호출이 보는 시각을 고정한다(벽시계에 기대지 않게)."""
    monkeypatch.setattr(provider, "_now", lambda: NOW)


def sms(**changes: object) -> MessageRequest:
    fields = {"channel": "sms", "to": SENTINEL_DIGITS, "sender": KAT_SENDER, "body": "내일 08시 타설입니다.",
              "idempotency_key": "idem-0001"}
    return MessageRequest(**{**fields, **changes})


def kakao(**changes: object) -> MessageRequest:
    return sms(**{"channel": "kakao", "body": "", "kakao_channel": "CH0001", "template_code": "TP0001",
                  "template_vars": {"작업": "타설"}, **changes})


def leaks(*values: object) -> list[str]:
    """값들을 글로 옮겨 키·Account ID·시험 번호(어느 꼴이든)가 남았는지 본다. 남은 것의 이름 목록."""
    found = []
    for value in values:
        text = value if isinstance(value, str) else repr(value)
        digits = "".join(c for c in text if c.isdigit())
        if SENTINEL_DIGITS in digits or SENTINEL_DIGITS[1:] in digits:
            found.append("phone")
        found += [name for name, secret in (("key", SENTINEL_KEY), ("account", KAT_ACCOUNT)) if key_survives(text, secret)]
    return found


def everything_in(exc: BaseException) -> list[object]:
    """예외에서 꺼낼 수 있는 글 전부(이어진 예외까지)."""
    out: list[object] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        out += [str(exc), repr(exc), list(exc.args), dict(vars(exc))]
        exc = exc.__cause__ or exc.__context__
    return out


async def failure(awaitable) -> ProviderFailed:
    with pytest.raises(ProviderFailed) as caught:
        await awaitable
    return caught.value


def answer(status: int, body: object = None, **kw: object):
    """모든 요청에 같은 응답을 주는 override."""
    return lambda request: httpx.Response(status, json=body, **kw) if body is not None else httpx.Response(status, **kw)


def raw(status: int, content: bytes, content_type: str = "text/html"):
    return lambda request: httpx.Response(status, content=content, headers={"content-type": content_type})


def raising(exc_type: type[Exception], text: str = ""):
    def override(request: httpx.Request) -> httpx.Response:
        raise exc_type(f"boom {text} {ECHO} {request.url}")

    return override


def page(rows: list) -> object:
    """받은 문자 한 쪽. 제공사가 한글·짝 없는 서로게이트를 \\uXXXX 로 적어 보낸 꼴(ensure_ascii)로 싣는다."""
    return raw(200, json.dumps({"data": rows, "meta": {"page": 0, "pageSize": 50, "total": len(rows)}}).encode(),
               "application/json")


def body_then(status: int, first: bytes, exc_type: type[Exception]):
    """상태와 본문 앞부분까지 온 뒤 끊기는 응답."""
    async def chunks():
        yield first
        raise exc_type(f"boom {ECHO}")

    return lambda request: httpx.Response(status, content=chunks(), headers={"content-type": "application/json"})


class Hangs(httpx.AsyncBaseTransport):
    """응답하지 않는 서버. at="connect" 는 요청을 읽기 전(연결 단계)에 멈춘다 — httpx 의 연결 시간 제한을 스스로 지킨다.
    at="response" 는 요청을 다 받은 뒤 멈춘다."""

    def __init__(self, at: str) -> None:
        self.at = at
        self.read_request = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.at == "connect":
            try:
                await asyncio.wait_for(asyncio.sleep(30), request.extensions["timeout"]["connect"])
            except TimeoutError:
                raise httpx.ConnectTimeout("connect timed out") from None
        await request.aread()
        self.read_request = True
        await asyncio.sleep(30)
        raise AssertionError("닿지 않는다")


def row(**changes: object) -> NotifyConnection:
    fields = {"name": "기본", "base_url": KAT_BASE, "secret_ciphertext": crypto.encrypt(SENTINEL_KEY), "secret_last4": "9999",
              "account_id": KAT_ACCOUNT}
    return NotifyConnection(**{**fields, **changes})


# ── 보내기 ──────────────────────────────────────────────────────────


async def test_send_puts_bearer_and_idempotency_key():
    mock = KatMock()
    accepted = await KatClient(CONN, transport=mock).send_message(sms())
    assert len(mock.requests) == 1
    request = mock.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{KAT_BASE}/v1/accounts/{KAT_ACCOUNT}/messages"
    assert request.headers["authorization"] == f"Bearer {SENTINEL_KEY}"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["content-length"] == str(len(request.content)) and "transfer-encoding" not in request.headers
    # Type 은 넣지 않는다 — 제공사가 본문 길이로 sms/lms 를 고른다(문서).
    assert json.loads(request.content) == {"To": SENTINEL_DIGITS, "From": KAT_SENDER, "Body": "내일 08시 타설입니다.",
                                           "IdempotencyKey": "idem-0001"}
    assert accepted == Accepted(provider_id=next(iter(mock.messages)))


async def test_kakao_body_has_channel_template_and_no_fallback_unless_asked():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    await client.send_message(kakao())
    await client.send_message(kakao(idempotency_key="idem-0002", fallback_sms=True))
    await client.send_message(kakao(idempotency_key="idem-0003", fallback_sms=True, fallback_body="문자로 보냅니다."))
    first, second, third = mock.sent_bodies()
    # 알림톡에는 Body·Type 을 넣지 않는다. 제공사는 Fallback 을 빼면 문자로 대신 보내므로, 기본은 끈다고 명시한다.
    assert first == {"To": SENTINEL_DIGITS, "From": KAT_SENDER, "IdempotencyKey": "idem-0001",
                     "Kakao": {"ChannelId": "CH0001", "TemplateId": "TP0001", "Variables": {"작업": "타설"}},
                     "Fallback": {"Disabled": True}}
    assert "Fallback" not in second  # 대신 보내기를 켜면 제공사 기본(문안 그대로 문자)
    assert third["Fallback"] == {"Body": "문자로 보냅니다."}
    assert "Body" not in second and "Type" not in second


BAD_REQUESTS = [
    sms(to=""), sms(sender=""), sms(body=""), sms(channel="call"), sms(to=None), sms(body=7),
    kakao(kakao_channel=None), kakao(template_code=""),
    kakao(template_vars={"a": object()}), kakao(template_vars={"a": 3}), kakao(template_vars=["a"]),  # 보낼 꼴로 만들 수 없다
    # 중복 방지 키는 ^[A-Za-z0-9_-]{8,64}$ 만
    sms(idempotency_key=""), sms(idempotency_key="short"), sms(idempotency_key="a" * 65), sms(idempotency_key=" idem-0001"),
    sms(idempotency_key="idem 0001"), sms(idempotency_key="idem-0001\n"), sms(idempotency_key="키-한글-0001"),
    sms(idempotency_key=None), sms(idempotency_key=17),
]


@pytest.mark.parametrize("req", BAD_REQUESTS)
async def test_incomplete_request_is_refused_before_any_call(req):
    mock = KatMock()
    e = await failure(KatClient(CONN, transport=mock).send_message(req))
    assert e.code == "bad_request" and mock.requests == [] and e.maybe_sent is False and e.http_status is None
    fake = FakeProvider()  # 가짜도 같은 검사를 한다
    assert (await failure(fake.send_message(req))).code == "bad_request" and fake.sent == []


@pytest.mark.parametrize(("text", "expected"), [
    ("8시 \u2014 타설", "8시 - 타설"), ("a\u2013b\u2015c\u2012d\u2010e\ufe58f\ufe63g\uff0dh", "a-b-c-d-e-f-g-h"),
    ("3\u20114층", "3-4층"), ("\u22125도", "-5도"), ("\u2022 철근", "\u00b7 철근"),
    ("\u2018네\u2019 \u201a", "'네' '"), ("\u201c확인\u201d \u201e", '"확인" "'), ("잠시만\u2026", "잠시만..."),
    ("8\u00a0시\u2009반\u202f끝\u2002.", "8 시 반 끝 ."), ("타\u200b설\u200c\u200d\u2060\ufeff", "타설"),
    ("확인 부탁드립니다 \U0001f64f\U0001f477\U0001f44d\ufe0f", "확인 부탁드립니다 "), ("깨진\ud800글", "깨진글"),
    (unicodedata.normalize("NFD", "타설 확인"), "타설 확인"),  # 풀어 쓴 한글은 모아 쓴 꼴로(지우지 않는다)
    ("3층·4층 「타설」 ※ 우천 ○ ☆ 줄\n바꿈 漢字", "3층·4층 「타설」 ※ 우천 ○ ☆ 줄\n바꿈 漢字"),  # KS X 1001 은 그대로
])
def test_sms_safe_swaps_or_drops_only_symbols_the_provider_cannot_carry(text, expected):
    out = sms_text.sms_safe(text)
    assert out == expected and sms_text.problem(out) is None
    out.encode("euc_kr")  # 제공사는 EUC-KR(KS X 1001)로 싣는다
    assert sms_text.sms_safe(out) == out  # 두 번 거쳐도 같다


@pytest.mark.parametrize(("text", "kept", "why"), [
    ("Xin ch\u00e0o, t\u00f4i l\u00e0 Vi\u1ec7t", "Vi\u1ec7t", sms_text.NOT_CARRIED),  # 베트남어 성조
    ("철근 \u4e22 확인", "\u4e22", sms_text.NOT_CARRIED),  # KS X 1001 에 없는 한자
    ("\u6211\u4eec\u8fd9\u91cc", "\u8fd9", sms_text.NOT_CARRIED),  # 간체자
    ("\ub620\ubc29\uac01\ud558", "\ub620", sms_text.NOT_CARRIED),  # CP949 에만 있는 한글(똠)
    ("\U0001f477\u200b \ufe0f", "", sms_text.EMPTY),
    ("가" * 1001, "가", sms_text.TOO_LONG),
])
def test_letters_that_cannot_be_carried_are_kept_and_refused_not_dropped(text, kept, why):
    assert kept in sms_text.sms_safe(text) and sms_text.problem(text) == why
    assert sms_text.problem("가" * 1000) is None and sms_text.byte_size("가" * 1000) == 2000


async def test_sms_and_fallback_text_go_out_in_what_the_provider_can_carry():
    mock = KatMock()
    await KatClient(CONN, transport=mock).send_message(sms(body="8시 \u2014 타설 \U0001f477"))
    await KatClient(CONN, transport=mock).send_message(kakao(fallback_sms=True, fallback_body="\u201c확인\u201d\u2026"))
    first, second = (json.loads(r.content) for r in mock.requests)
    assert first["Body"] == "8시 - 타설 " and second["Fallback"] == {"Body": '"확인"...'}
    for req in (sms(body="\U0001f477\u200b"), sms(body="Vi\u1ec7t"), kakao(fallback_sms=True, fallback_body="Vi\u1ec7t")):
        mock = KatMock()
        e = await failure(KatClient(CONN, transport=mock).send_message(req))  # 요청 전에 막는다
        assert e.code == "not_sendable" and mock.requests == [] and e.maybe_sent is False


@pytest.mark.parametrize("key", ["idem-0001", "a" * 8, "A_b-9" * 12 + "abcd", "0f8fad5bd9cb469fa16570867728950e"])
async def test_idempotency_key_goes_on_the_wire_as_given_and_nothing_is_retried(key):
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    first = await client.send_message(sms(idempotency_key=key))
    assert [body["IdempotencyKey"] for body in mock.sent_bodies()] == [key]
    assert await client.send_message(sms(idempotency_key=key)) == first and len(mock.messages) == 1  # 같은 키는 같은 메시지
    mock.requests.clear()
    mock.override = answer(500, {"error": "x", "code": "internal"})
    e = await failure(client.send_message(sms(idempotency_key=key)))
    assert e.code == "server" and len(mock.requests) == 1  # 다시 시도하지 않는다 — 다시 보내기는 나가는 문이 정한다
    assert json.loads(mock.requests[0].content)["IdempotencyKey"] == key


async def test_message_the_vendor_already_marked_failed_is_still_accepted_with_its_id():
    mock = KatMock(override=answer(201, {"messageId": "MG9", "status": "failed", "failureCode": "invalid_number"}))
    assert await KatClient(CONN, transport=mock).send_message(sms()) == Accepted(provider_id="MG9")  # 실패는 상태 조회가 알린다


# ── 보냈는지 알 수 있는가(maybe_sent) ──────────────────────────────

POST_OUTCOMES = [  # (이름, 가짜 응답, code, http_status, maybe_sent)
    ("connect error", raising(httpx.ConnectError), "network", None, False),
    ("tls error", raising(httpx.ConnectError, "[SSL: CERTIFICATE_VERIFY_FAILED]"), "network", None, False),
    ("pool timeout", raising(httpx.PoolTimeout), "timeout", None, False),
    ("write timeout", raising(httpx.WriteTimeout), "timeout", None, True),
    ("write error", raising(httpx.WriteError), "network", None, True),
    ("read timeout", raising(httpx.ReadTimeout), "timeout", None, True),
    ("read error", raising(httpx.ReadError), "network", None, True),
    ("protocol error", raising(httpx.RemoteProtocolError), "network", None, True),
    ("other exception", raising(RuntimeError), "unknown", None, True),
    ("2xx unreadable body", raw(200, b"<html>"), "unknown", 200, True),
    ("204 empty", answer(204), "unknown", 204, True),
    ("2xx without id", answer(202, {"note": "queued"}), "unknown", 202, True),
    ("2xx error-shaped", answer(200, {"error": "x", "code": "invalid_phone"}), "unknown", 200, True),
    ("302", answer(302, headers={"location": "https://elsewhere.invalid/"}), "bad_request", 302, True),
    ("400", answer(400, {"code": "invalid_phone"}), "bad_request", 400, False),
    ("401", raw(401, b"nope"), "bad_key", 401, False),
    ("403", answer(403, {"code": "forbidden"}), "bad_account", 403, False),
    ("408", answer(408), "bad_request", 408, False),
    ("409", answer(409, {"code": "idempotency_conflict"}), "bad_request", 409, True),  # 같은 키가 처리되는 중일 수 있다
    ("422", answer(422, {"code": "quota_exceeded"}), "bad_request", 422, False),
    ("429", answer(429, {"code": "rate_limited"}), "rate_limited", 429, False),
    ("500", answer(500, {"code": "internal"}), "server", 500, True),
    ("502 html", raw(502, b"<html>Bad Gateway</html>"), "server", 502, True),  # 관문이 대신 답함 — 제공사는 받았을 수 있다
    ("503", answer(503), "server", 503, True),
    ("504", raw(504, b"upstream timed out", "text/plain"), "server", 504, True),
    ("500 with a 4xx-looking code", answer(500, {"code": "invalid_phone"}), "bad_request", 500, True),
]


@pytest.mark.parametrize(("name", "override", "code", "status", "maybe_sent"), POST_OUTCOMES, ids=[c[0] for c in POST_OUTCOMES])
async def test_send_says_whether_the_message_may_have_gone(name, override, code, status, maybe_sent):
    mock = KatMock(override=override)
    client = KatClient(CONN, transport=mock)
    sent = await failure(client.send_message(sms()))
    assert (sent.code, sent.http_status, sent.maybe_sent) == (code, status, maybe_sent)
    assert ("보냈는지" in sent.message) is maybe_sent  # 글에도 적는다
    asked = await failure(client.message_status("MG000001abcdef"))
    assert asked.maybe_sent is False and "보냈는지" not in asked.message  # 조회는 보낸 것이 없다
    assert len(mock.requests) == 2  # 다시 시도하지 않는다
    assert leaks(*everything_in(sent), *everything_in(asked)) == []


@pytest.mark.parametrize(("connect_limit", "total_limit"), [(0.05, 0.4), (0.4, 0.05), (0.05, 0.05)])
async def test_timeout_before_the_request_is_written_means_nothing_was_sent(monkeypatch, connect_limit, total_limit):
    """닿지 않는 호스트: 연결 제한이 먼저 걸리든 전체 제한이 먼저 걸리든(둘이 같아도) 한 바이트도 안 나갔으면 「안 나감」."""
    monkeypatch.setattr(diagnostics, "CONNECT_TIMEOUT_S", connect_limit)
    monkeypatch.setattr(provider, "TIMEOUT_S", total_limit)
    hung = Hangs("connect")
    e = await failure(KatClient(CONN, transport=hung).send_message(sms()))
    assert (e.code, e.maybe_sent, e.http_status) == ("timeout", False, None) and hung.read_request is False
    assert "보냈는지" not in e.message


async def test_timeout_after_the_request_is_written_may_have_been_sent(monkeypatch):
    monkeypatch.setattr(provider, "TIMEOUT_S", 0.05)
    hung = Hangs("response")
    e = await failure(KatClient(CONN, transport=hung).send_message(sms()))
    assert (e.code, e.maybe_sent) == ("timeout", True) and hung.read_request is True
    asked = await failure(KatClient(CONN, transport=Hangs("response")).message_status("MG1"))
    assert (asked.code, asked.maybe_sent) == ("timeout", False)


async def test_connect_limit_is_shorter_than_the_whole_call_and_goes_on_every_request():
    assert 0 < diagnostics.CONNECT_TIMEOUT_S < diagnostics.TIMEOUT_S == provider.TIMEOUT_S
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    await client.check()
    await client.send_message(sms())
    for request in mock.requests:
        assert request.extensions["timeout"] == {"connect": diagnostics.CONNECT_TIMEOUT_S, "read": 15.0, "write": 15.0,
                                                 "pool": 15.0}


@pytest.mark.parametrize(("status", "exc_type", "code", "maybe_sent"), [
    (401, httpx.ReadError, "bad_key", False), (400, httpx.ReadTimeout, "bad_request", False),
    (403, httpx.RemoteProtocolError, "bad_account", False), (429, httpx.ReadError, "rate_limited", False),
    (409, httpx.ReadError, "bad_request", True), (500, httpx.ReadError, "server", True),
    (201, httpx.ReadError, "network", True), (200, httpx.ReadTimeout, "timeout", True),
])
async def test_reply_that_breaks_off_in_the_body_is_judged_by_its_status(status, exc_type, code, maybe_sent):
    mock = KatMock(override=body_then(status, b'{"code": "unau', exc_type))
    client = KatClient(CONN, transport=mock)
    sent = await failure(client.send_message(sms()))
    assert (sent.code, sent.http_status, sent.maybe_sent) == (code, status, maybe_sent)
    asked = await failure(client.check())
    assert (asked.http_status, asked.maybe_sent) == (status, False) and leaks(*everything_in(sent)) == []


async def test_httpx_reads_the_request_body_only_after_it_has_connected():
    """「나갔는가」를 요청 본문을 읽기 시작했는가로 정하는 근거를 httpx 실제 전송으로 확인한다(내 컴퓨터 안 127.0.0.1 만 —
    그곳은 표시 없이도 열려 있다). 연결이 안 되면 본문에 손대지 않고, 연결된 뒤에야 본문을 읽는다."""
    pulled: list[str] = []

    async def body(label: str):
        pulled.append(label)
        yield b"{}"

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)  # 받기만 하고 답하지 않는다
        await asyncio.sleep(1)
        writer.close()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    closed = await asyncio.start_server(silent, "127.0.0.1", 0)
    closed_port = closed.sockets[0].getsockname()[1]
    closed.close()
    await closed.wait_closed()
    headers = {"Content-Length": "2"}
    async with server, httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(0.3)) as http:
        with pytest.raises(httpx.ConnectError):
            await http.post(f"http://127.0.0.1:{closed_port}/", content=body("refused"), headers=headers)
        assert pulled == []  # 연결 전에는 본문을 읽지 않는다
        with pytest.raises(httpx.ReadTimeout):
            await http.post(f"http://127.0.0.1:{port}/", content=body("connected"), headers=headers)
        assert pulled == ["connected"]


async def test_whole_call_is_bounded_by_the_time_limit(monkeypatch):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    monkeypatch.setattr(provider, "TIMEOUT_S", 0.05)
    e = await failure(KatClient(CONN, transport=httpx.MockTransport(slow)).send_message(sms()))
    assert (e.code, e.maybe_sent) == ("timeout", True)


async def test_cancelled_send_propagates_cancellation():
    """끊긴 보내기는 ProviderFailed 가 아니다 — 부른 쪽이 「보냈는지 모름」으로 다뤄야 한다(모듈 머리 글)."""
    started = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(5)
        return httpx.Response(201, json={"messageId": "MG1"})

    task = asyncio.ensure_future(KatClient(CONN, transport=httpx.MockTransport(slow)).send_message(sms()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── 실패 코드 ───────────────────────────────────────────────────────


async def test_401_is_bad_key_without_key_in_message():
    mock = KatMock(override=answer(401, {"error": f"invalid {ECHO}", "code": SENTINEL_KEY}))
    e = await failure(KatClient(CONN, transport=mock).check())
    assert e.code == "bad_key" and e.http_status == 401
    assert SENTINEL_KEY not in e.message and leaks(*everything_in(e)) == []


@pytest.mark.parametrize(("status", "vendor_code", "call", "expected"), [
    (403, "forbidden", "check", "bad_account"),
    (403, "overseas_ip_blocked", "send", "overseas_ip"),
    (404, "not_found", "check", "bad_account"),  # 계정 경로뿐인 주소가 없다 → Account ID·기본 주소
    (404, "not_found", "send", "bad_account"),
    (404, "not_found", "status", "bad_request"),  # 그 메시지가 없다
    (404, "not_found", "call", "bad_request"),
    (400, "from_not_registered", "send", "bad_sender"),
    (400, "invalid_phone", "send", "bad_request"),
    (400, "INVALID_PHONE_NUMBER", "send", "bad_request"),
    (422, "quota_exceeded", "send", "bad_request"),
    (422, "recipient_blocked", "send", "bad_request"),
    (429, "rate_limited", "send", "rate_limited"),
    (503, None, "received", "server"),
    (418, "teapot", "check", "bad_request"),
])
async def test_http_errors_map_to_codes(status, vendor_code, call, expected):
    mock = KatMock(override=answer(status, {"error": ECHO, "code": vendor_code}))
    client = KatClient(CONN, transport=mock)
    calls = {"check": client.check, "send": lambda: client.send_message(sms()),
             "status": lambda: client.message_status("MG000001abcdef"),
             "received": lambda: client.received(None), "call": lambda: client.call_info("CA000001")}
    e = await failure(calls[call]())
    assert (e.code, e.http_status) == (expected, status)
    assert e.maybe_sent is False and e.retry_after_s is None
    assert len(mock.requests) == 1 and leaks(*everything_in(e)) == []
    assert any("가" <= ch <= "힣" for ch in e.message)  # 한국어


async def test_overseas_ip_has_its_own_code_and_says_korean_addresses_only():
    mock = KatMock(override=answer(403, {"error": "x", "code": "overseas_ip_blocked", "ip": "203.0.113.9"}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert e.code == "overseas_ip" and "한국" in e.message and "IP" in e.message and "203.0.113.9" not in e.message


@pytest.mark.parametrize(("header", "expected"), [("30", 30), ("0", 0), ("9999", 600), (" 12 ", 12), (None, None),
                                                  ("99999999999", 600), ("9" * 5000, 600),  # 터무니없는 값도 600 으로
                                                  ("soon", None), ("-5", None), ("1.5", None),
                                                  ("Wed, 21 Oct 2026 07:28:00 GMT", None), (ECHO, None)])
async def test_429_keeps_retry_after_seconds_capped(header, expected):
    headers = {} if header is None else {"retry-after": header}
    mock = KatMock(override=answer(429, {"code": "rate_limited"}, headers=headers))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert (e.code, e.retry_after_s) == ("rate_limited", expected) and leaks(*everything_in(e)) == []
    other = KatMock(override=answer(503, {"code": "x"}, headers={"retry-after": "30"}))
    assert (await failure(KatClient(CONN, transport=other).check())).retry_after_s is None  # 429 에만


async def test_known_vendor_codes_get_their_own_message_and_unknown_ones_are_named():
    client = KatClient(CONN, transport=KatMock(override=answer(422, {"error": "x", "code": "quota_exceeded"})))
    assert "한도" in (await failure(client.send_message(sms()))).message
    client = KatClient(CONN, transport=KatMock(override=answer(422, {"error": "x", "code": "brand_new_code"})))
    assert "brand_new_code" in (await failure(client.send_message(sms()))).message


async def test_vendor_error_code_is_repeated_only_when_it_is_a_plain_word():
    key = "katTESTkeyZZZZ9999"  # 코드처럼 생긴 키(글자·숫자뿐)
    conn = ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=key)
    odd = (key, key.upper(), key.lower(), SENTINEL_KEY, ECHO, f"x_{KAT_ACCOUNT}", 7, None, "a" * 41, f"to_{SENTINEL_DIGITS}",
           "code9", "with-dash", "")
    for vendor_code in odd:
        mock = KatMock(key=key, override=answer(422, {"error": ECHO, "code": vendor_code}))
        e = await failure(KatClient(conn, transport=mock).send_message(sms()))
        assert e.code == "bad_request" and "제공사 응답" not in e.message, vendor_code
        assert leaks(*everything_in(e)) == [] and not key_survives(e.message, key), vendor_code
    for vendor_code in ("Mixed_Case", "UPPER_CODE"):  # 대소문자 낱말은 옮긴다
        mock = KatMock(key=key, override=answer(422, {"error": ECHO, "code": vendor_code}))
        e = await failure(KatClient(conn, transport=mock).send_message(sms()))
        assert e.message.endswith(f"(제공사 응답: code={vendor_code})"), e.message
    lower = "kattestkeyzzzz"  # 소문자뿐인 키가 코드로 되돌아와도 옮기지 않는다
    mock = KatMock(key=lower, override=answer(422, {"code": lower}))
    e = await failure(KatClient(ProviderConn(KAT_BASE, KAT_ACCOUNT, lower), transport=mock).send_message(sms()))
    assert lower not in e.message


@pytest.mark.parametrize("vendor_code", ["QUOTA_EXCEEDED", "Quota_Exceeded", "quota_exceeded"])
async def test_documented_vendor_code_is_read_whatever_its_case(vendor_code):
    mock = KatMock(override=answer(422, {"error": "Monthly quota exceeded", "code": vendor_code}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert e.code == "bad_request" and "한도" in e.message and "제공사 응답" not in e.message
    assert diagnostics.http_failure(422, vendor_code) == diagnostics.VENDOR["quota_exceeded"]


async def failure_logged(caplog, override, conn: ProviderConn = CONN) -> tuple[ProviderFailed, str]:
    """보내기 실패 하나와 그 실패 로그 줄."""
    caplog.set_level(logging.WARNING, logger="app.outreach.provider")
    caplog.clear()
    e = await failure(KatClient(conn, transport=KatMock(key=conn.key, override=override)).send_message(sms()))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("제공사 호출 실패")]
    assert len(lines) == 1, lines
    return e, lines[0]


async def test_unknown_rejection_keeps_the_code_and_plain_error_text(caplog):
    e, line = await failure_logged(caplog, answer(422, {"error": "Sender is not allowed.", "code": "brand_new_code"}))
    shape = "code=brand_new_code; error=Sender is not allowed."
    assert e.message == f"{diagnostics.MESSAGES['bad_request']}(제공사 응답: {shape})"
    assert line.endswith(f"status=422 maybe_sent=False 응답={shape}")


async def test_validation_body_gives_field_names_and_types_but_no_values(caplog):
    detail = [{"loc": ["body", "To"], "msg": f"bad {SENTINEL_PHONE}", "type": "missing", "input": ECHO},
              {"loc": ["body", 0, "Type"], "msg": "x", "type": "literal_error", "input": "secretvalue"},
              {"loc": ["body", SENTINEL_KEY], "type": "value_error"},  # 꼴이 안 맞는 이름은 뺀다
              {"loc": "body", "type": 7}]
    e, line = await failure_logged(caplog, answer(422, {"detail": detail}))
    shape = "fields=body.To,body.Type; types=missing,literal_error,value_error"
    assert e.message.endswith(f"(제공사 응답: {shape})") and line.endswith(f"응답={shape}")
    for text in (e.message, line):
        assert leaks(text) == [] and "secretvalue" not in text and "msg" not in text and "input" not in text
    many = {"errors": [{"field": f"field_{chr(97 + i)}", "message": ECHO} for i in range(8)]}
    e, _ = await failure_logged(caplog, answer(400, many))
    assert e.message.endswith("(제공사 응답: fields=field_a,field_b,field_c,field_d,field_e)") and leaks(e.message) == []


@pytest.mark.parametrize(("error", "shown"), [
    ("Sender is not allowed.", "Sender is not allowed."),
    ("Invalid recipient: " + SENTINEL_PHONE, "Invalid recipient"),  # 첫 「:」 뒤는 자른다
    (f"Recipient {SENTINEL_PHONE} is blocked", None),  # 번호를 가린 표시도 ASCII 밖이라 통째로 뺀다
    (f"Recipient {SENTINEL_DIGITS} is blocked", None),
    ("Sender kim.cheolsu is not allowed", None),  # 낱말 속 「.」「@」는 이름·주소일 수 있다
    ("Contact ops@example is blocked", None),
    ("받는 사람 박현장 님 내일 타설 확인 부탁드립니다", None),  # 우리 글이 되돌아와도 옮기지 않는다
    ("Limit of 500 per day reached", None),  # 숫자가 남으면 뺀다
    ("x" * 61, None),  # 너무 길면 뺀다
    ("line one\nline two", None),
])
async def test_error_text_is_kept_only_when_short_plain_ascii(caplog, error, shown):
    e, line = await failure_logged(caplog, answer(422, {"error": error, "code": "odd_code"}))
    shape = "code=odd_code" + (f"; error={shown}" if shown else "")
    assert e.message.endswith(f"(제공사 응답: {shape})") and line.endswith(f"응답={shape}")
    assert e.shape == shape and leaks(e.message, line) == []
    assert "kim" not in e.message and "박현장" not in e.message


async def test_key_or_account_echoed_in_the_rejection_never_shows(caplog):
    key = "kattestkeyzzzz"  # 글자뿐인 키 — 꼴만으로는 걸러지지 않는다
    conn = ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=key)
    body = {"error": f"Bad key {key}", "code": key, "detail": [{"loc": ["body", key], "type": key}],
            "errors": [{"field": key}], "account": KAT_ACCOUNT, "request": {"To": SENTINEL_DIGITS, "Body": "내일"}}
    e, line = await failure_logged(caplog, answer(422, body), conn)
    assert e.message == diagnostics.MESSAGES["bad_request"]
    for text in (e.message, line, *map(str, everything_in(e))):
        assert not key_survives(text, key) and leaks(text) == [] and "내일" not in text


@pytest.mark.parametrize(("content", "content_type"), [
    (f"<html>Unprocessable {SENTINEL_PHONE} {SENTINEL_KEY}</html>".encode(), "text/html"),
    (b"[\"code\", \"quota\"]", "application/json"), (b"", "application/json"), (b"\xff\xfe", "application/json")])
async def test_unreadable_rejection_body_adds_nothing(caplog, content, content_type):
    e, line = await failure_logged(caplog, raw(422, content, content_type))
    assert e.message == diagnostics.MESSAGES["bad_request"] and line.endswith("maybe_sent=False")
    assert leaks(e.message, line) == []


@pytest.mark.parametrize(("body", "content_type"), [(b"<html>ok</html>", "text/html"), (b"[1, 2]", "application/json"),
                                                    (b"", "application/json"), (b"\xff\xfe", "application/json")])
async def test_unreadable_success_body_is_unknown(body, content_type):
    e = await failure(KatClient(CONN, transport=KatMock(override=raw(203, body, content_type))).check())
    assert e.code == "unknown" and e.http_status == 203  # 받은 상태 그대로


async def test_redirect_is_not_followed():
    mock = KatMock(override=answer(302, headers={"location": f"https://elsewhere.invalid/steal?{ECHO}"}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert e.code == "bad_request" and e.http_status == 302
    assert len(mock.requests) == 1 and mock.requests[0].url.host == "api.koreaaitel.com"
    assert leaks(*everything_in(e)) == []


# ── 요청 전에 막는 것 ──────────────────────────────────────────────


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1", "http://api.koreaaitel.com", "https://localhost", "https://127.0.0.1:8443", "https://10.0.0.5",
    "https://169.254.169.254", "https://[::1]", f"https://{SENTINEL_KEY}@api.koreaaitel.com", "ftp://api.koreaaitel.com",
    "", "not a url",
    # 주소는 scheme·호스트·포트뿐 — 뒤에 붙는 /v1/accounts/… 가 질의·조각 속으로 들어가지 않게(진단과 같은 검사)
    "https://api.koreaaitel.com?x=", "https://api.koreaaitel.com#", "https://api.koreaaitel.com/proxy?u=",
    "https://api.koreaaitel.com/a/../b", "https://api.koreaaitel.com/v1", " https://api.koreaaitel.com",
    "https://api.koreaaitel.com ", "https://api.koreaaitel.com%20", "https://evil.example\\.koreaaitel.com",
    "https://api.koreaaitel.com;evil.example", "https://evil.example,api.koreaaitel.com", "https://a&b.example",
    "https://a=b.example",
])
async def test_internal_base_url_is_refused(base_url, no_provider_dns):
    mock = KatMock()
    client = KatClient(ProviderConn(base_url=base_url, account_id=KAT_ACCOUNT, key=SENTINEL_KEY), transport=mock)
    for call in (client.check(), client.send_message(sms()), client.received(None)):
        e = await failure(call)
        assert e.code == "bad_request" and e.maybe_sent is False and leaks(*everything_in(e)) == []
    assert mock.requests == [] and no_provider_dns == []  # 요청 0번, 이름도 풀지 않았다


async def test_base_url_with_trailing_slash_or_port_is_used_as_is():
    for base, expected in ((f"{KAT_BASE}/", f"{KAT_BASE}/v1/accounts/{KAT_ACCOUNT}/sender-numbers"),
                           (f"{KAT_BASE}:8443", f"{KAT_BASE}:8443/v1/accounts/{KAT_ACCOUNT}/sender-numbers")):
        mock = KatMock()
        await KatClient(ProviderConn(base_url=base, account_id=KAT_ACCOUNT, key=SENTINEL_KEY), transport=mock).check()
        assert str(mock.requests[0].url) == expected


async def test_host_that_resolves_inside_is_refused(monkeypatch):
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    monkeypatch.setattr(provider, "RESOLVE", lambda host, port: ["93.184.216.34", "10.0.0.7"])
    e = await failure(client.send_message(sms()))
    assert e.code == "bad_request" and mock.requests == []

    def broken(host: str, port: int) -> list[str]:
        raise OSError(f"no such host {ECHO}")

    monkeypatch.setattr(provider, "RESOLVE", broken)
    e = await failure(client.send_message(sms()))
    assert e.code == "network" and e.maybe_sent is False and mock.requests == [] and leaks(*everything_in(e)) == []


@pytest.mark.parametrize(("key", "account", "code"), [
    ("", KAT_ACCOUNT, "bad_key"), ("short", KAT_ACCOUNT, "bad_key"), ("kat-test-key-한글ZZZZ", KAT_ACCOUNT, "bad_key"),
    ("kat-test-key\r\nX-Evil: 1", KAT_ACCOUNT, "bad_key"),
    (SENTINEL_KEY, "", "bad_account"), (SENTINEL_KEY, "AC1", "bad_account"), (SENTINEL_KEY, "AC0000\n0000", "bad_account"),
])
async def test_unusable_key_or_account_is_refused(key, account, code):
    mock = KatMock()
    e = await failure(KatClient(ProviderConn(base_url=KAT_BASE, account_id=account, key=key), transport=mock).check())
    assert e.code == code and mock.requests == []
    assert key == "" or key not in e.message


async def test_account_id_cannot_climb_out_of_its_path_segment():
    mock = KatMock(override=answer(200, {"senderNumbers": []}))
    client = KatClient(ProviderConn(base_url=KAT_BASE, account_id="../../admin?x=", key=SENTINEL_KEY), transport=mock)
    await client.check()
    assert mock.requests[0].url.raw_path == b"/v1/accounts/..%2F..%2Fadmin%3Fx%3D/sender-numbers"


async def test_message_id_is_one_path_segment():
    mock = KatMock()
    await failure(KatClient(CONN, transport=mock).message_status("../sender-numbers"))
    assert mock.requests[0].url.raw_path == f"/v1/accounts/{KAT_ACCOUNT}/messages/..%2Fsender-numbers".encode()
    for bad in ("", None):
        e = await failure(KatClient(CONN, transport=mock).message_status(bad))
        assert e.code == "bad_request"
    assert len(mock.requests) == 1


# ── 시험에서는 실제 전송으로 나갈 수 없다 ──────────────────────────


@pytest.fixture
def below_httpx(monkeypatch) -> list:
    """httpx 전송 아래(httpcore 연결 묶음)에 닿은 요청을 적는다 — 막이가 그 위에서 끊는지 보려고. 닿아도 나가지 않는다."""
    reached: list = []

    async def aconnect(self, request):
        reached.append(request)
        raise httpcore.ConnectError("blocked by the test")

    def connect(self, request):
        reached.append(request)
        raise httpcore.ConnectError("blocked by the test")

    monkeypatch.setattr(httpcore.AsyncConnectionPool, "handle_async_request", aconnect)
    monkeypatch.setattr(httpcore.ConnectionPool, "handle_request", connect)
    return reached


async def test_client_without_a_mock_transport_cannot_send_under_tests(below_httpx):
    client = provider.client_for(row())  # fake_provider 를 잊은 시험
    assert isinstance(client, KatClient)
    for call in (client.check(), client.send_message(sms()), client.received(None)):
        with pytest.raises(RealProviderCall, match="KatMock"):  # ProviderFailed 로 바뀌지 않고 그대로 올라온다
            await call
    assert not issubclass(RealProviderCall, Exception) and below_httpx == []


async def test_diagnostics_cannot_send_under_tests_however_the_client_was_made(below_httpx):
    from app.notify.diagnostics import (
        make_client,  # 모듈 속성이 아니라 이름으로 잡아 둔 것
    )

    conn = diagnostics.DiagnosticConn(KAT_BASE, SENTINEL_KEY, KAT_ACCOUNT)
    async with make_client() as http:
        with pytest.raises(RealProviderCall):
            await diagnostics.run_checks(conn, http, steps=(1,))
    async with httpx.AsyncClient(trust_env=False) as http:  # 손으로 만든 클라이언트
        with pytest.raises(RealProviderCall):
            await diagnostics.run_checks(conn, http, steps=(1,))
    with httpx.Client() as http, pytest.raises(RealProviderCall):  # 동기 클라이언트도
        http.get("https://example.invalid/")
    assert below_httpx == []


async def test_diagnostics_dns_is_faked_under_tests(no_provider_dns):
    assert diagnostics.RESOLVE is not diagnostics._system_resolve
    fake = KatMock()
    async with diagnostics.make_client(transport=fake) as http:
        steps = await diagnostics.run_checks(diagnostics.DiagnosticConn(KAT_BASE, SENTINEL_KEY, KAT_ACCOUNT), http, steps=(1,))
    assert steps[0].ok and no_provider_dns == ["api.koreaaitel.com"]  # resolve= 를 주지 않아도 시스템 DNS 가 아니다


OUTSIDE = "192.0.2.1"  # 문서용 주소(TEST-NET-1)


@pytest.fixture
def real_sockets_marked(monkeypatch) -> list:
    """막이 아래의 진짜 소켓 함수 자리에 표식을 둔다 — 막이가 듣지 않아도 아무것도 나가지 않고, 닿은 것이 적힌다."""
    assert socket.socket.connect is provider_doubles.guarded_connect  # 막이가 걸려 있을 때만 아래를 해 본다
    assert socket.socket.connect_ex is provider_doubles.guarded_connect_ex
    assert socket.getaddrinfo is provider_doubles.guarded_getaddrinfo
    reached: list = []

    def marker(*args, **kwargs):
        reached.append(args)
        raise OSError("표식: 막이를 지나 진짜 소켓 함수에 닿았다")

    for name in ("connect", "connect_ex", "getaddrinfo"):
        monkeypatch.setitem(provider_doubles.REAL_SOCKET, name, marker)
    return reached


def test_no_library_can_reach_beyond_this_computer_under_tests(real_sockets_marked):
    """소켓 층의 막이: 어떤 라이브러리로든 내 컴퓨터 밖으로 붙거나 이름을 풀 수 없다(표시로도 풀 수 없다)."""
    def raw(method: str):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            getattr(s, method)((OUTSIDE, 80))

    attempts = {
        "connect": lambda: raw("connect"), "connect_ex": lambda: raw("connect_ex"),
        "create_connection": lambda: socket.create_connection((OUTSIDE, 80), timeout=1),
        "getaddrinfo": lambda: socket.getaddrinfo("example.invalid", 443),
        "getaddrinfo bytes": lambda: socket.getaddrinfo(b"example.invalid", 443),
        "urllib": lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://{OUTSIDE}/", timeout=1),
        "httpcore": lambda: httpcore.ConnectionPool().request("GET", f"http://{OUTSIDE}/"),
    }
    for name, attempt in attempts.items():
        with pytest.raises(RealProviderCall):
            attempt()
        assert real_sockets_marked == [], name
    with pytest.raises(OSError, match="표식"):  # 내 컴퓨터 안은 막이를 지나간다(여기서는 표식에 닿는다)
        socket.create_connection(("127.0.0.1", 9), timeout=1)
    with pytest.raises(OSError, match="표식"):
        socket.getaddrinfo("localhost", 80)
    assert len(real_sockets_marked) == 2


async def test_async_libraries_cannot_reach_beyond_this_computer_either(real_sockets_marked):
    """음성 SDK 가 쓰는 aiohttp, asyncio 스트림, 실제 전송을 물려받아 고친 httpx 전송 — httpx 막이가 못 덮는 길들."""
    aiohttp = pytest.importorskip("aiohttp")

    async def with_aiohttp():
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=1)) as http:
            await http.get(f"http://{OUTSIDE}/")

    class Reworked(httpx.AsyncHTTPTransport):  # 막이가 바꿔 둔 메서드를 다시 정의한 전송
        async def handle_async_request(self, request):
            return await self._pool.handle_async_request(httpcore.Request(request.method, str(request.url)))

    async def with_subclass():
        async with httpx.AsyncClient(transport=Reworked(), trust_env=False) as http:
            await http.get(f"http://{OUTSIDE}/")

    for attempt in (with_aiohttp, with_subclass, lambda: asyncio.open_connection(OUTSIDE, 80),
                    lambda: asyncio.get_running_loop().getaddrinfo("example.invalid", 443)):
        with pytest.raises(BaseException) as caught:
            await asyncio.wait_for(attempt(), 5)
        stopped = caught.value  # anyio(httpcore)는 태스크 묶음의 예외로 싸서 올린다 — 그래도 Exception 은 아니다
        assert isinstance(stopped, RealProviderCall) or stopped.subgroup(RealProviderCall) is not None
        assert not isinstance(stopped, Exception)
    assert real_sockets_marked == []


_AT_IMPORT: list = []
try:  # 시험 몸통 밖(모듈을 불러올 때)에도 막이가 걸려 있는가 — 걸려 있지 않으면 해 보지 않는다
    if socket.getaddrinfo is provider_doubles.guarded_getaddrinfo:
        socket.getaddrinfo("example.invalid", 443)
except RealProviderCall:
    _AT_IMPORT.append("refused")


@pytest.fixture(scope="module")
def outside_a_test_body() -> list:
    seen = list(_AT_IMPORT)
    try:
        if socket.getaddrinfo is provider_doubles.guarded_getaddrinfo:
            socket.getaddrinfo("example.invalid", 443)
    except RealProviderCall:
        seen.append("refused")
    return seen


def test_socket_guard_is_on_for_the_whole_run_not_per_test(outside_a_test_body, request):
    assert outside_a_test_body == ["refused", "refused"]  # 불러올 때 · 모듈 범위 고정물에서
    assert not any(line.startswith("real_http") for line in request.config.getini("markers"))  # 푸는 표시는 없다


async def test_loopback_passes_both_guards_without_a_marker():
    """내 컴퓨터 안(127.0.0.1)의 시험 서버에는 표시 없이 닿는다 — httpx 실제 전송으로도."""
    async def hello(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(hello, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server, httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(2)) as http:
        assert (await http.get(f"http://127.0.0.1:{port}/")).text == "ok"


def test_no_transport_means_the_real_one_and_only_the_guard_stops_it():
    assert provider._default_transport() is None and KatClient(CONN)._transport is None
    assert not httpx.AsyncHTTPTransport.handle_async_request.__module__.startswith("httpx")  # 막이가 걸려 있다


# ── 로그·되돌려 주는 값 ────────────────────────────────────────────


async def test_no_key_phone_or_account_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    mock.add_inbound(SENTINEL_DIGITS, f"회신 {ECHO}", T0)
    mock.add_call("CA000001")
    await client.check()
    accepted = await client.send_message(sms(body=f"연락처 {SENTINEL_PHONE}"))
    mock.set_status(accepted.provider_id, "failed", "invalid_number", ECHO)
    await client.message_status(accepted.provider_id)
    await client.received(None)
    await client.call_info("CA000001")
    for override in (answer(401, {"error": ECHO, "code": ECHO}), answer(500, {"error": ECHO}), raising(httpx.ConnectError),
                     raising(httpx.ReadTimeout), raising(RuntimeError), answer(200, {"messageId": SENTINEL_KEY}),
                     answer(201, {"messageId": SENTINEL_PHONE}), page([{**GOOD, "from": ECHO, "dateCreated": ECHO}]),
                     answer(302, headers={"location": f"https://elsewhere.invalid/?{ECHO}"})):
        mock.override = override
        await failure(client.send_message(sms()))
        await failure(client.check())
    lines = [r.getMessage() for r in caplog.records]
    assert any(r.name == "httpx" and "/v1/accounts/" in r.getMessage() for r in caplog.records)  # 요청 줄이 잡혔다
    assert any(r.name == "app.outreach.provider" for r in caplog.records)  # 실패 줄이 잡혔다
    assert_clean(caplog, KAT_ACCOUNT)
    assert leaks(*lines) == []


async def test_new_client_registers_its_key_and_account_with_the_log_filter(caplog):
    key, account = "kat-test-key-UNIQ0001", "AC0000000000uniq"
    log = logging.getLogger("app.outreach.elsewhere")
    log.warning("before key=%s account=%s", key, account)
    KatClient(ProviderConn(base_url=KAT_BASE, account_id=account, key=key), transport=KatMock())
    log.warning("after key=%s account=%s", key, account)
    before, after = (r.getMessage() for r in caplog.records)
    assert key in before  # 시험이 뜻이 있으려면: 등록 전에는 남는다
    assert key not in after and account not in after and after.startswith("after key=")


async def test_registered_secrets_survive_another_caller_installing_its_own_source(caplog, monkeypatch):
    """다른 모듈이 redact.install 로 제 비밀 목록을 걸어도, 이미 만든 클라이언트의 요청 줄에서 Account ID 가 지워진다."""
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)  # 이 시험이 건 것을 되돌린다
    caplog.set_level(logging.INFO)
    key, account = "kat-test-key-KEEP0002", "AC0000000000keep"
    mock = KatMock(key=key, account=account)
    client = KatClient(ProviderConn(base_url=KAT_BASE, account_id=account, key=key), transport=mock)
    redact.install(lambda: ["some-other-module-secret-1234"])
    await client.check()
    request_lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert request_lines and all("/v1/accounts/" in line for line in request_lines)
    assert not any(account in line or key in line for line in request_lines)
    logging.getLogger("app.outreach.elsewhere").warning("other=%s", "some-other-module-secret-1234")
    assert "some-other-module-secret-1234" not in caplog.records[-1].getMessage()  # 그쪽 것도 그대로 지워진다


async def test_traceback_with_local_variables_has_no_key():
    for override in (raising(httpx.ConnectError), raising(httpx.ReadTimeout), answer(500), answer(401)):
        e = await failure(KatClient(CONN, transport=KatMock(override=override)).send_message(sms()))
        text = "".join(traceback.TracebackException.from_exception(e, capture_locals=True).format())
        assert "send_message" in text and not key_survives(text, SENTINEL_KEY)
        assert SENTINEL_DIGITS not in text and "타설" not in text  # 보낼 본문(받는 번호·글)도 남지 않는다


async def test_vendor_echo_never_reaches_a_return_value():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    mock.override = answer(201, {"messageId": SENTINEL_KEY, "status": "queued"})
    e = await failure(client.send_message(sms()))  # 키를 id 로 돌려주면 받지 않는다
    assert (e.code, e.maybe_sent, e.http_status) == ("unknown", True, 201) and leaks(*everything_in(e)) == []

    mock.override = answer(200, {"messageId": "MG1", "status": "failed", "failureCode": SENTINEL_KEY, "failureMessage": ECHO})
    delivery = await client.message_status("MG1")
    assert delivery.state == "failed" and delivery.fail_code == "unknown" and leaks(delivery, asdict(delivery)) == []

    mock.override = page([
        {**GOOD, "messageId": SENTINEL_KEY},
        {**GOOD, "messageId": "MG2", "body": f"키는 {SENTINEL_KEY} 계정 {KAT_ACCOUNT}", "dateCreated": "2026-11-23T03:00:01Z"}])
    got = await client.received(None)
    assert [m.provider_id for m in got.items] == ["MG2"] and got.skipped == 1
    body = got.items[0].body
    assert SENTINEL_KEY not in body and KAT_ACCOUNT not in body and body.startswith("키는 ")

    mock.override = answer(200, {"senderNumbers": [{"number": ECHO, "status": "approved"}, {"number": 7, "status": "approved"},
                                                   {"number": "070-0000-0123", "status": "approved"}, "junk"]})
    assert (await client.check()).senders == [KAT_SENDER]


@pytest.mark.parametrize("message_id", [SENTINEL_PHONE, SENTINEL_DIGITS, "+82 10-0000-0199", "1588-0199", "031-200-0199", 123, None,
                                        "", "a b", "x" * 101, "..", "-_-", "."])
async def test_message_id_that_is_a_phone_number_or_not_an_id_is_refused(message_id):
    mock = KatMock(override=answer(201, {"messageId": message_id, "status": "queued"}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert (e.code, e.maybe_sent, e.http_status) == ("unknown", True, 201) and leaks(*everything_in(e)) == []
    mock = KatMock(override=page([{**GOOD, "messageId": message_id}, {**GOOD, "messageId": "MG7"}]))
    got = await KatClient(CONN, transport=mock).received(None)
    assert [m.provider_id for m in got.items] == ["MG7"] and got.skipped == 1  # 그 줄만 건너뛴다


@pytest.mark.parametrize("message_id", ["202611230000123", "1234567890123456789", "MG01000000199", "msg_01.a:b-c"])
async def test_ids_with_long_digit_runs_are_fine(message_id):
    mock = KatMock(override=answer(201, {"messageId": message_id, "status": "queued"}))
    assert (await KatClient(CONN, transport=mock).send_message(sms())).provider_id == message_id


def test_reprs_hide_key_account_numbers_and_text():
    client = KatClient(CONN, transport=KatMock())
    inbound = provider.Inbound(provider_id="MG1", from_number=SENTINEL_DIGITS, body=f"연락처 {SENTINEL_PHONE}", at=T0,
                               has_media=False, to_number=SENTINEL_DIGITS)
    check = provider.Check(ok=True, senders=[SENTINEL_DIGITS], latency_ms=3)
    got = Received(items=[inbound], fetched_at=NOW)
    assert leaks(CONN, client, sms(body=f"연락처 {SENTINEL_PHONE}"), inbound, check, got, str(CONN), f"{client}") == []
    assert "idem-0001" in repr(sms())  # 가릴 것이 아닌 칸은 보인다


# ── 읽는 양의 상한 ─────────────────────────────────────────────────


async def test_response_body_over_the_cap_is_not_read_to_the_end(monkeypatch):
    monkeypatch.setattr(provider, "MAX_BYTES", 2000)
    pulled = []

    async def endless():
        for i in range(500):
            pulled.append(i)
            yield b'{"pad": "' + b"a" * 990 if i == 0 else b"a" * 1000

    def stream(status: int):
        return lambda request: httpx.Response(status, content=endless(), headers={"content-type": "application/json"})

    mock = KatMock(override=stream(200))
    client = KatClient(CONN, transport=mock)
    e = await failure(client.received(None))
    assert (e.code, e.http_status, e.maybe_sent) == ("unknown", 200, False)
    assert len(pulled) < 10  # 500 조각을 다 읽지 않았다
    e = await failure(client.send_message(sms()))
    assert (e.code, e.http_status, e.maybe_sent) == ("unknown", 200, True)  # 2xx 인데 읽지 못함 — 보냈을 수 있다
    mock.override = stream(400)
    e = await failure(client.send_message(sms()))
    assert (e.code, e.http_status, e.maybe_sent) == ("bad_request", 400, False)  # 상태로 가른다

    fits = json.dumps({"senderNumbers": [], "pad": "a" * 1900}).encode()
    assert len(fits) <= 2000
    assert (await KatClient(CONN, transport=KatMock(override=raw(200, fits, "application/json"))).check()).senders == []


async def test_compressed_reply_is_refused_without_being_unpacked():
    packed = gzip.compress(b'{"messageId": "MG1", "pad": "' + b"a" * 50_000_000 + b'"}')
    pulled = []

    async def chunks():
        for i in range(0, len(packed), 4096):
            pulled.append(i)
            yield packed[i:i + 4096]

    def encoded(status: int, encoding: str = "gzip"):
        return lambda request: httpx.Response(status, content=chunks(), headers={"content-encoding": encoding})

    mock = KatMock(override=encoded(201))
    client = KatClient(CONN, transport=mock)
    sent = await failure(client.send_message(sms()))
    assert (sent.code, sent.http_status, sent.maybe_sent) == ("unknown", 201, True)
    assert mock.requests[0].headers["accept-encoding"] == "identity"  # 압축하지 말라고 청한다
    asked = await failure(client.check())
    assert (asked.code, asked.http_status, asked.maybe_sent) == ("unknown", 201, False)
    mock.override = encoded(400, "deflate")
    assert ((await failure(client.send_message(sms()))).code, len(pulled)) == ("bad_request", 0)  # 본문을 당기지도 않았다
    plain = KatMock(override=lambda r: httpx.Response(200, json={"senderNumbers": []}, headers={"content-encoding": "identity"}))
    assert (await KatClient(CONN, transport=plain).check()).senders == []

    mock = KatMock(override=encoded(200), limit=3)  # 받은 문자 쪽이 압축돼 오면 절반 크기로 다시 묻지 않는다(다시 물어도 같다)
    e = await failure(KatClient(CONN, transport=mock).received(T0))
    assert (e.code, e.http_status, len(mock.requests), len(pulled)) == ("unknown", 200, 1, 0)


async def test_inbound_body_is_capped_and_cleaned():
    hostile = "x\x00y\x1b[31mred\x07 \u202eevil\u2066 \r\n\tz\x7f"
    mock = KatMock(override=page([{**GOOD, "messageId": "L1", "body": "가" * 5000}, {**GOOD, "messageId": "L2", "body": hostile},
                                  {**GOOD, "messageId": "L3", "body": "가" * 4000}, {**GOOD, "messageId": "L4", "body": {"x": 1}},
                                  {**GOOD, "messageId": "L5", "body": "\x00" * 5000 + "끝"}]))
    got = {m.provider_id: m for m in (await KatClient(CONN, transport=mock).received(None)).items}
    assert (len(got["L1"].body), got["L1"].body_cut) == (provider.INBOUND_BODY_MAX, True)  # 4,000자에서 자르고 표시한다
    assert (got["L2"].body, got["L2"].body_cut) == ("xy[31mred evil \n\tz", False)  # 제어 글자·방향 덮어쓰기 글자를 뺀다
    assert (len(got["L3"].body), got["L3"].body_cut) == (4000, False)
    assert (got["L4"].body, got["L5"].body, got["L5"].body_cut) == ("", "끝", False)


@pytest.mark.parametrize(("given", "expected"), [
    ("ok \ud83d lone", "ok  lone"), ("\udc00앞 뒤\ud800", "앞 뒤"),  # 짝 없는 서로게이트(그대로 두면 DB 에 넣을 때 깨진다)
    ("웃음 \U0001f600 그대로", "웃음 \U0001f600 그대로"), ("가족 \U0001f468\u200d\U0001f469 사진", "가족 \U0001f468\u200d\U0001f469 사진"),
    ("1번\r2번\r3번", "1번\n2번\n3번"), ("a\r\nb\r\n", "a\nb\n"), ("a\u2028b\u2029c", "a\nb\nc"),  # 줄 나눔은 \n 하나로
    ("a\x9b31mred\x85b\x80", "a31mredb"), ("ok\U000e0041\U000e0042\U000e007f", "ok"), ("a\x0bb\x0cc", "abc"),
    ("việc xong · می\u200cخواهم", "việc xong · می\u200cخواهم"),  # 다른 말의 글자는 건드리지 않는다
])
async def test_inbound_text_is_made_safe_to_store(given, expected):
    mock = KatMock(override=page([{**GOOD, "body": given}]))
    body = (await KatClient(CONN, transport=mock).received(None)).items[0].body
    assert body == expected
    body.encode("utf-8")  # 저장할 수 있다


# ── 상태·받은 문자·발신번호·통화 ───────────────────────────────────


async def test_each_documented_status_word_reaches_the_caller_through_the_map(monkeypatch):
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    one = (await client.send_message(sms())).provider_id
    seen = {}
    for word in ("queued", "sent", "failed"):
        mock.set_status(one, word)
        seen[word] = (await client.message_status(one)).state
    assert seen == {"queued": "accepted", "sent": "delivered", "failed": "failed"}
    assert STATUS_MAP["received"] == "received" and set(STATUS_MAP) == {"queued", "sent", "failed", "received"}
    mock.set_status(one, "sent")
    monkeypatch.setitem(STATUS_MAP, "sent", "accepted")  # P3 실측이 「도착 아님」이면 이 한 줄만 바꾼다
    assert (await client.message_status(one)).state == "accepted"


async def test_status_and_received_are_parsed():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    one = (await client.send_message(sms())).provider_id
    two = (await client.send_message(sms(idempotency_key="idem-0002"))).provider_id
    assert asdict(await client.message_status(one)) == {"state": "accepted", "fail_code": None, "fail_text": None,
                                                        "fell_back": False}
    mock.set_status(one, "sent")
    assert (await client.message_status(one)).state == "delivered"
    mock.set_status(two, "failed", "handset_off", f"단말기 전원 꺼짐 {ECHO}")
    failed = await client.message_status(two)
    assert (failed.state, failed.fail_code) == ("failed", "handset_off")
    assert "전원" in failed.fail_text and leaks(failed.fail_text) == []  # 우리 표의 글 — 제공사 글을 옮기지 않는다
    assert failed.fell_back is False  # 문서 확인 필요: 대신 나간 문자를 원래 메시지에서 알 길이 문서에 없다
    assert mock.requests[-1].url.path == f"/v1/accounts/{KAT_ACCOUNT}/messages/{two}"

    mock.set_status(two, "failed", "some_new_code")
    newer = await client.message_status(two)
    assert newer.fail_code == "some_new_code" and "some_new_code" in newer.fail_text
    for odd in (None, f"n{SENTINEL_DIGITS}", "Some_Code", "code9", 7):  # 소문자 낱말이 아니면 옮기지 않는다
        mock.set_status(two, "failed", odd)
        plain = await client.message_status(two)
        assert plain.fail_code == "unknown" and plain.fail_text and leaks(plain) == []

    first = mock.add_inbound(SENTINEL_DIGITS, "네 알겠습니다", T0)
    second = mock.add_inbound("+82 10-0000-0188", "사진 보냅니다", T0 + timedelta(seconds=30), media=1)
    got = await client.received(None)
    assert isinstance(got, Received) and (got.truncated, got.skipped, got.redated, got.fetched_at) == (False, 0, 0, NOW)
    assert provider.SINCE_MARGIN_S == 600 and got.next_since == NOW - timedelta(minutes=10)  # 일꾼은 이 값을 다음 since 로
    assert [(m.provider_id, m.from_number, m.to_number, m.body, m.at, m.has_media, m.body_cut) for m in got.items] == [
        (first, SENTINEL_DIGITS, KAT_SENDER, "네 알겠습니다", T0, False, False),
        (second, "01000000188", KAT_SENDER, "사진 보냅니다", T0 + timedelta(seconds=30), True, False)]  # 오래된 것부터
    assert dict(mock.requests[-1].url.params) == {"status": "received", "pageSize": str(RECEIVED_PAGE_SIZE), "page": "0"}


@pytest.mark.parametrize("status", ["received", "sending", None, 7])
async def test_status_word_we_do_not_know_is_a_failure_not_a_guess(status):
    mock = KatMock(override=answer(200, {"messageId": "MG1", "status": status}))
    e = await failure(KatClient(CONN, transport=mock).message_status("MG1"))
    assert e.code == "unknown" and e.http_status == 200


async def test_received_keeps_only_since_and_later_and_stops_paging_at_older_rows():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    size = RECEIVED_PAGE_SIZE
    total, in_first_page, in_second_page = size + size // 2, size + size // 2 - size // 5, size // 5
    ids = [mock.add_inbound(SENTINEL_DIGITS, f"회신 {i}", T0 + timedelta(seconds=i)) for i in range(total)]
    mock.messages[(await client.send_message(sms())).provider_id]["dateCreated"] = "2026-11-23T03:05:00.000Z"  # 보낸 것은 받은 것이 아니다
    mock.requests.clear()

    since = T0 + timedelta(seconds=in_first_page)
    got = await client.received(since)
    assert [m.provider_id for m in got.items] == ids[in_first_page:]  # 같은 시각 것도 준다(겹침은 받는 쪽이 id 로 막는다)
    assert [r.url.params["page"] for r in mock.requests] == ["0"] and got.truncated is False  # 첫 쪽의 끝 줄이 since 보다 오래됐다

    mock.requests.clear()
    got = await client.received(T0 + timedelta(seconds=in_second_page))
    assert [m.provider_id for m in got.items] == ids[in_second_page:]
    assert [r.url.params["page"] for r in mock.requests] == ["0", "1"]

    naive = since.replace(tzinfo=None)  # DB 에서 읽은 시각(UTC, tz 없음)
    assert [m.provider_id for m in (await client.received(naive)).items] == ids[in_first_page:]

    mock.requests.clear()
    assert len((await client.received(None)).items) == size and len(mock.requests) == 1  # 처음에는 한 쪽만


def longest(i: int, url_chars: int = 40) -> dict:
    """가장 긴 문자(2,000자) 한 줄. 사진 주소 길이는 고를 수 있다."""
    return {**GOOD, "messageId": f"MG{i:06d}abcdef", "accountId": KAT_ACCOUNT, "subject": None, "body": "가" * 2000,
            "numMedia": 3, "mediaUrl": [f"https://media.invalid/{i}/{n}/" + "u" * url_chars for n in range(3)],
            "dateCreated": (T0 + timedelta(seconds=i)).isoformat().replace("+00:00", "Z")}


async def test_a_full_page_of_the_longest_texts_is_read_in_one_request():
    """쪽 크기는 응답 상한에 맞춘 값이다: 2,000자 문자가 \\uXXXX 꼴로 한 쪽 가득 와도 읽힌다."""
    mock = KatMock(override=page([longest(i) for i in range(RECEIVED_PAGE_SIZE)]))
    got = await KatClient(CONN, transport=mock).received(None)
    assert len(got.items) == RECEIVED_PAGE_SIZE and len(mock.requests) == 1 and got.skipped == 0
    assert all(len(m.body) == 2000 and m.has_media for m in got.items)


async def test_page_over_the_cap_is_read_again_in_halves():
    rows = [longest(i, url_chars=4500) for i in range(RECEIVED_PAGE_SIZE)]  # 사진 주소가 길어 한 쪽이 상한을 넘는다

    def listing(request: httpx.Request) -> httpx.Response:
        size, number = int(request.url.params["pageSize"]), int(request.url.params["page"])
        newest_first = rows[::-1]
        return page(newest_first[number * size:(number + 1) * size])(request)

    half = RECEIVED_PAGE_SIZE // 2
    whole = json.dumps({"data": rows[:RECEIVED_PAGE_SIZE]}).encode()
    assert len(whole) > provider.MAX_BYTES > len(json.dumps({"data": rows[:half]}).encode()) + 200
    mock = KatMock(override=listing)
    got = await KatClient(CONN, transport=mock).received(T0)
    asked = [(r.url.params["pageSize"], r.url.params["page"]) for r in mock.requests]
    assert asked == [(str(RECEIVED_PAGE_SIZE), "0"), (str(half), "0"), (str(half), "1"), (str(half), "2")]
    assert [m.provider_id for m in got.items] == [r["messageId"] for r in rows] and got.truncated is False


def always_over_the_cap(limit: int) -> KatMock:
    """무엇을 물어도 응답 상한을 넘는 본문을 주는 가짜. limit 번까지만 답한다(그 뒤는 RunawayFake) — 주는 양에 끝이 있다."""
    return KatMock(override=raw(200, b'{"data": [], "pad": "' + b"a" * provider.MAX_BYTES + b'"}', "application/json"),
                   limit=limit)


async def test_reply_that_is_always_over_the_cap_is_asked_for_only_twice():
    """2026-11-23: 이 고리가 끝나지 않아 시험 프로세스가 메모리 5GB 를 잡았다. 절반으로 한 번만 다시 읽고 그만둔다."""
    mock = always_over_the_cap(limit=RECEIVED_MAX_REQUESTS + 1)
    started = time.monotonic()
    e = await failure(KatClient(CONN, transport=mock).received(T0))
    assert (e.code, e.http_status) == ("unknown", 200)
    assert [r.url.params["pageSize"] for r in mock.requests] == [str(RECEIVED_PAGE_SIZE), str(RECEIVED_PAGE_SIZE // 2)]
    assert time.monotonic() - started < 5


async def test_received_never_asks_more_than_its_request_limit(monkeypatch):
    """멈춤 조건과 따로 요청 수에 굳은 상한이 있다(RECEIVED_MAX_REQUESTS) — 제대로 읽을 때는 닿지 않는다."""
    assert RECEIVED_MAX_REQUESTS >= RECEIVED_MAX_PAGES * 2 + 1
    mock = KatMock(limit=10)
    for i in range(RECEIVED_PAGE_SIZE * 2):
        mock.add_inbound(SENTINEL_DIGITS, "회신", T0 + timedelta(seconds=i))
    assert len((await KatClient(CONN, transport=mock).received(T0)).items) == RECEIVED_PAGE_SIZE * 2
    assert len(mock.requests) == 3  # 두 쪽 + 빈 쪽

    monkeypatch.setattr(provider, "RECEIVED_MAX_REQUESTS", 2)
    mock.requests.clear()
    e = await failure(KatClient(CONN, transport=mock).received(T0))
    assert e.code == "unknown" and len(mock.requests) == 2


async def test_fake_server_ends_a_caller_that_keeps_asking():
    """가짜는 limit 번까지만 받는다. 넘으면 RunawayFake — `except Exception` 으로 삼키는 호출 코드도 뚫고 올라온다."""
    mock = KatMock(limit=2)
    client = KatClient(CONN, transport=mock)
    await client.check()
    await client.check()
    with pytest.raises(RunawayFake):
        await client.check()
    assert len(mock.requests) == 2 and not issubclass(RunawayFake, Exception)


def test_time_limit_cuts_a_loop_that_does_not_end():
    """time_guard 가 쓰는 time_limit 은 스스로 멈추지 않는 고리를 끊는다. 고리도 2초로 묶여 있다(안 끊기면 실패로 끝난다)."""
    def spin(until: float) -> None:  # 따로 둔 함수: 고리의 되돌이 자리에서 난 끊김은 같은 함수의 try·with 를 건너뛴다
        while time.monotonic() < until:
            pass

    end, cut = time.monotonic() + 2, False
    try:
        with time_limit(0.05):
            spin(end)
    except KeyboardInterrupt:  # pytest.raises 는 KeyboardInterrupt 를 잡지 않는다
        cut = True
    assert cut and time.monotonic() < end


@pytest.mark.parametrize("sigint", ["as it is", signal.SIG_IGN])
def test_time_limit_cuts_a_test_that_only_waits(sigint):
    """기다리기만 하는 시험(막힌 시스템 호출)도 끊는다 — 진짜 신호를 보낸다. SIGINT 를 무시하게 띄운 실행(셸의 배경 작업)에서도.
    기다림은 3초로 묶여 있다."""
    before = signal.getsignal(signal.SIGINT)
    if sigint is signal.SIG_IGN:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    started, cut = time.monotonic(), False
    try:
        with time_limit(0.1):
            time.sleep(3)
    except KeyboardInterrupt:
        cut = True
    finally:
        after = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, before)
    assert cut and time.monotonic() - started < 2
    assert after is (signal.SIG_IGN if sigint is signal.SIG_IGN else before)  # 신호 처리기를 제자리에 돌려놓는다


async def test_time_limit_cuts_an_await_nobody_resolves():
    """아무도 풀어 주지 않는 await 도 끊는다(asyncio 는 신호를 받으면 그 태스크를 취소한다). 3초 뒤에는 스스로 풀린다."""
    never = asyncio.Event()
    release = asyncio.get_running_loop().call_later(3, never.set)
    started, cut = time.monotonic(), False
    try:
        with time_limit(0.1):
            await never.wait()
    except asyncio.CancelledError:
        asyncio.current_task().uncancel()  # 이 시험은 끊긴 것을 확인하고 이어 간다
        cut = True
    finally:
        release.cancel()
    assert cut and time.monotonic() - started < 2


async def test_reply_with_more_rows_than_asked_is_cut_to_the_page_size():
    """pageSize 를 듣지 않는 제공사가 한 응답에 몇 쪽 분량을 실어 보내도 청한 만큼만 읽고, 버린 줄이 있음을 알린다."""
    rows = [{**GOOD, "messageId": f"M{i}", "dateCreated": (T0 + timedelta(hours=1, seconds=-i)).isoformat().replace("+00:00", "Z")}
            for i in range(RECEIVED_PAGE_SIZE * 3)]  # 최신순
    mock = KatMock(override=page(rows), limit=RECEIVED_MAX_REQUESTS)
    got = await KatClient(CONN, transport=mock).received(None)
    assert [m.provider_id for m in got.items] == [f"M{i}" for i in range(RECEIVED_PAGE_SIZE)][::-1]  # 앞(최신) 한 쪽만
    assert (got.truncated, got.skipped, len(mock.requests)) == (True, 0, 1)

    exact = KatMock(override=page(rows[:RECEIVED_PAGE_SIZE]), limit=3)
    assert (await KatClient(CONN, transport=exact).received(None)).truncated is False  # 딱 한 쪽이면 버린 것이 없다


async def test_paging_stops_on_the_last_row_of_a_page_not_on_any_older_row():
    """쪽이 꼭 최신순이 아니어도(오래된 줄 하나가 앞에 끼어도) 다음 쪽의 새 줄을 놓치지 않는다."""
    since = datetime(2026, 11, 23, 2, 0, tzinfo=UTC)
    full = RECEIVED_PAGE_SIZE - 1  # 오래된 줄 하나와 함께 한 쪽을 꼭 채운다(청한 쪽 크기를 넘는 줄은 버려진다)
    first = [{**GOOD, "messageId": "OLD", "dateCreated": "2026-11-20T00:00:00Z"}] + [
        {**GOOD, "messageId": f"N{i}", "dateCreated": f"2026-11-23T03:{i // 60:02d}:{i % 60:02d}Z"} for i in range(full)]
    second = [{**GOOD, "messageId": f"P{i}", "dateCreated": "2026-11-23T02:59:00Z"} for i in range(10)]
    mock = KatMock(override=lambda r: page(first if r.url.params["page"] == "0" else second)(r))
    got = await KatClient(CONN, transport=mock).received(since)
    assert [r.url.params["page"] for r in mock.requests] == ["0", "1"]
    assert len(got.items) == full + 10 and "OLD" not in {m.provider_id for m in got.items} and got.truncated is False

    # 끝 줄을 읽을 수 없으면 그 쪽에서 읽힌 마지막 줄로 정한다
    tail_broken = [{**GOOD, "messageId": f"Q{i}", "dateCreated": "2026-11-20T00:00:00Z"} for i in range(full)] + ["junk"]
    mock = KatMock(override=page(tail_broken))
    got = await KatClient(CONN, transport=mock).received(since)
    assert len(mock.requests) == 1 and got.items == [] and got.skipped == 1


async def test_received_stops_at_the_page_limit_and_says_so(caplog):
    mock = KatMock()
    for i in range(RECEIVED_PAGE_SIZE * RECEIVED_MAX_PAGES + 5):
        mock.add_inbound(SENTINEL_DIGITS, "회신", T0 + timedelta(seconds=i))
    got = await KatClient(CONN, transport=mock).received(T0)
    assert len(mock.requests) == RECEIVED_MAX_PAGES and len(got.items) == RECEIVED_PAGE_SIZE * RECEIVED_MAX_PAGES
    assert got.truncated is True and got.items[0].at < got.items[-1].at  # 더 오래된 5건은 못 읽었다 — 부른 쪽이 안다
    assert any("쪽" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.parametrize("bad_date", ["0001-01-01T00:00:00+09:00", "9999-12-31T23:59:59-01:00", "어제", "", None, 1763866800,
                                      ["2026-11-23T03:00:00Z"], "2026-13-45T00:00:00Z"])
async def test_one_unreadable_date_skips_only_that_row(bad_date):
    mock = KatMock(override=page([GOOD, {**GOOD, "messageId": "MG2", "dateCreated": bad_date}]))
    got = await KatClient(CONN, transport=mock).received(T0 - timedelta(days=1))
    assert [m.provider_id for m in got.items] == ["MG1"] and got.skipped == 1


async def test_any_error_while_reading_one_row_skips_only_that_row(monkeypatch):
    real = provider._parse_inbound

    def flaky(item, secrets):
        if isinstance(item, dict) and item.get("messageId") == "MG2":
            raise ArithmeticError(f"boom {ECHO}")
        return real(item, secrets)

    monkeypatch.setattr(provider, "_parse_inbound", flaky)
    mock = KatMock(override=page([GOOD, {**GOOD, "messageId": "MG2"}, {**GOOD, "messageId": "MG3"}]))
    got = await KatClient(CONN, transport=mock).received(None)
    assert [m.provider_id for m in got.items] == ["MG1", "MG3"] and got.skipped == 1


async def test_received_skips_rows_it_cannot_read_and_duplicates():
    rows = [GOOD, dict(GOOD), {**GOOD, "messageId": "MG2", "direction": "outbound"}, {**GOOD, "messageId": None}, "junk",
            {**GOOD, "messageId": "MG3", "direction": ["inbound"]},
            {**GOOD, "messageId": "MG5", "body": None, "numMedia": 0, "mediaUrl": ["https://media.invalid/1.jpg"],
             "dateCreated": "2026-11-23T12:00:01+09:00"},
            {**GOOD, "messageId": "MG6", "numMedia": "3", "dateCreated": "2026-11-23T03:00:02"},
            {**GOOD, "messageId": "MG7", "numMedia": True, "mediaUrl": "x", "dateCreated": "2026-11-23T03:00:03Z"}]
    mock = KatMock(override=page(rows))
    got = await KatClient(CONN, transport=mock).received(None)
    assert [(m.provider_id, m.body, m.has_media) for m in got.items] == [
        ("MG1", "네", False), ("MG5", "", True), ("MG6", "네", False), ("MG7", "네", False)]  # 수·목록이 아닌 값은 사진으로 보지 않는다
    assert got.skipped == 4
    at = [m.at for m in got.items]
    assert at[0] == datetime(2026, 11, 23, 3, 0, 0, 123000, tzinfo=UTC) and at[1] == datetime(2026, 11, 23, 3, 0, 1, tzinfo=UTC)
    assert at[2] == datetime(2026, 11, 23, 3, 0, 2, tzinfo=UTC)  # tz 가 없으면 UTC 로 본다
    e = await failure(KatClient(CONN, transport=KatMock(override=answer(200, {"meta": {}}))).received(None))
    assert e.code == "unknown" and e.http_status == 200


@pytest.mark.parametrize(("given", "expected"), [
    (SENTINEL_PHONE, SENTINEL_DIGITS), ("+82 10-0000-0199", SENTINEL_DIGITS), ("1588-0199", "15880199"),
    ("+1 588 0199", "+15880199"),  # 나라 밖 번호는 국내 대표번호 15880199 와 같은 열쇠가 되지 않는다
    ("+1588-0199", "+15880199"), ("+1 (555) 123-4567", "+15551234567"), ("+44 20 7946 0958", "+442079460958"),
    ("+82 1588-0199", "15880199"), ("+8215880199", "15880199"),  # +82 가 붙은 대표번호는 국내 열쇠 그대로
    ("KB국민", phone.NO_NUMBER), ("114", phone.NO_NUMBER), ("#0100000019", phone.NO_NUMBER),
    ("(((((((((((0", phone.NO_NUMBER), ("", phone.NO_NUMBER), ("+", phone.NO_NUMBER), ("+12", phone.NO_NUMBER),
    ("+1234567890123456", phone.NO_NUMBER), ("+0 10 0000 0199", phone.NO_NUMBER),  # 0 으로 시작하는 나라 번호는 없다 (["01000000199"], phone.NO_NUMBER), (None, phone.NO_NUMBER), (0, phone.NO_NUMBER),
])
async def test_sender_and_receiver_numbers_of_an_inbound_text(given, expected):
    mock = KatMock(override=page([{**GOOD, "from": given, "to": given}]))
    got = await KatClient(CONN, transport=mock).received(None)
    assert [(m.from_number, m.to_number) for m in got.items] == [(expected, expected)] and got.skipped == 0


async def test_row_dated_in_the_future_gets_the_fetch_time_and_is_counted():
    def at(delta: timedelta) -> str:
        return (NOW + delta).isoformat().replace("+00:00", "Z")

    far = {**GOOD, "messageId": "F1", "dateCreated": "2099-01-01T00:00:00Z"}
    mock = KatMock(override=page([far, dict(far),  # 같은 줄이 두 번 와도 한 번만 센다
                                  {**GOOD, "messageId": "F2", "dateCreated": at(timedelta(minutes=5, seconds=1))},
                                  {**GOOD, "messageId": "F3", "dateCreated": at(timedelta(minutes=4))}, GOOD]))
    got = await KatClient(CONN, transport=mock).received(T0)
    times = {m.provider_id: m.at for m in got.items}
    assert times == {"MG1": T0.replace(microsecond=123000), "F1": NOW, "F2": NOW, "F3": NOW + timedelta(minutes=4)}
    assert (got.redated, got.fetched_at) == (2, NOW)  # 시계가 조금 다른 것(5분까지)은 그대로 둔다


async def test_check_returns_approved_senders_and_latency():
    mock = KatMock()
    check = await KatClient(CONN, transport=mock).check()
    assert check.ok is True and check.senders == [KAT_SENDER] and check.latency_ms >= 0  # 승인 대기 번호는 뺀다
    assert [(r.method, r.url.path) for r in mock.requests] == [("GET", f"/v1/accounts/{KAT_ACCOUNT}/sender-numbers")]
    mock.senders = [{"number": n, "status": "approved"} for n in ("+82 70-0000-0123", "1588-0199", "07000000123", "114", "9")]
    assert (await KatClient(CONN, transport=mock).check()).senders == [KAT_SENDER, "15880199", "114"]  # 저장된 꼴과 같은 열쇠
    e = await failure(KatClient(CONN, transport=KatMock(override=answer(200, {"grace": []}))).check())
    assert e.code == "unknown" and e.http_status == 200


async def test_call_info_returns_only_plain_documented_fields():
    mock = KatMock()
    mock.add_call("CA000001", transferReasonText=ECHO, recordingUrl=f"https://x.invalid/{KAT_ACCOUNT}/r.wav",
                  transfers=[{"to": SENTINEL_DIGITS}], surprise=SENTINEL_KEY)
    info = await KatClient(CONN, transport=mock).call_info("CA000001")
    assert mock.requests[0].url.path == f"/v1/accounts/{KAT_ACCOUNT}/calls/CA000001"
    assert info == {"callId": "CA000001", "status": "completed", "direction": "outbound", "duration": 42, "answeredBy": None,
                    "hangupCause": None, "hangupSource": "callee", "callerIdRestricted": None, "recording": False,
                    "dateCreated": "2026-11-02T00:00:00.000Z", "dateUpdated": "2026-11-02T00:00:42.000Z"}
    assert leaks(info, json.dumps(info, ensure_ascii=False)) == []


async def test_call_info_drops_values_of_the_wrong_shape():
    mock = KatMock()
    mock.add_call("CA1", status="in-progress", duration=int(SENTINEL_DIGITS), hangupCause="1588-0199 로 전환", answeredBy=1.5,
                  recording=f"https://x.invalid/rec/{SENTINEL_DIGITS}.wav", callerIdRestricted="yes", hangupSource=ECHO,
                  direction=SENTINEL_PHONE, dateCreated=ECHO, dateUpdated=SENTINEL_DIGITS)
    info = await KatClient(CONN, transport=mock).call_info("CA1")
    assert info == {"callId": "CA1", "status": "in-progress", "direction": None, "duration": None, "answeredBy": None,
                    "hangupCause": None, "hangupSource": None, "callerIdRestricted": None, "recording": None,
                    "dateCreated": None, "dateUpdated": None}
    mock.add_call("CA2", duration=True, hangupCause="no-answer", answeredBy="human", callerIdRestricted=True)
    info = await KatClient(CONN, transport=mock).call_info("CA2")
    assert (info["duration"], info["hangupCause"], info["answeredBy"], info["callerIdRestricted"]) == (None, "no-answer", "human", True)
    mock.add_call("CA4", dateCreated="0001-01-01T00:00:00+09:00", dateUpdated="9999-12-31T23:59:59-01:00")
    info = await KatClient(CONN, transport=mock).call_info("CA4")
    assert (info["dateCreated"], info["dateUpdated"]) == (None, None)  # 읽을 수 없는 시각 때문에 호출이 깨지지 않는다
    for call_id in (SENTINEL_PHONE, SENTINEL_KEY, 7):  # 번호·키 꼴의 id 는 받지 않는다
        mock.add_call("CA3", callId=call_id)
        e = await failure(KatClient(CONN, transport=mock).call_info("CA3"))
        assert e.code == "unknown" and e.http_status == 200 and leaks(*everything_in(e)) == []


# ── client_for · 가짜 ─────────────────────────────────────────────


async def test_client_for_decrypts_the_stored_key_and_calls_with_it(monkeypatch):
    mock = KatMock()
    monkeypatch.setattr(provider, "_default_transport", lambda: mock)
    client = provider.client_for(row())
    assert isinstance(client, KatClient) and client.conn == CONN
    await client.check()
    assert mock.requests[0].headers["authorization"] == f"Bearer {SENTINEL_KEY}"
    assert mock.requests[0].url.path == f"/v1/accounts/{KAT_ACCOUNT}/sender-numbers"


def test_client_for_with_unreadable_secret_is_bad_key():
    with pytest.raises(ProviderFailed) as caught:
        provider.client_for(row(secret_ciphertext="not-a-fernet-token"))
    assert caught.value.code == "bad_key" and "not-a-fernet-token" not in caught.value.message


async def test_fake_provider_replaces_client_for(fake_provider):
    assert isinstance(fake_provider, FakeProvider) and provider.client_for(row()) is fake_provider
    first = await fake_provider.send_message(sms())
    again = await fake_provider.send_message(sms())
    assert first == again and len(fake_provider.sent) == 1  # 같은 키는 한 번만 나간다
    assert (await fake_provider.message_status(first.provider_id)).state == "accepted"
    old, new = (provider.Inbound(provider_id=f"MG{i}", from_number=SENTINEL_DIGITS, body="네", at=T0 + timedelta(hours=i),
                                 has_media=False) for i in (1, 2))
    fake_provider.inbox = [new, old]
    fake_provider.received_flags = {"truncated": True}
    got = await fake_provider.received(T0 + timedelta(hours=2))
    assert isinstance(got, Received) and got.items == [new] and got.truncated is True and got.fetched_at is not None
    assert (await fake_provider.received(None)).items == [old, new]
    fake_provider.fail = ProviderFailed("rate_limited", "잠시 뒤 다시 해 주세요.", 429, retry_after_s=30)
    e = await failure(fake_provider.check())
    assert (e.code, e.retry_after_s) == ("rate_limited", 30)
    assert fake_provider.log == ["send_message", "send_message", "message_status", "received", "received", "check"]
