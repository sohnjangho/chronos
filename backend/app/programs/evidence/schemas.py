"""근거 API 의 응답 모양."""

from pydantic import BaseModel


class LinkOut(BaseModel):
    condition_id: str | None
    assumption_label: str | None


class EvidenceOut(BaseModel):
    id: int
    title: str
    url: str
    hostname: str
    description: str
    date: str | None
    mode: str  # 'web' | 'scholar' …
    query: str
    links: list[LinkOut]


class RetiredOut(BaseModel):
    id: int
    retired: bool  # true 면 다시 쓰지 않는다(이미 붙은 곳에는 그대로 보인다)
