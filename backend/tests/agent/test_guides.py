"""지시문 조각(prompts/guides/*.md): system.md 뒤에 이름 순으로 붙는다(Task 21)."""

from app.agent import context
from app.tools.registry import list_tools, load_all


def test_guides_are_appended_in_name_order(monkeypatch, tmp_path):
    (tmp_path / "b.md").write_text("둘째", encoding="utf-8")
    (tmp_path / "a.md").write_text("첫째", encoding="utf-8")
    (tmp_path / "_x.md").write_text("숨김", encoding="utf-8")
    monkeypatch.setattr(context, "GUIDES_DIR", tmp_path)
    p = context.system_prompt()
    assert p.index("첫째") < p.index("둘째") and "숨김" not in p
    assert p.endswith("\n\n첫째\n\n둘째")


def test_no_guides_leaves_the_prompt_as_before(monkeypatch, tmp_path):
    (tmp_path / "notes.txt").write_text("md 가 아님", encoding="utf-8")
    monkeypatch.setattr(context, "GUIDES_DIR", tmp_path)
    p = context.system_prompt()
    assert "md 가 아님" not in p and "{{" not in p


def test_guides_dir_is_under_prompts():
    assert context.GUIDES_DIR == context.PROMPT.parent / "guides" and context.GUIDES_DIR.is_dir()


def test_guides_name_tools_as_the_model_sees_them():
    load_all()
    names = {s.name for s in list_tools(enabled_only=False)}
    for f in context.GUIDES_DIR.glob("*.md"):
        assert not [n for n in names if n in f.read_text(encoding="utf-8")], f.name  # 점 표기 금지(__ 꼴만)
