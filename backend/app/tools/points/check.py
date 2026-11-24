"""points.check — 관리 포인트를 확인한다(읽기): 지금 포인트·마지막 차이·바깥 위험·근거 문장 상태.

what_if = 열린 지연 사건을 넣은 가정 포인트(지연 기록·분석은 버전을 만들지 않는다): 지금 계산해 카드 차이를 적고, 새 포인트가
있으면 바깥 위험 찾기를 뒤에서 띄운다(이 도구는 기다리지 않는다 — 카드는 「바깥 위험 찾는 중」). 아니면 지금 버전의 저장한
차이(버전을 만들 때 적은 것)를 읽기만 한다. 날짜·여유는 저장한 엔진 값 그대로다. 근거 문장은 채우지 않는다(사람이 누를 때만).
사건: 바뀜(added·became_critical·tightened)이 있으면 card {kind: "points_changed", …}(app.points.card.payload).
"""

from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import AgentEvent
from app.errors import ApiError
from app.points import card
from app.points import service as points_service
from app.programs.points import service
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.registry import tool

SHOWN = "관리 포인트가 바뀌어 카드를 냈습니다. 바깥 위험 줄·숫자는 카드에 있는 그대로만 말합니다."
SAME = "관리 포인트는 바뀌지 않았습니다(카드 없음)."
FIRST = "처음 계산한 포인트라 견줄 앞 상태가 없습니다(카드 없음)."
LOOKING = " 바깥 위험은 뒤에서 찾는 중입니다."


class PointsCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_if: bool = Field(default=False, description="true = 열린 지연 사건을 넣은 가정 포인트(지연 기록·분석 뒤)")


class PointsCheckOut(BaseModel):
    schedule_id: int
    version: int
    what_if: bool
    basis: dict  # {tf_days, window_weeks}
    points: list[dict]  # {activity_id, name, critical, tf, es, ef} — 엔진 값
    diff: dict | None  # {added, removed, tightened, became_critical, before_tf}. 처음 계산이면 null
    risk_status: str  # looking | done | failed | none
    risks: list[dict]  # {activity_id, kind, line, status(ok·none·skipped), source, as_of, why, evidence_id}
    quotes: dict  # 'activity_id/kind' → {status, message, quotes, error_code} | null(아직 누르지 않음)
    card: bool  # 카드를 냈는가
    note: str


@tool(
    "points.check",
    "관리 포인트(크리티컬이거나 여유가 적고 곧 시작하는 작업)를 확인한다: {what_if?}. 지금 포인트·마지막 차이·새 포인트의 "
    "바깥 위험(날씨·자재·환율·업체)·근거 문장 상태를 준다. 바뀌었으면 카드를 낸다. 지연을 기록·분석한 뒤에는 what_if true. "
    "날짜·여유는 코드가 계산한 값이다. 일정은 바뀌지 않는다.",
)
def check(args: PointsCheckIn, ctx: ToolContext) -> PointsCheckOut:
    schedule_id = ctx.require_schedule_id()
    session = ctx.session
    with explained_schedule_errors():
        if args.what_if:
            _, _, n, look = points_service.remember_what_if(session, schedule_id)
            session.commit()
            if look:
                card.launch(schedule_id, n, what_if=True)
        try:
            got = service.view(session, schedule_id, what_if=args.what_if)
        except ApiError as e:
            raise ToolError(e.message) from None
    payload = got.pop("card")
    if payload is not None:
        ctx.emit(AgentEvent("card", payload))
    got.pop("risk_message")
    note = SHOWN if payload is not None else (FIRST if got["diff"] is None else SAME)
    if payload is not None and got["risk_status"] == card.LOOKING:
        note += LOOKING
    return PointsCheckOut(**got, card=payload is not None, note=note)
