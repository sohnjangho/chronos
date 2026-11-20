"""대화에 붙인 파일(Task 50): 맥락 줄 「이 대화에 붙인 파일」, 도구 files.read·files.search, 지운 파일.

파일·사람·현장은 모두 가상이다(5층 사무동 신축 · A현장). 뜻 검색은 꺼져 있어(시험 설정) 낱말 검색만 돈다.
"""

import io
import json

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.agent import image_turn, loop
from app.agent.context import UiContext, build_context
from app.agent.trace import context_parts
from app.files import jobs
from app.files.search import search
from app.llm.client import LlmClient
from app.store import chats, files
from app.store.tables import FileAxis, FileRow, User, WorkflowRun
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.registry import call
from tests.fixtures.files import make
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

PAGES = [
    "Concrete strength C24 is required for the 5F office building slab.",
    "Rebar inspection precedes every pour.",
    "Winter curing needs a heated enclosure for 7 days.",
]


@pytest.fixture(autouse=True)
def empty_jobs(monkeypatch):
    """올린 파일이 프로세스의 작업 줄에 남지 않게(tests/files 와 같은 방식)."""
    monkeypatch.setattr(jobs, "_queue", [])
    monkeypatch.setattr(jobs, "_waiting", set())
    monkeypatch.setattr(jobs, "_cursors", {})


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def chat_id(session, admin_user) -> int:
    return chats.create_chat(session, user_id=admin_user.id).id


@pytest.fixture
def chat_ctx(session, admin_user, chat_id, events) -> ToolContext:
    return ToolContext(session=session, user=admin_user, schedule_id=None, emit=events.append, chat_session_id=chat_id)


@pytest.fixture
def put(session, admin_user):
    """put(내용 bytes|str, 이름, chat_id=None) → 올린 파일(대화를 주면 붙인다)."""

    def upload(body: bytes | str, name: str, chat_id: int | None = None) -> FileRow:
        data = body.encode("utf-8") if isinstance(body, str) else body
        row = files.save_upload(session, data, name, admin_user)
        if chat_id is not None:
            files.link(session, chat_id, row.id)
        return row

    return upload


def pdf(pages: list[str]) -> bytes:
    writer = PdfWriter()
    for text in pages:
        make._text_page(writer, text)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def files_lines(session, admin_user, chat_id) -> list[str]:
    """system 메시지의 「이 대화에 붙인 파일」 줄(지시문 조각 글은 빼고)."""
    system = build_context(session, admin_user, chat_id, UiContext())[0]["content"]
    return [x for x in system.splitlines() if x.startswith("- 이 대화에 붙인 파일: ")]


# ── 맥락 줄 ─────────────────────────────────────────────────────────


async def test_context_lists_session_files_with_status(session, admin_user, chat_id, put):
    spec = put(pdf(PAGES), "시방서_A현장.pdf", chat_id)
    spec.status, spec.summary = "classified", "콘크리트 양생 최소 7일"
    session.add_all([FileAxis(file_id=spec.id, axis="공종", value="골조"),
                     FileAxis(file_id=spec.id, axis="종류", value="시방서")])
    photo = put(make.png(), "1103.jpg", chat_id)
    broken = put(b"%PDF-1.4 broken", "깨진.pdf", chat_id)
    session.commit()
    [line] = files_lines(session, admin_user, chat_id)
    assert line == (
        f'- 이 대화에 붙인 파일: #{spec.id} 시방서_A현장.pdf (pdf · 시방서·골조 · 분류됨) "콘크리트 양생 최소 7일"'
        f" | #{photo.id} 1103.jpg (image · 읽음)"
        f" | #{broken.id} 깨진.pdf (pdf · 실패 — {broken.reason})"
    )


async def test_context_shows_latest_20_files(session, admin_user, chat_id, put):
    rows = [put(f"메모 {n}", f"메모{n:02}.txt", chat_id) for n in range(22)]
    [line] = files_lines(session, admin_user, chat_id)
    assert f"#{rows[0].id} " not in line and f"#{rows[1].id} " not in line
    assert line.count(" | ") == 20 and line.endswith(" | 외 2개")
    assert line.startswith(f"- 이 대화에 붙인 파일: #{rows[2].id} 메모02.txt (text · 읽음)")


async def test_long_names_and_reasons_are_cut(session, admin_user, chat_id, put):
    name = "가" * 100 + ".txt"
    memo = put("골조", name, chat_id)
    memo.reason = "나" * 100
    session.commit()
    [line] = files_lines(session, admin_user, chat_id)
    assert f"#{memo.id} {'가' * 60}… (text · 읽음 — {'나' * 60}…)" in line


async def test_trace_counts_the_files_line(session, admin_user, chat_id, put):
    put("골조 1층 기둥", "메모.txt", chat_id)
    tools = registry.as_llm_tools()
    parts = {p["name"]: p["chars"] for p in context_parts(session, admin_user, chat_id, UiContext(), tools)}
    system = build_context(session, admin_user, chat_id, UiContext())[0]["content"]
    text_parts = ["지시문", "분야 지식", "정밀도", "지금 상황", "날짜 도우미"]
    assert sum(parts[n] for n in text_parts) == len(system) - 4


async def test_no_files_no_line(session, admin_user, chat_id):
    assert files_lines(session, admin_user, chat_id) == []


async def test_deleted_file_in_session_context(session, admin_user, chat_id, put):  # Review Focus 4
    memo = put("골조 1층 기둥 타설 5일", "메모.txt", chat_id)
    files.soft_delete(session, memo.id, admin_user)
    add_connection(session)
    llm = ScriptedLlm([calls("files.read", {"file_id": memo.id}), reply("지운 파일이라 읽지 못했습니다.")])
    client = LlmClient(session, transport=llm.transport)
    events = [e async for e in loop.run_turn(session, admin_user, chat_id, "메모 내용 알려 줘", UiContext(), llm=client)]

    assert f"- 이 대화에 붙인 파일: #{memo.id} 메모.txt (지워짐)" in llm.bodies[0]["messages"][0]["content"]
    assert "골조 1층" not in llm.bodies[0]["messages"][0]["content"]
    end = next(e for e in events if e.type == "tool_end")
    assert end.data["ok"] is False and end.data["error"] == "지워진 파일입니다."
    assert [e.type for e in events][-3:] == ["workflow", "usage", "done"] and "error" not in [e.type for e in events]
    assert events[-4].data == {"text": "지운 파일이라 읽지 못했습니다."}
    session.expire_all()
    assert session.scalars(select(WorkflowRun)).one().status == "done"


# ── files.read ──────────────────────────────────────────────────────


async def test_read_file_returns_locators(chat_ctx, chat_id, put):
    spec = put(pdf(PAGES), "시방서_A현장.pdf", chat_id)
    r = await call("files.read", {"file_id": spec.id, "page": 3}, chat_ctx)
    assert r.ok, r.error
    assert r.output["parts"][0]["locator"] == "3쪽" and "heated enclosure" in r.output["parts"][0]["text"]
    assert {k: r.output[k] for k in ("file_id", "name", "kind", "status", "pages", "image")} == {
        "file_id": spec.id, "name": "시방서_A현장.pdf", "kind": "pdf", "status": "extracted", "pages": 3, "image": False,
    }
    found = await call("files.read", {"file_id": spec.id, "query": "heated enclosure"}, chat_ctx)
    assert found.output["parts"][0]["locator"] == "3쪽"
    head = await call("files.read", {"file_id": spec.id}, chat_ctx)
    assert [p["locator"] for p in head.output["parts"]] == ["1쪽", "2쪽", "3쪽"]


async def test_read_file_query_stays_inside_that_file(chat_ctx, chat_id, put):
    put("heated enclosure heated enclosure heated enclosure", "다른메모.txt")
    spec = put(pdf(PAGES), "시방서_A현장.pdf", chat_id)
    r = await call("files.read", {"file_id": spec.id, "query": "heated enclosure"}, chat_ctx)
    assert [p["locator"] for p in r.output["parts"]] == ["3쪽"]


async def test_read_file_first_five_parts_and_missing_page(chat_ctx, put):
    long = put("\n".join(f"{n}번째 줄 " + "가" * 300 for n in range(20)), "긴메모.txt")
    r = await call("files.read", {"file_id": long.id}, chat_ctx)
    assert len(r.output["parts"]) == 5 and all(len(p["text"]) <= 600 for p in r.output["parts"])
    assert len(json.dumps(r.output, ensure_ascii=False)) < 4000  # 도구 결과 한도 안
    missing = await call("files.read", {"file_id": long.id, "page": 2}, chat_ctx)
    assert missing.ok is False and missing.error == "없는 쪽입니다(이 파일은 1쪽까지입니다)."


async def test_read_unknown_file(chat_ctx):
    r = await call("files.read", {"file_id": 999}, chat_ctx)
    assert r.ok is False and r.error == "없는 파일입니다."


async def test_read_image_flag_only_for_pictures(chat_ctx, put, monkeypatch):
    memo = put("골조", "메모.txt")
    photo = put(make.png(), "1103.jpg")
    text = (await call("files.read", {"file_id": memo.id, "image": True}, chat_ctx)).output
    assert (text["image"], text["image_note"]) == (False, "그림 파일이 아니라 그림을 붙이지 않았습니다.")
    shown = (await call("files.read", {"file_id": photo.id, "image": True}, chat_ctx)).output
    assert (shown["image"], shown["image_note"]) == (True, None)
    plain = (await call("files.read", {"file_id": photo.id}, chat_ctx)).output
    assert (plain["image"], plain["image_note"]) == (False, None)
    monkeypatch.setattr(image_turn, "IMAGE_MAX_BYTES", photo.size)  # 원본은 들어가도 base64 는 넘는다
    big = (await call("files.read", {"file_id": photo.id, "image": True}, chat_ctx)).output
    assert (big["image"], big["image_note"]) == (False, "그림이 커서 붙이지 않았습니다. 설명 글(parts)을 쓰세요.")


# ── files.search ────────────────────────────────────────────────────


async def test_search_prefers_session_files(session, chat_ctx, ctx, chat_id, put):
    other = put("동절기 타설 보온 양생. 동절기 타설은 보온 양생을 한다. 동절기 타설.", "B현장_메모.txt")
    mine = put("동절기 타설 기준 메모", "A현장_메모.txt", chat_id)
    session.add(FileAxis(file_id=mine.id, axis="현장", value="A현장"))
    session.commit()
    outside = await call("files.search", {"query": "동절기 타설"}, ctx)  # 대화 밖: 낱말 순위 그대로
    assert [h["file_id"] for h in outside.output["hits"]] == [other.id, mine.id]
    r = await call("files.search", {"query": "동절기 타설"}, chat_ctx)
    assert [h["file_id"] for h in r.output["hits"]] == [mine.id, other.id]
    assert r.output["hits"][0] == {"file_id": mine.id, "name": "A현장_메모.txt", "locator": "본문",
                                   "text": "동절기 타설 기준 메모", "axes": {"현장": ["A현장"]}}


async def test_search_filters_limit_and_text_cut(session, admin_user, chat_ctx, put):
    a = put("동절기 타설 " + "가" * 600, "A.txt")
    b = put("동절기 타설 B", "B.txt")
    session.add(FileAxis(file_id=a.id, axis="공종", value="골조"))
    session.commit()
    r = await call("files.search", {"query": "동절기 타설", "filters": {"공종": ["골조"]}}, chat_ctx)
    assert [h["file_id"] for h in r.output["hits"]] == [a.id] and len(r.output["hits"][0]["text"]) == 400
    one = await call("files.search", {"query": "동절기 타설", "limit": 1}, chat_ctx)
    assert len(one.output["hits"]) == 1
    files.soft_delete(session, b.id, admin_user)
    assert b.id not in [h["file_id"] for h in (await call("files.search", {"query": "타설"}, chat_ctx)).output["hits"]]
    bad = await call("files.search", {"query": "x", "limit": 11}, chat_ctx)
    assert bad.ok is False


async def test_search_inside_given_files_meets_axis_filter(session, put):
    a, b, c = put("동절기 타설 A", "A.txt"), put("동절기 타설 B", "B.txt"), put("동절기 타설 C", "C.txt")
    session.add_all([FileAxis(file_id=a.id, axis="공종", value="골조"), FileAxis(file_id=b.id, axis="공종", value="골조")])
    session.commit()
    assert {h.file_id for h in await search(session, "동절기 타설", file_ids=[b.id, c.id])} == {b.id, c.id}
    assert {h.file_id for h in await search(session, "동절기 타설", file_ids=[b.id, c.id],
                                           filters={"공종": ["골조"]})} == {b.id}
    assert await search(session, "동절기 타설", file_ids=[]) == []
