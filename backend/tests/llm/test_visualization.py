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
)
from app.store.visuals import VisualTable
from tests.llm_doubles import KEY, add_connection
from tests.visual_doubles import VisualMock, atlas_body, chart_html

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


# ── 요청 글 ──────────────────────────────────────────────────────────


def test_query_says_which_columns_go_in_the_chart_and_which_in_the_table():
    table = VisualTable(kind="scenario_compare", title="안 비교", columns=["안", "준공", "크리티컬(개)"],
                        rows=[["지금 일정", "2027-07-06", 5]], chart="bars", version=1, data_date=None,
                        roles=("charted", "shown", "charted"))
    q = query_text(table)
    assert "그림에 그릴 열: 안, 크리티컬(개)" in q
    assert "그림 아래 표에만 적을 열: 준공" in q
    assert "그림 아래에 표 전체를 <table> 로" in q
    assert "그림 아래 표에만 적을 열" not in query_text(TABLE)


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
