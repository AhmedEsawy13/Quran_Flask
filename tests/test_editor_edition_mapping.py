"""Editor marks and word ids across the editions with their own text or layout (قطر، المساحة)."""
import os
import sqlite3

import pytest

from core.config import MESAHA_LAYOUT_DATABASE, MUSHAF_WAQF_DATABASE
from modules import editor
from modules import layout_studio
from modules.layout_editions import MESAHA
from modules.layouts import _find_mushaf_row_match_index


def _mesaha_word_id(surah, ayah, position):
    return layout_studio._project_word_map(MESAHA)['key_to_id'][f'{surah}:{ayah}:{position}']


def test_row_matching_folds_the_undotted_final_yaa():
    # مصحف قطر pages carry Tanzil text (نَفْسِى); the waqf rows spell it نَفۡسِيۖ
    words = [{'text': 'عَلَىٰ'}, {'text': 'نَفْسِى'}, {'text': 'وَإِنِ'}]
    row = {'clean_token': 'نَفۡسِيۖ', 'word_index': 2, 'token_index': 7}
    assert _find_mushaf_row_match_index(words, row) == 1
    # a stricter match still wins over the folded one
    words = [{'text': 'نَفْسِى'}, {'text': 'نَفۡسِي'}]
    assert _find_mushaf_row_match_index(words, {'clean_token': 'نَفۡسِيۖ', 'token_index': 1}) == 1


def test_qatar_spread_shows_marks_on_yaa_ending_words(client):
    # 36:61 «ٱعۡبُدُونِيۚ» carries قطر's only mark of the ayah
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    try:
        expected = conn.execute(
            'SELECT COUNT(*) FROM waqf WHERE "السورة" = 36 AND "الآية" = 61 '
            'AND "قطر" IS NOT NULL AND "قطر" <> \'\''
        ).fetchone()[0]
    finally:
        conn.close()
    if not expected:
        pytest.skip('no قطر mark on 36:61 in this database')
    page = client.get('/api/mushaf-editor/page-by-ayah/36/61?edition=قطر').get_json()['page_number']
    spread = client.get(f'/api/mushaf-editor/spread/{(page + 1) // 2}?edition=قطر').get_json()
    shown = 0
    for side in (spread['right'], spread['left']):
        for line in (side or {}).get('lines') or []:
            for word in line.get('words') or []:
                if (word.get('surah'), word.get('ayah')) != (36, 61):
                    continue
                marks = word.get('waqf_symbols')
                shown += sum(
                    1 for mark in (marks if isinstance(marks, list) else [])
                    if mark.get('version') == 'قطر' and mark.get('symbols')
                )
    assert shown == expected


@pytest.mark.parametrize('surah, ayah, position, token', [
    (2, 72, 4, 3),      # فَٱدَّٰرَٰءۡتُمۡ: hamza on the line here, combining in Digital Khatt
    (2, 157, 9, 8),     # ٱلۡمُهۡتَدُونَ١٥٧: the ayah number is glued to the word
    (3, 110, None, 22),
    (15, 7, 1, 1),      # لَّوۡمَا is two Digital Khatt tokens; the sign sits on the second
    (27, 20, None, 4),
    (36, 22, 1, 1),
])
def test_mesaha_words_with_a_different_spelling_reach_a_cloud_token(surah, ayah, position, token):
    if not os.path.exists(MESAHA_LAYOUT_DATABASE):
        pytest.skip('Mesaha layout database not present')
    tokens = editor._mesaha_ayah_tokens(surah, ayah)
    assert len(set(tokens.values())) == len(tokens), 'two Mesaha words on one cloud token'
    if position is not None:
        assert tokens[_mesaha_word_id(surah, ayah, position)] == token
    else:
        assert token in tokens.values()


def test_closed_page_row_budget_counts_rows_not_slots():
    # Mesaha pages 2-3 hold 8 rows (name + info + basmallah + 5 ayah rows); the two-slot basmallah of the
    # profile must not take one off, or undo/header moves merge two ayah rows of the page
    profile = layout_studio._load_profile(MESAHA)
    for page in (2, 3):
        rows = [{'line_type': t} for t in ('surah_name', 'surah_info', 'basmallah', *['ayah'] * 5)]
        assert layout_studio._page_row_budget(MESAHA, profile, page, rows=rows) == 8
