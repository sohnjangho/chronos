"""지시문 조각 visual.md(Task 44): 언제 그림을 권하는지, 숫자를 넣지 않는지, 대조 결과를 그대로 말하는지."""

from app.agent import context


def test_visual_guide_rules():
    text = (context.GUIDES_DIR / "visual.md").read_text(encoding="utf-8")
    for words in ("visual__make", "보고서", "숫자를 넣지 않는다", "캡션", "숫자 대조 통과", "기본 그림", "note",
                  "summary", "delay_impact", "scenario_compare", "s_curve", "resource_load", "20~30초"):
        assert words in text, words
