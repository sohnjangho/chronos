"""당김 효과(core.accel): 묶음이 당긴 일수 가운데 준공에 반영된 일수와 다음에 약속을 정하는 줄. 날짜는 엔진 값만."""

from dataclasses import replace
from datetime import date

import pytest

from app.core.accel import AccelRefused, accel_effect, pull_request
from app.core.cpm import compute
from app.core.model import Relation, Resource
from app.core.shorten import Move, apply_moves
from tests.core.helpers import act, sched

CHAIN = sched([act("A", 6), act("B", 4), act("C", 5)], [Relation("A", "B"), Relation("B", "C")])  # 준공 3/19
# A 6 → B 4 → D 2 와 나란한 X 9 → D. X 의 여유 1 — B 를 1일 넘게 당기면 X 가 막는다.
SIDE = sched([act("A", 6), act("B", 4), act("X", 9), act("D", 2)],
             [Relation("A", "B"), Relation("B", "D"), Relation("X", "D")])
CRANE = Resource("crane", "타워크레인", "대", 1)
# C 10 은 혼자, A 5·B 5 는 크레인 1대를 나눠 쓴다 — 맞추면 A 다음 B 라 준공은 크레인 줄이 정한다.
CRANED = replace(sched([act("C", 10), act("A", 5, resources=("crane",)), act("B", 5, resources=("crane",))], []),
                 resources=(CRANE,))


def _effect(s, moves, *, ratio=0.5, k=3, w=8):
    return accel_effect(s, moves, warn_ratio=ratio, tf_days=k, window_weeks=w)


def test_pulling_the_only_critical_reaches_the_finish():
    r = _effect(CHAIN, pull_request(CHAIN, "C", 2))
    assert (r.pulled_days, r.finish_before, r.finish_after, r.finish_gain) == (2, date(2027, 3, 19), date(2027, 3, 17), 2)
    assert (r.ratio, r.warn) == (1.0, False)
    assert r.next_chain == ("A", "B") and r.same_chain is True  # 같은 줄이 계속 약속을 정한다


def test_parallel_path_blocks_soon_partial_and_warns():
    r = _effect(SIDE, pull_request(SIDE, "B", 3))
    assert (r.pulled_days, r.finish_gain, r.warn) == (3, 1, True)
    assert r.ratio == pytest.approx(1 / 3)
    assert r.next_chain == ("X", "D") and r.same_chain is False  # 다음 결정 줄은 X → D


def test_next_chain_marks_management_points():
    r = _effect(SIDE, pull_request(SIDE, "B", 3), w=1)  # 창 1주(3/1~3/8): X 는 포인트, D(3/12 시작)는 아니다
    assert r.next_chain_points == ("X",)
    assert _effect(SIDE, pull_request(SIDE, "B", 3)).next_chain_points == ("X", "D")


def test_blocked_by_resource_leveling():
    moves = pull_request(CRANED, "C", 3)
    assert compute(apply_moves(CRANED, moves)).finish < compute(CRANED).finish  # 맞추지 않으면 당겨지는 것처럼 보인다
    r = _effect(CRANED, moves)
    assert (r.pulled_days, r.finish_gain, r.ratio, r.warn) == (3, 0, 0.0, True)
    assert r.next_chain == ("B",)  # 크레인 줄이 약속을 정한다


def test_ratio_equal_to_warn_ratio_does_not_warn():
    r = _effect(SIDE, pull_request(SIDE, "B", 2))  # 2일 당김 → 준공 1일
    assert (r.pulled_days, r.finish_gain, r.ratio) == (2, 1, 0.5)
    assert r.warn is False
    assert _effect(SIDE, pull_request(SIDE, "B", 2), ratio=0.6).warn is True


def test_parallel_counts_overlap_days_and_add_resource_counts_zero():
    par = Move("par:A>B", "parallel", ("A", "B"), "", relation=Relation("A", "B", "SS", 3))
    r = _effect(CHAIN, [par])
    assert (r.pulled_days, r.finish_gain) == (3, 3)  # A 6일 − SS 3 = B 가 3일 앞선다
    res = Move("res:crane", "add_resource", ("B",), "", resource_id="crane", capacity=2)
    r = _effect(CRANED, [res])
    assert (r.pulled_days, r.finish_gain, r.ratio, r.warn) == (0, 0, 0.0, True)  # 준공은 C 10일이 정한다
    lone = replace(CRANED, activities=CRANED.activities[1:])  # C 없이 크레인 줄만
    r = _effect(lone, [res])
    assert (r.pulled_days, r.finish_gain, r.ratio, r.warn) == (0, 5, 1.0, False)


def test_pull_request_shortens_od_to_at_least_one():
    (m,) = pull_request(CHAIN, "B", 10)
    assert (m.kind, m.activity_ids, m.od) == ("compress", ("B",), 1)
    assert _effect(CHAIN, [m]).pulled_days == 3


def test_pull_request_refuses_started_or_unknown_work():
    started = sched([act("A", 6, actual_start=date(2027, 3, 1)), act("B", 4)], [Relation("A", "B")])
    with pytest.raises(AccelRefused):
        pull_request(started, "A", 2)
    done = sched([act("A", 6, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 8))], [])
    with pytest.raises(AccelRefused):
        pull_request(done, "A", 1)
    with pytest.raises(AccelRefused):
        pull_request(CHAIN, "Z", 1)
    with pytest.raises(AccelRefused):
        pull_request(sched([act("A", 1)], []), "A", 1)  # 더 줄일 기간이 없다
