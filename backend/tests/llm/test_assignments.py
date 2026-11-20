"""쓰임새별 배정 풀기(app.llm.assignments)와 LLM 쪽 도구 이름."""

import pytest

from app.llm.assignments import Assignment, resolve, resolve_all
from app.llm.names import from_llm_name, to_llm_name
from app.store.tables import LlmAssignment
from tests.llm_doubles import add_connection


def test_defaults_point_at_default_connection(session):
    conn = add_connection(session)
    assert resolve_all(session) == [
        Assignment("light", conn.id, "liner-claude-router", "cost"),
        Assignment("normal", conn.id, "liner-claude-router", "balanced"),
        Assignment("hard", conn.id, "liner-claude-router", "quality"),
        Assignment("longdoc", conn.id, "liner-mark", None),
        Assignment("vision", conn.id, "liner-claude-router", "balanced"),
        Assignment("embedding", conn.id, "openai/text-embedding-3-small", None),
    ]


def test_defaults_without_connection_have_no_connection_id(session):
    assert resolve(session, "hard") == Assignment("hard", None, "liner-claude-router", "quality")


def test_stored_assignment_wins(session):
    conn = add_connection(session)
    session.add(LlmAssignment(purpose="hard", connection_id=conn.id, model="m", routing_strategy=None))
    session.commit()
    assert resolve(session, "hard") == Assignment("hard", conn.id, "m", None)
    assert resolve(session, "light").model == "liner-claude-router"


def test_unknown_purpose_is_an_error(session):
    with pytest.raises(KeyError):
        resolve(session, "huge")


@pytest.mark.parametrize(
    ("name", "llm_name"),
    [("schedule.read", "schedule__read"), ("ui.open_window", "ui__open_window"), ("spy", "spy")],
)
def test_tool_name_mapping_both_ways(name, llm_name):
    assert to_llm_name(name) == llm_name and from_llm_name(llm_name) == name
