"""그림 턴(Task 50, 설계 5-5): 이번 메시지에 그림이 붙으면 그 턴의 루프 호출은 모두 「그림 읽기」(vision),
첫 사용자 메시지에 그림(image_url), notice 사건. 다음 턴은 글만. files.read {image: true} 는 그 단계부터 vision.
그리고 대화 API 의 file_ids(한도·없는 파일·지운 파일)와 대화 상세의 files.
"""

import base64
import json
import math

import httpx
import pytest
from sqlalchemy import select

from app.agent.context import UiContext
from app.agent.loop import run_turn
from app.files import jobs
from app.llm.client import LlmClient
from app.store import chats, files
from app.store.tables import ChatSessionFile, LlmAssignment, LlmCall, TraceEvent, User
from app.tools import registry
from tests.fixtures.files import make
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

NOTICE = "그림이 있어 그림 읽기 모델(liner-claude-router)로 답합니다."
PNG = make.png()
DATA_URI = "data:image/jpeg;base64," + base64.b64encode(PNG).decode()  # 이름이 .jpg 라 jpeg


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    registry.load_all()
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
def conn(session):
    return add_connection(session)


@pytest.fixture
def run(session, admin_user, chat_id, conn):
    """run(대본, 글, file_ids=…) → 사건 목록."""

    async def go(llm: ScriptedLlm, text: str, **kw):
        client = LlmClient(session, transport=llm.transport)
        return [e async for e in run_turn(session, admin_user, chat_id, text, UiContext(), llm=client, **kw)]

    return go


@pytest.fixture
def photo(session, admin_user):
    return files.save_upload(session, PNG, "1103.jpg", admin_user)


def purposes(session, chat_id) -> list[str]:
    session.expire_all()
    return [c.purpose for c in session.scalars(select(LlmCall).where(LlmCall.chat_session_id == chat_id)
                                               .order_by(LlmCall.id))]


def image_urls(body: dict) -> list[str]:
    out = []
    for m in body["messages"]:
        if isinstance(m.get("content"), list):
            out += [p["image_url"]["url"] for p in m["content"] if p.get("type") == "image_url"]
    return out


async def test_image_turn_uses_vision_and_notice(session, run, chat_id, photo, conn):
    chat = chats.get_chat(session, chat_id)  # 대화 모델을 골랐어도 그 턴은 그림 읽기
    chat.model_connection_id, chat.model_name, chat.model_routing = conn.id, "liner-mark", None
    session.commit()
    llm = ScriptedLlm([calls("files.read", {"file_id": photo.id}), reply("3층 슬래브 거푸집입니다.")])
    events = await run(llm, "이 사진 봐 줘", file_ids=[photo.id])

    assert events[0].type == "notice" and events[0].data == {"text": NOTICE}
    assert [e.type for e in events].count("notice") == 1
    assert purposes(session, chat_id) == ["vision", "vision"]
    assert [(b["model"], b.get("routing_strategy")) for b in llm.bodies] == [("liner-claude-router", "balanced")] * 2
    for body in llm.bodies:
        user = body["messages"][1]
        assert user["role"] == "user" and image_urls(body) == [DATA_URI]
        assert user["content"][0] == {"type": "text", "text": f"이 사진 봐 줘\n(붙인 파일: #{photo.id} 1103.jpg)"}
    stored = chats.messages(session, chat_id)[0].content_json
    assert stored == {"kind": "text", "text": "이 사진 봐 줘",
                      "files": [{"file_id": photo.id, "name": "1103.jpg", "kind": "image"}]}
    assert session.get(ChatSessionFile, (chat_id, photo.id)) is not None
    traces = session.scalars(select(TraceEvent).where(TraceEvent.kind == "llm")).all()
    assert [t.label for t in traces] == ["vision", "vision"] and all("base64" not in t.input_text for t in traces)


async def test_next_turn_uses_description_only(session, run, chat_id, photo):
    await run(ScriptedLlm([reply("거푸집 사진입니다.")]), "이 사진 봐 줘", file_ids=[photo.id])
    photo.summary = "3층 슬래브 거푸집 설치 사진"  # 분류 단계(Task 49)가 쓰는 설명 글
    session.commit()
    llm = ScriptedLlm([reply("거푸집은 설치 중입니다.")])
    events = await run(llm, "아까 사진에서 거푸집 상태는?")

    assert "notice" not in [e.type for e in events]
    assert image_urls(llm.last_body) == [] and "base64" not in json.dumps(llm.last_body)
    assert '"3층 슬래브 거푸집 설치 사진"' in llm.last_body["messages"][0]["content"]
    assert purposes(session, chat_id) == ["vision", "normal"]


async def test_read_image_true_switches_from_that_step(session, run, chat_id, photo):
    files.link(session, chat_id, photo.id)  # 앞 턴에 붙였던 그림
    llm = ScriptedLlm([calls("files.read", {"file_id": photo.id, "image": True}), reply("다시 보니 거푸집입니다.")])
    events = await run(llm, "아까 사진 다시 봐 줘")

    assert purposes(session, chat_id) == ["normal", "vision"]
    assert image_urls(llm.bodies[0]) == []
    last = llm.bodies[1]["messages"]
    assert [m["role"] for m in last[-3:]] == ["assistant", "tool", "user"]
    assert image_urls(llm.bodies[1]) == [DATA_URI]
    kinds = [e.type for e in events]
    assert kinds.count("notice") == 1 and kinds.index("tool_end") < kinds.index("notice") < kinds.index("text")
    assert events[kinds.index("notice")].data == {"text": NOTICE}


async def test_big_picture_is_described_not_sent(session, run, chat_id, photo, monkeypatch):
    from app.agent import image_turn

    monkeypatch.setattr(image_turn, "IMAGE_MAX_BYTES", 10)
    llm = ScriptedLlm([reply("그림이 커서 보지 못했습니다.")])
    await run(llm, "이 사진 봐 줘", file_ids=[photo.id])
    assert image_urls(llm.last_body) == [] and purposes(session, chat_id) == ["vision"]
    assert "1103.jpg: 커서 보내지 않았습니다" in json.dumps(llm.last_body, ensure_ascii=False)


async def test_plain_files_do_not_switch_model(session, run, chat_id, admin_user):
    memo = files.save_upload(session, "골조 1층 기둥".encode(), "메모.txt", admin_user)
    llm = ScriptedLlm([reply("네")])
    events = await run(llm, "메모 봐 줘", file_ids=[memo.id])
    assert "notice" not in [e.type for e in events] and purposes(session, chat_id) == ["normal"]
    assert llm.last_body["messages"][1]["content"] == f"메모 봐 줘\n(붙인 파일: #{memo.id} 메모.txt)"


# ── Fix round 1: base64 기준 상한 · 거절되면 글로 한 번 더 · 연결 없음 · 같은 그림 두 번 ──


def refused(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "image rejected"}})


def llm_errors(session, chat_id) -> list[str | None]:
    session.expire_all()
    return [c.error_code for c in session.scalars(select(LlmCall).where(LlmCall.chat_session_id == chat_id)
                                                  .order_by(LlmCall.id))]


@pytest.mark.parametrize("raw_fits_only", [True, False])
async def test_cap_counts_base64_length(session, run, chat_id, photo, monkeypatch, raw_fits_only):
    from app.agent import image_turn

    encoded = 4 * math.ceil(photo.size / 3)
    monkeypatch.setattr(image_turn, "IMAGE_MAX_BYTES", photo.size if raw_fits_only else encoded)
    llm = ScriptedLlm([reply("네")])
    await run(llm, "이 사진 봐 줘", file_ids=[photo.id])
    assert image_urls(llm.last_body) == ([] if raw_fits_only else [DATA_URI])


async def test_provider_refusal_retries_once_without_pictures(session, run, chat_id, photo):
    llm = ScriptedLlm([refused(400), reply("그림 없이 답합니다.")])
    events = await run(llm, "이 사진 봐 줘", file_ids=[photo.id])
    assert [len(image_urls(b)) for b in llm.bodies] == [1, 0]
    note = f"(그림 #{photo.id} 1103.jpg: 모델이 그림을 받지 못해 보내지 않았습니다)"
    assert note in json.dumps(llm.bodies[1], ensure_ascii=False)
    assert [e.type for e in events if e.type in ("text", "error")] == ["text"]
    assert purposes(session, chat_id) == ["vision", "vision"] and llm_errors(session, chat_id) == ["bad_request", None]


async def test_refusal_is_retried_only_once(session, run, chat_id, photo):
    llm = ScriptedLlm([refused(400), refused(400), reply("안 불림")])
    events = await run(llm, "이 사진 봐 줘", file_ids=[photo.id])
    assert len(llm.bodies) == 2 and events[-2].type == "error" and events[-2].data["reason"] == "bad_request"


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_auth_or_limit_errors_are_not_retried(session, run, chat_id, photo, status):
    llm = ScriptedLlm([refused(status), reply("안 불림")])
    events = await run(llm, "이 사진 봐 줘", file_ids=[photo.id])
    assert len(llm.bodies) == 1 and events[-2].type == "error"


async def test_text_turn_refusal_is_not_retried(session, run, chat_id):
    llm = ScriptedLlm([refused(400), reply("안 불림")])
    events = await run(llm, "안녕")
    assert len(llm.bodies) == 1 and events[-2].data["reason"] == "bad_request"


async def test_vision_without_connection_says_so(session, run, chat_id, photo):
    session.add(LlmAssignment(purpose="vision", connection_id=None, model="liner-claude-router"))
    session.commit()
    events = await run(ScriptedLlm([reply("안 불림")]), "이 사진 봐 줘", file_ids=[photo.id])
    error = next(e for e in events if e.type == "error")
    assert error.data["code"] == "llm_not_ready" and error.data["message"] == (
        "그림 읽기 모델 연결이 없습니다 — 설정 → 작업별 모델 배정에서 「그림 읽기」를 정해 주세요")
    assert error.data["action"] == {"open": "settings", "params": {"section": "llm"}}
    events = await run(ScriptedLlm([reply("네")]), "글만 보냅니다")  # 그림 없는 턴은 그대로
    assert "error" not in [e.type for e in events]


async def test_same_picture_is_not_attached_twice(session, run, chat_id, photo):
    llm = ScriptedLlm([
        calls("files.read", {"file_id": photo.id, "image": True}),
        reply("봤습니다."),
    ])
    await run(llm, "이 사진 봐 줘", file_ids=[photo.id])  # 메시지에 붙인 그림을 다시 열려 함
    assert [len(image_urls(b)) for b in llm.bodies] == [1, 1]
    result = json.loads(llm.bodies[1]["messages"][-1]["content"])
    assert result["image"] is False and result["image_note"] == "이 턴에 이미 붙인 그림입니다. 앞의 그림을 보세요."


async def test_reopened_picture_is_attached_once(session, run, chat_id, photo):
    files.link(session, chat_id, photo.id)
    llm = ScriptedLlm([
        calls("files.read", {"file_id": photo.id, "image": True}),
        calls("files.read", {"file_id": photo.id, "image": True}, call_id="call_2"),
        reply("봤습니다."),
    ])
    await run(llm, "아까 사진 다시 봐 줘")
    assert [len(image_urls(b)) for b in llm.bodies] == [0, 1, 1]
    second = json.loads(llm.bodies[2]["messages"][-1]["content"])
    assert second["image"] is False and "이미 붙인 그림" in second["image_note"]


# ── 대화 API ────────────────────────────────────────────────────────


@pytest.fixture
def api_chat(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


def post(client, chat_id, headers, **body):
    return client.post(f"/api/chat/sessions/{chat_id}/messages", json={"ui": {}, **body}, headers=headers)


def test_message_with_11_files_is_refused(client, admin, api_chat):
    r = post(client, api_chat, admin, text="x", file_ids=list(range(1, 12)))
    assert r.status_code == 422 and [(d["loc"], d["type"]) for d in r.json()["detail"]] == [(["body", "file_ids"], "too_long")]


def test_files_need_text(client, admin, api_chat, photo):
    r = post(client, api_chat, admin, questionnaire_id=1, file_ids=[photo.id])
    assert r.status_code == 422 and "파일은 글(text)과 함께 보냅니다." in r.json()["detail"][0]["msg"]


def test_unknown_or_deleted_file_is_refused(client, admin, api_chat, session, admin_user, photo):
    r = post(client, api_chat, admin, text="x", file_ids=[photo.id, 999])
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("invalid_file", "없는 파일입니다.")
    files.soft_delete(session, photo.id, admin_user)
    r = post(client, api_chat, admin, text="x", file_ids=[photo.id])
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("invalid_file", "지워진 파일입니다.")
    assert session.scalars(select(ChatSessionFile)).all() == []


def test_message_with_files_links_them(client, admin, api_chat, session, photo, monkeypatch, conn):
    from app.agent import loop

    llm = ScriptedLlm([reply("봤습니다.")])
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    body = post(client, api_chat, admin, text="이 사진 봐 줘", file_ids=[photo.id, photo.id]).text
    assert body.startswith(f"event: notice\ndata: {json.dumps({'text': NOTICE}, ensure_ascii=False)}\n\n")
    session.expire_all()
    assert [(f.session_id, f.file_id) for f in session.scalars(select(ChatSessionFile))] == [(api_chat, photo.id)]


def test_detail_lists_session_files(client, admin, api_chat, session, admin_user, photo):
    memo = files.save_upload(session, "골조".encode(), "메모.txt", admin_user)
    files.link(session, api_chat, photo.id)
    files.link(session, api_chat, memo.id)
    files.soft_delete(session, memo.id, admin_user)
    detail = client.get(f"/api/chat/sessions/{api_chat}", headers=admin).json()
    assert detail["files"] == [
        {"file_id": photo.id, "name": "1103.jpg", "kind": "image", "status": "extracted", "deleted": False},
        {"file_id": memo.id, "name": "메모.txt", "kind": "text", "status": "extracted", "deleted": True},
    ]
