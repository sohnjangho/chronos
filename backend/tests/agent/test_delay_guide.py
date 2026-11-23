"""지연 기록 지시문(prompts/guides/delay.md): 기록한(열린) 지연이 화면 어디에 보이는지 화면과 같게 말한다(W2, 11-23)."""

from app.agent import context

DELAY_GUIDE = (context.GUIDES_DIR / "delay.md").read_text(encoding="utf-8")


def test_the_guide_does_not_promise_a_late_mark_that_no_screen_shows():
    assert '"늦음 +n"' not in DELAY_GUIDE


def test_the_guide_points_at_the_open_delay_band_on_the_gantt_and_progress_windows():
    assert "기록된 지연" in DELAY_GUIDE and "승인 전" in DELAY_GUIDE
    assert "간트차트" in DELAY_GUIDE and "공정률" in DELAY_GUIDE
