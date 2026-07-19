"""Azhar layout workspace — seeded from الشمرلي, Amiri render, editor writes."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


@pytest.fixture
def restore_azhar_layout_db():
    """Mutating tests must restore the seeded Shemrly geometry afterward."""
    yield
    from pipeline.seed_azhar_layout_db import seed
    seed(force=True)


def test_azhar_layout_page_and_api(client):
    page = client.get('/azhar-layout').get_data(as_text=True)
    assert 'id="az-title"' in page
    assert 'azhar_layout.css' in page
    assert 'azhar_layout.js' in page
    assert 'az-cancel' in page
    assert 'اسحب كلمة' in page

    r = client.get('/api/azhar/page/2')
    assert r.status_code == 200
    data = r.get_json()
    assert data['source'] == 'azhar'
    assert data['font_name'] == 'Amiri Quran'
    assert data['lines']
    # الفاتحة — Shemrly seed (surah + basmala + ayah lines), all words on page 2
    assert data['lines'][0]['line_type'] == 'surah_name'
    assert data['lines'][1]['line_type'] == 'basmallah'
    ayah_lines = [ln for ln in data['lines'] if ln['line_type'] == 'ayah']
    assert len(ayah_lines) >= 1
    assert ayah_lines[-1]['last_word_id'] == 38
    assert any(line.get('words') for line in data['lines'])

    by_ayah = client.get('/api/azhar/page-by-ayah/1/1')
    assert by_ayah.status_code == 200
    assert by_ayah.get_json()['page_number'] == 2


def test_azhar_line_break_and_progress(client, restore_azhar_layout_db):
    page = client.get('/api/azhar-layout/page/2').get_json()
    ayah_line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words') and len(line['words']) > 2
    )
    mid = ayah_line['words'][len(ayah_line['words']) // 2]
    before_last = ayah_line['last_word_id']
    r = client.post('/api/azhar-layout/line-break', json={
        'page_number': 2,
        'line_number': ayah_line['line_number'],
        'word_id': mid['word_index'],
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert body.get('undo_available', 0) >= 1
    updated = body['page']
    updated_line = next(
        line for line in updated['lines']
        if line['line_number'] == ayah_line['line_number']
    )
    assert updated_line['last_word_id'] == mid['word_index']
    # Closed Fatiha page — every ayah word through 38 stays on page 2
    fatiha = client.get('/api/azhar-layout/page/2').get_json()
    ayah_words = [
        w['word_index']
        for ln in fatiha['lines'] if ln['line_type'] == 'ayah'
        for w in (ln.get('words') or [])
    ]
    assert ayah_words[0] == 8
    assert ayah_words[-1] == 38
    assert max(ayah_words) == 38
    # البقرة must not absorb الفاتحة
    page3 = client.get('/api/azhar-layout/page/3').get_json()
    first_ayah = next(ln for ln in page3['lines'] if ln['line_type'] == 'ayah')
    assert first_ayah['first_word_id'] == 45

    undone = client.post('/api/azhar-layout/undo', json={'page_number': 2})
    assert undone.status_code == 200
    restored = next(
        line for line in undone.get_json()['page']['lines']
        if line['line_number'] == ayah_line['line_number']
    )
    assert restored['last_word_id'] == before_last

    prog = client.post('/api/azhar-layout/progress', json={'page_number': 2, 'reviewed': True})
    assert prog.status_code == 200
    listed = client.get('/api/azhar-layout/progress').get_json()
    assert 2 in listed['reviewed_pages']


def test_seed_script_exists():
    script = PROJECT_ROOT / 'pipeline' / 'seed_azhar_layout_db.py'
    assert script.is_file()
    db = PROJECT_ROOT / 'data' / 'mushaf-azhar-layout.db'
    assert db.is_file()
