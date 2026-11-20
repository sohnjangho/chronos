"""files.read — 파일 하나를 읽는다: 관련 조각(query)·그 쪽(page)·앞 조각을 출처 위치(locator)와 함께.

- 보는 범위는 지금은 회사 전체(지우지 않은 파일이면 누구나). 지운 파일은 「지워진 파일입니다.」, 없는 파일은
  「없는 파일입니다.」(ToolError — 턴은 이어 간다).
- query 를 주면 그 파일 안에서 뜻+낱말 검색 상위 PARTS 개(app.files.search.search 의 file_ids). 없으면 page 의 조각,
  page 도 없으면 앞 PARTS 조각. page: PDF 는 그 쪽(「n쪽」), 엑셀은 n번째 시트, 그 밖은 1쪽(전체)뿐.
- 조각 글은 PART_LIMIT 자까지 — 조각끼리 100자 겹치므로 이어진 조각은 잃는 글이 없고, 5개가 도구 결과 한도(4,000자) 안에 든다.
- image=true 이고 그림 파일이면 image true — 루프가 그 그림을 다음 메시지에 끼우고 그 단계부터 턴 끝까지
  「그림 읽기」 모델로 부른다(app.agent.image_turn). 그림이 너무 크면 false.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.agent.image_turn import IMAGE_MAX_BYTES
from app.files.search import search
from app.store import files as file_store
from app.store.tables import FileChunk, FileRow
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

PARTS = 5
PART_LIMIT = 700
NOT_FOUND = "없는 파일입니다."
DELETED = "지워진 파일입니다."


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int = Field(description="파일 id(「이 대화에 붙인 파일」의 #id, files__search 결과의 file_id)")
    query: str | None = Field(default=None, min_length=1, max_length=200,
                              description="이 파일 안에서 찾을 말. 주면 관련 조각 5개")
    page: int | None = Field(default=None, ge=1, description="쪽 번호(PDF) 또는 시트 번호(엑셀). query 가 없을 때만 본다")
    image: bool = Field(default=False, description="그림 파일의 그림 자체를 다시 볼 때만 true(이 단계부터 그림 읽기 모델)")


class PartOut(BaseModel):
    locator: str  # 출처 위치: 「3쪽」·「공정표 행 1–20」·「본문」
    text: str  # PART_LIMIT 자까지


class ReadOut(BaseModel):
    file_id: int
    name: str
    kind: str  # image|table|sheet|pdf|doc|text
    status: str  # received|extracted|indexed|classified|failed
    reason: str | None  # 실패·주의의 까닭(예: 스캔 문서)
    pages: int | None  # PDF 쪽 수 · 엑셀 시트 수
    parts: list[PartOut]
    image: bool  # true 면 다음 메시지에 그 그림이 붙는다


def _row(ctx: ToolContext, file_id: int) -> FileRow:
    row = ctx.session.get(FileRow, file_id)
    if row is None:
        raise ToolError(NOT_FOUND)
    if row.deleted_at is not None:
        raise ToolError(DELETED)
    return row


def _sheet(locator: str) -> str:
    return locator.rsplit(" 행 ", 1)[0]


def _page(row: FileRow, pieces: list[FileChunk], page: int) -> list[FileChunk]:
    """그 쪽의 조각(자료함 미리 보기와 같은 규칙). 없는 쪽이면 ToolError."""
    pages = (row.pages or 1) if row.kind in ("pdf", "sheet") else 1
    if page > pages:
        raise ToolError(f"없는 쪽입니다(이 파일은 {pages}쪽까지입니다).")
    if row.kind == "pdf":
        return [p for p in pieces if p.locator == f"{page}쪽"]
    if row.kind == "sheet":
        sheets = list(dict.fromkeys(_sheet(p.locator) for p in pieces))
        return [p for p in pieces if page <= len(sheets) and _sheet(p.locator) == sheets[page - 1]]
    return pieces


async def _parts(ctx: ToolContext, row: FileRow, args: ReadIn) -> list[tuple[str, str]]:
    if args.query is not None:
        hits = await search(ctx.session, args.query, limit=PARTS, file_ids=[row.id])
        return [(h.locator, h.text) for h in hits]
    pieces = file_store.chunks_of(ctx.session, row.id)
    if args.page is not None:
        pieces = _page(row, pieces, args.page)
    return [(p.locator, p.text) for p in pieces[:PARTS]]


@tool(
    "files.read",
    "파일 하나를 읽는다(「이 대화에 붙인 파일」의 #id 나 files__search 결과의 file_id). query 를 주면 그 파일 안에서 "
    "관련 조각 5개, page 를 주면 그 쪽(PDF)·시트(엑셀), 둘 다 없으면 앞 5조각. 조각마다 locator(「3쪽」·「공정표 행 1–20」)가 "
    "있다 — 답에 쓸 때 「파일 이름 · locator」로 출처를 붙인다. 그림 파일의 조각은 그림 설명 글이다. 그림 자체를 다시 봐야 "
    "할 때만 image true(이 단계부터 그림 읽기 모델). 지운 파일은 읽을 수 없다.",
)
async def read_file(args: ReadIn, ctx: ToolContext) -> ReadOut:
    row = _row(ctx, args.file_id)
    parts = [PartOut(locator=locator, text=text[:PART_LIMIT]) for locator, text in await _parts(ctx, row, args)]
    image = args.image and row.kind == "image" and row.size <= IMAGE_MAX_BYTES
    return ReadOut(file_id=row.id, name=row.name, kind=row.kind, status=row.status, reason=row.reason,
                   pages=row.pages, parts=parts, image=image)
