"""현장 모바일 협업 API 서비스:
1. 일일 1분 현장 체크인 (checkin)
2. 현장 사진 AI 진도율 판독 & 증빙 (photo)
3. 만회안·일정 변경 공종 담당자 실현성 의견 조회 (poll)
4. 착수 D-3 선·후행 공종 핸드오프 준비 점검 (handoff)
"""

import secrets
from dataclasses import replace
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context
from app.agent.proposals import (
    Proposal,
    ProposalError,
    actual_dates_problem,
    actuals_blocked,
    propose,
)
from app.core.calendar import NoWorkdayError, WorkCalendar
from app.core.cpm import ScheduleError
from app.core.model import Activity, Schedule
from app.errors import ApiError
from app.harness.assemble import prepare_stored
from app.harness.conditions import Condition
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.store import approvals
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load, run
from app.store.tables import FieldItem, User
from app.store.timeutil import as_utc
from app.store.view import view_data

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
FieldKind = Literal["checkin", "photo", "poll", "handoff"]

# 사진 판독(PM 결정 11-23, F1): 사진을 그림 읽기(vision) 모델로 실제로 읽는다. 사진이 없거나 읽지 못하면
# 「판독하지 않음」(response_choice unread, 진도 값 없음)과 까닭만 남기고, 숫자를 지어내지 않는다.
UNREAD = "unread"
NO_PHOTO = "사진이 없어 판독하지 않았습니다."
BAD_ANSWER = "모델 답을 읽지 못해 판독하지 않았습니다."
LEGACY_PHOTO = "이전 방식으로 만든 항목입니다. 사진을 다시 올려 주세요"  # F1 이전 항목(숫자를 지어냈다, 리뷰 I-3)
VISION_PROMPT = (
    "너는 건설·제조 현장 사진을 보고 한 작업의 진도를 판독한다. 사진에 보이는 것만 근거로 삼고, 보이지 않는 것은 짐작하지 않는다. "
    "progress: 이 작업의 진도율(0~100 정수). reason: 그 진도로 본 까닭 한 문장(한국어). "
    "risks: 사진에 보이는 안전·품질·일정 위험(한국어 짧은 문장, 없으면 빈 목록)."
)
VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "progress": {"type": "integer"},
        "reason": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["progress", "reason", "risks"],
    "additionalProperties": False,
}


class VisionAnswer(BaseModel):
    progress: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    risks: list[str]


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DispatchCheckinIn(StrictIn):
    activity_ids: list[str] | None = None


# 사진 data URL 길이 한도. 화면이 긴 변 1280px·JPEG 0.7 로 줄여 보낸다(보통 base64 0.2~1MB). 그림 읽기 한도
# (agent.image_turn.IMAGE_MAX_BYTES, 5MiB) 안이다. 화면(progress/FieldHub.tsx PHOTO_MAX_CHARS)과 같은 값.
PHOTO_DATA_URL_MAX = 1_500_000


class PhotoUploadIn(StrictIn):
    activity_id: str = Field(min_length=1, max_length=50)
    trade: str = Field(default="", max_length=120)
    photo_name: str = Field(min_length=1, max_length=200)
    photo_data_url: str | None = Field(default=None, max_length=PHOTO_DATA_URL_MAX)
    note: str = Field(default="", max_length=500)


class CreatePollIn(StrictIn):
    activity_id: str = Field(min_length=1, max_length=50)
    trade: str = Field(default="", max_length=120)
    scenario_title: str = Field(min_length=1, max_length=160)
    target_delta_days: int = Field(default=-3, ge=-60, le=60)
    prompt_text: str = Field(min_length=1, max_length=500)


class RespondIn(StrictIn):
    response_choice: str = Field(min_length=1, max_length=40)
    reported_progress: int | None = Field(default=None, ge=0, le=100)
    reported_rd: int | None = Field(default=None, ge=0, le=365)
    response_note: str = Field(default="", max_length=1000)


class HandoffUpdateIn(StrictIn):
    pred_handover_ok: bool
    material: bool
    equipment: bool
    workforce: bool
    response_note: str = Field(default="", max_length=1000)


class FieldItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    schedule_id: int
    kind: str
    activity_id: str
    activity_name: str
    trade: str
    status: str
    title: str
    prompt_text: str
    response_choice: str | None
    reported_progress: int | None
    reported_rd: int | None
    response_note: str
    payload_json: dict[str, Any]
    approval_id: int | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class FieldSummary(BaseModel):
    checkin_total: int
    checkin_responded: int
    photo_total: int
    poll_total: int
    poll_feasible: int
    poll_conditional: int
    poll_infeasible: int
    handoff_total: int
    handoff_ready: int


class FieldListOut(BaseModel):
    schedule_id: int
    schedule_name: str
    activities: list[dict[str, Any]]
    summary: FieldSummary
    items: list[FieldItemOut]


def client_for(session: Session) -> LlmClient:
    """사진 판독이 쓰는 LLM 클라이언트(시험이 대본 LLM 으로 바꾼다)."""
    return LlmClient(session)


def _load_view(session: Session, schedule_id: int) -> dict[str, Any]:
    try:
        return view_data(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None


def _guess_trade(act_name: str, index: int = 0) -> str:
    n = act_name
    if any(k in n for k in ("철근", "거푸집", "타설", "골조", "슬래브", "콘크리트", "기초")):
        return "골조팀 박반장"
    if any(k in n for k in ("외장", "커튼월", "창호", "방수", "도장", "단열")):
        return "외장팀 최과장"
    if any(k in n for k in ("전기", "설비", "배관", "소방", "기계", "덕트")):
        return "설비팀 이소장"
    if any(k in n for k in ("프레스", "금형", "성형", "가공")):
        return "프레스반 정반장"
    if any(k in n for k in ("도금", "검사", "포장", "조립", "출하")):
        return "조립·품질팀 김주임"
    return ("공정담당 김대리", "시공팀 박과장", "품질팀 최주임")[index % 3]


def ensure_seeded(session: Session, schedule_id: int, view: dict[str, Any]) -> None:
    """일정에 현장 협업 항목이 하나도 없으면 실제 액티비티·관계 기반으로 초기 시연 데이터를 채운다."""
    has_any = session.scalar(select(FieldItem.id).where(FieldItem.schedule_id == schedule_id).limit(1))
    if has_any is not None:
        return
    acts = [a for a in view["activities"] if a["kind"] == "task"] or list(view["activities"])
    if not acts:
        return
    a0 = acts[0]
    a1 = acts[1] if len(acts) > 1 else a0
    a2 = acts[2] if len(acts) > 2 else a1
    p0 = round(float(a0.get("progress") or 0.0) * 100)
    rd0 = int(a0.get("rd") or a0.get("od") or 3)
    rd1 = int(a1.get("rd") or a1.get("od") or 4)
    day_tag = str(view.get("data_date") or context.today()).replace("-", "")
    def iso(v: Any) -> str | None:
        return v.isoformat() if isinstance(v, date) else (str(v) if v is not None else None)

    seeds: list[FieldItem] = [
        FieldItem(
            schedule_id=schedule_id,
            kind="checkin",
            activity_id=a0["id"],
            activity_name=a0["name"],
            trade=_guess_trade(a0["name"], 0),
            status="responded",
            title=f"[오늘 체크인] {a0['id']} {a0['name']}",
            prompt_text=f"{a0['name']} 금일 진행 상황과 잔여일(RD)을 회신해 주세요.",
            response_choice="delayed" if a0.get("status") == "late" else "on_track",
            reported_progress=min(100, max(25, p0 or 45)),
            reported_rd=rd0,
            response_note="오전 자재 양중 완료, 오후 후속 작업 구간 정리 중입니다.",
            payload_json={"planned_finish": iso(a0.get("ef")), "critical": bool(a0.get("critical"))},
        ),
        FieldItem(
            schedule_id=schedule_id,
            kind="checkin",
            activity_id=a1["id"],
            activity_name=a1["name"],
            trade=_guess_trade(a1["name"], 1),
            status="pending",
            title=f"[체크인 요청] {a1['id']} {a1['name']}",
            prompt_text=f"관리자 에이전트: 오늘 예정된 {a1['name']} 착수/진행 여부를 회신해 주세요.",
            response_choice=None,
            reported_progress=round(float(a1.get("progress") or 0.0) * 100),
            reported_rd=rd1,
            response_note="",
            payload_json={"planned_finish": iso(a1.get("ef")), "critical": bool(a1.get("critical"))},
        ),
        FieldItem(
            schedule_id=schedule_id,
            kind="photo",
            activity_id=a0["id"],
            activity_name=a0["name"],
            trade=_guess_trade(a0["name"], 0),
            status="responded",
            title=f"[AI 사진 판독] {a0['id']} {a0['name']}",
            prompt_text=f"예시 항목 · {NO_PHOTO}",
            response_choice=UNREAD,
            reported_progress=None,
            reported_rd=None,
            response_note="철근 배근 1차 검측 통과, 거푸집 조립 50% 진행 확인",
            payload_json={
                "sample_key": "rebar",
                "photo_name": f"site_{a0['id']}_{day_tag}.jpg",
                "ai_progress": None,
                "unread_reason": NO_PHOTO,
                "evidence_tag": f"#{schedule_id}-{a0['id']}-{day_tag}",
                "captured_at": f"{context.today().isoformat()} 14:20",
            },
        ),
        FieldItem(
            schedule_id=schedule_id,
            kind="poll",
            activity_id=a1["id"],
            activity_name=a1["name"],
            trade=_guess_trade(a1["name"], 1),
            status="responded",
            title=f"[만회안 의견] {a1['id']} 야간 연장/병행 단축 3일안",
            prompt_text=f"{a1['name']} 후속 공정을 3일 단축하기 위해 야간 2교대 투입이 가능한지 의견을 주세요.",
            response_choice="conditional",
            response_note="20시 이후 타워크레인 양중 소음 민원으로 불가, 주간 인력 2명 보강 시 -2일 단축 가능",
            payload_json={"scenario_title": "단축안 A (야간·인력 보강)", "target_delta_days": -3},
        ),
        FieldItem(
            schedule_id=schedule_id,
            kind="poll",
            activity_id=a2["id"],
            activity_name=a2["name"],
            trade=_guess_trade(a2["name"], 2),
            status="pending",
            title=f"[만회안 의견] {a2['id']} 선행 공종 병행 착수(SS+2d)",
            prompt_text=f"{a2['name']} 작업 구간 중 북측 존부터 선행 공종과 2일 중첩 착수할 수 있습니까?",
            response_choice=None,
            response_note="",
            payload_json={"scenario_title": "단축안 B (구간 분할 병행)", "target_delta_days": -2},
        ),
    ]

    act_by_id = {a["id"]: a for a in view["activities"]}
    rel = next((r for r in view["relations"] if r["pred"] in act_by_id and r["succ"] in act_by_id), None)
    pred_act = act_by_id[rel["pred"]] if rel else a0
    succ_act = act_by_id[rel["succ"]] if rel else a1
    seeds.append(
        FieldItem(
            schedule_id=schedule_id,
            kind="handoff",
            activity_id=succ_act["id"],
            activity_name=succ_act["name"],
            trade=f"{_guess_trade(pred_act['name'], 0)} → {_guess_trade(succ_act['name'], 1)}",
            status="pending",
            title=f"[D-3 핸드오프] {pred_act['id']} → {succ_act['id']}",
            prompt_text=f"선행 {pred_act['name']} 작업면 인계 여부와 후행 {succ_act['name']} 투입 3대 요소(자재·장비·인력)를 점검하세요.",
            response_choice="hold",
            response_note="후행 자재 창고 입고 대기(내일 오전 반입 예정)",
            payload_json={
                "pred_id": pred_act["id"],
                "pred_name": pred_act["name"],
                "succ_start": iso(succ_act.get("es")),
                "days_left": 3,
                "pred_handover_ok": True,
                "checklist": {"material": True, "equipment": False, "workforce": True},
            },
        )
    )
    session.add_all(seeds)
    session.commit()


def legacy_photo(row: FieldItem) -> bool:
    """F1 이전에 만든 사진 항목: 판독 까닭(ai_reason)도 못 읽은 까닭(unread_reason)도 없다 — 숫자는 모델이 읽은 것이 아니다.
    현장 허브(상신 막기)와 승인함(그 항목에서 나온 승인 건 막기, programs/approvals)이 같이 쓰는 기준."""
    payload = row.payload_json or {}
    return row.kind == "photo" and "ai_reason" not in payload and "unread_reason" not in payload


def _item_out(row: FieldItem) -> FieldItemOut:
    """예전 방식의 사진 항목은 판독하지 않음으로 내보낸다(저장된 줄은 바꾸지 않는다, 리뷰 I-3)."""
    out = FieldItemOut.model_validate(row)
    if not legacy_photo(row):
        return out
    payload = {**out.payload_json, "ai_progress": None, "unread_reason": LEGACY_PHOTO}
    return out.model_copy(update={"response_choice": "unread", "reported_progress": None, "payload_json": payload})


def _list_out(session: Session, schedule_id: int, view: dict[str, Any]) -> FieldListOut:
    rows = list(
        session.scalars(
            select(FieldItem).where(FieldItem.schedule_id == schedule_id).order_by(FieldItem.id.desc())
        )
    )
    checkins = [r for r in rows if r.kind == "checkin"]
    photos = [r for r in rows if r.kind == "photo"]
    polls = [r for r in rows if r.kind == "poll"]
    handoffs = [r for r in rows if r.kind == "handoff"]
    summary = FieldSummary(
        checkin_total=len(checkins),
        checkin_responded=sum(1 for r in checkins if r.status in ("responded", "applied")),
        photo_total=len(photos),
        poll_total=len(polls),
        poll_feasible=sum(1 for r in polls if r.response_choice == "feasible"),
        poll_conditional=sum(1 for r in polls if r.response_choice == "conditional"),
        poll_infeasible=sum(1 for r in polls if r.response_choice == "infeasible"),
        handoff_total=len(handoffs),
        handoff_ready=sum(1 for r in handoffs if r.response_choice == "ready"),
    )
    activities = [
        {"id": a["id"], "name": a["name"], "progress": round(float(a.get("progress") or 0.0) * 100), "rd": a.get("rd") or a.get("od")}
        for a in view["activities"]
        if a["kind"] == "task"
    ] or [{"id": a["id"], "name": a["name"], "progress": 0, "rd": 0} for a in view["activities"]]
    return FieldListOut(
        schedule_id=schedule_id,
        schedule_name=view["name"],
        activities=activities,
        summary=summary,
        items=[_item_out(r) for r in rows],
    )


def list_field(session: Session, schedule_id: int) -> FieldListOut:
    view = _load_view(session, schedule_id)
    ensure_seeded(session, schedule_id, view)
    return _list_out(session, schedule_id, view)


def dispatch_checkins(session: Session, schedule_id: int, body: DispatchCheckinIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    ensure_seeded(session, schedule_id, view)
    tasks = [a for a in view["activities"] if a["kind"] == "task"]
    if body.activity_ids:
        wanted = set(body.activity_ids)
        targets = [a for a in tasks if a["id"] in wanted]
    else:
        open_tasks = [a for a in tasks if a.get("status") != "done"] or tasks
        targets = open_tasks[:3]
    for i, a in enumerate(targets):
        session.add(
            FieldItem(
                schedule_id=schedule_id,
                kind="checkin",
                activity_id=a["id"],
                activity_name=a["name"],
                trade=_guess_trade(a["name"], i),
                status="pending",
                title=f"[에이전트 체크인] {a['id']} {a['name']}",
                prompt_text=f"관리자 에이전트 일일 요청: {a['name']} 오늘 작업 진행 여부와 잔여일(RD)을 회신해 주세요.",
                reported_progress=round(float(a.get("progress") or 0.0) * 100),
                reported_rd=int(a.get("rd") or a.get("od") or 1),
                payload_json={
                    "planned_finish": a["ef"].isoformat() if isinstance(a.get("ef"), date) else a.get("ef"),
                    "critical": bool(a.get("critical")),
                },
            )
        )
    session.commit()
    return _list_out(session, schedule_id, view)


async def _read_photo(
    session: Session, act: dict[str, Any], data_url: str, note: str
) -> tuple[VisionAnswer | None, str | None]:
    """그림 읽기 모델로 사진을 한 번 읽는다(llm_calls 에 남는다). (답, None) 또는 (None, 판독하지 않은 까닭)."""
    base_pct = round(float(act.get("progress") or 0.0) * 100)
    text = f"작업: {act['id']} {act['name']}\n지금 기록된 진도: {base_pct}%\n현장 소견: {note or '(없음)'}"
    messages = [
        {"role": "system", "content": VISION_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": data_url}}]},
    ]
    try:
        reply = await client_for(session).chat("vision", messages, json_schema=VISION_SCHEMA)
    except LlmNotReady as e:
        return None, f"판독하지 못했습니다: {e.message}"
    except LlmFailed as e:
        return None, f"판독하지 못했습니다: {e.error.message}"
    try:
        return VisionAnswer.model_validate(reply.parsed), None
    except ValidationError:
        return None, BAD_ANSWER


async def upload_photo(session: Session, schedule_id: int, body: PhotoUploadIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    act = next((a for a in view["activities"] if a["id"] == body.activity_id), None)
    if act is None:
        raise ApiError(422, "invalid_activity", f"없는 액티비티입니다: {body.activity_id}")
    photo = body.photo_data_url if body.photo_data_url and body.photo_data_url.startswith("data:image/") else None
    answer, why = await _read_photo(session, act, photo, body.note) if photo else (None, NO_PHOTO)
    day_tag = str(context.today()).replace("-", "")
    payload: dict[str, Any] = {
        "photo_name": body.photo_name,
        "ai_progress": answer.progress if answer else None,
        "evidence_tag": f"#{schedule_id}-{act['id']}-{day_tag}",
        "captured_at": f"{context.today().isoformat()} {datetime.now().strftime('%H:%M')}",
    }
    if answer:
        payload |= {"ai_reason": answer.reason, "ai_risks": answer.risks}
    else:
        payload["unread_reason"] = why
    if photo:
        payload["photo_data_url"] = photo
    else:
        payload["sample_key"] = "custom"
    rd_now = int(act.get("rd") or act.get("od") or 1)
    trade = body.trade.strip() or _guess_trade(act["name"])
    session.add(
        FieldItem(
            schedule_id=schedule_id,
            kind="photo",
            activity_id=act["id"],
            activity_name=act["name"],
            trade=trade,
            status="responded",
            title=f"[AI 사진 판독] {act['id']} {act['name']}",
            prompt_text=(
                f"사진({body.photo_name}) 그림 읽기 판독 · 진도 {answer.progress}%"
                if answer
                else f"사진({body.photo_name}) 판독하지 않음 — {why}"
            ),
            response_choice=UNREAD if answer is None else "risk" if answer.risks else "verified",
            reported_progress=answer.progress if answer else None,
            reported_rd=(0 if answer.progress >= 100 else max(1, rd_now)) if answer else None,
            response_note=body.note or (answer.reason if answer else ""),
            payload_json=payload,
        )
    )
    session.commit()
    return _list_out(session, schedule_id, view)


def create_poll(session: Session, schedule_id: int, body: CreatePollIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    act = next((a for a in view["activities"] if a["id"] == body.activity_id), None)
    if act is None:
        raise ApiError(422, "invalid_activity", f"없는 액티비티입니다: {body.activity_id}")
    trade = body.trade.strip() or _guess_trade(act["name"])
    session.add(
        FieldItem(
            schedule_id=schedule_id,
            kind="poll",
            activity_id=act["id"],
            activity_name=act["name"],
            trade=trade,
            status="pending",
            title=f"[만회안 의견] {act['id']} {body.scenario_title}",
            prompt_text=body.prompt_text,
            payload_json={"scenario_title": body.scenario_title, "target_delta_days": body.target_delta_days},
        )
    )
    session.commit()
    return _list_out(session, schedule_id, view)


def _get_item(session: Session, schedule_id: int, item_id: int) -> FieldItem:
    item = session.get(FieldItem, item_id)
    if item is None or item.schedule_id != schedule_id:
        raise ApiError(404, "not_found", "현장 협업 항목을 찾을 수 없습니다.")
    return item


def respond_item(session: Session, schedule_id: int, item_id: int, body: RespondIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    item = _get_item(session, schedule_id, item_id)
    item.response_choice = body.response_choice
    if body.reported_progress is not None:
        item.reported_progress = body.reported_progress
    if body.reported_rd is not None:
        item.reported_rd = body.reported_rd
    item.response_note = body.response_note
    if item.status == "pending":
        item.status = "responded"
    session.commit()
    return _list_out(session, schedule_id, view)


def update_handoff(session: Session, schedule_id: int, item_id: int, body: HandoffUpdateIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    item = _get_item(session, schedule_id, item_id)
    if item.kind != "handoff":
        raise ApiError(422, "invalid_kind", "핸드오프 항목만 체크리스트를 수정할 수 있습니다.")
    all_ok = body.pred_handover_ok and body.material and body.equipment and body.workforce
    payload = dict(item.payload_json or {})
    payload["pred_handover_ok"] = body.pred_handover_ok
    payload["checklist"] = {"material": body.material, "equipment": body.equipment, "workforce": body.workforce}
    item.payload_json = payload
    item.response_choice = "ready" if all_ok else "hold"
    item.response_note = body.response_note
    item.status = "responded"
    session.commit()
    return _list_out(session, schedule_id, view)


def _start_note(schedule: Schedule, stored: list[dict], activity: Activity, data_date: date) -> str | None:
    """실제 시작을 Data Date 로 넣을 때 반영 전 계산의 가장 이른 시작이 그보다 늦으면 승인 요약에 남길 한 줄. 늦은 까닭이
    달력뿐(Data Date 가 쉬는 날)이면 그렇게, 아니면 선행·제약 탓으로 적는다. 늦지 않거나 계산이 안 되면 None."""
    try:
        row = run(schedule, stored).rows.get(activity.id)
        workday = WorkCalendar(prepare_stored(schedule, stored).calendar).next_workday(data_date, activity.tags)
    except (ScheduleError, NoWorkdayError):
        return None
    if row is None or row.es <= data_date:
        return None
    head = f"{activity.id} {activity.name}: 실제 시작을 Data Date {data_date.isoformat()}로 넣었습니다 — "
    if row.es == workday:
        return head + f"그날은 달력상 쉬는 날이라 계산상 가장 이른 시작은 {row.es.isoformat()}입니다."
    return head + (f"선행 작업·제약으로 계산한 가장 이른 시작 {row.es.isoformat()}보다 이릅니다"
                   "(선행이 끝나기 전에 시작한 것으로 기록됩니다).")


def apply_item(session: Session, schedule_id: int, item_id: int, user: User) -> FieldListOut:
    """현장 회신/사진/의견을 실제 승인함(Approval) · 내 규칙 제안으로 반영."""
    view = _load_view(session, schedule_id)
    item = _get_item(session, schedule_id, item_id)
    if item.approval_id is not None:
        return _list_out(session, schedule_id, view)
    if item.kind == "photo" and (item.reported_progress is None or legacy_photo(item)):
        raise ApiError(422, "photo_unread", "판독하지 않은 사진은 승인함에 올릴 수 없습니다.")

    record = get_record(session, schedule_id)
    before, stored, n = load(session, schedule_id)

    if item.kind == "poll":
        note_text = item.response_note or item.prompt_text
        rule_text = f"[{item.activity_id} {item.trade}] {note_text}"[:190]
        cond = Condition(f"mine.{secrets.token_hex(3)}", "mine", "text_only", {}, rule_text, f"공종 의견 ({item.trade})")
        rule = {"scope": "schedule", "domain": record.domain, "schedule_id": schedule_id, "condition": cond.to_dict()}
        row = approvals.create(
            session,
            kind="rule",
            title=f"내 규칙 저장 — {rule_text}"[:100],
            reasons_json=["rule_save"],
            schedule_id=schedule_id,
            draft_id=None,
            base_version=n,
            summary_json={"rule": {"scope": "schedule", "domain": record.domain, "text": cond.text, "kind": "text_only", "params": {}}},
            diff_json=[],
            snapshot_json={},
            conditions_json=[],
            changes_json=[],
            status="pending",
            request=item.title,
            chat_session_id=None,
            requested_by=user.name,
            requested_kind="user",
            link_kind="rule",
            rule_json=rule,
        )
        item.approval_id = row.id
        item.status = "applied"
        session.commit()
        return _list_out(session, schedule_id, view)

    # checkin / photo / handoff -> 일정 변경 승인 상신. 지연 사건은 만들지 않는다(PM 결정 11-23, F2):
    # 늦음은 이 승인 건(진도·잔여일)이 승인되면 일정에 들어가고, 지연 기록은 본사가 지연 기록 창·대화에서 한다.
    # 현장 회신의 「오늘」은 일정의 Data Date 다(없을 때만 실제 오늘). 실제 오늘을 넣으면 Data Date 가 먼 일정에서
    # 시작일이 몇 달 어긋난다(재확인 #18). 넣는 실제 시작은 Data Date 를 넘지 않고, 선행이 허락하는 날보다 이르면 요약에 남긴다.
    pct_val = item.reported_progress if item.reported_progress is not None else 50
    progress_frac = round(max(0.0, min(1.0, pct_val / 100.0)), 2)
    data_date = before.data_date or context.today()
    new_acts = []
    notes: list[str] = []
    for a in before.activities:
        if a.id != item.activity_id:
            new_acts.append(a)
            continue
        actual_start = a.actual_start
        if actual_start is None and progress_frac > 0:
            actual_start = data_date
            if (note := _start_note(before, stored, a, data_date)) is not None:
                notes.append(note)
        actual_finish = data_date if progress_frac >= 1.0 else None
        rd_val = 0 if progress_frac >= 1.0 else (item.reported_rd if item.reported_rd is not None else (a.rd if a.rd is not None else a.od))
        new_acts.append(replace(a, progress=progress_frac, rd=rd_val, actual_start=actual_start, actual_finish=actual_finish))

    after = replace(before, data_date=data_date, activities=tuple(new_acts))
    if (problem := actual_dates_problem(before, after)) is not None:  # Data Date 뒤·착공일 앞 실적은 올리지 않는다
        raise ApiError(422, "actual_dates", actuals_blocked(after, problem))
    approval_row = None
    try:
        res = propose(
            session,
            Proposal(
                kind="change",
                title=f"[현장 반영] {item.activity_id} {item.activity_name} ({pct_val}%)"[:100],
                before=before,
                before_conditions=stored,
                after=after,
                after_conditions=stored,
                schedule_id=schedule_id,
                draft_id=None,
                base_version=n,
                requested_kind="user",
                requested_role=user.role,  # 현장 관리자가 올린 것은 승인 수준과 상관없이 늘 기다린다
            ),
            chat_session_id=None,
            requested_by=user.name,
            force_auto=False,
        )
        approval_row = res.row
        if notes:  # 승인함 요약에 보인다(화면 approvals/ApprovalDetail 의 알릴 것)
            summary = approval_row.summary_json
            approval_row.summary_json = {**summary, "notes": [*(summary.get("notes") or []), *notes]}
    except ProposalError:
        # 진도 수치 변화 없이 증빙·체크인만 확정할 때는 현장 확인 규칙 건으로 승인함에 남긴다.
        note_rule = f"[현장 확인] {item.activity_id} {item.activity_name} — {item.response_note or '현황 확인 완료'}"[:190]
        cond = Condition(f"mine.{secrets.token_hex(3)}", "mine", "text_only", {}, note_rule, "현장 모바일 확인")
        rule = {"scope": "schedule", "domain": record.domain, "schedule_id": schedule_id, "condition": cond.to_dict()}
        approval_row = approvals.create(
            session,
            kind="rule",
            title=f"현장 증빙 확인 — {item.activity_id}"[:100],
            reasons_json=["rule_save"],
            schedule_id=schedule_id,
            draft_id=None,
            base_version=n,
            summary_json={"rule": {"scope": "schedule", "domain": record.domain, "text": cond.text, "kind": "text_only", "params": {}}},
            diff_json=[],
            snapshot_json={},
            conditions_json=[],
            changes_json=[],
            status="pending",
            request=item.title,
            chat_session_id=None,
            requested_by=user.name,
            requested_kind="user",
            link_kind="rule",
            rule_json=rule,
        )

    item.approval_id = approval_row.id
    item.status = "applied"
    session.commit()
    return _list_out(session, schedule_id, view)
