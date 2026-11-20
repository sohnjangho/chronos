"""도구 out.submit_change: 초안 저장·일정 고침을 내보내고, 승인이 필요하면 승인 건을, 아니면 바로 저장한다."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.model import Relation
from app.store import chats
from app.store.schedules import load
from app.store.settings import set_approval_mode
from app.store.tables import Approval, ScheduleDraft, ScheduleRecord, ScheduleVersion
from app.store.versions import list_versions
from app.tools.registry import call, list_tools
from tests.approval_doubles import assembled, crane, make_draft, net, note_only
from tests.schedules import store

STALE = "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."
DOMAIN_NOTE = {"id": "construction.curing", "layer": "domain", "kind": "text_only", "params": {},
               "text": "양생 기간을 지킨다", "source": "분야 규칙"}


@pytest.fixture
def chat(session, ctx) -> int:
    chat = chats.create_chat(session, user_id=ctx.user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "B 를 8일로 늘려 줘"})
    session.commit()
    return chat.id


@pytest.fixture
def cx(ctx, chat):
    return replace(ctx, chat_session_id=chat)


@pytest.fixture
def net_id(session) -> int:
    """net() 를 크레인 1대 조건(조립된 목록)과 함께 버전 1로 저장한 일정."""
    return store(session, net(), assembled(crane(1)))


def change(net_id: int, *ops: dict, base: int = 1, **more) -> dict:
    return {"title": "B 기간 늘림", "schedule_id": net_id, "base_version": base, "changes": list(ops), **more}


def update(aid: str, **fields) -> dict:
    return {"op": "update_activity", "id": aid, **fields}


def test_spec():
    spec = {t.name: t for t in list_tools()}["out.submit_change"]
    assert (spec.program, spec.mutates) == ("approvals", True) and spec.description


# ── R1: 초안 저장 = 첫 저장 ─────────────────────────────────────────


async def test_draft_is_a_first_save_that_waits_for_approval(cx, session, events, chat):
    did = make_draft(session, conditions=(crane(1),), chat_session_id=chat)
    r = await call("out.submit_change", {"draft_id": did, "title": "사무동 신축"}, cx)
    assert r.ok, r.error
    aid = r.output["approval_id"]
    assert r.output == {"applied": False, "approval_id": aid, "version": None, "schedule_id": None,
                        "reasons": ["first_save"]}
    row = session.get(Approval, aid)
    assert (row.kind, row.status, row.base_version, row.draft_id, row.schedule_id) == ("first_save", "pending", 0, did, None)
    assert (row.title, row.requested_by, row.chat_session_id, row.request) == ("사무동 신축", "관리자", chat, "B 를 8일로 늘려 줘")
    # R10: 대화 카드가 다시 읽지 않고 보이도록 제목·사유·요약을 함께 낸다
    assert [(e.type, e.data) for e in events] == [
        ("approval", {"id": aid, "title": "사무동 신축", "reasons": ["first_save"], "summary": row.summary_json})
    ]
    assert row.summary_json["finish"]["after"] == "2027-03-10" and row.summary_json["changed_count"] == 4
    assert session.scalars(select(ScheduleRecord)).all() == []  # 승인 전에는 일정이 없다


async def test_used_draft_is_refused(cx, session):
    did = make_draft(session)
    session.get(ScheduleDraft, did).used_at = datetime.now(UTC)
    session.commit()
    r = await call("out.submit_change", {"draft_id": did, "title": "사무동"}, cx)
    assert (r.ok, r.error) == (False, "이미 저장한 초안입니다.")


async def test_draft_already_waiting_for_approval_is_refused(cx, session):
    did = make_draft(session)
    assert (await call("out.submit_change", {"draft_id": did, "title": "사무동"}, cx)).ok
    r = await call("out.submit_change", {"draft_id": did, "title": "사무동"}, cx)
    assert (r.ok, r.error) == (False, "이미 승인을 기다리는 초안입니다.")


async def test_missing_or_broken_draft_is_refused(cx, session):
    r = await call("out.submit_change", {"draft_id": 999, "title": "사무동"}, cx)
    assert (r.ok, r.error) == (False, "초안을 찾을 수 없습니다.")
    broken = net(extra_rels=(Relation("D", "A"),))  # 고리
    r = await call("out.submit_change", {"draft_id": make_draft(session, broken), "title": "사무동"}, cx)
    assert (r.ok, r.error) == (False, "선후 관계가 고리를 이룹니다.")


@pytest.mark.parametrize(
    "args",
    [
        {"title": "x"},
        {"title": "x", "draft_id": 1, "schedule_id": 1, "base_version": 1, "changes": [update("A", od=1)]},
        {"title": "x", "schedule_id": 1, "changes": [update("A", od=1)]},
        {"title": "x", "base_version": 1, "changes": [update("A", od=1)]},
        {"title": "x", "draft_id": 1, "conditions": []},
        {"title": "", "draft_id": 1},
        {"title": "x", "schedule_id": 1, "base_version": 1, "changes": []},
        {"title": "x", "schedule_id": 1, "base_version": 1, "changes": [{"op": "rename", "id": "A"}]},
        {"title": "x", "schedule_id": 1, "base_version": 1, "changes": [update("A", od=1, wbs="2")]},
        {"title": "x", "schedule_id": 1, "base_version": 1, "changes": [update("A", od=1)] * 101},
    ],
    ids=["neither", "both", "no_base", "no_schedule", "draft_with_conditions", "blank_title", "no_ops",
         "unknown_op", "unknown_field", "too_many_ops"],
)
async def test_input_shape_is_checked(cx, args):
    r = await call("out.submit_change", args, cx)
    assert r.ok is False and r.error.startswith("입력 형식 오류")


# ── R2: 일정 고침 ───────────────────────────────────────────────────


async def test_finish_change_waits_for_approval_and_keeps_the_schedule(cx, session, events, net_id):
    r = await call("out.submit_change", change(net_id, update("B", od=8)), cx)
    assert r.ok, r.error
    assert (r.output["applied"], r.output["version"], r.output["reasons"]) == (False, None, ["finish_changed"])
    row = session.get(Approval, r.output["approval_id"])
    assert (row.kind, row.status, row.schedule_id, row.base_version) == ("change", "pending", net_id, 1)
    assert row.changes_json == [{"id": "B", "field": "od", "from": 4, "to": 8}]
    assert [d["activity_id"] for d in row.diff_json] == ["B", "D"]
    assert row.summary_json["finish"] == {"before": "2027-03-10", "after": "2027-03-16", "delta_days": 6}
    assert [e.type for e in events] == ["approval"]
    assert load(session, net_id)[2] == 1  # 승인 전에는 반영하지 않는다


async def test_change_absorbed_in_float_is_applied_at_once(cx, session, events, net_id):
    r = await call("out.submit_change", change(net_id, update("C", od=3), title="C 기간 3일"), cx)
    assert r.ok, r.error
    aid = r.output["approval_id"]
    assert r.output == {"applied": True, "approval_id": aid, "version": 2, "schedule_id": net_id, "reasons": []}
    session.commit()
    newest = list_versions(session, net_id)[0]
    assert (newest.n, newest.by_kind, newest.by_name, newest.note) == (2, "agent", "에이전트", "C 기간 3일")
    assert load(session, net_id)[0].activities[2].od == 3
    # R8: 자동 적용도 승인 표에 남긴다(같은 요약, 되돌릴 버전)
    row = session.get(Approval, aid)
    assert (row.status, row.version, row.restore_to, row.decided_by) == ("auto", 2, 1, None)
    assert [(e.type, e.data) for e in events] == [
        ("card", {"kind": "auto_applied", "schedule_id": net_id, "version": 2, "count": 1, "summary": row.summary_json})
    ]


async def test_add_activity_and_delete_activity(cx, session, net_id):
    new = {"id": "E", "name": "외부 마감", "od": 1, "preds": [{"pred": "A"}], "tags": ["마감"]}
    r = await call("out.submit_change", change(net_id, {"op": "add_activity", "activity": new}), cx)
    assert (r.ok, r.output["applied"]) == (True, True), r.error  # 여유 안에서 더하기만 함 → 자동
    schedule = load(session, net_id)[0]
    e = schedule.activities[-1]
    assert (e.id, e.wbs, e.tags, e.kind) == ("E", "1", ("마감",), "task")  # wbs 는 첫 선행의 것
    assert Relation("A", "E") in schedule.relations
    r = await call("out.submit_change", change(net_id, {"op": "delete_activity", "id": "C"}, base=2), cx)
    assert (r.output["applied"], r.output["reasons"]) == (False, ["structure_changed"])
    changes = session.get(Approval, r.output["approval_id"]).changes_json
    # 변경 이력 모양은 되돌리기와 같다(store.diff.schedule_changes)
    assert [(c["id"], c["field"]) for c in changes] == [("D", "predecessors"), ("C", "activity"), ("C", "predecessors")]


async def test_update_replaces_name_and_predecessors(cx, session, net_id):
    ops = [update("C", name="설비 배관", preds=[{"pred": "B", "type": "SS", "lag": 1}])]
    r = await call("out.submit_change", change(net_id, *ops), cx)
    assert r.ok, r.error
    assert (r.output["applied"], r.output["reasons"]) == (False, ["structure_changed"])  # A → C 관계가 없어졌다
    row = session.get(Approval, r.output["approval_id"])
    assert row.changes_json == [
        {"id": "C", "field": "name", "from": "작업 C", "to": "설비 배관"},
        {"id": "C", "field": "predecessors", "from": [{"pred": "A", "type": "FS", "lag": 0}],
         "to": [{"pred": "B", "type": "SS", "lag": 1}]},
    ]
    assert row.diff_json == [
        {"activity_id": "C", "name": "설비 배관", "before": {"start": "2027-03-04", "finish": "2027-03-04"},
         "after": {"start": "2027-03-05", "finish": "2027-03-05"}, "finish_delta": 1},
    ]


@pytest.mark.parametrize(
    ("op", "message"),
    [
        (update("Z", od=1), "없는 액티비티입니다: Z"),
        ({"op": "delete_activity", "id": "Z"}, "없는 액티비티입니다: Z"),
        (update("C", preds=[{"pred": "D"}]), "선후 관계가 고리를 이룹니다."),
        (update("C", preds=[{"pred": "Q"}]), "없는 액티비티를 가리키는 관계가 있습니다."),
        ({"op": "add_activity", "activity": {"id": "A", "name": "중복", "od": 1, "preds": []}},
         "같은 ID의 액티비티가 있습니다."),
        ({"op": "add_activity", "activity": {"id": "E", "name": "e", "od": 1, "preds": [], "wbs": "9"}},
         "없는 WBS 코드입니다: 9"),
        ({"op": "add_activity", "activity": {"id": "E", "name": "e", "od": 1, "preds": [], "resources": ["pump"]}},
         "없는 자원입니다: pump"),
        (update("C", od=1), "바뀐 것이 없습니다."),
    ],
    ids=["unknown_update", "unknown_delete", "cycle", "dangling", "duplicate", "unknown_wbs", "unknown_resource",
         "no_change"],
)
async def test_invalid_changes_are_tool_errors_and_save_nothing(cx, session, net_id, op, message):
    r = await call("out.submit_change", change(net_id, op), cx)
    assert (r.ok, r.error) == (False, message)
    session.rollback()
    assert session.scalars(select(Approval)).all() == [] and load(session, net_id)[2] == 1


async def test_stale_base_version_at_submit(cx, session, net_id):
    r = await call("out.submit_change", change(net_id, update("B", od=8), base=3), cx)
    assert (r.ok, r.error) == (False, STALE)
    r = await call("out.submit_change", change(999, update("B", od=8)), cx)
    assert (r.ok, r.error) == (False, "일정을 찾을 수 없습니다.")


async def test_conditions_replace_only_the_input_layer(cx, session):
    sid = store(session, net(), [DOMAIN_NOTE, *assembled(crane(1))])
    r = await call("out.submit_change", change(sid, conditions=[crane(2)]), cx)
    assert r.ok, r.error
    assert (r.output["applied"], r.output["reasons"]) == (False, ["condition_changed"])
    row = session.get(Approval, r.output["approval_id"])
    kept = [(c["id"], c["layer"]) for c in row.conditions_json]
    assert kept == [("construction.curing", "domain"), ("base.no_cycle", "base"), ("base.no_dangling", "base"),
                    ("base.calendar", "base"), ("base.valid", "base"), ("in.resource_cap.crane", "input")]
    assert row.conditions_json[-1]["params"]["capacity"] == 2
    assert row.summary_json["conditions_changed"] == [
        {"id": "in.resource_cap.crane", "name": "타워크레인", "before": "1대", "after": "2대"}
    ]


async def test_conditions_must_be_readable_input_conditions(cx, net_id):
    r = await call("out.submit_change", change(net_id, conditions=[DOMAIN_NOTE]), cx)
    assert (r.ok, r.error) == (False, "입력 조건(layer input)만 바꿀 수 있습니다: construction.curing")
    r = await call("out.submit_change", change(net_id, conditions=[{**crane(1), "params": {}}]), cx)
    assert (r.ok, r.error) == (False, "조건을 읽을 수 없습니다: in.resource_cap.crane: 'resource_id' 칸이 없습니다.")


# ── R4·R5: 요약 ─────────────────────────────────────────────────────


async def test_unchecked_conditions_are_never_counted_as_passed(cx, session):
    sid = store(session, net(), assembled(crane(1), note_only()))
    r = await call("out.submit_change", change(sid, update("B", od=8)), cx)
    summary = session.get(Approval, r.output["approval_id"]).summary_json
    assert summary["check"] == {"passed": 5, "violations": [], "uncheckable": 1, "invalid": 0}


async def test_request_is_the_last_user_text_cut_to_200(cx, session, chat, net_id):
    chats.add_message(session, chat, "user", {"kind": "text", "text": "가" * 250})
    session.commit()
    r = await call("out.submit_change", change(net_id, update("B", od=8)), cx)
    assert session.get(Approval, r.output["approval_id"]).request == "가" * 200


async def test_without_a_chat_the_request_is_empty(ctx, session, net_id):
    r = await call("out.submit_change", change(net_id, update("B", od=8)), ctx)
    row = session.get(Approval, r.output["approval_id"])
    assert (row.request, row.chat_session_id) == ("", None)


# ── R9: 승인 수준 ───────────────────────────────────────────────────


async def test_approval_mode_setting_decides(cx, session, net_id):
    set_approval_mode(session, "auto")
    r = await call("out.submit_change", change(net_id, update("B", od=8)), cx)
    assert (r.output["applied"], r.output["version"]) == (True, 2)  # 위반이 없으면 준공이 바뀌어도 자동
    set_approval_mode(session, "all")
    r = await call("out.submit_change", change(net_id, update("C", od=2), base=2), cx)
    assert (r.output["applied"], r.output["reasons"]) == (False, [])  # all 은 늘 승인


async def test_first_save_in_auto_mode_creates_the_plan(cx, session, events):
    set_approval_mode(session, "auto")
    did = make_draft(session, conditions=(crane(1),))
    r = await call("out.submit_change", {"draft_id": did, "title": "사무동 신축"}, cx)
    assert r.ok, r.error
    sid = r.output["schedule_id"]
    assert (r.output["applied"], r.output["version"]) == (True, 1)
    session.commit()
    record = session.get(ScheduleRecord, sid)
    assert (record.name, record.domain, record.level) == ("사무동 신축", "construction", "L3")
    assert session.get(ScheduleVersion, (sid, 1)).is_plan is True
    draft = session.get(ScheduleDraft, did)
    assert draft.used_at is not None and draft.schedule_id == sid
    row = session.get(Approval, r.output["approval_id"])
    assert (row.status, row.restore_to, row.schedule_id) == ("auto", None, sid)
    assert events[0].data["kind"] == "auto_applied" and events[0].data["schedule_id"] == sid
