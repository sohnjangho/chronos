"""Task 59 — 연결 진단(P1~P4) 함수. 실제 제공사를 부르지 않는다(httpx.MockTransport).

응답 모양은 한국AI통신 공개 문서(api-reference/claw-ops-api/…)의 칸 이름을 따른 가상 값이다.
"""

import json
from dataclasses import asdict
from urllib.parse import quote, quote_plus

import httpx
import pytest

from app.notify import diagnostics
from app.notify.diagnostics import (
    DEFAULT_BASE_URL,
    MAX_REQUESTS,
    Calls,
    DiagnosticConn,
    check_message_status,
    check_received,
    check_send_sms,
    check_senders,
    make_client,
    run_checks,
    scrub,
)

SENTINEL_KEY = "kat-test-key-ZZZZ9999"
SENTINEL_PHONE = "010-0000-0199"
ACCOUNT = "AC00000000003c4d"
FROM = "07000000123"
TO = "01000000199"
MSG_ID = "MG00000000000000000000000000000001"
CONN = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to=TO)
LEAKS = (SENTINEL_KEY, ACCOUNT, "3c4d", TO, "0199", FROM, "0123", "ZZZZ9999")


def msg(status: str, direction: str = "outbound", failure: str | None = None) -> dict:
    """문서의 메시지 칸(가상 값). 번호·계정이 본문에 그대로 실려 온다고 본다."""
    return {"messageId": MSG_ID, "accountId": ACCOUNT, "direction": direction, "type": "sms",
            "from": FROM, "to": TO, "subject": None, "body": f"to {SENTINEL_PHONE}", "status": status,
            "failureCode": failure, "failureMessage": None, "numMedia": 0, "mediaUrl": [],
            "dateCreated": "2026-11-23T04:12:44.123Z", "dateUpdated": "2026-11-23T04:12:51.884Z"}


class KatFake(httpx.MockTransport):
    """경로로 P1~P4 를 나눈다. `statuses` 는 P3 조회마다 차례로 돌려줄 상태(마지막 것은 계속)."""

    def __init__(self, statuses: tuple[str, ...] = ("queued", "sent"), override=None) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses)
        self.override = override
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.override is not None:
            return self.override(request)
        path = request.url.path
        if path.endswith("/sender-numbers"):
            return httpx.Response(200, json={"senderNumbers": [
                {"number": FROM, "status": "approved"}, {"number": "07000000456", "status": "pending"}]})
        if request.method == "POST" and path.endswith("/messages"):
            return httpx.Response(201, json=msg("queued"))
        if path.endswith(f"/messages/{MSG_ID}"):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json=msg(status, failure="handset_off" if status == "failed" else None))
        if path.endswith("/messages"):
            return httpx.Response(200, json={"data": [msg("received", "inbound")],
                                             "meta": {"page": 0, "pageSize": 20, "total": 1}})
        return httpx.Response(404, json={"code": "not_found", "error": "없음"})


PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """시험은 이름 풀이(DNS)를 쓰지 않는다 — 모든 호스트가 공인 IP 하나로 풀린다."""
    asked: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        asked.append(host)
        return [PUBLIC_IP]

    monkeypatch.setattr(diagnostics, "RESOLVE", resolve)
    return asked


def client(fake: KatFake) -> httpx.AsyncClient:
    return make_client(transport=fake)


async def no_sleep(_s: float) -> None:
    return None


def assert_clean(results) -> None:
    text = json.dumps([asdict(r) for r in results], ensure_ascii=False)
    for leak in LEAKS:
        assert leak not in text, leak


def test_scrub_hides_key_account_numbers_and_long_tokens():
    out = scrub(f"key={SENTINEL_KEY} acct={ACCOUNT} to=010-0000-0199 raw={TO} +82 10-0000-0777 x 07000000888 "
                + "t" * 45 + " date 2026-11-23", secrets=[SENTINEL_KEY, ACCOUNT], numbers=[TO])
    for leak in (SENTINEL_KEY, "3c4d", "0199", "0777", "0888", "t" * 45):
        assert leak not in out
    assert "2026-11-23" in out  # 날짜는 번호로 보지 않는다
    assert len(scrub("가" * 500, secrets=[], numbers=[])) == 200


async def test_connection_test_never_sends_sms():
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, sleep=no_sleep)
    assert [r.id for r in results] == ["P1", "P2", "P3", "P4"]
    assert results[0].ok and results[3].ok
    assert results[1].skipped and not results[1].ok and "send_test_sms" in results[1].detail
    assert results[2].skipped
    assert not [r for r in fake.requests if r.method == "POST"]


async def test_send_sms_needs_explicit_flag():
    fake = KatFake()
    async with client(fake) as http:
        result, mid = await check_send_sms(CONN, http, calls=Calls())
    assert result.skipped and mid is None and fake.requests == []


async def test_full_run_sends_one_sms_and_results_are_clean():
    fake = KatFake(statuses=("queued", "queued", "sent"))
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    async with client(fake) as http:
        results = await run_checks(CONN, http, send_test_sms=True, sleep=sleep)
    assert all(r.ok and not r.skipped for r in results), [asdict(r) for r in results]
    p1, p2, p3, p4 = results
    assert "approved 1" in p1.detail and "고른 발신번호 승인됨" in p1.detail
    assert p1.latency_ms is not None and p1.label
    assert "status=queued" in p2.detail
    assert p3.detail.startswith("queued → sent")
    assert p4.detail.startswith("1건") and any("구조" in n for n in p4.notes)
    assert_clean(results)
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert body["To"] == TO and body["From"] == FROM and body["Type"] == "sms"
    assert body["Body"] == "[ChronOS] 실측 문자입니다." and body["IdempotencyKey"].startswith("chronos-probe-")
    for r in fake.requests:
        assert r.headers["authorization"] == f"Bearer {SENTINEL_KEY}"
        assert r.url.host == "api.koreaaitel.com" and r.url.path.startswith(f"/v1/accounts/{ACCOUNT}/")
    received = [r for r in fake.requests if r.method == "GET" and r.url.path.endswith("/messages")]
    assert received[0].url.params["status"] == "received"
    assert len(fake.requests) == 6 and sleeps == [5, 5]


async def test_status_polls_at_most_four_times_within_cap():
    fake = KatFake(statuses=("queued",))
    calls = Calls()
    async with client(fake) as http:
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, calls=calls)
    p3 = results[2]
    assert not p3.ok and p3.detail.startswith("still_queued")
    polls = [r for r in fake.requests if r.url.path.endswith(f"/messages/{MSG_ID}")]
    assert len(polls) == 4 and calls.sent == 7 <= MAX_REQUESTS


async def test_failed_status_shows_failure_code():
    fake = KatFake(statuses=("failed",))
    async with client(fake) as http:
        result = await check_message_status(CONN, http, MSG_ID, sleep=no_sleep, calls=Calls())
    assert result.ok and result.detail == "failed · failureCode=handset_off"


async def test_request_cap_fails_without_calling():
    fake = KatFake()
    calls = Calls()
    calls.sent = MAX_REQUESTS
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=calls)
    assert not result.ok and result.detail.startswith("request_limit") and fake.requests == []


async def test_error_body_gives_code_and_no_secret():
    fake = KatFake(override=lambda r: httpx.Response(401, json={
        "code": "unauthorized", "error": f"bad key {SENTINEL_KEY} for {ACCOUNT} from {FROM} to {SENTINEL_PHONE}"}))
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and result.detail.startswith("unauthorized")
    assert any("bad key" in n for n in result.notes)
    assert_clean([result])


async def test_network_error_gives_type_only():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} key {SENTINEL_KEY}")

    async with client(KatFake(override=boom)) as http:
        result = await check_received(CONN, http, calls=Calls())
    assert not result.ok and result.detail == "ConnectError"
    assert "cannot reach" not in json.dumps(asdict(result), ensure_ascii=False)
    assert_clean([result])


async def test_redirect_is_not_followed_even_if_client_would():
    fake = KatFake(override=lambda r: httpx.Response(302, headers={"location": "https://elsewhere.example/x"}))
    async with httpx.AsyncClient(transport=fake, follow_redirects=True, trust_env=False) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and result.detail.startswith("http_302") and len(fake.requests) == 1


async def test_send_without_recipient_is_skipped():
    conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to="")
    fake = KatFake()
    async with client(fake) as http:
        result, mid = await check_send_sms(conn, http, send_test_sms=True, calls=Calls())
    assert result.skipped and mid is None and fake.requests == []


# ── 리뷰 1차 ─────────────────────────────────────────────────────────

ODD_KEY = "kT+9/zQ=Secret_KEY_value"
ODD_ACCOUNT = "AcCt-77x/9"


def secret_forms(s: str) -> set[str]:
    full = "".join(f"%{b:02X}" for b in s.encode())
    forms = {s, quote(s), quote(s, safe=""), quote_plus(s), full, full.lower()}
    return forms | {f.lower() for f in forms} | {f.upper() for f in forms}


def phone_forms(n: str) -> set[str]:
    a, b, c = n[:3], n[3:7], n[7:]
    intl = "82" + n[1:]
    return {n, f"{a}-{b}-{c}", f"+{intl}", f"+82 {n[1:3]}-{b}-{c}", f"({a}) {b} {c}", f"{a}.{b}.{c}",
            quote(f"+{intl}"), quote(f"+82 {n[1:3]}-{b}-{c}"), quote(f"{a} {b} {c}"), quote_plus(f"+82 {n[1:]}"),
            f"{a}%2D{b}%2D{c}", f"{a}%2d{b}%2d{c}", f"{a}%20{b}%20{c}", f"{a}%2E{b}%2E{c}", f"tel:{n}"}


@pytest.mark.parametrize("flag", ["false", "0", 1, None, "true", "True"])
async def test_send_needs_literal_true(flag):
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, send_test_sms=flag, sleep=no_sleep)
        single, mid = await check_send_sms(CONN, http, send_test_sms=flag, calls=Calls())
    assert not [r for r in fake.requests if r.method == "POST"]
    assert results[1].skipped and single.skipped and mid is None


@pytest.mark.parametrize("planted", sorted(
    secret_forms(ODD_KEY) | secret_forms(ODD_ACCOUNT) | phone_forms(FROM) | phone_forms(TO)))
async def test_scrub_removes_encoded_case_and_separator_variants(planted):
    conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=ODD_KEY, account_id=ODD_ACCOUNT, sender=FROM, test_to=TO)
    fake = KatFake(override=lambda r: httpx.Response(400, json={"code": f"c {planted} c", "error": f"e {planted} e"},
                                                     headers={"Retry-After": planted}))
    async with client(fake) as http:
        result = await check_senders(conn, http, calls=Calls())
    text = result.detail + " ".join(result.notes)
    assert planted not in text and planted.lower() not in text.lower()
    for n in (FROM, TO):
        assert n[1:] not in "".join(ch for ch in text if ch.isdigit())


async def test_every_request_has_an_explicit_timeout():
    fake = KatFake(statuses=("sent",))
    async with httpx.AsyncClient(transport=fake, trust_env=False, timeout=120) as http:
        await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep)
    assert fake.requests
    for r in fake.requests:
        assert r.extensions["timeout"] == {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0}


def test_make_client_has_the_contract():
    http = make_client()
    assert http.trust_env is False and http.follow_redirects is False and http.timeout.read == 15.0


async def test_client_that_trusts_env_sends_nothing():
    fake = KatFake()
    async with httpx.AsyncClient(transport=fake) as http:  # trust_env 기본 True
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep)
        single = await check_senders(CONN, http, calls=Calls())
    assert fake.requests == []
    for r in [*results, single]:
        assert not r.ok and not r.skipped and "trust_env=False" in r.detail


@pytest.mark.parametrize("base", ["http://127.0.0.1:5600", "ftp://x", "https://api.koreaaitel.com@evil.test",
                                  "https://localhost", "https://10.0.0.1", "https://[::1]", "https://169.254.169.254",
                                  "", "not a url"])
async def test_unsafe_base_url_is_refused_before_any_request(base):
    conn = DiagnosticConn(base_url=base, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to=TO)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(conn, http, send_test_sms=True, sleep=no_sleep)
        single = await check_received(conn, http, calls=Calls())
    assert fake.requests == []
    assert len(results) == 4
    for r in [*results, single]:
        assert not r.ok and not r.skipped and r.detail.startswith("bad_base_url · ") and "주소" in r.detail


@pytest.mark.parametrize("base", [
    "https://api.koreaaitel.com?x=", "https://api.koreaaitel.com#", "https://api.koreaaitel.com/proxy?u=",
    "https://api.koreaaitel.com/a/../b", "https://api.koreaaitel.com/v1", " https://api.koreaaitel.com",
    "https://api.koreaaitel.com ", "https://api.koreaaitel.com%20", "https://api.koreaaitel.com%0a",
    "https://api.koreaaitel.com\t", "https://api.koreaaitel.com\n", "https://evil.example\\.koreaaitel.com",
])
async def test_base_url_with_path_query_fragment_or_whitespace_is_refused(base):
    """주소는 scheme·호스트·포트뿐이어야 한다 — 뒤에 붙이는 /v1/accounts/… 가 질의·조각 속으로 들어가지 않게."""
    conn = DiagnosticConn(base_url=base, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to=TO)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(conn, http, send_test_sms=True, sleep=no_sleep)
    assert fake.requests == [] and len(results) == 4
    for r in results:
        assert not r.ok and not r.skipped and r.detail.startswith("bad_base_url · ") and "주소" in r.detail


@pytest.mark.parametrize("base", ["https://api.koreaaitel.com", "https://api.koreaaitel.com/", "HTTPS://API.KOREAAITEL.COM",
                                  "https://api.koreaaitel.com:8443"])
def test_plain_base_urls_are_accepted(base):
    assert diagnostics.base_url_problem(base) is None


def test_shared_helpers_have_public_names_and_the_old_ones_still_work():
    assert diagnostics.segment is diagnostics._segment and diagnostics.resolve_problem is diagnostics._resolve_problem
    assert diagnostics.segment("..") == "%2E%2E" and diagnostics.segment("a/b?c") == "a%2Fb%3Fc"


async def test_broken_connection_values_never_raise():
    fake = KatFake()
    async with client(fake) as http:
        for conn in (DiagnosticConn(base_url=None, key=SENTINEL_KEY, account_id=ACCOUNT),  # type: ignore[arg-type]
                     DiagnosticConn(base_url=DEFAULT_BASE_URL, key=None, account_id=ACCOUNT),  # type: ignore[arg-type]
                     DiagnosticConn(base_url=DEFAULT_BASE_URL, key="a\nb", account_id=ACCOUNT),
                     DiagnosticConn(base_url=DEFAULT_BASE_URL, key="키값", account_id=ACCOUNT)):
            results = await run_checks(conn, http, send_test_sms=True, sleep=no_sleep)
            assert results and not any(r.ok for r in results)


def test_conn_repr_hides_key_account_and_numbers():
    for text in (repr(CONN), str(CONN)):
        for leak in (SENTINEL_KEY, ACCOUNT, FROM, TO):
            assert leak not in text


async def test_ids_are_quoted_into_the_path():
    odd = "../../x?y=1#f"
    fake = KatFake(override=lambda r: httpx.Response(201, json={"messageId": odd, "status": "queued"})
                   if r.method == "POST" else httpx.Response(200, json={"status": "sent"}))
    async with client(fake) as http:
        await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, steps=(2, 3))
        conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=SENTINEL_KEY, account_id="x/../../admin?q=1")
        await check_senders(conn, http, calls=Calls())
    poll, senders = fake.requests[1], fake.requests[2]
    assert poll.url.query == b"" and poll.url.raw_path.endswith(b"/messages/..%2F..%2Fx%3Fy%3D1%23f")
    assert senders.url.query == b"" and senders.url.raw_path.startswith(b"/v1/accounts/x%2F..%2F..%2Fadmin%3Fq%3D1/")
    for r in fake.requests:
        assert r.url.path.startswith("/v1/accounts/")


async def test_dot_ids_cannot_climb_the_path():
    fake = KatFake(override=lambda r: httpx.Response(201, json={"messageId": "..", "status": "queued"})
                   if r.method == "POST" else httpx.Response(200, json={"status": "sent"}))
    async with client(fake) as http:
        await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, steps=(2, 3))
    assert fake.requests[1].url.path.endswith("/messages/..")  # %2E%2E 로 보냄 — 위로 올라가지 않음
    assert fake.requests[1].url.raw_path.endswith(b"/messages/%2E%2E")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError])
async def test_post_that_may_have_gone_says_so(exc):
    def boom(request: httpx.Request) -> httpx.Response:
        raise exc("x")

    async with client(KatFake(override=boom)) as http:
        result, mid = await check_send_sms(CONN, http, send_test_sms=True, calls=Calls())
    assert not result.ok and mid is None and result.detail.startswith(exc.__name__)
    assert "보냈는지 알 수 없" in result.detail and "두 번째 문자" in result.detail


async def test_post_that_never_connected_does_not_warn():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    async with client(KatFake(override=boom)) as http:
        result, _ = await check_send_sms(CONN, http, send_test_sms=True, calls=Calls())
    assert result.detail == "ConnectError"


async def test_steps_accept_p_strings():
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, steps=("P1", "p4"), sleep=no_sleep)
    assert [r.id for r in results] == ["P1", "P4"]


# ── 리뷰 2차 ─────────────────────────────────────────────────────────


def resolver(*addresses: str):
    def resolve(host: str, port: int) -> list[str]:
        return list(addresses)
    return resolve


@pytest.mark.parametrize("addresses", [("10.0.0.7",), (PUBLIC_IP, "192.168.0.3"), ("169.254.169.254",),
                                       ("::1",), ("fd00::1",), ()])
async def test_host_that_resolves_inside_is_refused(addresses):
    conn = DiagnosticConn(base_url="https://intranet.example", key=SENTINEL_KEY, account_id=ACCOUNT,
                          sender=FROM, test_to=TO)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(conn, http, send_test_sms=True, sleep=no_sleep, resolve=resolver(*addresses))
        single = await check_senders(conn, http, calls=Calls(), resolve=resolver(*addresses))
    assert fake.requests == []
    for r in [*results, single]:
        assert not r.ok and not r.skipped and r.detail.startswith("bad_base_url · ") and "내부망" in r.detail


async def test_host_that_resolves_public_only_proceeds():
    asked: list[tuple[str, int]] = []

    def resolve(host: str, port: int) -> list[str]:
        asked.append((host, port))
        return [PUBLIC_IP, "2606:2800:220:1:248:1893:25c8:1946"]

    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, sleep=no_sleep, steps=(1,), resolve=resolve)
    assert results[0].ok and len(fake.requests) == 1
    assert asked == [("api.koreaaitel.com", 443)]


@pytest.mark.parametrize("error", [OSError("no such host"), RuntimeError("boom")])
async def test_resolver_error_fails_without_request(error):
    def resolve(host: str, port: int) -> list[str]:
        raise error

    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, resolve=resolve)
    assert fake.requests == [] and len(results) == 4
    for r in results:
        assert not r.ok and not r.skipped and r.detail.startswith("resolve_failed · ") and "boom" not in r.detail


async def test_slow_resolver_runs_out_of_time(monkeypatch):
    import threading

    gate = threading.Event()

    def resolve(host: str, port: int) -> list[str]:
        gate.wait(2)
        return [PUBLIC_IP]

    monkeypatch.setattr(diagnostics, "RESOLVE_TIMEOUT_S", 0.05)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, sleep=no_sleep, steps=(1,), resolve=resolve)
    gate.set()
    assert fake.requests == [] and results[0].detail.startswith("resolve_failed · ")


async def test_ip_literal_host_is_not_resolved(fake_dns):
    conn = DiagnosticConn(base_url="https://93.184.216.34", key=SENTINEL_KEY, account_id=ACCOUNT)
    async with client(KatFake()) as http:
        results = await run_checks(conn, http, sleep=no_sleep, steps=(1,))
    assert results[0].ok and fake_dns == []


async def test_send_needs_room_for_one_status_check():
    calls = Calls()
    calls.sent = MAX_REQUESTS - 1
    fake = KatFake()
    async with client(fake) as http:
        result, mid = await check_send_sms(CONN, http, send_test_sms=True, calls=calls)
    assert result.skipped and not result.ok and result.detail.startswith("request_limit") and mid is None
    assert fake.requests == [] and calls.sent == MAX_REQUESTS - 1


@pytest.mark.parametrize("field_name", ["key", "account_id"])
async def test_short_key_or_account_is_refused(field_name):
    values = {"base_url": DEFAULT_BASE_URL, "key": SENTINEL_KEY, "account_id": ACCOUNT, field_name: "Ab12345"}
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(DiagnosticConn(**values), http, send_test_sms=True, sleep=no_sleep)
    assert fake.requests == []
    for r in results:
        assert not r.ok and r.detail.startswith("bad_connection · ") and "8자" in r.detail


def test_normal_key_leaves_ordinary_text_alone():
    text = "unauthorized · HTTP 401 · status=queued · 발신번호 2개 · approved 1"
    assert scrub(text, secrets=[SENTINEL_KEY, ACCOUNT], numbers=[FROM, TO]) == text
