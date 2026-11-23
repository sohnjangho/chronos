"""뜻 검색 벡터(Qdrant). 컬렉션은 인스턴스·모델·차원마다 하나(`chunks__<인스턴스>__<모델 정리>__<차원>`), 점 하나 = 글 조각 하나.

- 인스턴스 = 이 서버(DB)의 id(jobs 가 settings 표에 한 번 만든다). 같은 Qdrant 를 여러 서버(PM 앱·개발·시험)가 함께 써도
  collections·delete_file·지우기는 제 인스턴스 컬렉션만 건드린다.

- 점 id = 조각 id(file_chunks.id), payload 는 file_id 만. 분류 축은 SQLite(file_axes)에 있고 분류 뒤·언제든 바뀌므로,
  축 거르기는 files.search 가 축 값 → 파일 id 로 바꿔 {"file_id": [...]} 로 거른다.
- 거리는 코사인. 컬렉션은 처음 넣을 때 벡터 길이로 만든다.
- STORE: 서버가 쓰는 Store. jobs.start 가 CHRONOS_QDRANT_URL 로 만든다(빈 값이면 None = 뜻 검색 끔). 시험이 바꿔 끼운다.
- 메서드는 막히는(sync) 호출이다. 이벤트 루프 안에서는 asyncio.to_thread 로 부른다.
- unsaved: 임베딩했지만 아직 다 넣지 못한 벡터(A5). jobs 가 다시 할 때 임베딩(과금)을 다시 부르지 않고 이것을 넣는다.
"""

import re
import warnings
from collections import OrderedDict
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

PREFIX = "chunks__"
TIMEOUT_S = 5
KEEP = 1024  # unsaved 가 들고 있을 벡터 수. 넘으면 오래된 묶음부터 버린다(그 묶음은 다시 임베딩한다)


@dataclass(frozen=True)
class Point:
    chunk_id: int
    file_id: int
    vector: list[float]


def collection_for(model: str, dim: int, instance: str) -> str:
    """모델 이름은 소문자로 하고 영문·숫자·_·- 밖의 글자 묶음을 _ 로 바꾼다."""
    name = re.sub(r"[^a-z0-9_-]+", "_", model.lower()).strip("_")
    return f"{PREFIX}{instance}__{name}__{dim}"


class Unsaved:
    """(모델, 조각들) → 벡터. 조각들은 무엇이든 hashable 한 묶음(jobs 의 (조각 id, 파일 id, 글) 들)."""

    def __init__(self) -> None:
        self._kept: OrderedDict[tuple, list[list[float]]] = OrderedDict()

    def get(self, model: str, pieces: tuple) -> list[list[float]] | None:
        return self._kept.get((model, pieces))

    def put(self, model: str, pieces: tuple, found: list[list[float]]) -> None:
        self._kept[(model, pieces)] = found
        while len(self._kept) > 1 and sum(map(len, self._kept.values())) > KEEP:
            self._kept.popitem(last=False)

    def drop(self, pieces: tuple) -> None:
        """그 조각들을 다 넣었다 — 모든 모델의 벡터를 버린다."""
        for key in [key for key in self._kept if key[1] == pieces]:
            del self._kept[key]


class Store:
    """url 이 ":memory:" 면 메모리 Qdrant(시험), 아니면 Qdrant 서버(http). client 를 주면 그것을 함께 쓴다(시험).

    주소가 잘못됐으면 만들 때 예외(LocationParseError·ValueError 등)."""

    def __init__(self, url: str, instance: str, *, client: QdrantClient | None = None) -> None:
        self.instance = instance
        self.unsaved = Unsaved()
        if client is not None:
            self.client = client
        elif url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        else:
            self.client = QdrantClient(url=url, timeout=TIMEOUT_S, check_compatibility=False)

    def collection_for(self, model: str, dim: int) -> str:
        return collection_for(model, dim, self.instance)

    def available(self) -> bool:
        try:
            self.client.get_collections()
        except Exception:  # noqa: BLE001 — 어떤 실패든 「쓸 수 없음」
            return False
        return True

    def upsert(self, collection: str, points: list[Point]) -> None:
        """같은 조각 id 는 바꿔 넣는다. 컬렉션이 없으면 첫 벡터 길이로 만든다."""
        if not points:
            return
        if not self.client.collection_exists(collection):
            params = models.VectorParams(size=len(points[0].vector), distance=models.Distance.COSINE)
            self.client.create_collection(collection, vectors_config=params)
            with warnings.catch_warnings():  # 메모리 Qdrant 는 「색인이 효과 없음」을 알린다
                warnings.simplefilter("ignore", UserWarning)
                self.client.create_payload_index(collection, "file_id", models.PayloadSchemaType.INTEGER)
        structs = [models.PointStruct(id=p.chunk_id, vector=p.vector, payload={"file_id": p.file_id}) for p in points]
        self.client.upsert(collection, points=structs, wait=True)

    def search(
        self, collection: str, vector: list[float], limit: int, filter: dict[str, list] | None = None
    ) -> list[tuple[int, float]]:
        """[(조각 id, 점수)] 점수 큰 차례. filter = {payload 칸: [값…]} — 칸마다 값 가운데 하나, 칸끼리는 모두.

        빈 값 목록이 있거나 컬렉션이 없으면 [].
        """
        conditions = [models.FieldCondition(key=k, match=models.MatchAny(any=list(v))) for k, v in (filter or {}).items()]
        if any(not values for values in (filter or {}).values()) or not self.client.collection_exists(collection):
            return []
        found = self.client.query_points(collection, query=vector, limit=limit, with_payload=False,
                                          query_filter=models.Filter(must=conditions) if conditions else None)
        return [(int(p.id), p.score) for p in found.points]

    def collections(self) -> list[str]:
        """이 인스턴스의 컬렉션만."""
        mine = f"{PREFIX}{self.instance}__"
        return [c.name for c in self.client.get_collections().collections if c.name.startswith(mine)]

    def drop(self, collection: str) -> None:
        self.client.delete_collection(collection)

    def delete_file(self, file_id: int) -> None:
        """이 인스턴스의 모든 컬렉션에서 그 파일의 점을 지운다."""
        match = models.FieldCondition(key="file_id", match=models.MatchValue(value=file_id))
        selector = models.FilterSelector(filter=models.Filter(must=[match]))
        for name in self.collections():
            self.client.delete(name, points_selector=selector, wait=True)


STORE: Store | None = None
