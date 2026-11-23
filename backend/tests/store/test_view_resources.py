"""일정 화면 자료(store.view.view_data)의 자원 칸: 계산에 쓴 용량(조건 resource_cap 을 넣은 값)을 보인다(W3, 11-23).

간트 자원 줄이 「타워크레인 (1대)」인데 계산·답변은 조건의 2대 기준이던 결함.
"""

from app.core.model import Resource
from app.harness.conditions import Condition
from app.store.view import view_data
from tests.schedules import make, store, task

CRANE = Resource("crane", "타워크레인", "대", 1)
SCHEDULE = make([task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",))], resources=[CRANE])


def cap(n: int) -> dict:
    return Condition("in.resource_cap.crane", "input", "resource_cap", {"resource_id": "crane", "capacity": n}, "",
                     "프롬프트").to_dict()


def test_the_view_shows_the_capacity_the_conditions_compute_with(session):
    sid = store(session, SCHEDULE, conditions=[cap(2)])
    assert view_data(session, sid)["resources"] == [{"id": "crane", "name": "타워크레인", "unit": "대", "capacity": 2}]


def test_without_a_condition_the_stored_capacity_is_shown(session):
    sid = store(session, SCHEDULE)
    assert view_data(session, sid)["resources"] == [{"id": "crane", "name": "타워크레인", "unit": "대", "capacity": 1}]
