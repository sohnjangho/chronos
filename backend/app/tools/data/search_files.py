"""files.search — 자료함(지금은 회사 전체)에서 뜻+낱말로 조각을 찾는다. 이 대화에 붙인 파일이 먼저
(점수 ×app.files.search.PREFER).

- filters {축: [값]}: 축 안의 값은 하나라도, 축끼리는 모두 맞는 파일만. 지운 파일은 나오지 않는다.
- 결과마다 파일 이름·위치(locator)·조각 글(TEXT_LIMIT 자까지)·그 파일의 축 값.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.files.search import search
from app.store import files as file_store
from app.store.tables import FileRow
from app.tools.context import ToolContext
from app.tools.registry import tool

TEXT_LIMIT = 400


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200, description="찾을 말(예: 동절기 콘크리트 양생 기간)")
    filters: dict[str, list[str]] | None = Field(
        default=None,
        description='분류 축별 값으로 거르기(예: {"종류": ["시방서"], "공종": ["골조"]}). 축: 종류·공종·현장·시기·출처',
    )
    limit: int = Field(default=5, ge=1, le=10, description="결과 수")


class HitOut(BaseModel):
    file_id: int
    name: str
    locator: str  # 출처 위치: 「3쪽」·「공정표 행 1–20」·「본문」
    text: str  # TEXT_LIMIT 자까지
    axes: dict[str, list[str]]  # 그 파일의 분류 값


class SearchOut(BaseModel):
    hits: list[HitOut]


@tool(
    "files.search",
    "자료함 전체(이 대화에 붙인 파일이 먼저)에서 뜻+낱말로 조각을 찾는다. 이 대화의 파일만으로 모자랄 때 쓴다. "
    "결과마다 file_id·파일 이름·locator·조각 글·분류 값 — 더 읽으려면 files__read. 답에 쓸 때 「파일 이름 · locator」로 "
    "출처를 붙인다.",
)
async def search_files(args: SearchIn, ctx: ToolContext) -> SearchOut:
    prefer = [] if ctx.chat_session_id is None else [f.id for f in file_store.session_files(ctx.session, ctx.chat_session_id)]
    hits = await search(ctx.session, args.query, limit=args.limit, filters=args.filters, prefer_file_ids=prefer)
    out = []
    for h in hits:
        row = ctx.session.get(FileRow, h.file_id)
        out.append(HitOut(file_id=h.file_id, name=row.name, locator=h.locator, text=h.text[:TEXT_LIMIT],
                          axes=file_store.axes_of(ctx.session, h.file_id)))
    return SearchOut(hits=out)
