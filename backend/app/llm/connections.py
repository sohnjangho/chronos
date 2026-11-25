"""LLM 연결 시험: GET {base_url}/models 로 키와 주소가 맞는지 본다.

키는 Authorization 머리글로만 보낸다. 결과·예외·기록 어디에도 키를 담지 않는다.
"""

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TypedDict

import httpx
import yaml

from app.llm.errors import InvalidBaseUrl, LlmError, explain

PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_BASE_URLS = {"liner": "https://platform.liner.com/api/v1"}
# 머리글에 그대로 실을 수 있는 키: 보이는 ASCII(0x21~0x7e) 1~512자.
# 공백·줄바꿈이 섞이면 h11 이 머리글 값 전체를 담은 예외를 내고 httpcore 가 그것을 기록한다.
_SENDABLE_SECRET = re.compile(r"[\x21-\x7e]{1,512}")


CHAT_ENDPOINT = "/v1/chat/completions"
EMBED_ENDPOINT = "/v1/embeddings"


PRICES_PATH = Path(__file__).with_name("prices.yaml")
_PRICE_KEYS = {"input", "output", "cached_input"}


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"가격표 {where}: 0 이상의 숫자여야 합니다.")
    return float(value)


@cache
def load_prices(path: Path = PRICES_PATH) -> dict[str, dict]:
    """가격표(prices.yaml)를 한 번 읽고 검증해 모델 id → 가격으로 돌려준다(Liner 는 부르지 않는다).

    가격은 {"kind": "model", input, output, cached_input, as_of} 또는 라우터의
    {"kind": "range", input_min, input_max, output_min, output_max, as_of} 다.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"source", "as_of", "models", "aliases", "routers"}:
        raise ValueError("가격표: source·as_of·models·aliases·routers 만 있어야 합니다.")
    as_of = str(data["as_of"])
    models: dict[str, dict] = {}
    for model_id, row in data["models"].items():
        if not isinstance(row, dict) or set(row) != _PRICE_KEYS:
            raise ValueError(f"가격표 {model_id}: input·output·cached_input 만 있어야 합니다.")
        models[model_id] = {"kind": "model", **{k: _number(row[k], f"{model_id}.{k}") for k in sorted(_PRICE_KEYS)},
                            "as_of": as_of}
    prices = dict(models)
    for alias, target in data["aliases"].items():
        if target not in models:
            raise ValueError(f"가격표 별칭 {alias}: 모르는 모델 {target}")
        prices[alias] = models[target]
    for router, members in data["routers"].items():
        if not members or any(member not in models for member in members):
            raise ValueError(f"가격표 라우터 {router}: 모르는 모델이 있습니다.")
        ins = [models[member]["input"] for member in members]
        outs = [models[member]["output"] for member in members]
        prices[router] = {"kind": "range", "input_min": min(ins), "input_max": max(ins),
                          "output_min": min(outs), "output_max": max(outs), "as_of": as_of}
    return prices


def price_of(model_id: str) -> dict | None:
    """공개 가격표에 있는 모델의 가격, 없으면 None."""
    return load_prices().get(model_id)


def estimate_cost(
    served: str, requested: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
) -> float | None:
    """제공자가 비용을 알리지 않을 때 가격표로 어림한 비용(USD).

    답한 모델(served)의 가격, 없으면 요청한 모델이 단일 모델일 때 그 가격. 라우터(가격이 범위)뿐이면 None.
    캐시 입력 토큰은 입력 토큰 안의 몫으로 보고 cached_input 가격으로 센다.
    """
    for model_id in (served, requested):
        price = price_of(model_id)
        if price is not None and price["kind"] == "model":
            cached = min(max(cached_input_tokens, 0), input_tokens)
            fresh = input_tokens - cached
            return (fresh * price["input"] + cached * price["cached_input"] + output_tokens * price["output"]) / 1_000_000
    return None


class ModelInfo(TypedDict):
    """모델 한 개. vendor 는 owned_by(없으면 id 의 "/" 앞), chat 은 대화 API 를 받는지, price 는 공개 가격(없으면 None)."""

    id: str
    name: str
    vendor: str
    vendor_name: str
    context_length: int | None
    chat: bool
    price: dict | None
    embedding: bool  # /v1/embeddings 를 받는지(endpoints 가 없으면 거짓). 예전에 저장된 줄에는 없을 수 있다


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    models: list[ModelInfo] = field(default_factory=list)
    error: LlmError | None = None


def secret_is_sendable(secret: str) -> bool:
    return _SENDABLE_SECRET.fullmatch(secret) is not None


def normalize_base_url(base_url: str) -> str:
    """앞뒤 공백과 끝의 / 를 뗀다. http(s) 주소가 아니거나 사용자 정보·?·# 가 있으면 InvalidBaseUrl."""
    url = base_url.strip().rstrip("/")
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise InvalidBaseUrl("주소가 올바르지 않습니다.") from None
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise InvalidBaseUrl("주소는 http:// 또는 https:// 로 시작해야 합니다.")
    if parsed.userinfo or "?" in url or "#" in url:
        raise InvalidBaseUrl("주소에 사용자 정보나 물음표(?)·샵(#) 뒤 값은 넣을 수 없습니다.")
    return url


# 서버가 모델 이름을 주지 않을 때 보일 업체 이름(흔한 업체). 표에 없으면 title-case.
_VENDOR_NAMES = {
    "liner": "Liner",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta-llama": "Meta Llama",
    "mistralai": "Mistral AI",
    "x-ai": "xAI",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "z-ai": "Z.ai",
    "microsoft": "Microsoft",
    "cohere": "Cohere",
    "nvidia": "NVIDIA",
    "amazon": "Amazon",
    "perplexity": "Perplexity",
    "moonshotai": "Moonshot AI",
    "minimax": "MiniMax",
}


def readable_vendor(vendor: str) -> str:
    return _VENDOR_NAMES.get(vendor, vendor.title())


def _vendor_from_id(model_id: str) -> str:
    """id 의 "/" 앞(앞의 ~ 는 뗀다). "/" 가 없으면 Liner 의 모델."""
    prefix = model_id.split("/", 1)[0].lstrip("~") if "/" in model_id else ""
    return prefix or "liner"


def model_info(item: dict) -> ModelInfo:
    """/models 의 항목 하나를 ModelInfo 로. 없는 값은 규칙대로 채운다."""
    model_id = str(item["id"])
    vendor = str(item.get("owned_by") or "").strip() or _vendor_from_id(model_id)
    given = str(item.get("name") or "").strip()
    # ":" 앞을 업체 이름으로 쓰는 것은 서버가 준 이름일 때만이다(id 의 ":free" 같은 꼬리를 자르지 않게).
    vendor_name = given.split(":", 1)[0].strip() if ":" in given else readable_vendor(vendor)
    endpoints = item.get("endpoints")
    context = item.get("context_length")
    return ModelInfo(
        id=model_id,
        name=given or model_id,
        vendor=vendor,
        vendor_name=vendor_name,
        context_length=context if isinstance(context, int) and not isinstance(context, bool) else None,
        chat=CHAT_ENDPOINT in endpoints if isinstance(endpoints, list) else True,
        price=price_of(model_id),
        embedding=isinstance(endpoints, list) and EMBED_ENDPOINT in endpoints,
    )


def _one_name_per_vendor(models: list[ModelInfo]) -> list[ModelInfo]:
    """같은 업체의 모델은 가장 많이 나온 업체 이름 하나를 쓴다(묶음 머리와 찾기가 어긋나지 않게)."""
    counts: dict[str, Counter[str]] = {}
    for model in models:
        counts.setdefault(model["vendor"], Counter())[model["vendor_name"]] += 1
    best = {vendor: counter.most_common(1)[0][0] for vendor, counter in counts.items()}
    return [ModelInfo(**{**model, "vendor_name": best[model["vendor"]]}) for model in models]


def _stored(item: dict) -> ModelInfo:
    """새 꼴로 저장된 줄. 서버 이름 없이 저장된 줄(name == id)은 업체 이름을 다시 만든다."""
    model = ModelInfo(**{key: item.get(key) for key in ModelInfo.__annotations__})
    model["price"] = price_of(model["id"])  # 저장된 값이 아니라 지금 가격표로
    model["embedding"] = bool(item.get("embedding"))  # 이 칸 전에 저장된 줄은 거짓(다시 시험하면 채워짐)
    if model["name"] == model["id"]:
        model["vendor_name"] = readable_vendor(model["vendor"])
    return model


def normalize_models(stored: list | None) -> list[ModelInfo]:
    """저장된 모델 목록을 ModelInfo 꼴로. 예전 꼴(id 문자열 목록)도 받는다."""
    models: list[ModelInfo] = []
    for item in stored or []:
        if isinstance(item, str):
            models.append(model_info({"id": item}))
        elif isinstance(item, dict) and "id" in item:
            known = all(key in item for key in ModelInfo.__annotations__ if key not in ("price", "embedding"))
            models.append(_stored(item) if known else model_info(item))
    return _one_name_per_vendor(models)


def _models(body: object) -> list[ModelInfo]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise TypeError("models 응답에 data 목록이 없습니다.")
    return _one_name_per_vendor([model_info(item) for item in data if isinstance(item, dict) and "id" in item])


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    # trust_env=False: HTTP(S)_PROXY 같은 환경 변수의 프록시로 키가 나가지 않게 한다.
    return httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS, trust_env=False)


def probe(
    base_url: str, secret: str, *, transport: httpx.BaseTransport | None = None
) -> ProbeResult:
    """연결을 시험한다. 실패해도 예외 대신 설명 붙은 ProbeResult 를 돌려준다."""
    start = time.perf_counter()
    try:
        if not secret_is_sendable(secret):
            raise ValueError("키에 보낼 수 없는 문자가 있습니다.")  # 키 값은 담지 않는다
        url = normalize_base_url(base_url)
        with _client(transport) as client:
            response = client.get(f"{url}/models", headers={"Authorization": f"Bearer {secret}"})
        response.raise_for_status()
        models = _models(response.json())
    # 통신·주소·응답 형식 실패는 설명으로 바꾼다. ValueError 에는 JSON 해석 실패와
    # 보낼 수 없는 키가 들어간다.
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError) as exc:
        return ProbeResult(ok=False, latency_ms=_elapsed_ms(start), error=explain(exc))
    return ProbeResult(ok=True, latency_ms=_elapsed_ms(start), models=models)
