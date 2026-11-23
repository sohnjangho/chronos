"""도구 묶음의 등급표와 도구 정의(Task 67) — 어느 등급이 어느 도구를 받는가, 모델이 보는 인자 꼴."""

import json
from typing import get_args

import pytest

from app.outreach.harness import toolsets
from app.outreach.harness.toolsets import ALL, SHARED, VOICE_ONLY, for_class, tool_defs
from app.outreach.harness.types import (
    SHARED_TOOLS,
    VOICE_ONLY_TOOLS,
    CallerClass,
    ToolDef,
)

SESSION_CLASSES = ["outbound", "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld"]
EXPECTED = {
    "outbound": set(SHARED),
    "contact": set(SHARED), "contact_multi": set(SHARED), "shared": set(SHARED),
    "internal": {"find_contact", "schedule_fact", "take_message", "handoff_to_human"},
    "do_not_contact": {"take_message"},
    "unknown": {"take_message", "propose_contact", "handoff_to_human"},
    "withheld": {"take_message", "propose_contact", "handoff_to_human"},
}


def test_names_are_the_harness_vocabulary():
    assert SHARED == SHARED_TOOLS and VOICE_ONLY == VOICE_ONLY_TOOLS == ("end_call", "confirm_person")
    assert ALL == SHARED + VOICE_ONLY and len(set(ALL)) == 12


@pytest.mark.parametrize("cls", SESSION_CLASSES)
@pytest.mark.parametrize("medium", ["sms", "call"])
def test_toolset_per_class_is_same_for_both_media_except_voice_only(cls, medium):
    assert for_class(cls, "call") - for_class(cls, "sms") <= set(VOICE_ONLY)
    assert for_class(cls, medium) & set(SHARED) == EXPECTED[cls]
    assert for_class(cls, "sms") == EXPECTED[cls]


@pytest.mark.parametrize("cls", SESSION_CLASSES)
def test_every_call_class_can_end_the_call_and_only_outbound_confirms_the_person(cls):
    voice = for_class(cls, "call") - set(SHARED)
    assert voice == ({"end_call", "confirm_person"} if cls == "outbound" else {"end_call"})


def test_unknown_class_has_no_schedule_tools():
    for cls in ("unknown", "withheld", "do_not_contact"):
        for medium in ("sms", "call"):
            assert not {"schedule_fact", "my_requests", "find_contact"} & for_class(cls, medium)


def test_no_toolset_for_rejected_classes():
    for cls in ("blocked", "outside_test"):
        for medium in ("sms", "call"):
            assert for_class(cls, medium) == frozenset()


def test_every_class_of_the_table_is_decided():
    assert set(EXPECTED) | {"blocked", "outside_test"} == set(get_args(CallerClass))


@pytest.mark.parametrize("cls, medium", [("stranger", "sms"), ("contact", "kakao"), (None, "sms"), ("contact", None)])
def test_unknown_class_or_medium_is_an_error_not_an_open_set(cls, medium):
    with pytest.raises(ValueError):
        for_class(cls, medium)


def test_toolsets_are_read_only():
    assert isinstance(for_class("contact", "sms"), frozenset)
    with pytest.raises(TypeError):
        toolsets.ARGS["find_contact"] = None


def test_tool_defs_follow_the_table_order_and_are_frozen():
    defs = tool_defs(frozenset(ALL))
    assert [d.name for d in defs] == list(ALL)
    assert all(isinstance(d, ToolDef) and d.description.strip() for d in defs)
    assert [d.name for d in tool_defs({"take_message", "find_contact"})] == ["find_contact", "take_message"]
    with pytest.raises(TypeError):
        defs[0].parameters["properties"]["extra"] = {}
    with pytest.raises(ValueError):
        tool_defs({"find_contact", "change_schedule"})


def test_tool_arguments_have_no_id_or_scope_field():
    """일정·연락처·협력사는 범위에서만 온다 — 인자에 그 칸이 없고, 모르는 칸은 받지 않는다."""
    for definition in tool_defs(frozenset(ALL)):
        schema = definition.json_schema()
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        fields = set(schema["properties"])
        assert not {f for f in fields if f.endswith(("_id", "_ids")) or f in ("schedule", "company", "contact")}
        assert set(schema.get("required", ())) <= fields
        json.dumps(schema)  # 음성·글 세션에 그대로 넘길 수 있다


def test_only_propose_contact_takes_a_number_and_no_tool_takes_two():
    takes = {d.name for d in tool_defs(frozenset(ALL)) if "phone" in d.json_schema()["properties"]}
    assert takes == {"propose_contact"}


def test_argument_shapes_of_the_table():
    props = {d.name: d.json_schema() for d in tool_defs(frozenset(ALL))}
    assert set(props["find_contact"]["properties"]) == {"query", "site", "redirect"}
    assert set(props["propose_contact"]["properties"]) == {"name", "role_title", "phone"}
    assert set(props["schedule_fact"]["properties"]) == {"activity", "site"}
    assert set(props["my_requests"]["properties"]) == {"site"}
    assert set(props["record_answer"]["properties"]) == {"question", "answer", "quote"}
    assert set(props["take_message"]["properties"]) == {"text", "claimed_name"}
    assert set(props["report_from_contact"]["properties"]) == {"kind", "text", "quote", "site"}
    assert props["report_from_contact"]["properties"]["kind"]["enum"] == ["delay", "problem", "change_request", "other"]
    assert set(props["schedule_callback"]["properties"]) == {"day_offset", "hour", "minute"}
    assert props["schedule_callback"]["properties"]["day_offset"]["maximum"] == 14
    assert set(props["mark_do_not_contact"]["properties"]) == {"reason"}
    assert props["handoff_to_human"]["properties"]["reason"]["enum"] == [
        "asked_for_person", "out_of_scope", "schedule_change", "emergency", "other"]
    assert props["end_call"]["properties"]["reason"]["enum"] == [
        "done", "wrong_person", "voicemail", "wrong_number", "busy_callback", "do_not_contact", "silence", "time_limit",
        "handoff", "other"]
    assert set(props["confirm_person"]["properties"]) == {"is_person"}


def test_descriptions_have_no_number_or_class_name():
    for definition in tool_defs(frozenset(ALL)):
        text = definition.description + json.dumps(definition.json_schema(), ensure_ascii=False)
        assert not any(cls in text for cls in ("contact_multi", "outside_test", "withheld"))
        assert not any(ch.isdigit() for ch in definition.description)
