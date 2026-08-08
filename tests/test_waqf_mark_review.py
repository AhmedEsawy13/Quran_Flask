"""Smoke tests for the Plan A waqf-mark-review checklist (الشمرلي first)."""
from __future__ import annotations

import sqlite3

from modules.waqf_mark_review import (
    PRINT_PACKS,
    PRINT_ROWS_PER_COLUMN,
    _build_print_pack,
    pack_page_range,
    waqf_glyph,
    waqf_write_form,
)


def test_waqf_glyph_maps_letter_codes_to_printed_marks():
    assert waqf_glyph('ص') == 'ۖ'
    assert waqf_glyph('ق') == 'ۗ'
    assert waqf_glyph('م') == 'ۘ'
    assert waqf_glyph('ج') == 'ۚ'
    assert waqf_glyph('لا') == 'ۙ'
    assert waqf_glyph('ع') == 'ۛ'


def test_waqf_write_form_uses_paper_labels():
    assert waqf_write_form('ص') == 'صلى'
    assert waqf_write_form('ق') == 'قلى'
    assert waqf_write_form('ج') == 'ج'
    assert waqf_write_form('لا') == 'لا'
    assert waqf_write_form('م') == 'م'


def test_pack_page_ranges_cover_ten_juz_batches():
    assert pack_page_range(1, 10) == (2, 200)
    assert pack_page_range(11, 20) == (201, 401)
    assert pack_page_range(21, 30) == (402, 522)
    assert set(PRINT_PACKS) == {1, 2, 3}


def test_waqf_mark_review_page_renders_shemrly(client):
    page = client.get('/waqf-mark-review')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'id="wmr-list"' in body
    assert 'الشمرلي' in body
    assert 'uthmanic_hafs' in body
    assert 'js/athar-mushaf.js' in body
    assert 'id="wmr-login"' in body
    assert 'js/waqf_mark_review.js' in body
    assert '/waqf-mark-review/print?pack=1' in body
    assert '/waqf-mark-review/print?pack=2' in body
    assert '/waqf-mark-review/print?pack=3' in body


def test_azhar_surah_review_page_and_table(client):
    page = client.get('/azhar-waqf-review')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'علامات الوقف — سورةً سورةً' in body
    assert 'azhar_waqf_review.js' in body
    assert 'azhar_waqf_review.css' in body

    response = client.get('/api/azhar-waqf-review/surah/2')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['edition'] == 'الأزهر'
    assert payload['surah_name'] == 'البقرة'
    assert payload['ayah_count'] == 286
    assert len(payload['rows']) == payload['ayah_count']
    row = next(item for item in payload['rows'] if item['ayah'] == 2)
    assert row['text']
    assert row['marks'][0]['word_index'] == 2
    assert row['marks'][0]['mark'] == 'ج'
    assert row['marks'][0]['glyph'] == 'ۚ'


def test_azhar_surah_review_rejects_invalid_surah(client):
    assert client.get('/api/azhar-waqf-review/surah/0').status_code == 400
    assert client.get('/api/azhar-waqf-review/surah/115').status_code == 400


def test_waqf_mark_review_print_pack1_renders(client):
    page = client.get('/waqf-mark-review/print?pack=1')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'الأجزاء ١–١٠' in body
    assert 'wmr-print-main' in body
    assert 'wmr-print-table' in body
    assert 'wmr-print-split' in body
    assert 'wmr-print-sheet' in body
    assert 'css/waqf_mark_review_print.css' in body
    assert 'الصفحة' in body
    assert 'السطر' in body
    assert 'الكلمة' in body
    assert 'علامة الوقف' in body
    assert 'الصحيح' not in body
    assert 'col-id' not in body


def test_waqf_mark_review_print_invalid_pack(client):
    page = client.get('/waqf-mark-review/print?pack=9')
    assert page.status_code == 400


def test_build_print_pack_matches_checklist_totals():
    from modules.waqf_mark_review import _build_shamarly_checklist

    pack = _build_print_pack(3)  # smallest pack — faster
    assert pack['pack_id'] == 3
    assert pack['page_from'] == 402
    assert pack['page_to'] == 522
    assert pack['mark_total'] == sum(p['item_count'] for p in pack['pages'])
    assert pack['mark_total'] >= 1
    assert len(pack['rows']) == pack['mark_total']
    assert sum(len(c) for c in pack['columns']) == pack['mark_total']
    assert all(
        len(column) <= PRINT_ROWS_PER_COLUMN
        for sheet in pack['print_sheets']
        for column in sheet['columns']
    )
    sheet_rows = [
        item
        for sheet in pack['print_sheets']
        for column in sheet['columns']
        for item in column
    ]
    assert [item['word_id'] for item in sheet_rows] == [
        item['word_id'] for item in pack['rows']
    ]
    # Spot-check one page against the live checklist builder.
    sample = pack['pages'][0]
    live = _build_shamarly_checklist(sample['page_number'])
    assert sample['item_count'] == live['item_count']
    assert [i['word_id'] for i in sample['marks']] == [i['word_id'] for i in live['items']]
    assert all(i.get('line_label') and i.get('ayah_ref') for i in sample['marks'])
    assert sample['marks'][0]['is_page_start'] is True
    assert sample['marks'][0]['mark_write']
    if len(sample['marks']) > 1:
        assert sample['marks'][1]['is_page_start'] is False


def test_waqf_mark_review_shemrly_page_returns_glyphs(client):
    response = client.get('/api/waqf-mark-review/page/4?edition=%D8%A7%D9%84%D8%B4%D9%85%D8%B1%D9%84%D9%8A')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['edition'] == 'الشمرلي'
    assert payload['page_number'] == 4
    assert payload['item_count'] >= 1
    row = payload['items'][0]
    assert {'word_id', 'surah', 'ayah', 'text', 'mark', 'mark_glyph'} <= set(row)
    assert row['mark']
    assert row['mark_glyph']
    assert any(item['mark_glyph'] in 'ۘۗۖۚۙۛۜ' for item in payload['items'])
    # Letter codes must not be shown as the primary glyph for common marks.
    assert all(
        item['mark_glyph'] != item['mark'] or item['mark'] in 'ۘۗۖۚۙۛۜ'
        for item in payload['items']
    )
    hearing = next(i for i in payload['items'] if i['ayah'] == 7 and i['mark'] == 'ص')
    assert hearing['mark_glyph'] == 'ۖ'
    assert hearing['text'].startswith('سَم')
    assert hearing.get('word_on_line')
    assert hearing.get('line')


def test_waqf_mark_review_decisions_persist_locally(client, tmp_path, monkeypatch):
    """Without Supabase, decisions land in mushaf_waqf.db (isolated temp file)."""
    import modules.waqf_mark_review as wmr
    from core import supabase_editor as sb

    db = tmp_path / 'mark-review-test.db'
    monkeypatch.setattr(wmr, 'MARK_REVIEW_STORE_DATABASE', str(db))
    monkeypatch.setattr(sb, 'is_configured', lambda: False)

    edition = 'الشمرلي'
    page = client.get('/api/waqf-mark-review/page/4?edition=' + edition)
    assert page.status_code == 200
    item = page.get_json()['items'][0]
    word_id = item['word_id']

    save = client.post('/api/waqf-mark-review/decisions', json={
        'edition': edition,
        'page_number': 4,
        'word_id': word_id,
        'decision': 'ok',
        'our_mark': item['mark'],
        'surah': item['surah'],
        'ayah': item['ayah'],
        'text': item['text'],
    })
    assert save.status_code == 200
    assert save.get_json()['storage'] == 'local'

    listed = client.get('/api/waqf-mark-review/decisions?edition=' + edition)
    assert listed.status_code == 200
    payload = listed.get_json()
    assert payload['storage'] == 'local'
    assert payload['decisions']['4'][str(word_id)]['decision'] == 'ok'

    note = client.post('/api/waqf-mark-review/notes', json={
        'edition': edition,
        'page_number': 4,
        'note': 'علامة ناقصة تجريبية',
    })
    assert note.status_code == 200
    listed2 = client.get('/api/waqf-mark-review/decisions?edition=' + edition)
    notes = listed2.get_json()['decisions']['_missing']['4']
    assert any(n['text'] == 'علامة ناقصة تجريبية' for n in notes)

    gone = client.delete('/api/waqf-mark-review/decisions', json={
        'edition': edition,
        'page_number': 4,
        'word_id': word_id,
    })
    assert gone.status_code == 200
    after = client.get('/api/waqf-mark-review/decisions?edition=' + edition)
    assert str(word_id) not in (after.get_json()['decisions'].get('4') or {})


def test_waqf_mark_review_gets_do_not_create_local_tables(client, tmp_path, monkeypatch):
    import modules.waqf_mark_review as wmr
    from core import supabase_editor as sb

    db = tmp_path / 'read-only-mark-review.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE existing_data (value TEXT)')
        conn.execute("INSERT INTO existing_data VALUES ('keep')")
    before = db.read_bytes()
    monkeypatch.setattr(wmr, 'MARK_REVIEW_STORE_DATABASE', str(db))
    monkeypatch.setattr(sb, 'is_configured', lambda: False)

    decisions = client.get('/api/waqf-mark-review/decisions?edition=الشمرلي')
    progress = client.get('/api/waqf-mark-review/progress?edition=الشمرلي')

    assert decisions.status_code == 200
    assert decisions.get_json()['decisions'] == {}
    assert progress.status_code == 200
    assert progress.get_json()['reviewed_pages'] == []
    assert db.read_bytes() == before


def test_waqf_mark_review_progress_local(client, tmp_path, monkeypatch):
    import modules.waqf_mark_review as wmr
    from core import supabase_editor as sb

    db = tmp_path / 'mark-review-progress.db'
    monkeypatch.setattr(wmr, 'MARK_REVIEW_STORE_DATABASE', str(db))
    monkeypatch.setattr(sb, 'is_configured', lambda: False)

    edition = 'الشمرلي'
    post = client.post('/api/waqf-mark-review/progress', json={
        'edition': edition,
        'page_number': 4,
        'reviewed': True,
    })
    assert post.status_code == 200
    assert post.get_json()['storage'] == 'local'
    get = client.get('/api/waqf-mark-review/progress?edition=' + edition)
    assert 4 in get.get_json()['reviewed_pages']
