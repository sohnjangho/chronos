"""주의할 일정: 일정마다 지금 버전의 계산·조건 점검·열린 지연으로 위험(danger)·주의(warning)·괜찮음(ok)을 가른다.

danger = 음수 여유 > 0 이거나 위반 > 0, warning = 늦은 task > 0 이거나 열린 지연 > 0, 그 밖 ok.
계산이 안 되는 일정은 danger, 위반 1. 차례는 danger → warning → ok, 같으면 이름(그다음 id).
날짜·여유는 app.store.view, 위반은 harness check 가 센다. 여기서는 세고 가르기만 한다.
"""

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.checks import check
from app.harness.conditions import read_conditions
from app.programs.attention.schemas import AttentionItem, AttentionOut
from app.store.delays import open_events
from app.store.schedules import list_records, load, run
from app.store.tables import ScheduleRecord
from app.store.view import plan_of, view_of

_ORDER = {"danger": 0, "warning": 1, "ok": 2}


def _level(negative: int, violations: int, late: int, open_delays: int) -> str:
    if negative > 0 or violations > 0:
        return "danger"
    return "warning" if late > 0 or open_delays > 0 else "ok"


def _broken(record: ScheduleRecord, open_delays: int) -> AttentionItem:
    return AttentionItem(
        id=record.id, name=record.name, domain=record.domain, open_delays=open_delays, finish=None,
        plan_finish=None, finish_delta=None, late_count=0, negative_float_count=0, violations=1, level="danger",
    )


def _compute(session: Session, record: ScheduleRecord, open_delays: int) -> AttentionItem:
    schedule, stored, n = load(session, record.id)
    ready = prepare_stored(schedule, stored)
    cpm = run(ready)
    plan = plan_of(session, record.id, n, cpm)
    view = view_of(session, record.id, n, schedule, ready, cpm, plan)
    readable, _ = read_conditions(stored)
    violations = len(check(schedule, assemble_all(readable)).violations)
    late = view["summary"]["warning_count"]
    negative = view["summary"]["negative_float_count"]
    delta = WorkCalendar(ready.calendar).workdays_between(plan.finish, cpm.finish) if plan else None
    return AttentionItem(
        id=record.id, name=record.name, domain=record.domain, open_delays=open_delays, finish=cpm.finish,
        plan_finish=plan.finish if plan else None, finish_delta=delta, late_count=late,
        negative_float_count=negative, violations=violations,
        level=_level(negative, violations, late, open_delays),
    )


def _item(session: Session, record: ScheduleRecord) -> AttentionItem:
    """일정 하나. 어디서 실패하든(계산 불가·점검 오류) 그 일정만 danger 로 두고 전체 목록은 막지 않는다."""
    open_delays = len(open_events(session, record.id))
    try:
        return _compute(session, record, open_delays)
    except Exception:  # noqa: BLE001 - 일정 하나의 오류가 위젯 전체를 막지 않게
        return _broken(record, open_delays)


def attention(session: Session) -> AttentionOut:
    items = [_item(session, r) for r in list_records(session)]
    items.sort(key=lambda i: (_ORDER[i.level], i.name, i.id))
    return AttentionOut(items=items)
