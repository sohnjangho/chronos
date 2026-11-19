"""하네스 시험 일정. 모두 2027-03-01(월) 시작, 주 5일."""

import pytest

from app.core.model import Relation, Resource
from tests.schedules import make, task

CRANE = Resource("crane", "타워크레인", "대", 1)


@pytest.fixture
def s_finish_0305():
    """A(3일) → B(2일). A 03.01~03.03, B 03.04~03.05. 준공 03.05(금)."""
    return make([task("A", 3), task("B", 2)], [Relation("A", "B")])


@pytest.fixture
def two_crane_tasks():
    """A·B(각 3일)가 같은 날 시작하고 크레인(1대)을 같이 쓴다.

    맞추기 전에는 둘 다 03.01~03.03, 맞춘 뒤에는 B 가 03.04~03.08(월).
    """
    return make(
        [task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",))],
        resources=[CRANE],
    )


@pytest.fixture
def pour_then_next_day():
    """타설 P(2일, 03.01~03.02) 바로 다음 근무일에 N(1일, 03.03)이 시작한다."""
    return make([task("P", 2, tags=("타설",)), task("N", 1)], [Relation("P", "N")])


@pytest.fixture
def cyclic():
    return make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])
