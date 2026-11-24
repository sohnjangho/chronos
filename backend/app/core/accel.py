"""당김 효과(계획 5 F, 「당겨도 소용 있나」): 이동 묶음이 당긴 일수 가운데 준공에 반영된 일수와, 넣은 뒤 약속을 정하는 줄.

계산은 기존 엔진만 쓴다 — `apply_moves` → `compute` → `level(shift=True)` 로 넣기 전·뒤 준공을 구한다. 판단은 없다.

당긴 일수(pulled_days) = 묶음의 이동을 차례대로 넣으며 센 일수의 합
- compress: 그때까지의 od − 새 od.
- parallel: 넣기 전 크리티컬 사슬에서 그 관계가 후행을 당기는 일수 = 선행 od − SS lag(0 아래면 0)
  (FS 0 이면 후행은 선행이 끝난 뒤, SS+lag 면 선행 시작 lag 일 뒤에 시작한다). 선행 od 는 같은 묶음에서 앞서 넣은
  압축을 반영한 값이다(압축한 일수를 병행에서 다시 세지 않는다).
- add_resource: 0 으로 센다(기간을 줄이지 않는다). 이 이동만 있는 묶음은 finish_gain 만 본다 —
  ratio 는 준공이 당겨지면 1.0, 아니면 0.0.
반영 일수(finish_gain) = 넣기 전 준공 → 넣은 뒤 준공의 근무일(받은 일정의 달력, 단축안의 이득과 같은 셈).
ratio = finish_gain / pulled_days, warn = ratio < warn_ratio(같으면 경고하지 않는다). 준공이 늦어지면 finish_gain·ratio 는
음수 그대로 둔다(맞춤의 우선순위가 바뀌어 늦어질 수 있다). 압축과 자원 추가를 함께 넣으면 ratio 가 1 을 넘을 수 있다.

다음 결정 줄(next_chain) = 넣은 뒤 맞춘 일정의 크리티컬 패스(위상 순) 가운데 묶음이 건드리지 않은 task(끝난 것 제외).
same_chain = 넣기 전 크리티컬 패스에 같은 규칙을 쓴 줄과 같다(같은 줄이 계속 약속을 정한다).
next_chain_points = 그 가운데 넣은 뒤 일정의 관리 포인트(`compute_points`)인 것.
한계: 크리티컬은 맞춘 일정(`level(...).cpm`)의 것이라 맞춤이 둔 `pinned_start` 앞에서 사슬이 끊긴다 — 자원 때문에 밀린
작업부터 뒤만 보인다. 나란한 크리티컬 갈래가 여럿이면 한 줄로 이어지지 않고 위상 순으로 섞여 나온다.

만약에 복사본(`derive_moves`): 복사본과 그 바탕 버전을 조건까지 넣은 일정으로 견줘 이동을 끌어낸다 — 같은 id 의 od 가
줄면 compress, 같은 (선행, 후행)의 FS 0 이 SS(+lag)가 되면 parallel, 자원 용량이 늘면(입력 조건 resource_cap)
add_resource. 그 밖의 바뀜(작업·관계·자원이 늘거나 빠짐, od 가 늚, lag·관계 종류의 다른 바뀜, 다른 칸, 시작·달력·
Data Date)이 당김과 함께 있으면 None — 화면에는 `MIXED_REASON`. 당김이 하나도 없으면 ()(당김 효과 없음).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.model import Schedule
from app.core.points import compute_points
from app.core.resources import LevelResult, level
from app.core.shorten import Move, apply_moves

MIXED_REASON = "여러 가지를 함께 바꿔 당김 효과를 따로 셀 수 없습니다"


class AccelRefused(ValueError):
    """당길 수 없는 요청(없는 작업·마일스톤·실적 있음·더 줄일 기간 없음). 메시지는 사용자에게 그대로 보인다."""


@dataclass(frozen=True)
class AccelResult:
    pulled_days: int
    finish_before: date
    finish_after: date
    finish_gain: int
    ratio: float
    warn: bool
    next_chain: tuple[str, ...]  # 액티비티 id, 위상 순
    next_chain_points: tuple[str, ...]  # next_chain 가운데 관리 포인트(같은 차례)
    same_chain: bool


def pull_request(schedule: Schedule, activity_id: str, days: int) -> Sequence[Move]:
    """「〔작업〕을 days 일 당기면?」 — 그 작업 od 를 days 만큼 줄이는 압축 하나(최소 1, 관계는 그대로)."""
    a = next((a for a in schedule.activities if a.id == activity_id), None)
    if a is None:
        raise AccelRefused(f"작업을 찾을 수 없습니다: {activity_id}")
    if a.kind != "task":
        raise AccelRefused(f"{a.name} 은(는) 마일스톤이라 당길 기간이 없습니다.")
    if a.actual_start is not None or a.actual_finish is not None:
        raise AccelRefused(f"{a.name} 은(는) 실적이 있어 당길 수 없습니다.")
    if a.od <= 1:
        raise AccelRefused(f"{a.name} 은(는) 기간이 {a.od}일이라 더 줄일 수 없습니다.")
    od = max(1, a.od - days)
    return (Move(f"cmp:{a.id}", "compress", (a.id,), f"{a.name} 기간 {a.od}일 → {od}일", od=od),)


def _pulled(schedule: Schedule, moves: Sequence[Move]) -> int:
    """차례대로 센다. 병행의 선행 od 는 앞서 넣은 압축 뒤의 값."""
    ods = {a.id: a.od for a in schedule.activities}
    total = 0
    for m in moves:
        if m.kind == "compress":
            i = m.activity_ids[0]
            total += ods[i] - m.od
            ods[i] = m.od
        elif m.kind == "parallel":
            total += max(0, ods[m.relation.pred] - m.relation.lag)
    return total


def _chain(schedule: Schedule, lv: LevelResult, touched: set[str]) -> tuple[str, ...]:
    acts = {a.id: a for a in schedule.activities}
    return tuple(i for i in lv.cpm.critical_path
                 if i not in touched and acts[i].kind == "task" and acts[i].actual_finish is None)


def accel_effect(
    schedule: Schedule, moves: Sequence[Move], *, warn_ratio: float, tf_days: int, window_weeks: int
) -> AccelResult:
    """schedule(조건을 넣은 일정)에 moves 를 넣기 전·뒤를 맞춰 견준다. tf_days·window_weeks 는 관리 포인트 설정값."""
    before = level(schedule, compute(schedule), shift=True)
    after_schedule = apply_moves(schedule, moves)
    after = level(after_schedule, compute(after_schedule), shift=True)
    gain = WorkCalendar(schedule.calendar).workdays_between(after.finish, before.finish)
    pulled = _pulled(schedule, moves)
    ratio = gain / pulled if pulled > 0 else (1.0 if gain > 0 else 0.0)
    touched = {i for m in moves for i in m.activity_ids}
    chain = _chain(after_schedule, after, touched)
    points = {p.activity_id for p in compute_points(after_schedule, after.cpm, tf_days=tf_days,
                                                    window_weeks=window_weeks)}
    return AccelResult(
        pulled_days=pulled, finish_before=before.finish, finish_after=after.finish, finish_gain=gain,
        ratio=ratio, warn=ratio < warn_ratio, next_chain=chain,
        next_chain_points=tuple(i for i in chain if i in points),
        same_chain=chain == _chain(schedule, before, touched),
    )


def chain_items(schedule: Schedule, result: AccelResult) -> list[dict]:
    """다음 결정 줄을 이름·관리 포인트 표시와 함께 [{activity_id, name, point}](카드·만회안·비교판이 같은 꼴)."""
    names = {a.id: a.name for a in schedule.activities}
    points = set(result.next_chain_points)
    return [{"activity_id": i, "name": names[i], "point": i in points} for i in result.next_chain]


def accel_view(schedule: Schedule, result: AccelResult) -> dict:
    """비교판·복사본 카드의 당김 효과 칸 {pulled_days, finish_gain, warn, next_chain}."""
    return {"pulled_days": result.pulled_days, "finish_gain": result.finish_gain, "warn": result.warn,
            "next_chain": chain_items(schedule, result)}


def _activity_moves(base: Schedule, copy: Schedule) -> tuple[list[Move], bool]:
    """(압축, 그 밖의 바뀜이 있는가)."""
    mine, theirs = {a.id: a for a in base.activities}, {a.id: a for a in copy.activities}
    other = mine.keys() != theirs.keys()
    moves = []
    for i in mine.keys() & theirs.keys():
        a, b = mine[i], theirs[i]
        if replace(b, od=a.od) != a or b.od > a.od:
            other = True
        elif b.od < a.od:
            moves.append(Move(f"cmp:{i}", "compress", (i,), f"{a.name} 기간 {a.od}일 → {b.od}일", od=b.od))
    return sorted(moves, key=lambda m: m.id), other


def _relation_moves(base: Schedule, copy: Schedule) -> tuple[list[Move], bool]:
    """(병행, 그 밖의 바뀜이 있는가). 같은 (선행, 후행)에 관계가 둘 이상이면 셀 수 없다."""
    before = {(r.pred, r.succ): r for r in base.relations}
    after = {(r.pred, r.succ): r for r in copy.relations}
    other = (before.keys() != after.keys() or len(before) != len(base.relations)
             or len(after) != len(copy.relations))
    names = {a.id: a.name for a in base.activities}
    moves = []
    for key in sorted(before.keys() & after.keys()):
        r, new = before[key], after[key]
        if new == r:
            continue
        if (r.type, r.lag) == ("FS", 0) and new.type == "SS" and new.lag >= 0:
            p, q = key
            text = f"{names[p]} 시작 {new.lag}일 뒤 {names[q]} 시작 (FS → SS+{new.lag})"
            moves.append(Move(f"par:{p}>{q}", "parallel", key, text, relation=new))
        else:
            other = True
    return moves, other


def _resource_moves(base: Schedule, copy: Schedule) -> tuple[list[Move], bool]:
    """(자원 추가, 그 밖의 바뀜이 있는가)."""
    caps, new_caps = {r.id: r for r in base.resources}, {r.id: r for r in copy.resources}
    other = caps.keys() != new_caps.keys()
    moves = []
    for i in sorted(caps.keys() & new_caps.keys()):
        r, c = caps[i], new_caps[i]
        if replace(c, capacity=r.capacity) != r or c.capacity < r.capacity:
            other = True
        elif c.capacity > r.capacity:
            text = f"{r.name} {r.capacity}{r.unit} → {c.capacity}{r.unit}"
            moves.append(Move(f"res:{i}", "add_resource", (), text, resource_id=i, capacity=c.capacity))
    return moves, other


def derive_moves(base: Schedule, copy: Schedule) -> tuple[Move, ...] | None:
    """조건을 넣은 바탕 일정과 복사본을 견줘 이동을 끌어낸다(압축 → 병행 → 자원 차례).

    당김(압축·병행·자원 추가)과 그 밖의 바뀜이 함께 있으면 None(따로 셀 수 없다). 당김이 없으면 ()
    — 그 밖의 바뀜만 있어도(예: 기간을 늘려 보기) 당김 효과는 없다.
    """
    cmp, a = _activity_moves(base, copy)
    par, b = _relation_moves(base, copy)
    res, c = _resource_moves(base, copy)
    moves = (*cmp, *par, *res)
    other = a or b or c or (base.start, base.calendar, base.data_date) != (copy.start, copy.calendar, copy.data_date)
    if not moves:
        return ()
    return None if other else moves
