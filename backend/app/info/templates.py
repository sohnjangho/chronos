"""정보 API 「빠른 채움」 목록(templates.yaml) 읽기. 항목마다 계약 모양으로 검사하고, 틀리면 몇 번째 항목인지 밝혀 실패한다.

모양: templates: [{id, label, base_url, key_in, key_name, description, usage, test_path, docs_url}] — 칸은 꼭 이것만.
주소는 저장할 때와 같은 검사(http(s)·내부망 아님), test_path 는 부를 때와 같은 경로 검사를 받는다.
"""

from pathlib import Path
from typing import Annotated, Literal

import httpx
import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.info import generic
from app.llm.connections import normalize_base_url

PATH = Path(__file__).with_name("templates.yaml")


def _base_url(value: str) -> str:
    url = normalize_base_url(value)
    if (problem := generic.base_url_problem(url)) is not None:
        raise ValueError(problem)
    return url


def _docs_url(value: str) -> str:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError("문서 주소가 올바르지 않습니다.") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError("문서 주소는 http:// 또는 https:// 로 시작해야 합니다.")
    return value


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z0-9]+([_-][a-z0-9]+)*$", max_length=60)]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    base_url: Annotated[str, AfterValidator(_base_url)]
    key_in: Literal["query", "header"]
    key_name: Annotated[str, Field(pattern=generic.KEY_NAME_PATTERN)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    usage: Annotated[str, Field(max_length=3000)]  # 연결의 usage 한도와 같다
    test_path: Annotated[str, Field(min_length=1, max_length=500)]
    docs_url: Annotated[str, AfterValidator(_docs_url)]

    @model_validator(mode="after")
    def _test_path(self) -> "Template":
        if (problem := generic.request_problem(self.test_path, {}, self.key_name)) is not None:
            raise ValueError(f"test_path: {problem}")
        return self


def load_templates(path: Path = PATH) -> list[Template]:
    """목록을 읽어 검사한다. 틀린 항목이 하나라도 있으면 ValueError(「빠른 채움 목록 n번(id)」)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"templates"} or not isinstance(data["templates"], list):
        raise ValueError("빠른 채움 목록: 'templates:' 아래 목록 하나만 있어야 합니다.")
    found: list[Template] = []
    for n, entry in enumerate(data["templates"]):
        name = entry.get("id") if isinstance(entry, dict) else None
        try:
            found.append(Template.model_validate(entry))
        except (ValidationError, ValueError) as e:
            raise ValueError(f"빠른 채움 목록 {n}번({name}): {e}") from None
    ids = [t.id for t in found]
    if duplicated := sorted({i for i in ids if ids.count(i) > 1}):
        raise ValueError(f"빠른 채움 목록: 같은 id 가 여럿입니다 — {', '.join(duplicated)}")
    return found
