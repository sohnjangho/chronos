"""사용자 고침을 일정에 적용한다. 계산·저장은 하지 않는다.

각 함수는 (새 일정, 바뀐 것 [{id, field, from, to}], 한국어 설명) 을 돌려준다.
바뀐 것이 없으면 changes 가 빈 목록이다.
"""

import re
from dataclasses import replace
from typing import Any, NamedTuple

from app.core.model import Activity, Relation, Schedule
from app.errors import ApiError
from app.programs.schedule.schemas import ActivityCreate, RelationIn
from app.store.diff import field_changes, pred_json
from app.store.schedules import activity_from_json, activity_json

LABELS = {
    "name": "이름",
    "kind": "종류",
    "wbs": "WBS",
    "od": "기간",
    "rd": "남은 기간",
    "progress": "진행률",
    "actual_start": "실제 시작",
    "actual_finish": "실제 종료",
    "constraint": "제약",
    "tags": "꼬리표",
    "resources": "자원",
}

_GENERATED_ID = re.compile(r"A(\d{4,})")
_FIRST_ID_BASE = 1000  # 처음 만드는 id 는 A1010


class Edit(NamedTuple):
    schedule: Schedule
    changes: list[dict]
    note: str


def _find(schedule: Schedule, aid: str) -> Activity:
    for a in schedule.activities:
        if a.id == aid:
            return a
    raise ApiError(404, "not_found", "액티비티를 찾을 수 없습니다.", {"activity": aid})


def _show(value: Any) -> str:
    if value is None or value == []:
        return "없음"
    if isinstance(value, dict):  # 제약
        return f"{value['type']} {value['date']}"
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


def _relations_text(rels: list[Relation]) -> str:
    parts = [f"{r.pred}({r.type}{r.lag:+d})" if r.lag else f"{r.pred}({r.type})" for r in rels]
    return ", ".join(parts) or "없음"


def _invalid(message: str, detail: dict) -> ApiError:
    return ApiError(422, "invalid_activity", message, detail)


def _check(schedule: Schedule, a: Activity, fields: set[str]) -> None:
    """고친 뒤의 액티비티 a 를 확인한다. wbs·resources 는 fields 에 있을 때만 본다."""
    if a.actual_start and a.actual_finish and a.actual_finish < a.actual_start:
        raise _invalid(
            "실제 종료일이 실제 시작일보다 앞설 수 없습니다.",
            {"activity": a.id, "actual_start": a.actual_start.isoformat(),
             "actual_finish": a.actual_finish.isoformat()},
        )
    if "wbs" in fields and a.wbs not in {w.code for w in schedule.wbs}:
        raise _invalid(f"없는 WBS 코드입니다: {a.wbs}", {"activity": a.id, "wbs": a.wbs})
    known = {r.id for r in schedule.resources}
    missing = [r for r in a.resources if r not in known] if "resources" in fields else []
    if missing:
        raise _invalid(
            f"없는 자원입니다: {', '.join(missing)}", {"activity": a.id, "resources": missing}
        )


def patch_activity(schedule: Schedule, aid: str, fields: dict[str, Any]) -> Edit:
    """fields 는 JSON 꼴 값(날짜는 ISO 문자열). 보낸 칸만 바꾼다."""
    old = activity_json(_find(schedule, aid))
    changes = field_changes(aid, old, fields)
    new = activity_from_json({**old, **fields})
    _check(schedule, new, set(fields))
    acts = tuple(new if a.id == aid else a for a in schedule.activities)
    note = f"{aid} " + ", ".join(
        f"{LABELS[c['field']]} {_show(c['from'])} → {_show(c['to'])}" for c in changes
    )
    return Edit(replace(schedule, activities=acts), changes, note)


def next_id(schedule: Schedule) -> str:
    """A + 네 자리 이상, 지금 가장 큰 A숫자 id 위의 다음 10 단위(A1010, A1020, …, A9990, A10000)."""
    nums = [_FIRST_ID_BASE]
    for a in schedule.activities:
        m = _GENERATED_ID.fullmatch(a.id)
        if m:
            nums.append(int(m.group(1)))
    return f"A{(max(nums) // 10 + 1) * 10:04d}"


def add_activity(schedule: Schedule, body: ActivityCreate) -> Edit:
    """after 를 주면 그 액티비티 바로 뒤에 넣고 after → 새 액티비티 FS 관계를 단다."""
    aid = body.id or next_id(schedule)
    new = Activity(id=aid, name=body.name, kind=body.kind, wbs=body.wbs, od=body.od)
    _check(schedule, new, {"wbs"})
    acts = list(schedule.activities)
    at = next((k + 1 for k, a in enumerate(acts) if a.id == body.after), len(acts))
    acts.insert(at, new)
    rels = schedule.relations
    changes = [{"id": aid, "field": "activity", "from": None, "to": activity_json(new)}]
    note = f"{aid} 추가"
    if body.after is not None:
        rel = Relation(body.after, aid)
        rels += (rel,)
        changes.append({"id": aid, "field": "predecessors", "from": [], "to": [pred_json(rel)]})
        note += f" ({body.after} 뒤)"
    return Edit(replace(schedule, activities=tuple(acts), relations=rels), changes, note)


def delete_activity(schedule: Schedule, aid: str) -> Edit:
    """액티비티와, 그것을 가리키는 관계를 모두 지운다."""
    gone = _find(schedule, aid)
    removed = [r for r in schedule.relations if aid in (r.pred, r.succ)]
    changes = [{"id": aid, "field": "activity", "from": activity_json(gone), "to": None}]
    changes += [
        {"id": r.succ, "field": "relation", "from": {"succ": r.succ, **pred_json(r)}, "to": None}
        for r in removed
    ]
    out = replace(
        schedule,
        activities=tuple(a for a in schedule.activities if a.id != aid),
        relations=tuple(r for r in schedule.relations if r not in removed),
    )
    return Edit(out, changes, f"{aid} 삭제")


def set_predecessors(schedule: Schedule, aid: str, items: list[RelationIn]) -> Edit:
    """aid 가 후행인 관계를 items 로 모두 바꾼다."""
    _find(schedule, aid)
    old = [r for r in schedule.relations if r.succ == aid]
    new = [Relation(i.pred, aid, i.type, i.lag) for i in items]
    if old == new:
        return Edit(schedule, [], "")
    rels = tuple(r for r in schedule.relations if r.succ != aid) + tuple(new)
    changes = [
        {
            "id": aid,
            "field": "predecessors",
            "from": [pred_json(r) for r in old],
            "to": [pred_json(r) for r in new],
        }
    ]
    note = f"{aid} 선행 {_relations_text(old)} → {_relations_text(new)}"
    return Edit(replace(schedule, relations=rels), changes, note)
