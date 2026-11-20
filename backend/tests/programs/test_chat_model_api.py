"""대화 모델 고르기: 한 대화에만 모델을 바꾸고, 에이전트 루프의 대화 호출(normal)에만 쓴다(설계 5-5)."""

import pytest
from pydantic import BaseModel, ConfigDict

from app.agent import loop
from app.llm import assignments
from app.llm.client import LlmClient
from app.store.tables import LlmConnection
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply
from tests.tool_doubles import registered

PICKED = {"model": "google/gemini-4-neon", "routing_strategy": None}


STORED_MODELS = [  # 연결 시험으로 저장된 목록(/models 항목 꼴)
    {"id": "liner-claude-router"},
    {"id": "liner-mark", "endpoints": ["/v1/chat/completions"]},
    {"id": "google/gemini-4-neon", "endpoints": ["/v1/chat/completions"]},
    {"id": "openai/text-embedding-3-small", "endpoints": ["/v1/embeddings"]},
]


@pytest.fixture
def conn(session) -> LlmConnection:
    row = add_connection(session)
    row.models_json = STORED_MODELS
    session.commit()
    return row


@pytest.fixture
def chat_id(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


def _url(chat_id: int) -> str:
    return f"/api/chat/sessions/{chat_id}/model"


def test_pick_read_and_reset_chat_model(client, admin, session, conn, chat_id):
    detail = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()
    assert detail["model"] is None  # 기본 = 설정의 대화 배정

    body = {"connection_id": conn.id, "model": "liner-claude-router", "routing_strategy": "quality"}
    r = client.put(_url(chat_id), json=body, headers=admin)
    assert r.status_code == 200 and r.json() == body
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"] == body
    session.expire_all()
    assert assignments.chat_model(session, chat_id) == assignments.Assignment(
        "normal", conn.id, "liner-claude-router", "quality")

    assert client.delete(_url(chat_id), headers=admin).status_code == 204
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"] is None
    session.expire_all()
    assert assignments.chat_model(session, chat_id) is None


def test_routing_strategy_may_be_left_out(client, admin, conn, chat_id):
    r = client.put(_url(chat_id), json={"connection_id": conn.id, "model": "liner-mark"}, headers=admin)
    assert r.json() == {"connection_id": conn.id, "model": "liner-mark", "routing_strategy": None}


@pytest.mark.parametrize("body", [
    {"connection_id": 999, "model": "m"},
    {"connection_id": 1, "model": ""},
    {"connection_id": 1, "model": "m", "routing_strategy": "fast"},
    {"connection_id": 1, "model": "m", "extra": 1},
])
def test_bad_body_is_422(client, admin, conn, chat_id, body):
    r = client.put(_url(chat_id), json=body, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_unknown_connection_message(client, admin, conn, chat_id):
    r = client.put(_url(chat_id), json={"connection_id": 999, "model": "m"}, headers=admin)
    assert r.json()["message"] == "없는 연결을 골랐습니다."


def test_other_users_chat_model_is_404(client, admin, user, conn, chat_id):
    """대화는 만든 사용자만 본다 — 남의 대화는 있는지도 알리지 않는다(대화 API 의 규칙과 같게 404)."""
    body = {"connection_id": conn.id, "model": "liner-mark"}
    assert client.put(_url(chat_id), json=body, headers=user).status_code == 404
    assert client.delete(_url(chat_id), headers=user).status_code == 404
    assert client.put(_url(chat_id), json=body, headers=admin).status_code == 200
    assert client.delete(_url(chat_id), headers=user).status_code == 404
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"]["model"] == "liner-mark"


@pytest.mark.parametrize("model", ["openai/gpt-none", "openai/text-embedding-3-small"])
def test_model_must_be_a_chat_model_of_that_connection(client, admin, conn, chat_id, model):
    """목록에 없거나 대화용이 아닌(임베딩 전용) 모델은 거절."""
    r = client.put(_url(chat_id), json={"connection_id": conn.id, "model": model}, headers=admin)
    assert r.status_code == 422 and r.json()["message"] == "그 연결에 없는 모델입니다."
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"] is None


def test_untested_connection_is_refused(client, admin, session, chat_id):
    untested = add_connection(session, name="시험 안 함", is_default=False)
    r = client.put(_url(chat_id), json={"connection_id": untested.id, "model": "liner-mark"}, headers=admin)
    assert r.status_code == 422 and r.json()["message"] == "연결 시험을 먼저 해 주세요."


def test_routing_strategy_is_dropped_for_non_router_models(client, admin, conn, chat_id):
    body = {"connection_id": conn.id, "model": "liner-mark", "routing_strategy": "quality"}
    r = client.put(_url(chat_id), json=body, headers=admin)
    assert r.status_code == 200 and r.json()["routing_strategy"] is None
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"]["routing_strategy"] is None


def test_deleted_connection_falls_back_to_assignment(client, admin, session, conn, chat_id):
    client.put(_url(chat_id), json={"connection_id": conn.id, **PICKED}, headers=admin)
    session.delete(session.get(LlmConnection, conn.id))
    session.commit()
    assert assignments.chat_model(session, chat_id) is None
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["model"] is None


class _Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


def test_chat_model_override_only_for_normal(client, admin, conn, chat_id, monkeypatch):
    """고른 모델은 루프의 대화 호출에만. 도구 안의 hard·normal 호출은 설정 배정 그대로."""
    sent: list[tuple[str, int]] = []
    llm = ScriptedLlm(
        [calls("spy.inner", {}), reply("어려운 답"), reply("보통 답"), reply("끝")],
        on_request=lambda body: sent.append((body["model"], body["max_tokens"])),
    )
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))

    async def inner(args: _Empty, ctx) -> _Empty:
        client_ = LlmClient(ctx.session, transport=llm.transport)
        await client_.chat("hard", [{"role": "user", "content": "x"}])
        await client_.chat("normal", [{"role": "user", "content": "y"}])
        return _Empty()

    client.put(_url(chat_id), json={"connection_id": conn.id, **PICKED}, headers=admin)
    with registered("spy.inner", inner):
        r = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "해 줘", "ui": {}}, headers=admin)
    assert r.status_code == 200 and "event: done" in r.text
    assert sent == [
        ("google/gemini-4-neon", 4000),  # 루프의 대화 호출 — 고른 모델
        ("liner-claude-router", 16000),  # 도구 안 hard — 배정 그대로
        ("liner-claude-router", 4000),  # 도구 안 normal — 배정 그대로
        ("google/gemini-4-neon", 4000),  # 루프의 다음 단계도 고른 모델
    ]


def test_without_pick_the_loop_uses_the_assignment(client, admin, conn, chat_id, monkeypatch):
    sent: list[str] = []
    llm = ScriptedLlm([reply("안녕하세요")], on_request=lambda body: sent.append(body["model"]))
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "안녕", "ui": {}}, headers=admin)
    assert sent == ["liner-claude-router"]
