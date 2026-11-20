"""분류 단계(app.files.classify, Task 49): 축 값 다시 쓰기·새 값 표시·그림 설명·실패·대화 카드·사람 고침·값 합치기."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.files import classify, jobs, merge_suggest, vectors
from app.store import chats, files
from app.store.tables import (
    AxisValue,
    ChatMessage,
    FileAxis,
    FileRow,
    LlmCall,
    ScheduleRecord,
)
from tests.embed_doubles import OLD, SMALL, vector
from tests.llm_doubles import add_connection, chat_body
from tests.loop_doubles import ScriptedLlm

REAL_AFTER_INDEX = classify.after_index  # tests/conftest.py 가 시험마다 끈다 — 이 파일에서 다시 켠다
REAL_SUGGEST = merge_suggest.suggest_if_due
FAILED = "분류하지 못했습니다"
BIG_IMAGE = "그림이 커서 설명을 만들지 않았습니다"
NOT_READY = "뜻 검색 준비 안 됨"
PNG = b"\x89PNG\r\n\x1a\n"
TESTS_FIXTURES = Path(__file__).parent.parent / "fixtures" / "files"


def answer(kind=(), trade=(), site=(), source=(), summary="한 줄 요약", description=None) -> dict:
    """분류 LLM 의 strict JSON 답."""
    body: dict = {"axes": {"kind": list(kind), "trade": list(trade), "site": list(site), "source": list(source)},
                  "summary": summary}
    if description is not None:
        body["description"] = description
    return chat_body(json.dumps(body, ensure_ascii=False))


@pytest.fixture
def llm(monkeypatch) -> ScriptedLlm:
    double = ScriptedLlm()
    monkeypatch.setattr(classify, "TRANSPORT", double.transport)
    return double


@pytest.fixture
def conn(session):
    return add_connection(session)


@pytest.fixture
def classify_on(monkeypatch):
    monkeypatch.setattr(classify, "after_index", REAL_AFTER_INDEX)
    monkeypatch.setattr(merge_suggest, "suggest_if_due", REAL_SUGGEST)


def _indexed(session, row: FileRow) -> FileRow:
    row.status = "indexed"
    session.commit()
    return row


def _seed(session, axis: str, *values: str, is_new: bool = False) -> None:
    session.add_all(AxisValue(axis=axis, value=v, is_new=is_new) for v in values)
    session.commit()


def _purposes(session) -> list[str]:
    return list(session.scalars(select(LlmCall.purpose).order_by(LlmCall.id)))


def _events(session, chat_id: int) -> list[dict]:
    query = select(ChatMessage.content_json).where(ChatMessage.session_id == chat_id, ChatMessage.role == "event")
    return list(session.scalars(query))


# ── 지시서 시험 ──────────────────────────────────────────────────────


async def test_reuses_existing_values(session, conn, llm, put):
    _seed(session, "종류", "시방서", "도면")
    _seed(session, "공종", "골조")
    f = _indexed(session, put("콘크리트 양생은 최소 7일로 한다.", "시방서_A.txt"))
    llm.push(answer(kind=[" 시방서 ", "시방서"], trade=["골조"], summary="콘크리트 양생 기준"))

    got = await classify.classify(session, f.id)

    assert got.axes["종류"] == ["시방서"] and got.axes["공종"] == ["골조"]  # 앞뒤 공백·중복은 코드가 정리
    assert got.new_values == []
    assert "시방서" in llm.last_messages_text and "도면" in llm.last_messages_text  # 지금 값 목록을 지시에 넣는다
    assert "양생" in llm.last_messages_text
    schema = llm.last_body["response_format"]["json_schema"]
    assert schema["strict"] is True and "description" not in schema["schema"]["properties"]
    session.expire_all()
    assert (f.status, f.summary) == ("classified", "콘크리트 양생 기준")
    assert files.axes_of(session, f.id)["종류"] == ["시방서"]
    assert _purposes(session) == ["light"]


async def test_new_value_is_marked_new(client, admin, session, conn, llm, put):
    _seed(session, "종류", "시방서")
    f = _indexed(session, put("견적 금액 합계 1억", "견적.txt"))
    llm.push(answer(kind=["견적서"], trade=["전기"]))

    got = await classify.classify(session, f.id)

    assert sorted(got.new_values) == [("공종", "전기"), ("종류", "견적서")]
    session.expire_all()
    assert session.get(AxisValue, ("종류", "견적서")).is_new is True
    assert session.get(AxisValue, ("종류", "시방서")).is_new is False
    axes = client.get("/api/files/axes", headers=admin).json()
    assert set(axes) == {"종류", "공종", "현장", "시기", "출처"}
    assert {"value": "견적서", "count": 1, "is_new": True} in axes["종류"]
    assert {"value": "시방서", "count": 0, "is_new": False} in axes["종류"]


async def test_image_gets_a_description_chunk_with_vision_purpose(session, ready, llm, store, admin_user, classify_on):
    f = files.save_upload(session, (TESTS_FIXTURES / "dot.png").read_bytes(), "1103.png", admin_user)
    llm.push(answer(kind=["현장 사진"], summary="골조 철근 배근 사진", description="철근 배근을 위에서 찍은 사진" + "가" * 700))

    await jobs.drain()

    session.expire_all()
    pieces = files.chunks_of(session, f.id)
    assert len(pieces) == 1 and pieces[0].locator == "그림 설명"
    assert pieces[0].text.startswith("철근 배근을") and len(pieces[0].text) == 600
    assert _purposes(session) == ["vision", "embedding"]  # 분류는 그림 읽기 한 번, 설명 조각 임베딩 한 번
    content = llm.last_body["messages"][-1]["content"]
    assert any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in content)
    assert "description" in llm.last_body["response_format"]["json_schema"]["schema"]["properties"]
    assert (f.status, f.reason) == ("classified", None)
    # 설명 조각은 낱말 검색과 뜻 검색(Qdrant)에 들어간다
    assert [h.file_id for h in files.keyword_search(session, "배근을", 5)] == [f.id]
    assert store.search(OLD, vector("철근", SMALL), 5)[0][0] == pieces[0].id


async def test_llm_failure_keeps_file_usable(session, ready, llm, put, admin_user, classify_on):
    chat = chats.create_chat(session, user_id=admin_user.id)
    f = put("동절기 타설 계획", "계획.txt")
    files.link(session, chat.id, f.id)
    llm.push(httpx.Response(500))

    await jobs.drain()

    session.expire_all()
    assert (f.status, f.reason) == ("indexed", FAILED)
    assert files.axes_of(session, f.id) == {}
    assert _events(session, chat.id) == []  # 대화 카드 없음
    assert jobs.waiting() == [] and jobs._queue == []  # 임베딩 실패처럼 다시 하지 않는다


def test_patch_axes_and_list_filters(client, admin, user, session, put, admin_user):
    spec = put("콘크리트 양생 7일 이상", "시방서_A현장.txt")
    plan = put("철근 배근 검측 계획", "검측계획.txt")
    put("전기 배관 접속", "전기.txt")

    r = client.patch(f"/api/files/{spec.id}/axes", json={"종류": [" 시방서 ", "시방서"], "현장": ["A 현장"]}, headers=user)
    assert r.status_code == 200, r.text
    assert r.json()["axes"] == {"종류": ["시방서"], "현장": ["A 현장"]}  # 사람이 고친 값은 그대로(공백·중복만 정리)
    client.patch(f"/api/files/{plan.id}/axes", json={"종류": ["계획서"], "현장": ["A 현장"]}, headers=admin)
    session.expire_all()
    assert session.get(AxisValue, ("현장", "A 현장")).is_new is False  # 사람이 넣은 값은 「새」 아님

    def names(**params) -> list[str]:
        r = client.get("/api/files", params=params, headers=user)
        assert r.status_code == 200, r.text
        return [item["name"] for item in r.json()["items"]]

    assert names() == ["전기.txt", "검측계획.txt", "시방서_A현장.txt"]  # 새것부터
    assert names(종류="시방서") == ["시방서_A현장.txt"]
    assert names(현장="A 현장") == ["검측계획.txt", "시방서_A현장.txt"]
    assert names(현장="A 현장", 종류="계획서") == ["검측계획.txt"]
    assert names(q="양생") == ["시방서_A현장.txt"]  # 내용(낱말) 찾기
    assert names(q="검측계획") == ["검측계획.txt"]  # 이름 찾기
    assert names(q="양생", 종류="계획서") == []
    body = client.get("/api/files", params={"page": 2}, headers=user).json()
    assert (body["items"], body["total"], body["page"]) == ([], 3, 2)

    assert client.patch(f"/api/files/{spec.id}/axes", json={"색깔": ["빨강"]}, headers=user).status_code == 422
    assert client.patch(f"/api/files/{spec.id}/axes", json={"종류": ["가" * 101]}, headers=user).status_code == 422
    assert client.patch("/api/files/999/axes", json={"종류": ["시방서"]}, headers=user).status_code == 404
    files.soft_delete(session, plan.id, admin_user)
    assert names(현장="A 현장") == ["시방서_A현장.txt"]  # 지운 파일은 목록에서 빠진다


def test_merge_moves_files_and_drops_old_value(client, admin, user, session, put):
    a, b = put("양생 기준", "가.txt"), put("배근 기준", "나.txt")
    client.patch(f"/api/files/{a.id}/axes", json={"종류": ["시방서"]}, headers=admin)
    client.patch(f"/api/files/{b.id}/axes", json={"종류": ["시방 서류", "시방서"]}, headers=admin)
    _seed(session, "종류", "사양서", is_new=True)

    assert client.post("/api/files/merge", json={"axis": "종류", "from": ["시방 서류"], "to": "시방서"},
                       headers=user).status_code == 403
    r = client.post("/api/files/merge", json={"axis": "종류", "from": ["시방 서류", "사양서"], "to": "시방서"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"axis": "종류", "to": "시방서", "files": 1}

    session.expire_all()
    assert files.axes_of(session, b.id) == {"종류": ["시방서"]}
    assert session.get(AxisValue, ("종류", "시방 서류")) is None and session.get(AxisValue, ("종류", "사양서")) is None
    axes = client.get("/api/files/axes", headers=admin).json()
    assert axes["종류"] == [{"value": "시방서", "count": 2, "is_new": False}]

    # 새 이름으로 합치기 · 없는 값 · 없는 축
    r = client.post("/api/files/merge", json={"axis": "종류", "from": ["시방서"], "to": "시방 문서"}, headers=admin)
    assert r.json()["files"] == 2
    session.expire_all()
    assert files.axes_of(session, a.id) == {"종류": ["시방 문서"]}
    assert client.post("/api/files/merge", json={"axis": "종류", "from": ["없음"], "to": "x"},
                       headers=admin).status_code == 422
    assert client.post("/api/files/merge", json={"axis": "색깔", "from": ["x"], "to": "y"}, headers=admin).status_code == 422


# ── 더한 시험 ────────────────────────────────────────────────────────


async def test_success_leaves_a_card_in_every_linked_chat(session, conn, llm, put, admin_user):
    one, two = chats.create_chat(session, user_id=admin_user.id), chats.create_chat(session, user_id=admin_user.id)
    f = _indexed(session, put("콘크리트 양생", "시방서.txt"))
    files.link(session, one.id, f.id)
    files.link(session, two.id, f.id)
    llm.push(answer(kind=["시방서"], trade=["골조"], site=["A현장"]))

    await classify.classify(session, f.id)

    session.expire_all()
    for chat in (one, two):
        [event] = _events(session, chat.id)
        assert event["type"] == "card"
        data = event["data"]
        assert (data["kind"], data["file_id"], data["name"]) == ("file_saved", f.id, "시방서.txt")
        assert data["axes"]["종류"] == ["시방서"] and data["axes"]["현장"] == ["A현장"]


async def test_period_comes_from_dates_in_text_not_from_the_agent(session, conn, llm, put):
    f = _indexed(session, put("2026-03-05 타설\n2026.03.12 양생\n2026년 4월 1일 거푸집", "기록.txt"))
    llm.push(answer(kind=["회의록"]))
    got = await classify.classify(session, f.id)
    assert got.axes["시기"] == ["2026-03"]  # 가장 많이 나온 달(코드가 센다)
    assert ("시기", "2026-03") not in got.new_values  # 코드가 만든 값은 「새」 아님
    schema = llm.bodies[-1]["response_format"]["json_schema"]["schema"]
    assert "period" not in schema["properties"]["axes"]["properties"]

    g = _indexed(session, put("날짜 없는 글", "메모.txt"))
    g.uploaded_at = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)  # 한국 시각 11-01 01:00
    session.commit()
    llm.push(answer(kind=["기타"]))
    assert (await classify.classify(session, g.id)).axes["시기"] == ["2026-11"]  # 날짜가 없으면 올린 달(한국 시각)


async def test_site_hints_include_schedule_names(session, conn, llm, put):
    session.add(ScheduleRecord(name="5층 사무동 신축", domain="construction", level="L3", created_by="admin"))
    session.commit()
    f = _indexed(session, put("골조 일정", "a.txt"))
    llm.push(answer(site=["5층 사무동 신축"]))
    await classify.classify(session, f.id)
    assert "5층 사무동 신축" in llm.last_messages_text


async def test_agent_keeps_axes_a_person_already_set(session, conn, llm, put):
    f = _indexed(session, put("양생 기준", "a.txt"))
    session.add(FileAxis(file_id=f.id, axis="종류", value="법규"))
    session.add(AxisValue(axis="종류", value="법규", is_new=False))
    session.commit()
    llm.push(answer(kind=["시방서"], trade=["골조"]))
    got = await classify.classify(session, f.id)
    assert got.axes["종류"] == ["법규"] and got.axes["공종"] == ["골조"]
    assert ("종류", "시방서") not in got.new_values
    session.expire_all()
    assert session.get(AxisValue, ("종류", "시방서")) is None


async def test_big_image_is_classified_without_a_description(session, conn, llm, admin_user):
    data = PNG + b"\0" * (5 * 1024 * 1024)
    f = _indexed(session, files.save_upload(session, data, "큰사진.png", admin_user))
    llm.push(answer(kind=["현장 사진"]))
    await classify.classify(session, f.id)
    session.expire_all()
    assert _purposes(session) == ["light"]  # 그림을 보내지 않는다
    assert files.chunks_of(session, f.id) == []
    assert (f.status, f.reason) == ("classified", BIG_IMAGE)


async def test_bad_json_counts_as_failure(session, conn, llm, put):
    f = _indexed(session, put("양생", "a.txt"))
    llm.push(chat_body("분류할 수 없습니다"))
    with pytest.raises(classify.ClassifyFailed):
        await classify.classify(session, f.id)
    session.expire_all()
    assert (f.status, f.reason) == ("indexed", FAILED)


async def test_deleted_files_are_not_classified(session, conn, llm, put, admin_user, classify_on):
    f = _indexed(session, put("양생", "a.txt"))
    files.soft_delete(session, f.id, admin_user)
    await classify.after_index(f.id)
    assert llm.bodies == []


async def test_extracted_file_is_classified_without_vectors(session, conn, llm, put, classify_on):
    assert vectors.STORE is None  # 뜻 검색 꺼짐(주소 빈 값·잘못된 주소)
    f = put("양생 기준", "시방서.txt")
    llm.push(answer(kind=["시방서"], summary="양생 기준"))
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.summary) == ("extracted", "양생 기준")  # extracted 그대로 — 뒤에 임베딩될 수 있게
    assert files.axes_of(session, f.id)["종류"] == ["시방서"]


async def test_worker_runs_and_classifies_when_vectors_are_off(session, conn, llm, put, monkeypatch, classify_on):
    monkeypatch.setenv("CHRONOS_QDRANT_URL", "")
    monkeypatch.setattr(vectors, "STORE", None)
    llm.push(answer(kind=["시방서"]))
    jobs.start.__wrapped__()  # 진짜 start(tests/conftest.py 의 시험용 감쌈 안쪽)
    try:
        f = put("양생 기준", "시방서.txt")
        for _ in range(100):
            await asyncio.sleep(0.02)
            session.expire_all()
            if f.summary:
                break
        assert (f.status, f.summary) == ("extracted", "한 줄 요약")
    finally:
        await jobs.stop()


@pytest.fixture
def qdrant_up(monkeypatch, store) -> dict:
    """store.available 을 바꿔 끼운다: qdrant_up["ok"] = False 면 Qdrant 가 꺼진 것."""
    state = {"ok": False}
    monkeypatch.setattr(store, "available", lambda: state["ok"])
    return state


async def test_qdrant_down_still_classifies_and_keeps_the_file_waiting(session, ready, llm, put, qdrant_up,
                                                                      classify_on):
    f = put("동절기 타설", "계획.txt")
    llm.push(answer(kind=["계획서"]))
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason, f.summary) == ("extracted", NOT_READY, "한 줄 요약")
    assert jobs.waiting() == [f.id]  # 「다시 넣기」 줄에 남는다


async def test_classified_first_then_embedded_ends_classified(session, ready, llm, put, store, qdrant_up,
                                                             classify_on):
    f = put("동절기 타설", "계획.txt")
    llm.push(answer(kind=["계획서"]))
    await jobs.drain()
    qdrant_up["ok"] = True  # Qdrant 가 돌아왔다
    assert await jobs.recheck() == 1
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason) == ("classified", None)
    assert len(llm.bodies) == 1  # 두 번 분류하지 않는다
    assert store.search(OLD, vector("겨울", SMALL), 5)[0][0] == files.chunks_of(session, f.id)[0].id


async def test_summary_means_no_llm_on_restart_or_late_embedding(session, ready, llm, put, monkeypatch, classify_on):
    left = _indexed(session, put("양생", "a.txt"))
    left.summary = "이미 요약"
    late = put("동절기 타설", "b.txt")  # 먼저 분류되고 아직 임베딩 안 됨
    late.summary = "이미 요약"
    session.commit()
    monkeypatch.setattr(jobs, "_queue", [])  # 서버가 다시 떴다
    jobs.reload()
    await jobs.drain()
    session.expire_all()
    assert llm.bodies == []
    assert (left.status, late.status) == ("indexed", "classified")


async def test_big_image_reason_survives_late_embedding(session, ready, llm, admin_user, classify_on):
    f = files.save_upload(session, PNG + b"\0" * (5 * 1024 * 1024), "큰사진.png", admin_user)
    f.reason, f.summary = NOT_READY, "큰 사진"  # 분류는 됐고 뜻 검색이 늦었다
    session.commit()
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason) == ("classified", BIG_IMAGE) and llm.bodies == []


async def test_summary_is_one_line_and_never_empty(session, conn, llm, put):
    f = _indexed(session, put("양생", "a.txt"))
    llm.push(answer(summary="  콘크리트\n 양생   기준 "))
    assert (await classify.classify(session, f.id)).summary == "콘크리트 양생 기준"
    g = _indexed(session, put("배근", "배근_검측.txt"))
    llm.push(answer(summary="  "))
    assert (await classify.classify(session, g.id)).summary == "배근_검측.txt"  # 비면 파일 이름


async def test_restart_classifies_files_left_indexed(session, ready, llm, put, monkeypatch, classify_on):
    failed = _indexed(session, put("양생 기준", "a.txt"))
    failed.reason = FAILED
    session.commit()
    monkeypatch.setattr(jobs, "_queue", [])  # 서버가 다시 떴다
    jobs.reload()
    llm.push(answer(kind=["시방서"]))
    await jobs.drain()
    session.expire_all()
    assert (failed.status, failed.reason) == ("classified", None)  # 실패한 분류는 다시 해 본다
    assert _purposes(session) == ["light"]  # 임베딩은 다시 하지 않는다


# ── 값 합치기 제안 ───────────────────────────────────────────────────


def _suggestions(items: list[dict]) -> dict:
    return chat_body(json.dumps({"items": items}, ensure_ascii=False))


async def test_merge_suggestions_are_made_once_a_day_and_checked(client, admin, user, session, conn, llm, put,
                                                                 classify_on):
    f = put("양생", "a.txt")
    client.patch(f"/api/files/{f.id}/axes", json={"종류": ["시방서", "시방 서류"], "공종": ["골조"]}, headers=admin)
    llm.push(_suggestions([
        {"axis": "종류", "from": ["시방 서류"], "to": "시방서", "why": "같은 뜻"},
        {"axis": "종류", "from": ["없는 값"], "to": "시방서", "why": "x"},  # 없는 값 → 버림
        {"axis": "공종", "from": ["골조"], "to": "골조", "why": "x"},  # 자기 자신 → 버림
    ]))

    await merge_suggest.suggest_if_due()
    await merge_suggest.suggest_if_due()  # 하루 안에는 다시 만들지 않는다

    assert len(llm.bodies) == 1 and "시방 서류" in llm.last_messages_text
    assert client.get("/api/files/merge-suggestions", headers=user).status_code == 403
    body = client.get("/api/files/merge-suggestions", headers=admin).json()
    assert body["items"] == [{"axis": "종류", "from": ["시방 서류"], "to": "시방서", "why": "같은 뜻"}]
    assert body["made_at"] is not None

    client.post("/api/files/merge", json={"axis": "종류", "from": ["시방 서류"], "to": "시방서"}, headers=admin)
    assert client.get("/api/files/merge-suggestions", headers=admin).json()["items"] == []  # 합친 제안은 빠진다


async def test_merge_suggestions_tell_the_agent_about_crowded_axes(session, conn, llm, monkeypatch, classify_on):
    _seed(session, "공종", *(f"공종{i:02d}" for i in range(31)))
    llm.push(_suggestions([]))
    await merge_suggest.suggest_if_due()
    assert "공종: 31개" in llm.last_messages_text

    # 하루가 지나면 다시
    later = datetime.now(UTC) + timedelta(days=1, minutes=1)
    monkeypatch.setattr(merge_suggest, "_now", lambda: later)
    llm.push(_suggestions([]))
    await merge_suggest.suggest_if_due()
    assert len(llm.bodies) == 2


async def test_no_values_to_compare_means_no_llm_call(session, conn, llm, classify_on):
    _seed(session, "종류", "시방서")
    await merge_suggest.suggest_if_due()
    assert llm.bodies == []


def _good(session) -> dict:
    _seed(session, "종류", "시방서", "시방 서류")
    return {"axis": "종류", "from": ["시방 서류"], "to": "시방서", "why": "같은 뜻"}


async def test_broken_suggestions_file_counts_as_empty(client, admin, session, conn, llm, classify_on):
    path = Settings().data_dir / "files" / "merge_suggestions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{깨진", encoding="utf-8")
    assert client.get("/api/files/merge-suggestions", headers=admin).json() == {"made_at": None, "items": []}
    item = _good(session)
    llm.push(_suggestions([item]))
    await merge_suggest.suggest_if_due()  # 깨진 파일 = 아직 없음 → 새로 만든다
    assert client.get("/api/files/merge-suggestions", headers=admin).json()["items"] == [item]


async def test_bad_answer_keeps_the_previous_suggestions(client, admin, session, conn, llm, monkeypatch, classify_on):
    item = _good(session)
    llm.push(_suggestions([item]))
    await merge_suggest.suggest_if_due()
    later = datetime.now(UTC) + timedelta(days=1, minutes=1)
    monkeypatch.setattr(merge_suggest, "_now", lambda: later)
    llm.push(chat_body(json.dumps({"wrong": []})))
    await merge_suggest.suggest_if_due()
    assert len(llm.bodies) == 2
    body = client.get("/api/files/merge-suggestions", headers=admin).json()
    assert body["items"] == [item] and body["made_at"].startswith(later.date().isoformat())


async def test_hand_broken_suggestion_lines_are_dropped(client, admin, session):
    item = _good(session)
    path = Settings().data_dir / "files" / "merge_suggestions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    broken = [
        {"axis": "종류", "from": ["시방 서류"], "to": "시방서"},  # why 없음
        {"axis": "종류", "from": [], "to": "시방서", "why": "x"},  # from 빈 목록
        {"axis": ["종류"], "from": ["시방 서류"], "to": "시방서", "why": "x"},
        {"axis": "종류", "from": "시방 서류", "to": "시방서", "why": "x"},
    ]
    path.write_text(json.dumps({"made_at": None, "items": [*broken, item]}, ensure_ascii=False), encoding="utf-8")
    r = client.get("/api/files/merge-suggestions", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == [item]


async def test_cancelling_during_indexing_never_classifies(session, put, monkeypatch):
    calls: list[int] = []

    async def spy(file_id: int) -> None:
        calls.append(file_id)

    async def cancelled(file_id: int) -> None:
        raise asyncio.CancelledError

    async def broken(file_id: int) -> None:
        raise RuntimeError

    monkeypatch.setattr(classify, "after_index", spy)
    f = put("양생", "a.txt")
    monkeypatch.setattr(jobs, "_index_file", cancelled)
    with pytest.raises(asyncio.CancelledError):  # 서버를 끈다
        await jobs._do(jobs._Item("file", f.id))
    assert calls == []
    monkeypatch.setattr(jobs, "_index_file", broken)
    await jobs._do(jobs._Item("file", f.id))  # 임베딩 실패는 그래도 분류
    assert calls == [f.id]
