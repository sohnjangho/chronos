"""Liner Visualization(app.llm.visualization): 요청 모양·응답 읽기·오류·숫자 대조. 진짜 Liner 는 부르지 않는다."""

import json
from datetime import date

import httpx
import pytest

from app.llm import visualization
from app.llm.visualization import (
    VisualFailed,
    VisualNotReady,
    liner_visualize,
    query_text,
    verify,
)
from app.store.visuals import VisualTable
from tests.llm_doubles import KEY, add_connection
from tests.visual_doubles import CDN, VisualMock, atlas_body, chart_html

ROWS = [
    ["터파기", "2027-03-12", "2027-03-15"],
    ["기초 타설", "2027-04-02", "2027-04-09"],
    ["골조 1층", "2027-05-07", "2027-05-14"],
    ["골조 2층", "2027-06-04", "2027-06-18"],
    ["지붕 방수", "2027-06-25", "2027-07-06"],
]
TABLE = VisualTable(kind="summary", title="계획과 전망 끝", columns=["작업", "계획 끝", "전망 끝"], rows=ROWS,
                    chart="timeline", version=3, data_date=date(2027, 3, 1))


@pytest.fixture(autouse=True)
def no_gap(monkeypatch):
    monkeypatch.setattr(visualization, "MIN_GAP_S", 0.0)


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
    assert "HTML 에 없는 표 값: 2027-04-09" in v.problems


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


# ── 요청 글 ──────────────────────────────────────────────────────────


def test_query_is_fixed_frame_plus_csv():
    q = query_text(TABLE)
    assert q.startswith("아래 표의 값만 그대로 써서")
    assert "계산·반올림·추정·추가하지 마라" in q
    assert q.rstrip().endswith("지붕 방수,2027-06-25,2027-07-06")
    assert "작업,계획 끝,전망 끝" in q


# ── 부르기 ───────────────────────────────────────────────────────────


async def test_request_shape_and_atlas(session):
    add_connection(session)
    t = VisualMock(atlas_body(chart_html(ROWS)))
    a = await liner_visualize(session, "그려라", transport=t)
    assert t.last.method == "POST" and t.last.url.path == "/api/v1/tools/visualization"
    assert t.last.headers["x-api-key"] == KEY and "authorization" not in t.last.headers
    assert json.loads(t.last.content) == {"query": "그려라", "stream": False}  # is_search_context 없음
    assert (a.theme, a.resource_id, a.description) == ("comparison", "viz_test1", "작업별 계획과 전망 비교")
    assert a.html.startswith("<!DOCTYPE html>") and a.latency_ms >= 0


@pytest.mark.parametrize("status,code", [(400, "bad_request"), (401, "bad_key"), (402, "no_credit"),
                                         (429, "rate_limited"), (502, "server_error")])
async def test_http_errors_are_explained(session, status, code):
    add_connection(session)
    with pytest.raises(VisualFailed) as e:
        await liner_visualize(session, "q", transport=VisualMock(status))
    assert e.value.code == code and e.value.__context__ is None


async def test_data_error_chunk_and_missing_atlas_fail(session):
    add_connection(session)
    err = {"chunks": [{"type": "start"}, {"type": "data-error", "id": "data-error-1", "data": {"message": "실패"}}]}
    odd = {"chunks": [{"type": "data-atlas", "data": "x"}]}
    for body in (err, {"chunks": [{"type": "finish"}]}, {"chunks": "x"}, odd):
        with pytest.raises(VisualFailed) as e:
            await liner_visualize(session, "q", transport=VisualMock(body))
        assert e.value.code == "unknown"


async def test_timeout_is_explained(session):
    add_connection(session)
    with pytest.raises(VisualFailed) as e:
        await liner_visualize(session, "q", transport=VisualMock(httpx.ReadTimeout("느림")))
    assert e.value.code == "timeout"


async def test_no_connection_is_not_ready(session):
    with pytest.raises(VisualNotReady):
        await liner_visualize(session, "q", transport=VisualMock(atlas_body("x")))


async def test_calls_are_spaced(session, monkeypatch):
    add_connection(session)
    monkeypatch.setattr(visualization, "MIN_GAP_S", 0.2)
    t = VisualMock(atlas_body(chart_html(ROWS)))
    stamps = []
    for _ in range(2):
        await liner_visualize(session, "q", transport=t)
        stamps.append(visualization._last_start)
    assert stamps[1] - stamps[0] >= 0.2
