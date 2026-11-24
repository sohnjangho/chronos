"""씨앗 일정 「5층 사무동 신축」(건설·L3): 액티비티 59개, 조건 14개(기본 4·분야 4·입력 6), 주요 자원 3개.

버전 1 = 처음 계획(실적 없음, 「처음 계획」 표시), 버전 2 = 실적 일부와 Data Date 를 넣은 것.
버전 3(`office_building(..., v3=True)` — 계획 5 관리 포인트·당김 효과 시연) = 6월 말 실적 + 커튼월·창호 조달 줄(액티비티 65개).
"""

from dataclasses import replace
from datetime import date

from sqlalchemy.orm import Session

from app.core.model import Activity, CalendarSpec, Relation, Resource, Schedule, WbsNode
from app.domains.loader import load as load_pack
from app.harness.assemble import assemble, holidays_of
from app.harness.conditions import Condition
from app.seed.rows import BY, Row, activity
from app.store.diff import schedule_changes
from app.store.schedules import create_schedule, run
from app.store.versions import mark_plan, save_new_version

OFFICE = "5층 사무동 신축"
START = date(2027, 3, 2)  # 3월 1일(삼일절) 다음 날 착공
DATA_DATE = date(2027, 4, 17)  # 실적 기준일(토요일, 주 6일 달력의 근무일)
DATA_DATE_V3 = date(2027, 6, 30)  # 버전 3 실적 기준일(수요일)
V3_NOTE = "6월 말 실적 + 커튼월·창호 조달 일정 반영"
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

_FOUNDATION: tuple[Row, ...] = (
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
_FINISHING: tuple[Row, ...] = (
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


def _frame_rows() -> tuple[Row, ...]:
    """지상 1~5층 골조: 층마다 철근 배근(4) → 거푸집(SS+1, 4) → 타설(1). 다음 층은 아래층 타설 뒤.

    id: A12{층}0 철근 · A12{층}2 거푸집 · A12{층}4 타설.
    """
    rows: list[Row] = []
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


def _office_plan() -> Schedule:
    activities, relations = [], []
    for row in (*_FOUNDATION, *_frame_rows(), *_FINISHING):
        act, rels = activity(row, _USES)
        activities.append(act)
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


# ── 버전 3: 6월 말 실적 + 커튼월·창호 조달 ────────────────────────────────
# 골조는 장마로 늦어져 4층 거푸집이 진행 중이다. 조달 줄은 Data Date 에 시작한다(선행 = 착공).
# 기본 설정(k=3, w=3)에서: 5층 거푸집·타설·옥탑 골조가 크리티컬, 커튼월 줄 여유 4, 창호 줄 여유 13
# (숫자는 scripts/find_demo_pair.py · find_accel_case.py --version 3, docs/demo/시나리오.md 「관리 포인트 장면」).

_ACTUALS_JUNE = (
    ("A1090", date(2027, 4, 13), date(2027, 4, 21), 1.0, None),
    ("A1100", date(2027, 4, 22), date(2027, 4, 28), 1.0, None),
    ("A1110", date(2027, 4, 29), date(2027, 4, 30), 1.0, None),
    ("A1210", date(2027, 5, 4), date(2027, 5, 10), 1.0, None),
    ("A1212", date(2027, 5, 11), date(2027, 5, 15), 1.0, None),
    ("A1214", date(2027, 5, 17), date(2027, 5, 17), 1.0, None),
    ("A1220", date(2027, 5, 18), date(2027, 5, 22), 1.0, None),
    ("A1222", date(2027, 5, 24), date(2027, 5, 28), 1.0, None),
    ("A1224", date(2027, 5, 29), date(2027, 5, 29), 1.0, None),
    ("A1230", date(2027, 5, 31), date(2027, 6, 5), 1.0, None),
    ("A1232", date(2027, 6, 7), date(2027, 6, 12), 1.0, None),
    ("A1234", date(2027, 6, 14), date(2027, 6, 14), 1.0, None),
    ("A1240", date(2027, 6, 15), date(2027, 6, 25), 1.0, None),  # 장마
    ("A1242", date(2027, 6, 26), None, 0.4, 3),
    ("A1400", date(2027, 6, 15), date(2027, 6, 25), 1.0, None),
    ("A1500", date(2027, 6, 15), None, 0.6, 5),
    ("A1600", date(2027, 6, 17), None, 0.5, 6),
)
# (줄, 붙일 자리 = 이 액티비티 앞, 이어지는 설치 작업)
_PROCUREMENT: tuple[tuple[tuple[Row, ...], str], ...] = (
    ((("A1402", "커튼월 제작 도면 승인", "3.1.2", 2, ("A1000",), ()),
      ("A1404", "커튼월 공장 제작", "3.1.2", 6, ("A1402",), ()),
      ("A1406", "커튼월 자재 반입", "3.1.2", 1, ("A1404",), ())), "A1410"),
    ((("A1434", "창호 제작 도면 승인", "3.1.3", 3, ("A1000",), ()),
      ("A1436", "창호 제작", "3.1.3", 6, ("A1434",), ()),
      ("A1438", "창호 반입", "3.1.3", 1, ("A1436",), ())), "A1440"),
)
# 커튼월·외장 패널은 커튼월 업체 장비(윈치·곤돌라)로 단다 — 버전 3 에서는 타워크레인을 쓰지 않는다
# (크레인을 쓰면 골조와 맞춤 순서가 얽혀 골조가 크리티컬에서 빠진다).
_RENAMED_V3 = {"A1410": "커튼월·외장 패널 1~3층", "A1430": "커튼월·외장 패널 4~5층"}


def _june(v2: Schedule) -> Schedule:
    """버전 2 에 6월 말 실적·조달 줄(설치 작업 앞에 FS)을 넣고 외장 패널 이름을 바꾼 버전 3."""
    actual = {aid: (s, f, p, rd) for aid, s, f, p, rd in _ACTUALS_JUNE}
    before = {at: rows for rows, at in _PROCUREMENT}
    activities, relations = [], list(v2.relations)
    for a in v2.activities:
        for row in before.get(a.id, ()):
            act, rels = activity(row, _USES)
            activities.append(act)
            relations += rels
        if a.id in before:
            relations.append(Relation(before[a.id][-1][0], a.id))
        if a.id in _RENAMED_V3:
            a = replace(a, name=_RENAMED_V3[a.id], resources=())
        if a.id in actual:
            s, f, p, rd = actual[a.id]
            a = replace(a, actual_start=s, actual_finish=f, progress=p, rd=rd)
        activities.append(a)
    return replace(v2, activities=tuple(activities), relations=tuple(relations), data_date=DATA_DATE_V3)


def office_building(session: Session, *, v3: bool = False) -> int:
    """「5층 사무동 신축」: 버전 1 처음 계획 → 버전 2 실적 입력(→ v3 면 버전 3 6월 말 실적·조달 줄). 일정 id 를 준다."""
    pack = load_pack("construction")
    domain_rules = [Condition.from_dict(r) for r in pack.rules_raw]
    conditions = [c.to_dict() for c in assemble(domain_rules, [], _office_inputs())]
    plan = _office_plan()
    sid = create_schedule(session, name=OFFICE, domain="construction", level="L3", schedule=plan,
                          conditions=conditions, by_kind="user", by_name=BY, note="처음 계획", commit=False)
    mark_plan(session, sid, 1, commit=False)
    actual = _with_actuals(plan)
    run(actual, conditions)  # 실적을 넣은 일정이 계산되는지 확인(깨지면 ScheduleError, 저장하지 않음 — save_new_version 은 확인하지 않는다)
    save_new_version(session, sid, actual, conditions, by_kind="user", by_name=BY,
                     note=f"실적 입력(Data Date {DATA_DATE.isoformat()})",
                     changes=schedule_changes(plan, actual), base_version=1, plan_change=False, commit=False)
    if v3:
        june = _june(actual)
        run(june, conditions)
        save_new_version(session, sid, june, conditions, by_kind="user", by_name=BY, note=V3_NOTE,
                         changes=schedule_changes(actual, june), base_version=2, plan_change=False, commit=False)
    return sid
