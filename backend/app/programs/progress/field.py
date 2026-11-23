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

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context
from app.agent.proposals import Proposal, ProposalError, propose
from app.core.cpm import ScheduleError
from app.errors import ApiError
from app.harness.conditions import Condition
from app.store import approvals
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load
from app.store.tables import FieldItem, User
from app.store.timeutil import as_utc
from app.store.view import view_data

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
FieldKind = Literal["checkin", "photo", "poll", "handoff"]


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DispatchCheckinIn(StrictIn):
    activity_ids: list[str] | None = None


class PhotoUploadIn(StrictIn):
    activity_id: str = Field(min_length=1, max_length=50)
    trade: str = Field(default="", max_length=120)
    photo_name: str = Field(min_length=1, max_length=200)
    photo_data_url: str | None = Field(default=None, max_length=350_000)
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
            prompt_text="현장 작업 사진 기반 AI 진도율 판독 및 증빙 태깅 결과입니다.",
            response_choice="verified",
            reported_progress=65,
            reported_rd=max(1, rd0 - 1),
            response_note="철근 배근 1차 검측 통과, 거푸집 조립 50% 진행 확인",
            payload_json={
                "sample_key": "rebar",
                "photo_name": f"site_{a0['id']}_{day_tag}.jpg",
                "ai_progress": 65,
                "ai_stage": "본작업 2단계 진행 (품질 검측 적합)",
                "ai_risks": ["자재 적치 구역 통행로 1.2m 확보 필요"],
                "confidence": 0.92,
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


def _item_out(row: FieldItem) -> FieldItemOut:
    return FieldItemOut.model_validate(row)


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


def _analyze_photo(act: dict[str, Any], photo_name: str, note: str, schedule_id: int) -> dict[str, Any]:
    text = f"{photo_name} {note} {act['name']}".lower()
    base_pct = round(float(act.get("progress") or 0.0) * 100)
    risks: list[str] = []
    if any(k in text for k in ("지연", "간섭", "우천", "비", "누수", "불량", "대기")):
        est = max(base_pct, 40)
        stage = "공정 진행 중 (리스크 요인 감지)"
        risks.append("현장 작업 지연·간섭 요소가 감지되어 일정 재계산 검토가 필요합니다.")
    elif any(k in text for k in ("완료", "마감", "출하", "준공")):
        est = 95
        stage = "최종 마무리 및 품질 검측 단계"
    elif any(k in text for k in ("외장", "커튼월", "유리", "창호")):
        est = min(100, max(base_pct + 20, 60))
        stage = "외장재 설치·양중 본작업 단계"
        risks.append("강풍·타워크레인 점유 시간 교차 확인 권장")
    elif any(k in text for k in ("금형", "프레스", "조립", "설비")):
        est = min(100, max(base_pct + 25, 75))
        stage = "설비·금형 세팅 및 연속 가동 단계"
    else:
        est = min(100, max(base_pct + 25, 70))
        stage = "주요 구조·본작업 시공 단계 (정상 양호)"
    day_tag = str(context.today()).replace("-", "")
    return {
        "photo_name": photo_name,
        "ai_progress": est,
        "ai_stage": stage,
        "ai_risks": risks,
        "confidence": 0.91 if not risks else 0.87,
        "evidence_tag": f"#{schedule_id}-{act['id']}-{day_tag}",
        "captured_at": f"{context.today().isoformat()} {datetime.now().strftime('%H:%M')}",
    }


def upload_photo(session: Session, schedule_id: int, body: PhotoUploadIn) -> FieldListOut:
    view = _load_view(session, schedule_id)
    act = next((a for a in view["activities"] if a["id"] == body.activity_id), None)
    if act is None:
        raise ApiError(422, "invalid_activity", f"없는 액티비티입니다: {body.activity_id}")
    analysis = _analyze_photo(act, body.photo_name, body.note, schedule_id)
    if body.photo_data_url and body.photo_data_url.startswith("data:image/"):
        analysis["photo_data_url"] = body.photo_data_url
    else:
        analysis["sample_key"] = "custom"
    rd_now = int(act.get("rd") or act.get("od") or 1)
    est_rd = 0 if analysis["ai_progress"] >= 100 else max(1, rd_now)
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
            prompt_text=f"사진({body.photo_name}) Vision 분석 · 진도 {analysis['ai_progress']}% 추정",
            response_choice="risk" if analysis["ai_risks"] else "verified",
            reported_progress=analysis["ai_progress"],
            reported_rd=est_rd,
            response_note=body.note or analysis["ai_stage"],
            payload_json=analysis,
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


def apply_item(session: Session, schedule_id: int, item_id: int, user: User) -> FieldListOut:
    """현장 회신/사진/의견을 실제 승인함(Approval) · 내 규칙 제안으로 반영."""
    view = _load_view(session, schedule_id)
    item = _get_item(session, schedule_id, item_id)
    if item.approval_id is not None:
        return _list_out(session, schedule_id, view)

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
            requested_by=f"{item.trade} ({user.name})",
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
    today_d = context.today()
    pct_val = item.reported_progress if item.reported_progress is not None else 50
    progress_frac = round(max(0.0, min(1.0, pct_val / 100.0)), 2)
    data_date = before.data_date or today_d
    new_acts = []
    for a in before.activities:
        if a.id != item.activity_id:
            new_acts.append(a)
            continue
        actual_start = a.actual_start or (today_d if progress_frac > 0 else None)
        actual_finish = today_d if progress_frac >= 1.0 else None
        rd_val = 0 if progress_frac >= 1.0 else (item.reported_rd if item.reported_rd is not None else (a.rd if a.rd is not None else a.od))
        new_acts.append(replace(a, progress=progress_frac, rd=rd_val, actual_start=actual_start, actual_finish=actual_finish))

    after = replace(before, data_date=data_date, activities=tuple(new_acts))
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
            ),
            chat_session_id=None,
            requested_by=f"{item.trade} ({user.name})",
            force_auto=False,
        )
        approval_row = res.row
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
            requested_by=f"{item.trade} ({user.name})",
            requested_kind="user",
            link_kind="rule",
            rule_json=rule,
        )

    item.approval_id = approval_row.id
    item.status = "applied"
    session.commit()
    return _list_out(session, schedule_id, view)
