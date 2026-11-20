"""시연용 씨앗 자료. `python -m app.seed demo` 로 가상 예시 일정을 만든다.

- 지금 있는 것: 「5층 사무동 신축」(건설·L3) — 액티비티 60개, 조건 14개(기본 4·분야 4·입력 6), 주요 자원 3개.
  버전 1 = 처음 계획(실적 없음, 「처음 계획」 표시), 버전 2 = 실적 일부와 Data Date 를 넣은 것.
- 여러 번 돌려도 같다: 같은 이름의 일정과 그 일정에 딸린 줄을 먼저 지우고 새로 만든다. 다른 일정은 건드리지 않는다.
- LLM 을 부르지 않는다. 날짜는 넣지 않고(시작일·실적만) 계산은 core 가 한다.
- 일정을 더하려면 함수 하나(세션 → 일정 id)를 만들어 DEMO 에 넣는다(예: 생산 분야 일정).
- 사람·회사·현장은 모두 가상이다.
"""

import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date

from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.model import Activity, CalendarSpec, Relation, Resource, Schedule, WbsNode
from app.domains.loader import load as load_pack
from app.harness.assemble import assemble, holidays_of
from app.harness.conditions import Condition
from app.store.diff import schedule_changes
from app.store.schedules import create_schedule, run
from app.store.tables import Base, ChatSession, ScheduleRecord
from app.store.upgrade import add_missing_columns
from app.store.versions import mark_plan, save_new_version

BY = "시연 자료"
OFFICE = "5층 사무동 신축"
START = date(2027, 3, 2)  # 3월 1일(삼일절) 다음 날 착공
DATA_DATE = date(2027, 4, 17)  # 실적 기준일(토요일, 주 6일 달력의 근무일)
CRANE_CONDITION = "in.resource_cap.tower_crane"

# ── 「5층 사무동 신축」 자료 ─────────────────────────────────────────────

_WBS = (
    ("1", "기초", None), ("1.1", "착공 준비·가설", "1"), ("1.1.1", "가설 울타리·현장 사무실", "1.1"),
    ("1.1.2", "타워크레인 설치", "1.1"), ("1.2", "흙막이·터파기", "1"), ("1.2.1", "흙막이 설치", "1.2"),
    ("1.2.2", "터파기·잔토 처리", "1.2"), ("1.3", "기초 공사", "1"), ("1.3.1", "버림 콘크리트", "1.3"),
    ("1.3.2", "기초 철근 배근·거푸집", "1.3"), ("1.3.3", "기초 콘크리트 타설", "1.3"),
    ("2", "골조", None), ("2.2", "지상층 골조", "2"), ("2.2.1", "기준층 철근 배근", "2.2"),
    ("2.2.2", "기준층 거푸집", "2.2"), ("2.2.3", "기준층 콘크리트 타설", "2.2"),
    ("2.3", "옥탑·지붕", "2"), ("2.3.1", "옥탑 골조", "2.3"), ("2.3.2", "지붕 방수", "2.3"),
    ("3", "외장·설비", None), ("3.1", "외장", "3"), ("3.1.1", "외벽 단열·방수", "3.1"),
    ("3.1.2", "커튼월·외장 패널", "3.1"), ("3.1.3", "창호", "3.1"), ("3.2", "기계 설비", "3"),
    ("3.2.1", "설비 배관", "3.2"), ("3.2.2", "공조·덕트·소방", "3.2"), ("3.2.3", "승강기 설치", "3.2"),
    ("3.3", "전기·통신", "3"), ("3.3.1", "전기 배관·배선", "3.3"), ("3.3.2", "수변전·통신 설비", "3.3"),
    ("4", "마감", None), ("4.1", "내부 마감", "4"), ("4.1.1", "경량 벽체·천장", "4.1"),
    ("4.1.2", "바닥·도장", "4.1"), ("4.2", "부대 토목·조경", "4"), ("4.2.1", "부대 토목", "4.2"),
    ("4.2.2", "조경", "4.2"), ("4.3", "준공 준비", "4"), ("4.3.1", "시운전·종합 점검", "4.3"),
    ("4.3.2", "사용승인·준공 검사", "4.3"),
)

# 쓰는 자원(이름의 작업 유형 낱말로 분야 묶음이 붙이는 것과 같다. 타설반은 이 일정의 주요 자원이 아니다)
_CRANE, _REBAR, _FORM = "tower_crane", "rebar_crew", "form_crew"
_USES = {"철근": (_REBAR, _CRANE), "거푸집": (_FORM, _CRANE), "골조": (_CRANE,), "외장": (_CRANE,)}

# (id, 이름, WBS, 기간(근무일), 선행 [(id, 관계, lag)], 꼬리표). 선행 글 "A1010" 은 FS lag 0.
_Row = tuple[str, str, str, int, tuple, tuple[str, ...]]
_FOUNDATION: tuple[_Row, ...] = (
    ("A1000", "착공", "1.1.1", 0, (), ()),
    ("A1010", "가설 울타리 설치", "1.1.1", 5, ("A1000",), ()),
    ("A1020", "현장 사무실 설치", "1.1.1", 4, ("A1010",), ()),
    ("A1025", "가설 전기·용수 인입", "1.1.1", 3, ("A1020",), ()),
    ("A1030", "타워크레인 기초", "1.1.2", 5, ("A1010",), ()),
    ("A1040", "타워크레인 설치·검사", "1.1.2", 4, ("A1030",), ()),
    ("A1050", "흙막이 설치", "1.2.1", 12, ("A1010",), ("터파기",)),
    ("A1060", "터파기", "1.2.2", 10, ("A1050",), ("터파기",)),
    ("A1070", "잔토 처리", "1.2.2", 6, (("A1060", "SS", 3),), ()),
    ("A1080", "버림 콘크리트", "1.3.1", 2, ("A1060",), ()),
    ("A1090", "기초 철근 배근", "1.3.2", 6, ("A1080", "A1040"), ("철근",)),
    ("A1100", "기초 거푸집", "1.3.2", 5, (("A1090", "SS", 2),), ("거푸집",)),
    ("A1110", "기초 콘크리트 타설", "1.3.3", 2, ("A1090", "A1100"), ("타설",)),
)
_FINISHING: tuple[_Row, ...] = (
    ("A1300", "옥탑 골조", "2.3.1", 6, ("A1254",), ("골조",)),
    ("A1310", "골조 완료", "2.3.1", 0, ("A1300",), ()),
    ("A1320", "지붕 방수", "2.3.2", 6, ("A1300",), ()),
    ("A1400", "외벽 단열·방수 1~3층", "3.1.1", 8, ("A1234",), ()),
    ("A1410", "외장 패널 1~3층", "3.1.2", 10, ("A1400",), ("외장",)),
    ("A1420", "외벽 단열·방수 4~5층·옥탑", "3.1.1", 8, ("A1300",), ()),
    ("A1430", "외장 패널 4~5층", "3.1.2", 8, ("A1420", "A1410"), ("외장",)),
    ("A1440", "창호 설치 1~3층", "3.1.3", 10, ("A1410",), ()),
    ("A1445", "창호 설치 4~5층", "3.1.3", 8, ("A1430", "A1440"), ()),
    ("A1500", "설비 배관 1~3층", "3.2.1", 12, ("A1234",), ()),
    ("A1510", "설비 배관 4~5층", "3.2.1", 10, ("A1300", "A1500"), ()),
    ("A1520", "공조·덕트", "3.2.2", 15, ("A1510",), ()),
    ("A1540", "소방 설비", "3.2.2", 12, ("A1510",), ()),
    ("A1530", "승강기 설치", "3.2.3", 20, ("A1300",), ()),
    ("A1600", "전기 배관·배선 1~3층", "3.3.1", 12, ("A1234",), ()),
    ("A1610", "전기 배관·배선 4~5층", "3.3.1", 10, ("A1300", "A1600"), ()),
    ("A1620", "수변전 설비", "3.3.2", 10, ("A1610",), ()),
    ("A1630", "통신 설비", "3.3.2", 8, ("A1610",), ()),
    ("A1700", "경량 벽체 1~3층", "4.1.1", 10, ("A1500", "A1600", "A1440"), ()),
    ("A1710", "경량 벽체 4~5층", "4.1.1", 10, ("A1700", "A1510", "A1610", "A1445"), ()),
    ("A1720", "천장 마감", "4.1.1", 15, ("A1710",), ()),
    ("A1730", "바닥 마감 1~3층", "4.1.2", 8, ("A1720",), ()),
    ("A1735", "바닥 마감 4~5층", "4.1.2", 8, ("A1730",), ()),
    ("A1740", "도장", "4.1.2", 12, (("A1730", "SS", 5),), ()),
    ("A1800", "부대 토목", "4.2.1", 10, ("A1430",), ()),
    ("A1810", "조경", "4.2.2", 8, ("A1800",), ()),
    ("A1900", "설비 시운전", "4.3.1", 6, ("A1520", "A1540", "A1620", "A1630"), ()),
    ("A1910", "종합 점검", "4.3.1", 4, ("A1900", "A1735", "A1740", "A1530"), ()),
    ("A1915", "준공 청소", "4.3.1", 5, ("A1910",), ()),
    ("A1920", "사용승인 신청·검사", "4.3.2", 10, ("A1915", "A1810", "A1320"), ()),
    ("A1930", "준공", "4.3.2", 0, ("A1920",), ()),
)


def _frame_rows() -> tuple[_Row, ...]:
    """지상 1~5층 골조: 층마다 철근 배근(4) → 거푸집(SS+1, 4) → 타설(1). 다음 층은 아래층 타설 뒤.

    id: A12{층}0 철근 · A12{층}2 거푸집 · A12{층}4 타설.
    """
    rows: list[_Row] = []
    below = "A1110"
    for floor in range(1, 6):
        rebar, form, pour = (f"A12{floor}{k}" for k in (0, 2, 4))
        rows += [
            (rebar, f"{floor}층 철근 배근", "2.2.1", 4, (below,), ("철근",)),
            (form, f"{floor}층 거푸집", "2.2.2", 4, ((rebar, "SS", 1),), ("거푸집",)),
            (pour, f"{floor}층 콘크리트 타설", "2.2.3", 1, (rebar, form), ("타설",)),
        ]
        below = pour
    return tuple(rows)


def _activity(row: _Row) -> tuple[Activity, list[Relation]]:
    aid, name, wbs, od, preds, tags = row
    kind = "task" if od else ("start_ms" if not preds else "finish_ms")
    uses = dict.fromkeys(r for t in tags for r in _USES.get(t, ()))
    rels = [Relation(p, aid) if isinstance(p, str) else Relation(p[0], aid, p[1], p[2]) for p in preds]
    return Activity(aid, name, kind, wbs, od, resources=tuple(uses), tags=tags), rels


def _office_plan() -> Schedule:
    activities, relations = [], []
    for row in (*_FOUNDATION, *_frame_rows(), *_FINISHING):
        activity, rels = _activity(row)
        activities.append(activity)
        relations += rels
    cal = load_pack("construction").default_calendar
    return Schedule(
        start=START,
        calendar=CalendarSpec(cal.days_per_week, holidays_of(cal.holidays)),
        wbs=tuple(WbsNode(*node) for node in _WBS),
        activities=tuple(activities),
        relations=tuple(relations),
        resources=(Resource(_CRANE, "타워크레인", "대", 1), Resource(_REBAR, "철근공", "명", 1),
                   Resource(_FORM, "형틀목공", "명", 1)),
    )


def _office_inputs() -> list[Condition]:
    def cond(cid: str, kind: str, params: dict, text: str, source: str = "질문지") -> Condition:
        return Condition(cid, "input", kind, params, text, source)

    return [
        cond("in.finish_by", "finish_by", {"date": "2027-12-24"}, "준공 2027-12-24까지", "프롬프트"),
        cond(CRANE_CONDITION, "resource_cap", {"resource_id": _CRANE, "capacity": 1}, "타워크레인 1대"),
        cond("in.resource_cap.rebar_crew", "resource_cap", {"resource_id": _REBAR, "capacity": 1}, "철근공 1개 조"),
        cond("in.milestone_by.A1310", "milestone_by", {"activity_id": "A1310", "date": "2027-07-31"},
             "골조 완료 2027-07-31까지"),
        cond("in.blocked_period.pour", "blocked_period", {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"},
             "동절기(12월 1일~2월 말) 콘크리트 타설 금지", "분야 지식"),
        cond("in.text_only.site", "text_only", {}, "현장 사무실은 남측 진입로 옆에 둔다", "프롬프트"),
    ]


# (id, 실제 시작, 실제 종료 또는 None, 진도). 진행 중이면 남은 기간 rd 를 넣는다.
_ACTUALS = (
    ("A1000", date(2027, 3, 2), date(2027, 3, 2), 1.0, None),
    ("A1010", date(2027, 3, 2), date(2027, 3, 8), 1.0, None),
    ("A1020", date(2027, 3, 9), date(2027, 3, 12), 1.0, None),
    ("A1025", date(2027, 3, 13), date(2027, 3, 16), 1.0, None),
    ("A1030", date(2027, 3, 9), date(2027, 3, 15), 1.0, None),
    ("A1040", date(2027, 3, 16), date(2027, 3, 19), 1.0, None),
    ("A1050", date(2027, 3, 10), date(2027, 3, 25), 1.0, None),
    ("A1060", date(2027, 3, 26), date(2027, 4, 9), 1.0, None),
    ("A1070", date(2027, 3, 30), date(2027, 4, 6), 1.0, None),
    ("A1080", date(2027, 4, 10), date(2027, 4, 12), 1.0, None),
    ("A1090", date(2027, 4, 13), None, 0.5, 3),
)


def _with_actuals(plan: Schedule) -> Schedule:
    actual = {aid: (s, f, p, rd) for aid, s, f, p, rd in _ACTUALS}

    def one(a: Activity) -> Activity:
        if a.id not in actual:
            return a
        s, f, p, rd = actual[a.id]
        return replace(a, actual_start=s, actual_finish=f, progress=p, rd=rd)

    return replace(plan, activities=tuple(one(a) for a in plan.activities), data_date=DATA_DATE)


def office_building(session: Session) -> int:
    """「5층 사무동 신축」: 버전 1 처음 계획 → 버전 2 실적 입력. 일정 id 를 준다."""
    pack = load_pack("construction")
    domain_rules = [Condition.from_dict(r) for r in pack.rules_raw]
    conditions = [c.to_dict() for c in assemble(domain_rules, [], _office_inputs())]
    plan = _office_plan()
    sid = create_schedule(session, name=OFFICE, domain="construction", level="L3", schedule=plan,
                          conditions=conditions, by_kind="user", by_name=BY, note="처음 계획", commit=False)
    mark_plan(session, sid, 1, commit=False)
    actual = _with_actuals(plan)
    run(actual, conditions)
    save_new_version(session, sid, actual, conditions, by_kind="user", by_name=BY,
                     note=f"실적 입력(Data Date {DATA_DATE.isoformat()})",
                     changes=schedule_changes(plan, actual), base_version=1, commit=False)
    return sid


# ── 지우고 만들기 ────────────────────────────────────────────────────────

DEMO: tuple[tuple[str, Callable[[Session], int]], ...] = ((OFFICE, office_building),)


def _clear(session: Session, name: str) -> None:
    """그 이름의 일정과 일정에 딸린 줄(schedule_id 칸이 있는 모든 표)을 지운다. 대화는 남기고 일정 연결만 끊는다."""
    ids = list(session.scalars(select(ScheduleRecord.id).where(ScheduleRecord.name == name)))
    if not ids:
        return
    session.execute(update(ChatSession).where(ChatSession.schedule_id.in_(ids)).values(schedule_id=None))
    for table in reversed(Base.metadata.sorted_tables):
        column = table.columns.get("schedule_id")
        if column is not None and table.name != ChatSession.__tablename__:
            session.execute(delete(table).where(column.in_(ids)))
    session.execute(delete(ScheduleRecord).where(ScheduleRecord.id.in_(ids)))


def seed_demo(session: Session) -> list[int]:
    """시연 일정을 모두 지우고 다시 만든다(한 트랜잭션). 만든 일정 id 를 차례로 준다."""
    try:
        for name, _ in DEMO:
            _clear(session, name)
        ids = [make(session) for _, make in DEMO]
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return ids


def _engine() -> Engine:
    """앱과 같은 DB 파일. 표가 없으면 만든다(첫 관리자는 앱이 뜰 때 만든다)."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.data_dir / 'chronos.db'}")
    Base.metadata.create_all(engine)
    add_missing_columns(engine, Base.metadata)
    return engine


def main(argv: Sequence[str]) -> int:
    if list(argv) != ["demo"]:
        print("사용법: python -m app.seed demo", file=sys.stderr)
        return 2
    engine = _engine()
    try:
        with Session(engine) as session:
            ids = seed_demo(session)
    finally:
        engine.dispose()
    print(f"시연 일정 {len(ids)}개를 만들었습니다: {', '.join(name for name, _ in DEMO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
