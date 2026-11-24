"""시연 씨앗(app.seed): 가상 예시 일정 「5층 사무동 신축」을 만든다. 여러 번 돌려도 같다. LLM 을 부르지 않는다."""

from datetime import date

from sqlalchemy import func, select

from app import seed
from app.store.schedules import load, run
from app.store.tables import ChangeLog, LlmCall, ScheduleRecord, ScheduleVersion
from app.store.versions import list_versions

NAME = "5층 사무동 신축"


def _demo(session) -> ScheduleRecord:
    rows = session.scalars(select(ScheduleRecord).where(ScheduleRecord.name == NAME)).all()
    assert len(rows) == 1
    return rows[0]


def _with_crane(conditions: list[dict], capacity: int) -> list[dict]:
    return [
        {**c, "params": {**c["params"], "capacity": capacity}} if c["id"] == seed.CRANE_CONDITION else c
        for c in conditions
    ]


def test_demo_schedule_shape(session):
    seed.seed_demo(session)
    record = _demo(session)
    assert (record.domain, record.level, record.current_version) == ("construction", "L3", 2)
    schedule, conditions, _ = load(session, record.id)
    assert 55 <= len(schedule.activities) <= 65
    assert len(conditions) == 14
    assert [r.id for r in schedule.resources] == ["tower_crane", "rebar_crew", "form_crew"]
    assert {c["layer"] for c in conditions} == {"base", "domain", "input"}
    assert any(not c["checkable"] for c in conditions if c["layer"] == "input")  # 「자동 점검 안 됨」 보이기
    run(schedule, conditions)  # 계산된다


def test_demo_has_some_actuals_with_a_data_date(session):
    seed.seed_demo(session)
    schedule, _, _ = load(session, _demo(session).id)
    assert schedule.data_date == seed.DATA_DATE
    done = [a for a in schedule.activities if a.actual_finish is not None]
    going = [a for a in schedule.activities if a.actual_start is not None and a.actual_finish is None]
    assert done and going and len(done) + len(going) < len(schedule.activities) // 2
    assert all(a.actual_start <= seed.DATA_DATE for a in done + going)
    assert all(a.actual_finish <= seed.DATA_DATE for a in done)


def test_version_one_is_the_first_plan_without_actuals(session):
    seed.seed_demo(session)
    record = _demo(session)
    assert [(v.n, v.is_plan) for v in list_versions(session, record.id)] == [(2, False), (1, True)]
    first, _, _ = load(session, record.id, 1)
    assert first.data_date is None and all(a.actual_start is None for a in first.activities)
    assert session.scalar(select(func.count()).select_from(ChangeLog).where(ChangeLog.schedule_id == record.id)) == 1


def test_two_tower_cranes_finish_earlier(session):
    """조건·규칙에서 크레인을 2대로 바꾸면 준공이 당겨진다(시연 장면)."""
    seed.seed_demo(session)
    schedule, conditions, _ = load(session, _demo(session).id)
    assert run(schedule, _with_crane(conditions, 2)).finish < run(schedule, _with_crane(conditions, 1)).finish


def test_seed_twice_gives_the_same_result(session):
    seed.seed_demo(session)
    first = load(session, _demo(session).id)
    seed.seed_demo(session)
    again = _demo(session)
    assert load(session, again.id) == first
    assert session.scalar(select(func.count()).select_from(ScheduleVersion).where(ScheduleVersion.schedule_id == again.id)) == 2
    assert session.scalar(select(func.count()).select_from(ScheduleVersion)) == 3  # 옛 버전은 지웠다(사무동 2 · 공장 1)


def test_seed_leaves_other_schedules_and_calls_no_llm(session, sid):
    seed.seed_demo(session)
    seed.seed_demo(session)
    assert session.get(ScheduleRecord, sid) is not None
    assert session.scalar(select(func.count()).select_from(LlmCall)) == 0


def test_cli_demo(client, session):
    assert seed.main(["demo"]) == 0
    session.expire_all()
    assert _demo(session).current_version == 2


def test_cli_unknown_name(capsys):
    assert seed.main(["nothing"]) == 2
    assert "demo" in capsys.readouterr().err


def test_data_date_is_after_start(session):
    seed.seed_demo(session)
    schedule, _, _ = load(session, _demo(session).id)
    assert schedule.start == date(2027, 3, 2) < seed.DATA_DATE


# ── 시연 일정을 다시 만들 때 연락 자료(계획 4 Task 61) ──────────────────────


def test_reseed_clears_the_old_address_book_but_keeps_do_not_contact(session):
    from app.store import contacts, outreach
    from app.store.tables_outreach import Contact, ContactCompany

    old = seed.seed_demo(session)[0]
    company = ContactCompany(schedule_id=old, name="가상건설")
    session.add(company)
    session.flush()
    session.add(Contact(schedule_id=old, company_id=company.id, name="김가상", phone="01000000199",
                        do_not_contact=True))
    session.commit()

    again = seed.seed_demo(session)[0]

    assert again == old  # 같은 id 가 다시 쓰인다
    assert contacts.listed(session, again, include_hidden=True) == []
    assert outreach.is_do_not_contact(session, "010-0000-0199") is True


def test_seed_module_registers_outreach_tables():
    """`python -m app.seed demo` 는 app.db 를 import 하지 않는다 — seed 가 스스로 연락 표를 올려야 지운다."""
    import subprocess
    import sys
    from pathlib import Path

    code = "import app.seed; from app.store.tables import Base; print('contacts' in Base.metadata.tables)"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "True"


def test_reseed_finds_the_demo_by_its_marker_not_its_name(session, sid):
    """시연 일정을 프로젝트 관리에서 이름을 바꿔도 다시 심으면 그 일정을 지운다 · 같은 이름의 사용자 일정은 남긴다."""
    first = seed.seed_demo(session)
    session.get(ScheduleRecord, first[0]).name = "이름을 바꾼 시연 일정"
    session.get(ScheduleRecord, sid).name = NAME  # 사용자가 만든 같은 이름의 일정
    session.commit()

    again = seed.seed_demo(session)

    session.expire_all()
    assert session.get(ScheduleRecord, first[0]) is None or first[0] in again
    assert session.scalars(select(ScheduleRecord.name).where(ScheduleRecord.name == "이름을 바꾼 시연 일정")).all() == []
    assert session.get(ScheduleRecord, sid).name == NAME
