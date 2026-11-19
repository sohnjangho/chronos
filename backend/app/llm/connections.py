"""LLM 연결 시험: GET {base_url}/models 로 키와 주소가 맞는지 본다.

키는 Authorization 머리글로만 보낸다. 결과·예외·기록 어디에도 키를 담지 않는다.
"""

import time
from dataclasses import dataclass, field

import httpx

from app.llm.errors import InvalidBaseUrl, LlmError, explain

PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_BASE_URLS = {"liner": "https://platform.liner.com/api/v1"}


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    models: list[str] = field(default_factory=list)
    error: LlmError | None = None


def normalize_base_url(base_url: str) -> str:
    """앞뒤 공백과 끝의 / 를 뗀다. http(s) 주소가 아니면 InvalidBaseUrl."""
    url = base_url.strip().rstrip("/")
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise InvalidBaseUrl("주소가 올바르지 않습니다.") from None
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise InvalidBaseUrl("주소는 http:// 또는 https:// 로 시작해야 합니다.")
    return url


def _model_ids(body: object) -> list[str]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise TypeError("models 응답에 data 목록이 없습니다.")
    return [str(item["id"]) for item in data if isinstance(item, dict) and "id" in item]


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def probe(
    base_url: str, secret: str, *, transport: httpx.BaseTransport | None = None
) -> ProbeResult:
    """연결을 시험한다. 실패해도 예외 대신 설명 붙은 ProbeResult 를 돌려준다."""
    start = time.perf_counter()
    try:
        url = normalize_base_url(base_url)
        with httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = client.get(f"{url}/models", headers={"Authorization": f"Bearer {secret}"})
        response.raise_for_status()
        models = _model_ids(response.json())
    # 통신·주소·응답 형식 실패는 설명으로 바꾼다. ValueError 에는 JSON 해석 실패와
    # 머리글에 넣을 수 없는 키(UnicodeEncodeError)가 들어간다.
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError) as exc:
        return ProbeResult(ok=False, latency_ms=_elapsed_ms(start), error=explain(exc))
    return ProbeResult(ok=True, latency_ms=_elapsed_ms(start), models=models)
