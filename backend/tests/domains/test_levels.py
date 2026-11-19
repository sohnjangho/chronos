"""정밀도 5단계 정의(levels.yaml)와 에이전트 지시문에 넣을 글."""

from app.domains.loader import levels, levels_prompt

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_levels_match_design():
    lv = levels()
    assert [x.id for x in lv.values()] == ["L1", "L2", "L3", "L4", "L5"]
    assert lv["L3"].activity_count == [50, 100] and lv["L5"].activity_count is None and lv["L1"].time_unit == "월"


def test_levels_prompt_mentions_every_level():
    t = levels_prompt()
    assert all(x in t for x in ["L1", "L5", "50~100"])


# ── 덧붙인 시험 ─────────────────────────────────────────────────────

# 설계 11-2 표 그대로: (id, 이름, 쓰는 곳, WBS 깊이, 액티비티 수, 단위, 자원, 꼭 있어야 하는 것)
DESIGN_TABLE = [
    ("L1", "마스터", "경영 보고·제안", [1, 2], [10, 20], "월", "없음", "주요 단계와 착공·준공"),
    ("L2", "요약", "타당성·계약", [2, 3], [20, 40], "주", "없음", "단계별 기간, 중간 마일스톤, 인허가 대기"),
    ("L3", "관리", "계획 수립·월간 보고", [3, 3], [50, 100], "일", "주요 자원", "공종별 액티비티, 선후 관계, 달력, 주요 자원"),
    ("L4", "실행", "주간 관리", [4, 4], [100, 200], "일", "주요 자원", "작업 단위 액티비티, 기준 기간, 예비 기간, 실적"),
    ("L5", "상세", "3주 앞 작업 계획·작업 지시", [5, 5], None, "일·교대", "주요 자원", "고른 구간의 작업 지시 수준"),
]


def test_every_level_matches_the_design_table():
    got = [
        (x.id, x.name, x.use, x.wbs_depth, x.activity_count, x.time_unit, x.resources, x.must_contain)
        for x in levels().values()
    ]
    assert got == DESIGN_TABLE


def test_levels_prompt_has_one_line_per_level_with_its_definition():
    lines = levels_prompt().splitlines()
    for level_id, name, use, _, _, unit, resources, must in DESIGN_TABLE:
        line = next(x for x in lines if f"{level_id} {name}" in x)
        assert use in line and unit in line and resources in line and must in line
    l3 = next(x for x in lines if "L3 관리" in x)
    assert "WBS 깊이: 3 " in l3 and "3~3" not in l3  # 같은 두 값은 하나로
    assert "액티비티 수: 50~100개" in l3 and "기간 단위: 일" in l3 and "자원: 주요 자원" in l3
    assert "쓰는 곳: 계획 수립·월간 보고" in l3 and "꼭 있어야 하는 것: 공종별 액티비티" in l3
    l1 = next(x for x in lines if "L1 마스터" in x)
    assert "자원: 없음" in l1
    l5 = next(x for x in lines if "L5 상세" in x)
    assert "액티비티 수: 고른 구간만" in l5


def test_levels_hands_out_a_copy():
    levels().pop("L1")
    assert "L1" in levels()


def test_levels_cache_cannot_be_corrupted():
    lv = levels()
    lv["L3"].wbs_depth.append(9)
    lv["L3"].activity_count[0] = 1
    assert levels()["L3"].wbs_depth == [3, 3] and levels()["L3"].activity_count == [50, 100]
