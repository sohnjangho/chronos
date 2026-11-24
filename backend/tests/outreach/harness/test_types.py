"""하네스 낱말(Task 64): 꼴, 판정 코드·사건 이름 상수, 범위의 현장 짝과 「현장을 고르기 전에는 닫힘」, 값 검사,
도구 정의 읽기 전용, 통로 결과 셋 갈래."""

import dataclasses
import json
from dataclasses import FrozenInstanceError, fields
from typing import get_args

import pytest

from app.outreach.harness.types import (
    ADMIT_REASONS,
    CALL_RESULTS,
    CHANNELS,
    DELIVERY_UPDATES,
    DELIVERY_VERDICT,
    EVENT_GROUP_KEYS,
    EVENT_GROUPS,
    EVENT_RULES,
    FIXED_DETAILS,
    GATE_NOTES,
    GATE_RULES,
    GRANT_CEILING,
    REVIEW_FLAGS,
    SHARED_TOOLS,
    TOOL_REFUSALS,
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
ALL_CLASSES = get_args(CallerClass)


def test_words_have_the_plan_shapes():
    assert get_args(Medium) == ("sms", "call")
    assert ALL_CLASSES == (
        "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked",
        "outside_test", "outbound",
    )
    shapes = {
        Actor: ["kind", "user_id", "name", "role"],
        Outcome: ["code", "message", "rule", "scheduled_at"],
        Candidate: ["schedule_id", "contact_id", "company_id"],
        Caller: ["caller_class", "candidates", "user_id"],
        Scope: ["caller_class", "schedule_ids", "candidates", "grant_personal", "grant_facts", "manager"],  # manager 11-24
        Ref: ["kind", "row_id"],
        Delivered: ["state", "provider_id", "fail_code", "fail_text", "shape"],  # shape: 제공사 거절의 거른 모양(문이 꼴을 다시 본다)
        ToolDef: ["name", "description", "parameters"],
    }
    for cls, names in shapes.items():
        assert [f.name for f in fields(cls)] == names, cls.__name__
    assert Outcome("accepted", "보냈습니다") == Outcome("accepted", "보냈습니다", None, None)
    assert Delivered("sent") == Delivered("sent", None, None, None)
    scope = Scope("contact", (A,), (IN_A,), True, "trade")
    with pytest.raises(FrozenInstanceError):
        scope.grant_facts = "all"  # 범위는 만든 뒤 바꿀 수 없다
    assert hash(scope) == hash(Scope("contact", [A], [IN_A], True, "trade"))


# ── 판정 코드·사건 이름 ──────────────────────────────────────────────


def test_outcome_codes_equal_the_plan_list():
    # 이름표 14개 + unsure(보내기 요청은 나갔는데 결과를 모름 — 「보냈는지 확인 필요」, 제공사 리뷰 11-23 더함)
    # + failed(문은 지나갔는데 통로가 보내지 못함 — 「보내기를 거절함」인 not_sendable 과 가른다, Task 65 더함)
    assert set(get_args(OutcomeCode)) == {code.strip() for code in PLAN_OUTCOME_CODES.split("|")} | {"unsure", "failed"}
    assert len(get_args(OutcomeCode)) == 16


def test_outcome_checks_code_and_rule():
    assert Outcome("blocked_hours", "근무시간 밖", rule=3).rule == 3
    with pytest.raises(ValueError):
        Outcome("sent", "없는 판정 코드")
    with pytest.raises(ValueError):
        Outcome("duplicate", "없는 차례", rule=9)


def test_gate_rules_follow_the_design_order():
    # 설계 규칙 1: 시험 모드 → 차단·수신 거부 → 근무시간 → 상한 → 권한 → 중복, 그리고 채널 고르기(0 은 앞 확인)
    assert list(GATE_RULES) == list(range(8))
    assert [GATE_RULES[n] for n in range(8)] == [
        "precheck", "test_mode", "blocked_or_dnc", "working_hours", "limits", "permission", "duplicate", "channel_choice",
    ]
    assert not set(GATE_RULES.values()) & EVENT_RULES  # 이름이 겹치지 않는다


def test_constant_maps_are_read_only():
    for mapping in (GATE_RULES, GRANT_CEILING, DELIVERY_VERDICT, FIXED_DETAILS):
        with pytest.raises(TypeError):
            mapping["x"] = "y"
    for name_set in (EVENT_RULES, GATE_NOTES, TOOL_REFUSALS, REVIEW_FLAGS, ADMIT_REASONS, CALL_RESULTS, DELIVERY_UPDATES):
        assert isinstance(name_set, frozenset)
    assert all(isinstance(codes, frozenset) for codes in FIXED_DETAILS.values())


def test_event_vocabulary_is_complete():
    assert GATE_NOTES == {"reply_within_grace", "kakao_not_ready"}
    assert TOOL_REFUSALS == {"tool:unknown", "tool_not_allowed", "tool_bad_args", "scope_denied"}
    assert REVIEW_FLAGS == {"unsupported_date", "unsupported_answer", "out_of_scope_said", "money_said",
                            "disclosed_to_unknown"}
    assert EVENT_RULES == GATE_NOTES | REVIEW_FLAGS | (TOOL_REFUSALS - {"tool:unknown"}) | {
        "delivery", "delivery_update", "no_answer_retry", "admission", "site_pinned", "reply_failed", "held_for_review",
        "recheck_before_dial", "silence", "time_limit", "call_result", "hangup_by_person", "server_restart",
    }
    assert DELIVERY_UPDATES == {"delivered", "failed", "gave_up"}
    assert CALL_RESULTS == {"no_answer", "busy", "failed", "backend_error"}
    assert dict(DELIVERY_VERDICT) == {"sent": "allowed", "failed": "blocked", "unsure": "noted"}
    assert dict(FIXED_DETAILS) == {"channel_choice": frozenset(CHANNELS), "admission": ADMIT_REASONS,
                                   "call_result": CALL_RESULTS, "delivery_update": DELIVERY_UPDATES}
    assert CHANNELS == ("sms", "kakao", "call")


def test_admit_reasons_cover_the_door_table():
    # 계획 Task 66 의 받기 차례 표 아홉 줄(전화·문자 갈래 포함)
    assert ADMIT_REASONS == {
        "inbound_off",  # 1 받는 범위 「받지 않음」
        "outside_test", "blocked_number",  # 2 시험 모드 밖 · 차단 번호
        "burst_limit", "auto_reply_limit",  # 3 잦은 전화 · 자동 답 상한
        "stop_word",  # 4 수신 거부 말
        "machine_text", "media_attached",  # 5 기계 문자 · 사진
        "do_not_contact",  # 6 수신 거부 연락처
        "unknown_not_accepted", "unknown_accepted",  # 7 모르는 번호·번호 숨김(모드에 따라)
        "line_busy",  # 8 동시 통화 한도
        "known_caller",  # 9 내부·연락처 등급
    }


def test_event_rules_cover_the_names_later_tasks_record():
    assert {
        "reply_within_grace", "kakao_not_ready", "delivery", "no_answer_retry", "admission", "scope_denied",
        "unsupported_date", "out_of_scope_said", "money_said", "disclosed_to_unknown", "reply_failed",
        "held_for_review", "recheck_before_dial", "silence", "time_limit", "server_restart",
    } <= EVENT_RULES


def test_tool_names_are_the_plan_list():
    assert SHARED_TOOLS == PLAN_SHARED_TOOLS
    assert VOICE_ONLY_TOOLS == ("end_call", "confirm_person")


# ── 범위: 현장 짝과 「현장을 고르기 전에는 닫힘」 ─────────────────────


def test_pinned_scope_keeps_only_that_site_pairing():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade")
    at_a = multi.pinned(A)
    assert at_a.schedule_ids == (A,)
    assert at_a.company_ids == (21,) and at_a.contact_ids == (11,)
    assert at_a.facts == "trade" and at_a.personal is True and at_a.site_required is False
    assert multi.company_ids == (21, 22)  # 고르기 전에는 두 짝이 다 있지만
    assert multi.facts == "none"  # 사실은 하나도 말하지 않는다


def test_site_required_is_derived_not_an_argument():
    forgot = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade")  # 만드는 쪽이 아무것도 적지 않아도
    assert forgot.site_required is True and forgot.facts == "none"
    with pytest.raises(TypeError):
        Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade", site_required=False)  # 받는 칸이 없다
    assert Scope("contact", (A,), (IN_A,), True, "trade").site_required is False


def test_personal_is_closed_until_a_site_is_pinned():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade")
    assert multi.personal is False  # 두 프로젝트의 「내게 온 요청」이 섞이지 않게
    assert multi.grant_personal is True and multi.pinned(B).personal is True


def test_pinning_outside_the_candidates_raises():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade")
    with pytest.raises(ValueError):
        multi.pinned(303)
    with pytest.raises(ValueError):
        multi.pinned(A).pinned(B)  # 굳힌 뒤에는 다른 현장으로 넓힐 수 없다
    with pytest.raises(ValueError):
        multi.pinned(True)


def test_internal_scope_requires_a_site_when_it_sees_several():
    internal = Scope("internal", (A, B), (), False, "all")
    assert internal.site_required is True and internal.facts == "none"
    assert internal.pinned(B).schedule_ids == (B,) and internal.pinned(B).facts == "all"
    assert internal.pinned(B).contact_ids == ()
    assert Scope("internal", (A,), (), False, "all").facts == "all"


def test_replace_cannot_widen_a_scope():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "trade")
    with pytest.raises(TypeError):
        dataclasses.replace(multi, site_required=False)
    with pytest.raises(ValueError):
        dataclasses.replace(multi, grant_facts="all")  # 연락처 쪽의 끝은 trade(관리자 표시 없이는)
    shared = Scope("shared", (A,), (IN_A, Candidate(A, 13, 21)), False, "trade")
    with pytest.raises(ValueError):
        dataclasses.replace(shared, grant_personal=True)  # 대표번호는 개인 요청을 말하지 않는다
    unknown = Scope("unknown", (), (), False, "none")
    with pytest.raises(ValueError):
        dataclasses.replace(unknown, grant_facts="trade")
    with pytest.raises(ValueError):
        dataclasses.replace(multi, schedule_ids=(A, B, 303))  # 짝 없는 일정을 끼워 넣음


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_grant_never_exceeds_the_class_ceiling(cls):
    ceiling = GRANT_CEILING[cls]
    order = ("none", "trade", "all")
    pairs = () if cls == "internal" else (IN_A,)
    ids = (A,)
    for level in order:
        if order.index(level) <= order.index(ceiling):
            assert Scope(cls, ids, pairs, False, level).grant_facts == level
        else:
            with pytest.raises(ValueError):
                Scope(cls, ids, pairs, False, level)
    assert set(GRANT_CEILING) == set(ALL_CLASSES)


def test_class_ceilings():
    assert dict(GRANT_CEILING) == {
        "internal": "all", "contact": "trade", "contact_multi": "trade", "shared": "trade", "outbound": "trade",
        "do_not_contact": "none", "unknown": "none", "withheld": "none", "blocked": "none", "outside_test": "none",
    }
    for cls in ("internal", "shared", "do_not_contact", "unknown", "withheld", "blocked", "outside_test"):
        with pytest.raises(ValueError):
            Scope(cls, (A,), () if cls == "internal" else (IN_A,), True, "none")  # 개인 요청은 연락처 본인 등급만
    for cls in ("contact", "contact_multi", "outbound"):
        assert Scope(cls, (A,), (IN_A,), True, "none").grant_personal is True


def test_contact_side_schedules_must_equal_the_pair_schedules():
    with pytest.raises(ValueError):
        Scope("contact", (A, B), (IN_A,), True, "trade")  # B 에 짝이 없다 — 굳히면 협력사 없는 trade 가 된다
    with pytest.raises(ValueError):
        Scope("contact", (A,), (IN_A, IN_B), True, "trade")  # 짝의 일정이 범위에 없다
    with pytest.raises(ValueError):
        Scope("internal", (A,), (IN_A,), False, "all")  # 내부 계정은 연락처 짝이 없다
    with pytest.raises(ValueError):
        Scope("contact", (A, A), (IN_A,), True, "trade")  # 같은 일정 두 번
    assert Scope("unknown", (), (), False, "none").facts == "none"


def test_scope_and_caller_coerce_and_validate():
    scope = Scope("contact", [A], [IN_A], True, "trade")
    assert scope.schedule_ids == (A,) and scope.candidates == (IN_A,)
    caller = Caller("contact", [IN_A], None)
    assert caller.candidates == (IN_A,)
    base = {"caller_class": "contact", "schedule_ids": (A,), "candidates": (IN_A,), "grant_personal": True,
            "grant_facts": "trade"}
    bad_scopes = [
        {"caller_class": "friend"},  # 등급표 밖
        {"grant_facts": "everything"},  # 사실 수준 밖
        {"schedule_ids": ("101",)},  # 정수가 아님
        {"candidates": ((A, 11, 21),)},  # Candidate 가 아님
        {"grant_personal": "yes"},
    ]
    for bad in bad_scopes:
        with pytest.raises(ValueError):
            Scope(**{**base, **bad})
    with pytest.raises(ValueError):
        Caller("friend", (), None)
    with pytest.raises(ValueError):
        Caller("contact", ((A, 11, 21),), None)
    with pytest.raises(ValueError):
        Candidate(A, "11", 21)


# ── 그 밖의 낱말 ─────────────────────────────────────────────────────


def test_ref_checks_its_kind():
    with pytest.raises(ValueError, match="message"):
        Ref("letter", 1)
    with pytest.raises(ValueError):
        Ref("call", "7")


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


# ── 범위의 모양: 공유 번호·같은 일정 두 사람·빈 범위 ─────────────────────


def test_shared_number_across_two_companies_gets_nothing():
    two_companies = (Candidate(A, 11, 21), Candidate(A, 13, 23))  # 한 일정에서 한 번호를 두 협력사 사람이 씀
    with pytest.raises(ValueError):
        Scope("shared", (A,), two_companies, False, "trade")  # 어느 협력사의 공종도 들을 수 없다
    nothing = Scope("shared", (A,), two_companies, False, "none")
    assert nothing.company_ids == () and nothing.facts == "none"
    one_company = Scope("shared", (A,), (Candidate(A, 11, 21), Candidate(A, 13, 21)), False, "trade")
    assert one_company.company_ids == (21,) and one_company.facts == "trade"
    across_sites = Scope("shared", (A, B), (Candidate(A, 11, 21), Candidate(A, 13, 21), Candidate(B, 12, 22)),
                         False, "trade")  # 협력사 id 는 일정마다 따로 — 일정마다 한 협력사면 된다
    assert across_sites.pinned(B).company_ids == (22,)


@pytest.mark.parametrize("cls", ["contact", "contact_multi", "outbound"])
def test_one_person_classes_have_one_pair_per_schedule(cls):
    with pytest.raises(ValueError):
        Scope(cls, (A,), (Candidate(A, 11, 21), Candidate(A, 13, 21)), True, "trade")  # 같은 일정에 둘이면 shared


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_empty_scope_only_for_classes_that_see_nothing(cls):
    if GRANT_CEILING[cls] == "none":
        empty = Scope(cls, (), (), False, "none")
        assert empty.facts == "none" and empty.contact_ids == () and empty.company_ids == ()
    else:
        with pytest.raises(ValueError):  # 빈 범위는 「아무것도 안 보임」이지 「거르지 않음」이 아니다
            Scope(cls, (), (), False, "none")


def test_event_groups_are_read_only_and_known():
    with pytest.raises(TypeError):
        EVENT_GROUPS["x"] = "tool"
    assert set(EVENT_GROUPS.values()) <= set(EVENT_GROUP_KEYS)
    assert EVENT_GROUPS["test_mode"] == "gate_decision" and EVENT_GROUPS["tool:find_contact"] == "tool"
    assert EVENT_GROUPS["kakao_not_ready"] == "gate_note" and EVENT_GROUPS["scope_denied"] == "tool"
    assert EVENT_GROUPS["delivery_update"] == "channel_result" and EVENT_GROUPS["server_restart"] == "recovery"


# ── 관리자 등급 연락처(11-24): manager 표시가 있을 때만 한 사람 등급의 끝이 all ──────────────────


@pytest.mark.parametrize("cls", ["contact", "contact_multi", "outbound"])
def test_manager_flag_is_the_only_way_to_all_for_a_contact(cls):
    with pytest.raises(ValueError):
        Scope(cls, (A,), (IN_A,), True, "all")
    manager = Scope(cls, (A,), (IN_A,), True, "all", manager=True)
    assert manager.facts == "all" and manager.manager
    plain = Scope(cls, (A,), (IN_A,), True, "trade")
    with pytest.raises(ValueError):
        dataclasses.replace(plain, grant_facts="all")
    assert dataclasses.replace(plain, manager=True, grant_facts="all").facts == "all"


@pytest.mark.parametrize("cls", ["internal", "shared", "do_not_contact", "unknown", "withheld", "blocked", "outside_test"])
def test_manager_flag_is_refused_on_other_classes(cls):
    pairs = () if cls == "internal" or GRANT_CEILING[cls] == "none" else (IN_A,)
    ids = (A,) if pairs or cls == "internal" else ()
    with pytest.raises(ValueError):
        Scope(cls, ids, pairs, False, "none", manager=True)


def test_manager_flag_survives_pinning_and_is_a_bool():
    multi = Scope("contact_multi", (A, B), (IN_A, IN_B), True, "all", manager=True)
    assert multi.facts == "none" and multi.pinned(B).facts == "all" and multi.pinned(B).manager
    with pytest.raises(ValueError):
        Scope("contact", (A,), (IN_A,), True, "all", manager=1)
