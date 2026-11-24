"""Premium Data(`knowledge` 표) 읽기·흐름 계산과 include_knowledge 켠 부르기. 진짜 Liner 는 부르지 않는다.

표본은 0단계 실측(11-24) 응답을 줄인 tests/fixtures/liner_knowledge_real_sample.json.
"""

import json
from pathlib import Path

import pytest

from app.llm import knowledge
from app.llm.knowledge import KnowledgeTable
from app.llm.search import SearchFailed, liner_knowledge
from tests.llm_doubles import add_connection
from tests.search_doubles import mock

SAMPLE = json.loads((Path(__file__).parent.parent / "fixtures" / "liner_knowledge_real_sample.json").read_text())


def test_read_real_metal_table():
    tables = knowledge.read(SAMPLE["aluminum"]["body"])
    assert len(tables) == 1
    t = tables[0]
    assert (t.title, t.source, t.as_of) == ("Aluminum Price", "The World Bank", "2026-10-01")
    assert t.columns == ("Timestamp", "spot_price - Aluminum Price")
    assert t.rows[0] == ("2024-05-01 00:00:00+00:00", "2565.0") and len(t.rows) == 4


@pytest.mark.parametrize("body", [SAMPLE["rebar_none"]["body"], {"results": []}, {"knowledge": None},
                                  {"knowledge": "표"}, [], "글"])
def test_read_without_knowledge_is_empty(body):
    assert knowledge.read(body) == []


def test_read_drops_broken_tables_keeps_good():
    good = SAMPLE["copper"]["body"]["knowledge"][0]
    body = {"knowledge": ["표", {"title": "제목만"}, {**good, "rows": "없음"}, {**good, "columns": [1, 2]}, good]}
    tables = knowledge.read(body)
    assert [t.title for t in tables] == ["Copper Price"]


def test_trend_three_months_from_real_rows():
    t = knowledge.read(SAMPLE["aluminum"]["body"])[0]
    prev, last, pct = knowledge.trend(t, months=3)
    assert (prev, last) == (2565.0, 2344.0)
    assert pct == pytest.approx((2344 - 2565) / 2565 * 100)


def test_trend_sorts_rows_by_time():
    t = knowledge.read(SAMPLE["aluminum"]["body"])[0]
    shuffled = KnowledgeTable(t.title, t.source, t.as_of, t.columns, tuple(reversed(t.rows)))
    assert knowledge.trend(shuffled, months=3)[:2] == (2565.0, 2344.0)


@pytest.mark.parametrize("rows", [
    (("2026-08-01", "10"), ("2026-09-01", "11"), ("2026-10-01", "12")),  # 3개월 앞 값이 없다
    (("2026-07-01", "10"), ("2026-08-01", "11"), ("2026-09-01", "12"), ("2026-10-01", "—")),  # 숫자 아님
    (("2026-07-01", ""), ("2026-08-01", "11"), ("2026-09-01", "12"), ("2026-10-01", "13")),
    (("2026-07-01", "nan"), ("2026-08-01", "11"), ("2026-09-01", "12"), ("2026-10-01", "13")),
    (("2026-07-01", "0"), ("2026-08-01", "11"), ("2026-09-01", "12"), ("2026-10-01", "13")),  # 0 으로 나눔
    (("2026-07-01",), ("2026-08-01", "11"), ("2026-09-01", "12"), ("2026-10-01", "13")),  # 칸 모자람
])
def test_trend_none_when_values_missing(rows):
    assert knowledge.trend(KnowledgeTable("t", None, None, ("Timestamp", "v"), rows), months=3) is None


async def test_liner_knowledge_turns_premium_data_on(session):
    add_connection(session)
    t = mock(200, SAMPLE["copper"]["body"])
    data = await liner_knowledge(session, "copper price", transport=t)
    sent = json.loads(t.last.content)
    assert sent == {"query": "copper price", "max_results": 3, "include_knowledge": True}  # country_code·lang 없음
    assert t.last.url.path == "/api/v1/tools/search/web"
    assert knowledge.read(data)[0].title == "Copper Price"


@pytest.mark.parametrize("status,body,code", [(402, {}, "no_credit"), (200, ["목록"], "unknown"),
                                              (200, "<html>", "unknown")])
async def test_liner_knowledge_failures(session, status, body, code):
    add_connection(session)
    with pytest.raises(SearchFailed) as e:
        await liner_knowledge(session, "copper price", transport=mock(status, body))
    assert e.value.code == code and e.value.__context__ is None
