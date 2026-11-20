"""일정 저장·버전·변경 이력(store)."""

import json
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.core.model import (
    Activity,
    BlockedPeriod,
    CalendarSpec,
    Constraint,
    Relation,
    Resource,
    Schedule,
    WbsNode,
)
from app.store.schedules import (
    NotFound,
    activity_json,
    create_schedule,
    from_json,
    get_record,
    load,
    to_json,
)
from app.store.tables import ChangeLog, ScheduleRecord, ScheduleVersion
from app.store.versions import (
    VersionConflict,
    list_versions,
    mark_plan,
    restore,
    save_new_version,
)
from tests.schedules import make, store, task

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_json_roundtrip(sample_schedule):
    assert from_json(to_json(sample_schedule)) == sample_schedule
def test_save_bumps_version_and_logs(session, sid, sample_schedule):
    n = save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="손장호", note="x", changes=[{"id": "A", "field": "od", "from": 3, "to": 4}], base_version=1)
    assert n == 2 and session.query(ChangeLog).filter_by(schedule_id=sid).count() == 1
def test_stale_base_version_conflicts(session, sid, sample_schedule):
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    with pytest.raises(VersionConflict) as e:
        save_new_version(session, sid, sample_schedule, [], by_kind="agent", by_name="에이전트", note="", changes=[], base_version=1)
    assert e.value.current == 2
def test_restore_creates_new_version_keeping_history(session, sid, sample_schedule):
    # 지시서 시험은 버전 2 가 이미 있다고 본다(sid 는 버전 1 만 있다). 한 번 고친 뒤 되돌린다.
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    assert restore(session, sid, 1, by_name="손장호") == 3 and len(list_versions(session, sid)) == 3


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


def _rich() -> Schedule:
    """모든 칸을 채운 일정."""
    cal = CalendarSpec(
        days_per_week=6,
        holidays=(date(2027, 3, 1), date(2027, 5, 5)),
        blocked=(BlockedPeriod((12, 1), (2, 28), "타설"),),
    )
    acts = (
        Activity("S", "착공", "start_ms", "1", 0),
        Activity(
            "A", "기초", "task", "1.1", 5, rd=2, progress=0.6,
            actual_start=date(2027, 3, 2), constraint=Constraint("SNET", date(2027, 3, 2)),
            resources=("crane", "pump"), tags=("타설",),
        ),
        Activity(
            "B", "골조", "task", "1.1", 4, progress=1.0,
            actual_start=date(2027, 3, 9), actual_finish=date(2027, 3, 12),
            constraint=Constraint("FNLT", date(2027, 4, 1)),
        ),
        Activity("F", "준공", "finish_ms", "1", 0, start_floor=date(2027, 4, 5)),
    )
    rels = (
        Relation("S", "A"), Relation("A", "B", "SS", 2), Relation("B", "F", "FF", -1),
    )
    return Schedule(
        start=date(2027, 3, 1),
        calendar=cal,
        wbs=(WbsNode("1", "사업", None), WbsNode("1.1", "골조", "1")),
        activities=acts,
        relations=rels,
        resources=(Resource("crane", "타워크레인", "대", 1), Resource("pump", "펌프카", "대", 2)),
        data_date=date(2027, 3, 10),
    )


def test_roundtrip_keeps_every_field_and_is_plain_json():
    s = _rich()
    d = to_json(s)
    assert json.loads(json.dumps(d)) == d
    assert from_json(d) == s


def test_start_floor_is_persisted(session):
    s = _rich()
    assert to_json(s)["activities"][3]["start_floor"] == "2027-04-05"
    assert from_json(to_json(s)).activities[3].start_floor == date(2027, 4, 5)
    sid = store(session, s)
    loaded, _, _ = load(session, sid)
    assert loaded.activities[3].start_floor == date(2027, 4, 5)


def test_pinned_start_is_never_persisted(session):
    s = _rich()
    pinned = replace(
        s, activities=tuple(replace(a, pinned_start=date(2027, 4, 1)) for a in s.activities)
    )
    assert all("pinned_start" not in a for a in to_json(pinned)["activities"])
    assert from_json(to_json(pinned)) == s

    sid = store(session, pinned)
    loaded, _, _ = load(session, sid)
    assert all(a.pinned_start is None for a in loaded.activities)
    save_new_version(session, sid, pinned, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    loaded, _, n = load(session, sid)
    assert n == 2 and all(a.pinned_start is None for a in loaded.activities)


def test_create_and_load(session, sample_schedule):
    conditions = [{"type": "deadline", "date": "2027-12-31"}, {"x": [1, 2]}]
    sid = create_schedule(
        session, name="물류센터", domain="construction", level="L2", schedule=sample_schedule,
        conditions=conditions, by_kind="agent", by_name="에이전트", note="처음 만듦",
    )
    rec = session.get(ScheduleRecord, sid)
    assert (rec.name, rec.domain, rec.level, rec.current_version, rec.created_by) == (
        "물류센터", "construction", "L2", 1, "에이전트"
    )
    v1 = session.get(ScheduleVersion, (sid, 1))
    assert (v1.note, v1.by_kind, v1.by_name, v1.is_plan) == ("처음 만듦", "agent", "에이전트", False)
    assert load(session, sid) == (sample_schedule, conditions, 1)
    assert session.query(ChangeLog).filter_by(schedule_id=sid).count() == 0


def test_load_older_version(session, sid, sample_schedule):
    changed = replace(sample_schedule, activities=sample_schedule.activities[:1], relations=())
    save_new_version(session, sid, changed, [{"c": 1}], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    assert load(session, sid) == (changed, [{"c": 1}], 2)
    assert load(session, sid, 1) == (sample_schedule, [], 1)


def test_load_unknown_raises_not_found(session, sid):
    with pytest.raises(NotFound):
        load(session, sid + 1)
    with pytest.raises(NotFound):
        load(session, sid, 9)


def test_save_writes_version_and_change_log(session, sid, sample_schedule):
    changes = [{"id": "A", "field": "od", "from": 3, "to": 4}]
    save_new_version(session, sid, sample_schedule, [{"c": 1}], by_kind="user", by_name="손장호", note="A 기간 3 → 4", changes=changes, base_version=1)
    v2 = session.get(ScheduleVersion, (sid, 2))
    assert (v2.note, v2.by_kind, v2.by_name, v2.is_plan, v2.conditions_json) == (
        "A 기간 3 → 4", "user", "손장호", False, [{"c": 1}]
    )
    log = session.query(ChangeLog).filter_by(schedule_id=sid).one()
    assert (log.version_n, log.by_kind, log.by_name, log.summary, log.changes_json) == (
        2, "user", "손장호", "A 기간 3 → 4", changes
    )


def test_conflict_saves_nothing(session, sid, sample_schedule):
    with pytest.raises(VersionConflict) as e:
        save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[{"id": "A"}], base_version=0)
    assert e.value.current == 1
    session.expire_all()
    assert session.get(ScheduleRecord, sid).current_version == 1
    assert len(list_versions(session, sid)) == 1
    assert session.query(ChangeLog).filter_by(schedule_id=sid).count() == 0


def test_restore_copies_old_content_and_lists_newest_first(session, sid, sample_schedule):
    changed = replace(sample_schedule, activities=sample_schedule.activities[:1], relations=())
    save_new_version(session, sid, changed, [{"c": 1}], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    assert restore(session, sid, 1, by_name="손장호") == 3
    assert load(session, sid) == (sample_schedule, [], 3)
    versions = list_versions(session, sid)
    assert [v.n for v in versions] == [3, 2, 1]
    assert (versions[0].by_kind, versions[0].by_name, versions[0].note) == ("user", "손장호", "1번 버전으로 되돌림")


def test_restore_unknown_version_raises_not_found(session, sid):
    with pytest.raises(NotFound):
        restore(session, sid, 5, by_name="a")


def test_restore_checks_base_version(session, sid, sample_schedule):
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    with pytest.raises(VersionConflict) as e:
        restore(session, sid, 1, by_name="a", base_version=1)
    assert e.value.current == 2


def test_two_sessions_cannot_both_save_on_the_same_base(session, sid, sample_schedule):
    """두 요청이 같은 버전을 읽고 저장하면 나중 것은 VersionConflict(잃는 고침 없음)."""
    with Session(session.get_bind()) as other:
        get_record(other, sid)  # 다른 세션도 버전 1 을 읽어 둔다
        get_record(session, sid)
        save_new_version(other, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
        with pytest.raises(VersionConflict) as e:
            save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="b", note="", changes=[], base_version=1)
    assert e.value.current == 2
    assert [v.by_name for v in list_versions(session, sid)] == ["a", "에이전트"]


# ── 고침 1차 ────────────────────────────────────────────────────────

CYCLE = make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])


def _save(session, sid, schedule, base, **k):
    return save_new_version(session, sid, schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=base, **k)


def test_from_json_fills_defaults_for_missing_keys(sample_schedule):
    d = to_json(sample_schedule)
    del d["data_date"], d["calendar"]["holidays"], d["calendar"]["blocked"]
    for a in d["activities"]:
        for key in ("rd", "progress", "actual_start", "actual_finish", "constraint", "resources", "tags", "start_floor"):
            del a[key]
    del d["resources"]
    for r in d["relations"]:
        del r["type"], r["lag"]
    assert from_json(d) == replace(sample_schedule, resources=())


def test_create_schedule_rejects_invalid_schedule(session):
    with pytest.raises(ScheduleError) as e:
        store(session, CYCLE)
    assert e.value.code == "cycle"
    assert session.query(ScheduleRecord).count() == 0
    assert session.query(ScheduleVersion).count() == 0


def test_commit_false_then_rollback_persists_nothing(session, sid, sample_schedule):
    other = create_schedule(
        session, name="x", domain="d", level="L1", schedule=sample_schedule, conditions=[],
        by_kind="agent", by_name="a", note="", commit=False,
    )
    assert _save(session, sid, sample_schedule, 1, commit=False) == 2
    assert restore(session, sid, 1, by_name="a", commit=False) == 3
    mark_plan(session, sid, 3, commit=False)
    session.rollback()
    assert session.get(ScheduleRecord, other) is None
    assert session.get(ScheduleRecord, sid).current_version == 1
    assert [(v.n, v.is_plan) for v in list_versions(session, sid)] == [(1, False)]
    assert session.query(ChangeLog).count() == 0


def test_conflict_with_commit_false_leaves_the_session_to_the_caller(session, sid, sample_schedule):
    other = create_schedule(
        session, name="x", domain="d", level="L1", schedule=sample_schedule, conditions=[],
        by_kind="agent", by_name="a", note="", commit=False,
    )
    with pytest.raises(VersionConflict) as e:
        _save(session, sid, sample_schedule, 5, commit=False)
    assert e.value.current == 1
    assert session.get(ScheduleRecord, other) is not None  # 되돌리지 않았다
    session.commit()
    session.expire_all()
    assert session.get(ScheduleRecord, other).current_version == 1


def test_mark_plan_leaves_exactly_one_plan(session, sid, sample_schedule):
    _save(session, sid, sample_schedule, 1)
    _save(session, sid, sample_schedule, 2)
    mark_plan(session, sid, 2)
    mark_plan(session, sid, 3)
    session.expire_all()
    assert [(v.n, v.is_plan) for v in list_versions(session, sid)] == [(3, True), (2, False), (1, False)]
    with pytest.raises(NotFound):
        mark_plan(session, sid, 9)


def test_restore_records_differences(session, sid, sample_schedule):
    a = sample_schedule.activities[0]
    changed = replace(
        sample_schedule,
        activities=(replace(a, od=5, tags=("x",)), task("C", 1)),
        relations=(Relation("A", "C", "SS", 1),),
    )
    _save(session, sid, changed, 1)
    restore(session, sid, 1, by_name="손장호")
    log = session.query(ChangeLog).filter_by(schedule_id=sid, version_n=3).one()
    assert log.summary == "1번 버전으로 되돌림"
    assert sorted(log.changes_json, key=lambda c: (c["id"], c["field"])) == [
        {"id": "A", "field": "od", "from": 5, "to": 3},
        {"id": "A", "field": "tags", "from": ["x"], "to": []},
        {"id": "B", "field": "activity", "from": None, "to": activity_json(sample_schedule.activities[1])},
        {"id": "B", "field": "predecessors", "from": [], "to": [{"pred": "A", "type": "FS", "lag": 0}]},
        {"id": "C", "field": "activity", "from": activity_json(task("C", 1)), "to": None},
        {"id": "C", "field": "predecessors", "from": [{"pred": "A", "type": "SS", "lag": 1}], "to": []},
    ]


def test_restore_of_invalid_snapshot_raises_and_saves_nothing(session, sid, sample_schedule):
    _save(session, sid, sample_schedule, 1)
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(CYCLE)
    session.commit()
    with pytest.raises(ScheduleError):
        restore(session, sid, 1, by_name="a")
    session.expire_all()
    assert session.get(ScheduleRecord, sid).current_version == 2
    assert len(list_versions(session, sid)) == 2
    assert session.query(ChangeLog).filter_by(schedule_id=sid).count() == 1


# ── 고침 2차 ────────────────────────────────────────────────────────


def _two_saves_elsewhere(session, sid, schedule):
    """다른 세션이 두 번 저장한다(DB 의 지금 버전 3)."""
    with Session(session.get_bind()) as other:
        _save(other, sid, schedule, 1)
        _save(other, sid, schedule, 2)


def test_conflict_with_commit_false_keeps_the_db_version_in_session(session, sid, sample_schedule):
    # 세션의 객체 지도는 약한 참조라, 부르는 쪽처럼 객체를 붙잡고 있어야 낡은 값이 남는다.
    record = get_record(session, sid)
    assert record.current_version == 1
    _two_saves_elsewhere(session, sid, sample_schedule)
    with pytest.raises(VersionConflict) as e:
        _save(session, sid, sample_schedule, 1, commit=False)
    assert e.value.current == 3
    assert get_record(session, sid) is record and record.current_version == 3
    assert load(session, sid)[2] == 3


def test_successful_save_with_commit_false_shows_the_new_version_in_session(session, sid, sample_schedule):
    record = get_record(session, sid)
    assert record.current_version == 1
    assert _save(session, sid, sample_schedule, 1, commit=False) == 2
    assert record.current_version == 2


def test_restore_reads_the_db_version_not_a_stale_session_value(session, sid, sample_schedule):
    record = get_record(session, sid)
    assert record.current_version == 1
    _two_saves_elsewhere(session, sid, sample_schedule)
    assert restore(session, sid, 1, by_name="a", base_version=3, commit=False) == 4
    with pytest.raises(VersionConflict) as e:
        restore(session, sid, 1, by_name="a", base_version=3, commit=False)
    assert e.value.current == 4
    assert record.current_version == 4
