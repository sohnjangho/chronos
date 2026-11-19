"""app.store.schedules.run(schedule, conditions) — 저장된 조건을 넣어 계산한다 (Task 7 fix round 1, F4)."""

from datetime import date

from app.core.model import Resource
from app.harness.conditions import Condition
from app.store.schedules import run
from tests.schedules import make, task

CRANE = Resource("crane", "타워크레인", "대", 1)
TWO_CRANE_TASKS = make(
    [task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",))], resources=[CRANE]
)


def cap(n: int, layer: str = "input", cid: str = "c") -> dict:
    return Condition(cid, layer, "resource_cap", {"resource_id": "crane", "capacity": n}, "", "프롬프트").to_dict()


def test_without_conditions_nothing_changes():
    assert run(TWO_CRANE_TASKS).finish == date(2027, 3, 8)
    assert run(TWO_CRANE_TASKS, []).finish == date(2027, 3, 8)


def test_stored_conditions_are_assembled_and_applied():
    assert run(TWO_CRANE_TASKS, [cap(2)]).finish == date(2027, 3, 3)
    # 입력(1대)이 분야 규칙(2대)을 이긴다
    assert run(TWO_CRANE_TASKS, [cap(2, "domain", "d"), cap(1, "input", "i")]).finish == date(2027, 3, 8)


def test_unreadable_stored_conditions_are_skipped():
    assert run(TWO_CRANE_TASKS, [{"id": "c1"}, {"x": [1, 2]}, cap(2)]).finish == date(2027, 3, 3)
