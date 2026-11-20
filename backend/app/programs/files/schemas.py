"""파일 API 의 응답 모양."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class FileListOut(BaseModel):
    """자료함 목록(숨긴 파일 빼고). q 가 없으면 올린 때 새것부터, 있으면 이름 맞음 → 내용(뜻+낱말) 맞음 차례."""

    items: list[FileOut]
    total: int  # 거르기·찾기에 맞는 파일 수(모든 쪽)
    page: int
    page_size: int


class AxisValueOut(BaseModel):
    value: str
    count: int  # 이 값을 가진 보이는 파일 수(0 이면 지금 쓰는 파일 없음)
    is_new: bool  # 에이전트가 새로 만든 값을 아직 사람이 확인하지 않음(자료함 「새」)


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    axis: str
    from_: list[str] = Field(alias="from", min_length=1, max_length=200)
    to: str


class MergeOut(BaseModel):
    axis: str
    to: str
    files: int  # 값이 바뀐 파일 수


class MergeSuggestionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    axis: str
    from_: list[str] = Field(alias="from")
    to: str
    why: str


class MergeSuggestionsOut(BaseModel):
    made_at: datetime | None  # 마지막으로 만든 때(하루 한 번). 아직 없으면 null
    items: list[MergeSuggestionOut]
