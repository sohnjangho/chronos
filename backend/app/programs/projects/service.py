"""프로젝트 관리: 목록·하나·고치기.

- 이름(schedules.name)과 소개(project_profiles 한 줄 — 없으면 모두 빈 값)를 한 번에 고친다. 이름은 일정 버전에 들지 않으므로
  버전을 만들지 않는다. 주소록·연락 기록·버전은 schedule_id 로 가리키므로 이름을 바꿔도 그대로다.
- 검사(칸마다): 길이 상한(LIMITS) · 줄 바꿈·보이지 않는 글자(주소록과 같은 contacts.service.check_texts) · 번호
  (voice.session.has_phone — redact.hide_phones 가 가리는 꼴과 대표번호. 통화 명세가 번호 든 글을 받지 않으므로 여기서 막는다).
  걸리면 422, 값은 싣지 않는다. 부를 이름이 다른 프로젝트의 부를 이름·다듬은 이름과 같으면 409 spoken_name_taken, 새 이름의
  다듬은 꼴이 그러면 409 name_taken(글에 겹치는 프로젝트 이름) — 견주기는 현장 맞추기와 같은 site_name.key. 이미 겹친 것·부를
  이름을 비워 겹치게 된 것은 거절하지 않고 same_name·same_as(겹치는 프로젝트 이름)로 알린다.
- 남기는 것: 소개 줄의 updated_at·updated_by, 서버 기록 한 줄(사용자 id·일정 id·바꾼 칸 이름 — 글은 싣지 않는다).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import site_name
from app.outreach.voice.session import has_phone
from app.programs.contacts.service import check_texts
from app.programs.projects.schemas import ProjectOut, ProjectPatch
from app.store.schedules import list_records
from app.store.tables import ProjectProfile, ScheduleRecord, User

logger = logging.getLogger(__name__)

NOT_FOUND = "프로젝트를 찾을 수 없습니다."
NO_NAME = "프로젝트 이름을 적어 주세요."
LINE_TEXT = "줄 바꿈이나 보이지 않는 제어 글자를 쓸 수 없습니다."
NO_PHONE = "전화번호는 적을 수 없습니다(에이전트가 통화·문자에서 읽는 글입니다)."
NAME_TAKEN = ("「{other}」 프로젝트가 이미 이 이름(날짜·판 표시를 뗀 이름)으로 불립니다. AI 가 두 현장을 구별할 수 있게 다른 "
              "이름을 적어 주세요.")
TAKEN = ("「{other}」 프로젝트가 이미 이 이름(부를 이름이나 날짜·판 표시를 뗀 이름)으로 불립니다. AI 가 두 현장을 같은 이름으로 "
         "부르지 않게 다른 이름을 적어 주세요.")
LIMITS = {"name": 120, "spoken_name": site_name.MAX_SPOKEN, "site_address": site_name.MAX_ADDRESS,
          "summary": site_name.MAX_SUMMARY, "client_builder": site_name.MAX_CLIENT}
LABELS = {"name": "프로젝트 이름", "spoken_name": "AI 가 부를 이름", "site_address": "현장 주소", "summary": "한 줄 소개",
          "client_builder": "발주처·시공사"}
PROFILE_FIELDS = ("spoken_name", "site_address", "summary", "client_builder")


def _record(session: Session, schedule_id: int) -> ScheduleRecord:
    record = session.get(ScheduleRecord, schedule_id)
    if record is None:
        raise ApiError(404, "not_found", NOT_FOUND)
    return record


def _out(session: Session, record: ScheduleRecord, same_as: str | None = None) -> ProjectOut:
    profile = session.get(ProjectProfile, record.id)
    values = {field: getattr(profile, field) if profile is not None else "" for field in PROFILE_FIELDS}
    return ProjectOut(id=record.id, name=record.name, spoken=site_name.spoken(session, record.id), **values,
                      updated_at=profile.updated_at if profile is not None else None,
                      updated_by=profile.updated_by if profile is not None else "", same_name=same_as is not None, same_as=same_as)


def _same_as(session: Session) -> dict[int, str]:
    """부를 이름(실제로 부르는 이름)이 다른 프로젝트의 부를 이름·다듬은 이름과 같은 프로젝트 → 겹치는 (첫) 프로젝트의 이름.
    예전에 겹쳐 들어온 것과 부를 이름을 비워 다듬은 이름으로 돌아간 것(거절하지 않고 알린다)."""
    records = list_records(session)
    keys = {record.id: _keys(session, record) for record in records}
    out = {}
    for record in records:
        spoken = keys[record.id][0]
        other = next((o for o in records if o.id != record.id and spoken in keys[o.id]), None) if spoken else None
        if other is not None:
            out[record.id] = other.name
    return out


def list_projects(session: Session) -> list[ProjectOut]:
    same = _same_as(session)
    return [_out(session, record, same.get(record.id)) for record in list_records(session)]


def get_project(session: Session, schedule_id: int) -> ProjectOut:
    return _out(session, _record(session, schedule_id), _same_as(session).get(schedule_id))


def _check(field: str, value: str) -> None:
    if len(value) > LIMITS[field]:
        raise ApiError(422, "text_too_long", f"{LABELS[field]}은(는) {LIMITS[field]}자까지입니다.",
                       detail={"field": field, "max": LIMITS[field]})
    try:
        check_texts({"name": value})  # 한 줄 글 검사(주소록 이름과 같은 규칙)
    except ApiError:
        raise ApiError(422, "invalid_text", f"{LABELS[field]}에는 {LINE_TEXT}", detail={"field": field}) from None
    if has_phone(value):
        raise ApiError(422, "phone_in_text", f"{LABELS[field]}에 {NO_PHONE}", detail={"field": field})


def _keys(session: Session, record: ScheduleRecord) -> tuple[str, str]:
    """(부를 이름, 다듬은 이름)의 견줄 꼴 — 현장 맞추기와 같은 기준(site_name.key)."""
    return site_name.key(site_name.spoken(session, record.id)), site_name.key(site_name.clean(record.name))


def _taken(session: Session, schedule_id: int, name: str) -> str | None:
    """그 이름이 다른 프로젝트의 부를 이름이나 다듬은 이름과 같으면 그 프로젝트의 이름."""
    want = site_name.key(name)
    if not want:
        return None
    return next((other.name for other in list_records(session)
                 if other.id != schedule_id and want in _keys(session, other)), None)


def patch_project(session: Session, schedule_id: int, body: ProjectPatch, user: User) -> ProjectOut:
    record = _record(session, schedule_id)
    sent = {field: getattr(body, field) for field in body.model_fields_set}
    if "name" in sent and not sent["name"]:
        raise ApiError(422, "invalid_name", NO_NAME, detail={"field": "name"})
    for field, value in sent.items():
        _check(field, value)
    # 부를 이름을 비우는 것은 거절하지 않는다 — 다듬은 이름이 겹치면 응답의 same_name·same_as 로 알린다
    if sent.get("spoken_name") and (other := _taken(session, schedule_id, sent["spoken_name"])):
        raise ApiError(409, "spoken_name_taken", TAKEN.format(other=other), detail={"field": "spoken_name"})
    if "name" in sent and sent["name"] != record.name and (other := _taken(session, schedule_id, site_name.clean(sent["name"]))):
        raise ApiError(409, "name_taken", NAME_TAKEN.format(other=other), detail={"field": "name"})
    profile = session.get(ProjectProfile, schedule_id)
    changed = [field for field, value in sent.items()
               if value != (record.name if field == "name" else getattr(profile, field, ""))]
    if not changed:
        return get_project(session, schedule_id)
    if profile is None:
        profile = ProjectProfile(schedule_id=schedule_id)
        session.add(profile)
    if "name" in changed:
        record.name = sent["name"]
    for field in changed:
        if field != "name":
            setattr(profile, field, sent[field])
    profile.updated_at, profile.updated_by = datetime.now(UTC), user.name
    session.commit()
    logger.info("프로젝트 정보 고침: 사용자 %s · 일정 %s · 칸 %s", user.id, schedule_id, ",".join(sorted(changed)))
    return get_project(session, schedule_id)
