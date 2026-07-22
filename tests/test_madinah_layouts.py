"""Regression coverage for the three Madinah layouts offered by تثبيت."""

import sqlite3

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
