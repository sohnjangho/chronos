"""Task 59 — 연결 진단(P1~P4) 함수. 실제 제공사를 부르지 않는다(httpx.MockTransport).

응답 모양은 한국AI통신 공개 문서(api-reference/claw-ops-api/…)의 칸 이름을 따른 가상 값이다.
"""

import asyncio
import json
import re
import time
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
from tests.provider_doubles import MAX_FAKE_REQUESTS, RunawayFake

pytestmark = pytest.mark.usefixtures("time_guard")  # 큰 응답·느린 이름 풀이를 흉내 내는 시험들 — 하나가 20초를 넘기면 끊는다

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
        if len(self.requests) >= MAX_FAKE_REQUESTS:
            raise RunawayFake("가짜 서버가 너무 많이 불렸습니다 — 부르는 쪽이 끝나지 않습니다")
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
    assert results[1].skipped and not results[1].ok
    assert (results[1].code, results[1].detail) == ("skipped_no_send", diagnostics.NO_SEND)
    assert results[2].skipped and (results[2].code, results[2].detail) == ("skipped_no_message", diagnostics.NO_MESSAGE)
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
    assert p1.detail == "인증됨 · 발신번호 2개(승인 1 · 심사 중 1) · 고른 발신번호는 승인됨"
    assert p1.latency_ms is not None and p1.label and all(r.code == "ok" and readable(r) for r in results)
    assert p2.detail == diagnostics.ACCEPTED and any("status=queued" in n for n in p2.notes)  # 제공사 말은 접어 보이는 줄에
    assert p3.detail == "접수됨 → 전송됨" and any("status=sent" in n for n in p3.notes)
    assert p4.detail == "받은 문자 1건" and any("구조" in n for n in p4.notes) and any("meta.total=1" in n for n in p4.notes)
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
    assert not p3.ok and p3.pending and p3.code == "still_queued"
    polls = [r for r in fake.requests if r.url.path.endswith(f"/messages/{MSG_ID}")]
    assert len(polls) == 4 and calls.sent == 7 <= MAX_REQUESTS


async def test_failed_status_shows_failure_code():
    fake = KatFake(statuses=("failed",))
    async with client(fake) as http:
        result = await check_message_status(CONN, http, MSG_ID, sleep=no_sleep, calls=Calls())
    assert not result.ok and (result.code, result.detail) == ("delivery_failed", "실패 — 단말기 전원이 꺼져 있습니다.")
    assert any("failureCode=handset_off" in n for n in result.notes)


async def test_request_cap_fails_without_calling():
    fake = KatFake()
    calls = Calls()
    calls.sent = MAX_REQUESTS
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=calls)
    assert not result.ok and result.code == "request_limit" and readable(result) and fake.requests == []


async def test_error_body_gives_code_and_no_secret():
    fake = KatFake(override=lambda r: httpx.Response(401, json={
        "code": "unauthorized", "error": f"bad key {SENTINEL_KEY} for {ACCOUNT} from {FROM} to {SENTINEL_PHONE}"}))
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and (result.code, result.detail) == ("bad_key", diagnostics.MESSAGES["bad_key"])
    assert any("bad key" in n for n in result.notes) and any("code=unauthorized" in n for n in result.notes)
    assert_clean([result])


async def test_network_error_gives_type_only():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} key {SENTINEL_KEY}")

    async with client(KatFake(override=boom)) as http:
        result = await check_received(CONN, http, calls=Calls())
    assert not result.ok and (result.code, result.detail) == ("network", diagnostics.MESSAGES["network"])
    assert any("ConnectError" in n for n in result.notes)  # 예외 종류는 접어 보이는 줄에만
    assert "cannot reach" not in json.dumps(asdict(result), ensure_ascii=False)
    assert_clean([result])


async def test_redirect_is_not_followed_even_if_client_would():
    fake = KatFake(override=lambda r: httpx.Response(302, headers={"location": "https://elsewhere.example/x"}))
    async with httpx.AsyncClient(transport=fake, follow_redirects=True, trust_env=False) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and result.code == "bad_request" and "따라가지 않았습니다" in result.detail
    assert len(fake.requests) == 1 and any("HTTP 302" in n for n in result.notes)


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
        # 연결 제한은 전체보다 짧다 — 닿지 않는 호스트에서 연결 시간 초과가 먼저 나게(제공사 호출과 같은 값)
        assert r.extensions["timeout"] == {"connect": 5.0, "read": 15.0, "write": 15.0, "pool": 15.0}
        assert r.headers["accept-encoding"] == "identity"


def test_make_client_has_the_contract():
    http = make_client()
    assert http.trust_env is False and http.follow_redirects is False and http.timeout.read == 15.0
    assert http.timeout.connect == diagnostics.CONNECT_TIMEOUT_S == 5.0 < diagnostics.TIMEOUT_S


async def test_diagnosis_scrubs_its_own_account_id_from_the_request_log(caplog):
    """진단만 돌려도(제공사 클라이언트를 만들지 않아도) httpx 요청 줄에 Account ID·키가 남지 않는다."""
    import logging

    caplog.set_level(logging.INFO)
    key, account = "kat-test-key-FRESH0001", "AC99999999fresh01"
    conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=key, account_id=account)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(conn, http, steps=(1, 4))
        single = await check_senders(DiagnosticConn(DEFAULT_BASE_URL, key, "AC88888888single"), http, calls=Calls())
    assert results[0].ok and single.ok and account in str(fake.requests[0].url)  # 요청에는 그대로 나갔다
    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert len(lines) == 3 and all("/v1/accounts/" in line for line in lines)
    assert not any(account in line or "AC88888888single" in line or key in line for line in lines)


async def test_reply_body_is_read_only_up_to_the_cap_and_never_unpacked(monkeypatch):
    import gzip

    monkeypatch.setattr(diagnostics, "MAX_BODY_BYTES", 2000)
    pulled = []

    async def endless():
        for i in range(500):
            pulled.append(i)
            yield b'{"senderNumbers": [], "pad": "' + b"a" * 970 if i == 0 else b"a" * 1000

    fake = KatFake(override=lambda r: httpx.Response(200, content=endless()))
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and result.code == "unknown" and len(pulled) < 10

    packed = gzip.compress(b'{"senderNumbers": []}' + b" " * 5_000_000)
    fake = KatFake(override=lambda r: httpx.Response(200, content=packed, headers={"content-encoding": "gzip"}))
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert not result.ok and (result.code, result.detail) == ("unknown", diagnostics.MESSAGES["unknown"])

    fits = b'{"senderNumbers": [], "pad": "' + b"a" * 1900 + b'"}'
    fake = KatFake(override=lambda r: httpx.Response(200, content=fits))
    async with client(fake) as http:
        assert (await check_senders(CONN, http, calls=Calls())).ok


def trickle(pieces: int = 40):
    """본문을 0.05초마다 한 조각씩 주는 응답(읽기 제한에는 걸리지 않는다). pieces 조각(2초)에서 스스로 끝난다."""
    async def chunks():
        yield b'{"senderNumbers": ['
        for _ in range(pieces):
            await asyncio.sleep(0.05)
            yield b" "
        yield b"]}"

    return chunks()


async def test_one_step_is_bounded_in_total_when_the_body_trickles_in(monkeypatch):
    monkeypatch.setattr(diagnostics, "TIMEOUT_S", 0.2)
    started = time.monotonic()
    fake = KatFake(override=lambda r: httpx.Response(200, content=trickle()))
    async with client(fake) as http:
        result = await check_senders(CONN, http, calls=Calls())
        assert not result.ok and (result.code, result.detail) == ("timeout", diagnostics.MESSAGES["timeout"])
        assert time.monotonic() - started < 1
        fake.override = lambda r: httpx.Response(201, content=trickle())
        sent, mid = await check_send_sms(CONN, http, send_test_sms=True, calls=Calls())
    assert not sent.ok and mid is None and sent.maybe_sent  # 요청은 나갔다
    assert sent.detail == f"{diagnostics.MESSAGES['timeout']} {diagnostics.MAYBE_SENT}"
    assert time.monotonic() - started < 2


async def test_test_sms_accepted_with_an_unreadable_reply_is_sent_with_outcome_unknown(monkeypatch):
    """201 을 받았는데 본문을 읽지 못하면(압축·상한 초과) 그냥 실패가 아니다 — 문자는 접수됐을 수 있다(`maybe_sent`)."""
    import gzip

    monkeypatch.setattr(diagnostics, "MAX_BODY_BYTES", 2000)
    replies = (httpx.Response(201, content=gzip.compress(json.dumps(msg("queued")).encode()), headers={"content-encoding": "gzip"}),
               httpx.Response(201, content=b'{"messageId": "' + b"a" * 3000 + b'"}'))
    for reply in replies:
        fake = KatFake(override=lambda r, reply=reply: reply)
        async with client(fake) as http:
            results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, steps=(2, 3))
        _, p2, p3, _ = results
        assert not p2.ok and not p2.skipped and (p2.code, p2.maybe_sent) == ("unknown", True)
        assert p2.detail == f"{diagnostics.MESSAGES['unknown']} {diagnostics.MAYBE_SENT}"
        assert p3.skipped and len(fake.requests) == 1  # 다시 보내지도, 모르는 id 로 조회하지도 않는다
        assert_clean(results)


async def test_client_that_trusts_env_sends_nothing():
    fake = KatFake()
    async with httpx.AsyncClient(transport=fake) as http:  # trust_env 기본 True
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep)
        single = await check_senders(CONN, http, calls=Calls())
    assert fake.requests == []
    for r in [*results, single]:
        assert not r.ok and not r.skipped and (r.code, r.detail) == ("untrusted_client", diagnostics.UNTRUSTED_CLIENT)
        assert "trust_env=False" in r.notes[0]  # 고칠 사람이 볼 말은 접어 보이는 줄에


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
        assert not r.ok and not r.skipped and r.code == "bad_base_url" and "주소" in r.detail and readable(r)


@pytest.mark.parametrize("base", [
    "https://api.koreaaitel.com?x=", "https://api.koreaaitel.com#", "https://api.koreaaitel.com/proxy?u=",
    "https://api.koreaaitel.com/a/../b", "https://api.koreaaitel.com/v1", " https://api.koreaaitel.com",
    "https://api.koreaaitel.com ", "https://api.koreaaitel.com%20", "https://api.koreaaitel.com%0a",
    "https://api.koreaaitel.com\t", "https://api.koreaaitel.com\n", "https://evil.example\\.koreaaitel.com",
    "https://api.koreaaitel.com;evil.example", "https://evil.example,api.koreaaitel.com", "https://a&b.example",
    "https://a=b.example",
])
async def test_base_url_with_path_query_fragment_or_whitespace_is_refused(base):
    """주소는 scheme·호스트·포트뿐이어야 한다 — 뒤에 붙이는 /v1/accounts/… 가 질의·조각 속으로 들어가지 않게."""
    conn = DiagnosticConn(base_url=base, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to=TO)
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(conn, http, send_test_sms=True, sleep=no_sleep)
    assert fake.requests == [] and len(results) == 4
    for r in results:
        assert not r.ok and not r.skipped and r.code == "bad_base_url" and "주소" in r.detail and readable(r)


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
    assert not result.ok and mid is None and result.maybe_sent and any(exc.__name__ in n for n in result.notes)
    assert "보냈는지 알 수 없" in result.detail and "두 번째 문자" in result.detail and readable(result)


async def test_post_that_never_connected_does_not_warn():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    async with client(KatFake(override=boom)) as http:
        result, _ = await check_send_sms(CONN, http, send_test_sms=True, calls=Calls())
    assert (result.code, result.maybe_sent, result.detail) == ("network", False, diagnostics.MESSAGES["network"])


async def test_steps_accept_p_strings():
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, steps=("P1", "p4"), sleep=no_sleep)
    assert [r.id for r in results if not r.skipped] == ["P1", "P4"] and len(fake.requests) == 2


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
        assert not r.ok and not r.skipped and r.code == "bad_base_url" and "내부망" in r.detail and readable(r)


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
        assert not r.ok and not r.skipped and (r.code, r.detail) == ("resolve_failed", diagnostics.RESOLVE_FAILED)


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
    assert fake.requests == [] and results[0].code == "resolve_failed"


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
    assert result.skipped and not result.ok and (result.code, result.detail) == ("request_limit", diagnostics.NO_ROOM)
    assert mid is None
    assert fake.requests == [] and calls.sent == MAX_REQUESTS - 1


@pytest.mark.parametrize("field_name", ["key", "account_id"])
async def test_short_key_or_account_is_refused(field_name):
    values = {"base_url": DEFAULT_BASE_URL, "key": SENTINEL_KEY, "account_id": ACCOUNT, field_name: "Ab12345"}
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(DiagnosticConn(**values), http, send_test_sms=True, sleep=no_sleep)
    assert fake.requests == []
    for r in results:
        assert not r.ok and r.code == ("bad_key" if field_name == "key" else "bad_account") and "8자" in r.detail


def test_normal_key_leaves_ordinary_text_alone():
    text = "unauthorized · HTTP 401 · status=queued · 발신번호 2개 · approved 1"
    assert scrub(text, secrets=[SENTINEL_KEY, ACCOUNT], numbers=[FROM, TO]) == text


# ── 화면에 그대로 보이는 글·기계가 읽는 칸(code · maybe_sent · pending) ──────────

_NOT_FOR_PEOPLE = re.compile(r"[a-z]+_[a-z]|status=|HTTP |failureCode|messageId|meta\.|[A-Za-z]+(?:Error|Timeout|Exception)\b"
                             r"|trust_env|send_test_sms|None\b|\bqueued\b|\bsent\b|\bapproved\b")


def readable(step) -> bool:
    """detail 이 사람이 읽는 한국어 문장인가(코드 낱말·예외 이름·칸 이름이 없다). 기계가 읽을 것은 code 와 notes 에 있다."""
    return bool(re.search(r"[가-힣]", step.detail)) and not _NOT_FOR_PEOPLE.search(step.detail) and bool(step.code)


class Breaks(httpx.AsyncBaseTransport):
    """요청 본문을 읽기 전(before — 연결 단계) 또는 읽은 뒤(after)에 exc 를 올린다. hang 을 주면 그만큼 멈춘 뒤에 올린다
    (스스로 끝난다). 본문을 읽은 뒤에는 `pulled` 가 선다."""

    def __init__(self, when: str, exc: Exception | None = None, hang: float = 0.0) -> None:
        self.when, self.exc, self.hang = when, exc or httpx.ReadTimeout("x"), hang
        self.pulled = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.when == "after":
            await request.aread()
            self.pulled.set()
        await asyncio.sleep(self.hang)
        raise self.exc


def reply(status: int, **kw: object):
    return lambda: KatFake(override=lambda r: httpx.Response(status, **kw))


def broken(status: int):
    """상태와 본문 앞부분까지 온 뒤 끊기는 응답."""
    async def chunks():
        yield b'{"code": "unau'
        raise httpx.ReadError("x")

    return lambda: KatFake(override=lambda r: httpx.Response(status, content=chunks()))


SENT_TABLE = [  # (전송을 만드는 함수, code, maybe_sent) — 시험 문자(P2) 한 건을 보냈을 때
    # 본문이 나갔고 깨끗한 거절이 아니다 → 갔을 수 있다
    (reply(500), "server", True), (reply(502, content=b"<html>"), "server", True), (reply(504), "server", True),
    (reply(409), "bad_request", True), (reply(302, headers={"location": "https://elsewhere.invalid/"}), "bad_request", True),
    (reply(201, json={"status": "queued"}), "unknown", True), (reply(200, content=b"<html>ok</html>"), "unknown", True),
    (reply(201, json=["MG1"]), "unknown", True), (reply(204), "unknown", True),
    (reply(201, content=b'{"messageId": "' + b"a" * 1_000_001 + b'"}'), "unknown", True),
    (reply(201, content=b"\x1f\x8b\x08", headers={"content-encoding": "gzip"}), "unknown", True),
    (broken(201), "network", True), (broken(500), "server", True),
    (lambda: Breaks("after", httpx.ReadTimeout("x")), "timeout", True), (lambda: Breaks("after", httpx.WriteTimeout("x")), "timeout", True),
    (lambda: Breaks("after", httpx.ReadError("x")), "network", True),
    (lambda: Breaks("after", httpx.RemoteProtocolError("x")), "network", True),
    (lambda: Breaks("after", RuntimeError("x")), "unknown", True), (lambda: Breaks("after", hang=2), "timeout", True),
    # 본문이 나가기 전에 끝났다 → 가지 않았다
    (lambda: Breaks("before", httpx.ConnectError("x")), "network", False),
    (lambda: Breaks("before", httpx.ConnectTimeout("x")), "timeout", False),
    (lambda: Breaks("before", httpx.PoolTimeout("x")), "timeout", False),
    (lambda: Breaks("before", httpx.WriteError("x")), "network", False), (lambda: Breaks("before", hang=2), "timeout", False),
    # 깨끗한 거절(409 밖의 4xx) → 가지 않았다
    (reply(400, json={"code": "invalid_phone"}), "bad_request", False), (reply(400, json={"code": "from_not_registered"}), "bad_sender", False),
    (reply(401, json={"code": "unauthorized"}), "bad_key", False), (reply(403), "bad_account", False),
    (reply(403, json={"code": "overseas_ip_blocked"}), "overseas_ip", False), (reply(404), "bad_account", False),
    (reply(422, json={"code": "quota_exceeded"}), "bad_request", False), (reply(429, headers={"retry-after": "30"}), "rate_limited", False),
    (broken(401), "bad_key", False), (broken(400), "bad_request", False),
]


@pytest.mark.parametrize(("make", "code", "maybe"), SENT_TABLE)
async def test_test_sms_says_whether_it_may_have_gone_out(make, code, maybe, monkeypatch):
    """P2 의 `maybe_sent`: 본문이 나갔고 깨끗한 거절이 아니면 참 — 그냥 실패로 보이면 사람이 한 번 더 눌러 진짜 문자가 또 간다.
    제공사 호출(KatClient.send_message)과 같은 구현이라 같은 표를 통과한다."""
    from app.outreach import provider
    from app.outreach.provider import (
        KatClient,
        MessageRequest,
        ProviderConn,
        ProviderFailed,
    )

    monkeypatch.setattr(diagnostics, "TIMEOUT_S", 0.3)
    monkeypatch.setattr(provider, "TIMEOUT_S", 0.3)
    calls = Calls()
    async with make_client(transport=make()) as http:
        step, mid = await check_send_sms(CONN, http, send_test_sms=True, calls=calls)
    assert (step.ok, mid, step.skipped, step.pending) == (False, None, False, False)
    assert (step.code, step.maybe_sent, calls.maybe_sent) == (code, maybe, maybe)
    assert (diagnostics.MAYBE_SENT in step.detail) is maybe and readable(step), step.detail
    assert_clean([step])

    request = MessageRequest(channel="sms", to=TO, sender=FROM, body="시험", idempotency_key="idem-0001")
    with pytest.raises(ProviderFailed) as caught:
        await KatClient(ProviderConn(DEFAULT_BASE_URL, ACCOUNT, SENTINEL_KEY), transport=make()).send_message(request)
    assert (caught.value.code, caught.value.maybe_sent) == (code, maybe)


async def test_accepted_test_sms_is_not_a_maybe():
    calls = Calls()
    async with client(KatFake()) as http:
        step, mid = await check_send_sms(CONN, http, send_test_sms=True, calls=calls)
    assert (step.ok, step.code, step.maybe_sent, calls.maybe_sent, mid) == (True, "ok", False, False, MSG_ID)
    assert step.detail == "시험 문자가 접수됐습니다." and any("HTTP 201" in n for n in step.notes)  # 기계 글은 접어 보이는 줄에


@pytest.mark.parametrize(("when", "maybe"), [("after", True), ("before", False)])
async def test_cut_off_diagnosis_leaves_whether_the_sms_went_out_on_calls(when, maybe):
    """진단이 끊기면(취소·전체 시간 초과) 걸음은 돌아오지 않는다 — 부른 쪽은 넘겨 준 `Calls.maybe_sent` 로 안다."""
    transport, calls = Breaks(when, hang=3), Calls()
    async with make_client(transport=transport) as http:
        task = asyncio.ensure_future(check_send_sms(CONN, http, send_test_sms=True, calls=calls))
        await asyncio.wait_for(transport.pulled.wait(), 2) if when == "after" else await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls.maybe_sent is maybe and calls.sent == 1


async def test_still_queued_after_the_polls_is_pending_not_failed():
    async with client(KatFake(statuses=("queued",))) as http:
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep)
    p2, p3 = results[1], results[2]
    assert p2.ok and (p3.ok, p3.pending, p3.code, p3.skipped, p3.maybe_sent) == (False, True, "still_queued", False, False)
    assert p3.detail.startswith("접수됨 — 통신사로 넘어가기를 기다리는 중") and readable(p3)
    assert any("status=queued" in n for n in p3.notes)

    async with client(KatFake(statuses=("queued", "failed"))) as http:
        failed = await check_message_status(CONN, http, MSG_ID, sleep=no_sleep, calls=Calls())
    assert (failed.ok, failed.pending, failed.code) == (False, False, "delivery_failed")  # 진짜 실패는 실패다
    assert failed.detail == "접수됨 → 실패 — 단말기 전원이 꺼져 있습니다." and readable(failed)


async def test_steps_not_asked_for_come_back_as_skipped_rows():
    fake = KatFake()
    async with client(fake) as http:
        results = await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, steps=("P2", "p3"))
    assert [(r.id, r.skipped, r.code) for r in results] == [
        ("P1", True, "skipped_not_requested"), ("P2", False, "ok"), ("P3", False, "ok"), ("P4", True, "skipped_not_requested")]
    assert results[0].detail == results[3].detail == "이번에는 확인하지 않았습니다." and not results[0].ok
    assert len(fake.requests) == 3 and all(r.label == diagnostics.LABELS[r.id] for r in results)  # 보내기 + 조회 둘
    bad = DiagnosticConn(base_url="http://127.0.0.1", key=SENTINEL_KEY, account_id=ACCOUNT)
    async with client(fake) as http:
        results = await run_checks(bad, http, steps=(1,))
    assert [(r.skipped, r.code) for r in results] == [(False, "bad_base_url")] + [(True, "skipped_not_requested")] * 3


async def test_every_text_shown_to_a_person_is_a_plain_sentence(monkeypatch):
    """label·detail 은 화면에 그대로 나온다 — 코드 낱말·예외 이름·칸 이름은 code 와 notes 에만."""
    seen: dict[str, str] = {}

    def keep(*steps) -> None:
        for step in steps:
            assert readable(step) and re.search(r"[가-힣]", step.label), (step.code, step.detail)
            seen[step.code] = step.detail

    async def run(fake, conn=CONN, **kw) -> None:
        async with client(fake) as http:
            keep(*await run_checks(conn, http, sleep=no_sleep, **kw))

    await run(KatFake())  # 연결 테스트(보내지 않음)
    await run(KatFake(statuses=("queued", "sent")), send_test_sms=True)
    await run(KatFake(statuses=("queued",)), send_test_sms=True)
    await run(KatFake(statuses=("failed",)), send_test_sms=True)
    await run(KatFake(statuses=("on-hold",)), send_test_sms=True)
    await run(KatFake(), DiagnosticConn(DEFAULT_BASE_URL, SENTINEL_KEY, ACCOUNT, sender=FROM), send_test_sms=True)
    await run(KatFake(), steps=(1,))
    for conn in (DiagnosticConn("http://x.example", SENTINEL_KEY, ACCOUNT), DiagnosticConn(DEFAULT_BASE_URL, "short", ACCOUNT),
                 DiagnosticConn(DEFAULT_BASE_URL, SENTINEL_KEY, ""), DiagnosticConn(None, SENTINEL_KEY, ACCOUNT)):  # type: ignore[arg-type]
        await run(KatFake(), conn)
    for make, _code, _maybe in SENT_TABLE:
        monkeypatch.setattr(diagnostics, "TIMEOUT_S", 0.3)
        async with make_client(transport=make()) as http:
            keep(*await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep))
    for override in (lambda r: httpx.Response(200, json={"data": 1}), lambda r: httpx.Response(200, json=[]),
                     lambda r: httpx.Response(404, json={"code": "not_found"})):
        await run(KatFake(override=override))
    async with httpx.AsyncClient(transport=KatFake()) as http:  # trust_env 를 끄지 않은 클라이언트
        keep(*await run_checks(CONN, http))
    calls = Calls()
    calls.sent = MAX_REQUESTS - 1
    async with client(KatFake()) as http:
        keep(*await run_checks(CONN, http, send_test_sms=True, sleep=no_sleep, calls=calls))
        keep(*await run_checks(CONN, http, resolve=lambda h, p: ["10.0.0.1"]))
        keep(await check_senders(CONN, http, calls=calls, resolve=lambda h, p: []))
    assert {"ok", "skipped_not_requested", "skipped_no_send", "skipped_no_numbers", "skipped_no_message", "still_queued",
            "delivery_failed", "request_limit", "untrusted_client", "bad_base_url", "bad_key", "bad_account", "bad_sender",
            "overseas_ip", "rate_limited", "timeout", "network", "bad_request", "server", "unknown"} <= set(seen)
    assert seen["bad_key"] in (diagnostics.MESSAGES["bad_key"], "API 키가 너무 짧습니다(8자 이상).")


def test_failure_texts_come_from_the_one_table_the_provider_client_uses():
    from app.outreach import provider

    assert provider._MESSAGES is diagnostics.MESSAGES and provider._VENDOR is diagnostics.VENDOR
    assert provider._FAILURES is diagnostics.FAILURES and provider._NOT_SENT is diagnostics.NOT_SENT
    assert diagnostics.http_failure(401, None) == ("bad_key", diagnostics.MESSAGES["bad_key"])
    assert diagnostics.http_failure(403, "overseas_ip_blocked") == ("overseas_ip", diagnostics.MESSAGES["overseas_ip"])
    assert diagnostics.http_failure(404, None, on_item=True)[0] == "bad_request"


async def test_our_own_error_inside_a_step_shows_no_exception_name():
    odd = {"senderNumbers": [{"number": FROM, "status": ["approved"]}]}  # 상태가 글이 아니다 — 걸음 안에서 TypeError 가 난다
    async with client(KatFake(override=lambda r: httpx.Response(200, json=odd))) as http:
        result = await check_senders(CONN, http, calls=Calls())
    assert (result.ok, result.code, result.detail) == (False, "unknown", diagnostics.MESSAGES["unknown"])
    assert any("TypeError" in n for n in result.notes) and readable(result)
