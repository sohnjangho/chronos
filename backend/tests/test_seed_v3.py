"""시연 씨앗 버전 3(`python -m app.seed demo v3`): 6월 말 실적 + 커튼월·창호 조달 줄, 승인한 계획 변경(Plan 다시 찍음).
기본 설정(k=3, w=3)에서 계획 5 두 장면(같은 3일 다른 영향 · 골조를 당겨도 준공은 1일)이 나오는지 숫자 그대로 고정한다.
숫자는 scripts/find_demo_pair.py · find_accel_case.py --version 3 출력, docs/demo/시나리오.md 「관리 포인트 장면」과 같다."""

from datetime import date

from sqlalchemy import select

from app import seed
from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.delay import DelayEvent, analyze, insert_delay
from app.core.points import compute_points, diff_points
from app.core.resources import level
from app.core.shorten import Move, apply_moves, shorten
from app.harness.assemble import prepare_stored
from app.store.schedules import load
from app.store.tables import Approval, ScheduleRecord

K, W = 3, 3
CURTAIN = ("A1402", "A1404", "A1406", "A1410")
WINDOW = ("A1434", "A1436", "A1438")
PULL_ROOF = [Move("m", "compress", ("A1300",), "", od=1)]  # 옥탑 골조 6 → 1
PULL_5F = [Move("a", "compress", ("A1250",), "", od=1), Move("b", "compress", ("A1252",), "", od=2)]  # 5층 4→1·4→2


def _record(session) -> ScheduleRecord:
    return session.scalars(select(ScheduleRecord).where(ScheduleRecord.name == seed.OFFICE)).one()


def _v3(session):
    seed.seed_demo(session, seed.DEMO_V3)
    record = _record(session)
    schedule, conditions, n = load(session, record.id)
    ready = prepare_stored(schedule, conditions)
    return record, n, ready, level(ready, compute(ready), shift=True)


def _delayed(ready, lv, aid: str):
    changed, _ = insert_delay(ready, DelayEvent("E1", aid, lv.dates[aid][0], 3))
    return changed, level(changed, compute(changed), shift=True)


def _gain(schedule, base, moves) -> int:
    moved = apply_moves(schedule, moves)
    after = level(moved, compute(moved), shift=True)
    return WorkCalendar(schedule.calendar).workdays_between(after.finish, base.finish), after


def test_v3_is_stacked_on_versions_one_and_two(session):
    """버전 3 은 버전 1·2 위에 쌓인다(버전 1·2 숫자 자체는 test_seed·test_plan_frozen 이 고정한다)."""
    seed.seed_demo(session)
    plain = _record(session)
    v1, v2 = load(session, plain.id, 1), load(session, plain.id, 2)
    record, n, ready, lv = _v3(session)
    assert (n, record.current_version) == (3, 3)
    assert load(session, record.id, 1)[:2] == v1[:2] and load(session, record.id, 2)[:2] == v2[:2]
    assert (ready.data_date, lv.finish) == (seed.DATA_DATE_V3, date(2027, 11, 8))
    acts = {a.id: a for a in ready.activities}
    assert (acts["A1410"].name, acts["A1430"].name) == ("커튼월·외장 패널 1~3층", "커튼월·외장 패널 4~5층")
    assert acts["A1410"].resources == acts["A1430"].resources == ()
    assert len(ready.activities) == len(v2[0].activities) + 6


def test_v3_is_an_approved_plan_change_with_zero_finish_variance(client, admin, session):
    record, _, _, _ = _v3(session)
    row = session.scalars(select(Approval).where(Approval.schedule_id == record.id)).one()
    assert (row.kind, row.status, row.version, row.base_version, row.title) == (
        "change", "approved", 3, 2, "6월 말 실적 + 커튼월·창호 조달 일정 반영")
    assert row.summary_json["plan_change"] is True
    view = client.get(f"/api/schedules/{record.id}", headers=admin).json()
    assert (view["version"], view["plan_finish"], view["finish"]) == (3, "2027-11-08", "2027-11-08")


def test_v3_points_and_procurement_floats(session):
    """R1 크리티컬·여유 3 이하 포인트(창 안) · R2 커튼월 줄 여유 4, 창호 줄 여유 13 · R5 공장 제작 od 6(압축 후보)."""
    _, _, ready, lv = _v3(session)
    points = compute_points(ready, lv.cpm, tf_days=K, window_weeks=W)
    assert [(p.activity_id, p.tf, p.critical) for p in points] == [
        ("A1242", 3, False), ("A1244", 3, False), ("A1250", 3, False),
        ("A1252", 0, True), ("A1254", 0, True), ("A1300", 0, True)]
    assert {i: lv.cpm.rows[i].tf for i in CURTAIN + WINDOW} == {**dict.fromkeys(CURTAIN, 4), **dict.fromkeys(WINDOW, 13)}
    assert (lv.cpm.rows["A1402"].es, lv.cpm.rows["A1434"].es) == (seed.DATA_DATE_V3, seed.DATA_DATE_V3)
    assert next(a.od for a in ready.activities if a.id == "A1404") == 6


def test_same_three_days_different_effect(session):
    """R3: 창호 도면 승인 +3 → 준공 0·포인트 그대로 / 커튼월 도면 승인 +3 → 준공 0, 커튼월 줄 넷이 여유 1 로 포인트에 들어온다."""
    _, _, ready, lv = _v3(session)
    before = compute_points(ready, lv.cpm, tf_days=K, window_weeks=W)
    results = {}
    for aid in ("A1434", "A1402"):
        impact = analyze(ready, [DelayEvent("E1", aid, lv.dates[aid][0], 3)]).impacts[0]
        changed, cl = _delayed(ready, lv, aid)
        results[aid] = impact.finish_delta, diff_points(before, compute_points(changed, cl.cpm, tf_days=K, window_weeks=W))
    delta, diff = results["A1434"]
    assert delta == 0 and (diff.added, diff.removed, diff.tightened) == ((), (), ())
    delta, diff = results["A1402"]
    assert delta == 0 and [(p.activity_id, p.tf) for p in diff.added] == [(i, 1) for i in CURTAIN]
    assert (diff.removed, diff.tightened) == ((), ())


def test_pulling_the_frame_five_days(session):
    """R4: 같은 5일 당김(옥탑 골조 6 → 1 · 5층 철근 4 → 1 + 거푸집 4 → 2)이 커튼월 지연 전에는 준공 4일, 커튼월 도면 승인 +3
    뒤에는 1일이고 다음 줄은 커튼월. R5: 그 일정의 만회안(목표 5) B 는 준공 11-01·이득 6, 커튼월 공장 제작 6 → 4 가 든다."""
    _, _, ready, lv = _v3(session)
    for moves in (PULL_ROOF, PULL_5F):
        assert _gain(ready, lv, moves)[0] == 4
    changed, cl = _delayed(ready, lv, "A1402")
    for moves in (PULL_ROOF, PULL_5F):
        gain, after = _gain(changed, cl, moves)
        assert (gain, after.finish) == (1, date(2027, 11, 6))
        assert after.cpm.critical_path[:4] == CURTAIN
    b = next(p for p in shorten(changed, target=5).packages if p.key == "B")
    assert (b.finish, b.gain) == (date(2027, 11, 1), 6)
    assert [m.id for m in b.moves] == ["res:tower_crane", "cmp:A1720", "cmp:A1404"]


def test_cli_demo_v3(client, session):
    assert seed.main(["demo", "v3"]) == 0
    session.expire_all()
    assert _record(session).current_version == 3
