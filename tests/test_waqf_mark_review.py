"""Smoke tests for the Plan A waqf-mark-review checklist (الشمرلي first)."""
from __future__ import annotations

from modules.waqf_mark_review import waqf_glyph


def test_waqf_glyph_maps_letter_codes_to_printed_marks():
    assert waqf_glyph('ص') == 'ۖ'
    assert waqf_glyph('ق') == 'ۗ'
    assert waqf_glyph('م') == 'ۘ'
    assert waqf_glyph('ج') == 'ۚ'
    assert waqf_glyph('لا') == 'ۙ'
    assert waqf_glyph('ع') == 'ۛ'


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
