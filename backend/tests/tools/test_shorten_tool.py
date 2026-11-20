"""도구 shorten.make — 단축안(만회안) 복사본 만들기, LLM 설명·추천(날짜가 든 글은 버림), 코드 추천."""

import json
from dataclasses import replace
from datetime import date

import pytest

from app.core.model import Relation, Resource
from app.llm.client import LlmClient
from app.store.schedules import from_json
from app.store.tables import DelayEvent, Scenario
from app.tools.registry import call, list_tools
from app.tools.respond import make_shortening
from tests.approval_doubles import crane, finish_by
from tests.llm_doubles import add_connection, chat_body
from tests.loop_doubles import FAIL, ScriptedLlm
from tests.schedules import make, store, task

NO_TARGET = "줄일 목표가 없습니다. 며칠 당길지 알려 주세요(target_days)."
A_MOVE = "A 절반 지점에서 B 시작 (FS → SS+3)"


def named(i: str, od: int, **k):
    return task(i, od, name=i, **k)


def chain():
    """A 6 → B 4 → C 5 (주 5일, 3/1 월요일 시작). 준공 3/19."""
    return make([named("A", 6), named("B", 4), named("C", 5)], [Relation("A", "B"), Relation("B", "C")])


def note(d: dict) -> dict:
    return chat_body(json.dumps(d, ensure_ascii=False))


class FailingLlm(ScriptedLlm):
    """늘 시간 초과로 실패하는 가짜 LLM."""

    def __init__(self) -> None:
        super().__init__([FAIL("timeout")] * 3)


def get(session, sc: int) -> Scenario:
    session.expire_all()
    return session.get(Scenario, sc)


@pytest.fixture
def use_llm(session, monkeypatch):
    """도구가 쓸 가짜 LLM 을 넣는다(연결 한 줄 포함)."""
    add_connection(session)

    def use(llm: ScriptedLlm) -> ScriptedLlm:
        monkeypatch.setattr(make_shortening, "client_for", lambda c: LlmClient(c.session, transport=llm.transport))
        return llm

    return use


@pytest.fixture
def sid_chain(session) -> int:
    """chain() + 입력 조건 finish_by 2027-03-16 (기준 준공 3/19 → 목표 3일)."""
    return store(session, chain(), [finish_by("2027-03-16")])


@pytest.fixture
def ctx_chain(ctx, sid_chain):
    return replace(ctx, schedule_id=sid_chain)


async def shorten(ctx, llm, use_llm, **args) -> dict:
    use_llm(llm)
    r = await call("shorten.make", args, ctx)
    assert r.ok, r.error
    return r.output


def add_event(session, sid: int, aid: str, days: int, **more) -> int:
    row = DelayEvent(schedule_id=sid, activity_id=aid, start_date=date(2027, 3, 4), days=days, created_by="김하늘",
                     **more)
    session.add(row)
    session.commit()
    return row.id


def test_spec():
    spec = {t.name: t for t in list_tools()}["shorten.make"]
    assert (spec.program, spec.mutates) == ("compare", True)


async def test_target_from_deadline_and_distinct_options(ctx_chain, use_llm):
    llm = ScriptedLlm([note({"recommended": "B", "notes": [{"key": "A", "note": "관계만 바꿉니다"},
                                                           {"key": "B", "note": "작업 시간을 늘립니다"}]})])
    o = await shorten(ctx_chain, llm, use_llm)
    assert o["target"] == 3 and [x["key"] for x in o["options"]] == ["A", "B"]
    assert [x["finish"] for x in o["options"]] == ["2027-03-16", "2027-03-16"]
    assert all(x["violations"] == 0 for x in o["options"]) and o["options"][0]["moves"] == [A_MOVE]
    assert o["recommended_scenario_id"] == o["options"][1]["scenario_id"]
    assert [x["note"] for x in o["options"]] == ["관계만 바꿉니다", "작업 시간을 늘립니다"]
    assert [x["recommended"] for x in o["options"]] == [False, True]


async def test_options_are_shorten_scenarios_with_summary(ctx_chain, use_llm, session, sid_chain):
    llm = ScriptedLlm([note({"recommended": "B", "notes": [{"key": "B", "note": "작업 시간을 늘립니다"}]})])
    o = await shorten(ctx_chain, llm, use_llm)
    a, b = (get(session, x["scenario_id"]) for x in o["options"])
    assert (a.name, a.source, a.status, a.base_version, a.schedule_id) == ("만회안 A · 병행 우선", "shorten", "open", 1,
                                                                           sid_chain)
    assert b.name == "만회안 B · 압축·자원 추가" and a.moves_json == [{"id": "par:A>B", "kind": "parallel", "text": A_MOVE}]
    assert {k: a.summary_json[k] for k in ("gain", "base_finish", "note", "recommended", "finish")} == {
        "gain": 3, "base_finish": "2027-03-19", "note": "", "recommended": False, "finish": "2027-03-16"}
    assert (b.summary_json["note"], b.summary_json["recommended"]) == ("작업 시간을 늘립니다", True)
    assert (o["base"], o["base_finish"], o["schedule_id"]) == ("current", "2027-03-19", sid_chain)
    assert {(x.pred, x.succ, x.type, x.lag) for x in from_json(a.snapshot_json).relations} == {
        ("A", "B", "SS", 3), ("B", "C", "FS", 0)}


async def test_card_and_compare_window(ctx_chain, use_llm, events, sid_chain):
    o = await shorten(ctx_chain, ScriptedLlm([note({"recommended": "A", "notes": []})]), use_llm)
    assert [e.data.get("kind", e.type) for e in events] == ["shorten_options", "open_window"]
    assert events[0].data == {**o, "kind": "shorten_options"}
    rec = o["recommended_scenario_id"]
    assert rec == o["options"][0]["scenario_id"]
    assert events[1].data == {"program": "compare", "params": {"id": str(sid_chain), "base": "current", "other": f"s:{rec}"}}
    assert set(o["options"][0]) == {"scenario_id", "key", "name", "finish", "gain", "reached", "moves", "violations",
                                    "uncheckable", "recommended", "note"}


async def test_llm_gets_option_json_and_hard_schema(ctx_chain, use_llm):
    llm = ScriptedLlm([note({"recommended": "A", "notes": []})])
    await shorten(ctx_chain, llm, use_llm)
    body = llm.last_body
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == make_shortening.SHORTEN_NOTE_SCHEMA
    assert body["max_tokens"] == 16000  # hard
    sent = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
    assert sent[0] == {"key": "A", "name": "만회안 A · 병행 우선", "finish": "2027-03-16", "gain": 3, "reached": True,
                       "moves": [A_MOVE], "violations": 0}
    assert "날짜" in next(m["content"] for m in body["messages"] if m["role"] == "system")


async def test_llm_failure_falls_back_to_code_pick(ctx_chain, use_llm):
    o = await shorten(ctx_chain, FailingLlm(), use_llm)
    assert [x["recommended"] for x in o["options"]] == [True, False] and all(x["note"] == "" for x in o["options"])
    assert o["recommended_scenario_id"] == o["options"][0]["scenario_id"]  # 이동이 적은 A


async def test_no_llm_connection_falls_back_to_code_pick(ctx_chain):
    r = await call("shorten.make", {}, ctx_chain)
    assert r.ok, r.error
    assert [x["recommended"] for x in r.output["options"]] == [True, False]


@pytest.mark.parametrize("text", ["2027-03-16에 끝납니다", "3월 16일에 끝납니다", "3월16일 준공", "2027.03.16 준공"])
async def test_llm_note_with_a_date_is_dropped(ctx_chain, use_llm, text):
    llm = ScriptedLlm([note({"recommended": "A", "notes": [{"key": "A", "note": text}, {"key": "B", "note": "길게"}]})])
    o = await shorten(ctx_chain, llm, use_llm)
    assert [x["note"] for x in o["options"]] == ["", "길게"]
    assert o["options"][0]["recommended"] is True  # 추천은 그대로


@pytest.mark.parametrize("reply", [
    {"recommended": "C", "notes": []},          # 만든 안에 없는 key(C 는 A 와 같아 빠짐)
    {"recommended": None, "notes": []},
    {"notes": []},                               # 모양이 틀림
])
async def test_dropped_recommendation_falls_back_to_code_pick(ctx_chain, use_llm, reply):
    o = await shorten(ctx_chain, ScriptedLlm([note(reply)]), use_llm)
    assert [x["recommended"] for x in o["options"]] == [True, False]


async def test_cut_reply_is_not_used(ctx_chain, use_llm):
    cut = chat_body(json.dumps({"recommended": "B", "notes": [{"key": "B", "note": "설명"}]}), finish_reason="length")
    o = await shorten(ctx_chain, ScriptedLlm([cut]), use_llm)
    assert [(x["recommended"], x["note"]) for x in o["options"]] == [(True, ""), (False, "")]


async def test_target_days_wins(ctx_chain, use_llm):
    o = await shorten(ctx_chain, FailingLlm(), use_llm, target_days=1)
    assert o["target"] == 1 and all(x["reached"] for x in o["options"])


async def test_open_delays_are_in_the_base(ctx_chain, use_llm, session, sid_chain):
    event = add_event(session, sid_chain, "B", 2)  # B +2 → 기준 준공 3/23, 기한 3/16 까지 목표 5
    o = await shorten(ctx_chain, FailingLlm(), use_llm)
    assert (o["base_finish"], o["target"]) == ("2027-03-23", 5) and o["base"].startswith("s:")
    base = get(session, int(o["base"][2:]))
    assert (base.source, base.name, base.delay_event_ids, base.status) == ("delay", "지연 반영안", [event], "open")
    assert get(session, o["options"][0]["scenario_id"]).delay_event_ids == [event]
    assert all(x["finish"] < "2027-03-23" for x in o["options"])


async def test_an_open_delay_scenario_of_the_same_events_is_reused(ctx_chain, use_llm, session, sid_chain):
    add_event(session, sid_chain, "B", 2)
    first = await shorten(ctx_chain, FailingLlm(), use_llm)
    session.commit()
    second = await shorten(ctx_chain, FailingLlm(), use_llm)
    assert second["base"] == first["base"]
    assert session.query(Scenario).filter(Scenario.source == "delay").count() == 1


async def test_without_open_delays(ctx_chain, use_llm, session, sid_chain):
    add_event(session, sid_chain, "B", 2)
    o = await shorten(ctx_chain, FailingLlm(), use_llm, include_open_delays=False)
    assert (o["base"], o["base_finish"], o["target"]) == ("current", "2027-03-19", 3)
    assert get(session, o["options"][0]["scenario_id"]).delay_event_ids == []


async def test_shorten_base_skips_reflected_delays(ctx_chain, use_llm, session, sid_chain):
    add_event(session, sid_chain, "B", 2, status="reflected", reflected_version=1)
    o = await shorten(ctx_chain, FailingLlm(), use_llm)
    assert (o["base"], o["base_finish"]) == ("current", "2027-03-19")


async def test_target_from_plan_when_no_deadline(ctx, use_llm, session):
    """기한이 없으면 Plan(기록한 지연을 빼고 계산) 준공까지: B +2 → 목표 2."""
    sid = store(session, chain())
    add_event(session, sid, "B", 2)
    o = await shorten(replace(ctx, schedule_id=sid), FailingLlm(), use_llm)
    assert (o["base_finish"], o["target"]) == ("2027-03-23", 2)


async def test_no_target_is_tool_error(ctx, sid, session):
    r = await call("shorten.make", {}, replace(ctx, schedule_id=sid))
    assert (r.ok, r.error) == (False, NO_TARGET)
    assert session.query(Scenario).count() == 0


async def test_deadline_already_met_and_on_plan_is_tool_error(ctx, session):
    sid = store(session, chain(), [finish_by("2027-03-31")])
    r = await call("shorten.make", {}, replace(ctx, schedule_id=sid))
    assert r.error == NO_TARGET


async def test_nothing_to_shorten_is_tool_error(ctx, session):
    sid = store(session, make([named("A", 3, actual_start=date(2027, 3, 1))]), [finish_by("2027-03-02")])
    r = await call("shorten.make", {}, replace(ctx, schedule_id=sid))
    assert (r.ok, r.error) == (False, make_shortening.NOTHING_MESSAGE)


@pytest.mark.parametrize("args", [{"target_days": 0}, {"target_days": 366}, {"days": 3}])
async def test_bad_input(ctx_chain, args):
    assert (await call("shorten.make", args, ctx_chain)).error.startswith("입력 형식 오류")


async def test_needs_a_schedule(ctx):
    assert (await call("shorten.make", {}, ctx)).error == "대상 일정이 없습니다."


async def test_add_resource_becomes_input_condition(ctx, use_llm, session):
    """A 6·B 3 이 크레인 1대를 나눠 씀 → 준공 3/11. 기한 3/8 → 목표 3, B 안 = 크레인 2대."""
    two_crane = make([named("A", 6, resources=("crane",)), named("B", 3, resources=("crane",))], (),
                     [Resource("crane", "타워크레인", "대", 1)])
    sid = store(session, two_crane, [finish_by("2027-03-08")])
    o = await shorten(replace(ctx, schedule_id=sid), FailingLlm(), use_llm)
    option_b = next(x for x in o["options"] if x["key"] == "B")
    assert option_b["moves"] == ["타워크레인 1대 → 2대"] and option_b["finish"] == "2027-03-08"
    c = get(session, option_b["scenario_id"]).conditions_json
    assert {"id": "in.resource_cap.crane", "layer": "input", "kind": "resource_cap",
            "params": {"resource_id": "crane", "capacity": 2}, "text": "타워크레인 2대",
            "source": "단축안"}.items() <= next(d for d in c if d["id"] == "in.resource_cap.crane").items()
    assert [d["id"] for d in c] == ["in.finish_by", "in.resource_cap.crane"]
    snap = get(session, option_b["scenario_id"]).snapshot_json
    assert snap["resources"][0]["capacity"] == 1  # 용량은 조건으로만 바꾼다


async def test_add_resource_replaces_the_same_input_condition(ctx, use_llm, session):
    two_crane = make([named("A", 6, resources=("crane",)), named("B", 3, resources=("crane",))], (),
                     [Resource("crane", "타워크레인", "대", 3)])
    sid = store(session, two_crane, [crane(1), finish_by("2027-03-08")])
    o = await shorten(replace(ctx, schedule_id=sid), FailingLlm(), use_llm)
    option_b = next(x for x in o["options"] if x["key"] == "B")
    c = get(session, option_b["scenario_id"]).conditions_json
    caps = [d for d in c if d["id"] == "in.resource_cap.crane"]
    assert len(caps) == 1 and caps[0]["params"]["capacity"] == 2 and caps[0]["source"] == "단축안"
