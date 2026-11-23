"""승인 판단: 에이전트가 낸 변경(첫 저장·일정 고침)을 사람이 승인해야 하는지 코드가 정한다.

비교하는 것은 입력이 아니라 계산한 결과다. 양쪽 일정에 저장할 조건을 넣고(`prepare_stored`, 화면·점검과 같은
준비) 경로 계산·자원 맞춤을 한 날짜(`store.schedules.run`)로 본다.

사유(Reason)
- first_save: 새 일정(before 가 None). 이때 다른 비교는 하지 않는다(위반만 함께 본다).
- finish_changed: 준공일이 다르다. milestone_changed: 마일스톤({id: 종료일})이 다르다(더함·없앰 포함).
- critical_path_changed: 크리티컬 액티비티 id 의 모음이 다르다.
- condition_violated: 점검 보고서에 위반이 있다.
- condition_changed: 조립한 조건 가운데 켜진 것의 {id: (종류, params)} 가 다르다(글만 바뀐 것은 아니다).
- structure_changed: 액티비티나 관계(선행·후행 짝)가 없어졌거나, WBS 코드가 없어지거나 상위가 바뀌었거나,
  남은 액티비티의 WBS 가 바뀌었다. 더하기만 한 것은 구조 변경이 아니다.
- rule_save·plan_reset: 뒤 계획에서 쓴다. 여기서는 만들지 않는다.
사유가 없으면 바뀐 날짜가 여유 안에서 흡수된 것이다.

승인 수준(mode): important = 사유가 하나라도 있으면 승인, all = 늘 승인, auto = 위반(condition_violated)만 승인.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult
from app.core.model import Schedule
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.checks import CheckReport
from app.harness.conditions import Condition, condition_problem, read_conditions
from app.store.diff import pred_json
from app.store.drafts import violation_json
from app.store.schedules import activity_json, run

Reason = Literal["first_save", "finish_changed", "milestone_changed", "critical_path_changed",
                 "condition_violated", "condition_changed", "structure_changed", "plan_reset", "rule_save",
                 "field_report"]  # field_report: 현장 관리자가 올린 건(승인 수준과 상관없이 기다린다, proposals.propose)
Mode = Literal["all", "important", "auto"]
REASONS: tuple[str, ...] = get_args(Reason)  # 사유는 이 차례로 낸다
MODES: tuple[str, ...] = get_args(Mode)


@dataclass(frozen=True)
class Decision:
    needs_approval: bool
    reasons: list[Reason]


@dataclass(frozen=True)
class Assessment:
    """판단과 승인함 화면에 보일 것: summary(요약)·diff(바뀌는 액티비티). 모양은 assess 의 docstring."""

    decision: Decision
    summary: dict
    diff: list[dict]


@dataclass(frozen=True)
class _Side:
    """한쪽(바꾸기 전·후) 일정의 계산 결과."""

    schedule: Schedule  # 저장할 일정 그대로(조건을 넣기 전)
    conditions: list[Condition]  # 기본 규칙과 조립한 목록
    calendar: WorkCalendar  # 조건을 넣은 달력
    cpm: CpmResult  # 화면 날짜(조건 넣기 + 경로 계산 + 자원 맞춤)


def _side(schedule: Schedule, stored: list[dict]) -> _Side:
    ready = prepare_stored(schedule, stored)
    # 형식이 맞는 조건만 비교·요약에 쓴다(틀린 조건은 일정에도 들어가지 않는다 — apply_to_schedule 과 같은 거름)
    conditions = [c for c in assemble_all(read_conditions(stored)[0]) if condition_problem(c) is None]
    return _Side(schedule, conditions, WorkCalendar(ready.calendar), run(ready))


def decide(before: Schedule | None, after: Schedule, before_conditions: list[dict], after_conditions: list[dict],
           report: CheckReport, *, mode: Mode = "important") -> Decision:
    """승인이 필요한지와 그 사유. 조건은 저장된 dict 목록. 깨진 일정이면 ScheduleError(부르는 쪽이 먼저 확인)."""
    return assess(before, after, before_conditions, after_conditions, report, mode=mode).decision


def assess(before: Schedule | None, after: Schedule, before_conditions: list[dict], after_conditions: list[dict],
           report: CheckReport, *, mode: Mode = "important") -> Assessment:
    """decide 와 같은 판단에 화면 요약과 차이를 더한다(날짜는 'YYYY-MM-DD', JSON 그대로 저장할 수 있다).

    summary = {finish: {before, after, delta_days}, critical: {before_count, after_count, path_changed},
               conditions_changed: [{id, name, before, after}], changed_count,
               check: {passed, violations: [{condition_id, message, activity_ids, amount}], uncheckable, invalid},
               finish_float: {before, after}}
    - delta_days: 달력 날 수(앞당기면 음수). finish_float: 준공 → 가장 이른 켜진 finish_by 기한의 근무일 수(없으면 None).
    - check.passed 는 점검한 조건만 센다. 자동 점검이 안 되는 조건은 uncheckable 로 따로 센다.
    - 첫 저장이면 before 쪽 값은 None, conditions_changed 는 [], path_changed 는 False.
    diff = [{activity_id, name, before: {start, finish} | None, after: {…} | None, finish_delta}] — 바뀐(날짜·입력·선행)
    액티비티만, id 순. finish_delta 는 종료일의 달력 날 수 차이(한쪽에만 있으면 None).
    """
    new = _side(after, after_conditions)
    old = _side(before, before_conditions) if before is not None else None
    reasons = _reasons(old, new, report)
    diff = _diff(old, new)
    return Assessment(Decision(_needs(mode, reasons), reasons), _summary(old, new, report, diff), diff)


# ── 사유 ────────────────────────────────────────────────────────────


def _needs(mode: Mode, reasons: list[Reason]) -> bool:
    if mode == "all":
        return True
    if mode == "auto":
        return "condition_violated" in reasons
    return bool(reasons)


def _critical(side: _Side) -> set[str]:
    return {i for i, row in side.cpm.rows.items() if row.critical}


def _milestones(side: _Side) -> dict[str, date]:
    return {a.id: side.cpm.rows[a.id].ef for a in side.schedule.activities if a.kind != "task"}


def _enabled(side: _Side) -> dict[str, tuple]:
    return {c.id: (c.kind, c.params) for c in side.conditions if c.enabled}


def _structure_changed(old: Schedule, new: Schedule) -> bool:
    wbs_of = {a.id: a.wbs for a in new.activities}
    pairs = {(r.pred, r.succ) for r in new.relations}
    tree = {w.code: w.parent for w in new.wbs}
    return (
        any(a.id not in wbs_of or wbs_of[a.id] != a.wbs for a in old.activities)
        or any((r.pred, r.succ) not in pairs for r in old.relations)
        or any(w.code not in tree or tree[w.code] != w.parent for w in old.wbs)
    )


def _reasons(old: _Side | None, new: _Side, report: CheckReport) -> list[Reason]:
    found: set[str] = {"condition_violated"} if report.violations else set()
    if old is None:
        found.add("first_save")
    else:
        checks = {
            "finish_changed": old.cpm.finish != new.cpm.finish,
            "milestone_changed": _milestones(old) != _milestones(new),
            "critical_path_changed": _critical(old) != _critical(new),
            "condition_changed": _enabled(old) != _enabled(new),
            "structure_changed": _structure_changed(old.schedule, new.schedule),
        }
        found |= {reason for reason, hit in checks.items() if hit}
    return [r for r in REASONS if r in found]


# ── 요약·차이 ───────────────────────────────────────────────────────


def _dates(side: _Side | None, aid: str) -> dict | None:
    if side is None or aid not in side.cpm.rows:
        return None
    row = side.cpm.rows[aid]
    return {"start": row.es.isoformat(), "finish": row.ef.isoformat()}


def _inputs(side: _Side | None) -> dict[str, tuple]:
    """액티비티마다 (입력 칸, 선행 관계) — 날짜가 그대로여도 이것이 다르면 바뀐 것이다."""
    if side is None:
        return {}
    preds: dict[str, list[dict]] = {}
    for r in side.schedule.relations:
        preds.setdefault(r.succ, []).append(pred_json(r))
    return {a.id: (activity_json(a), preds.get(a.id, [])) for a in side.schedule.activities}


def _diff(old: _Side | None, new: _Side) -> list[dict]:
    names = {a.id: a.name for a in (*(old.schedule.activities if old else ()), *new.schedule.activities)}
    old_inputs, new_inputs = _inputs(old), _inputs(new)
    rows = []
    for aid in sorted(names):
        before, after = _dates(old, aid), _dates(new, aid)
        if before == after and old_inputs.get(aid) == new_inputs.get(aid):
            continue
        delta = None
        if before and after:
            delta = (date.fromisoformat(after["finish"]) - date.fromisoformat(before["finish"])).days
        rows.append({"activity_id": aid, "name": names[aid], "before": before, "after": after, "finish_delta": delta})
    return rows


def _finish_float(side: _Side | None) -> int | None:
    if side is None:
        return None
    dues = [date.fromisoformat(c.params["date"]) for c in side.conditions if c.enabled and c.kind == "finish_by"]
    return side.calendar.workdays_between(side.cpm.finish, min(dues)) if dues else None


def _label(c: Condition, schedule: Schedule) -> str:
    if c.kind == "resource_cap":
        return next((r.name for r in schedule.resources if r.id == c.params["resource_id"]), c.params["resource_id"])
    return c.text


def _value(c: Condition, schedule: Schedule) -> str:
    """조건 값을 짧은 한국어로(조건 변화 줄의 '전 → 후')."""
    p = c.params
    if c.kind == "resource_cap":
        unit = next((r.unit for r in schedule.resources if r.id == p["resource_id"]), "")
        return f"{p['capacity']}{unit}"
    if c.kind in ("finish_by", "start_after"):
        return p["date"]
    if c.kind == "milestone_by":
        return f"{p['activity_id']} {p['date']}"
    if c.kind == "calendar":
        return f"주 {p['days_per_week']}일"
    if c.kind == "blocked_period":
        (m1, d1), (m2, d2) = p["start_md"], p["end_md"]
        return f"{m1}.{d1}~{m2}.{d2}"
    if c.kind in ("min_gap", "max_duration"):
        return f"{p['days']}일"
    return c.text


def _condition_changes(old: _Side, new: _Side) -> list[dict]:
    before = {c.id: c for c in old.conditions if c.enabled}
    after = {c.id: c for c in new.conditions if c.enabled}
    rows = []
    for cid in sorted(before.keys() | after.keys()):
        b, a = before.get(cid), after.get(cid)
        if b and a and (b.kind, b.params) == (a.kind, a.params):
            continue
        shown = (a, new.schedule) if a else (b, old.schedule)
        rows.append({"id": cid, "name": _label(*shown),
                     "before": _value(b, old.schedule) if b else None,
                     "after": _value(a, new.schedule) if a else None})
    return rows


def _summary(old: _Side | None, new: _Side, report: CheckReport, diff: list[dict]) -> dict:
    return {
        "finish": {
            "before": old.cpm.finish.isoformat() if old else None,
            "after": new.cpm.finish.isoformat(),
            "delta_days": (new.cpm.finish - old.cpm.finish).days if old else None,
        },
        "critical": {
            "before_count": len(_critical(old)) if old else None,
            "after_count": len(_critical(new)),
            "path_changed": old is not None and _critical(old) != _critical(new),
        },
        "conditions_changed": _condition_changes(old, new) if old else [],
        "changed_count": len(diff),
        "check": {
            "passed": len(report.passed),
            "violations": [violation_json(v) for v in report.violations],
            "uncheckable": len(report.uncheckable),
            "invalid": len(report.invalid),
        },
        "finish_float": {"before": _finish_float(old), "after": _finish_float(new)},
    }
