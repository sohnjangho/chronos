"""음성·글 지시문이 같이 쓰는 고정 줄과 등급별 범위 단락(Task 67)."""

from typing import get_args

import pytest

from app.outreach import redact
from app.outreach.harness import rules_text
from app.outreach.harness.toolsets import ALL
from app.outreach.harness.types import CallerClass

CLASSES = get_args(CallerClass)
KEYS = {"no_change", "no_money", "identity", "dates", "ai", "language", "emergency"}


def test_fixed_lines_and_scope_paragraphs_have_no_number_or_class_name():
    texts = [*rules_text.FIXED.values(), *(rules_text.scope_paragraph(cls) for cls in CLASSES)]
    for text in texts:
        assert text.strip() and redact.hide_phones(text) == text
        assert not any(ch.isdigit() for ch in text)
        bare = text
        for tool in ALL:  # 도구 이름(report_from_contact 등)은 등급 이름이 아니다
            bare = bare.replace(tool, "")
        assert not any(word in bare for word in (*CLASSES, "caller", "class", "scope"))


def test_fixed_lines_are_the_seven_rules_and_read_only():
    assert set(rules_text.FIXED) == KEYS
    with pytest.raises(TypeError):
        rules_text.FIXED["no_change"] = "바꿔도 됩니다"


def test_fixed_lines_name_only_real_tools_and_the_fixed_reply():
    assert "take_message" in rules_text.FIXED["identity"] and "등록된 번호로 다시 연락드리겠습니다" in rules_text.FIXED["identity"]
    assert "schedule_fact" in rules_text.FIXED["dates"]
    assert "handoff_to_human" in rules_text.FIXED["emergency"] and "emergency" in rules_text.FIXED["emergency"]
    for word in ("금액", "계약", "다른 협력사", "다른 프로젝트", "내부 평가", "만회안"):
        assert word in rules_text.FIXED["no_money"]
    named = {word for text in rules_text.FIXED.values() for word in text.replace("(", " ").replace(")", " ").split()
             if "_" in word}
    assert {word.strip("`.,·") for word in named} <= set(ALL) | {"emergency"}


@pytest.mark.parametrize("cls", CLASSES)
def test_scope_paragraph_per_class(cls):
    text = rules_text.scope_paragraph(cls)
    open_classes = ("internal", "contact", "contact_multi", "shared", "outbound")
    assert ("schedule_fact" in text) == (cls in open_classes)
    assert ("my_requests" in text) == (cls in ("contact", "contact_multi", "outbound"))
    if cls not in open_classes:
        assert "일정" in text and "말하지 않" in text
    if cls == "contact_multi":
        assert "현장" in text


def test_paragraphs_differ_only_where_the_scope_differs():
    assert rules_text.scope_paragraph("unknown") == rules_text.scope_paragraph("withheld")
    assert rules_text.scope_paragraph("contact") != rules_text.scope_paragraph("shared")
    assert rules_text.scope_paragraph("internal") != rules_text.scope_paragraph("contact")


def test_unknown_class_name_is_an_error():
    with pytest.raises(ValueError):
        rules_text.scope_paragraph("vip")
