"""두 일정의 차이를 변경 이력 꼴 [{id, field, from, to}] 로 만든다.

- 칸이 달라진 액티비티: 칸마다 {id, field, from, to} (값은 JSON 꼴).
- 생긴·없어진 액티비티: {id, field: "activity", from: None, to: id} / {from: id, to: None}.
- 선행이 달라진 액티비티: {id: 후행, field: "predecessors", from: [{pred,type,lag}], to: [...]}.
일정 전체의 칸(달력·WBS·자원·시작일·Data Date)은 비교하지 않는다.
"""

from app.core.model import Relation, Schedule
from app.store.schedules import activity_json


def pred_json(r: Relation) -> dict:
    return {"pred": r.pred, "type": r.type, "lag": r.lag}


def field_changes(aid: str, old: dict, new: dict) -> list[dict]:
    """액티비티 JSON 두 개에서 달라진 칸마다 한 줄(new 에 있는 칸만, new 의 순서로)."""
    return [
        {"id": aid, "field": k, "from": old[k], "to": v}
        for k, v in new.items()
        if k != "id" and old.get(k) != v
    ]


def predecessors(schedule: Schedule, aid: str) -> list[dict]:
    return [pred_json(r) for r in schedule.relations if r.succ == aid]


def schedule_changes(old: Schedule, new: Schedule) -> list[dict]:
    """old → new 로 바뀐 것. 액티비티는 new 의 순서, 그다음 old 에만 있던 것."""
    olds = {a.id: activity_json(a) for a in old.activities}
    news = {a.id: activity_json(a) for a in new.activities}
    changes: list[dict] = []
    for aid in list(news) + [i for i in olds if i not in news]:
        if aid not in olds:
            changes.append({"id": aid, "field": "activity", "from": None, "to": aid})
        elif aid not in news:
            changes.append({"id": aid, "field": "activity", "from": aid, "to": None})
        else:
            changes += field_changes(aid, olds[aid], news[aid])
        before, after = predecessors(old, aid), predecessors(new, aid)
        if before != after:
            changes.append({"id": aid, "field": "predecessors", "from": before, "to": after})
    return changes
