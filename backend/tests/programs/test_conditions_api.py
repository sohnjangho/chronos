"""조건·규칙 API (Task 18): 겹별 보기·미리 보기(저장 안 함)·확정(승인 판단)·에이전트에게 맞추게 하기.

시험 일정: 2027-03-01(월) 시작, 주 5일. A 40일 → B·C 30일(둘 다 타워크레인) → D 20일.
크레인 1대면 B 뒤에 C 를 맞춰 준공 2027-08-13, 2대면 B·C 를 같이 해 준공 2027-07-02.
"""


import pytest

from app.core.model import Relation, Resource
from app.harness.conditions import Condition
from app.store.tables import ScheduleVersion
from tests.schedules import make, store, task

CRANE = Resource("crane", "타워크레인", "대", 1)


def cond(cid, layer, kind, params, text, source, **k) -> dict:
    return Condition(cid, layer, kind, params, text, source, **k).to_dict()


CONDITIONS = [
    cond("dom.curing", "domain", "text_only", {}, "타설 뒤 7일 이상 습윤 양생", "분야 규칙"),
    cond("my.max", "mine", "max_duration", {"days": 60}, "한 액티비티는 60일 이하", "내 규칙"),
    cond("in.crane", "input", "resource_cap", {"resource_id": "crane", "capacity": 1}, "타워크레인 1대", "프롬프트"),
    cond("in.finish_by", "input", "finish_by", {"date": "2027-12-31"}, "준공 2027.12.31 이전", "프롬프트"),
    cond("in.safety", "input", "text_only", {}, "안전 우선으로 여유 있게", "프롬프트"),
]


def office():
    return make(
        [
            task("A", 40, name="터파기"),
            task("B", 30, name="골조 1구역", resources=("crane",), tags=("골조",)),
            task("C", 30, name="골조 2구역", resources=("crane",), tags=("골조",)),
            task("D", 20, name="마감"),
        ],
        [Relation("A", "B"), Relation("A", "C"), Relation("B", "D"), Relation("C", "D")],
        [CRANE],
    )


@pytest.fixture
def sid(session) -> int:
    """이 파일의 시험 일정(버전 1, 조건 CONDITIONS). 전역 sid 를 덮는다."""
    return store(session, office(), conditions=list(CONDITIONS))


@pytest.fixture
def sid_crane(sid) -> int:
    return sid


@pytest.fixture
def sid_v2(client, admin, sid) -> int:
    r = client.patch(f"/api/schedules/{sid}/activities/D", json={"od": 21, "base_version": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["version"] == 2
    return sid


CRANE_TWO = [{"id": "in.crane", "params": {"resource_id": "crane", "capacity": 2}}]


def _url(sid, action="") -> str:
    return f"/api/schedules/{sid}/conditions" + (f"/{action}" if action else "")


def _post(client, headers, sid, action, changes, base_version=1):
    return client.post(_url(sid, action), json={"base_version": base_version, "changes": changes}, headers=headers)


def _rows(j) -> dict[str, dict]:
    return {c["id"]: c for layer in j["layers"].values() for c in layer}


# ── 지시서 시험 ────────────────────────────────────────────────────


def test_layers_and_states(client, admin, sid):
    j = client.get(f"/api/schedules/{sid}/conditions", headers=admin).json()
    assert j["layers"]["base"][0]["editable"] is False and any(c["state"] == "uncheckable" for c in j["layers"]["input"])


def test_preview_crane_two_pulls_finish_and_does_not_save(client, admin, sid_crane):
    r = client.post(f"/api/schedules/{sid_crane}/conditions/preview", json={"base_version": 1, "changes": [{"id": "in.crane", "params": {"resource_id": "crane", "capacity": 2}}]}, headers=admin).json()
    assert r["after"]["finish"] < r["before"]["finish"] and r["moved"] and client.get(f"/api/schedules/{sid_crane}", headers=admin).json()["version"] == 1


def test_preview_infeasible_deadline(client, admin, sid):
    r = client.post(f"/api/schedules/{sid}/conditions/preview", json={"base_version": 1, "changes": [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}]}, headers=admin).json()
    assert r["feasible"] is False and r["violations"][0]["condition_id"] == "in.finish_by"


def test_commit_condition_change_goes_to_approval(client, admin, sid_crane):
    r = client.post(f"/api/schedules/{sid_crane}/conditions/commit", json={"base_version": 1, "changes": [{"id": "in.crane", "params": {"resource_id": "crane", "capacity": 2}}]}, headers=admin).json()
    assert r["applied"] is False and r["approval_id"]


def test_base_layer_cannot_be_changed(client, admin, sid):
    assert client.post(f"/api/schedules/{sid}/conditions/preview", json={"base_version": 1, "changes": [{"id": "base.no_cycle", "enabled": False}]}, headers=admin).status_code == 422


def test_user_cannot_toggle_domain_rule(client, user, sid):
    assert client.post(f"/api/schedules/{sid}/conditions/commit", json={"base_version": 1, "changes": [{"id": "dom.curing", "enabled": False}]}, headers=user).status_code == 403


def test_stale_base_version_conflicts(client, admin, sid_v2):
    assert client.post(f"/api/schedules/{sid_v2}/conditions/preview", json={"base_version": 1, "changes": []}, headers=admin).status_code == 409


# ── GET: 겹·상태·편집 가능 여부 ─────────────────────────────────────


def test_the_four_layers_in_order_with_base_rules_first(client, admin, sid):
    j = client.get(_url(sid), headers=admin).json()
    assert (j["schedule_id"], j["name"], j["version"]) == (sid, "시험 일정", 1)
    assert [c["id"] for c in j["layers"]["base"]] == ["base.no_cycle", "base.no_dangling", "base.calendar", "base.valid"]
    assert [c["id"] for c in j["layers"]["domain"]] == ["dom.curing"]
    assert [c["id"] for c in j["layers"]["mine"]] == ["my.max"]
    assert [c["id"] for c in j["layers"]["input"]] == ["in.crane", "in.finish_by", "in.safety"]
    assert j["resources"] == [{"id": "crane", "name": "타워크레인", "unit": "대", "capacity": 1}]
    assert j["invalid"] == []


def test_condition_shape(client, admin, sid):
    crane = _rows(client.get(_url(sid), headers=admin).json())["in.crane"]
    assert crane == {
        "id": "in.crane", "layer": "input", "kind": "resource_cap", "params": {"resource_id": "crane", "capacity": 1},
        "text": "타워크레인 1대", "source": "프롬프트", "enabled": True, "editable": True, "state": "passed",
        "message": crane["message"], "overridden_by": None, "used_by": ["B", "C"], "evidence": [],
    }
    # 맞춤이 푼 겹침은 알림(통과)이다: 용량 1대로 B 뒤에 C 를 미뤘다
    assert crane["message"].startswith("맞추기 전 날짜로는 타워크레인 필요량이 용량(1대)을 넘는 날이")


def test_unchecked_conditions_are_never_counted_as_passed(client, admin, sid):
    j = client.get(_url(sid), headers=admin).json()
    rows = _rows(j)
    assert rows["in.safety"]["state"] == rows["dom.curing"]["state"] == "uncheckable"
    assert j["summary"] == {"passed": 7, "violated": 0, "uncheckable": 2}  # 기본 규칙 4 + 내 규칙 1 + 입력 2


@pytest.mark.parametrize(("who", "domain"), [("admin", "toggle"), ("user", False)])
def test_editable_by_layer_and_role(client, request, sid, who, domain):
    j = client.get(_url(sid), headers=request.getfixturevalue(who)).json()
    assert {c["editable"] for c in j["layers"]["base"]} == {False}
    assert [c["editable"] for c in j["layers"]["domain"]] == [domain]
    assert [c["editable"] for c in j["layers"]["mine"]] == [False]  # 내 규칙은 이 계획에서 읽기만
    assert {c["editable"] for c in j["layers"]["input"]} == {True}


def test_overridden_and_switched_off_conditions_are_off(client, admin, session):
    conditions = [
        cond("dom.crane", "domain", "resource_cap", {"resource_id": "crane", "capacity": 1}, "크레인 1대 기준", "분야 규칙"),
        cond("in.crane", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "타워크레인 2대", "프롬프트"),
        cond("in.gap", "input", "min_gap", {"after_tag": "골조", "days": 3}, "골조 뒤 3일", "질문지", enabled=False),
    ]
    sid = store(session, office(), conditions=conditions)
    rows = _rows(client.get(_url(sid), headers=admin).json())
    assert (rows["dom.crane"]["state"], rows["dom.crane"]["overridden_by"]) == ("off", "in.crane")
    assert "타워크레인 2대" in rows["dom.crane"]["message"]
    assert (rows["in.gap"]["state"], rows["in.gap"]["overridden_by"], rows["in.gap"]["used_by"]) == ("off", None, ["B", "C"])


def test_a_violated_condition_carries_its_message(client, admin, session):
    late = cond("in.finish_by", "input", "finish_by", {"date": "2027-08-06"}, "준공 기한", "질문지")
    sid = store(session, office(), conditions=[late])
    j = client.get(_url(sid), headers=admin).json()
    row = _rows(j)["in.finish_by"]
    assert (row["state"], row["message"]) == ("violated", "준공이 기한보다 5일 늦습니다.")
    assert j["summary"]["violated"] == 1


def test_unreadable_stored_conditions_are_listed_not_passed(client, admin, session):
    sid = store(session, office(), conditions=[{"id": "x1"}, CONDITIONS[2]])
    j = client.get(_url(sid), headers=admin).json()
    assert j["invalid"] == [{"condition_id": "x1", "message": "'kind' 칸이 없습니다."}]
    assert "x1" not in _rows(j)


def test_missing_schedule_and_login(client, admin, sid):
    assert client.get(_url(999), headers=admin).status_code == 404
    assert _post(client, admin, 999, "preview", []).status_code == 404
    assert client.get(_url(sid)).status_code == 401


# ── 미리 보기 ───────────────────────────────────────────────────────


def test_preview_shapes_the_whole_answer(client, admin, sid):
    r = _post(client, admin, sid, "preview", CRANE_TWO).json()
    assert r["feasible"] is True and r["violations"] == []
    assert r["before"] == {"finish": "2027-08-13", "critical_count": 2, "violated": 0}  # 맞춤이 C 를 고정해 C·D 만 크리티컬
    assert r["after"] == {"finish": "2027-07-02", "critical_count": 4, "violated": 0}
    assert r["moved"] == [
        {"activity_id": "C", "name": "골조 2구역", "before": {"start": "2027-06-07", "finish": "2027-07-16"},
         "after": {"start": "2027-04-26", "finish": "2027-06-04"}},
        {"activity_id": "D", "name": "마감", "before": {"start": "2027-07-19", "finish": "2027-08-13"},
         "after": {"start": "2027-06-07", "finish": "2027-07-02"}},
    ]
    # 미리 보기 상태의 조건 겹(같은 모양): 크레인은 2대, 알림 없이 통과
    crane = _rows(r["conditions"])["in.crane"]
    assert (crane["params"]["capacity"], crane["state"], crane["message"]) == (2, "passed", None)


def test_preview_view_is_the_previewed_schedule_with_plan_bars_at_the_previewed_dates(client, admin, sid):
    # Task 16d: Plan 은 바꾼 조건으로 계산한다. 실적이 없으면 Plan = 계산 날짜.
    view = _post(client, admin, sid, "preview", CRANE_TWO).json()["view"]
    c = next(a for a in view["activities"] if a["id"] == "C")
    assert (view["id"], view["version"], view["finish"], view["plan_finish"]) == (sid, 1, "2027-07-02", "2027-07-02")
    assert (c["es"], c["ef"], c["plan_start"], c["plan_finish"]) == ("2027-04-26", "2027-06-04", "2027-04-26", "2027-06-04")
    assert c["status"] == "on_plan"
    assert view["summary"]["critical_count"] == 4


def test_preview_saves_nothing(client, admin, sid):
    _post(client, admin, sid, "preview", CRANE_TWO)
    _post(client, admin, sid, "preview", [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}])
    assert len(client.get(f"/api/schedules/{sid}/versions", headers=admin).json()) == 1
    assert _rows(client.get(_url(sid), headers=admin).json())["in.crane"]["params"]["capacity"] == 1
    assert client.get("/api/approvals/count", headers=admin).json() == {"pending": 0}


def test_preview_infeasible_lists_every_violation_and_counts_them(client, admin, sid):
    r = _post(client, admin, sid, "preview", [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}]).json()
    assert r["violations"] == [{"condition_id": "in.finish_by", "message": "준공이 기한보다 32일 늦습니다.",
                                "activity_ids": ["C", "D"], "amount": 32}]
    assert (r["after"]["violated"], r["conditions"]["summary"]["violated"]) == (1, 1)
    assert _rows(r["conditions"])["in.finish_by"]["state"] == "violated"


def test_params_are_merged_into_the_current_ones(client, admin, sid):
    r = _post(client, admin, sid, "preview", [{"id": "in.crane", "params": {"capacity": 2}}]).json()
    assert _rows(r["conditions"])["in.crane"]["params"] == {"resource_id": "crane", "capacity": 2}
    assert r["after"]["finish"] == "2027-07-02"


def test_switching_an_input_off_and_adding_and_removing(client, admin, sid):
    added = cond("in.max", "input", "max_duration", {"days": 35}, "35일 이하", "조건 화면")
    changes = [{"id": "in.safety", "enabled": False}, {"add": added}, {"remove": "in.finish_by"}]
    r = _post(client, admin, sid, "preview", changes).json()
    rows = _rows(r["conditions"])
    assert rows["in.safety"]["state"] == "off" and "in.finish_by" not in rows
    assert [v["condition_id"] for v in r["violations"]] == ["in.max"]  # A 가 40일
    assert r["feasible"] is False


def test_admin_may_switch_a_domain_rule_off(client, admin, sid):
    r = _post(client, admin, sid, "preview", [{"id": "dom.curing", "enabled": False}])
    assert r.status_code == 200 and _rows(r.json()["conditions"])["dom.curing"]["state"] == "off"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "base.no_cycle", "enabled": False}, "기본 규칙은 바꿀 수 없습니다."),
        ({"id": "base.calendar", "params": {}}, "기본 규칙은 바꿀 수 없습니다."),
        ({"id": "nope", "enabled": False}, "없는 조건입니다: nope"),
        ({"id": "dom.curing", "params": {"x": 1}}, "분야 규칙은 켜고 끄기만 할 수 있습니다: dom.curing"),
        ({"id": "my.max", "enabled": False}, "내 규칙은 이 화면에서 바꿀 수 없습니다: my.max"),
        ({"id": "in.crane", "params": {"capacity": -1}}, "in.crane: 'capacity' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
        ({"id": "in.finish_by", "params": {"date": "2027-02-30"}}, "in.finish_by: 'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
        ({"add": {"id": "in.x", "layer": "domain", "kind": "text_only", "params": {}, "text": "t", "source": "s"}},
         "입력 조건만 더할 수 있습니다: in.x"),
        ({"add": {"id": "in.crane", "layer": "input", "kind": "text_only", "params": {}, "text": "t", "source": "s"}},
         "같은 id 의 조건이 이미 있습니다: in.crane"),
        ({"add": {"id": "in.y", "layer": "input", "kind": "max_duration", "params": {}, "text": "t", "source": "s"}},
         "in.y: 'days' 칸이 없습니다."),
        ({"remove": "dom.curing"}, "입력 조건만 뺄 수 있습니다: dom.curing"),
        ({"remove": "nope"}, "없는 조건입니다: nope"),
    ],
)
def test_changes_that_cannot_be_made_are_422(client, admin, sid, change, message):
    r = _post(client, admin, sid, "preview", [change])
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("invalid_change", message)


@pytest.mark.parametrize("change", [{"id": "in.crane"}, {"id": "in.crane", "enabled": "no"}, {"id": "a", "add": {}}, {"what": 1}])
def test_malformed_change_bodies_are_invalid_request(client, admin, sid, change):
    r = _post(client, admin, sid, "preview", [change])
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_user_cannot_preview_a_domain_toggle_either(client, user, sid):
    r = _post(client, user, sid, "preview", [{"id": "dom.curing", "enabled": False}])
    assert r.status_code == 403 and r.json()["message"] == "분야 규칙은 관리자만 켜고 끌 수 있습니다."


def test_a_change_that_leaves_no_workday_is_schedule_invalid(client, admin, sid):
    winter = cond("in.block", "input", "blocked_period", {"start_md": [1, 1], "end_md": [12, 31], "tag": "골조"}, "", "조건 화면")
    r = _post(client, admin, sid, "preview", [{"add": winter}])
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == (
        "schedule_invalid", "바꾼 조건으로는 일정을 계산할 수 없습니다: 일할 수 있는 날이 없는 달력입니다.")  # fix1 m2


@pytest.mark.parametrize("action", ["preview", "commit", "ask-agent"])
def test_every_action_checks_the_base_version(client, admin, sid_v2, action):
    r = _post(client, admin, sid_v2, action, CRANE_TWO)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and r.json()["detail"] == {"current": 2}


# ── 확정 ────────────────────────────────────────────────────────────


def test_commit_creates_a_pending_approval_with_the_task_11_summary(client, admin, sid):
    r = _post(client, admin, sid, "commit", CRANE_TWO).json()
    assert (r["applied"], r["version"]) == (False, None)
    detail = client.get(f"/api/approvals/{r['approval_id']}", headers=admin).json()
    assert (detail["kind"], detail["status"], detail["schedule_id"], detail["base_version"]) == ("change", "pending", sid, 1)
    assert detail["title"] == "조건 바꾸기 — 타워크레인: 1대 → 2대"
    assert "condition_changed" in detail["reasons"] and "finish_changed" in detail["reasons"]
    assert detail["summary"]["conditions_changed"] == [{"id": "in.crane", "name": "타워크레인", "before": "1대", "after": "2대"}]
    assert detail["summary"]["finish"] == {"before": "2027-08-13", "after": "2027-07-02", "delta_days": -42}
    assert [d["activity_id"] for d in detail["diff"]] == ["C", "D"]
    assert len(client.get(f"/api/schedules/{sid}/versions", headers=admin).json()) == 1  # 아직 반영 안 됨


def test_approving_the_commit_saves_the_new_conditions(client, admin, sid):
    approval_id = _post(client, admin, sid, "commit", CRANE_TWO).json()["approval_id"]
    decided = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=admin).json()
    assert (decided["status"], decided["version"]) == ("approved", 2)
    j = client.get(_url(sid), headers=admin).json()
    assert j["version"] == 2 and _rows(j)["in.crane"]["params"]["capacity"] == 2
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["finish"] == "2027-07-02"


def test_commit_is_applied_at_once_when_the_approval_mode_allows(client, admin, sid):
    assert client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin).status_code == 200
    r = _post(client, admin, sid, "commit", CRANE_TWO).json()
    assert (r["applied"], r["version"]) == (True, 2) and r["approval_id"]
    j = client.get(_url(sid), headers=admin).json()
    assert j["version"] == 2 and _rows(j)["in.crane"]["params"]["capacity"] == 2
    auto = client.get("/api/approvals?status=auto", headers=admin).json()["items"]
    assert [(a["id"], a["restore_to"], a["version"]) for a in auto] == [(r["approval_id"], 1, 2)]


def test_a_violating_commit_needs_approval_even_in_auto_mode(client, admin, sid):
    client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin)
    r = _post(client, admin, sid, "commit", [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}]).json()
    assert r["applied"] is False
    reasons = client.get(f"/api/approvals/{r['approval_id']}", headers=admin).json()["reasons"]
    assert {"condition_violated", "condition_changed"} <= set(reasons)


@pytest.mark.parametrize("changes", [[], [{"id": "in.crane", "enabled": True}], [{"id": "in.crane", "params": {"capacity": 1}}]])
def test_commit_without_an_effective_change_is_refused(client, admin, sid, changes):
    r = _post(client, admin, sid, "commit", changes)
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("no_change", "바뀌는 것이 없습니다.")
    assert client.get("/api/approvals/count", headers=admin).json() == {"pending": 0}


def test_admin_commits_a_domain_toggle_to_the_approvals(client, admin, sid):
    r = _post(client, admin, sid, "commit", [{"id": "dom.curing", "enabled": False}]).json()
    detail = client.get(f"/api/approvals/{r['approval_id']}", headers=admin).json()
    assert detail["reasons"] == ["condition_changed"]
    assert detail["title"] == "조건 바꾸기 — 타설 뒤 7일 이상 습윤 양생: 적용 안 함"


# ── 에이전트에게 맞추게 하기 ─────────────────────────────────────────


def test_ask_agent_creates_a_chat_for_the_caller_with_the_request_text(client, admin, user, sid):
    r = _post(client, admin, sid, "ask-agent", [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}])
    assert r.status_code == 200
    body = r.json()
    chat = client.get(f"/api/chat/sessions/{body['chat_session_id']}", headers=admin).json()
    assert (chat["title"], chat["schedule_id"], chat["messages"], chat["running"]) == ("조건 맞추기 — 시험 일정", sid, [], False)
    assert client.get(f"/api/chat/sessions/{body['chat_session_id']}", headers=user).status_code == 404
    assert body["text"] == (
        "'시험 일정' 일정의 조건을 아래처럼 바꾸려고 합니다. 이 조건에 맞게 일정을 고쳐 주세요.\n"
        "- 완료 기한 2027.06.30(in.finish_by): 2027-12-31 → 2027-06-30\n"  # fix1 I6: 값을 바꾸면 글을 다시 만든다
        "바꾼 조건으로 계산하면 준공 2027-08-13(그대로), 위반 1건입니다.\n"
        "- 준공이 기한보다 32일 늦습니다."
    )
    assert len(client.get(f"/api/schedules/{sid}/versions", headers=admin).json()) == 1


def test_ask_agent_without_changes_asks_to_fix_the_current_conditions(client, admin, session):
    late = cond("in.finish_by", "input", "finish_by", {"date": "2027-08-06"}, "준공 기한", "질문지")
    sid = store(session, office(), conditions=[late])
    text = _post(client, admin, sid, "ask-agent", []).json()["text"]
    assert text == "'시험 일정' 일정을 지금 조건에 맞게 고쳐 주세요.\n지금 준공 2027-08-13, 위반 1건입니다.\n- 준공이 기한보다 5일 늦습니다."


def test_ask_agent_validates_the_changes_before_creating_a_chat(client, user, sid):
    assert _post(client, user, sid, "ask-agent", [{"id": "dom.curing", "enabled": False}]).status_code == 403
    assert _post(client, user, sid, "ask-agent", [{"id": "nope", "enabled": False}]).status_code == 422
    assert client.get("/api/chat/sessions", headers=user).json() == []
    ok = _post(client, user, sid, "ask-agent", CRANE_TWO).json()
    assert [s["id"] for s in client.get("/api/chat/sessions", headers=user).json()] == [ok["chat_session_id"]]


# ── Fix round 1 ────────────────────────────────────────────────────


def _versions_of(client, headers, sid) -> list[dict]:
    return client.get(f"/api/schedules/{sid}/versions", headers=headers).json()


def test_i1_an_auto_applied_commit_is_recorded_as_the_user(client, admin, sid):
    client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin)
    assert _post(client, admin, sid, "commit", CRANE_TWO).json()["applied"] is True
    newest = _versions_of(client, admin, sid)[0]
    assert (newest["n"], newest["by_kind"], newest["by_name"]) == (2, "user", "관리자")


def test_i1_an_approved_commit_is_recorded_as_the_user(client, admin, user, sid):
    approval_id = _post(client, user, sid, "commit", CRANE_TWO).json()["approval_id"]
    client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=admin)
    newest = _versions_of(client, admin, sid)[0]
    assert (newest["n"], newest["by_kind"], newest["by_name"]) == (2, "user", "관리자")  # by_name 은 승인한 사람(Task 11)


def test_i2_a_preview_without_changes_is_the_schedule_view(client, admin, sid):
    got = _post(client, admin, sid, "preview", []).json()["view"]
    want = client.get(f"/api/schedules/{sid}", headers=admin).json()
    # 미리 보기 view 는 store 의 보기 자료 그대로다. 일정 API 는 그 가운데 ScheduleView 칸만 보인다(예: start_floor 는 안 보임).
    got["activities"] = [{k: a[k] for k in b} for a, b in zip(got["activities"], want["activities"], strict=True)]
    assert {k: got[k] for k in want} == want


def test_i3_the_agent_text_covers_input_changes_and_mentions_domain_changes(client, admin, sid):
    changes = [{"id": "dom.curing", "enabled": False}, *CRANE_TWO]
    text = _post(client, admin, sid, "ask-agent", changes).json()["text"]
    assert text == (
        "'시험 일정' 일정의 조건을 아래처럼 바꾸려고 합니다. 이 조건에 맞게 일정을 고쳐 주세요.\n"
        "- 타워크레인(in.crane): 1대 → 2대\n"
        "바꾼 조건으로 계산하면 준공 2027-08-13 → 2027-07-02, 위반 0건입니다.\n"
        "분야 규칙 변경은 [확정]으로 반영해 주세요."
    )


def test_i3_only_domain_changes_ask_to_fix_the_current_conditions(client, admin, sid):
    text = _post(client, admin, sid, "ask-agent", [{"id": "dom.curing", "enabled": False}]).json()["text"]
    assert text == ("'시험 일정' 일정을 지금 조건에 맞게 고쳐 주세요.\n지금 준공 2027-08-13, 위반 0건입니다.\n"
                    "분야 규칙 변경은 [확정]으로 반영해 주세요.")


def test_i6_a_changed_value_regenerates_the_condition_text(client, admin, sid):
    client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin)
    late = [{"id": "in.finish_by", "params": {"date": "2027-09-30"}}]
    assert _rows(_post(client, admin, sid, "preview", late).json()["conditions"])["in.finish_by"]["text"] == "완료 기한 2027.09.30"
    assert _post(client, admin, sid, "commit", [*late, *CRANE_TWO]).json()["applied"] is True
    rows = _rows(client.get(_url(sid), headers=admin).json())
    assert (rows["in.finish_by"]["text"], rows["in.crane"]["text"]) == ("완료 기한 2027.09.30", "타워크레인 2대")
    assert rows["in.safety"]["text"] == "안전 우선으로 여유 있게"  # 값이 없는 조건과 바꾸지 않은 조건은 글 그대로


def _broken(session, sid) -> None:
    """저장된 지금 버전의 조건만 고쳐 계산이 안 되게 한다(골조 꼬리표의 모든 날을 막음)."""
    block = cond("in.block", "input", "blocked_period", {"start_md": [1, 1], "end_md": [12, 31], "tag": "골조"}, "", "문서")
    row = session.get(ScheduleVersion, (sid, 1))
    row.conditions_json = [*row.conditions_json, block]
    session.commit()


def test_m2_a_fix_can_be_previewed_when_the_stored_version_does_not_compute(client, admin, session, sid):
    _broken(session, sid)
    r = _post(client, admin, sid, "preview", [{"remove": "in.block"}])
    assert r.status_code == 200
    j = r.json()
    assert j["before"] == {"finish": None, "critical_count": None, "violated": 1} and j["moved"] == []
    # Task 16d: 저장된 쪽 Plan 은 없지만(moved 없음) 바꾼 조건의 Plan 은 계산된다
    assert (j["after"]["finish"], j["feasible"], j["view"]["plan_finish"]) == ("2027-08-13", True, "2027-08-13")


def test_m2_commit_on_a_stored_version_that_does_not_compute_is_a_korean_422(client, admin, session, sid):
    _broken(session, sid)
    r = _post(client, admin, sid, "commit", [{"remove": "in.block"}])
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == (
        "schedule_invalid", "지금 저장된 일정을 계산할 수 없어 확정할 수 없습니다: 일할 수 있는 날이 없는 달력입니다.")


def test_m3_changing_the_value_of_an_overridden_condition_keeps_it_overridden(client, admin, session):
    early = cond("in.fin_a", "input", "finish_by", {"date": "2027-12-31"}, "준공 a", "문서", enabled=False,
                 overridden_by="in.fin_b")
    later = cond("in.fin_b", "input", "finish_by", {"date": "2027-11-30"}, "준공 b", "문서")
    sid = store(session, office(), conditions=[early, later])
    edit = {"id": "in.fin_a", "params": {"date": "2027-10-31"}}
    row = _rows(_post(client, admin, sid, "preview", [edit]).json()["conditions"])["in.fin_a"]
    assert (row["state"], row["overridden_by"]) == ("off", "in.fin_b")
    freed = _rows(_post(client, admin, sid, "preview", [edit, {"remove": "in.fin_b"}]).json()["conditions"])["in.fin_a"]
    assert (freed["state"], freed["params"]) == ("passed", {"date": "2027-10-31"})


def test_m6_ask_agent_reuses_the_callers_latest_session_for_the_schedule(client, admin, user, session, sid):
    first = _post(client, admin, sid, "ask-agent", CRANE_TWO).json()["chat_session_id"]
    assert _post(client, admin, sid, "ask-agent", []).json()["chat_session_id"] == first
    assert _post(client, user, sid, "ask-agent", []).json()["chat_session_id"] != first
    other = store(session, office(), conditions=list(CONDITIONS))
    assert _post(client, admin, other, "ask-agent", []).json()["chat_session_id"] != first
    assert [s["id"] for s in client.get("/api/chat/sessions", headers=admin).json()].count(first) == 1


# ── Task 16d → 16e: 미리 보기의 Plan 은 확정하면 될 Plan(바꾼 조건으로 계산한 지금 예측) ─────────────────


def _late_start(client, admin, sid) -> None:
    """버전 1(실적 없음)의 Plan 위에 A 를 실적으로 늦춘다(버전 2·3, Data Date 2027-03-29, A 진행 중 남은 30일).
    실적은 계획 변경이 아니라 Plan 은 버전 1 것 그대로이고 ES/EF 는 그보다 2주 늦다.
    지원하는 차례(조정 11-24): Data Date 를 먼저 정하고(버전 2) 실적을 넣는다(버전 3)."""
    body = {"data_date": "2027-03-29", "base_version": 1}
    assert client.patch(f"/api/schedules/{sid}", json=body, headers=admin).status_code == 200
    body = {"actual_start": "2027-03-01", "progress": 0.5, "rd": 30, "base_version": 2}
    assert client.patch(f"/api/schedules/{sid}/activities/A", json=body, headers=admin).status_code == 200


def test_16d_preview_moves_the_plan_with_the_changed_capacity(client, admin, sid):
    _late_start(client, admin, sid)
    r = _post(client, admin, sid, "preview", CRANE_TWO, base_version=3).json()
    # moved 는 조건의 효과만: before = 저장된 조건의 지금 예측(크레인 1대, A 실적 포함), after = 바꾼 조건의 예측.
    # A·B 는 실적 때문에 Plan 과 다르지만 조건으로는 움직이지 않으므로 빠진다(리뷰 M1).
    assert r["moved"] == [
        {"activity_id": "C", "name": "골조 2구역", "before": {"start": "2027-06-21", "finish": "2027-07-30"},
         "after": {"start": "2027-05-10", "finish": "2027-06-18"}},
        {"activity_id": "D", "name": "마감", "before": {"start": "2027-08-02", "finish": "2027-08-27"},
         "after": {"start": "2027-06-21", "finish": "2027-07-16"}},
    ]
    # PM 결정 11-20 밤(16e): view 의 Plan 은 확정하면 될 Plan = 바꾼 조건(크레인 2대)으로 계산한 지금 예측(A 실적 포함)
    view = r["view"]
    c = next(a for a in view["activities"] if a["id"] == "C")
    assert (c["plan_start"], c["plan_finish"], view["plan_finish"]) == ("2027-05-10", "2027-06-18", "2027-07-16")
    assert view["finish"] == view["plan_finish"] and {a["status"] for a in view["activities"]} == {"on_plan"}


def test_16e_preview_of_a_condition_without_date_effect_moves_nothing(client, admin, sid):
    """날짜에 영향이 없는 조건(준공 기한을 늦춤)은 실적으로 Plan 과 어긋난 액티비티가 있어도 moved 가 비어 있다."""
    _late_start(client, admin, sid)
    r = _post(client, admin, sid, "preview", [{"id": "in.finish_by", "params": {"date": "2028-03-31"}}], base_version=3)
    assert r.status_code == 200 and r.json()["moved"] == []
