"""Regression coverage for the three Madinah layouts offered by تثبيت."""

import sqlite3
from urllib.parse import quote

from core.config import QPC_V2_LAYOUT_DATABASE


def _word_bounds(payload):
    words = [word for line in payload['lines'] for word in line['words']]
    return words[0]['word_index'], words[-1]['word_index']


def test_qpc_v2_database_is_the_1421_digital_khatt_layout():
    with sqlite3.connect(QPC_V2_LAYOUT_DATABASE) as conn:
        name, pages, lines, font = conn.execute(
            'SELECT name, number_of_pages, lines_per_page, font_name FROM info LIMIT 1'
        ).fetchone()

    assert '1421' in name
    assert (pages, lines, font) == (604, 15, 'digitalkhatt')


def test_qpc_v2_page_api_uses_digital_khatt_font_and_native_boundaries(client):
    response = client.get('/api/qpc-v2/page/358')
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['source'] == 'qpc_v2'
    assert payload['font_name'] == 'Digital Khatt'
    assert payload['layout_name'] == 'Digital Khatt (KFGQPC V2 1421H print)'
    assert payload['page_number'] == 358
    assert payload['lines_per_page'] == 15
    assert len(payload['lines']) == 15

    with sqlite3.connect(QPC_V2_LAYOUT_DATABASE) as conn:
        expected = conn.execute(
            "SELECT MIN(CAST(first_word_id AS INTEGER)), MAX(CAST(last_word_id AS INTEGER)) "
            "FROM pages WHERE page_number = 358 AND line_type = 'ayah'"
        ).fetchone()
    assert _word_bounds(payload) == expected


def test_qpc_v2_page_by_ayah_focuses_and_rejects_invalid_pages(client):
    response = client.get('/api/qpc-v2/page-by-ayah/2/255')
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['source'] == 'qpc_v2'
    assert payload['focus_surah'] == 2
    assert payload['focus_ayah'] == 255
    assert any(line['contains_focus_ayah'] for line in payload['lines'])
    assert client.get('/api/qpc-v2/page/605').status_code == 404


def test_memorize_page_lists_three_madinah_years(client):
    page = client.get('/memorize').get_data(as_text=True)
    assert '<option value="qpc_v1">المدينة ١٤٠٥</option>' in page
    assert '<option value="qpc_v2">المدينة ١٤٢١ — Digital Khatt (KFGQPC V2)</option>' in page
    assert '<option value="digital_khatt">المدينة ١٤٤١</option>' in page


def test_memorize_exposes_three_independent_waqf_choices(client):
    page = client.get('/memorize').get_data(as_text=True)
    script = client.get('/static/js/mushaf_memorize.js').get_data(as_text=True)
    css = client.get('/static/css/mushaf_memorize.css').get_data(as_text=True)

    # The selector must be in the visible source panel, not the hidden legacy
    # compatibility container where it previously existed.
    assert page.index('id="mz-waqf-pills"') < page.index('class="mz-compat"')
    assert 'role="radiogroup"' in page
    assert "const WAQF_CHOICES = ['المدينة الجديد', 'المدينة القديم', 'الشمرلي']" in script
    assert "return state.mushafVersions.slice(0, 1)" in script
    assert "p.classList.toggle('mz-src-shamarly', state.src === 'shamarly')" in script
    assert "if (state.src === 'shamarly') return raw;" in script
    assert "const overlay = entries.filter(entry => entry && entry.version === selectedWaqf)" in script
    assert "selectedMark ? integratedWaqfGlyph(selectedMark) : ''" in script
    assert '.mz-page.mz-src-shamarly .waqf-stack {' in css
    assert '.waqf-symbol[data-version="الشمرلي"] { color: var(--mz-quran); }' in css


def test_all_three_waqf_editions_are_available_on_madinah_and_shamarly_layouts(client):
    versions = ('المدينة الجديد', 'المدينة القديم', 'الشمرلي')
    for source in ('qpc-v2', 'shamarly'):
        for version in versions:
            response = client.get(
                f'/api/{source}/page-by-ayah/2/2?mushaf_version={quote(version)}'
            )
            assert response.status_code == 200
            entries = [
                entry
                for line in response.get_json()['lines']
                for word in line['words']
                for entry in (word['waqf_symbols'] if isinstance(word['waqf_symbols'], list) else [])
            ]
            assert entries
            assert {entry['version'] for entry in entries} == {version}


def test_madinah_yasin_closing_ayah_survives_phantom_last_word_id(client):
    """Madinah layouts end يس with last_word_id 61191 (no map token).

    That phantom used to make the whole closing line expand to zero words,
    dropping 36:83 (فسبحان الذي بيده ملكوت كل شيء وإليه ترجعون).
    """
    from modules.layouts import _get_dk_layout_word_map, _word_ids_in_map_span

    word_map = _get_dk_layout_word_map()
    assert 61191 not in word_map['id2tok']
    span = _word_ids_in_map_span(word_map, 61183, 61191)
    assert span == list(range(61183, 61191))
    assert word_map['id2tok'][span[-1]]['ayah'] == 83

    for path in (
        '/api/digital-khatt/page/445',
        '/api/qpc-v2/page/445',
        '/api/qpc-v1/page/445',
    ):
        payload = client.get(path).get_json()
        assert payload['page_number'] == 445
        y83 = [
            word
            for line in payload['lines']
            for word in line['words']
            if word.get('surah') == 36 and word.get('ayah') == 83
        ]
        assert len(y83) >= 8, path
        joined = ' '.join(word['text'] for word in y83)
        assert 'تُرْجَعُونَ' in joined, path


def test_madinah_saffat_closing_ayah_keeps_verse_number(client):
    """الصافات 182 marker overflows the layout surah span by one id.

    Digital Khatt has ۝١٨٢ but the Madinah layout caps the surah at the last
    content word, so the marker must be appended synthetically.
    """
    from modules import layouts as layouts_mod
    from modules.layouts import _get_dk_layout_word_map, _synthetic_ayah_marker_id

    layouts_mod._DK_LAYOUT_WORD_MAP = None
    layouts_mod._QPC_HAFS_LAYOUT_WORD_MAP = None
    word_map = _get_dk_layout_word_map()
    marker_id = _synthetic_ayah_marker_id(37, 182)
    assert word_map['id2tok'][marker_id]['text'] == '۝١٨٢'
    assert marker_id in word_map['append_after_id'][62233]

    for path in (
        '/api/digital-khatt/page/452',
        '/api/qpc-v2/page/452',
        '/api/qpc-v1/page/452',
    ):
        payload = client.get(path).get_json()
        assert payload['page_number'] == 452
        y182 = [
            word
            for line in payload['lines']
            for word in line['words']
            if word.get('surah') == 37 and word.get('ayah') == 182
        ]
        joined = ' '.join(word['text'] for word in y182)
        assert 'ٱلْعَٰلَمِينَ' in joined, path
        assert '۝١٨٢' in joined, path
