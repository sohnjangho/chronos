"""하네스 낱말(Task 64): 꼴, 판정 코드·문 차례 이름, 범위의 현장 짝·현장 고르기, 값 검사, 도구 정의 읽기 전용."""

import json
from dataclasses import FrozenInstanceError, fields
from typing import get_args

import pytest

from app.outreach.harness.types import (
    EVENT_RULES,
    GATE_RULES,
    SHARED_TOOLS,
    VOICE_ONLY_TOOLS,
    Actor,
    Caller,
    CallerClass,
    Candidate,
    Delivered,
    Medium,
    Outcome,
    OutcomeCode,
    Ref,
    Scope,
    ToolDef,
)

# 계획 머리(plan-head.md) 「이름표」에서 그대로 옮김 — 판정 코드(Outcome.code)
PLAN_OUTCOME_CODES = (
    "accepted | queued | scheduled | blocked_test | blocked_hours | blocked_number | do_not_contact | limit_daily | "
    "limit_person | needs_approval | duplicate | held_for_review | not_ready | not_sendable"
)
# 「이름표」의 도구(음성·글 공통 10개)와 통화에만 있는 것
PLAN_SHARED_TOOLS = ("find_contact", "propose_contact", "schedule_fact", "my_requests", "record_answer", "take_message",
                     "report_from_contact", "schedule_callback", "mark_do_not_contact", "handoff_to_human")

# 일정 A(협력사 21, 철근)·B(협력사 22, 전기)에 같은 사람(연락처 11·12)이 있다
A, B = 101, 202
IN_A, IN_B = Candidate(A, 11, 21), Candidate(B, 12, 22)


def test_words_have_the_plan_shapes():
    assert get_args(Medium) == ("sms", "call")
    assert get_args(CallerClass) == (
        "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked",
        "outside_test", "outbound",
    )
    shapes = {
        Actor: ["kind", "user_id", "name", "role"],
        Outcome: ["code", "message", "rule", "scheduled_at"],
        Candidate: ["schedule_id", "contact_id", "company_id"],
        Caller: ["caller_class", "candidates", "user_id"],
        Scope: ["caller_class", "schedule_ids", "candidates", "personal", "granted", "site_required"],
        Ref: ["kind", "row_id"],
        Delivered: ["state", "provider_id", "fail_code", "fail_text"],
        ToolDef: ["name", "description", "parameters"],
    }
    for cls, names in shapes.items():
        assert [f.name for f in fields(cls)] == names, cls.__name__
    assert Outcome("accepted", "보냈습니다") == Outcome("accepted", "보냈습니다", None, None)
    assert Delivered("sent") == Delivered("sent", None, None, None)
    scope = Scope("contact", (A,), (IN_A,), True, "trade")
    with pytest.raises(FrozenInstanceError):
        scope.granted = "all"  # 범위는 만든 뒤 바꿀 수 없다
    assert hash(scope) == hash(Scope("contact", [A], [IN_A], True, "trade"))


def test_outcome_codes_equal_the_plan_list():
    # 이름표 14개 + unsure(보내기 요청은 나갔는데 결과를 모름 — 「보냈는지 확인 필요」, 제공사 리뷰 11-23 더함)
    assert set(get_args(OutcomeCode)) == {code.strip() for code in PLAN_OUTCOME_CODES.split("|")} | {"unsure"}
    assert len(get_args(OutcomeCode)) == 15


def test_unsure_delivery_is_distinguishable_from_failed():
    sent = Delivered("sent", provider_id="p-1")
    failed = Delivered("failed", fail_code="bad_sender", fail_text="발신번호가 등록돼 있지 않습니다")
    unsure = Delivered("unsure", fail_code="timeout", fail_text="결과를 알 수 없습니다")
    assert (sent.state, failed.state, unsure.state) == ("sent", "failed", "unsure")
    assert sent.ok and not failed.ok and not unsure.ok  # ok 는 「보냈음이 확실함」일 때만
    assert unsure != failed  # 실패로 납작해지지 않는다(다시 보내면 두 번 감)
    assert Outcome("unsure", "보냈는지 확인 필요").code == "unsure"
    with pytest.raises(ValueError):
        Delivered("maybe")
    with pytest.raises(ValueError):
        Delivered(True)  # 옛 꼴(ok: bool)은 받지 않는다


def test_outcome_checks_code_and_rule():
    assert Outcome("blocked_hours", "근무시간 밖", rule=3).rule == 3
    with pytest.raises(ValueError):
        Outcome("sent", "없는 판정 코드")
    with pytest.raises(ValueError):
        Outcome("duplicate", "없는 차례", rule=9)


def test_gate_rules_follow_the_design_order():
    # 설계 규칙 1: 시험 모드 → 차단·수신 거부 → 근무시간 → 상한 → 권한 → 중복, 그리고 채널 고르기(0 은 앞 확인)
    assert list(GATE_RULES) == list(range(8))
    assert [GATE_RULES[n] for n in range(1, 8)] == [
        "test_mode", "blocked_or_dnc", "working_hours", "limits", "permission", "duplicate", "channel_choice",
    ]
    assert GATE_RULES[0] == "ready"
    assert not set(GATE_RULES.values()) & EVENT_RULES  # 이름이 겹치지 않는다


def test_event_rules_cover_the_names_later_tasks_record():
    # Task 65·66·67·68·71·84·88·95 의 글에 나오는 사건 이름
    assert {
        "reply_within_grace", "kakao_not_ready", "delivery", "no_answer_retry", "admit", "scope_denied",
        "unsupported_date", "out_of_scope_said", "money_said", "disclosed_to_unknown", "reply_failed",
        "held_for_review", "recheck_before_dial", "silence", "time_limit", "server_restart",
    } <= EVENT_RULES


def test_tool_names_are_the_plan_list():
    assert SHARED_TOOLS == PLAN_SHARED_TOOLS
    assert VOICE_ONLY_TOOLS == ("end_call", "confirm_person")


def test_pinned_scope_keeps_only_that_site_pairing():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade", site_required=True)
    at_a = multi.pinned(A)
    assert at_a.schedule_ids == (A,)
    assert at_a.company_ids == (21,) and at_a.contact_ids == (11,)
    assert at_a.facts == "trade" and at_a.site_required is False
    assert multi.company_ids == (21, 22)  # 고르기 전에는 두 짝이 다 있지만
    assert multi.facts == "none"  # 사실은 하나도 말하지 않는다


def test_unpinned_multi_site_scope_has_no_facts():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "all", site_required=True)
    assert multi.facts == "none"
    assert multi.granted == "all"  # 고른 뒤에 줄 수준은 남아 있다
    assert multi.pinned(B).facts == "all"


def test_pinning_outside_the_candidates_raises():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade", site_required=True)
    with pytest.raises(ValueError):
        multi.pinned(303)
    with pytest.raises(ValueError):
        multi.pinned(A).pinned(B)  # 굳힌 뒤에는 다른 현장으로 넓힐 수 없다


def test_internal_scope_pins_to_a_schedule_without_pairs():
    internal = Scope("internal", (A, B), (), False, "all")
    assert internal.pinned(B).schedule_ids == (B,) and internal.pinned(B).contact_ids == ()


def test_scope_and_caller_coerce_and_validate():
    scope = Scope("contact", [A], [IN_A], True, "trade")
    assert scope.schedule_ids == (A,) and scope.candidates == (IN_A,)
    caller = Caller("contact", [IN_A], None)
    assert caller.candidates == (IN_A,)
    bad_scopes = [
        {"caller_class": "friend"},  # 등급표 밖
        {"granted": "everything"},  # 사실 수준 밖
        {"schedule_ids": (B,)},  # 짝의 일정이 범위에 없음
        {"schedule_ids": ("101",)},  # 정수가 아님
        {"candidates": ((A, 11, 21),)},  # Candidate 가 아님
        {"personal": "yes"},
    ]
    base = {"caller_class": "contact", "schedule_ids": (A,), "candidates": (IN_A,), "personal": True, "granted": "trade"}
    for bad in bad_scopes:
        with pytest.raises(ValueError):
            Scope(**{**base, **bad})
    with pytest.raises(ValueError):
        Caller("friend", (), None)
    with pytest.raises(ValueError):
        Caller("contact", ((A, 11, 21),), None)
    with pytest.raises(ValueError):
        Candidate(A, "11", 21)


def test_ref_checks_its_kind():
    with pytest.raises(ValueError, match="message"):
        Ref("letter", 1)
    with pytest.raises(ValueError):
        Ref("call", "7")


def test_tool_parameters_are_read_only():
    source = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    tool = ToolDef("find_contact", "주소록에서 찾기", source)
    source["properties"]["query"]["type"] = "integer"  # 넘긴 쪽이 나중에 고쳐도
    assert tool.parameters["properties"]["query"]["type"] == "string"
    with pytest.raises(TypeError):
        tool.parameters["type"] = "array"
    with pytest.raises(TypeError):
        tool.parameters["properties"]["query"]["type"] = "integer"
    schema = tool.json_schema()  # 세션·SDK 에 넘길 때는 새 dict
    assert schema == {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    schema["required"].append("x")
    assert tool.json_schema()["required"] == ["query"]
    assert json.loads(json.dumps(schema))["type"] == "object"
