"""뜻 검색 벡터 저장(app.files.vectors, Task 48): 컬렉션 이름·넣기·찾기·거르기·지우기·연결 확인·인스턴스별 컬렉션."""

import pytest

from app.files.vectors import Point, Store, collection_for

A, B = collection_for("m", 3, "a"), collection_for("m", 4, "a")


def test_collection_name_has_instance_model_and_dim():
    assert collection_for("openai/text-embedding-3-small", 1536, "ab12") == "chunks__ab12__openai_text-embedding-3-small__1536"
    assert collection_for("BAAI/bge-m3", 1024, "ab12") == "chunks__ab12__baai_bge-m3__1024"
    assert collection_for("~vendor/모델 v2", 8, "ab12") == "chunks__ab12__vendor_v2__8"
    assert Store(":memory:", "ab12").collection_for("m", 3) == "chunks__ab12__m__3"


def test_upsert_creates_the_collection_and_search_ranks_by_score():
    s = Store(":memory:", "a")
    s.upsert(A, [Point(1, 10, [1, 0, 0]), Point(2, 10, [0, 1, 0]), Point(3, 11, [0.9, 0.1, 0])])
    hits = s.search(A, [1, 0, 0], limit=2)
    assert [chunk_id for chunk_id, _ in hits] == [1, 3] and hits[0][1] == pytest.approx(1.0)
    s.upsert(A, [Point(1, 10, [0, 0, 1])])  # 같은 조각 id 는 바꿔 넣는다
    assert [chunk_id for chunk_id, _ in s.search(A, [0, 0, 1], limit=1)] == [1]


def test_search_filter_keeps_only_given_payload_values():
    s = Store(":memory:", "a")
    s.upsert(A, [Point(1, 10, [1, 0, 0]), Point(2, 11, [1, 0, 0]), Point(3, 12, [1, 0, 0])])
    assert sorted(c for c, _ in s.search(A, [1, 0, 0], 5, {"file_id": [11, 12]})) == [2, 3]
    assert s.search(A, [1, 0, 0], 5, {"file_id": []}) == []


def test_search_in_a_missing_collection_is_empty():
    assert Store(":memory:", "a").search(collection_for("none", 3, "a"), [1, 0, 0], 5) == []


@pytest.mark.usefixtures("http_refused")  # 꺼진 Qdrant: httpx 전송이 연결 거절로 끝난다(소켓에 닿지 않는다)
def test_available():
    assert Store(":memory:", "a").available()
    assert not Store("http://127.0.0.1:1", "a").available()  # 아무도 듣지 않는 곳


def test_delete_file_in_every_collection_and_drop():
    s = Store(":memory:", "a")
    s.upsert(A, [Point(1, 10, [1, 0, 0]), Point(2, 11, [1, 0, 0])])
    s.upsert(B, [Point(1, 10, [1, 0, 0, 0])])
    s.delete_file(10)
    assert [c for c, _ in s.search(A, [1, 0, 0], 5)] == [2] and s.search(B, [1, 0, 0, 0], 5) == []
    assert sorted(s.collections()) == sorted([A, B])
    s.drop(A)
    assert s.collections() == [B]


def test_two_instances_sharing_one_qdrant_touch_only_their_own_collections():
    a = Store(":memory:", "a")
    b = Store(":memory:", "b", client=a.client)  # 같은 Qdrant 서버(예: PM 앱과 개발용 서버)
    a.upsert(a.collection_for("m", 3), [Point(1, 10, [1, 0, 0])])
    b.upsert(b.collection_for("m", 3), [Point(1, 10, [1, 0, 0])])
    assert a.collections() == ["chunks__a__m__3"] and b.collections() == ["chunks__b__m__3"]
    a.delete_file(10)
    assert a.search("chunks__a__m__3", [1, 0, 0], 5) == []
    assert [c for c, _ in b.search("chunks__b__m__3", [1, 0, 0], 5)] == [1]  # 다른 인스턴스의 점은 그대로
