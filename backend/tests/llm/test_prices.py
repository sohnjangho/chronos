import httpx
import pytest

from app.llm import connections
from app.llm.connections import load_prices, price_of, probe


def test_known_models_have_public_prices():
    assert price_of("gpt-6-luna") == {"kind": "model", "input": 0.10, "output": 0.50, "cached_input": 0.01,
                                      "as_of": "2026-11-20"}
    assert price_of("liner-mark-1.0")["output"] == 6.0
    # 가격 문서의 라우터 표 값(카탈로그 표의 0.825 / 4.125 가 아니다)
    assert (price_of("gemini-3.8-flash")["input"], price_of("gemini-3.8-flash")["output"]) == (0.75, 3.75)
    assert price_of("liner-mark") == price_of("liner-mark-latest") == price_of("liner-mark-1.3")
    assert price_of("openai/text-embedding-3-small") == {"kind": "model", "input": 0.02, "output": 0.0,
                                                         "cached_input": 0.0, "as_of": "2026-11-20"}


def test_routers_are_ranges_of_the_models_they_pick():
    assert price_of("liner-claude-router") == {"kind": "range", "input_min": 0.10, "input_max": 10.0,
                                               "output_min": 0.50, "output_max": 50.0, "as_of": "2026-11-20"}
    assert price_of("liner-gpt-router")["input_max"] == 10.0
    assert price_of("liner-gemini-router")["output_min"] == 2.5


def test_missing_model_has_no_price():
    assert price_of("openai/unknown-model") is None


def test_prices_are_loaded_once():
    assert load_prices() is load_prices()


def _write(tmp_path, body):
    path = tmp_path / "prices.yaml"
    path.write_text(body, encoding="utf-8")
    return path


BASE = "source: x\nas_of: '2026-11-20'\naliases: {}\nrouters: {}\n"


@pytest.mark.parametrize(
    "models",
    [
        "models: {a: {input: -1, output: 1, cached_input: 0}}",
        "models: {a: {input: 'x', output: 1, cached_input: 0}}",
        "models: {a: {input: true, output: 1, cached_input: 0}}",
        "models: {a: {input: 1, output: 1}}",
        "models: {a: {input: 1, output: 1, cached_input: 0, extra: 1}}",
    ],
)
def test_bad_price_rows_are_rejected(tmp_path, models):
    with pytest.raises(ValueError):
        load_prices.__wrapped__(_write(tmp_path, BASE + models))


def test_unknown_keys_and_references_are_rejected(tmp_path):
    ok = "models: {a: {input: 1, output: 1, cached_input: 0}}\n"
    with pytest.raises(ValueError):
        load_prices.__wrapped__(_write(tmp_path, BASE + ok + "oops: 1"))
    with pytest.raises(ValueError):
        load_prices.__wrapped__(_write(tmp_path, BASE.replace("routers: {}", "routers: {r: [zzz]}") + ok))
    with pytest.raises(ValueError):
        load_prices.__wrapped__(_write(tmp_path, BASE.replace("aliases: {}", "aliases: {b: zzz}") + ok))


def test_probe_attaches_price_without_calling_anything_else():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": "liner-claude-router"}, {"id": "mystery"}]})

    result = probe("https://platform.liner.com/api/v1", "k", transport=httpx.MockTransport(handler))
    assert [m["price"] is not None for m in result.models] == [True, False]
    assert seen == ["https://platform.liner.com/api/v1/models"]
    assert connections.PRICES_PATH.name == "prices.yaml"
