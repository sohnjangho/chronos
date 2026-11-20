"""보고서용 그림 숫자 대조(app.llm.visual_check): 실측 모양 HTML·리뷰어 probe 를 시험으로. Liner 는 부르지 않는다."""

from datetime import date

import pytest

from app.llm.visual_check import verify
from app.store.visuals import VisualTable
from tests.visual_doubles import CDN, chart_html

ROWS = [
    ["터파기", "2027-03-12", "2027-03-15"],
    ["기초 타설", "2027-04-02", "2027-04-09"],
    ["골조 1층", "2027-05-07", "2027-05-14"],
    ["골조 2층", "2027-06-04", "2027-06-18"],
    ["지붕 방수", "2027-06-25", "2027-07-06"],
]
TABLE = VisualTable(kind="summary", title="계획과 전망 끝", columns=["작업", "계획 끝", "전망 끝"], rows=ROWS,
                    chart="timeline", version=3, data_date=date(2027, 3, 1))


# ── 대조 ─────────────────────────────────────────────────────────────


def test_probe_shaped_html_passes_with_axis_bounds():
    v = verify(chart_html(ROWS), TABLE)
    assert v.ok, v.problems
    assert (v.passed, v.total) == (15, 15)
    assert v.external == list(CDN)


def test_value_missing_from_html_fails():
    changed = [r[:] for r in ROWS]
    changed[1][2] = "2027-04-10"  # 우리 표는 04-09
    v = verify(chart_html(changed), TABLE)
    assert not v.ok and (v.passed, v.total) == (14, 15)
    assert "차트 자료에 없는 표 값: 2027-04-09" in v.problems


def test_extra_date_in_data_array_fails():
    v = verify(chart_html(ROWS, extra_data='{ c0: "터파기", c1: "2027-03-20" }'), TABLE)
    assert not v.ok
    assert "데이터에 표에 없는 날짜: 2027-03-20" in v.problems


def test_extra_label_in_data_array_fails():
    v = verify(chart_html(ROWS, extra_data='{ c0: "가설 공사", c1: "2027-03-12" }'), TABLE)
    assert not v.ok
    assert "데이터에 표에 없는 값: 가설 공사" in v.problems


def test_labels_literal_array_is_checked():
    script = "\n  const more = { labels: ['터파기', '준공 검사'] };"
    v = verify(chart_html(ROWS, extra_script=script), TABLE)
    assert "데이터에 표에 없는 값: 준공 검사" in v.problems


def test_axis_bound_more_than_a_month_outside_fails():
    v = verify(chart_html(ROWS, bounds=("2027-01-15", "2027-07-15")), TABLE)
    assert not v.ok
    assert "축 범위가 표 날짜에서 한 달 넘게 벗어남: 2027-01-15" in v.problems


def test_axis_bound_within_a_month_passes():
    assert verify(chart_html(ROWS, bounds=("2027-02-10", "2027-08-06")), TABLE).ok


def test_numeric_axis_bounds_are_layout_not_data():
    table = VisualTable(kind="delay_impact", title="지연", columns=["작업", "지연(근무일)"], rows=[["터파기", 3], ["기초 타설", 7]],
                        chart="bars", version=1, data_date=None)
    html = chart_html([["터파기", 3], ["기초 타설", 7]], bounds=None, extra_script="\n  const y = { min: 0, max: 10 };")
    assert verify(html, table).ok


def test_numbers_in_data_arrays_must_be_table_numbers():
    table = VisualTable(kind="delay_impact", title="지연", columns=["작업", "지연(근무일)"], rows=[["터파기", 3], ["기초 타설", 7]],
                        chart="bars", version=1, data_date=None)
    ok = chart_html([["터파기", 3], ["기초 타설", 7]], bounds=None, extra_script="\n  const d2 = { data: [3, 7] };")
    bad = chart_html([["터파기", 3], ["기초 타설", 7]], bounds=None, extra_script="\n  const d2 = { data: [3, 8] };")
    assert verify(ok, table).ok
    assert "데이터에 표에 없는 값: 8" in verify(bad, table).problems


def test_date_outside_table_anywhere_in_html_fails():
    v = verify(chart_html(ROWS).replace("</body>", "<p>준공 2027-09-30 예상</p></body>"), TABLE)
    assert "표에 없는 날짜: 2027-09-30" in v.problems


def test_unparseable_chart_is_a_failure():
    v = verify(chart_html(ROWS, chart=False), TABLE)
    assert not v.ok
    assert "차트 설정을 읽지 못함" in v.problems


def test_empty_cells_are_not_counted():
    table = VisualTable(kind="s_curve", title="S", columns=["날짜", "계획", "실적"],
                        rows=[["2027-03-01", 10, 5], ["2027-03-08", 20, None]], chart="line", version=1, data_date=None)
    v = verify(chart_html([["2027-03-01", 10, 5], ["2027-03-08", 20, None]], bounds=None), table)
    assert v.ok, v.problems
    assert (v.passed, v.total) == (5, 5)


# ── 차트 자료로 세기(리뷰 I1) · 보이는 글의 숫자(I2) · 외부 주소 허용(CSP) ──

DELAY = VisualTable(kind="delay_impact", title="지연 영향", columns=["작업", "지연(근무일)", "흡수(근무일)", "준공 영향(근무일)"],
                    rows=[["골조 1층", 5, 2, 3], ["지붕 방수", 4, 4, 0]], chart="bars", version=3, data_date=date(2027, 3, 1))
HEAD = f'<html><head><script src="{CDN[2]}"></script></head><body>'
BAR = ("<script>\n(function(){ const ctx=1; new Chart(ctx,{type:'bar',data:{labels:['골조 1층','지붕 방수'],datasets:["
       "{label:'지연(근무일)',data:[5,4]},{label:'흡수(근무일)',data:[2,4]},{label:'준공 영향(근무일)',data:[3,0]}]},"
       "options:{scales:{x:{max:10}}}});})();\n</script><table><tr><td>골조 1층</td><td>5</td><td>2</td><td>3</td></tr>"
       "<tr><td>지붕 방수</td><td>4</td><td>4</td><td>0</td></tr></table></body></html>")


def test_reviewer_bar_chart_passes():
    v = verify(HEAD + BAR, DELAY)
    assert v.ok, v.problems
    assert (v.passed, v.total) == (8, 8)


def test_a_row_missing_from_the_chart_is_not_counted():
    html = HEAD + BAR.replace("labels:['골조 1층','지붕 방수']", "labels:['골조 1층']").replace("data:[5,4]", "data:[5]")
    v = verify(html, DELAY)  # 보이는 표는 다 있어도 차트 자료에 없으면 세지 않는다(4 는 표에 두 번, 차트에 한 번)
    assert not v.ok and (v.passed, v.total) == (6, 8)
    assert "차트 자료에 없는 표 값: 지붕 방수" in v.problems


def test_empty_series_are_not_counted():
    v = verify(HEAD + BAR.replace("data:[2,4]", "data:[]").replace("data:[3,0]", "data:[]"), DELAY)
    assert not v.ok and (v.passed, v.total) == (4, 8)  # 개수까지 센다: 두 번째 4 도 없다
    assert {"차트 자료에 없는 표 값: 2", "차트 자료에 없는 표 값: 3", "차트 자료에 없는 표 값: 4",
            "차트 자료에 없는 표 값: 0"} <= set(v.problems)


def test_text_must_match_exactly_in_chart_data():
    v = verify(HEAD + BAR.replace("'골조 1층','지붕 방수'", "'골조 1층(지연)','지붕 방수'"), DELAY)
    assert "차트 자료에 없는 표 값: 골조 1층" in v.problems


def test_a_visible_total_row_fails():
    html = HEAD + BAR.replace("</table>", "<tr><td>합계</td><td>9</td><td>6</td><td>3</td></tr></table>")
    v = verify(html, DELAY)
    assert not v.ok
    assert {"보이는 글에 표에 없는 숫자: 9", "보이는 글에 표에 없는 숫자: 6"} <= set(v.problems)


def test_an_sr_only_count_fails():
    html = chart_html(ROWS).replace('<canvas id="c">', '<h2 class="sr-only">총 지연 31일, 작업별 계획과 전망</h2><canvas id="c">')
    v = verify(html, TABLE)
    assert "보이는 글에 표에 없는 숫자: 31" in v.problems


def test_aria_label_numbers_inside_table_text_are_fine():
    html = chart_html(ROWS).replace('<canvas id="c">', '<canvas id="c" role="img" aria-label="골조 1층, 골조 2층의 계획과 전망">')
    assert verify(html, TABLE).ok
    bad = chart_html(ROWS).replace('<canvas id="c">', '<canvas id="c" aria-label="5개 작업 중 3개 지연">')
    assert {"보이는 글에 표에 없는 숫자: 5", "보이는 글에 표에 없는 숫자: 3"} <= set(verify(bad, TABLE).problems)


def test_external_hosts_outside_the_allowlist_fail():
    html = chart_html(ROWS).replace("</head>", '<script src="https://cdn.example.com/x.js"></script></head>')
    v = verify(html, TABLE)
    assert "허용하지 않은 외부 주소: https://cdn.example.com/x.js" in v.problems
    assert "https://cdn.example.com/x.js" in v.external




# ── 리뷰 2: 개수까지 세기(I1) · 칸별 규칙 charted/shown(I2) · 보이는 글 전체(I4) · 숫자 꼴 · 주소 앞부분 ──


def test_a_value_repeated_in_the_table_must_be_repeated_in_the_chart():
    v = verify(HEAD + BAR.replace("data:[2,4]", "data:[2]"), DELAY)  # 4 는 다른 계열에 한 번 있다
    assert not v.ok and (v.passed, v.total) == (7, 8)
    assert "차트 자료에 없는 표 값: 4" in v.problems


SC = VisualTable(kind="s_curve", title="진행 S-커브", columns=["날짜", "계획 누적(%)", "실적 누적(%)"],
                 rows=[["2027-03-01", 0, 0], ["2027-03-08", 50, 40], ["2027-03-15", 100, None], ["2027-03-22", 100, None]],
                 chart="line", version=3, data_date=date(2027, 3, 10))
LINE = ("<script>(function(){ new Chart(c,{type:'line',data:{labels:['2027-03-01','2027-03-08','2027-03-15','2027-03-22'],"
        "datasets:[{label:'계획 누적(%)',data:[0,50,100,100]},{label:'실적 누적(%)',data:[0,40,null,null]}]},"
        "options:{scales:{y:{min:0,max:100}}}});})();</script></body></html>")


def test_a_truncated_last_point_fails():
    assert verify(HEAD + LINE, SC).ok
    v = verify(HEAD + LINE.replace("data:[0,50,100,100]", "data:[0,50,100]"), SC)
    assert not v.ok and "차트 자료에 없는 표 값: 100" in v.problems


def test_an_emptied_series_whose_values_repeat_elsewhere_fails():
    table = VisualTable(kind="s_curve", title="S", columns=SC.columns, chart="line", version=3, data_date=date(2027, 3, 15),
                        rows=[["2027-03-01", 0, 0], ["2027-03-08", 25, 25], ["2027-03-15", 50, 50], ["2027-03-22", 80, None]])
    html = HEAD + LINE.replace("data:[0,50,100,100]", "data:[0,25,50,80]").replace("data:[0,40,null,null]", "data:[]")
    v = verify(html, table)
    assert not v.ok and (v.passed, v.total) == (8, 11)


SCN = VisualTable(kind="scenario_compare", title="안 비교", columns=["안", "준공", "크리티컬(개)", "위반(개)"],
                  rows=[["지금 일정", "2027-07-06", 5, 0], ["안 A", "2027-06-30", 6, 1]], chart="bars", version=3,
                  data_date=date(2027, 3, 1), roles=("charted", "shown", "charted", "charted"))
SCN_BARS = ("<script>(function(){new Chart(c,{type:'bar',data:{labels:['지금 일정','안 A'],datasets:[{label:'크리티컬(개)',"
            "data:[5,6]},{label:'위반(개)',data:[0,1]}]}});})();</script><table><tr><th>안</th><th>준공</th>"
            "<th>크리티컬(개)</th><th>위반(개)</th></tr><tr><td>지금 일정</td><td>2027-07-06</td><td>5</td><td>0</td></tr>"
            "<tr><td>안 A</td><td>2027-06-30</td><td>6</td><td>1</td></tr></table></body></html>")


def test_shown_columns_may_live_only_in_the_visible_table():
    v = verify(HEAD + SCN_BARS, SCN)
    assert v.ok, v.problems
    assert (v.passed, v.total) == (8, 8)


def test_shown_columns_must_be_in_visible_cells():
    v = verify(HEAD + SCN_BARS.replace("<td>2027-06-30</td>", "<td>—</td>"), SCN)
    assert not v.ok and (v.passed, v.total) == (7, 8)
    assert "보이는 표에 없는 값: 2027-06-30" in v.problems


def test_a_shown_status_column_is_checked_in_the_table():
    table = VisualTable(kind="delay_impact", title="지연 영향", columns=[*DELAY.columns, "상태"], chart="bars", version=3,
                        data_date=date(2027, 3, 1), rows=[[*DELAY.rows[0], "열림"], [*DELAY.rows[1], "반영됨"]],
                        roles=("charted", "charted", "charted", "charted", "shown"))
    good = HEAD + BAR.replace("<td>3</td></tr>", "<td>3</td><td>열림</td></tr>").replace("<td>0</td></tr>", "<td>0</td><td>반영됨</td></tr>")
    assert verify(good, table).ok
    assert "보이는 표에 없는 값: 반영됨" in verify(HEAD + BAR, table).problems


@pytest.mark.parametrize("change,number", [
    (("label:'흡수(근무일)'", "label:'흡수 평균 7일'"), "7"),
    (("options:{", "options:{plugins:{title:{display:true,text:'총 지연 31일'}},"), "31"),
    (("<table>", "<p>총 지연 9일, 영향 31%</p><table>"), "31"),
    (("<table>", "<figcaption>5개 중 2개 흡수 99%</figcaption><table>"), "99"),
    (("<table>", "<svg><text>총 31일</text></svg><table>"), "31"),
    (("<table>", "<h3>지연 합계 12일</h3><table>"), "12"),
    (("options:{", "options:{scales:{y:{ticks:{callback:function(v){return v+'일(최대 12일)';}}}},"), "12"),
    (("<td>0</td>", "<td>-1</td>"), "-1"),
    (("<td>5</td>", "<td>1,234</td>"), "1,234"),
])
def test_numbers_anywhere_in_shown_text_must_be_ours(change, number):
    v = verify(HEAD + BAR.replace(*change), DELAY)
    assert f"보이는 글에 표에 없는 숫자: {number}" in v.problems


def test_code_literals_and_our_numbers_are_fine():
    tick = "options:{plugins:{tooltip:{callbacks:{label:function(c){return String(c.raw).padStart(2, '0') + '일';}}}},"
    assert verify(HEAD + BAR.replace("options:{", tick), DELAY).ok
    table = VisualTable(kind="delay_impact", title="지연", columns=DELAY.columns, rows=[["골조 1층", 5, 7, -2]], chart="bars",
                        version=3, data_date=date(2027, 3, 1))
    html = (HEAD + "<script>(function(){new Chart(c,{type:'bar',data:{labels:['골조 1층'],datasets:[{label:'a',data:[5]},"
            "{label:'b',data:[7]},{label:'c',data:[-2]}]}});})();</script><table><tr><td>골조 1층</td><td>5</td><td>7</td>"
            "<td>-2</td></tr></table><p>골조 1층 준공 −2일</p></body></html>")
    assert verify(html, table).ok, verify(html, table).problems


@pytest.mark.parametrize("url", ["https://fonts.googleapis.com/css2?family=Noto", "//evil.example/x.js",
                                 "https://cdn.jsdelivr.net/npm/evil@1.0.0/x.js", "https://cdnjs.cloudflare.com/ajax/libs/d3/7.0.0/d3.js"])
def test_only_the_seen_cdn_paths_are_allowed(url):
    html = chart_html(ROWS).replace("</head>", f'<script src="{url}"></script></head>')
    assert f"허용하지 않은 외부 주소: {url}" in verify(html, TABLE).problems
