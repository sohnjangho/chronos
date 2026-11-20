"""파일 API 의 응답 모양."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class ReindexJobOut(BaseModel):
    """다시 넣기(임베딩 모델 바꾸기) 한 번. status: running|done|failed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    model: str
    status: str
    total: int  # 넣을 조각 수
    done: int
    started_at: datetime
    finished_at: datetime | None


class ReindexStatusOut(BaseModel):
    active_model: str  # 지금 검색에 쓰는 모델(마지막으로 끝난 다시 넣기의 모델)
    assigned_model: str  # 배정(설정)의 임베딩 모델
    job: ReindexJobOut | None  # 마지막 다시 넣기(없으면 null)


class ReindexStartOut(BaseModel):
    job_id: int
    total: int
