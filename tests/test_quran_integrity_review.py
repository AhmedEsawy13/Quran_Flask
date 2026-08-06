"""Read-only dashboard tests for the Quran integrity audit report."""

from __future__ import annotations

import pytest

from modules import quran_integrity_review as review


def test_quran_integrity_review_page_renders(client):
    page = client.get("/quran-integrity-review")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "نتائج التدقيق" in body
    assert "quran_integrity_review.css" in body
    assert "quran_integrity_review.js" in body
    assert "/api/quran-integrity/report" in body


def test_quran_integrity_report_api_exposes_current_findings(client):
    if not review.REPORT_PATH.exists():
        pytest.skip("run --audit to install the integrity report")
    response = client.get("/api/quran-integrity/report")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    payload = response.get_json()
    assert payload["status"] == "review_required"
    assert payload["failure_count"] == 12
    assert len(payload["failures"]) == 12
    assert payload["reference"]["verse_count"] == 6236
    assert payload["layouts"]["azhar"]["missing_id_count"] == 58
    assert payload["word_meanings"]["status"] in {
        "not_harvested",
        "harvesting",
        "not_compared",
        "review_required",
        "no_text_differences",
    }
