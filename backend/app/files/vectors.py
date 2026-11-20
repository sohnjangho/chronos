"""뜻 검색 벡터(Qdrant). 컬렉션은 모델·차원마다 하나(`chunks__<모델 정리>__<차원>`), 점 하나 = 글 조각 하나.

- 점 id = 조각 id(file_chunks.id), payload 는 file_id 만. 분류 축은 SQLite(file_axes)에 있고 분류 뒤·언제든 바뀌므로,
  축 거르기는 files.search 가 축 값 → 파일 id 로 바꿔 {"file_id": [...]} 로 거른다.
- 거리는 코사인. 컬렉션은 처음 넣을 때 벡터 길이로 만든다.
- STORE: 서버가 쓰는 Store. jobs.start 가 CHRONOS_QDRANT_URL 로 만든다(빈 값이면 None = 뜻 검색 끔). 시험이 바꿔 끼운다.
- 메서드는 막히는(sync) 호출이다. 이벤트 루프 안에서는 asyncio.to_thread 로 부른다.
"""

import re
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

PREFIX = "chunks__"
TIMEOUT_S = 5


@dataclass(frozen=True)
class Point:
    chunk_id: int
    file_id: int
    vector: list[float]


def collection_for(model: str, dim: int) -> str:
    """모델 이름은 소문자로 하고 영문·숫자·_·- 밖의 글자 묶음을 _ 로 바꾼다."""
    name = re.sub(r"[^a-z0-9_-]+", "_", model.lower()).strip("_")
    return f"{PREFIX}{name}__{dim}"


class Store:
    """url 이 ":memory:" 면 메모리 Qdrant(시험), 아니면 Qdrant 서버(http)."""

    def __init__(self, url: str) -> None:
        if url == ":memory:":
            self._client = QdrantClient(location=":memory:")
        else:
            self._client = QdrantClient(url=url, timeout=TIMEOUT_S, check_compatibility=False)

    def available(self) -> bool:
        try:
            self._client.get_collections()
        except Exception:  # noqa: BLE001 — 어떤 실패든 「쓸 수 없음」
            return False
        return True

    def upsert(self, collection: str, points: list[Point]) -> None:
        """같은 조각 id 는 바꿔 넣는다. 컬렉션이 없으면 첫 벡터 길이로 만든다."""
        if not points:
            return
        if not self._client.collection_exists(collection):
            params = models.VectorParams(size=len(points[0].vector), distance=models.Distance.COSINE)
            self._client.create_collection(collection, vectors_config=params)
        structs = [models.PointStruct(id=p.chunk_id, vector=p.vector, payload={"file_id": p.file_id}) for p in points]
        self._client.upsert(collection, points=structs, wait=True)

    def search(
        self, collection: str, vector: list[float], limit: int, filter: dict[str, list] | None = None
    ) -> list[tuple[int, float]]:
        """[(조각 id, 점수)] 점수 큰 차례. filter = {payload 칸: [값…]} — 칸마다 값 가운데 하나, 칸끼리는 모두.

        빈 값 목록이 있거나 컬렉션이 없으면 [].
        """
        conditions = [models.FieldCondition(key=k, match=models.MatchAny(any=list(v))) for k, v in (filter or {}).items()]
        if any(not values for values in (filter or {}).values()) or not self._client.collection_exists(collection):
            return []
        found = self._client.query_points(collection, query=vector, limit=limit, with_payload=False,
                                          query_filter=models.Filter(must=conditions) if conditions else None)
        return [(int(p.id), p.score) for p in found.points]

    def collections(self) -> list[str]:
        """우리 컬렉션(chunks__ 로 시작)만."""
        return [c.name for c in self._client.get_collections().collections if c.name.startswith(PREFIX)]

    def drop(self, collection: str) -> None:
        self._client.delete_collection(collection)

    def delete_file(self, file_id: int) -> None:
        """모든 우리 컬렉션에서 그 파일의 점을 지운다."""
        match = models.FieldCondition(key="file_id", match=models.MatchValue(value=file_id))
        selector = models.FilterSelector(filter=models.Filter(must=[match]))
        for name in self.collections():
            self._client.delete(name, points_selector=selector, wait=True)


STORE: Store | None = None
