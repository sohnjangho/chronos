"""일정 고침 목록(op)의 입력 모양과 그것을 일정 사본에 넣는 방법. 도구(out.submit_change·scenario.create)가 같이 쓴다.

op 는 차례대로 넣는다. 계산 확인은 하지 않는다(부르는 쪽이 run 으로 본다). 잘못된 op 는 OpError(한국어 message) —
도구는 ToolError 로, API 는 422 invalid_change 로 바꾼다.
"""

from dataclasses import replace
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.generation_build import MAX_LAG, MAX_OD
from app.core.model import Activity, Relation, Schedule
from app.harness.conditions import Condition, ConditionFormatError

Od = Annotated[int, Field(ge=0, le=MAX_OD, strict=True)]


class OpError(ValueError):
    """넣을 수 없는 op 나 조건. message 는 화면·모델에 그대로 보일 한국어."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PredIn(Strict):
    pred: str = Field(min_length=1, description="선행 액티비티 id")
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag: int = Field(default=0, ge=-MAX_LAG, le=MAX_LAG, strict=True)


class UpdateOp(Strict):
    """보낸 칸만 바꾼다. preds 를 보내면 이 액티비티의 선행 관계를 모두 그것으로 바꾼다."""

    op: Literal["update_activity"]
    id: str
    od: Od | None = Field(default=None, description="기간(근무일)")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    preds: list[PredIn] | None = None


class NewActivity(Strict):
    id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    od: Od
    preds: list[PredIn]
    wbs: str | None = Field(default=None, description="없으면 첫 선행의 WBS")
    resources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class AddOp(Strict):
    op: Literal["add_activity"]
    activity: NewActivity


class DeleteOp(Strict):
    """액티비티와 그것을 가리키는 관계를 지운다."""

    op: Literal["delete_activity"]
    id: str


Op = Annotated[UpdateOp | AddOp | DeleteOp, Field(discriminator="op")]


def _index(acts: list[Activity], aid: str) -> int:
    for n, a in enumerate(acts):
        if a.id == aid:
            return n
    raise OpError(f"없는 액티비티입니다: {aid}")


def _relations(aid: str, preds: list[PredIn]) -> list[Relation]:
    return [Relation(p.pred, aid, p.type, p.lag) for p in preds]


def _new_activity(schedule: Schedule, acts: list[Activity], new: NewActivity) -> Activity:
    wbs_of = {a.id: a.wbs for a in acts}
    first = next((wbs_of[p.pred] for p in new.preds if p.pred in wbs_of), None)
    wbs = new.wbs or first or (schedule.wbs[0].code if schedule.wbs else "")
    if new.wbs is not None and new.wbs not in {w.code for w in schedule.wbs}:
        raise OpError(f"없는 WBS 코드입니다: {new.wbs}")
    missing = [r for r in new.resources if r not in {x.id for x in schedule.resources}]
    if missing:
        raise OpError(f"없는 자원입니다: {', '.join(missing)}")
    return Activity(new.id, new.name, "task", wbs, new.od, resources=tuple(new.resources), tags=tuple(new.tags))


def apply_ops(schedule: Schedule, ops: list[UpdateOp | AddOp | DeleteOp]) -> Schedule:
    """고침을 차례대로 일정 사본에 넣는다. 계산 확인은 하지 않는다."""
    acts, rels = list(schedule.activities), list(schedule.relations)
    for op in ops:
        if isinstance(op, AddOp):
            acts.append(_new_activity(schedule, acts, op.activity))
            rels += _relations(op.activity.id, op.activity.preds)
            continue
        n = _index(acts, op.id)
        if isinstance(op, DeleteOp):
            del acts[n]
            rels = [r for r in rels if op.id not in (r.pred, r.succ)]
            continue
        a = acts[n]
        acts[n] = replace(a, od=a.od if op.od is None else op.od, name=op.name or a.name)
        if op.preds is not None:
            rels = [r for r in rels if r.succ != op.id] + _relations(op.id, op.preds)
    ids = {a.id for a in acts}
    missing = sorted({r.pred for r in rels if r.pred not in ids})  # 없는 id·지운 액티비티를 선행으로 가리킴
    if missing:
        raise OpError(f"없는 액티비티를 가리킵니다: {', '.join(missing)}")
    return replace(schedule, activities=tuple(acts), relations=tuple(rels))


def with_inputs(stored: list[dict], given: list[dict]) -> list[dict]:
    """저장된 조건에서 입력 겹(layer input)만 given 으로 바꾼다(다른 겹은 그 자리 그대로, 새 입력은 끝에)."""
    fresh = []
    for d in given:
        try:
            c = Condition.from_dict(d)
        except ConditionFormatError as e:
            raise OpError(f"조건을 읽을 수 없습니다: {e.condition_id}: {e.message}") from None
        if c.layer != "input":
            raise OpError(f"입력 조건(layer input)만 바꿀 수 있습니다: {c.id}")
        fresh.append(c.to_dict())
    return [d for d in stored if not (isinstance(d, dict) and d.get("layer") == "input")] + fresh
