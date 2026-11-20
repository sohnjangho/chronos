import time
from dataclasses import replace
from datetime import date

import pytest

from app.core.cpm import compute
from app.core.model import Relation, Resource
from app.core.resources import level
from app.core.shorten import MAX_CANDIDATES, Move, apply_moves, candidate_moves, shorten
from tests.core.helpers import act, big_schedule, sched

CHAIN = sched([act("A", 6), act("B", 4), act("C", 5)], [Relation("A", "B"), Relation("B", "C")])   # A 3/1~3/8, B 3/9~3/12, C 3/15~3/19
CRANE = Resource("crane", "타워크레인", "대", 1)
two_crane_sched = replace(
    sched([act("A", 6, resources=("crane",)), act("B", 3, resources=("crane",))], []), resources=(CRANE,)
)


def test_parallel_package_reaches_target_with_one_move():
    a = shorten(CHAIN, target=3).packages[0]
    assert (a.key, [m.id for m in a.moves], a.finish, a.gain, a.reached) == ("A", ["par:A>B"], date(2027, 3, 16), 3, True)
    assert a.moves[0].relation == Relation("A", "B", "SS", 3) and a.moves[0].text == "A 절반 지점에서 B 시작 (FS → SS+3)"


def test_parallel_package_keeps_going_until_no_gain():
    a = shorten(CHAIN, target=10).packages[0]
    assert ([m.id for m in a.moves], a.finish, a.gain, a.reached) == (["par:A>B", "par:B>C"], date(2027, 3, 12), 5, False)


def test_compress_package():
    b = shorten(CHAIN, target=3).packages[1]
    assert ([m.id for m in b.moves], [m.od for m in b.moves], b.finish, b.gain) == (["cmp:A", "cmp:C"], [4, 4], date(2027, 3, 16), 3)


def test_same_moves_are_not_repeated_as_another_package():
    assert [p.key for p in shorten(CHAIN, target=3).packages] == ["A", "B"]          # C 는 A 와 같아 빠짐


def test_add_resource_when_leveling_pushes_critical_work():
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 3, resources=("crane",))], []), resources=(R,))   # 맞춤 뒤 준공 3/8
    r = shorten(s, target=1)
    assert [p.key for p in r.packages] == ["A", "B"] and r.packages[0].moves == ()
    m = r.packages[1].moves[0]
    assert (m.id, m.capacity, r.packages[1].gain, m.text) == ("res:crane", 2, 3, "타워크레인 1대 → 2대")


def test_started_work_is_not_touched():
    s = sched([act("A", 6, actual_start=date(2027, 3, 1)), act("B", 4), act("C", 5)], [Relation("A", "B"), Relation("B", "C")])
    ids = {m.id for p in shorten(s, target=3).packages for m in p.moves}
    assert "par:A>B" not in ids and "cmp:A" not in ids


def test_apply_moves_without_resources_keeps_capacity():
    m = [Move("res:crane", "add_resource", ("A",), "", resource_id="crane", capacity=2), Move("cmp:A", "compress", ("A",), "", od=4)]
    out = apply_moves(two_crane_sched, m, resources=False)
    assert out.resources[0].capacity == 1 and out.activities[0].od == 4


def test_target_must_be_positive():
    with pytest.raises(ValueError):
        shorten(CHAIN, target=0)


def test_two_hundred_activities_shorten_quickly():
    t = time.perf_counter()
    shorten(big_schedule(), target=5)
    assert time.perf_counter() - t < 5.0


# 아래는 brief 밖에서 더한 시험

TWO_CHAINS = sched([act("A", 6), act("B", 4), act("D", 5), act("E", 4)], [Relation("A", "B"), Relation("D", "E")])
# A 3/1~3/8, B 3/9~3/12 (크리티컬) · D 3/1~3/5, E 3/8~3/11 (여유 1일)


def test_next_move_follows_the_new_critical_chain():
    """첫 사슬을 줄이면 둘째 사슬이 크리티컬이 되고, 다음 이동은 둘째 사슬에서 고른다(컨트롤러 판정 11-20)."""
    a = shorten(TWO_CHAINS, target=3).packages[0]
    assert ([m.id for m in a.moves], a.finish, a.gain, a.reached) == (["par:A>B", "par:D>E"], date(2027, 3, 9), 3, True)
    first, second = a.moves
    assert (first.critical_before, first.critical_after) == (("A", "B"), ("D", "E"))
    assert (second.critical_before, second.critical_after) == (("D", "E"), ("A", "B", "D", "E"))


def test_critical_paths_do_not_change_move_equality():
    m = Move("cmp:A", "compress", ("A",), "", od=4)
    assert replace(m, critical_before=("A",), critical_after=("B",)) == m


def test_compress_rounds_the_cut_up_exactly():
    s = sched([act("A", 35), act("B", 5), act("C", 4)], [Relation("A", "B"), Relation("B", "C")])
    lv = level(s, compute(s))
    cuts = {m.id: m.od for m in candidate_moves(s, lv) if m.kind == "compress"}
    assert cuts == {"cmp:A": 28, "cmp:B": 4}                       # 35 − 7, 5 − 1. 4일은 줄이지 않는다


def test_candidates_are_the_earliest_critical_work_up_to_the_limit():
    s = sched([act(f"T{k:02d}", 5) for k in range(20)], [Relation(f"T{k:02d}", f"T{k + 1:02d}") for k in range(19)])
    lv = level(s, compute(s))
    moves = candidate_moves(s, lv)
    assert len(moves) == MAX_CANDIDATES
    assert [m.id for m in moves[:3]] == ["cmp:T00", "par:T00>T01", "cmp:T01"]     # ES, 액티비티 id, 이동 id 순


def test_apply_moves_changes_relation_duration_and_capacity():
    s = replace(sched([act("A", 6, resources=("crane",)), act("B", 4)], [Relation("A", "B")]), resources=(CRANE,))
    m = [
        Move("par:A>B", "parallel", ("A", "B"), "", relation=Relation("A", "B", "SS", 3)),
        Move("cmp:B", "compress", ("B",), "", od=3),
        Move("res:crane", "add_resource", ("A",), "", resource_id="crane", capacity=2),
    ]
    out = apply_moves(s, m)
    assert (out.relations, out.activities[1].od, out.resources[0].capacity) == ((Relation("A", "B", "SS", 3),), 3, 2)


RESOURCE_CHAIN = replace(
    sched([act("A", 6), act("B", 4, resources=("crane",)), act("C", 4, resources=("crane",))],
          [Relation("A", "B"), Relation("A", "C")]),
    resources=(CRANE,),
)   # 맞춤: A 3/1~3/8, B 3/9~3/12, C 는 크레인을 기다려 3/15~3/18


def _leveled_finish(s, m):
    out = apply_moves(s, [m])
    return level(out, compute(out)).finish


def test_parallel_on_resource_driven_chain_after_leveling():
    """Fix 1: 맞춘 일정의 크리티컬은 C 하나라 A 는 빠지지만, A 에서 갈라지는 병행도 후보가 되어 준공이 당겨진다."""
    lv = level(RESOURCE_CHAIN, compute(RESOURCE_CHAIN))
    assert (lv.cpm.critical_path, lv.shifted, lv.finish) == (("C",), ("C",), date(2027, 3, 18))
    assert {m.id for m in candidate_moves(RESOURCE_CHAIN, lv) if m.kind == "parallel"} == {"par:A>B", "par:A>C"}
    a = shorten(RESOURCE_CHAIN, target=3).packages[0]
    assert (len(a.moves), a.finish, a.gain, a.reached) == (1, date(2027, 3, 15), 3, True)


def test_unshifted_move_is_rechecked_and_wins_an_equal_gain_by_id():
    """Fix 2: par:A>B 는 A·B 가 밀리지 않아 어림 이득이 0 이지만 다시 맞추면 par:A>C 와 같은 3일. 같으면 id 순."""
    lv = level(RESOURCE_CHAIN, compute(RESOURCE_CHAIN))
    assert not {"A", "B"} & set(lv.shifted)
    real = {m.id: _leveled_finish(RESOURCE_CHAIN, m) for m in candidate_moves(RESOURCE_CHAIN, lv) if m.kind == "parallel"}
    assert real == {"par:A>B": date(2027, 3, 15), "par:A>C": date(2027, 3, 15)}
    m = shorten(RESOURCE_CHAIN, target=3).packages[0].moves[0]
    assert (m.id, m.relation, m.critical_before, m.critical_after) == ("par:A>B", Relation("A", "B", "SS", 3), ("C",), ("C",))


def test_max_moves_stops_the_package():
    a = shorten(CHAIN, target=10, max_moves=1).packages[0]
    assert ([m.id for m in a.moves], a.gain, a.reached) == (["par:A>B"], 3, False)


def test_equal_gains_prefer_parallel_then_add_resource_then_compress():
    s = replace(
        sched([act("W", 1), act("S", 5, resources=("crane",)), act("P", 4), act("Q", 6), act("K", 3, resources=("crane",))],
              [Relation("W", "S"), Relation("S", "P"), Relation("P", "Q")]),
        resources=(CRANE,),
    )   # 맞춤: K 가 크레인을 먼저 써서 S 3/4~3/10, P 3/11~3/16, Q 3/17~3/24
    lv = level(s, compute(s))
    first = {m.id for m in candidate_moves(s, lv) if _leveled_finish(s, m) == date(2027, 3, 22)}
    assert first == {"par:P>Q", "par:S>P", "res:crane", "cmp:Q"}          # 첫 단계는 넷 다 이득 2
    _, b, c = shorten(s, target=8).packages
    assert b.moves[0].id == "res:crane"                                   # add_resource < compress
    assert [m.id for m in c.moves] == ["par:P>Q", "par:S>P", "res:crane", "cmp:Q"]   # parallel(같으면 id) 이 먼저
    assert (c.finish, c.gain, c.reached) == (date(2027, 3, 12), 8, True)
