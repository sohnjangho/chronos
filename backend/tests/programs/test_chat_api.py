"""대화 API: 대화 만들기·읽기, 메시지 보내기(SSE), 질문지 제출로 이어 가기, 멈춤, 소유자 확인."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import loop, turns
from app.agent.context import UiContext
from app.llm.client import LlmClient
from app.main import app
from app.programs.chat import service
from app.store import questionnaires as qstore
from app.store.questionnaires import Question
from app.store.tables import User, WorkflowRun
from app.tools import registry
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply


@pytest.fixture
def scripted(session, monkeypatch) -> ScriptedLlm:
    """루프가 쓰는 LLM 을 대본 가짜로 바꾼다(기본 연결 하나). 첫 답은 "안녕하세요"."""
    add_connection(session)
    llm = ScriptedLlm([reply("안녕하세요")])
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    return llm


@pytest.fixture
def chat_id(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


def post(client, chat_id, headers, **body) -> httpx.Response:
    return client.post(f"/api/chat/sessions/{chat_id}/messages", json={"ui": {}, **body}, headers=headers)


def parse(body: str) -> list[tuple[str, dict]]:
    """SSE 본문 → [(event, data)]."""
    out = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n")
        assert event.startswith("event: ") and data.startswith("data: ")
        out.append((event[len("event: "):], json.loads(data[len("data: "):])))
    return out


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_sse_stream_format(client, admin, chat_id, scripted):
    body = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "안녕", "ui": {}}, headers=admin).text
    assert "event: text\n" in body and body.rstrip().endswith("event: done\ndata: {}")


# ── 앱 시작(R1) ─────────────────────────────────────────────────────


def test_startup_loads_every_tool(monkeypatch):
    seen = []
    real = registry.load_all
    monkeypatch.setattr(registry, "load_all", lambda: (seen.append(1), real()))
    with TestClient(app):
        pass
    assert seen == [1]
    names = {s.name for s in registry.list_tools()}
    assert {"ask.fill_answers", "ask.questionnaire", "generate.run", "schedule.read", "ui.open_window"} <= names


# ── 대화 만들기·읽기 ────────────────────────────────────────────────


def test_create_list_and_read_sessions(client, admin, sid):
    created = client.post("/api/chat/sessions", json={"schedule_id": sid}, headers=admin)
    assert created.status_code == 200
    body = created.json()
    assert set(body) == {"id", "title", "schedule_id", "created_at"}
    assert (body["title"], body["schedule_id"]) == ("", sid) and body["created_at"].endswith("Z")
    empty = client.post("/api/chat/sessions", headers=admin).json()  # 본문 없이도 된다
    listed = client.get("/api/chat/sessions", headers=admin).json()
    assert [s["id"] for s in listed] == [empty["id"], body["id"]]  # 새것부터
    detail = client.get(f"/api/chat/sessions/{body['id']}", headers=admin).json()
    assert detail == {**body, "running": False, "messages": []}


def test_messages_are_kept_and_the_title_is_the_first_text(client, admin, chat_id, scripted):
    text = "다섯 층짜리 사무동 신축 일정을 만들어 줘. 착공은 내년 3월이고 준공은 그다음 해 가을이야."
    post(client, chat_id, admin, text=text)
    scripted.push(reply("두 번째 답"))
    post(client, chat_id, admin, text="고마워")
    detail = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()
    assert detail["title"] == text[:40]
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", {"kind": "text", "text": text}),
        ("assistant", {"kind": "text", "text": "안녕하세요"}),
        ("user", {"kind": "text", "text": "고마워"}),
        ("assistant", {"kind": "text", "text": "두 번째 답"}),
    ]
    assert all(set(m) == {"id", "role", "content", "created_at"} for m in detail["messages"])


def test_stream_response_headers_and_events(client, admin, chat_id, scripted):
    r = post(client, chat_id, admin, text="안녕")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert parse(r.text) == [
        ("text", {"text": "안녕하세요"}),
        ("usage", {"input_tokens": 12, "output_tokens": 5, "cost": 0.04, "calls": 1}),
        ("done", {}),
    ]


def test_tool_turn_over_the_api_records_a_workflow(client, admin, chat_id, scripted, sid, session):
    scripted._script.clear()
    scripted.push(calls("schedule.read", {}), reply("두 개입니다."))
    events = parse(post(client, chat_id, admin, text="몇 개야?", ui={"program": "schedule", "schedule_id": sid}).text)
    assert [e for e, _ in events] == [
        "workflow", "tool_start", "tool_end", "workflow", "text", "workflow", "usage", "done",
    ]
    session.expire_all()
    assert session.query(WorkflowRun).one().status == "done"


@pytest.mark.parametrize(
    "body",
    [
        {"ui": {}},
        {"text": "안녕", "questionnaire_id": 1, "ui": {}},
        {"text": "   ", "ui": {}},
        {"text": "안녕", "ui": {"program": "x", "typo": 1}},
        {"text": "가" * 4001, "ui": {}},
    ],
    ids=["neither", "both", "blank", "unknown_ui_field", "too_long"],
)
def test_message_body_is_checked(client, admin, chat_id, body):
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", json=body, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


# ── 소유자(R9) ──────────────────────────────────────────────────────


def test_someone_elses_session_is_404(client, admin, user, chat_id):
    for r in (
        client.get(f"/api/chat/sessions/{chat_id}", headers=user),
        post(client, chat_id, user, text="안녕"),
        client.post(f"/api/chat/sessions/{chat_id}/stop", headers=user),
    ):
        assert r.status_code == 404 and r.json() == {
            "code": "not_found", "message": "대화를 찾을 수 없습니다.", "detail": None,
        }
    assert client.get("/api/chat/sessions", headers=user).json() == []
    assert client.get("/api/chat/sessions/999", headers=admin).status_code == 404


def test_login_is_required(client, chat_id):
    assert client.get("/api/chat/sessions").status_code == 401
    assert client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "x", "ui": {}}).status_code == 401


# ── 한 대화에 한 턴(R10) ───────────────────────────────────────────


def test_second_turn_while_one_is_running_is_409(client, admin, chat_id, scripted):
    claim = turns.claim(chat_id)
    try:
        r = post(client, chat_id, admin, text="또")
        assert r.status_code == 409 and r.json()["code"] == "turn_running"
        assert r.json()["message"] == "앞의 요청을 처리하는 중입니다."
        assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["running"] is True
    finally:
        turns.release(chat_id, claim)
    assert post(client, chat_id, admin, text="이제").status_code == 200
    assert not turns.is_running(chat_id)  # 턴이 끝나면 풀린다


def test_stop_endpoint_sets_the_flag(client, admin, chat_id):
    assert client.post(f"/api/chat/sessions/{chat_id}/stop", headers=admin).json() == {"stopping": False}
    claim = turns.claim(chat_id)
    try:
        assert client.post(f"/api/chat/sessions/{chat_id}/stop", headers=admin).json() == {"stopping": True}
        assert turns.stop_requested(chat_id)
    finally:
        turns.release(chat_id, claim)
    assert not turns.stop_requested(chat_id)


async def test_closing_the_stream_releases_the_turn_and_stops_the_run(session, chat_id, scripted):
    scripted._script.clear()
    scripted.push(calls("schedule.read", {}), reply("끝"))
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    claim = turns.claim(chat_id)
    stream = service.turn_stream(chat_id, admin.id, "x", UiContext(None, None, None), None, claim)
    async for chunk in stream:
        if chunk.startswith("event: tool_start"):
            break
    await stream.aclose()
    assert not turns.is_running(chat_id)
    session.expire_all()
    assert session.query(WorkflowRun).one().status == "stopped"


# ── SSE 글 정리(R4) ─────────────────────────────────────────────────


def test_lone_surrogates_are_replaced_before_sending_and_storing(client, admin, chat_id, scripted):
    scripted._script.clear()
    raw = b'{"model":"m\\ud800","choices":[{"message":{"role":"assistant","content":"hi \\udfff there"}}]}'
    scripted.push(httpx.Response(200, content=raw, headers={"content-type": "application/json"}))
    r = post(client, chat_id, admin, text="안녕")
    assert r.status_code == 200 and ("text", {"text": "hi ? there"}) in parse(r.text)
    messages = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["messages"]
    assert messages[-1]["content"] == {"kind": "text", "text": "hi ? there"}


# ── 질문지 제출로 이어 가기(R7) ─────────────────────────────────────


QUESTIONS = [
    Question(id="floors", group="범위", question="지상 몇 층인가요?", assumption="5층으로 가정합니다.",
             options=[{"value": "5", "label": "5층"}, {"value": "10", "label": "10층"}]),
    Question(id="finish", group="날짜", question="준공 목표일은?", assumption="18개월 뒤로 가정합니다."),
]


def make_questionnaire(session, chat_id: int | None, *, submit: bool = True) -> int:
    qid = qstore.create(session, purpose="generate", title="질문", questions=QUESTIONS, prefilled=[],
                        domain="construction", level="L3", chat_session_id=chat_id)
    qstore.answer(session, qid, "floors", "10")
    if submit:
        qstore.submit(session, qid)
    return qid


def test_submitted_questionnaire_resumes_the_chat(client, admin, chat_id, scripted, session):
    qid = make_questionnaire(session, chat_id)
    r = post(client, chat_id, admin, questionnaire_id=qid)
    assert r.status_code == 200 and r.text.rstrip().endswith("event: done\ndata: {}")
    detail = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()
    assert detail["title"] == "질문지 답"
    first = detail["messages"][0]
    assert first["role"] == "user" and first["content"]["kind"] == "questionnaire_submitted"
    assert first["content"]["questionnaire_id"] == qid
    assert [a["label"] for a in first["content"]["answers"]] == ["10층"]
    assert [a["assumption"] for a in first["content"]["assumed"]] == ["18개월 뒤로 가정합니다."]
    model_input = scripted.last_body["messages"][-1]["content"]
    assert "지상 몇 층인가요?: 10층" in model_input and "준공 목표일은?: 18개월 뒤로 가정합니다." in model_input


@pytest.mark.parametrize("case", ["missing", "still_open", "other_chat", "no_chat"])
def test_questionnaire_resume_rejects_a_wrong_questionnaire(client, admin, chat_id, scripted, session, case):
    other = client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]
    qid = {
        "missing": lambda: 999,
        "still_open": lambda: make_questionnaire(session, chat_id, submit=False),
        "other_chat": lambda: make_questionnaire(session, other),
        "no_chat": lambda: make_questionnaire(session, None),
    }[case]()
    r = post(client, chat_id, admin, questionnaire_id=qid)
    assert r.status_code == 422 and r.json()["code"] == "invalid_questionnaire"
    assert r.json()["message"] == "이 대화에서 제출한 질문지가 아닙니다."
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["messages"] == []
    assert not turns.is_running(chat_id)
