"""단축안(만회안) 계산. 받은 일정을 바꾸지 않고, 줄이는 이동을 골라 묶음 셋을 만든다.

받는 일정
- 조건을 넣은 일정 그대로다(지연을 넣은 일정이면 그것이 기준이다). 기준 준공은 이 일정을
  `level(shift=True)` 한 값이다.

병행·압축을 볼 액티비티(후보 범위)
- 맞춘 일정의 크리티컬(`lv.cpm`) ∪ 맞추기 전 크리티컬(`compute(schedule)`) ∪ 맞춤에서 밀린 것
  (`lv.shifted`). 자원을 맞춘 일정은 `pinned_start` 앞에서 크리티컬이 끊겨 `lv.cpm` 만으로는
  준공을 정하는 자원 사슬이 빠지기 때문이다(컨트롤러 판정 11-20).

이동 세 가지(실적이 있는 액티비티는 건드리지 않는다)
- parallel(병행): FS lag 0 관계에서 선행·후행 모두 후보 범위의 task, 선행 od ≥ 4 →
  `Relation(선행, 후행, "SS", ceil(선행 od / 2))`.
- compress(압축): 후보 범위의 task, od ≥ 5 → `od − ceil(od × 0.2)`. 액티비티마다 한 번.
- add_resource(자원 추가): 용량 ≥ 1 인 자원을 쓰는 액티비티가 맞춤에서 밀렸고(`shifted`)
  `lv.cpm` 에서 크리티컬이면 → 용량 + 1.
- 병행·압축 후보는 (첫 액티비티의 ES, 그 id, 이동 id) 순으로 `MAX_CANDIDATES` 개(묶음이 허용한
  종류, 이미 넣은 id 는 뺀 뒤 센다). 자원 추가 후보는 자원마다 하나라 그 수와 따로 뒤에 붙인다.

고르기(묶음마다 따로)
- 지금 일정의 후보마다 이득(근무일, 지금 준공 − 넣은 뒤 준공)을 어림한다. parallel·compress 는
  맞춤 고정(`pinned_start`)을 둔 `lv.schedule` 에 넣고 `compute` 만, add_resource 는 `level` 까지.
- 이득이 큰 것부터(같으면 parallel < add_resource < compress, 그다음 id) `level` 까지 다시
  계산해 실제 이득 > 0 인 첫 후보를 넣는다. 어림 이득 ≤ 0 인 후보는, 그 액티비티가 하나도
  `lv.shifted` 에 없으면 다시 계산하지 않고 버린다(밀린 작업은 다시 맞춰야 줄어들 수 있다).
- 넣은 뒤에는 다시 맞춘 일정의 새 크리티컬 패스·후보 범위에서 후보를 다시 만든다(이전
  후보는 버린다). 이동마다 넣기 전·뒤 크리티컬 패스를 적는다.
- 누적 실제 이득 ≥ target, 이동 수 = max_moves, 이득 있는 후보 없음 가운데 하나면 멈춘다.
- 같은 이동 집합의 일정은 한 번만 맞춘다(묶음끼리 나눠 쓴다).

묶음
- `finish`·`gain` 은 최종 일정을 `level(shift=True)` 한 값, `reached = gain >= target`.
- 앞 묶음과 이동 집합이 같은 뒤 묶음은 뺀다. 이동이 없는 묶음은 남긴다.

`apply_moves` 는 받은 일정에 이동을 넣는다. 저장용 원본에는 `resources=False`(관계·기간만).
`lv.schedule`(맞춤 임시 값)에 넣은 결과는 어림에만 쓰고 저장하지 않는다.
"""

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from fractions import Fraction
from typing import Literal

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.model import Activity, Relation, Schedule
from app.core.resources import LevelResult, level

MoveKind = Literal["parallel", "compress", "add_resource"]


@dataclass(frozen=True)
class Move:
    id: str
    kind: MoveKind
    activity_ids: tuple[str, ...]
    text: str
    relation: Relation | None = None  # parallel: 바꾼 뒤 관계(pred, succ, "SS", lag)
    od: int | None = None  # compress: 새 기간
    resource_id: str | None = None  # add_resource: 자원 id
    capacity: int | None = None  # add_resource: 새 용량
    # 넣기 전·뒤 크리티컬 패스(위상 순). 묶음이 넣은 이동에만 있다. 같은 이동인지 견줄 때는 보지 않는다.
    critical_before: tuple[str, ...] = field(default=(), compare=False)
    critical_after: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class Package:
    key: Literal["A", "B", "C"]
    name: str
    moves: tuple[Move, ...]
    finish: date
    gain: int
    reached: bool


@dataclass(frozen=True)
class ShortenResult:
    base_finish: date
    target: int
    packages: tuple[Package, ...]


PACKAGES = (
    ("A", "병행 우선", frozenset({"parallel"})),
    ("B", "압축·자원 추가", frozenset({"compress", "add_resource"})),
    ("C", "섞음", frozenset({"parallel", "compress", "add_resource"})),
)
COMPRESS_RATIO = 0.2
COMPRESS_MIN_OD = 5
PARALLEL_MIN_OD = 4
MAX_MOVES = 6
MAX_CANDIDATES = 12

_ALL_KINDS = frozenset({"parallel", "compress", "add_resource"})
_RANK = {"parallel": 0, "add_resource": 1, "compress": 2}  # 이득이 같을 때 앞서는 순서


def _pool(schedule: Schedule, lv: LevelResult) -> set[str]:
    """병행·압축 후보 범위: 맞춘 크리티컬 ∪ 맞추기 전 크리티컬 ∪ 맞춤에서 밀린 것."""
    return set(lv.cpm.critical_path) | set(compute(schedule).critical_path) | set(lv.shifted)


def _free(a: Activity, pool: set[str]) -> bool:
    """후보 범위에 있고 실적이 없는 task."""
    no_actual = a.actual_start is None and a.actual_finish is None
    return a.kind == "task" and no_actual and a.id in pool


def _parallel_moves(schedule: Schedule, pool: set[str]) -> Iterator[Move]:
    acts = {a.id: a for a in schedule.activities}
    for r in schedule.relations:
        p, s = acts[r.pred], acts[r.succ]
        if (r.type, r.lag) != ("FS", 0) or p.od < PARALLEL_MIN_OD or not (_free(p, pool) and _free(s, pool)):
            continue
        lag = math.ceil(p.od / 2)
        text = f"{p.name} 절반 지점에서 {s.name} 시작 (FS → SS+{lag})"
        yield Move(f"par:{p.id}>{s.id}", "parallel", (p.id, s.id), text, relation=Relation(p.id, s.id, "SS", lag))


def _compress_moves(schedule: Schedule, pool: set[str]) -> Iterator[Move]:
    ratio = Fraction(str(COMPRESS_RATIO))  # 0.2 × 35 같은 소수 오차 없이 올림한다
    for a in schedule.activities:
        if a.od >= COMPRESS_MIN_OD and _free(a, pool):
            od = a.od - math.ceil(a.od * ratio)
            text = f"{a.name} 기간 {a.od}일 → {od}일 (작업 시간을 늘림)"
            yield Move(f"cmp:{a.id}", "compress", (a.id,), text, od=od)


def _resource_moves(schedule: Schedule, lv: LevelResult) -> Iterator[Move]:
    shifted = set(lv.shifted)
    rows = lv.cpm.rows
    for r in schedule.resources:
        if r.capacity < 1:
            continue
        users = sorted(
            (a.id for a in schedule.activities
             if a.id in shifted and a.od > 0 and r.id in a.resources and rows[a.id].critical),
            key=lambda i: (rows[i].es, i),
        )
        if users:
            text = f"{r.name} {r.capacity}{r.unit} → {r.capacity + 1}{r.unit}"
            yield Move(f"res:{r.id}", "add_resource", tuple(users), text, resource_id=r.id, capacity=r.capacity + 1)


def _candidates(
    schedule: Schedule, lv: LevelResult, kinds: frozenset[str], used: set[str]
) -> list[Move]:
    """kinds 종류이고 used 에 없는 후보.

    병행·압축은 (첫 액티비티의 ES, 그 id, 이동 id) 순으로 MAX_CANDIDATES 개. 자원 추가는 자원마다
    하나뿐이라 그 수에 넣지 않고 뒤에 붙인다(밀린 작업이 많으면 앞자리에서 밀려나지 않게).
    """
    pool = _pool(schedule, lv)
    moves = [
        m
        for m in (*_parallel_moves(schedule, pool), *_compress_moves(schedule, pool))
        if m.kind in kinds and m.id not in used
    ]
    moves.sort(key=lambda m: (lv.cpm.rows[m.activity_ids[0]].es, m.activity_ids[0], m.id))
    extra = [m for m in _resource_moves(schedule, lv) if m.kind in kinds and m.id not in used]
    return moves[:MAX_CANDIDATES] + extra


def candidate_moves(schedule: Schedule, lv: LevelResult) -> list[Move]:
    """모든 종류의 후보(병행·압축 MAX_CANDIDATES 개 + 자원 추가). lv 는 level(schedule, compute(schedule))."""
    return _candidates(schedule, lv, _ALL_KINDS, set())


def apply_moves(schedule: Schedule, moves: Sequence[Move], *, resources: bool = True) -> Schedule:
    """이동을 넣은 일정. resources=False 면 add_resource 는 넣지 않는다(관계·기간만)."""
    rels = list(schedule.relations)
    ods: dict[str, int] = {}
    caps: dict[str, int] = {}
    for m in moves:
        if m.kind == "parallel":
            new = m.relation
            rels = [new if (r.pred, r.succ, r.type, r.lag) == (new.pred, new.succ, "FS", 0) else r for r in rels]
        elif m.kind == "compress":
            ods[m.activity_ids[0]] = m.od
        elif resources:
            caps[m.resource_id] = m.capacity
    return replace(
        schedule,
        activities=tuple(replace(a, od=ods[a.id]) if a.id in ods else a for a in schedule.activities),
        relations=tuple(rels),
        resources=tuple(replace(r, capacity=caps[r.id]) if r.id in caps else r for r in schedule.resources),
    )


class _Search:
    """받은 일정 하나에서 이동 집합마다 맞춘 결과를 한 번만 계산해 둔다."""

    def __init__(self, schedule: Schedule) -> None:
        self._base = schedule
        self._cal = WorkCalendar(schedule.calendar)
        self._levels: dict[frozenset[Move], tuple[Schedule, LevelResult]] = {}

    def state(self, moves: frozenset[Move]) -> tuple[Schedule, LevelResult]:
        """moves 를 넣은 일정(맞춤 고정 없음)과 그 맞춤 결과."""
        if moves not in self._levels:
            s = apply_moves(self._base, sorted(moves, key=lambda m: m.id))
            self._levels[moves] = (s, level(s, compute(s)))
        return self._levels[moves]

    def gain(self, finish: date, before: date) -> int:
        """before 에서 finish 로 당겨진 근무일 수."""
        return self._cal.workdays_between(finish, before)

    def guess(self, done: frozenset[Move], lv: LevelResult, m: Move) -> int:
        """m 을 넣었을 때의 이득 어림. add_resource 만 맞춤까지 한다."""
        if m.kind == "add_resource":
            finish = self.state(done | {m})[1].finish
        else:
            finish = compute(apply_moves(lv.schedule, [m])).finish
        return self.gain(finish, lv.finish)


def _next_move(
    search: _Search, applied: list[Move], lv: LevelResult, kinds: frozenset[str]
) -> tuple[Move, LevelResult] | None:
    """지금 크리티컬 패스에서 실제 이득 > 0 인 가장 좋은 이동과 넣은 뒤 맞춤 결과."""
    done = frozenset(applied)
    schedule, _ = search.state(done)
    cands = _candidates(schedule, lv, kinds, {m.id for m in applied})
    guesses = {m.id: search.guess(done, lv, m) for m in cands}
    shifted = set(lv.shifted)
    for m in sorted(cands, key=lambda m: (-guesses[m.id], _RANK[m.kind], m.id)):
        if guesses[m.id] <= 0 and shifted.isdisjoint(m.activity_ids):
            continue  # 밀리지 않은 작업은 어림대로 줄지 않는다
        after = search.state(done | {m})[1]
        if search.gain(after.finish, lv.finish) > 0:
            return m, after
    return None


def _grow(
    search: _Search, kinds: frozenset[str], target: int, max_moves: int
) -> tuple[tuple[Move, ...], LevelResult]:
    """한 묶음의 이동을 하나씩 넣는다. (넣은 이동, 최종 맞춤 결과)."""
    applied: list[Move] = []
    lv = search.state(frozenset())[1]
    base = lv.finish
    while len(applied) < max_moves and search.gain(lv.finish, base) < target:
        found = _next_move(search, applied, lv, kinds)
        if found is None:
            break
        m, after = found
        applied.append(replace(m, critical_before=lv.cpm.critical_path, critical_after=after.cpm.critical_path))
        lv = after
    return tuple(applied), lv


def shorten(schedule: Schedule, *, target: int, max_moves: int = MAX_MOVES) -> ShortenResult:
    """target 근무일을 줄이는 묶음 A(병행)·B(압축·자원)·C(섞음). 같은 이동 집합의 뒤 묶음은 뺀다."""
    if target < 1:
        raise ValueError("줄일 일수는 1 이상이어야 합니다.")
    search = _Search(schedule)
    base = search.state(frozenset())[1].finish
    packages: list[Package] = []
    for key, name, kinds in PACKAGES:
        moves, lv = _grow(search, kinds, target, max_moves)
        if moves and any(frozenset(moves) == frozenset(p.moves) for p in packages):
            continue
        gain = search.gain(lv.finish, base)
        packages.append(Package(key, name, moves, lv.finish, gain, gain >= target))
    return ShortenResult(base, target, tuple(packages))
