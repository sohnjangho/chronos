"""관리 포인트 계산(core.points): 끝나지 않은 task 가운데 크리티컬·여유 k 이하, Data Date 부터 w 주 안에 시작하는 것."""

from dataclasses import replace
from datetime import date

from app.core.cpm import compute
from app.core.model import Activity, Relation
from app.core.points import Point, PointsDiff, compute_points, diff_points
from tests.core.helpers import act, sched


def _ms(i: str, kind: str = "finish_ms") -> Activity:
    return Activity(id=i, name=i, kind=kind, wbs="1", od=0)


def _points(s, *, k: int = 3, w: int = 3) -> tuple[Point, ...]:
    return compute_points(s, compute(s), tf_days=k, window_weeks=w)


def _fan() -> list:
    """X(10)·B(8)·C(7)·E(6) 이 나란히 끝 마일스톤 F 로. 여유 X 0 · B 2 · C 3 · E 4."""
    acts = [act("X", 10), act("B", 8), act("C", 7), act("E", 6), _ms("F")]
    rels = [Relation(i, "F") for i in ("X", "B", "C", "E")]
    return sched(acts, rels)


def test_critical_and_near_critical_in_window():
    s = _fan()
    tf = {i: r.tf for i, r in compute(s).rows.items()}
    assert (tf["X"], tf["B"], tf["C"], tf["E"]) == (0, 2, 3, 4)
    got = _points(s, k=3)
    assert [p.activity_id for p in got] == ["X", "B", "C"]
    x = got[0]
    row = compute(s).rows["X"]
    assert x == Point("X", "X", True, 0, row.es, row.ef)
    assert [p.critical for p in got] == [True, False, False]
    assert [p.activity_id for p in _points(s, k=2)] == ["X", "B"]
    assert [p.activity_id for p in _points(s, k=0)] == ["X"]


def test_finished_and_milestones_excluded():
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0)
    acts = [_ms("S", "start_ms"), a, act("B", 2), _ms("F")]
    rels = [Relation("S", "A"), Relation("A", "B"), Relation("B", "F")]
    s = replace(sched(acts, rels), data_date=date(2027, 3, 4))
    rows = compute(s).rows
    assert rows["S"].critical and rows["F"].critical  # 크리티컬이어도 마일스톤은 포인트가 아니다
    assert [p.activity_id for p in _points(s)] == ["B"]


def test_window_cuts_by_es():
    """창 = Data Date + w 주(달력). ES 가 그 날 이하면 넣고, 넘으면 뺀다. 진행 중(ES 가 Data Date 앞)도 넣는다."""
    a = act("A", 5, actual_start=date(2027, 2, 22), rd=3, progress=0.4)
    acts = [a, act("B", 2), act("C", 5), act("D", 5)]
    rels = [Relation("A", "B"), Relation("B", "C"), Relation("C", "D")]
    s = replace(sched(acts, rels, start=date(2027, 2, 22)), data_date=date(2027, 3, 1))
    rows = compute(s).rows
    assert rows["A"].es < date(2027, 3, 1)  # 진행 중
    # A 남은 3일 3/1~3/3, B 3/4~3/5, C 3/8~3/12, D 3/15~
    assert (rows["B"].es, rows["C"].es, rows["D"].es) == (date(2027, 3, 4), date(2027, 3, 8), date(2027, 3, 15))
    assert [p.activity_id for p in _points(s, w=1)] == ["A", "B", "C"]  # 3/8 = DD + 7일 은 창 안
    assert [p.activity_id for p in _points(s, w=2)] == ["A", "B", "C", "D"]


def test_window_starts_at_schedule_start_without_data_date():
    acts = [act("A", 5), act("B", 5), act("C", 5)]
    s = sched(acts, [Relation("A", "B"), Relation("B", "C")])  # 3/1 시작, A 3/1 · B 3/8 · C 3/15
    assert [p.activity_id for p in _points(s, w=1)] == ["A", "B"]


def test_points_in_es_order():
    acts = [act("L", 2), act("K", 3)]
    s = sched(acts, [Relation("K", "L")])
    assert [p.activity_id for p in _points(s)] == ["K", "L"]


def test_all_finished_gives_no_points():
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0)
    b = act("B", 2, actual_start=date(2027, 3, 4), actual_finish=date(2027, 3, 5), progress=1.0)
    s = replace(sched([a, b, _ms("F")], [Relation("A", "B"), Relation("B", "F")]), data_date=date(2027, 3, 8))
    assert _points(s) == ()


def _p(i: str, tf: int, es: date = date(2027, 3, 1)) -> Point:
    return Point(i, f"작업 {i}", tf == 0, tf, es, es)


def test_diff_added_removed_tightened():
    prev = (_p("A", 0), _p("B", 3), _p("C", 2), _p("E", 1))
    cur = (_p("A", 0), _p("D", 0), _p("B", 1), _p("E", 2))
    got = diff_points(prev, cur)
    assert got == PointsDiff(added=(cur[1],), removed=("C",), tightened=(("B", 3, 1),),  # E 는 여유가 늘어 뺀다
                             became_critical=(), before_tf={"B": 3})  # D 는 앞 상태 여유를 모른다(prev_tf 없음)


def test_diff_became_critical_and_before_tf():
    """앞에도 포인트였고 크리티컬이 아니었다가 크리티컬이 된 것 = became_critical. before_tf 는 새로 들어온 것·
    크리티컬이 된 것·여유가 줄어든 것의 앞 상태 여유 — 앞에 포인트가 아니었어도 prev_tf(앞 상태 CPM)에서."""
    prev = (_p("A", 0), _p("B", 2))
    cur = (_p("A", 0), _p("B", 0), _p("D", 1), _p("N", 0))
    got = diff_points(prev, cur, prev_tf={"A": 0, "B": 2, "D": 5})
    assert [p.activity_id for p in got.added] == ["D", "N"]
    assert got.became_critical == ("B",)
    assert got.tightened == (("B", 2, 0),)
    assert got.before_tf == {"B": 2, "D": 5}  # N 은 앞 버전에 없던 액티비티


def test_diff_without_change_is_empty_not_none():
    prev = (_p("A", 0),)
    assert diff_points(prev, prev) == PointsDiff((), (), ())


def test_first_version_diff_is_none():
    assert diff_points(None, (_p("A", 0),)) is None
    assert diff_points(None, ()) is None
