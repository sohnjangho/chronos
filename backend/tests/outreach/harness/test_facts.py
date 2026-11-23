"""일정 사실(Task 67): 지금 버전의 보기 자료에서 다섯 칸만, 그리고 한 협력사·한 사람에게 말해도 되는 작업의 집합."""

from datetime import date

from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.outreach.harness import facts
from app.outreach.harness.facts import Fact
from app.store import view
from app.store.schedules import create_schedule
from app.store.tables import FieldItem
from tests.outreach.harness.test_tools import (
    MARK_A,
    MARK_B,
    call,
    firm,
    message,
    who,
    world,
)


def ids(found: list[Fact]) -> list[str]:
    return [fact.id for fact in found]


def test_find_gives_five_fields_from_the_current_view(session):
    w = world(session)

    found = facts.find(session, w.a, "철근 배근", allowed=None)

    assert found == [Fact("R", f"{MARK_A} 철근 배근", date(2027, 3, 1), date(2027, 3, 3), "on_plan")]
    assert {field for field in Fact.__dataclass_fields__} == {"id", "name", "start", "finish", "status"}
    every = {fact.id: fact for fact in facts.find(session, w.a, MARK_A, allowed=None)}
    assert (every["E"].start, every["E"].finish, every["Z"].finish) == (date(2027, 3, 4), date(2027, 3, 9), date(2027, 3, 9))
    other = {fact.id: fact for fact in facts.find(session, w.b, MARK_B, allowed=None)}
    assert (other["R"].start, other["R"].finish, other["E"].start, other["Z"].finish) == (
        date(2028, 5, 1), date(2028, 5, 3), date(2028, 5, 4), date(2028, 5, 9))


def test_find_matches_names_words_and_ids_of_that_schedule_only(session):
    w = world(session)

    assert ids(facts.find(session, w.a, "배근  철근", allowed=None)) == ["R"]  # 낱말이 모두 들어 있으면(차례 무관)
    assert ids(facts.find(session, w.a, "철근배근", allowed=None)) == ["R"]  # 띄어쓰기 무관
    assert ids(facts.find(session, w.a, "E", allowed=None)) == ["E"]  # 작업 id
    assert ids(facts.find(session, w.a, MARK_A, allowed=None)) == ["R", "E", "Z"]  # 시작일 순
    assert ids(facts.find(session, w.a, MARK_A, allowed=None, limit=2)) == ["R", "E"]
    assert facts.find(session, w.a, MARK_B, allowed=None) == []  # 다른 일정의 작업
    assert facts.find(session, w.a, "철근 전기", allowed=None) == []
    for nothing in ("", "   ", "없는 작업"):
        assert facts.find(session, w.a, nothing, allowed=None) == []


def test_find_puts_the_exact_name_first(session):
    schedule = Schedule(
        start=date(2027, 3, 1), calendar=CalendarSpec(days_per_week=5), wbs=(WbsNode("1", "골조", None),),
        activities=(Activity("A", "타설 준비", "task", "1", 2), Activity("B", "타설", "task", "1", 1)),
        relations=(Relation("A", "B"),), resources=(),
    )
    sid = create_schedule(session, name="순서", domain="construction", level="L3", schedule=schedule, conditions=[],
                          by_kind="agent", by_name="에이전트", note="처음")

    assert ids(facts.find(session, sid, "타설", allowed=None)) == ["B", "A"]


def test_find_stays_inside_the_allowed_set(session, monkeypatch):
    w = world(session)

    assert ids(facts.find(session, w.a, MARK_A, allowed={"R", "Z"})) == ["R", "Z"]
    assert facts.find(session, w.a, "마감", allowed={"R", "Z"}) == []
    assert facts.find(session, w.a, "E", allowed={"R", "Z"}) == []

    monkeypatch.setattr(view, "view_data", lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽지 않는다")))
    assert facts.find(session, w.a, MARK_A, allowed=set()) == []  # 빈 허용 집합은 「없음」 — 계산도 하지 않는다


def test_find_on_a_missing_schedule_is_empty(session):
    world(session)

    assert facts.find(session, 9999, "철근", allowed=None) == []
    assert facts.names(session, 9999) == {}


def test_allowed_for_trade_linked_and_milestones(session):
    """공종 말이 이름이나 WBS 이름에 든 작업 + 그 사람의 메시지·통화·현장 항목에 연결된 작업 + 마일스톤."""
    w = world(session)

    assert facts.allowed_for(session, w.a, [w.rebar_a.id], [w.park.id]) == {"R", "Z"}  # 이름에 「철근」 + 마일스톤
    assert facts.allowed_for(session, w.a, [w.mep_a.id], [w.lee.id]) == {"E", "Z"}  # WBS 이름 「설비」

    message(session, w.lee, activity_id="R")  # 다른 사람에게 간 것은 열어 주지 않는다
    assert facts.allowed_for(session, w.a, [w.rebar_a.id], [w.park.id]) == {"R", "Z"}

    message(session, w.park, activity_id="E")
    assert facts.allowed_for(session, w.a, [w.rebar_a.id], [w.park.id]) == {"R", "E", "Z"}
    assert facts.linked(session, w.a, [w.park.id]) == {"E"}


def test_allowed_for_follows_calls_and_field_items(session):
    w = world(session)
    kim = who(session, w.rebar_a, "김철근", "01000000122")
    item = FieldItem(schedule_id=w.a, kind="checkin", activity_id="E", activity_name="마감 작업", trade="설비", title="체크인")
    session.add(item)
    session.flush()

    elsewhere = FieldItem(schedule_id=w.b, kind="checkin", activity_id="R", activity_name="철근 배근", trade="철근", title="체크인")
    session.add(elsewhere)
    session.flush()

    call(session, w.park, activity_id="E")
    message(session, kim, field_item_id=item.id)
    message(session, w.lee, field_item_id=elsewhere.id)  # 다른 현장의 현장 항목 — 따라가지 않는다

    assert facts.linked(session, w.a, [w.park.id]) == {"E"}
    assert facts.linked(session, w.a, [kim.id]) == {"E"}
    assert facts.linked(session, w.a, []) == set()
    assert facts.linked(session, w.a, [w.lee.id]) == set()


def test_allowed_for_ignores_companies_of_other_schedules(session):
    """굳힌 일정의 협력사·연락처만 본다 — 다른 일정에 있는 같은 번호의 협력사 id 는 버린다."""
    w = world(session)
    mep_b = firm(session, w.b, "나래설비", "설비")  # 나래 현장의 「설비」 협력사 — 가람 현장의 설비 작업을 열어 주지 않는다
    lee_b = who(session, mep_b, "이설비", "01000000188")
    message(session, lee_b, activity_id="E")  # 나래 현장의 E — id 가 같아도 가람 현장의 E 가 아니다

    alone = facts.allowed_for(session, w.a, [w.rebar_a.id], [w.park.id])
    mixed = facts.allowed_for(session, w.a, [w.rebar_a.id, mep_b.id, w.elec_b.id], [w.park.id, lee_b.id, w.choi.id])

    assert alone == mixed == {"R", "Z"}
    assert facts.allowed_for(session, w.a, [mep_b.id], [lee_b.id]) == set()  # 그 일정의 협력사가 없으면 마일스톤도 없다
    assert facts.allowed_for(session, w.a, [], []) == set()
    assert facts.allowed_for(session, w.a, [w.rebar_a.id], []) == {"R", "Z"}
    assert facts.linked(session, w.a, [lee_b.id]) == set()

    # 어긋난 줄(일정과 연락처가 서로 다른 프로젝트)도 열어 주지 않는다 — 일정과 연락처를 둘 다 본다
    message(session, lee_b, schedule_id=w.a, activity_id="E")  # 가람 현장 줄인데 나래 현장 사람
    message(session, w.park, schedule_id=w.b, activity_id="E")  # 가람 현장 사람인데 나래 현장 줄
    assert facts.linked(session, w.a, [lee_b.id]) == set()
    assert facts.linked(session, w.a, [w.park.id]) == set()
    assert facts.allowed_for(session, w.a, [w.rebar_a.id], [w.park.id, lee_b.id]) == {"R", "Z"}


def test_allowed_for_reads_trade_words_and_parent_wbs_names(session):
    schedule = Schedule(
        start=date(2027, 3, 1), calendar=CalendarSpec(days_per_week=5),
        wbs=(WbsNode("1", "골조", None), WbsNode("2", "기계 설비", None), WbsNode("2.1", "배관", "2")),
        activities=(Activity("A", "형틀 조립", "task", "1", 2), Activity("B", "3층 슬래브", "task", "2.1", 1),
                    Activity("C", "콘크리트 타설", "task", "1", 1), Activity("S", "착공", "start_ms", "1", 0)),
        relations=(Relation("S", "A"), Relation("A", "B"), Relation("B", "C")), resources=(),
    )
    sid = create_schedule(session, name="공종", domain="construction", level="L3", schedule=schedule, conditions=[],
                          by_kind="agent", by_name="에이전트", note="처음")

    def allowed(trade: str) -> set[str]:
        return facts.allowed_for(session, sid, [firm(session, sid, f"협력사 {trade}", trade).id], [])

    assert allowed("철근·형틀") == {"A", "S"}  # 여러 공종을 적은 협력사
    assert allowed("거푸집, 형틀 및 타설") == {"A", "C", "S"}
    assert allowed("설비") == {"B", "S"}  # 윗 WBS 이름
    assert allowed("") == {"S"} and allowed("층") == {"S"}  # 공종이 비었거나 한 글자면 공종으로 맞추지 않는다
    assert facts.names(session, sid) == {"A": "형틀 조립", "B": "3층 슬래브", "C": "콘크리트 타설", "S": "착공"}
