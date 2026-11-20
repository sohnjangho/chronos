"""진행: 공정률·S-커브와 표(WBS·마일스톤·지연·앞으로 3주·CPM 지표).

날짜는 일정 자료(`view_data` — 일정 화면과 같은 계산), 공정률은 core 진행 계산(`app.core.progress`)에서 온다.
근무일은 저장된 조건을 넣은 달력(`prepare_stored`)과 액티비티의 꼬리표로 센다(일정 화면의 지연 일수와 같은 달력).
Data Date 가 없으면 오늘(`context.today()`)을 쓴다. 날짜 d 의 값은 "d 날 아침 = 전날까지 한 일" 이다.
공정률(Plan 선·실적 선·예측 선·SPI·WBS 표)은 Plan 이 있는 액티비티(기준 범위)만, 가중치를 그 안에서 다시 나눠 센다.
그래서 Plan 선은 100% 에 닿는다. Plan 이 계산되지 않은 액티비티는 `added_after_plan` 에 따로 보인다.
"""

from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.agent import context
from app.core.calendar import WorkCalendar
from app.core.cpm import ScheduleError
from app.core.model import Schedule
from app.core.progress import (
    Bar,
    actual,
    curve,
    half_up,
    planned,
    spi,
    start_block,
    weighted,
)
from app.errors import ApiError
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.conditions import duplicated_later, read_conditions
from app.programs.progress.schemas import ProgressOut, Unit
from app.store.messages import SCHEDULE_ERROR_MESSAGES
from app.store.schedules import NotFound, load
from app.store.view import view_data

LOOKAHEAD_DAYS = 20  # 앞으로 볼 날 수(Data Date ~ +20일)
TOP_DELAYS = 5
ONE_DAY = timedelta(days=1)


def _diff(a: float, b: float) -> float:
    return half_up(a - b, 1)


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _bars(view: dict) -> list[Bar]:
    return [
        Bar(
            id=a["id"],
            kind=a["kind"],
            wbs=a["wbs"],
            weight=a["weight"],
            plan_start=a["plan_start"],
            plan_finish=a["plan_finish"],
            start=a["es"],
            finish=a["ef"],
            actual_start=_day(a["actual_start"]),
            actual_finish=_day(a["actual_finish"]),
            progress=a["progress"],
            tags=tuple(a["tags"]),
        )
        for a in view["activities"]
    ]


def _delay(cal: WorkCalendar, b: Bar) -> int:
    """Plan 종료 → 지금 종료의 근무일 수(앞서면 음수). 끝난 것·Plan 없는 것은 0. 일정 화면 status 와 같은 값."""
    if b.actual_finish is not None or b.plan_finish is None:
        return 0
    return cal.workdays_between(b.plan_finish, b.finish, b.tags)


def _length(cal: WorkCalendar, start: date, finish: date, tags: tuple[str, ...]) -> int:
    """[start, finish] 의 근무일 수."""
    return cal.workdays_between(start - ONE_DAY, finish, tags)


def _deadline(stored: list[dict]) -> date | None:
    """켜진 finish_by 가운데 가장 이른 날. 조립(assemble_all) 뒤라 진 조건은 꺼져 있다. 같은 id 의 앞 조건은 뺀다."""
    conditions = assemble_all(read_conditions(stored)[0])
    days = [
        date.fromisoformat(c.params["date"])
        for c, dup in zip(conditions, duplicated_later(conditions), strict=True)
        if c.kind == "finish_by" and c.enabled and not dup
    ]
    return min(days, default=None)


def _finish(view: dict, cal: WorkCalendar, deadline: date | None) -> dict:
    current, plan = view["finish"], view["plan_finish"]
    return {
        "current": current,
        "plan": plan,
        "deadline": deadline,
        "delta": None if plan is None else cal.workdays_between(plan, current),
        "deadline_float": None if deadline is None else cal.workdays_between(current, deadline),
    }


def _counts(tasks: list[Bar], cal: WorkCalendar) -> dict:
    return {
        "total": len(tasks),
        "done": sum(b.actual_finish is not None for b in tasks),
        "in_progress": sum(b.actual_start is not None and b.actual_finish is None for b in tasks),
        "late": sum(_delay(cal, b) > 0 for b in tasks),
    }


def _root(code: str, parents: dict[str, str | None]) -> str | None:
    """WBS 코드의 맨 위 묶음 코드. 없는 코드(또는 끊긴·고리 부모)면 None."""
    seen: set[str] = set()
    while code in parents and parents[code] is not None and code not in seen:
        seen.add(code)
        code = parents[code]
    return code if parents.get(code, "") is None else None


def _wbs(nodes: list[dict], bars: list[Bar], plan_now: dict, actual_now: dict) -> list[dict]:
    """맨 위 WBS 묶음마다 공정률. bars = 기준 범위 막대. 묶음 안에서 가중치를 다시 나눈다(weighted 가 묶음의
    가중치 합으로 나눔). weight = 기준 범위 가중치 가운데 묶음의 몫(소수 4자리)."""
    parents = {n["code"]: n["parent"] for n in nodes}
    total = sum(b.weight for b in bars)
    rows = []
    for n in nodes:
        if n["parent"] is not None:
            continue
        group = [b for b in bars if _root(b.wbs, parents) == n["code"]]
        plan, act = weighted(group, plan_now), weighted(group, actual_now)
        weight = half_up(sum(b.weight for b in group) / total, 4) if total > 0 else 0.0
        rows.append({"code": n["code"], "name": n["name"], "weight": weight, "plan": plan, "actual": act, "diff": _diff(act, plan)})
    return rows


def _milestone_status(b: Bar, delta: int | None) -> str:
    if b.actual_finish is not None:
        return "완료"
    if not delta:
        return "예정"
    return "지연" if delta > 0 else "앞섬"


def _milestones(bars: list[Bar], names: dict[str, str], cal: WorkCalendar) -> list[dict]:
    rows = []
    for b in bars:
        if b.kind == "task":
            continue
        delta = None if b.plan_finish is None else cal.workdays_between(b.plan_finish, b.finish, b.tags)
        rows.append(
            {"id": b.id, "name": names[b.id], "plan": b.plan_finish, "actual_or_forecast": b.finish,
             "delta": delta, "status": _milestone_status(b, delta)}
        )
    return rows


def _top_delays(tasks: list[Bar], acts: dict[str, dict], cal: WorkCalendar) -> list[dict]:
    """늦은 task 를 지연이 큰 순서로(같으면 일정 순서) 최대 5개. 크리티컬이면 준공 영향 = 지연, 아니면 0."""
    late = [(b, d) for b in tasks if (d := _delay(cal, b)) > 0]
    late.sort(key=lambda x: -x[1])
    return [
        {"id": b.id, "name": acts[b.id]["name"], "delay": d, "tf": acts[b.id]["tf"],
         "finish_impact": d if acts[b.id]["critical"] else 0}
        for b, d in late[:TOP_DELAYS]
    ]


def _blocked(starts: list[dict], bars: dict[str, Bar], relations: list[dict], cal: WorkCalendar, data_date: date) -> list[dict]:
    """시작할 task 마다 막는 선행(start_block — 관계 종류·lag)을 까닭별로 묶는다. 예: "선행 미완료: A, C · 선행 미착수: B"."""
    out = []
    for s in starts:
        why: dict[str, list[str]] = {}
        for r in relations:
            if r["succ"] != s["id"]:
                continue
            reason = start_block(cal, bars[r["pred"]], r["type"], r["lag"], data_date, bars[s["id"]].tags)
            if reason and r["pred"] not in why.setdefault(reason, []):
                why[reason].append(r["pred"])
        if why:
            out.append({**s, "reason": " · ".join(f"{k}: {', '.join(ids)}" for k, ids in why.items())})
    return out


def _lookahead(bars: list[Bar], relations: list[dict], names: dict[str, str], cal: WorkCalendar, data_date: date) -> dict:
    """Data Date ~ +20일에 시작·종료할 task. 시작할 task 가운데 선행이 아직 허락하지 않는 것은 blocked."""
    to = data_date + timedelta(days=LOOKAHEAD_DAYS)
    tasks = [b for b in bars if b.kind == "task"]

    def within(b: Bar, day: date) -> dict | None:
        return {"id": b.id, "name": names[b.id], "date": day} if data_date <= day <= to else None

    starts = [x for b in tasks if b.actual_start is None and (x := within(b, b.start))]
    finishes = [x for b in tasks if b.actual_finish is None and (x := within(b, b.finish))]
    starts.sort(key=lambda x: x["date"])
    finishes.sort(key=lambda x: x["date"])
    blocked = _blocked(starts, {b.id: b for b in bars}, relations, cal, data_date)
    return {"from": data_date, "to": to, "starts": starts, "finishes": finishes, "blocked": blocked}


def _plan_compliance(tasks: list[Bar], data_date: date) -> dict | None:
    """Plan 종료가 Data Date 앞인 task(due) 가운데 Plan 종료까지 실제로 끝낸 것(done)의 비율."""
    due = [b for b in tasks if b.plan_finish is not None and b.plan_finish < data_date]
    if not due:
        return None
    done = sum(b.actual_finish is not None and b.actual_finish <= b.plan_finish for b in due)
    return {"pct": int(half_up(done / len(due) * 100)), "done": done, "due": len(due)}


def _critical_variance(tasks: list[Bar], acts: dict[str, dict], cal: WorkCalendar) -> dict | None:
    """크리티컬 task 의 (지금 근무일 길이 − Plan 근무일 길이) 합과 가장 큰 것(같으면 일정 순서 앞)."""
    rows = [
        (b.id, _length(cal, b.start, b.finish, b.tags) - _length(cal, b.plan_start, b.plan_finish, b.tags))
        for b in tasks
        if acts[b.id]["critical"] and b.plan_start is not None and b.plan_finish is not None
    ]
    if not rows:
        return None
    return {"days": sum(v for _, v in rows), "max_id": max(rows, key=lambda r: r[1])[0]}


def _cpm(tasks: list[Bar], acts: dict[str, dict], cal: WorkCalendar, finish: dict, data_date: date) -> dict:
    """finish = _finish 결과(준공 차이는 그 delta 와 같다)."""
    days = finish["delta"]
    return {
        "plan_compliance": _plan_compliance(tasks, data_date),
        "critical_variance": _critical_variance(tasks, acts, cal),
        "finish_variance": None if days is None else {"days": days, "plan": finish["plan"], "current": finish["current"]},
    }


def _read(session: Session, schedule_id: int) -> tuple[dict, Schedule, list[dict]]:
    """일정 자료와 그 버전의 조건을 넣은 일정·저장된 조건. 없으면 404, 계산이 안 되면 422."""
    try:
        view = view_data(session, schedule_id)
        schedule, conditions, _ = load(session, schedule_id, view["version"])
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", SCHEDULE_ERROR_MESSAGES[e.code], e.detail) from None
    return view, prepare_stored(schedule, conditions), conditions


def _in_plan(b: Bar) -> bool:
    return b.plan_start is not None and b.plan_finish is not None


def _rates(bars: list[Bar], wbs: list[dict], cal: WorkCalendar, data_date: date, unit: Unit) -> dict:
    """공정률 칸들. 기준 범위(Plan 이 있는 액티비티)로 세고, Plan 이 계산되지 않은 것은 수와 실적만 따로 낸다."""
    base = [b for b in bars if _in_plan(b)]
    added = [b for b in bars if not _in_plan(b)]
    plan_at = {b.id: planned(b, cal, data_date) for b in base}
    actual_at = {b.id: actual(b, cal, data_date, data_date) or 0.0 for b in bars}
    plan_now, actual_now = weighted(base, plan_at), weighted(base, actual_at)
    points = curve(base, cal, data_date=data_date, unit=unit)
    return {
        "plan_now": plan_now,
        "actual_now": actual_now,
        "gap": _diff(actual_now, plan_now),
        "spi": spi(plan_now, actual_now),
        "added_after_plan": {"count": len(added), "actual_pct": weighted(added, actual_at)},
        "curve": [asdict(p) for p in points],
        "spi_trend": [
            {"date": p.date, "spi": spi(p.plan_cum, p.actual_cum)}
            for p in points
            if p.actual_cum is not None and p.plan_cum > 0
        ],
        "wbs": _wbs(wbs, base, plan_at, actual_at),
    }


def progress(session: Session, schedule_id: int, unit: Unit) -> ProgressOut:
    view, ready, conditions = _read(session, schedule_id)
    cal = WorkCalendar(ready.calendar)
    data_date = view["data_date"] or context.today()
    bars = _bars(view)
    tasks = [b for b in bars if b.kind == "task"]
    acts = {a["id"]: a for a in view["activities"]}
    names = {i: a["name"] for i, a in acts.items()}
    finish = _finish(view, cal, _deadline(conditions))
    return ProgressOut.model_validate(
        {
            "schedule_id": schedule_id,
            "version": view["version"],
            "data_date": data_date,
            "data_date_assumed": view["data_date"] is None,
            "unit": unit,
            "weight_mode": view.get("weight_mode", "duration"),  # Task 21 전에는 칸이 없다
            **_rates(bars, view["wbs"], cal, data_date, unit),
            "finish": finish,
            "counts": _counts(tasks, cal),
            "milestones": _milestones(bars, names, cal),
            "top_delays": _top_delays(tasks, acts, cal),
            "lookahead": _lookahead(bars, view["relations"], names, cal, data_date),
            "cpm": _cpm(tasks, acts, cal, finish, data_date),
        }
    )
