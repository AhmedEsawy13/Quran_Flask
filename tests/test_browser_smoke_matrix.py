from pathlib import Path

from scripts import browser_smoke_matrix as smoke


ROOT = Path(__file__).resolve().parents[1]


def test_matrix_covers_every_critical_journey_at_two_widths():
    assert set(smoke.SCENARIOS) == {"desktop", "mobile"}
    assert {journey.name for journey in smoke.JOURNEYS} == {
        "reader", "memorize", "waqf", "editor", "layout_studio",
        "mark_review", "cv_labeling",
    }
    assert len({journey.shell_selector for journey in smoke.JOURNEYS}) == len(smoke.JOURNEYS)


def test_memorize_adds_narrow_and_short_landscape_edges():
    assert set(smoke.MEMORIZE_EDGE_SCENARIOS) == {"phone_narrow", "landscape_short"}
    assert smoke.MEMORIZE_EDGE_SCENARIOS["phone_narrow"]["width"] == 360
    assert smoke.MEMORIZE_EDGE_SCENARIOS["landscape_short"]["height"] == 390


def test_ci_installs_chromium_and_runs_the_matrix():
    workflow = (ROOT / ".github/workflows/browser-smoke.yml").read_text(encoding="utf-8")
    assert "playwright install --with-deps chromium" in workflow
    assert "python3 scripts/browser_smoke_matrix.py" in workflow


def test_cv_journey_uses_bahrain_reference_page_for_word_payload():
    journey = next(item for item in smoke.JOURNEYS if item.name == "cv_labeling")
    assert "page=17" in journey.path
    assert quote_path("البحرين") in journey.path


def quote_path(value: str) -> str:
    from urllib.parse import quote

    return quote(value)
