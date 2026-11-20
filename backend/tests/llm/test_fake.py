"""시험·시연용 가짜 Liner(app.llm.fake): CHRONOS_FAKE_LLM=1 일 때만 LlmClient 의 기본 transport 가 된다."""

import logging

import pytest

from app.llm import client as client_module
from app.llm import fake
from app.llm.client import LlmClient
from app.tools import registry
from app.tools.ask.make_questionnaire import AskIn
from tests.llm_doubles import FakeLiner


@pytest.fixture
def tools() -> list[dict]:
    registry.load_all()
    return registry.as_llm_tools()


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 1"])
def test_off_unless_exactly_one(monkeypatch, session, value):
    if value is None:
        monkeypatch.delenv(fake.ENV, raising=False)
    else:
        monkeypatch.setenv(fake.ENV, value)
    assert fake.enabled() is False
    assert LlmClient(session)._transport is None  # 진짜 Liner 로 간다
    with pytest.raises(RuntimeError, match=fake.ENV):
        fake.transport()  # 스위치가 꺼져 있으면 가짜를 만들 수조차 없다


def test_on_makes_the_fake_the_default(monkeypatch, session):
    monkeypatch.setenv(fake.ENV, "1")
    assert fake.enabled() is True
    assert LlmClient(session)._transport is not None
    given = FakeLiner().transport
    assert LlmClient(session, transport=given)._transport is given  # 시험이 넣은 것이 먼저다


async def test_first_request_opens_the_demo_questionnaire(monkeypatch, session, connection, tools):
    monkeypatch.setenv(fake.ENV, "1")
    reply = await LlmClient(session).chat("normal", [{"role": "user", "content": "5층 사무동 공정표 만들어 줘"}],
                                          tools=tools)
    assert [c.name for c in reply.tool_calls] == ["ask.questionnaire"]
    args = AskIn.model_validate(reply.tool_calls[0].arguments)  # 도구가 받는 모양 그대로
    assert args.purpose == "generate" and len(args.questions) >= 3  # 셋 이상이면 질문지 창이 열린다
    assert reply.model == fake.MODEL


async def test_after_a_tool_call_it_only_talks(monkeypatch, session, connection, tools):
    monkeypatch.setenv(fake.ENV, "1")
    history = [
        {"role": "user", "content": "5층 사무동 공정표 만들어 줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "ask.questionnaire", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{\"mode\": \"questionnaire\", \"id\": 1, \"total\": 3}"},
    ]
    reply = await LlmClient(session).chat("normal", history, tools=tools)
    assert reply.tool_calls == [] and "질문지" in reply.text


async def test_without_tools_it_only_talks(monkeypatch, session, connection):
    monkeypatch.setenv(fake.ENV, "1")
    reply = await LlmClient(session).chat("light", [{"role": "user", "content": "안녕"}])
    assert reply.tool_calls == [] and reply.text


def test_startup_warning_only_when_on(monkeypatch, caplog):
    monkeypatch.delenv(fake.ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        client_module.warn_if_fake()
    assert caplog.records == []
    monkeypatch.setenv(fake.ENV, "1")
    with caplog.at_level(logging.WARNING):
        client_module.warn_if_fake()
    assert len(caplog.records) == 1 and fake.ENV in caplog.records[0].getMessage()
