"""보고서용 그림(Task 44)의 표와 저장. 표(열·단위·값)는 저장된 일정에서 코드가 만든다 — LLM·Liner 는 값을 만들지 않는다.

종류(kind)와 표:
- summary: 크리티컬 패스 작업(시작 순) — 작업·시작·끝. version 을 주면 그 버전.
- delay_impact: 기록한 지연 사건(store.delays.report) — 작업·지연·흡수·준공 영향(근무일)·상태. 지금 버전만.
- scenario_compare: 지금 일정 + 열린·승인 대기 만약에 안(새것 5개) — 안·준공·크리티컬 수·위반 수. 지금 버전만.
- s_curve: 기준 범위(Plan 이 있는 액티비티)의 누적 계획·실적 %. unit(week·month)을 주면 그 단위, 없으면 주 단위.
  주가 40점을 넘으면 월로 바꾸고 note 에 「점이 많아 월 단위로 그렸습니다」. 지금 버전만.
열마다 대조 규칙(roles): charted(차트 자료에 개수까지) · shown(그림 아래 표 칸에 그대로). 막대 그림의 날짜·글 칸이 shown 이다.
- resource_load: 쓰이는 자원마다 한도·최고 사용·그날·한도 넘은 날 수(자원 맞춤 뒤). version 을 주면 그 버전.
기준일(data_date) = 그 버전 일정의 Data Date, 없으면 today(부르는 쪽이 준다 — app.agent.context.today()). 정수로 떨어지는 소수는 정수로 둔다(100.0 → 100, 글자 대조).
쓰기는 flush 만 한다(commit 은 부르는 쪽).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.progress import Bar, curve
from app.core.resources import level
from app.harness.assemble import prepare_stored
from app.store import delays, scenarios
from app.store.schedules import NotFound, get_record, load, run
from app.store.tables import Visual
from app.store.view import view_data

__all__ = ["KINDS", "NotFound", "TableError", "VisualTable", "build", "find_verified", "get", "out", "save"]

Kind = Literal["summary", "delay_impact", "scenario_compare", "s_curve", "resource_load"]
KINDS: tuple[str, ...] = ("summary", "delay_impact", "scenario_compare", "s_curve", "resource_load")
Chart = Literal["timeline", "bars", "line"]
Role = Literal["charted", "shown"]
C: Role = "charted"
S: Role = "shown"
Cell = str | int | float | None

MAX_ROWS = 25  # summary 줄 수 한도
MAX_SCENARIOS = 5
MAX_WEEK_POINTS = 40
MONTH_NOTE = "점이 많아 월 단위로 그렸습니다"
STATUS_LABELS = {"open": "열림", "reflected": "반영됨"}


class TableError(ValueError):
    """그릴 자료가 없다(사건·안·자원 없음, 지금 버전만 되는 그림에 옛 버전). message 는 한국어."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class VisualTable:
    kind: str
    title: str
    columns: list[str]
    rows: list[list[Cell]]
    chart: Chart  # 우리 그림(SVG)의 모양과 요청 글의 그림 종류
    version: int
    data_date: date | None
    # 열마다 대조 규칙: charted = 차트 자료에 개수까지 있어야 함, shown = 그림 아래 보이는 표 칸에 그대로 있어야 함.
    # 비면 모두 charted.
    roles: tuple[Role, ...] = ()
    note: str = ""  # 캡션에 덧붙일 글(예: 점이 많아 월 단위로 그렸습니다)

    def role(self, i: int) -> Role:
        return self.roles[i] if i < len(self.roles) else "charted"


def _num(x: float) -> int | float:
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _current_only(session: Session, schedule_id: int, version: int | None) -> int:
    n = get_record(session, schedule_id).current_version
    if version is not None and version != n:
        raise TableError(f"이 그림은 지금 버전(v{n})으로만 그립니다.")
    return n


def _summary(session: Session, schedule_id: int, version: int | None, today: date) -> VisualTable:
    schedule, conditions, n = load(session, schedule_id, version)
    cpm = run(schedule, conditions)
    on_path = sorted((cpm.rows[a.id].es, cpm.rows[a.id].ef, a.id, a.name) for a in schedule.activities
                     if cpm.rows[a.id].critical)
    rows: list[list[Cell]] = [[name, es.isoformat(), ef.isoformat()] for es, ef, _, name in on_path[:MAX_ROWS]]
    return VisualTable("summary", "일정 요약 — 크리티컬 패스 작업", ["작업", "시작", "끝"], rows, "timeline", n,
                       schedule.data_date or today, (C, C, C))


def _delay_impact(session: Session, schedule_id: int, version: int | None, today: date) -> VisualTable:
    _current_only(session, schedule_id, version)
    data = delays.report(session, schedule_id)
    rows: list[list[Cell]] = [
        [e["activity_name"], e["days"], e["impact"]["absorbed"], e["impact"]["finish_delta"],
         STATUS_LABELS.get(e["status"], e["status"])]
        for e in data["events"] if e["impact"]
    ]
    if not rows:
        raise TableError("기록한 지연이 없습니다.")
    schedule, _, n = load(session, schedule_id)
    return VisualTable("delay_impact", "지연 영향", ["작업", "지연(근무일)", "흡수(근무일)", "준공 영향(근무일)", "상태"],
                       rows, "bars", n, schedule.data_date or today, (C, C, C, C, S))


def _scenario_row(name: str, summary: dict) -> list[Cell]:
    return [name, summary["finish"], summary["critical_count"], len(summary["violations"])]


def _scenario_compare(session: Session, schedule_id: int, version: int | None, today: date) -> VisualTable:
    _current_only(session, schedule_id, version)
    found = scenarios.listed(session, schedule_id, ("open", "submitted"))[:MAX_SCENARIOS]
    if not found:
        raise TableError("비교할 만약에 안이 없습니다.")
    schedule, conditions, n = load(session, schedule_id)
    rows = [_scenario_row("지금 일정", scenarios.summarize(session, schedule_id, schedule, conditions))]
    rows += [_scenario_row(s.name, s.summary_json) for s in found]
    return VisualTable("scenario_compare", "안 비교", ["안", "준공", "크리티컬(개)", "위반(개)"], rows, "bars", n,
                       schedule.data_date or today, (C, S, C, C))


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _bars(view: dict) -> list[Bar]:
    """진행 화면(programs/progress)과 같은 막대 — 기준 범위는 Plan 이 계산된 것만."""
    bars = [
        Bar(id=a["id"], kind=a["kind"], wbs=a["wbs"], weight=a["weight"], plan_start=a["plan_start"],
            plan_finish=a["plan_finish"], start=a["es"], finish=a["ef"], actual_start=_day(a["actual_start"]),
            actual_finish=_day(a["actual_finish"]), progress=a["progress"], tags=tuple(a["tags"]))
        for a in view["activities"]
    ]
    return [b for b in bars if b.plan_start is not None and b.plan_finish is not None]


def _s_curve(session: Session, schedule_id: int, version: int | None, today: date,
             unit: str | None = None) -> VisualTable:
    _current_only(session, schedule_id, version)
    view = view_data(session, schedule_id)
    schedule, conditions, n = load(session, schedule_id, view["version"])
    base = _bars(view)
    if not base:
        raise TableError("Plan 이 계산되지 않아 S-커브를 그릴 수 없습니다.")
    cal = WorkCalendar(prepare_stored(schedule, conditions).calendar)
    data_date = view["data_date"] or today
    points = curve(base, cal, data_date=data_date, unit="month" if unit == "month" else "week")
    note = ""
    if unit != "month" and len(points) > MAX_WEEK_POINTS:  # 주가 40점을 넘으면 월(컨트롤러 판정 11-20)
        points, note = curve(base, cal, data_date=data_date, unit="month"), MONTH_NOTE
    rows: list[list[Cell]] = [
        [p.date.isoformat(), _num(p.plan_cum), None if p.actual_cum is None else _num(p.actual_cum)] for p in points
    ]
    return VisualTable("s_curve", "진행 S-커브", ["날짜", "계획 누적(%)", "실적 누적(%)"], rows, "line", n, data_date,
                       (C, C, C), note)


def _resource_load(session: Session, schedule_id: int, version: int | None, today: date) -> VisualTable:
    schedule, conditions, n = load(session, schedule_id, version)
    ready = prepare_stored(schedule, conditions)
    lv = level(ready, compute(ready), shift=True)
    rows: list[list[Cell]] = []
    for r in schedule.resources:
        peak = lv.peaks.get(r.id)
        if peak is None:
            continue
        over = sum(o.resource_id == r.id for o in lv.overloads)
        rows.append([r.name, r.capacity, peak.need, peak.when.isoformat(), over])
    if not rows:
        raise TableError("쓰는 자원이 없습니다.")
    return VisualTable("resource_load", "자원 부하", ["자원", "한도", "최고 사용", "최고 사용일", "한도 넘은 날(일)"], rows,
                       "bars", n, schedule.data_date or today, (C, C, C, S, C))


_BUILDERS: dict[str, Callable[[Session, int, int | None, date], VisualTable]] = {
    "summary": _summary,
    "delay_impact": _delay_impact,
    "scenario_compare": _scenario_compare,
    "s_curve": _s_curve,
    "resource_load": _resource_load,
}


def build(session: Session, kind: str, schedule_id: int, version: int | None = None, *, today: date,
          unit: str | None = None) -> VisualTable:
    """그 종류의 표. 없는 일정·버전이면 NotFound, 깨진 일정이면 ScheduleError, 그릴 자료가 없으면 TableError.

    unit(week·month)은 s_curve 만 쓴다.
    """
    get_record(session, schedule_id)
    if kind == "s_curve":
        return _s_curve(session, schedule_id, version, today, unit)
    return _BUILDERS[kind](session, schedule_id, version, today)


# ── 저장 ─────────────────────────────────────────────────────────────


def find_verified(session: Session, schedule_id: int, key: str) -> Visual | None:
    """같은 입력(key)으로 대조를 통과한 가장 새 그림. 없으면 None."""
    query = (select(Visual)
             .where(Visual.schedule_id == schedule_id, Visual.input_hash == key, Visual.verified)
             .order_by(Visual.id.desc()))
    return session.scalars(query).first()


def find_fallback(session: Session, schedule_id: int, key: str, note: str) -> Visual | None:
    """같은 입력·같은 까닭으로 우리 그림이 된 가장 새 그림(연결 없음 줄이 쌓이지 않게). 없으면 None."""
    query = (select(Visual)
             .where(Visual.schedule_id == schedule_id, Visual.input_hash == key, Visual.fallback, Visual.note == note)
             .order_by(Visual.id.desc()))
    return session.scalars(query).first()


def save(
    session: Session, *, schedule_id: int, table: VisualTable, key: str, html: str, theme: str, description: str,
    resource_id: str, verified: bool, passed: int, total: int, problems: list[str], external: list[str],
    attempts: int, fallback: bool, note: str, latency_ms: int | None, created_by: str,
) -> Visual:
    row = Visual(
        schedule_id=schedule_id, version=table.version, kind=table.kind, input_hash=key, data_date=table.data_date,
        table_json={"title": table.title, "columns": table.columns, "rows": table.rows, "chart": table.chart,
                    "roles": [table.role(i) for i in range(len(table.columns))], "note": table.note},
        html=html, theme=theme[:40], description=description, resource_id=resource_id[:100], verified=verified,
        passed=passed, total=total, checks_json={"problems": problems, "external": external}, attempts=attempts,
        fallback=fallback, note=note[:200], latency_ms=latency_ms, created_by=created_by[:100],
    )
    session.add(row)
    session.flush()
    return row


def get(session: Session, schedule_id: int, visual_id: int) -> Visual:
    """그 일정의 그림. 없거나 다른 일정의 것이면 NotFound."""
    row = session.get(Visual, visual_id)
    if row is None or row.schedule_id != schedule_id:
        raise NotFound(visual_id)
    return row


def out(row: Visual) -> dict:
    """화면·API 에 줄 모양(VisualOut). 우리 그림으로 대신하는 그림(fallback)은 html 을 주지 않는다."""
    t = row.table_json
    return {
        "id": row.id, "schedule_id": row.schedule_id, "kind": row.kind, "title": t["title"], "version": row.version,
        "data_date": row.data_date, "columns": t["columns"], "rows": t["rows"], "chart": t["chart"], "table_note": t.get("note", ""),
        "html": None if row.fallback else row.html, "theme": row.theme, "description": row.description,
        "resource_id": row.resource_id, "verified": row.verified, "passed": row.passed, "total": row.total,
        "fallback": row.fallback, "note": row.note, "external": list(row.checks_json.get("external", [])),
        "latency_ms": row.latency_ms, "created_at": row.created_at,
    }
