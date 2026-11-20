"""propose(일정 변경 제안의 공통 길)와 지연 반영 기준(store.delays.delayed_base)."""

from dataclasses import replace
from datetime import date

import pytest

from app.agent.proposals import Proposal, ProposalError, propose
from app.core.model import Relation
from app.store.delays import (
    DelayEventRow,
    delayed_base,
    mark_reflected,
    open_events,
    to_core,
)
from app.store.schedules import load, run
from app.store.settings import set_approval_mode
from app.store.versions import save_new_version
from tests.schedules import make, store, task

START_AFTER = {"id": "in.start_after", "layer": "input", "kind": "start_after", "params": {"date": "2027-03-03"},
               "text": "3월 3일 착공", "source": "프롬프트"}


def proposal(session, sid: int, *, od: int | None = 4, extra=(), **more) -> Proposal:
    """sid 의 B 기간을 od 로(None 이면 E(1일, A 뒤) 더하기 — 여유 안이라 assess 사유가 없다)."""
    before, stored, n = load(session, sid)
    if od is None:
        after = replace(before, activities=(*before.activities, task("E", 1)),
                        relations=(*before.relations, Relation("A", "E")))
    else:
        after = replace(before, activities=tuple(replace(a, od=od) if a.id == "B" else a for a in before.activities))
    return Proposal(kind="change", title="B 4일", before=before, before_conditions=stored, after=after,
                    after_conditions=stored, schedule_id=sid, draft_id=None, base_version=n, **more)


def change_with_finish_moved(session, sid: int) -> Proposal:
    return proposal(session, sid)


def add_delay(session, sid: int, aid: str, days: int, start: str = "2027-03-04", status: str = "open") -> int:
    row = DelayEventRow(schedule_id=sid, activity_id=aid, start_date=date.fromisoformat(start), days=days,
                        status=status, created_by="김하늘")
    session.add(row)
    session.commit()
    return row.id


# ── propose ─────────────────────────────────────────────────────────


def test_force_auto_records_an_auto_row(session, sid):
    r = propose(session, change_with_finish_moved(session, sid), chat_session_id=None, requested_by="김하늘",
                force_auto=True)
    assert r.applied and (r.row.status, r.row.restore_to) == ("auto", 1) and "finish_changed" in r.reasons
    assert (r.row.version, r.row.requested_by, r.row.reasons_json) == (2, "김하늘", r.reasons)
    session.commit()
    assert load(session, sid)[2] == 2


def test_change_that_needs_approval_waits_and_emits_the_approval_event(session, sid):
    events = []
    r = propose(session, proposal(session, sid), chat_session_id=None, requested_by="김하늘", emit=events.append)
    assert (r.applied, r.row.status, r.row.version, r.reasons) == (False, "pending", None, ["finish_changed"])
    assert [(e.type, e.data) for e in events] == [
        ("approval", {"id": r.row.id, "title": "B 4일", "reasons": ["finish_changed"], "summary": r.row.summary_json})
    ]
    assert load(session, sid)[2] == 1


def test_auto_apply_emits_the_auto_applied_card(session, sid):
    events = []
    r = propose(session, proposal(session, sid, od=None), chat_session_id=None, requested_by="김하늘",
                emit=events.append)
    assert (r.applied, r.reasons, r.row.status, r.row.restore_to) == (True, [], "auto", 1)
    assert [(e.type, e.data["kind"], e.data["version"], e.data["count"]) for e in events] == [
        ("card", "auto_applied", 2, 1)
    ]


def test_extra_reasons_join_in_reason_order_without_repeats(session, sid):
    r = propose(session, proposal(session, sid), chat_session_id=None, requested_by="김하늘",
                extra_reasons=("rule_save", "finish_changed"))
    assert r.reasons == ["finish_changed", "rule_save"] == r.row.reasons_json


def test_extra_reason_alone_needs_approval_when_important(session, sid):
    r = propose(session, proposal(session, sid, od=None), chat_session_id=None, requested_by="김하늘",
                extra_reasons=("rule_save",))
    assert (r.applied, r.reasons, r.row.status) == (False, ["rule_save"], "pending")


def test_auto_mode_applies_without_resetting_the_plan(session, sid):
    """PM 11-20: Plan 다시 잡기(reset_plan·plan_reset)는 없다 — 승인 표의 reset_plan 칸은 늘 False."""
    set_approval_mode(session, "auto")
    r = propose(session, proposal(session, sid), chat_session_id=None, requested_by="김하늘")
    assert (r.applied, r.reasons, r.row.reset_plan) == (True, ["finish_changed"], False)


def test_all_mode_always_waits(session, sid):
    set_approval_mode(session, "all")
    r = propose(session, proposal(session, sid, od=None), chat_session_id=None, requested_by="김하늘")
    assert (r.applied, r.reasons) == (False, [])


def test_link_fields_are_stored_on_the_row(session, sid):
    p = proposal(session, sid, link_kind="scenario", link_id=7, rule_json={"kind": "max_duration"})
    row = propose(session, p, chat_session_id=None, requested_by="김하늘").row
    assert (row.link_kind, row.link_id, row.reset_plan, row.rule_json) == ("scenario", 7, False, {"kind": "max_duration"})


@pytest.mark.parametrize(("make_after", "code", "message"), [
    (lambda s: s, "no_change", "바뀌는 것이 없습니다."),
    (lambda s: replace(s, relations=(*s.relations, Relation("B", "A"))), "schedule_invalid", "선후 관계가 고리를 이룹니다."),
])
def test_unchanged_or_broken_proposals_are_errors(session, sid, make_after, code, message):
    p = proposal(session, sid)
    with pytest.raises(ProposalError) as e:
        propose(session, replace(p, after=make_after(p.before)), chat_session_id=None, requested_by="김하늘")
    assert (e.value.code, e.value.message, str(e.value)) == (code, message, message)


def test_auto_apply_on_a_moved_schedule_is_stale(session, sid):
    p = proposal(session, sid)
    save_new_version(session, sid, p.before, p.before_conditions, by_kind="user", by_name="김하늘", note="다른 고침",
                     changes=[], base_version=1, plan_change=False)
    with pytest.raises(ProposalError) as e:
        propose(session, p, chat_session_id=None, requested_by="김하늘", force_auto=True)
    assert (e.value.code, e.value.message) == ("stale", "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요.")


# ── 지연 반영 기준 ──────────────────────────────────────────────────


@pytest.fixture
def sid_with_finished_A(session) -> int:
    """A(3일) 3/1~3/3 끝남 → B(2일), Data Date 3/4. 준공 3/5."""
    s = make([task("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3)), task("B", 2)],
             [Relation("A", "B")])
    return store(session, replace(s, data_date=date(2027, 3, 4)))


def test_delayed_base_inserts_open_events_and_skips_finished(session, sid_with_finished_A):
    sid = sid_with_finished_A
    on_b, on_a = add_delay(session, sid, "B", 2), add_delay(session, sid, "A", 1, start="2027-03-02")
    d = delayed_base(session, sid)        # B +2(열림, 시작 전이라 시작을 미룸), A +1(끝난 액티비티)
    assert {a.id: a.start_floor for a in d.schedule.activities}["B"] == date(2027, 3, 8)
    assert {a.id: a.od for a in d.schedule.activities} == {"A": 3, "B": 2}
    assert (d.event_ids, d.skipped, d.version, d.conditions) == ([on_b], [on_a], 1, [])
    assert run(d.schedule, d.conditions).finish == date(2027, 3, 9)


def test_delayed_base_counts_from_the_dates_the_user_sees(session):
    """착공 조건(3/3)으로 B 가 3/8 에 시작한다. 1일 지연의 하한은 그 3/8 에서 센다(조건 없는 3/4 가 아니라)."""
    sid = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]), [START_AFTER])
    add_delay(session, sid, "B", 1)
    d = delayed_base(session, sid)
    assert {a.id: a.start_floor for a in d.schedule.activities}["B"] == date(2027, 3, 9)
    assert d.conditions == [START_AFTER] and run(d.schedule, d.conditions).finish == date(2027, 3, 10)


def test_delayed_base_takes_only_open_events_of_the_schedule_in_start_order(session, sid):
    other = store(session, make([task("B", 2)]))
    later = add_delay(session, sid, "B", 1, start="2027-03-05")
    first = add_delay(session, sid, "A", 1, start="2027-03-01")
    add_delay(session, sid, "B", 5, status="reflected")
    add_delay(session, other, "B", 3)
    assert [e.id for e in open_events(session, sid)] == [first, later]
    assert delayed_base(session, sid).event_ids == [first, later]
    d = delayed_base(session, sid, [later])
    assert (d.event_ids, d.skipped, run(d.schedule, d.conditions).finish) == ([later], [], date(2027, 3, 8))


def test_event_on_a_missing_activity_is_skipped(session, sid):
    gone = add_delay(session, sid, "Z", 2)
    d = delayed_base(session, sid)
    assert (d.event_ids, d.skipped, d.schedule) == ([], [gone], load(session, sid)[0])


def test_to_core_and_mark_reflected(session, sid):
    eid = add_delay(session, sid, "B", 2)
    done = add_delay(session, sid, "A", 1, status="reflected")
    session.get(DelayEventRow, done).reflected_version = 1
    e = to_core(session.get(DelayEventRow, eid))
    assert (e.id, e.activity_id, e.start, e.days, e.daily_cost) == (f"{eid:012d}", "B", date(2027, 3, 4), 2, None)
    mark_reflected(session, [eid, done], 3)
    rows = [session.get(DelayEventRow, i) for i in (eid, done)]
    assert [(r.status, r.reflected_version) for r in rows] == [("reflected", 3), ("reflected", 1)]
