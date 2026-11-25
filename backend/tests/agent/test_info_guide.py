"""정보 API 지시문(prompts/guides/info.md): 외부 공공데이터 요청에 골라 붙고, system.md 에는 늘 한 줄이 있다."""

import pytest

from app.agent import context
from app.agent.context import UiContext

NO_UI = UiContext(None, None, None)


@pytest.mark.parametrize("text", ["12월 공휴일 빼고 일정 짜 줘", "공공데이터로 입찰공고 마감일 봐 줘",
                                  "미세먼지 나쁜 날은 옥외 작업 빼 줘", "기상특보 나오면 타설 미뤄"])
def test_info_guide_is_picked_for_outside_public_data(text):
    assert "info" in context.select_guides(text, NO_UI, has_files=False)


def test_info_guide_is_not_picked_for_a_plain_delay():
    assert context.select_guides("골조가 4일 밀렸어", NO_UI, has_files=False) == ["delay"]


def test_info_guide_says_how_to_use_the_tools():
    prompt = context.system_prompt(["info"])
    guide = (context.GUIDES_DIR / "info.md").read_text(encoding="utf-8")
    assert guide in prompt
    for part in ("info__list", "info__call", "info__weather", "evidence_id", "키"):
        assert part in guide


def test_system_prompt_always_mentions_info_list():
    assert "info__list" in context.system_prompt([])


def test_a_bare_rest_day_word_does_not_pick_the_info_guide():
    assert context.select_guides("휴일 반영해서 지연 다시 계산해줘", NO_UI, has_files=False) == ["delay"]


def test_info_guide_lists_then_reads_one_usage_then_calls():
    guide = (context.GUIDES_DIR / "info.md").read_text(encoding="utf-8")
    assert "connection_id" in guide and guide.index("info__list") < guide.index("info__call")
