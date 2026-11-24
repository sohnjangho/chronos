"""Liner Search Premium Data: 응답의 `knowledge[]` 표 읽기(`search.liner_knowledge` 가 받은 것).

- 표 한 개 = `{title, description, sources[], dataAsOf, columns[], rows[[글…]]}`(0단계 실측 11-24: 금속은 The World Bank
  월별 USD/톤, 환율은 Xignite 분 단위, 최근 30줄). 맞는 자료가 없으면 knowledge 가 없거나 빈 목록이다.
- 값은 글 그대로 둔다. 숫자로 읽는 것은 trend(코드가 계산) 뿐이고, 숫자가 아니거나 모자라면 None — 지어내지 않는다.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeTable:
    title: str
    source: str | None  # sources 를 「, 」로 이음. 없으면 None
    as_of: str | None  # dataAsOf
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def _texts(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(v, str | int | float) and not isinstance(v, bool)
                                              for v in value):
        return None
    return tuple(str(v) for v in value)


def _table(item: object) -> KnowledgeTable | None:
    if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
        return None
    columns = item.get("columns")
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        return None
    rows = item.get("rows")
    if not isinstance(rows, list):
        return None
    read = [_texts(r) for r in rows]
    sources = item.get("sources")
    names = [s.strip() for s in sources if isinstance(s, str) and s.strip()] if isinstance(sources, list) else []
    as_of = item.get("dataAsOf")
    return KnowledgeTable(title=item["title"].strip(), source=", ".join(names) or None,
                          as_of=(as_of.strip() or None) if isinstance(as_of, str) else None,
                          columns=tuple(columns), rows=tuple(r for r in read if r is not None))


def read(resp: dict) -> list[KnowledgeTable]:
    """응답 본문 → 표 목록(받은 차례). knowledge 가 없거나 목록이 아니면 []. 모양이 틀린 표는 버린다."""
    found = resp.get("knowledge") if isinstance(resp, dict) else None
    if not isinstance(found, list):
        return []
    return [t for t in map(_table, found) if t is not None]


def _number(row: tuple[str, ...]) -> float | None:
    if len(row) < 2:
        return None
    try:
        value = float(row[1])
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def sorted_rows(table: KnowledgeTable) -> list[tuple[str, ...]]:
    """때(첫 칸) 차례. 첫 칸이 없는 줄은 뺀다."""
    return sorted((r for r in table.rows if r), key=lambda r: r[0])


def trend(table: KnowledgeTable, months: int = 3) -> tuple[float, float, float] | None:
    """(앞 값, 뒤 값, %): 마지막 줄과 그보다 months 줄 앞(월별 표에서 months 개월 앞)의 값. 줄이 모자라거나 두 값 중
    하나라도 숫자가 아니거나 앞 값이 0 이면 None."""
    rows = sorted_rows(table)
    if len(rows) <= months:
        return None
    prev, last = _number(rows[-1 - months]), _number(rows[-1])
    if prev is None or last is None or prev == 0:
        return None
    return prev, last, (last - prev) / prev * 100
