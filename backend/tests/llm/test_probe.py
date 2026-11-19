import httpx
import pytest

from app.llm.connections import _client, normalize_base_url, probe
from app.llm.errors import InvalidBaseUrl, LlmError, explain

URL = "https://platform.liner.com/api/v1"


def _probe(handler, base_url=URL, secret="k"):
    return probe(base_url, secret, transport=httpx.MockTransport(handler))


def test_ok_lists_model_ids():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "liner-mark"}, {"id": "liner-claude-router"}]})

    result = _probe(handler, base_url=URL + "/")
    assert result.ok is True and result.error is None
    assert result.models == ["liner-mark", "liner-claude-router"]
    assert seen[0].url == httpx.URL(URL + "/models")
    assert seen[0].headers["Authorization"] == "Bearer k"
    assert seen[0].extensions["timeout"]["read"] == 10


@pytest.mark.parametrize(
    "status,code",
    [(401, "bad_key"), (403, "bad_key"), (429, "rate_limited"), (404, "bad_url"), (500, "server_error")],
)
def test_status_codes_are_explained(status, code):
    result = _probe(lambda request: httpx.Response(status))
    assert result.ok is False and result.models == [] and result.error.code == code


@pytest.mark.parametrize(
    "exc,code",
    [
        (httpx.ConnectError("dns"), "bad_url"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
    ],
)
def test_transport_errors_are_explained(exc, code):
    def handler(request):
        raise exc

    assert _probe(handler).error.code == code


def test_bad_body_is_unknown():
    assert _probe(lambda request: httpx.Response(200, json={"x": 1})).error.code == "unknown"
    assert _probe(lambda request: httpx.Response(200, text="not json")).error.code == "unknown"


@pytest.mark.parametrize("base_url", ["ftp://platform.liner.com", "platform.liner.com", "https://", ""])
def test_invalid_base_url_never_sent(base_url):
    seen = []
    result = _probe(lambda request: seen.append(request) or httpx.Response(200), base_url=base_url)
    assert result.error.code == "bad_url" and seen == []


def test_messages():
    assert explain(httpx.ReadTimeout("x")) == LlmError("timeout", "응답이 너무 늦습니다.")
    assert explain(RuntimeError("x")) == LlmError("unknown", "연결에 실패했습니다.")
    request = httpx.Request("GET", URL)
    cases = {
        401: "API 키가 맞지 않습니다.",
        404: "주소에 연결할 수 없습니다.",
        429: "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요.",
    }
    for status, message in cases.items():
        response = httpx.Response(status, request=request)
        exc = httpx.HTTPStatusError("x", request=request, response=response)
        assert explain(exc).message == message


@pytest.mark.parametrize("secret", ["키값", "abcd\nefgh", "abcd efgh", "abcd\x00", "", "a" * 513])
def test_unsendable_secret_is_never_sent(secret):
    seen = []
    result = _probe(lambda request: seen.append(request) or httpx.Response(200), secret=secret)
    assert result.ok is False and result.error.code == "unknown" and seen == []


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:pw@platform.liner.com/api/v1",
        "https://platform.liner.com/api/v1?key=x",
        "https://platform.liner.com/api/v1#frag",
    ],
)
def test_userinfo_query_fragment_rejected(base_url):
    seen = []
    result = _probe(lambda request: seen.append(request) or httpx.Response(200), base_url=base_url)
    assert result.error.code == "bad_url" and seen == []
    with pytest.raises(InvalidBaseUrl) as info:
        normalize_base_url(base_url)
    assert str(info.value) == "주소에 사용자 정보나 물음표(?)·샵(#) 뒤 값은 넣을 수 없습니다."


def test_client_ignores_proxy_environment():
    with _client(None) as client:
        assert client.trust_env is False


def test_secret_not_in_result_repr():
    result = _probe(lambda request: httpx.Response(401), secret="abcd1234efgh5678")
    assert "abcd1234" not in repr(result)
