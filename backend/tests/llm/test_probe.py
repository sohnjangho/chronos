import httpx
import pytest

from app.llm.connections import (
    _client,
    normalize_base_url,
    normalize_models,
    price_of,
    probe,
)
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
    assert [m["id"] for m in result.models] == ["liner-mark", "liner-claude-router"]
    assert seen[0].url == httpx.URL(URL + "/models")
    assert seen[0].headers["Authorization"] == "Bearer k"
    assert seen[0].extensions["timeout"]["read"] == 10


LINER_SHAPED = {
    "data": [
        {"id": "liner-mark", "name": "Liner: Liner Mark", "owned_by": "liner", "context_length": 1048576,
         "endpoints": ["/v1/chat/completions", "/v1/responses"]},
        {"id": "google/gemini-4-neon", "name": "Google: Gemini 4 Neon", "owned_by": "google",
         "context_length": 1048576, "endpoints": ["/v1/chat/completions"]},
        {"id": "~anthropic/claude-x", "name": "Claude X"},
        {"id": "batch-thing", "owned_by": "openai", "endpoints": ["/v1/batches"]},
        {"id": "plain-model"},
    ]
}


def test_models_keep_metadata():
    """업체·업체 이름·문맥 길이·대화용 여부를 남긴다. 없는 값은 규칙대로 채운다."""
    result = _probe(lambda request: httpx.Response(200, json=LINER_SHAPED))
    assert result.models == [
        {"id": "liner-mark", "name": "Liner: Liner Mark", "vendor": "liner", "vendor_name": "Liner",
         "context_length": 1048576, "chat": True, "price": price_of("liner-mark")},
        {"id": "google/gemini-4-neon", "name": "Google: Gemini 4 Neon", "vendor": "google",
         "vendor_name": "Google", "context_length": 1048576, "chat": True, "price": None},
        {"id": "~anthropic/claude-x", "name": "Claude X", "vendor": "anthropic", "vendor_name": "Anthropic",
         "context_length": None, "chat": True, "price": None},
        {"id": "batch-thing", "name": "batch-thing", "vendor": "openai", "vendor_name": "OpenAI",
         "context_length": None, "chat": False, "price": None},
        {"id": "plain-model", "name": "plain-model", "vendor": "liner", "vendor_name": "Liner",
         "context_length": None, "chat": True, "price": None},
    ]


@pytest.mark.parametrize(
    "vendor,readable",
    [("liner", "Liner"), ("openai", "OpenAI"), ("anthropic", "Anthropic"), ("google", "Google"),
     ("meta-llama", "Meta Llama"), ("mistralai", "Mistral AI"), ("x-ai", "xAI"), ("deepseek", "DeepSeek"),
     ("qwen", "Qwen"), ("z-ai", "Z.ai"), ("microsoft", "Microsoft"), ("cohere", "Cohere"), ("nvidia", "NVIDIA"),
     ("amazon", "Amazon"), ("perplexity", "Perplexity"), ("moonshotai", "Moonshot AI"), ("minimax", "MiniMax"),
     ("some-new-lab", "Some-New-Lab")],
)
def test_vendor_names_are_readable_without_a_server_name(vendor, readable):
    """서버가 name 을 주지 않으면 id 를 ":" 로 자르지 않고, 업체 열쇠를 읽기 좋은 이름으로 바꾼다."""
    [model] = normalize_models([f"{vendor}/some-model:free"])
    assert model["vendor"] == vendor and model["vendor_name"] == readable
    assert model["name"] == f"{vendor}/some-model:free"


def test_one_vendor_name_per_vendor():
    """같은 업체의 모델은 한 업체 이름을 쓴다(가장 많이 나온 이름)."""
    body = {"data": [
        {"id": "meta-llama/a", "name": "Meta: Llama A", "owned_by": "meta-llama"},
        {"id": "meta-llama/b", "name": "Meta Llama: Llama B", "owned_by": "meta-llama"},
        {"id": "meta-llama/c", "name": "Meta Llama: Llama C", "owned_by": "meta-llama"},
        {"id": "meta-llama/d", "owned_by": "meta-llama"},
    ]}
    result = _probe(lambda request: httpx.Response(200, json=body))
    assert [m["vendor_name"] for m in result.models] == ["Meta Llama"] * 4


def test_stored_rows_without_a_server_name_are_repaired():
    """이름 없이 저장된 줄(name == id)의 업체 이름이 id 조각이면 읽기 좋은 이름으로 고쳐 읽는다."""
    stored = [{"id": "deepseek/deepseek-r1:free", "name": "deepseek/deepseek-r1:free", "vendor": "deepseek",
               "vendor_name": "deepseek/deepseek-r1", "context_length": None, "chat": True}]
    assert normalize_models(stored)[0]["vendor_name"] == "DeepSeek"


def test_legacy_id_lists_are_normalized():
    """예전에 저장한 id 목록도 메타데이터 꼴로 읽는다(다음 시험 때까지 쓰이게)."""
    stored = ["liner-mark", "openai/gpt-x", {"id": "google/g", "name": "Google: G", "vendor": "google",
                                             "vendor_name": "Google", "context_length": 8, "chat": False}]
    assert normalize_models(stored) == [
        {"id": "liner-mark", "name": "liner-mark", "vendor": "liner", "vendor_name": "Liner",
         "context_length": None, "chat": True, "price": price_of("liner-mark")},
        {"id": "openai/gpt-x", "name": "openai/gpt-x", "vendor": "openai", "vendor_name": "OpenAI",
         "context_length": None, "chat": True, "price": None},
        {"id": "google/g", "name": "Google: G", "vendor": "google", "vendor_name": "Google",
         "context_length": 8, "chat": False, "price": None},
    ]


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
