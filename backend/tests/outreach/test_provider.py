"""Task 69 — 한국AI통신 REST 호출(app.outreach.provider). 실제 제공사·DNS 를 쓰지 않는다(KatMock = httpx.MockTransport).

응답 모양은 공개 문서(docs.koreaaitel.com, 2026-11-23)의 칸 이름을 따른 가상 값이다.
"""

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.info.generic import key_survives
from app.outreach import provider
from app.outreach.provider import (
    RECEIVED_MAX_PAGES,
    RECEIVED_PAGE_SIZE,
    STATUS_MAP,
    Accepted,
    KatClient,
    MessageRequest,
    ProviderConn,
    ProviderFailed,
)
from app.security import crypto
from app.store.tables_outreach import NotifyConnection
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
)

CONN = ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=SENTINEL_KEY)
T0 = datetime(2026, 11, 23, 3, 0, 0, tzinfo=UTC)
ECHO = f"key={SENTINEL_KEY} acct={KAT_ACCOUNT} to={SENTINEL_PHONE} raw={SENTINEL_DIGITS}"  # 제공사가 되돌려 보낸다고 치는 글


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


def raising(exc_type: type[Exception]):
    def override(request: httpx.Request) -> httpx.Response:
        raise exc_type(f"boom {ECHO} {request.url}")

    return override


# ── 보내기 ──────────────────────────────────────────────────────────


async def test_send_puts_bearer_and_idempotency_key():
    mock = KatMock()
    accepted = await KatClient(CONN, transport=mock).send_message(sms())
    assert len(mock.requests) == 1
    request = mock.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{KAT_BASE}/v1/accounts/{KAT_ACCOUNT}/messages"
    assert request.headers["authorization"] == f"Bearer {SENTINEL_KEY}"
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


@pytest.mark.parametrize("req", [
    sms(idempotency_key=""), sms(to=""), sms(sender=""), sms(body=""), sms(channel="call"),
    kakao(kakao_channel=None), kakao(template_code=""),
])
async def test_incomplete_request_is_refused_before_any_call(req):
    mock = KatMock()
    e = await failure(KatClient(CONN, transport=mock).send_message(req))
    assert e.code == "bad_request" and mock.requests == [] and e.maybe_sent is False


async def test_same_idempotency_key_goes_out_as_given_and_is_not_retried_here():
    mock = KatMock(override=answer(500, {"error": "x", "code": "internal"}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert e.code == "server" and e.http_status == 500
    assert len(mock.requests) == 1  # 다시 시도하지 않는다 — 다시 보내기는 나가는 문이 정한다


# ── 실패 코드 ───────────────────────────────────────────────────────


async def test_401_is_bad_key_without_key_in_message():
    mock = KatMock(override=answer(401, {"error": f"invalid {ECHO}", "code": SENTINEL_KEY}))
    e = await failure(KatClient(CONN, transport=mock).check())
    assert e.code == "bad_key" and e.http_status == 401
    assert SENTINEL_KEY not in e.message and leaks(*everything_in(e)) == []


@pytest.mark.parametrize(("status", "vendor_code", "call", "expected"), [
    (403, "forbidden", "check", "bad_account"),
    (403, "overseas_ip_blocked", "send", "network"),
    (404, "not_found", "check", "bad_account"),  # 계정 경로뿐인 주소가 없다 → Account ID·기본 주소
    (404, "not_found", "send", "bad_account"),
    (404, "not_found", "status", "bad_request"),  # 그 메시지가 없다
    (404, "not_found", "call", "bad_request"),
    (400, "from_not_registered", "send", "bad_sender"),
    (400, "invalid_phone", "send", "bad_request"),
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
    assert e.maybe_sent is False  # 제공사가 거절이라고 답했다
    assert len(mock.requests) == 1 and leaks(*everything_in(e)) == []
    assert any("가" <= ch <= "힣" for ch in e.message)  # 한국어


async def test_known_vendor_codes_get_their_own_message_and_unknown_ones_are_named():
    client = KatClient(CONN, transport=KatMock(override=answer(422, {"error": "x", "code": "quota_exceeded"})))
    assert "한도" in (await failure(client.send_message(sms()))).message
    client = KatClient(CONN, transport=KatMock(override=answer(422, {"error": "x", "code": "brand_new_code"})))
    assert "brand_new_code" in (await failure(client.send_message(sms()))).message


async def test_vendor_error_code_that_holds_a_secret_is_not_repeated():
    key = "katTESTkeyZZZZ9999"  # 코드처럼 생긴 키(글자·숫자뿐)
    conn = ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=key)
    for vendor_code in (key, key.upper(), SENTINEL_KEY, ECHO, f"x_{KAT_ACCOUNT}", 7, None, "a" * 41):
        mock = KatMock(key=key, override=answer(422, {"error": ECHO, "code": vendor_code}))
        e = await failure(KatClient(conn, transport=mock).send_message(sms()))
        assert e.code == "bad_request" and "제공사 코드" not in e.message, vendor_code
        assert leaks(*everything_in(e)) == [] and not key_survives(e.message, key), vendor_code


async def test_message_the_vendor_already_marked_failed_is_still_accepted_with_its_id():
    mock = KatMock(override=answer(201, {"messageId": "MG9", "status": "failed", "failureCode": "invalid_number"}))
    assert await KatClient(CONN, transport=mock).send_message(sms()) == Accepted(provider_id="MG9")  # 실패는 상태 조회가 알린다


@pytest.mark.parametrize(("body", "content_type"), [(b"<html>ok</html>", "text/html"), (b"[1, 2]", "application/json"),
                                                    (b"", "application/json")])
async def test_unreadable_success_body_is_unknown(body, content_type):
    mock = KatMock(override=lambda r: httpx.Response(200, content=body, headers={"content-type": content_type}))
    e = await failure(KatClient(CONN, transport=mock).check())
    assert e.code == "unknown" and e.http_status == 200


async def test_timeout_and_network_codes():
    cases = [(httpx.ConnectTimeout, "timeout", False), (httpx.ReadTimeout, "timeout", True),
             (httpx.ConnectError, "network", False), (httpx.ReadError, "network", True),
             (httpx.RemoteProtocolError, "network", True), (RuntimeError, "unknown", True)]
    for exc_type, code, maybe_sent in cases:
        mock = KatMock(override=raising(exc_type))
        client = KatClient(CONN, transport=mock)
        sent = await failure(client.send_message(sms()))
        assert (sent.code, sent.maybe_sent, sent.http_status) == (code, maybe_sent, None), exc_type
        asked = await failure(client.message_status("MG000001abcdef"))
        assert (asked.code, asked.maybe_sent) == (code, False), exc_type  # 조회는 보낸 것이 없다
        assert len(mock.requests) == 2  # 다시 시도하지 않는다
        assert leaks(*everything_in(sent), *everything_in(asked)) == [], exc_type
    assert "보냈는지" in sent.message  # 보냈는지 알 수 없다는 말


async def test_whole_call_is_bounded_by_the_time_limit(monkeypatch):
    import asyncio

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    monkeypatch.setattr(provider, "TIMEOUT_S", 0.05)
    e = await failure(KatClient(CONN, transport=httpx.MockTransport(slow)).send_message(sms()))
    assert (e.code, e.maybe_sent) == ("timeout", True)


async def test_redirect_is_not_followed():
    mock = KatMock(override=answer(302, headers={"location": f"https://elsewhere.invalid/steal?{ECHO}"}))
    e = await failure(KatClient(CONN, transport=mock).send_message(sms()))
    assert e.code == "bad_request" and e.http_status == 302
    assert len(mock.requests) == 1 and mock.requests[0].url.host == "api.koreaaitel.com"
    assert leaks(*everything_in(e)) == []


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1", "http://api.koreaaitel.com", "https://localhost", "https://127.0.0.1:8443", "https://10.0.0.5",
    "https://169.254.169.254", "https://[::1]", f"https://{SENTINEL_KEY}@api.koreaaitel.com", "ftp://api.koreaaitel.com",
    "", "not a url",
])
async def test_internal_base_url_is_refused(base_url, no_provider_dns):
    mock = KatMock()
    client = KatClient(ProviderConn(base_url=base_url, account_id=KAT_ACCOUNT, key=SENTINEL_KEY), transport=mock)
    for call in (client.check(), client.send_message(sms()), client.received(None)):
        e = await failure(call)
        assert e.code == "bad_request" and e.maybe_sent is False and leaks(*everything_in(e)) == []
    assert mock.requests == [] and no_provider_dns == []  # 요청 0번, 이름도 풀지 않았다


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
    KatClient(ProviderConn(base_url=KAT_BASE, account_id=account, key=key))
    log.warning("after key=%s account=%s", key, account)
    before, after = (r.getMessage() for r in caplog.records)
    assert key in before  # 시험이 뜻이 있으려면: 등록 전에는 남는다
    assert key not in after and account not in after and after.startswith("after key=")


async def test_vendor_echo_never_reaches_a_return_value():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    mock.override = answer(201, {"messageId": SENTINEL_KEY, "status": "queued"})
    e = await failure(client.send_message(sms()))  # 키를 id 로 돌려주면 받지 않는다
    assert (e.code, e.maybe_sent) == ("unknown", True) and leaks(*everything_in(e)) == []
    mock.override = answer(201, {"status": "queued"})
    assert (await failure(client.send_message(sms()))).maybe_sent is True  # id 가 없어도 보냈을 수 있다

    mock.override = answer(200, {"messageId": "MG1", "status": "failed", "failureCode": SENTINEL_KEY, "failureMessage": ECHO})
    delivery = await client.message_status("MG1")
    assert delivery.state == "failed" and delivery.fail_code == "unknown" and leaks(delivery, asdict(delivery)) == []

    mock.override = answer(200, {"data": [
        {"messageId": SENTINEL_KEY, "direction": "inbound", "from": SENTINEL_DIGITS, "body": "x", "dateCreated": "2026-11-23T03:00:00Z"},
        {"messageId": "MG2", "direction": "inbound", "from": SENTINEL_DIGITS, "body": f"키는 {SENTINEL_KEY} 계정 {KAT_ACCOUNT}",
         "dateCreated": "2026-11-23T03:00:01Z"}], "meta": {}})
    inbound = await client.received(None)
    assert [m.provider_id for m in inbound] == ["MG2"]
    assert SENTINEL_KEY not in inbound[0].body and KAT_ACCOUNT not in inbound[0].body and inbound[0].body.startswith("키는 ")

    mock.override = answer(200, {"senderNumbers": [{"number": ECHO, "status": "approved"}, {"number": 7, "status": "approved"},
                                                   {"number": "070-0000-0123", "status": "approved"}, "junk"]})
    assert (await client.check()).senders == [KAT_SENDER]


def test_reprs_hide_key_account_numbers_and_text():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    inbound = provider.Inbound(provider_id="MG1", from_number=SENTINEL_DIGITS, body=f"연락처 {SENTINEL_PHONE}", at=T0,
                               has_media=False)
    check = provider.Check(ok=True, senders=[SENTINEL_DIGITS], latency_ms=3)
    assert leaks(CONN, client, sms(body=f"연락처 {SENTINEL_PHONE}"), inbound, check, str(CONN), f"{client}") == []
    assert "idem-0001" in repr(sms())  # 가릴 것이 아닌 칸은 보인다


# ── 상태·받은 문자·발신번호·통화 ───────────────────────────────────


def test_status_map_covers_the_documented_words():
    assert STATUS_MAP == {"queued": "accepted", "sent": "delivered", "failed": "failed", "received": "received"}


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
    assert ((await client.message_status(two)).fail_code, "some_new_code" in (await client.message_status(two)).fail_text) \
        == ("some_new_code", True)
    mock.set_status(two, "failed")
    plain = await client.message_status(two)
    assert plain.fail_code == "unknown" and plain.fail_text

    first = mock.add_inbound(SENTINEL_DIGITS, "네 알겠습니다", T0)
    second = mock.add_inbound("+82 10-0000-0188", "사진 보냅니다", T0 + timedelta(seconds=30), media=1)
    inbound = await client.received(None)
    assert [(m.provider_id, m.from_number, m.body, m.at, m.has_media) for m in inbound] == [
        (first, SENTINEL_DIGITS, "네 알겠습니다", T0, False),
        (second, "01000000188", "사진 보냅니다", T0 + timedelta(seconds=30), True)]  # 오래된 것부터, 번호는 정리한 꼴
    assert dict(mock.requests[-1].url.params) == {"status": "received", "pageSize": str(RECEIVED_PAGE_SIZE), "page": "0"}


@pytest.mark.parametrize("status", ["received", "sending", None, 7])
async def test_status_word_we_do_not_know_is_a_failure_not_a_guess(status):
    mock = KatMock(override=answer(200, {"messageId": "MG1", "status": status}))
    e = await failure(KatClient(CONN, transport=mock).message_status("MG1"))
    assert e.code == "unknown"


async def test_message_id_is_one_path_segment():
    mock = KatMock()
    await failure(KatClient(CONN, transport=mock).message_status("../sender-numbers"))
    assert mock.requests[0].url.raw_path == f"/v1/accounts/{KAT_ACCOUNT}/messages/..%2Fsender-numbers".encode()
    for bad in ("", None):
        e = await failure(KatClient(CONN, transport=mock).message_status(bad))
        assert e.code == "bad_request"
    assert len(mock.requests) == 1


async def test_received_keeps_only_since_and_later_and_stops_paging_at_older_rows():
    mock = KatMock()
    client = KatClient(CONN, transport=mock)
    ids = [mock.add_inbound(SENTINEL_DIGITS, f"회신 {i}", T0 + timedelta(seconds=i)) for i in range(150)]
    mock.messages[(await client.send_message(sms())).provider_id]["dateCreated"] = "2026-11-23T03:05:00.000Z"  # 보낸 것은 받은 것이 아니다
    mock.requests.clear()

    since = T0 + timedelta(seconds=120)
    got = await client.received(since)
    assert [m.provider_id for m in got] == ids[120:]  # 같은 시각 것도 준다(겹침은 받는 쪽이 id 로 막는다)
    assert [r.url.params["page"] for r in mock.requests] == ["0"]  # 첫 쪽에서 더 오래된 줄을 봤다

    mock.requests.clear()
    got = await client.received(T0 + timedelta(seconds=20))
    assert [m.provider_id for m in got] == ids[20:] and [r.url.params["page"] for r in mock.requests] == ["0", "1"]

    naive = (T0 + timedelta(seconds=120)).replace(tzinfo=None)  # DB 에서 읽은 시각(UTC, tz 없음)
    assert [m.provider_id for m in await client.received(naive)] == ids[120:]

    mock.requests.clear()
    assert len(await client.received(None)) == RECEIVED_PAGE_SIZE and len(mock.requests) == 1  # 처음에는 한 쪽만


async def test_received_stops_at_the_page_limit_and_says_so(caplog):
    mock = KatMock()
    for i in range(RECEIVED_PAGE_SIZE * RECEIVED_MAX_PAGES + 5):
        mock.add_inbound(SENTINEL_DIGITS, "회신", T0 + timedelta(seconds=i))
    got = await KatClient(CONN, transport=mock).received(T0)
    assert len(mock.requests) == RECEIVED_MAX_PAGES and len(got) == RECEIVED_PAGE_SIZE * RECEIVED_MAX_PAGES
    assert got[0].at < got[-1].at
    assert any("쪽" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


async def test_received_skips_rows_it_cannot_read_and_duplicates():
    good = {"messageId": "MG1", "direction": "inbound", "from": SENTINEL_DIGITS, "body": None, "numMedia": 0,
            "mediaUrl": ["https://media.invalid/1.jpg"], "dateCreated": "2026-11-23T03:00:00.123Z"}
    rows = [good, dict(good), {**good, "messageId": "MG2", "direction": "outbound"}, {**good, "messageId": "MG3", "from": ""},
            {**good, "messageId": "MG4", "dateCreated": "어제"}, {**good, "messageId": None}, "junk",
            {**good, "messageId": "MG5", "from": "1588-0000", "dateCreated": "2026-11-23T12:00:01+09:00"}]
    mock = KatMock(override=answer(200, {"data": rows, "meta": {"page": 0, "pageSize": 100, "total": len(rows)}}))
    got = await KatClient(CONN, transport=mock).received(None)
    assert [(m.provider_id, m.from_number, m.body, m.has_media) for m in got] == [
        ("MG1", SENTINEL_DIGITS, "", True), ("MG5", "15880000", "", True)]  # 사람 번호가 아니어도 숫자만 남겨 준다
    assert got[0].at == datetime(2026, 11, 23, 3, 0, 0, 123000, tzinfo=UTC) and got[1].at.utcoffset() == timedelta(0)
    e = await failure(KatClient(CONN, transport=KatMock(override=answer(200, {"meta": {}}))).received(None))
    assert e.code == "unknown"


async def test_check_returns_approved_senders_and_latency():
    mock = KatMock()
    check = await KatClient(CONN, transport=mock).check()
    assert check.ok is True and check.senders == [KAT_SENDER] and check.latency_ms >= 0  # 승인 대기 번호는 뺀다
    assert [(r.method, r.url.path) for r in mock.requests] == [("GET", f"/v1/accounts/{KAT_ACCOUNT}/sender-numbers")]
    e = await failure(KatClient(CONN, transport=KatMock(override=answer(200, {"grace": []}))).check())
    assert e.code == "unknown"


async def test_call_info_returns_only_plain_documented_fields():
    mock = KatMock()
    mock.add_call("CA000001", hangupCause=ECHO, transferReasonText=ECHO, recordingUrl=f"https://x.invalid/{KAT_ACCOUNT}/r.wav",
                  transfers=[{"to": SENTINEL_DIGITS}], surprise=SENTINEL_KEY)
    info = await KatClient(CONN, transport=mock).call_info("CA000001")
    assert mock.requests[0].url.path == f"/v1/accounts/{KAT_ACCOUNT}/calls/CA000001"
    assert info["status"] == "completed" and info["direction"] == "outbound" and info["duration"] == 42
    assert info["dateCreated"] == "2026-11-23T00:00:00.000Z" and info["hangupSource"] == "callee"
    assert not {"to", "from", "accountId", "recordingUrl", "transfers", "transferReasonText", "surprise"} & set(info)
    assert leaks(info, json.dumps(info, ensure_ascii=False)) == []


# ── client_for · 가짜 ─────────────────────────────────────────────


def row(**changes: object) -> NotifyConnection:
    fields = {"name": "기본", "base_url": KAT_BASE, "secret_ciphertext": crypto.encrypt(SENTINEL_KEY), "secret_last4": "9999",
              "account_id": KAT_ACCOUNT}
    return NotifyConnection(**{**fields, **changes})


def test_client_for_decrypts_the_stored_key():
    client = provider.client_for(row())
    assert isinstance(client, KatClient) and client.conn == CONN


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
    fake_provider.fail = ProviderFailed("rate_limited", "잠시 뒤 다시 해 주세요.", 429)
    assert (await failure(fake_provider.check())).code == "rate_limited"
    assert fake_provider.log == ["send_message", "send_message", "message_status", "check"]
