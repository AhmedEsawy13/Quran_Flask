"""Keep Python and JSON waqf glyph maps in sync."""
from __future__ import annotations

import json
from pathlib import Path

from core.waqf_glyphs import SYMBOL_META, WAQF_GLYPH_MAP, waqf_glyph


def test_waqf_glyphs_json_matches_python():
    data = json.loads(Path('data/waqf_glyphs.json').read_text(encoding='utf-8'))
    assert data['glyph_map'] == WAQF_GLYPH_MAP
    assert data['symbol_meta'] == [list(row) for row in SYMBOL_META]


def test_indopak_small_high_marks_passthrough():
    assert waqf_glyph('ؕ') == 'ؕ'
    assert waqf_glyph('ؗۖ') == 'ؗۖ'
    assert waqf_glyph('ؔؕۘ') == 'ؔؕۘ'
