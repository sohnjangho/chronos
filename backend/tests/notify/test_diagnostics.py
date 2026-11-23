"""Task 59 — 연결 진단(P1~P4) 함수. 실제 제공사를 부르지 않는다(httpx.MockTransport).

응답 모양은 한국AI통신 공개 문서(api-reference/claw-ops-api/…)의 칸 이름을 따른 가상 값이다.
"""

import json
from dataclasses import asdict

import httpx

from app.notify.diagnostics import (
    DEFAULT_BASE_URL,
    MAX_REQUESTS,
    Calls,
    DiagnosticConn,
    check_message_status,
    check_received,
    check_send_sms,
    check_senders,
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


def client(fake: KatFake) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=fake, trust_env=False, follow_redirects=False)


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
        result, mid = await check_send_sms(CONN, http)
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
        result = await check_message_status(CONN, http, MSG_ID, sleep=no_sleep)
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
        result = await check_senders(CONN, http)
    assert not result.ok and result.detail.startswith("unauthorized")
    assert any("bad key" in n for n in result.notes)
    assert_clean([result])


async def test_network_error_gives_type_only():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} key {SENTINEL_KEY}")

    async with client(KatFake(override=boom)) as http:
        result = await check_received(CONN, http)
    assert not result.ok and result.detail == "ConnectError"
    assert "cannot reach" not in json.dumps(asdict(result), ensure_ascii=False)
    assert_clean([result])


async def test_redirect_is_not_followed_even_if_client_would():
    fake = KatFake(override=lambda r: httpx.Response(302, headers={"location": "https://elsewhere.example/x"}))
    async with httpx.AsyncClient(transport=fake, follow_redirects=True) as http:
        result = await check_senders(CONN, http)
    assert not result.ok and result.detail.startswith("http_302") and len(fake.requests) == 1


async def test_send_without_recipient_is_skipped():
    conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=SENTINEL_KEY, account_id=ACCOUNT, sender=FROM, test_to="")
    fake = KatFake()
    async with client(fake) as http:
        result, mid = await check_send_sms(conn, http, send_test_sms=True)
    assert result.skipped and mid is None and fake.requests == []
