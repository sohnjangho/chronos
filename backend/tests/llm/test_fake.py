"""시험·시연용 가짜 Liner(app.llm.fake): CHRONOS_FAKE_LLM=1 일 때만 LlmClient 의 기본 transport 가 된다."""

import json
import logging

import pytest

from app.llm import client as client_module
from app.llm import fake
from app.llm.client import LlmClient
from app.tools import registry
from app.tools.ask.make_questionnaire import AskIn
from app.tools.registry import to_llm_name
from app.tools.respond.make_shortening import DATE_IN_TEXT, SHORTEN_NOTE_SCHEMA
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


# ── 묶음 2 대본(지연 → 만회) ──────────────────────────────────────────────

DELAY = "지상 골조가 비 때문에 3일 늦어졌어"
SITUATION = {"role": "system", "content": "지금 상황\n- 고른 액티비티: A1210 1층 철근 배근 · 시작 2027-04-29"}


def _ask(tools: list[dict], messages: list[dict], **extra) -> dict:
    return fake.answer({"messages": messages, "tools": tools, **extra})


def _calls(body: dict) -> list[tuple[str, dict, str]]:
    calls = body["choices"][0]["message"].get("tool_calls") or []
    return [(c["function"]["name"], json.loads(c["function"]["arguments"]), c["id"]) for c in calls]


def _text(body: dict) -> str:
    return body["choices"][0]["message"]["content"]


def _called(name: str, call_id: str, args: dict, result: dict) -> list[dict]:
    """도구 호출 한 번과 그 결과(루프가 LLM 에 보내는 모양)."""
    return [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": to_llm_name(name), "arguments": json.dumps(args)}}]},
        {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)},
    ]


FOUND = {"matches": [{"id": "A1210", "name": "1층 철근 배근"}]}
RECORDED = {"event_id": 1, "status": "open", "impact": {"finish_delta": 3}, "totals": {}}


def test_a_delay_first_finds_the_selected_activity(tools):
    [(name, args, _)] = _calls(_ask(tools, [SITUATION, {"role": "user", "content": DELAY}]))
    assert (name, args) == (to_llm_name("schedule.find"), {"query": "A1210"})


def test_a_delay_without_a_selection_looks_for_frame_work(tools):
    [(_, args, _)] = _calls(_ask(tools, [{"role": "user", "content": DELAY}]))
    assert args == {"query": "골조"}


def test_then_records_the_found_activity_with_days_and_cause(tools):
    history = [SITUATION, {"role": "user", "content": DELAY}, *_called("schedule.find", "fake_call_1", {"query": "A1210"}, FOUND)]
    [(name, args, call_id)] = _calls(_ask(tools, history))
    assert (name, args) == (to_llm_name("delay.record"), {"activity_id": "A1210", "days": 3, "cause": "비"})
    assert call_id != "fake_call_1"  # 한 턴 안에서 호출 id 가 겹치지 않는다(결과 짝이 틀어지지 않게)


def test_nothing_found_says_so(tools):
    history = [{"role": "user", "content": DELAY}, *_called("schedule.find", "c1", {"query": "골조"}, {"matches": []})]
    body = _ask(tools, history)
    assert _calls(body) == [] and _text(body) == fake.NOT_FOUND_TEXT


def test_after_recording_it_talks_and_a_failed_record_is_reported_honestly(tools):
    base = [{"role": "user", "content": DELAY}, *_called("schedule.find", "c1", {"query": "A1210"}, FOUND)]
    ok = _ask(tools, [*base, *_called("delay.record", "c2", {}, RECORDED)])
    assert _calls(ok) == [] and _text(ok) == fake.DELAY_DONE_TEXT
    failed = _ask(tools, [*base, *_called("delay.record", "c2", {}, {"error": "없는 액티비티입니다: A1210"})])
    assert _text(failed) != fake.DELAY_DONE_TEXT and "기록하지 못했습니다" in _text(failed)
    assert "없는 액티비티입니다: A1210" in _text(failed)


def test_recovery_makes_shortening_options_then_talks(tools):
    earlier = [{"role": "user", "content": DELAY}, *_called("schedule.find", "c1", {"query": "A1210"}, FOUND),
               *_called("delay.record", "c2", {}, RECORDED), {"role": "assistant", "content": fake.DELAY_DONE_TEXT}]
    asked = [*earlier, {"role": "user", "content": "만회 계획 만들어 줘"}]  # 앞 턴의 도구 호출은 세지 않는다
    [(name, args, _)] = _calls(_ask(tools, asked))
    assert (name, args) == (to_llm_name("shorten.make"), {})
    [(_, args, _)] = _calls(_ask(tools, [{"role": "user", "content": "5일 만회해 줘"}]))
    assert args == {"target_days": 5}
    done = _ask(tools, [*asked, *_called("shorten.make", "c3", {}, {"kind": "shorten_options"})])
    assert _calls(done) == [] and _text(done) == fake.RECOVERY_DONE_TEXT
    failed = _ask(tools, [*asked, *_called("shorten.make", "c3", {}, {"error": "줄일 목표가 없습니다."})])
    assert _text(failed) != fake.RECOVERY_DONE_TEXT and "줄일 목표가 없습니다." in _text(failed)


def test_shortening_note_request_gets_notes_without_dates_and_no_pick():
    options = [{"key": "A", "moves": ["병행"]}, {"key": "B", "moves": ["압축", "자원"]}]
    body = fake.answer({
        "messages": [{"role": "system", "content": "지시"}, {"role": "user", "content": json.dumps(options)}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": SHORTEN_NOTE_SCHEMA}},
    })
    advice = json.loads(_text(body))
    assert advice["recommended"] is None  # 추천은 코드가 고른다
    assert [(n["key"], n["note"]) for n in advice["notes"]] == [
        ("A", fake.NOTE_TEXT.format(n=1)), ("B", fake.NOTE_TEXT.format(n=2))]
    assert not DATE_IN_TEXT.search(" ".join(n["note"] for n in advice["notes"]))


def test_the_bundle1_questionnaire_script_is_unchanged(tools):
    [(name, _, _)] = _calls(_ask(tools, [{"role": "user", "content": "5층 사무동 공정표 만들어 줘"}]))
    assert name == to_llm_name("ask.questionnaire")
