"""시연 씨앗 버전 3(`python -m app.seed demo v3`): 6월 말 실적 + 커튼월·창호 조달 줄. 기본 설정(k=3, w=3)에서 계획 5 두 장면
(같은 3일 다른 영향 · 골조를 당겨도 준공은 1일)이 나오는지 본다. 숫자는 docs/demo/시나리오.md 「관리 포인트 장면」과 같다."""

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
from app.store.tables import ScheduleRecord

K, W = 3, 3
CURTAIN = ("A1402", "A1404", "A1406", "A1410")
WINDOW = ("A1434", "A1436", "A1438")


def _v3(session):
    seed.seed_demo(session, seed.DEMO_V3)
    record = session.scalars(select(ScheduleRecord).where(ScheduleRecord.name == seed.OFFICE)).one()
    schedule, conditions, n = load(session, record.id)
    ready = prepare_stored(schedule, conditions)
    return record, n, ready, level(ready, compute(ready), shift=True)


def _delayed(ready, lv, aid: str):
    changed, _ = insert_delay(ready, DelayEvent("E1", aid, lv.dates[aid][0], 3))
    return changed, level(changed, compute(changed), shift=True)


def test_v3_keeps_versions_one_and_two(session):
    seed.seed_demo(session)
    plain = session.scalars(select(ScheduleRecord).where(ScheduleRecord.name == seed.OFFICE)).one()
    v1, v2 = load(session, plain.id, 1), load(session, plain.id, 2)
    record, n, ready, _ = _v3(session)
    assert (n, record.current_version) == (3, 3)
    assert load(session, record.id, 1)[:2] == v1[:2] and load(session, record.id, 2)[:2] == v2[:2]
    assert ready.data_date == seed.DATA_DATE_V3
    names = {a.id: a.name for a in ready.activities}
    assert names["A1410"] == "커튼월·외장 패널 1~3층" and names["A1430"] == "커튼월·외장 패널 4~5층"
    assert len(ready.activities) == len(v2[0].activities) + 6


def test_v3_frame_is_critical_and_procurement_floats(session):
    """R1 골조 크리티컬·창 안 · R2 커튼월 줄 여유 4, 창호 줄 여유 ≥ 10."""
    _, _, ready, lv = _v3(session)
    points = {p.activity_id: p for p in compute_points(ready, lv.cpm, tf_days=K, window_weeks=W)}
    assert {"A1252", "A1254", "A1300"} <= {i for i, p in points.items() if p.critical}
    assert {lv.cpm.rows[i].tf for i in CURTAIN} == {4}
    assert min(lv.cpm.rows[i].tf for i in WINDOW) >= 10
    assert lv.cpm.rows["A1404"].tf == 4 and next(a.od for a in ready.activities if a.id == "A1404") >= 5  # R5 압축 후보


def test_same_three_days_different_effect(session):
    """R3: 창호 도면 승인 +3 → 준공 0·포인트 그대로 / 커튼월 도면 승인 +3 → 준공 0, 커튼월 줄 여유 1 로 포인트에 들어온다."""
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
    assert delta == 0 and {p.activity_id: p.tf for p in diff.added} == dict.fromkeys(CURTAIN, 1)


def test_pulling_the_frame_after_the_curtain_wall_delay_gains_one_day(session):
    """R4: 커튼월 도면 승인 +3 뒤 골조 5일 당김(옥탑 골조 6 → 1 · 5층 철근 4 → 1 + 거푸집 4 → 2) → 준공 1일, 다음 줄은 커튼월.
    R5: 그 일정의 만회안 B 에 커튼월 공장 제작 압축이 든다."""
    _, _, ready, lv = _v3(session)
    changed, cl = _delayed(ready, lv, "A1402")
    cal = WorkCalendar(changed.calendar)
    for moves in ([Move("m", "compress", ("A1300",), "", od=1)],
                  [Move("a", "compress", ("A1250",), "", od=1), Move("b", "compress", ("A1252",), "", od=2)]):
        moved = apply_moves(changed, moves)
        after = level(moved, compute(moved), shift=True)
        assert cal.workdays_between(after.finish, cl.finish) == 1
        assert after.cpm.critical_path[:4] == CURTAIN
    b = next(p for p in shorten(changed, target=5).packages if p.key == "B")
    assert "cmp:A1404" in {m.id for m in b.moves}


def test_cli_demo_v3(client, session):
    assert seed.main(["demo", "v3"]) == 0
    session.expire_all()
    assert session.scalars(select(ScheduleRecord).where(ScheduleRecord.name == seed.OFFICE)).one().current_version == 3
