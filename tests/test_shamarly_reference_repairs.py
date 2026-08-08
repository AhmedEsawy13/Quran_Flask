"""Regressions derived from the PDF-verified ShemrlyMushaf project."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from core.config import QURAN_SCRIPT_DATABASE, SHAMARLY_LAYOUT_DATABASE, _BASE_DIR
from modules import layouts
from pipeline import audit_quran_integrity as audit


def _payload_words(page: int) -> dict[str, dict]:
    payload = layouts._build_shamarly_page_payload(page)
    assert payload and payload["glyph_mapping_mode"] == "shemrly-page-local"
    return {
        word["word_key"]: word
        for line in payload["lines"]
        for word in line["words"]
    }


def test_shamarly_layout_passes_the_full_canonical_integrity_audit():
    report = audit.audit_layouts(
        {"shamarly": Path(SHAMARLY_LAYOUT_DATABASE)},
        Path(QURAN_SCRIPT_DATABASE),
    )["shamarly"]
    assert report["status"] == "ok"
    for field in (
        "missing_id_count",
        "foreign_id_count",
        "unknown_ayah_endpoint_count",
        "cross_surah_line_count",
        "line_text_mismatch_count",
        "span_error_count",
        "ordering_error_count",
        "unresolved_order_count",
        "empty_ayah_line_count",
    ):
        assert report[field] == 0, (field, report[field])


def test_pdf_verified_page_boundaries_are_in_canonical_order():
    word_map = layouts.layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    id_to_key = {
        word_id: token["word_key"]
        for word_id, token in word_map["id2tok"].items()
    }
    with sqlite3.connect(SHAMARLY_LAYOUT_DATABASE) as connection:
        page_42 = connection.execute(
            "SELECT line_number,line_type,first_word_id,surah_number "
            "FROM pages WHERE page_number=42 ORDER BY line_number"
        ).fetchall()
        page_385 = connection.execute(
            "SELECT line_number,line_type,first_word_id,surah_number "
            "FROM pages WHERE page_number=385 ORDER BY line_number"
        ).fetchall()
        page_496 = connection.execute(
            "SELECT line_type,surah_number FROM pages "
            "WHERE page_number=496 AND line_number BETWEEN 1 AND 13"
        ).fetchall()

    assert id_to_key[page_42[0][2]] == "2:285:15"
    assert page_42[6][1] == "surah_name"
    assert page_42[6][3] == 3
    assert id_to_key[page_385[0][2]] == "38:79:4"
    assert page_385[5][1] == "surah_name"
    assert page_385[5][3] == 39
    assert all(line_type == "ayah" and surah == 76 for line_type, surah in page_496)


def test_every_bundled_shamarly_font_has_a_safe_word_mapping():
    font_dir = Path(_BASE_DIR) / "static" / "fonts"
    pages = sorted(
        int(name[12:15])
        for name in os.listdir(font_dir)
        if name.startswith("Shemrly-Page") and name.endswith(".woff2")
    )
    assert len(pages) == 200
    assert all(
        layouts._get_shamarly_page_glyph_overrides(page) is not None
        or layouts._get_shamarly_page_word_codepoint_map(page)
        for page in pages
    )


def test_exceptional_print_forms_use_explicit_glyph_overrides():
    # One printed ligature represents the canonical pair بَعۡدَ + مَا.
    page_209 = _payload_words(209)
    assert len(page_209["13:37:8"]["text"]) == 1
    assert page_209["13:37:9"]["suppress_render"] is True
    assert page_209["13:37:9"]["text"] == ""

    # Conversely, لَّوۡمَا is one canonical token printed with two glyphs.
    page_216 = _payload_words(216)
    assert len(page_216["15:7:1"]["text"]) == 2

    # These section ornaments have no dedicated page-font glyph and must use
    # their canonical Unicode text without shifting all following words.
    assert _payload_words(211)["14:10:1"]["text"] == "۞"
    assert _payload_words(213)["14:28:1"]["text"] == "۞"


def test_repaired_page_465_uses_its_non_monotonic_reference_glyph_order():
    page = _payload_words(465)
    assert ord(page["59:19:8"]["text"]) == 0xFB7A
    assert ord(page["60:1:1"]["text"]) == 0xFB51


def test_suppressed_ligature_tokens_are_not_rendered_as_empty_spans():
    source = (Path(_BASE_DIR) / "static" / "js" / "athar-mushaf.js").read_text(
        encoding="utf-8"
    )
    assert "if (word && word.suppress_render === true) return;" in source


def test_memorize_deep_links_accept_the_shamarly_source():
    source = (Path(_BASE_DIR) / "static" / "js" / "mushaf_memorize.js").read_text(
        encoding="utf-8"
    )
    assert "if (isMadinahSource(src) || src === 'shamarly')" in source
