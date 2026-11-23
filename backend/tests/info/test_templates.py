"""빠른 채움 목록(app/info/templates.yaml) 읽기: 항목마다 계약 모양을 검사하고, 틀린 항목은 크게 실패한다."""

import pytest

from app.info import generic, templates

GOOD = """templates:
  - id: holidays
    label: 특일 정보(공휴일)
    base_url: https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService
    key_in: query
    key_name: ServiceKey
    description: 공휴일 목록입니다.
    usage: |
      /getRestDeInfo?solYear=2026&_type=json
    test_path: /getRestDeInfo?solYear=2026&solMonth=12&_type=json
    docs_url: https://www.data.go.kr/data/15012690/openapi.do
"""


def _write(tmp_path, text: str):
    path = tmp_path / "templates.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_real_file_loads_and_every_entry_validates():
    found = templates.load_templates()
    assert found, "templates.yaml 이 비었습니다"
    assert len({t.id for t in found}) == len(found)
    for t in found:
        assert generic.base_url_problem(t.base_url) is None
        assert generic.request_problem(t.test_path, {}, t.key_name) is None
        assert set(t.model_dump()) == {"id", "label", "base_url", "key_in", "key_name", "description", "usage",
                                       "test_path", "docs_url"}


def test_a_good_entry(tmp_path):
    [t] = templates.load_templates(_write(tmp_path, GOOD))
    assert (t.id, t.key_name, t.key_in) == ("holidays", "ServiceKey", "query")
    assert t.test_path == "/getRestDeInfo?solYear=2026&solMonth=12&_type=json"


def test_an_empty_list_is_fine(tmp_path):
    assert templates.load_templates(_write(tmp_path, "templates: []\n")) == []


@pytest.mark.parametrize(("old", "new"), [
    ("    label: 특일 정보(공휴일)\n", ""),  # 칸 빠짐
    ("    docs_url:", "    extra: 1\n    docs_url:"),  # 모르는 칸
    ("https://apis.data.go.kr/B090041", "http://127.0.0.1/B090041"),  # 내부망 주소
    ("https://apis.data.go.kr/B090041", "ftp://apis.data.go.kr/B090041"),
    ("key_in: query", "key_in: body"),
    ("key_name: ServiceKey", "key_name: Service Key"),
    ("test_path: /getRestDeInfo", "test_path: //evil.example/getRestDeInfo"),
    ("test_path: /getRestDeInfo?", "test_path: /getRestDeInfo?ServiceKey=x&"),
    ("description: 공휴일 목록입니다.", "description: ''"),
    ("id: holidays", "id: Holidays!"),
    ("docs_url: https://www.data.go.kr", "docs_url: javascript:alert(1)//www.data.go.kr"),
])
def test_a_bad_entry_fails_loudly_naming_it(tmp_path, old, new):
    assert old in GOOD
    with pytest.raises(ValueError, match="빠른 채움 목록 0번"):
        templates.load_templates(_write(tmp_path, GOOD.replace(old, new)))


def test_duplicate_ids_fail(tmp_path):
    entry = GOOD.split("templates:\n", 1)[1]
    with pytest.raises(ValueError, match="holidays"):
        templates.load_templates(_write(tmp_path, GOOD + entry))


@pytest.mark.parametrize("text", ["", "templates:\n", "- a\n", "templates: []\nother: 1\n"])
def test_a_bad_top_level_fails(tmp_path, text):
    with pytest.raises(ValueError, match="빠른 채움 목록"):
        templates.load_templates(_write(tmp_path, text))
