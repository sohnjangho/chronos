"""파일 API 의 응답 모양."""

from datetime import datetime

from pydantic import BaseModel


class UploadItem(BaseModel):
    file_id: int
    name: str
    kind: str  # image|table|sheet|pdf|doc|text
    status: str  # received|extracted|indexed|classified|failed
    reason: str | None  # 실패나 주의(스캔 문서)의 까닭


class UploadOut(BaseModel):
    items: list[UploadItem]


class FileOut(BaseModel):
    file_id: int
    name: str
    ext: str
    kind: str
    size: int
    status: str
    reason: str | None
    uploaded_by: int  # 올린 사용자 id
    uploaded_at: datetime
    pages: int | None  # PDF 쪽 수 · 시트 수 · 그 밖은 1
    summary: str
    deleted: bool
    axes: dict[str, list[str]]  # 축 → 값들(분류 단계, Task 49)


class PreviewOut(BaseModel):
    file_id: int
    kind: str
    page: int  # PDF 는 쪽, 엑셀은 시트 차례(1부터), 그 밖은 1
    pages: int
    text: str  # 그 쪽·시트의 뽑은 글(조각 겹침을 지운 것). 그림은 빈 글(원본은 /raw)
    truncated: bool
