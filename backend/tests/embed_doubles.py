"""임베딩 시험용 가짜 `/embeddings`(네트워크 없음). 뜻 같은 글은 같은 벡터를 준다.

글의 뜻 = MEANINGS 에서 처음 들어 있는 낱말의 축(없으면 OTHER 축). 벡터는 그 축만 1 인 단위 벡터라
뜻이 같으면 점수 1, 다르면 0 이다. 모델마다 차원이 다르다(DIMS). `embeddings.TRANSPORT` 에 끼워 쓴다.
"""

import json

import httpx

SMALL, LARGE = "openai/text-embedding-3-small", "openai/text-embedding-3-large"
DIMS = {SMALL: 8, LARGE: 12}
MEANINGS = (("동절기", 0), ("겨울", 0), ("강도", 1), ("배관", 2), ("접속", 4), ("SNET", 3), ("철근", 5))
OTHER = 6
COST = 1.16e-06
# 가짜 임베딩이 만드는 컬렉션 이름(시험 인스턴스 t · 작은 모델 8차원 · 큰 모델 12차원)
OLD = "chunks__t__openai_text-embedding-3-small__8"
NEW = "chunks__t__openai_text-embedding-3-large__12"


def meaning(text: str) -> int:
    return next((axis for word, axis in MEANINGS if word in text), OTHER)


def vector(text: str, model: str) -> list[float]:
    out = [0.0] * DIMS.get(model, 8)
    out[meaning(text)] = 1.0
    return out


def body(texts: list[str], model: str) -> dict:
    """OpenAI 호환 응답. data 는 거꾸로 준다(index 로 맞추는지 보려고). model 은 업체 앞말을 뗀다(실측)."""
    data = [{"object": "embedding", "index": i, "embedding": vector(t, model)} for i, t in enumerate(texts)]
    tokens = sum(len(t) for t in texts)
    return {"object": "list", "data": data[::-1], "model": model.split("/")[-1],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens, "cost": COST}}


class FakeEmbedder:
    """대본(push)에 쌓은 차례대로 답하고, 대본이 비면 body() 를 준다. 대본: httpx.Response · dict · 던질 예외."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self._script: list[httpx.Response | dict | Exception] = []

    def push(self, *items: httpx.Response | dict | Exception) -> None:
        self._script.extend(items)

    @property
    def models(self) -> list[str]:
        return [b["model"] for b in self.bodies]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        sent = json.loads(request.content)
        self.bodies.append(sent)
        item = self._script.pop(0) if self._script else body(sent["input"], sent["model"])
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)
