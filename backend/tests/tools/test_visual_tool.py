"""도구 visual.make: 표는 코드가 만들고(인자에 숫자 없음), Liner 그림은 대조를 거친다. 진짜 Liner 는 부르지 않는다."""

import json
import logging
from dataclasses import replace
from datetime import date

import pytest

from app.agent import context
from app.llm import visualization
from app.store.tables import Visual
from app.tools.registry import call, list_tools
from tests.llm_doubles import KEY, add_connection
from tests.visual_doubles import VisualMock, atlas_body, chart_html

GOOD = [["작업 A", "2027-03-01", "2027-03-03"], ["작업 B", "2027-03-04", "2027-03-05"]]
BAD = [["작업 A", "2027-03-01", "2027-03-03"], ["작업 B", "2027-03-04", "2027-03-06"]]


@pytest.fixture(autouse=True)
def setup(monkeypatch, session):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 1))
    monkeypatch.setattr(visualization, "MIN_GAP_S", 0.0)
    add_connection(session)


@pytest.fixture
def liner(monkeypatch):
    def use(*replies):
        t = VisualMock(*replies)
        monkeypatch.setattr(visualization, "TRANSPORT", t)
        return t
    return use


@pytest.fixture
def sctx(ctx, sid):
    return replace(ctx, schedule_id=sid)


def test_spec():
    spec = {t.name: t for t in list_tools()}["visual.make"]
    assert spec.mutates is True
    props = spec.input_model.model_json_schema()["properties"]
    assert set(props) == {"kind", "schedule_id", "version"}


async def test_make_verified_card(sctx, events, liner, sid, session):
    t = liner(atlas_body(chart_html(GOOD, bounds=None), theme="summary"))
    r = await call("visual.make", {"kind": "summary"}, sctx)
    assert r.ok, r.error
    o = r.output
    assert (o["verified"], o["passed"], o["total"], o["fallback"], o["theme"]) == (True, 6, 6, False, "summary")
    query = json.loads(t.last.content)["query"]
    assert "작업 A,2027-03-01,2027-03-03" in query and "is_search_context" not in json.loads(t.last.content)
    card = events[0].data
    assert card == {"kind": "visual", "visual_id": o["visual_id"], "schedule_id": sid, "visual_kind": "summary",
                    "title": o["title"], "version": 1, "data_date": "2027-03-01", "verified": True, "passed": 6,
                    "total": 6, "fallback": False, "note": ""}
    row = session.get(Visual, o["visual_id"])
    assert row.resource_id == "viz_test1" and row.attempts == 1


async def test_same_table_is_not_drawn_again(sctx, liner):
    t = liner(atlas_body(chart_html(GOOD, bounds=None)))
    first = await call("visual.make", {"kind": "summary"}, sctx)
    second = await call("visual.make", {"kind": "summary"}, sctx)
    assert len(t.requests) == 1
    assert second.output["visual_id"] == first.output["visual_id"]


async def test_retry_once_then_pass(sctx, liner):
    t = liner(atlas_body(chart_html(BAD, bounds=None)), atlas_body(chart_html(GOOD, bounds=None)))
    r = await call("visual.make", {"kind": "summary"}, sctx)
    assert len(t.requests) == 2 and r.output["verified"] is True


async def test_two_failures_fall_back_and_log(sctx, liner, session, caplog):
    t = liner(atlas_body(chart_html(BAD, bounds=None)))
    with caplog.at_level(logging.WARNING):
        r = await call("visual.make", {"kind": "summary"}, sctx)
    assert len(t.requests) == 2
    o = r.output
    assert (o["verified"], o["fallback"], o["note"]) == (False, True, "Liner 그림 검증 실패 → 기본 그림")
    assert "Liner 그림 검증 실패 → 기본 그림" in caplog.text and KEY not in caplog.text
    row = session.get(Visual, o["visual_id"])
    assert row.attempts == 2 and "HTML 에 없는 표 값: 2027-03-05" in row.checks_json["problems"]
    again = await call("visual.make", {"kind": "summary"}, sctx)  # 실패한 그림은 다시 쓰지 않는다
    assert len(t.requests) == 4 and again.output["visual_id"] != o["visual_id"]


async def test_liner_errors_fall_back_with_the_reason(sctx, liner):
    t = liner(429)
    r = await call("visual.make", {"kind": "summary"}, sctx)
    assert len(t.requests) == 2
    assert (r.output["fallback"], r.output["note"]) == (True, "Liner 그림 실패(rate_limited) → 기본 그림")


async def test_no_connection_falls_back_without_calling(sctx, liner, session):
    from app.store.tables import LlmConnection

    session.query(LlmConnection).delete()
    session.commit()
    t = liner(atlas_body(chart_html(GOOD, bounds=None)))
    r = await call("visual.make", {"kind": "summary"}, sctx)
    assert t.requests == []
    assert (r.output["fallback"], r.output["note"]) == (True, "Liner 연결이 없어 기본 그림")


async def test_no_data_is_a_tool_error(sctx, liner):
    r = await call("visual.make", {"kind": "delay_impact"}, sctx)
    assert (r.ok, r.error) == (False, "기록한 지연이 없습니다.")


async def test_schedule_id_argument_and_missing_schedule(ctx, liner, sid):
    t = liner(atlas_body(chart_html(GOOD, bounds=None)))
    assert (await call("visual.make", {"kind": "summary", "schedule_id": sid}, ctx)).ok
    r = await call("visual.make", {"kind": "summary", "schedule_id": 99}, ctx)
    assert (r.ok, r.error) == (False, "일정을 찾을 수 없습니다.")
    assert len(t.requests) == 1


async def test_numbers_are_not_arguments(sctx, liner):
    r = await call("visual.make", {"kind": "summary", "rows": [[1]]}, sctx)
    assert not r.ok and r.error.startswith("입력 형식 오류")
