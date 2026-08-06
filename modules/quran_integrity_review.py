"""Read-only UI and API for the local Quran integrity audit report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import jsonify, render_template

from core.blueprints import core_bp


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "artifacts" / "quran-integrity" / "integrity-report.json"
WORD_COMPARISON_PATH = ROOT / "artifacts" / "quran-integrity" / "word-meaning-comparison.json"
WORD_MANIFEST_PATH = ROOT / "artifacts" / "quran-integrity" / "mcp-word-meaning-manifest.json"

FINDING_LABELS = {
    "reference_text_word_count": "مرجع MCP · اختلاف عدد الكلمات",
    "json_sources.digital_khatt": "Digital Khatt · النص الخام",
    "json_sources.qpc_hafs": "QPC Hafs · النص الخام",
    "json_sources.indopak": "Indopak · النص الخام",
    "json_sources.tanzil_uthmani": "Tanzil Uthmani · النص الخام",
    "databases.quran_script": "quran_script.db · الكلمات والمعرّفات",
    "databases.word_name": "word_name.db · معاني MCP",
    "databases.waqf_symbols": "waqf_symbols.db · علامات الوقف",
    "databases.mushaf_waqf": "mushaf_waqf.db · مواضع الوقف",
    "databases.classical_waqf": "classical_waqf.db · الوقف التراثي",
    "layouts.bahrain": "Bahrain · مخطط الصفحات",
    "layouts.shamarly": "Shemrly · مخطط الصفحات",
    "layouts.azhar": "Azhar · مخطط الصفحات",
    "word_meanings": "معاني الكلمات · مقارنة MCP والمحلي",
}

GROUP_LABELS = {
    "reference": "المرجع",
    "json_sources": "مصادر النص",
    "databases": "قواعد البيانات",
    "layouts": "مخططات الصفحات",
    "word_meanings": "معاني الكلمات",
}

REVIEW_URLS = {
    "layouts.shamarly": "/waqf-mark-review",
    "layouts.azhar": "/azhar-waqf-review",
}


def load_report() -> dict[str, Any] | None:
    """Load the ignored report without making the audit a runtime dependency."""
    try:
        with REPORT_PATH.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    comparison = _load_word_comparison()
    value["word_meanings"] = comparison
    return value


def _load_word_comparison() -> dict[str, Any]:
    try:
        with WORD_COMPARISON_PATH.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        manifest = _load_word_manifest()
        if manifest:
            return {
                "status": "harvesting" if not manifest.get("complete") else "not_compared",
                "recommendation": "run pipeline/compare_word_meanings.py --compare",
                "coverage": {
                    "mcp_word_count": manifest.get("expected_words", 0),
                    "mcp_cached_word_count": manifest.get("cached_words", 0),
                },
                "errors": manifest.get("errors", []),
                "verse_level": {"finding_count": 0, "findings": []},
                "phrase_level": {"group_count": 0, "unresolved_alignment_count": 0, "findings": []},
                "word_level": {
                    "comparable_word_count": 0,
                    "meaning_comparison_count": 0,
                    "exact_text_match_count": 0,
                    "meaning_difference_count": 0,
                    "meaning_unavailable_count": 0,
                    "findings": [],
                },
            }
        return {
            "status": "not_harvested",
            "recommendation": "run pipeline/compare_word_meanings.py --fetch --compare",
            "coverage": {},
            "verse_level": {"finding_count": 0, "findings": []},
            "phrase_level": {"group_count": 0, "unresolved_alignment_count": 0, "findings": []},
            "word_level": {
                "comparable_word_count": 0,
                "meaning_comparison_count": 0,
                "exact_text_match_count": 0,
                "meaning_difference_count": 0,
                "meaning_unavailable_count": 0,
                "findings": [],
            },
        }
    return value if isinstance(value, dict) else {"status": "not_harvested"}


def _load_word_manifest() -> dict[str, Any] | None:
    try:
        with WORD_MANIFEST_PATH.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def report_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "status": "missing",
            "failure_count": 0,
            "verse_count": 0,
            "word_count": 0,
            "text_token_count": 0,
            "sha256": "",
        }
    reference = report.get("reference") or {}
    return {
        "available": True,
        "status": report.get("status", "unknown"),
        "failure_count": int(report.get("failure_count") or 0),
        "verse_count": int(reference.get("verse_count") or 0),
        "word_count": int(reference.get("word_count") or 0),
        "text_token_count": int(reference.get("text_token_count") or 0),
        "sha256": reference.get("sha256", ""),
    }


@core_bp.route("/quran-integrity-review")
def quran_integrity_review_page():
    """Render the local, read-only audit review dashboard."""
    return render_template(
        "quran_integrity_review.html",
        summary=report_summary(load_report()),
    )


@core_bp.route("/api/quran-integrity/report")
def quran_integrity_report():
    """Return the generated report for the dashboard's expandable details."""
    report = load_report()
    if report is None:
        return jsonify({
            "error": "integrity report is unavailable; run the audit first",
            "path": str(REPORT_PATH),
        }), 404
    return jsonify(report)
