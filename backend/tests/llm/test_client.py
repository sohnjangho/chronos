"""LlmClient: 배정된 모델 부르기, 실패 설명, llm_calls 기록, 키가 새지 않는지."""

import logging

import httpx
import pytest

from app.llm.client import LlmClient, LlmFailed, LlmNotReady, _http_client
from app.store.tables import LlmAssignment, LlmCall
from tests.llm_doubles import KEY, LINER, add_connection, chat_body, tool_call

HI = [{"role": "user", "content": "hi"}]

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


async def test_chat_uses_assignment_and_records_cost(llm, session, fake_liner):
    r = await llm.chat("hard", [{"role": "user", "content": "hi"}])
    assert fake_liner.last_body["model"] == "liner-claude-router" and fake_liner.last_body["routing_strategy"] == "quality"
    assert r.model == "claude-opus-5.5" and r.usage.cost == 0.04 and session.query(LlmCall).one().cost == 0.04
async def test_no_connection_raises_not_ready(llm_empty):
    with pytest.raises(LlmNotReady): await llm_empty.chat("light", [])
async def test_timeout_becomes_llm_failed(llm, fake_liner_timeout):            # Review Focus 2
    with pytest.raises(LlmFailed) as e: await llm.chat("light", [], timeout_s=0.01)
    assert e.value.error.code == "timeout"


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


async def test_request_goes_to_chat_completions_with_bearer_key(llm, liner):
    await llm.chat("light", HI)
    request = liner.last_request
    assert request.method == "POST" and str(request.url) == f"{LINER}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert liner.last_body == {
        "model": "liner-claude-router",
        "messages": HI,
        "routing_strategy": "cost",
    }


async def test_reply_text_and_usage(llm, liner):
    liner.push(chat_body("안녕하세요", prompt_tokens=30, completion_tokens=7, cost=0.002))
    r = await llm.chat("normal", HI)
    assert r.text == "안녕하세요" and r.tool_calls == [] and r.parsed is None
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.cost) == (30, 7, 0.002)


async def test_routing_strategy_omitted_when_assignment_has_none(llm, liner):
    await llm.chat("longdoc", HI)
    assert liner.last_body["model"] == "liner-mark" and "routing_strategy" not in liner.last_body


async def test_stored_assignment_picks_its_connection_and_model(llm, session, liner):
    other = add_connection(
        session, name="다른 곳", base_url="https://llm.example.com/v1/", secret="other-KEY-99998888",
        is_default=False,
    )
    session.add(LlmAssignment(purpose="light", connection_id=other.id, model="m-small", routing_strategy=None))
    session.commit()
    await llm.chat("light", HI)
    assert str(liner.last_request.url) == "https://llm.example.com/v1/chat/completions"
    assert liner.last_request.headers["authorization"] == "Bearer other-KEY-99998888"
    assert liner.last_body["model"] == "m-small" and "routing_strategy" not in liner.last_body


async def test_not_ready_without_connection_says_why(llm_empty, session, liner):
    with pytest.raises(LlmNotReady) as e:
        await llm_empty.chat("light", HI)
    assert e.value.reason == "no_connection" and "연결" in str(e.value)
    assert liner.requests == [] and session.query(LlmCall).count() == 0


async def test_not_ready_when_stored_key_is_unreadable(llm, session, liner, monkeypatch):
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    with pytest.raises(LlmNotReady) as e:
        await llm.chat("light", HI)
    assert e.value.reason == "secret_unreadable" and "키를 다시 넣어 주세요" in str(e.value)
    assert liner.requests == []


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (400, "bad_request", "요청을 처리할 수 없습니다."),
        (401, "bad_key", "API 키가 맞지 않습니다."),
        (429, "rate_limited", "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요."),
        (500, "server_error", "LLM 서버에 문제가 있습니다. 잠시 뒤 다시 해 주세요."),
        (503, "server_error", "LLM 서버에 문제가 있습니다. 잠시 뒤 다시 해 주세요."),
    ],
)
async def test_http_failure_is_explained_and_recorded(llm, session, liner, status, code, message):
    liner.push(httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(LlmFailed) as e:
        await llm.chat("hard", HI, chat_session_id=7)
    assert (e.value.error.code, e.value.error.message) == (code, message)
    assert len(liner.requests) == 1  # 다시 시도하지 않는다
    row = session.query(LlmCall).one()
    assert row.ok is False and row.error_code == code and row.cost is None
    assert (row.purpose, row.requested_model, row.model, row.chat_session_id) == (
        "hard", "liner-claude-router", "liner-claude-router", 7,
    )
    assert (row.input_tokens, row.output_tokens) == (0, 0)


async def test_read_timeout_from_transport_is_timeout(llm, liner):
    liner.push(httpx.ReadTimeout("slow"))
    with pytest.raises(LlmFailed) as e:
        await llm.chat("light", HI)
    assert e.value.error.code == "timeout"


async def test_timeout_is_recorded(llm, session, fake_liner_timeout):
    with pytest.raises(LlmFailed):
        await llm.chat("light", HI, timeout_s=0.01)
    row = session.query(LlmCall).one()
    assert row.ok is False and row.error_code == "timeout"


async def test_connect_error_is_bad_url(llm, liner):
    liner.push(httpx.ConnectError("no route"))
    with pytest.raises(LlmFailed) as e:
        await llm.chat("light", HI)
    assert e.value.error.code == "bad_url"


@pytest.mark.parametrize("response", [httpx.Response(200, text="not json"), {"choices": []}, {"x": 1}])
async def test_unusable_body_is_unknown_failure(llm, session, liner, response):
    liner.push(response)
    with pytest.raises(LlmFailed) as e:
        await llm.chat("light", HI)
    assert e.value.error.code == "unknown" and session.query(LlmCall).one().ok is False


async def test_success_row_has_no_content_and_all_columns(llm, session, liner):
    liner.push(chat_body("비밀스러운 답", prompt_tokens=11, completion_tokens=3, cost=0.5))
    await llm.chat("hard", [{"role": "user", "content": "비밀스러운 질문"}], chat_session_id=3)
    row = session.query(LlmCall).one()
    assert (row.chat_session_id, row.purpose, row.model, row.requested_model, row.routing_strategy) == (
        3, "hard", "claude-opus-5.5", "liner-claude-router", "quality",
    )
    assert (row.input_tokens, row.output_tokens, row.cost, row.ok, row.error_code) == (11, 3, 0.5, True, None)
    assert row.latency_ms >= 0 and row.created_at is not None
    stored = " ".join(str(getattr(row, c.name)) for c in LlmCall.__table__.columns)
    assert "비밀스러운" not in stored and KEY not in stored


async def test_chat_session_id_defaults_to_null(llm, session):
    await llm.chat("light", HI)
    assert session.query(LlmCall).one().chat_session_id is None


async def test_tolerates_missing_cost_usage_tool_calls_and_content(llm, liner):
    liner.push(chat_body(None, cost=None), {"choices": [{"message": {"role": "assistant"}}]})
    r = await llm.chat("light", HI)
    assert r.text == "" and r.tool_calls == [] and r.usage.cost is None and r.usage.input_tokens == 12
    r = await llm.chat("light", HI)
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.cost) == (0, 0, None)
    assert r.model == "liner-claude-router"  # 응답에 model 이 없으면 요청한 이름


async def test_tools_are_sent_and_tool_call_names_come_back_dotted(llm, liner):
    tools = [{"type": "function", "function": {"name": "schedule__read", "description": "d", "parameters": {"type": "object"}}}]
    liner.push(chat_body(None, tool_calls=[
        tool_call("schedule__read", {}, "c1"),
        tool_call("ui__open_window", {"program": "schedule", "params": {"tab": "gantt"}}, "c2"),
    ]))
    r = await llm.chat("normal", HI, tools=tools)
    assert liner.last_body["tools"] == tools
    assert [(c.id, c.name, c.arguments) for c in r.tool_calls] == [
        ("c1", "schedule.read", {}),
        ("c2", "ui.open_window", {"program": "schedule", "params": {"tab": "gantt"}}),
    ]


async def test_unparseable_tool_arguments_become_empty_dict(llm, liner):
    liner.push(chat_body(None, tool_calls=[
        {"id": "c1", "type": "function", "function": {"name": "calc__cpm", "arguments": "{oops"}},
        {"id": "c2", "type": "function", "function": {"name": "calc__cpm", "arguments": "[1]"}},
    ]))
    r = await llm.chat("normal", HI)
    assert [c.arguments for c in r.tool_calls] == [{}, {}]


async def test_dotted_names_in_history_are_sent_in_llm_form(llm, liner):
    history = [
        {"role": "user", "content": "일정 보여줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "schedule.read", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    ]
    await llm.chat("normal", history)
    sent = liner.last_body["messages"]
    assert sent[1]["tool_calls"][0]["function"]["name"] == "schedule__read"
    assert sent[0] == history[0] and sent[2] == history[2]
    assert history[1]["tool_calls"][0]["function"]["name"] == "schedule.read"  # 받은 목록은 그대로


SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


async def test_json_schema_is_sent_and_reply_parsed(llm, liner):
    liner.push(chat_body('{"n": 3}'))
    r = await llm.chat("hard", HI, json_schema=SCHEMA)
    assert liner.last_body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": SCHEMA, "strict": True},
    }
    assert r.parsed == {"n": 3} and r.text == '{"n": 3}'


@pytest.mark.parametrize("text", ["죄송합니다, JSON 이 아닙니다", "[1, 2]", ""])
async def test_json_schema_with_invalid_reply_leaves_parsed_none(llm, liner, text):
    liner.push(chat_body(text))
    r = await llm.chat("hard", HI, json_schema=SCHEMA)
    assert r.parsed is None and r.text == text


async def test_parsed_is_none_when_schema_not_requested(llm, liner):
    liner.push(chat_body('{"n": 3}'))
    r = await llm.chat("hard", HI)
    assert r.parsed is None and "response_format" not in liner.last_body


async def test_key_never_logged_or_stored_or_in_errors(llm, session, liner, caplog):
    caplog.set_level(logging.DEBUG)
    liner.push(chat_body("ok"), httpx.Response(401), httpx.ReadTimeout("slow"), {"x": 1})
    await llm.chat("hard", HI)
    errors = []
    for _ in range(3):
        with pytest.raises(LlmFailed) as e:
            await llm.chat("hard", HI)
        errors.append(e.value)
    assert KEY not in caplog.text and "Bearer" not in caplog.text
    for err in errors:
        assert KEY not in str(err) and KEY not in repr(err) and KEY not in repr(err.error)
        assert err.__cause__ is None and err.__context__ is None
    for row in session.query(LlmCall):
        assert KEY not in " ".join(str(getattr(row, c.name)) for c in LlmCall.__table__.columns)
    assert KEY not in repr(llm) and KEY not in repr(vars(llm))


def test_http_client_ignores_proxy_environment_and_does_not_retry():
    client = _http_client(None, 5)
    assert client.trust_env is False and client.timeout == httpx.Timeout(5)


def test_client_needs_only_a_session(session):
    assert isinstance(LlmClient(session), LlmClient)
