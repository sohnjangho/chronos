"""씨앗 일정 「가상 부품 공장 — 브래킷 BR-200 2만 개」(생산·L3): 액티비티 30개(생산 WBS 틀), 주요 자원 6개,
조건 = 분야 규칙 + 입력 둘(납기 9월 10일·프레스 라인 1개). 버전 1 = 처음 계획 하나뿐(실적·Data Date 없음).
"""

from datetime import date

from sqlalchemy.orm import Session

from app.core.model import CalendarSpec, Resource, Schedule, WbsNode
from app.domains.loader import load as load_pack
from app.harness.assemble import assemble, holidays_of
from app.harness.conditions import Condition
from app.seed.rows import BY, Row, activity
from app.store.schedules import create_schedule
from app.store.versions import mark_plan

# ── 「가상 부품 공장 — 브래킷 BR-200 2만 개」 자료 ──────────────────────────
# 프레스 한 장짜리 브래킷이라 용접이 없고, 열처리·CNC 가공이 드는 제품이다(분야 묶음의 「제품에 따라」 공정).
# 금형은 기존 BR-100 금형을 고쳐 쓴다(새로 만들면 40근무일이라 납기 안에 들지 않는다). 2만 개를 1만 개씩 두 번에 나눈다.
# 1차분 블랭킹이 프레스 하계 정기 보수(7/29~8/4) 앞에서 시작해 보수 뒤에 이어진다(달력이 그 사이 날을 쉰다).

FACTORY = "가상 부품 공장 — 브래킷 BR-200 2만 개"
FACTORY_START = date(2027, 7, 5)
_FACTORY_WBS = ("1", "1.1", "1.1.1", "1.1.2", "1.2", "1.2.1", "1.2.2", "1.2.3", "2", "2.1", "2.2", "3", "3.1", "3.1.1",
                "3.1.2", "3.3", "3.3.1", "3.4", "3.4.1", "3.4.2", "3.5", "3.5.1", "3.6", "3.6.1", "3.6.2", "4", "4.1",
                "4.2", "4.3")
# 열처리 뒤 관계는 하루 띄운다(분야 규칙 「열처리 뒤 하루 식힘」). 꼬리표는 분야 묶음의 작업 유형 이름 낱말과 같다.
_FACTORY_ROWS: tuple[Row, ...] = (
    ("M1000", "착수", "1.1.1", 0, (), ()),
    ("M1010", "도면 검토·공정 설계", "1.1.1", 3, ("M1000",), ()),
    ("M1020", "지그·검사구 설계", "1.1.2", 4, ("M1010",), ()),
    ("M1030", "금형 설계(BR-100 금형 고침)", "1.2.1", 3, ("M1010",), ()),
    ("M1040", "금형 제작(기존 금형 개조)", "1.2.2", 7, ("M1030",), ("금형",)),
    ("M1050", "트라이아웃(시타)·수정", "1.2.3", 2, ("M1040",), ("금형",)),
    ("M1100", "원자재 발주·입고(강판 코일)", "2.1", 10, ("M1000",), ("자재",)),
    ("M1110", "수입 검사(성적서·경도 확인)", "2.2", 1, ("M1100",), ()),
    ("M1200", "양산 전 초도품 치수검사(FAI)", "4.1", 1, ("M1050", "M1020", "M1110"), ("검사",)),
    ("M1300", "블랭킹 1차분(1만 개)", "3.1.1", 2, ("M1200",), ("프레스",)),
    ("M1310", "성형·피어싱 1차분", "3.1.2", 2, ("M1300",), ("프레스",)),
    ("M1320", "블랭킹 2차분(1만 개)", "3.1.1", 2, ("M1300",), ("프레스",)),
    ("M1330", "성형·피어싱 2차분", "3.1.2", 2, ("M1320", "M1310"), ("프레스",)),
    ("M1500", "담금질·뜨임 1차분", "3.5.1", 2, ("M1310",), ("열처리",)),
    ("M1510", "담금질·뜨임 2차분", "3.5.1", 2, ("M1330",), ("열처리",)),
    ("M1600", "CNC 가공 1차분", "3.6.1", 2, (("M1500", "FS", 1),), ("가공",)),
    ("M1610", "탭핑 1차분", "3.6.2", 1, ("M1600",), ("가공",)),
    ("M1620", "CNC 가공 2차분", "3.6.1", 2, (("M1510", "FS", 1),), ("가공",)),
    ("M1630", "탭핑 2차분", "3.6.2", 1, ("M1620",), ("가공",)),
    ("M1700", "전착도장 외주 왕복 1차분", "3.3.1", 5, ("M1610",), ("표면처리",)),
    ("M1710", "전착도장 외주 왕복 2차분", "3.3.1", 5, ("M1630",), ("표면처리",)),
    ("M1800", "서브 조립 1차분(부싱 압입)", "3.4.1", 1, ("M1700",), ("조립",)),
    ("M1810", "최종 조립 1차분", "3.4.2", 1, ("M1800",), ("조립",)),
    ("M1820", "서브 조립 2차분(부싱 압입)", "3.4.1", 1, ("M1710",), ("조립",)),
    ("M1830", "최종 조립 2차분", "3.4.2", 1, ("M1820",), ("조립",)),
    ("M1900", "로트 치수검사 1차분", "4.2", 1, ("M1810",), ("검사",)),
    ("M1910", "로트 치수검사 2차분", "4.2", 1, ("M1830",), ("검사",)),
    ("M1920", "양산 검사(최종)", "4.2", 1, ("M1900", "M1910"), ()),
    ("M1950", "포장·출하", "4.3", 2, ("M1920",), ("출하",)),
    ("M1960", "납품 완료", "4.3", 0, ("M1950",), ()),
)
_FACTORY_CAPACITY = {"press_line": 1, "heat_furnace": 1, "cnc": 2, "assembly_line": 1, "cmm": 1, "mold_shop": 1}


def _factory_plan() -> Schedule:
    pack = load_pack("manufacturing")
    uses_of = {t.tag: tuple(t.resources) for t in pack.activity_types}
    activities, relations = [], []
    for row in _FACTORY_ROWS:
        act, rels = activity(row, uses_of)
        activities.append(act)
        relations += rels
    names = {n.code: n for n in pack.wbs_template}
    cal = pack.default_calendar
    return Schedule(
        start=FACTORY_START,
        calendar=CalendarSpec(cal.days_per_week, holidays_of(cal.holidays)),
        wbs=tuple(WbsNode(names[c].code, names[c].name, names[c].parent) for c in _FACTORY_WBS),
        activities=tuple(activities),
        relations=tuple(relations),
        resources=tuple(Resource(r.id, r.name, r.unit, _FACTORY_CAPACITY[r.id])
                        for r in pack.key_resources if r.id in _FACTORY_CAPACITY),
    )


def parts_factory(session: Session) -> int:
    """「가상 부품 공장 — 브래킷 BR-200 2만 개」: 버전 1 처음 계획만(실적·Data Date 없음). 일정 id 를 준다."""
    pack = load_pack("manufacturing")
    domain_rules = [Condition.from_dict(r) for r in pack.rules_raw]
    inputs = [
        Condition("in.finish_by", "input", "finish_by", {"date": "2027-09-10"}, "납기 9월 10일", "질문지"),
        Condition("in.resource_cap.press_line", "input", "resource_cap", {"resource_id": "press_line", "capacity": 1},
                  "프레스 라인 1개", "질문지"),
    ]
    conditions = [c.to_dict() for c in assemble(domain_rules, [], inputs)]
    sid = create_schedule(session, name=FACTORY, domain="manufacturing", level="L3", schedule=_factory_plan(),
                          conditions=conditions, by_kind="user", by_name=BY, note="처음 계획", commit=False)
    mark_plan(session, sid, 1, commit=False)
    return sid
