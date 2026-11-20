"""지시문(prompts/system.md)의 프로그램 목록: 화면 프로그램 id 와 이름(Task 16b — 일정판이 넷으로 나뉨)."""

import typing

from app.agent import context
from app.tools.ui.open_window import OpenWindowIn


def test_the_prompt_names_every_program_the_agent_can_open():
    prompt = context.system_prompt()
    ids = typing.get_args(OpenWindowIn.model_fields["program"].annotation)
    assert ids and all(f"`{i}`" in prompt for i in ids)
    for line in ("`schedule-table` 스케줄", "`gantt` 간트차트", "`cpm` CPM", "`progress` 공정률"):
        assert line in prompt


def test_the_old_schedule_board_is_gone_from_the_prompt():
    prompt = context.system_prompt()
    assert "일정판" not in prompt and "`schedule`" not in prompt
