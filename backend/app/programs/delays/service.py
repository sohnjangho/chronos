"""지연 기록 API: 기록·고침·지우기·분석·지연 반영안·미리 보기. 응답은 모두 DelaysOut(store.delays.report).

기록한 지연은 저장된 일정을 바꾸지 않고 Plan 도 옮기지 않는다(PM 결정 11-20). 일정에 넣는 것은 지연 반영안(복사본,
source 'delay')을 승인할 때뿐이고, 그때 사건이 'reflected' 가 된다(store.links). 반영된 사건은 일수·대상·시작일을
바꾸거나 지울 수 없다(409 delay_reflected). 쓰기 뒤에는 열린 사건을 다시 분석한다(사건마다 몫이 차례에 달려 있다).
확인 차례: 401 → 본문 422 invalid_request → 404 → 409 delay_reflected → 422 invalid_delay → 계산 422 schedule_invalid.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.errors import ApiError
from app.harness.assemble import prepare_stored
from app.programs.delays.schemas import (
    DelayIn,
    DelayPatch,
    DelaysOut,
    PreviewOut,
    ScenarioIn,
    ScenarioOut,
)
from app.store import delays, scenarios
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load, run
from app.store.tables import User
from app.store.view import plan_of, view_of

SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
NOT_FOUND_MESSAGE = "지연 사건을 찾을 수 없습니다."
LOCKED_EDIT_MESSAGE = "일정에 반영된 사건은 일수·대상·시작일을 바꿀 수 없습니다."
LOCKED_DELETE_MESSAGE = "일정에 반영된 사건은 지울 수 없습니다."
NO_OPEN_MESSAGE = "열린 지연 사건이 없습니다."
LOCKED_FIELDS = {"activity_id", "start_date", "days"}  # 반영된 사건에서 바꿀 수 없는 칸


def _schedule(session: Session, schedule_id: int) -> None:
    try:
        get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None


def _event(session: Session, schedule_id: int, eid: int) -> delays.DelayEventRow:
    _schedule(session, schedule_id)
    try:
        row = delays.get(session, eid)
    except delays.NotFound:
        row = None
    if row is None or row.schedule_id != schedule_id:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    return row


def _known(session: Session, schedule_id: int, activity_id: str) -> None:
    schedule, _, _ = load(session, schedule_id)
    if all(a.id != activity_id for a in schedule.activities):
        raise ApiError(422, "invalid_delay", f"없는 액티비티입니다: {activity_id}")


def _computed[T](make: Callable[[], T]) -> T:
    """계산이 안 되는 지금 일정이면 422 schedule_invalid(까닭은 한국어)."""
    try:
        return make()
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None


def _out(session: Session, schedule_id: int, *, force: bool = False) -> DelaysOut:
    """다시 분석(force 면 늘)한 묶음을 commit 하고 돌려준다. 실패면 rollback(적은 것 없음)."""
    try:
        if force:
            _computed(lambda: delays.refresh(session, schedule_id, force=True))
        out = DelaysOut.model_validate(_computed(lambda: delays.report(session, schedule_id)))
    except ApiError:
        session.rollback()
        raise
    session.commit()
    return out


def list_delays(session: Session, schedule_id: int) -> DelaysOut:
    _schedule(session, schedule_id)
    return _out(session, schedule_id)


def analyze(session: Session, schedule_id: int) -> DelaysOut:
    """열린 사건을 지금 버전으로 모두 다시 분석한다."""
    _schedule(session, schedule_id)
    return _out(session, schedule_id, force=True)


def create(session: Session, schedule_id: int, body: DelayIn, user: User) -> DelaysOut:
    _schedule(session, schedule_id)
    _known(session, schedule_id, body.activity_id)
    delays.create(session, schedule_id=schedule_id, **body.model_dump(), source="user", created_by=user.name)
    return _out(session, schedule_id)  # 새 사건은 분석 전이라 열린 사건을 모두 다시 분석한다


def patch(session: Session, schedule_id: int, eid: int, body: DelayPatch) -> DelaysOut:
    row = _event(session, schedule_id, eid)
    fields = body.model_dump(exclude_unset=True)
    if row.status == "reflected" and LOCKED_FIELDS & fields.keys():
        raise ApiError(409, "delay_reflected", LOCKED_EDIT_MESSAGE)
    if "activity_id" in fields:
        _known(session, schedule_id, fields["activity_id"])
    delays.update(session, row, **fields)
    if row.status == "reflected" and "daily_cost" in fields and row.impact_json:
        i = row.impact_json  # 반영된 사건은 다시 넣지 않는다: 적어 둔 몫으로 비용만 다시 센다
        pushed = i["finish_delta"] if i["applied"] and i["finish_delta"] > 0 else 0  # core.delay 의 비용 규칙
        cost = None if row.daily_cost is None else row.daily_cost * pushed
        delays.update(session, row, impact_json={**i, "cost": cost})
    return _out(session, schedule_id, force=row.status == "open")


def delete(session: Session, schedule_id: int, eid: int) -> DelaysOut:
    row = _event(session, schedule_id, eid)
    if row.status == "reflected":
        raise ApiError(409, "delay_reflected", LOCKED_DELETE_MESSAGE)
    delays.delete(session, row)
    return _out(session, schedule_id, force=True)


def scenario(session: Session, schedule_id: int, body: ScenarioIn, user: User) -> ScenarioOut:
    """열린 사건(event_ids 를 주면 그 가운데 열린 것)을 넣은 지연 반영안(source 'delay'). 일정은 그대로."""
    _schedule(session, schedule_id)
    base = delays.delayed_base(session, schedule_id, body.event_ids)
    if not base.event_ids:
        raise ApiError(422, "no_open_delays", NO_OPEN_MESSAGE)
    row = _computed(lambda: scenarios.create(
        session, schedule_id=schedule_id, base_version=base.version, name=f"지연 반영안 ({len(base.event_ids)}건)",
        source="delay", schedule=base.schedule, conditions=base.conditions, delay_event_ids=base.event_ids,
        created_by=user.name,
    ))
    session.commit()
    return ScenarioOut(scenario_id=row.id)


def _moved(schedule: Schedule, before: CpmResult, after: CpmResult) -> list[dict]:
    """시작이나 끝이 달라진 액티비티(일정 차례). 조건 미리 보기(programs/conditions/preview_view.moved)와 같은 모양 —
    프로그램끼리 import 하지 않으므로 여기 둔다."""
    rows = []
    for a in schedule.activities:
        b, c = before.rows[a.id], after.rows[a.id]
        if (b.es, b.ef) != (c.es, c.ef):
            rows.append({"activity_id": a.id, "name": a.name, "before": {"start": b.es, "finish": b.ef},
                         "after": {"start": c.es, "finish": c.ef}})
    return rows


def preview(session: Session, schedule_id: int) -> PreviewOut:
    """열린 사건을 넣은 일정(저장 안 함). Plan 은 지금 버전의 Plan 그대로라 지연은 late +n 으로 보인다."""
    _schedule(session, schedule_id)
    schedule, conditions, n = load(session, schedule_id)

    def make() -> PreviewOut:
        now = run(schedule, conditions)
        base = delays.delayed_base(session, schedule_id)
        ready = prepare_stored(base.schedule, conditions)
        cpm = run(ready)
        plan = plan_of(session, schedule_id, n, now)
        view = view_of(session, schedule_id, n, base.schedule, ready, cpm, plan)
        return PreviewOut.model_validate({"view": view, "moved": _moved(schedule, now, cpm)})

    return _computed(make)
