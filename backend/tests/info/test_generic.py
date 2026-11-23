"""범용 정보 API 호출(app.info.generic): 경로·주소 검사, 키 붙이기, 키 지우기, 리다이렉트·크기·시간 한도, XML → JSON 꼴.

네트워크를 쓰지 않는다(TRANSPORT·RESOLVE 를 가짜로). 값은 모두 가상이다.
"""

import asyncio
import json
import logging

import httpx
import pytest

from app.info import generic, kma
from app.info.generic import GenericConn, GenericFailed
from tests.info_doubles import (
    BASE,
    HOLIDAY_XML,
    HOST,
    KEY,
    KEY_ENCODED,
    PUBLIC_IP,
    ApiMock,
    holiday_body,
    public,
)
from tests.kma_doubles import gateway_body, gateway_xml

NAME = "공휴일"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """가짜를 고르지 않은 시험이 부르면 599. 이름 풀이는 늘 공인 IP."""
    monkeypatch.setattr(generic, "TRANSPORT", ApiMock((599, {})))
    monkeypatch.setattr(generic, "RESOLVE", public)


@pytest.fixture
def use(monkeypatch):
    def install(mock: ApiMock) -> ApiMock:
        monkeypatch.setattr(generic, "TRANSPORT", mock)
        return mock

    return install


def conn(key: str = KEY, key_in: str = "query", key_name: str = "serviceKey", base_url: str = BASE) -> GenericConn:
    return GenericConn(name=NAME, base_url=base_url, key=key, key_in=key_in, key_name=key_name)


# ── 경로 검사(부르기 전) ─────────────────────────────────────────────


@pytest.mark.parametrize("path", [
    "getRestDeInfo", "https://evil.example/x", "/x?u=http://evil.example", "//evil.example/x", "/a/../b",
    "/a/%2e%2E/b", "/a@evil.example", "/a\\b", "/a\nb", "/a\x00b", "/a\x7fb", "/a#frag", "",
])
def test_bad_paths_are_refused_in_korean(path):
    problem = generic.request_problem(path, {}, "serviceKey")
    assert problem and any("가" <= ch <= "힣" for ch in problem)


@pytest.mark.parametrize("path", ["/getRestDeInfo", "/getRestDeInfo?solYear=2026&_type=json", "/a/b.json", "/"])
def test_good_paths_pass(path):
    assert generic.request_problem(path, {"solMonth": "12"}, "serviceKey") is None


@pytest.mark.parametrize(("path", "params", "key_name"), [
    ("/x", {"serviceKey": "x"}, "serviceKey"), ("/x", {"SERVICEKEY": "x"}, "serviceKey"),
    ("/x?servicekey=abc", {}, "serviceKey"), ("/op?serviceKey=x", {}, "ServiceKey"),
    ("/op?a=1&ServiceKey=x", {}, "serviceKey"), ("/op?service%4Bey=x", {}, "ServiceKey"),
    ("/op", {"servicekey": "x"}, "ServiceKey"),
])
def test_key_name_in_params_or_path_query_is_refused_whatever_the_case(path, params, key_name):
    assert "키" in generic.request_problem(path, params, key_name)


# ── 주소 검사 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "ftp://apis.data.go.kr/x", "http://localhost:8000", "http://LOCALHOST", "http://api.localhost", "http://127.0.0.1",
    "http://127.1", "http://2130706433", "http://10.0.0.5", "http://172.16.3.4", "http://192.168.0.10",
    "http://169.254.169.254", "http://100.64.1.2", "http://0.0.0.0", "http://224.0.0.1", "http://[::1]:8080",
    "http://[fe80::1]", "http://[fc00::1]", "http://[::]", "http://[ff02::1]", "http://[::ffff:127.0.0.1]",
])
def test_internal_base_urls_are_refused(url):
    problem = generic.base_url_problem(url)
    assert problem and any("가" <= ch <= "힣" for ch in problem)


@pytest.mark.parametrize("url", [BASE, "http://93.184.216.34/api", "https://[2001:4860:4860::8888]/x"])
def test_public_base_urls_pass(url):
    assert generic.base_url_problem(url) is None


async def test_a_host_resolving_to_a_private_address_is_not_called(use, monkeypatch):
    mock = use(ApiMock())
    asked = []

    def resolve(host, port):
        asked.append((host, port))
        return [PUBLIC_IP, "10.1.2.3"]

    monkeypatch.setattr(generic, "RESOLVE", resolve)
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/getRestDeInfo", {})
    assert e.value.code == "blocked_host" and "내부망" in e.value.message
    assert asked == [(HOST, 443)] and mock.requests == []


async def test_dns_failure_is_reported_without_calling(use, monkeypatch):
    mock = use(ApiMock())

    def broken(host, port):
        raise OSError("nodename nor servname provided")

    monkeypatch.setattr(generic, "RESOLVE", broken)
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/getRestDeInfo", {})
    assert e.value.code == "bad_url" and mock.requests == []


async def test_saved_internal_base_url_is_checked_again_at_call_time(use):
    mock = use(ApiMock())
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(base_url="http://127.0.0.1:8210"), "/x", {})
    assert e.value.code == "blocked_host" and mock.requests == []


async def test_final_url_must_stay_on_the_base_host(use, monkeypatch):
    """경로 검사를 빼도(가정) 만든 주소의 scheme·host·port 를 다시 맞춘다: 'https://a.kr' + '@evil' → host evil."""
    mock = use(ApiMock())
    monkeypatch.setattr(generic, "request_problem", lambda *a: None)
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(base_url="https://apis.data.go.kr"), "@evil.example/x", {})
    assert e.value.code == "bad_path" and mock.requests == []


# ── 키 붙이기 ────────────────────────────────────────────────────────


async def test_decoded_query_key_is_encoded_once(use):
    mock = use(ApiMock())
    got = await generic.fetch(conn(KEY), "/getRestDeInfo", {"solYear": "2026", "solMonth": "12"})
    sent = mock.requests[0].url
    assert sent.host == HOST and sent.path == "/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
    assert f"serviceKey={KEY_ENCODED}&" in sent.query.decode() and "solYear=2026&solMonth=12" in sent.query.decode()
    assert mock.requests[0].method == "GET"
    assert got.http_status == 200 and "serviceKey" not in got.url and KEY_ENCODED not in got.url
    assert got.url == f"{BASE}/getRestDeInfo?solYear=2026&solMonth=12"


async def test_encoded_query_key_is_sent_as_is(use):
    mock = use(ApiMock())
    await generic.fetch(conn(KEY_ENCODED), "/getRestDeInfo?_type=json", {})
    assert mock.requests[0].url.query.decode() == f"_type=json&serviceKey={KEY_ENCODED}"


async def test_key_name_case_is_kept(use):
    mock = use(ApiMock())
    await generic.fetch(conn(key_name="ServiceKey"), "/getRestDeInfo", {"solYear": "2026"})
    assert mock.requests[0].url.query.decode().startswith(f"ServiceKey={KEY_ENCODED}&")


AIR_TEST_PATH = "/getCtprvnRltmMesureDnsty?sidoName=%EC%84%9C%EC%9A%B8&returnType=json&numOfRows=1&pageNo=1&ver=1.0"


async def test_an_already_encoded_path_query_is_not_encoded_again(use):
    mock = use(ApiMock())
    got = await generic.fetch(conn(base_url="https://apis.data.go.kr/B552584/ArpltnInforInqireSvc"), AIR_TEST_PATH, {})
    sent = str(mock.requests[0].url)
    assert sent.count("%EC%84%9C%EC%9A%B8") == 1 and "%25EC" not in sent
    assert got.url.count("%EC%84%9C%EC%9A%B8") == 1 and "%25" not in got.url


async def test_raw_params_and_raw_korean_path_are_encoded_once(use):
    mock = use(ApiMock())
    await generic.fetch(conn(), "/getCtprvnRltmMesureDnsty?sidoName=서울", {"stationName": "종로구", "q": "a b&c"})
    query = mock.requests[0].url.query.decode()
    assert "sidoName=%EC%84%9C%EC%9A%B8" in query and "stationName=%EC%A2%85%EB%A1%9C%EA%B5%AC" in query
    assert "q=a+b%26c" in query and "%25" not in query.replace(KEY_ENCODED, "")


async def test_header_key_goes_in_the_named_header_only(use):
    mock = use(ApiMock())
    await generic.fetch(conn(KEY, key_in="header", key_name="Authorization"), "/getRestDeInfo", {"a": "1"})
    request = mock.requests[0]
    assert request.headers["Authorization"] == KEY
    assert KEY not in str(request.url) and KEY_ENCODED not in str(request.url)


# ── 응답 읽기 ────────────────────────────────────────────────────────


async def test_json_body_is_returned_as_json_text(use):
    use(ApiMock((200, holiday_body())))
    got = await generic.fetch(conn(), "/getRestDeInfo", {})
    assert json.loads(got.text) == holiday_body() and "application/json" in got.content_type and not got.cut


async def test_xml_body_is_turned_into_json_like_data(use):
    use(ApiMock((200, HOLIDAY_XML)))
    got = await generic.fetch(conn(), "/getRestDeInfo", {})
    data = json.loads(got.text)
    items = data["response"]["body"]["items"]["item"]
    assert [i["dateName"] for i in items] == ["기독탄신일", "신정"] and items[0]["locdate"] == "20261225"
    assert data["response"]["header"] == {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}


def test_xml_conversion_keeps_attributes_and_drops_namespaces():
    data = generic.xml_to_data('<a:r xmlns:a="urn:x"><a:i n="1">x</a:i><a:i>y</a:i><e/></a:r>')
    assert data == {"r": {"i": [{"@n": "1", "#text": "x"}, "y"], "e": ""}}


@pytest.mark.parametrize("text", [
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">]><r>&a;&a;</r>',
    '<!doctype r SYSTEM "file:///etc/passwd"><r/>',
    "<r>" + "<a>" * 200 + "</a>" * 200 + "</r>",
    "<r>" + "<i/>" * 30_000 + "</r>",
    "<r><unclosed></r>",
])
def test_risky_or_broken_xml_is_not_converted(text):
    with pytest.raises(ValueError):
        generic.xml_to_data(text)


async def test_doctype_body_comes_back_as_plain_text_without_expansion(use):
    body = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "EXPANDED">]><r>&a;</r>'
    use(ApiMock((200, body)))
    got = await generic.fetch(conn(), "/x", {})
    assert got.text == body and "EXPANDED</r>" not in got.text


async def test_body_reading_stops_at_300kb(use):
    sent = []

    async def chunks():
        for _ in range(100):
            sent.append(1)
            yield b"x" * 10_000

    use(ApiMock(lambda request: httpx.Response(200, content=chunks(), headers={"content-type": "text/plain"})))
    got = await generic.fetch(conn(), "/x", {})
    assert got.cut and len(got.text) == generic.MAX_BYTES and len(sent) <= 32
    assert generic.MAX_BYTES == 300 * 1024


def test_model_body_is_cut_at_3500_with_a_korean_hint():
    body, truncated = generic.body_for_model("가" * 10_000, cut=False)
    assert truncated and len(body) <= 3500 and body.endswith(generic.TRUNCATED_HINT) and "범위를 좁혀" in body
    assert generic.body_for_model("짧은 글", cut=False) == ("짧은 글", False)
    assert generic.body_for_model("짧은 글", cut=True)[1] is True


# ── 실패 ────────────────────────────────────────────────────────────


async def test_redirects_are_not_followed(use):
    mock = use(ApiMock(httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "redirect" and "리다이렉트" in e.value.message and e.value.http_status == 302
    assert len(mock.requests) == 1


@pytest.mark.parametrize(("status", "body"), [
    (403, gateway_body("30")), (200, gateway_body("30")), (200, gateway_xml("30")), (403, gateway_xml("30")),
])
async def test_portal_gateway_envelope_uses_the_kma_messages(use, status, body):
    use(ApiMock((status, body)))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "not_registered"
    assert e.value.message == kma.FAILED_MESSAGES["not_registered"].replace("기상청", NAME)
    assert e.value.http_status == status and "returnReasonCode" in e.value.sample


@pytest.mark.parametrize(("code", "expected"), [
    ("31", "key_expired"), ("32", "ip_not_allowed"), ("22", "rate_limited"), ("20", "bad_key"), ("99", "unknown"),
])
async def test_gateway_reason_codes_share_the_kma_table(use, code, expected):
    use(ApiMock((200, gateway_body(code))))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == expected
    assert e.value.message == kma.FAILED_MESSAGES[expected].replace("기상청", NAME)


@pytest.mark.parametrize(("status", "code"), [(404, "bad_url"), (401, "bad_key"), (429, "rate_limited"),
                                              (500, "server_error"), (418, "unknown")])
async def test_http_errors(use, status, code):
    use(ApiMock((status, {"error": "x"})))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert (e.value.code, e.value.http_status) == (code, status)


async def test_timeout_is_15_seconds_overall(use, monkeypatch):
    assert generic.TIMEOUT_S == 15.0

    async def slow(request):
        await asyncio.sleep(5)

    use(ApiMock(slow))
    monkeypatch.setattr(generic, "TIMEOUT_S", 0.05)
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "timeout"


async def test_read_timeout(use):
    use(ApiMock(httpx.ReadTimeout("slow")))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "timeout"


# ── 키 지우기 ────────────────────────────────────────────────────────


def test_scrub_hides_the_key_parameter_value_whatever_the_case():
    text = "GET https://a.kr/x?SERVICEKEY=other-value&q=1 servicekey=v2"
    out = generic.scrub(text, KEY, key_name="ServiceKey")
    assert "other-value" not in out and "v2" not in out and "q=1" in out


def test_scrub_removes_raw_encoded_and_decoded_forms():
    lower = KEY_ENCODED.lower()
    text = f"a {KEY} b {KEY_ENCODED} c {lower} d {KEY.replace('/', chr(92) + '/')} e {KEY.replace('+', ' ')}"
    out = generic.scrub(text, KEY)
    for form in (KEY, KEY_ENCODED, lower, "zyxwVUTSrqpo"):
        assert form not in out
    assert generic.scrub(text, KEY_ENCODED) == out


async def test_key_planted_in_the_body_is_removed(use):
    use(ApiMock((200, {"echo": KEY, "echo2": KEY_ENCODED, "url": f"{BASE}?serviceKey={KEY_ENCODED}"})))
    got = await generic.fetch(conn(), "/x", {})
    assert KEY not in got.text and KEY_ENCODED not in got.text and "zyxwVUTSrqpo" not in got.text


@pytest.mark.parametrize("error", [httpx.ConnectError(f"cannot reach {BASE}?serviceKey={KEY_ENCODED}"),
                                   RuntimeError(f"boom {KEY}")])
async def test_key_in_an_exception_message_never_leaves(use, caplog, error):
    caplog.set_level(logging.DEBUG)
    use(ApiMock(error))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    text = f"{e.value} {e.value.message} {e.value.sample} {e.value.__cause__} {e.value.__context__} {caplog.text}"
    assert KEY not in text and KEY_ENCODED not in text and "zyxwVUTSrqpo" not in text


@pytest.mark.parametrize("key_name", ["serviceKey", "ServiceKey", "authKey"])
async def test_httpx_request_log_line_hides_the_key(use, caplog, key_name):
    caplog.set_level(logging.DEBUG)
    use(ApiMock())
    await generic.fetch(conn(key_name=key_name), "/x", {"q": "1"})
    assert "HTTP Request: GET" in caplog.text and f"{key_name}=" in caplog.text
    assert KEY not in caplog.text and KEY_ENCODED not in caplog.text and "zyxwVUTSrqpo" not in caplog.text


# ── 보안 검토 반영(1차) ─────────────────────────────────────────────


def test_model_body_is_budgeted_by_its_json_escaped_length():
    """따옴표·역빗금이 많은 본문도 JSON 으로 옮겼을 때 한도 안이다(도구 결과 4,000자 안에 evidence_id 가 남게)."""
    for text in ('"' * 5000, "\\" * 5000, '{"a": "b"}' * 600, "가" * 9000):
        body, truncated = generic.body_for_model(text, cut=False)
        assert truncated and len(json.dumps(body, ensure_ascii=False)) <= generic.BODY_LIMIT
        assert body.endswith(generic.TRUNCATED_HINT)
    body, truncated = generic.body_for_model('"' * 1000, cut=False)
    assert body == '"' * 1000 and not truncated


def _gzip_bomb(size: int) -> bytes:
    import zlib

    packer = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    zeros = b"\0" * (1024 * 1024)
    return b"".join(packer.compress(zeros) for _ in range(size // len(zeros))) + packer.flush()


async def test_a_gzip_bomb_never_expands_past_the_cap(use, monkeypatch):
    import zlib

    bomb = _gzip_bomb(64 * 1024 * 1024)
    produced = []
    real = zlib.decompressobj

    class Spy:
        def __init__(self, *a):
            self.inner = real(*a)

        def decompress(self, data, max_length=0):
            out = self.inner.decompress(data, max_length)
            produced.append(len(out))
            assert max_length, "max_length 없이 풀면 안 된다"
            return out

        def __getattr__(self, name):
            return getattr(self.inner, name)

    async def socket_chunks():  # 실제 소켓처럼 64KB 씩(미리 풀리지 않게 흐름으로)
        for i in range(0, len(bomb), 65536):
            yield bomb[i:i + 65536]

    monkeypatch.setattr(generic.zlib, "decompressobj", Spy)
    use(ApiMock(lambda request: httpx.Response(200, content=socket_chunks(),
                                               headers={"content-encoding": "gzip", "content-type": "text/plain"})))
    got = await generic.fetch(conn(), "/x", {})
    assert got.cut and len(got.text) == generic.MAX_BYTES
    assert sum(produced) <= generic.MAX_BYTES + 1


@pytest.mark.parametrize("wbits", [16 + 15, 15, -15])  # gzip · zlib 감싼 deflate · 날 deflate
async def test_compressed_bodies_are_read(use, wbits):
    import zlib

    packer = zlib.compressobj(6, zlib.DEFLATED, wbits)
    raw = json.dumps(holiday_body()).encode()
    encoding = "gzip" if wbits > 15 else "deflate"
    packed = packer.compress(raw) + packer.flush()

    async def body():
        yield packed

    use(ApiMock(lambda request: httpx.Response(200, content=body(), headers={
        "content-encoding": encoding, "content-type": "application/json"})))
    got = await generic.fetch(conn(), "/x", {})
    assert json.loads(got.text) == holiday_body()


async def test_an_unknown_content_encoding_is_refused(use):
    use(ApiMock(httpx.Response(200, content=b"\x1b\x00", headers={"content-encoding": "br"})))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "bad_encoding" and "압축" in e.value.message


async def test_content_type_is_scrubbed_and_cut(use):
    use(ApiMock(httpx.Response(200, json={"a": 1}, headers={"content-type": f"application/json; echo={KEY}"})))
    got = await generic.fetch(conn(), "/x", {})
    assert KEY not in got.content_type and "zyxwVUTSrqpo" not in got.content_type
    use(ApiMock(httpx.Response(200, content=b"{}", headers={"content-type": "x/" + "A" * 20000})))
    assert len((await generic.fetch(conn(), "/x", {})).content_type) <= 100


MIXED = {
    "plus only as %2B": KEY.replace("+", "%2B"),
    "html &#43;": KEY.replace("+", "&#43;"),
    "html &#x2F;": KEY.replace("/", "&#x2F;"),
    "double encoded": KEY_ENCODED.replace("%", "%25"),
    "json \\u002b": KEY.replace("+", "\\u002b"),
    "slash only encoded": KEY.replace("/", "%2f"),
}


@pytest.mark.parametrize("form", MIXED.values(), ids=MIXED.keys())
def test_scrub_catches_mixed_forms(form):
    for key in (KEY, KEY_ENCODED):
        out = generic.scrub(f"prefix {form} suffix", key)
        assert "zyxwVUTSrqpo" not in out and out.startswith("prefix ") and out.endswith(" suffix")


@pytest.mark.parametrize("form", [KEY.replace("+", "&amp;#43;"), KEY.replace("+", "%25252B")])
async def test_a_body_still_holding_the_key_after_decoding_is_dropped(use, form):
    use(ApiMock((200, f"request was /x?sk={form}&q=1", {"content-type": "text/plain"})))
    got = await generic.fetch(conn(), "/x", {})
    assert got.text == generic.KEY_IN_BODY and "zyxwVUTSrqpo" not in got.text


async def test_failure_sample_holding_the_key_is_dropped(use):
    use(ApiMock((500, f"error for key {KEY.replace('+', '&amp;#43;')}", {"content-type": "text/plain"})))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert "zyxwVUTSrqpo" not in (e.value.sample or "")


def test_mask_has_no_space_so_no_leftover_after_the_key_name_pass():
    assert " " not in generic.MASK
    assert generic.scrub(f"serviceKey={KEY}&q=1", KEY, key_name="serviceKey") == f"serviceKey={generic.MASK}&q=1"


async def test_http_connections_go_to_the_validated_ip_with_the_host_header(use, monkeypatch):
    mock = use(ApiMock())
    answers = iter([[PUBLIC_IP], ["10.0.0.1"]])  # 두 번째로 풀면 내부망(리바인딩) — 다시 풀지 않아야 한다
    monkeypatch.setattr(generic, "RESOLVE", lambda host, port: next(answers))
    await generic.fetch(conn(base_url="http://api.example.kr/svc"), "/x", {"q": "1"})
    [sent] = mock.requests
    assert sent.url.host == PUBLIC_IP and sent.headers["host"] == "api.example.kr"
    assert sent.url.path == "/svc/x"


async def test_https_connections_keep_the_host_name(use):
    mock = use(ApiMock())
    await generic.fetch(conn(), "/x", {})
    assert mock.requests[0].url.host == HOST


@pytest.mark.parametrize("address", ["::7f00:1", "::a00:1", "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "fec0::1"])
def test_embedded_and_site_local_ipv6_are_not_public(address):
    assert generic._public(address) is False
    assert generic.base_url_problem(f"http://[{address}]/x") is not None


async def test_name_resolution_is_inside_the_15_second_budget(use, monkeypatch):
    import time

    def slow(host, port):
        time.sleep(0.5)
        return [PUBLIC_IP]

    mock = use(ApiMock())
    monkeypatch.setattr(generic, "RESOLVE", slow)
    monkeypatch.setattr(generic, "TIMEOUT_S", 0.05)
    start = time.perf_counter()
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "timeout" and time.perf_counter() - start < 0.4 and mock.requests == []


async def test_a_url_that_cannot_be_built_is_a_bad_path(use, caplog):
    mock = use(ApiMock())
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {f"p{i}": "가" * 500 for i in range(30)})
    assert e.value.code == "bad_path" and any("가" <= ch <= "힣" for ch in e.value.message)
    assert mock.requests == [] and "Traceback" not in caplog.text


@pytest.mark.parametrize("path", ["/a/%252e%252e/b", "/a%25/b", "/%25"])
def test_percent_25_in_the_path_part_is_refused(path):
    assert generic.request_problem(path, {}, "serviceKey")


def test_percent_25_in_a_query_value_is_fine():
    assert generic.request_problem("/x?q=%25EC%2584", {}, "serviceKey") is None


@pytest.mark.parametrize(("body", "expected"), [
    ({"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR."}}}, "not_registered"),
    ({"response": {"header": {"resultCode": "22"}}}, "rate_limited"),
    ({"response": {"header": {"resultCode": "33"}}}, "bad_key"),
    ({"response": {"header": {"resultCode": "00"}}}, None),
    ({"response": {"header": {"resultCode": "03"}}}, None),
    ({"response": {"header": {"resultCode": "10"}}}, None),
    ({"other": 1}, None),
])
def test_result_code_account_failures(body, expected):
    assert generic.result_code_failure(json.dumps(body)) == expected


async def test_header_mode_body_and_logs_hold_no_key(use, caplog):
    caplog.set_level(logging.DEBUG)
    use(ApiMock((200, {"echo": KEY, "auth": f"Bearer {KEY}"})))
    got = await generic.fetch(conn(key_in="header", key_name="Authorization"), "/x", {})
    assert "zyxwVUTSrqpo" not in got.text + got.url + caplog.text


# ── 재검토 작은 지적 ─────────────────────────────────────────────────


def _stream(*chunks: bytes):
    async def gen():
        for chunk in chunks:
            yield chunk

    return gen()


def _pack(data: bytes, wbits: int) -> bytes:
    import zlib

    packer = zlib.compressobj(6, zlib.DEFLATED, wbits)
    return packer.compress(data) + packer.flush()


def test_a_huge_numeric_character_reference_counts_as_a_surviving_key():
    assert generic.key_survives("<p>&#" + "1" * 4301 + ";</p>", KEY) is True


async def test_a_body_with_a_huge_numeric_reference_is_dropped_not_raised(use):
    use(ApiMock((200, "<p>&#" + "1" * 5000 + ";</p>", {"content-type": "text/html"})))
    got = await generic.fetch(conn(), "/x", {})
    assert got.text == generic.KEY_IN_BODY


async def test_a_lone_surrogate_in_a_json_body_leaves_as_valid_utf8(use):
    use(ApiMock((200, b'{"a": "\\ud800 x"}', {"content-type": "application/json"})))
    got = await generic.fetch(conn(), "/x", {})
    assert got.text.encode("utf-8") and "x" in got.text


async def test_reading_stops_when_the_gzip_stream_has_ended(use):
    junk_chunks = []

    async def body():
        yield _pack(b'{"a": 1}', 31)
        for _ in range(1000):  # 끝난 뒤 쓰레기 64MB — 읽지 않아야 한다
            junk_chunks.append(1)
            yield b"\xaa" * 65536

    use(ApiMock(lambda request: httpx.Response(200, content=body(), headers={
        "content-encoding": "gzip", "content-type": "application/json"})))
    got = await generic.fetch(conn(), "/x", {})
    assert json.loads(got.text) == {"a": 1} and len(junk_chunks) <= 1 and got.cut


@pytest.mark.parametrize("label", ["truncated", "two members"])
async def test_a_truncated_or_multi_member_gzip_is_marked_cut(use, label):
    whole = _pack(json.dumps({"items": ["가나다라"] * 400}, ensure_ascii=False).encode(), 31)
    data = whole[: len(whole) // 2] if label == "truncated" else _pack(b'{"a": 1}', 31) + _pack(b'{"b": 2}', 31)
    use(ApiMock(lambda request: httpx.Response(200, content=_stream(data), headers={"content-encoding": "gzip"})))
    assert (await generic.fetch(conn(), "/x", {})).cut is True


@pytest.mark.parametrize("wbits", [15, -15])
async def test_deflate_header_is_decided_after_two_bytes(use, wbits):
    packed = _pack(json.dumps(holiday_body()).encode(), wbits)
    use(ApiMock(lambda request: httpx.Response(200, content=_stream(packed[:1], packed[1:]), headers={
        "content-encoding": "deflate", "content-type": "application/json"})))
    got = await generic.fetch(conn(), "/x", {})
    assert json.loads(got.text) == holiday_body() and not got.cut


@pytest.mark.parametrize("encoding", ["UTF-8", "none", "identity", "", " Identity "])
async def test_a_content_encoding_that_is_not_compression_is_read_as_is(use, encoding):
    use(ApiMock(lambda request: httpx.Response(200, content=_stream(b'{"a": 1}'), headers={
        "content-encoding": encoding, "content-type": "application/json"})))
    assert json.loads((await generic.fetch(conn(), "/x", {})).text) == {"a": 1}


@pytest.mark.parametrize("encoding", ["br", "zstd", "compress", "gzip, gzip"])
async def test_real_but_unsupported_compression_still_fails(use, encoding):
    use(ApiMock(lambda request: httpx.Response(200, content=_stream(b"\x1f\x8b"), headers={
        "content-encoding": encoding})))
    with pytest.raises(GenericFailed) as e:
        await generic.fetch(conn(), "/x", {})
    assert e.value.code == "bad_encoding"


async def test_http_prefers_an_ipv4_among_the_validated_addresses(use, monkeypatch):
    mock = use(ApiMock())
    monkeypatch.setattr(generic, "RESOLVE", lambda host, port: ["2001:4860:4860::8888", PUBLIC_IP])
    await generic.fetch(conn(base_url="http://api.example.kr/svc"), "/x", {})
    assert mock.requests[0].url.host == PUBLIC_IP


def test_fit_json_budgets_by_escaped_length():
    text, cut = generic.fit_json(('예: /getX?a=1&b="값"\n' * 200)[:3000], 1000, " …(줄임)")
    assert cut and len(json.dumps(text, ensure_ascii=False)) <= 1000 and text.endswith(" …(줄임)")
    assert generic.fit_json("짧다", 1000, " …") == ("짧다", False)
