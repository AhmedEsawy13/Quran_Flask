"""Azhar / Layout Studio — seeded from الشمرلي, Amiri render, editor writes."""
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


def test_layout_studio_registry_and_shell(client):
    editions = client.get('/api/layout-studio/editions').get_json()
    assert editions['default'] == 'azhar'
    assert any(e['id'] == 'azhar' for e in editions['editions'])

    bounced = client.get('/layout-studio')
    assert bounced.status_code in (301, 302)
    assert '/layout-studio/azhar' in bounced.headers.get('Location', '')

    page = client.get('/layout-studio/azhar').get_data(as_text=True)
    assert 'AtharLayoutStudio' in page
    assert 'استوديو التخطيط' in page
    assert 'مصحف الأزهر' in page
    assert 'id="az-undo"' in page
    assert '/api/layout-studio/azhar' in page

    unknown = client.get('/layout-studio/not-an-edition')
    assert unknown.status_code == 404

    api = client.get('/api/layout-studio/azhar/page/2')
    assert api.status_code == 200
    assert api.get_json()['source'] == 'azhar'


def test_azhar_layout_page_and_api(client):
    page = client.get('/azhar-layout').get_data(as_text=True)
    assert 'id="az-title"' in page
    assert 'استوديو التخطيط' in page
    assert 'azhar_layout.css' in page
    assert 'azhar_layout.js' in page
    assert 'az-cancel' in page
    assert 'id="az-undo"' in page
    assert 'az-reseed-note' in page
    assert 'AtharLayoutStudio' in page
    assert 'اسحب كلمة' in page
    assert 'id="az-compare"' in page
    assert 'id="az-ref-panel"' in page
    assert 'id="az-ref-img"' in page
    js = (PROJECT_ROOT / 'static/js/azhar_layout.js').read_text(encoding='utf-8')
    assert 'AtharLayoutStudio' in js
    assert 'apiBase' in js
    assert 'shamarlyshamarly' in js
    assert 'az-compare' in (PROJECT_ROOT / 'static/css/azhar_layout.css').read_text(encoding='utf-8')
    assert 'undoLast' in js

    r = client.get('/api/azhar/page/2')
    assert r.status_code == 200
    data = r.get_json()
    assert data['source'] == 'azhar'
    assert data['font_name'] == 'Amiri Quran'
    assert data['lines']
    assert data['lines'][0]['line_type'] == 'surah_name'
    assert data['lines'][1]['line_type'] == 'basmallah'
    assert data['lines_per_page'] == 6
    ayah_lines = [ln for ln in data['lines'] if ln['line_type'] == 'ayah']
    assert len(ayah_lines) == 4
    assert ayah_lines[-1]['last_word_id'] == 38
    assert any(line.get('words') for line in data['lines'])

    by_ayah = client.get('/api/azhar/page-by-ayah/1/1')
    assert by_ayah.status_code == 200
    assert by_ayah.get_json()['page_number'] == 2

    baqarah = client.get('/api/azhar/page/3').get_json()
    assert baqarah['lines_per_page'] == 5
    assert len(baqarah['lines']) == 5
    baq_ayah = [ln for ln in baqarah['lines'] if ln['line_type'] == 'ayah']
    assert len(baq_ayah) == 3
    assert baq_ayah[-1]['last_word_id'] == 76
    page4 = client.get('/api/azhar/page/4').get_json()
    first4 = next(ln for ln in page4['lines'] if ln['line_type'] == 'ayah')
    assert first4['first_word_id'] == 77


def test_azhar_line_break_and_progress(client, restore_azhar_layout_db):
    page = client.get('/api/layout-studio/azhar/page/2').get_json()
    ayah_line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words') and len(line['words']) > 2
    )
    mid = ayah_line['words'][len(ayah_line['words']) // 2]
    before_last = ayah_line['last_word_id']
    r = client.post('/api/layout-studio/azhar/line-break', json={
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
    fatiha = client.get('/api/azhar-layout/page/2').get_json()
    ayah_words = [
        w['word_index']
        for ln in fatiha['lines'] if ln['line_type'] == 'ayah'
        for w in (ln.get('words') or [])
    ]
    assert ayah_words[0] == 8
    assert ayah_words[-1] == 38
    assert max(ayah_words) == 38
    page3 = client.get('/api/azhar-layout/page/3').get_json()
    first_ayah = next(ln for ln in page3['lines'] if ln['line_type'] == 'ayah')
    assert first_ayah['first_word_id'] == 45

    undone = client.post('/api/layout-studio/azhar/undo', json={'page_number': 2})
    assert undone.status_code == 200
    restored = next(
        line for line in undone.get_json()['page']['lines']
        if line['line_number'] == ayah_line['line_number']
    )
    assert restored['last_word_id'] == before_last

    prog = client.post('/api/azhar-layout/progress', json={'page_number': 2, 'reviewed': True})
    assert prog.status_code == 200
    listed = client.get('/api/layout-studio/azhar/progress').get_json()
    assert 2 in listed['reviewed_pages']


def test_azhar_undo_is_page_scoped(client, restore_azhar_layout_db):
    """Fatiha edits snapshot only pages 2–3 (not the whole mushaf)."""
    import json
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE

    page = client.get('/api/layout-studio/azhar/page/2').get_json()
    ayah_line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words') and len(line['words']) > 2
    )
    mid = ayah_line['words'][len(ayah_line['words']) // 2]
    r = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 2,
        'line_number': ayah_line['line_number'],
        'word_id': mid['word_index'],
    })
    assert r.status_code == 200

    conn = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        row = conn.execute(
            'SELECT snapshot FROM azhar_layout_undo ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert isinstance(payload, dict)
        assert payload['page_from'] == 2
        assert payload['page_to'] == 3
        pages = {int(r['page_number']) for r in payload['rows']}
        assert pages <= {2, 3}
        assert 2 in pages
        assert len(payload['rows']) < 80
    finally:
        conn.close()

    status = client.get('/api/layout-studio/azhar/undo-status?page_number=2').get_json()
    assert status['undo_available'] >= 1
    other = client.get('/api/layout-studio/azhar/undo-status?page_number=10').get_json()
    assert other['undo_available'] == 0


def test_line_break_does_not_spill_into_next_surah(client, restore_azhar_layout_db):
    """Page 64: Al-Imran ends mid-page; a break must not push words onto An-Nisa."""
    page = client.get('/api/layout-studio/azhar/page/64').get_json()
    line3 = next(
        ln for ln in page['lines']
        if ln['line_number'] == 3 and ln['line_type'] == 'ayah'
    )
    assert len(line3['words']) > 2
    mid = line3['words'][1]

    def imran_ayah_ids(payload):
        ids = []
        for ln in payload['lines']:
            if ln['line_type'] in ('surah_name', 'surah_info', 'basmallah'):
                break
            if ln['line_type'] == 'ayah':
                ids.extend(w['word_index'] for w in (ln.get('words') or []))
        return ids

    before_ids = imran_ayah_ids(page)

    nisa_line = next(
        ln for ln in page['lines']
        if ln['line_type'] == 'ayah' and ln.get('surah_number') == 4
    )
    assert nisa_line['first_word_id'] == 10169
    nisa_line_no = nisa_line['line_number']

    r = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 64,
        'line_number': 3,
        'word_id': mid['word_index'],
        'role': 'end',
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['ok'] is True

    after = client.get('/api/layout-studio/azhar/page/64').get_json()
    updated_l3 = next(ln for ln in after['lines'] if ln['line_number'] == 3)
    assert updated_l3['last_word_id'] == mid['word_index']

    assert imran_ayah_ids(after) == before_ids  # same words, redistributed — none deleted

    nisa_after = next(ln for ln in after['lines'] if ln['line_number'] == nisa_line_no)
    assert nisa_after['first_word_id'] == 10169
    nisa_words = [w['word_index'] for w in (nisa_after.get('words') or [])]
    assert all(w >= 10169 for w in nisa_words)
    assert not any(w <= 10162 for w in nisa_words)

    # Last ayah of Al-Imran before the banner: shortening would drop words — reject.
    last_imran = None
    for ln in after['lines']:
        if ln['line_type'] in ('surah_name', 'surah_info', 'basmallah'):
            break
        if ln['line_type'] == 'ayah':
            last_imran = ln
    assert last_imran and len(last_imran['words']) > 2
    bad = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 64,
        'line_number': last_imran['line_number'],
        'word_id': last_imran['words'][1]['word_index'],
        'role': 'end',
    })
    assert bad.status_code == 400
    assert 'سور' in (bad.get_json().get('error') or '')

    # Merge across the surah header must be rejected.
    bad_merge = client.post('/api/layout-studio/azhar/merge-line', json={
        'page_number': 64,
        'line_number': last_imran['line_number'],
    })
    assert bad_merge.status_code == 400
    assert 'سور' in (bad_merge.get_json().get('error') or '')


def test_azhar_short_page_geometry(client):
    editions = client.get('/api/layout-studio/editions').get_json()
    azhar = next(e for e in editions['editions'] if e['id'] == 'azhar')
    assert azhar['short_pages'] == {'2': 6, '3': 5}

    p2 = client.get('/api/layout-studio/azhar/page/2').get_json()
    assert len(p2['lines']) == 6
    assert p2['lines_per_page'] == 6
    p3 = client.get('/api/layout-studio/azhar/page/3').get_json()
    assert len(p3['lines']) == 5
    assert p3['lines_per_page'] == 5


def test_azhar_surah_header_takes_three_lines(client):
    """Every page is 15 lines; a leading banner uses 3 of them (12 ayah left).

    Page 495 (الانسان): name + info + basmala + 12 ayah.
    Page 496 (continuation): still 15 ayah lines — never left short after spill.
    """
    p494 = client.get('/api/layout-studio/azhar/page/494').get_json()
    assert p494['lines']
    assert p494['lines'][-1]['line_type'] != 'surah_name'
    assert len(p494['lines']) == 15

    p495 = client.get('/api/layout-studio/azhar/page/495').get_json()
    types = [ln['line_type'] for ln in p495['lines']]
    assert types[:3] == ['surah_name', 'surah_info', 'basmallah']
    assert len(p495['lines']) == 15
    assert p495['lines_per_page'] == 15
    ayah = [ln for ln in p495['lines'] if ln['line_type'] == 'ayah']
    assert len(ayah) == 12
    assert (p495['lines'][0].get('display_text') or '').startswith('سورة')
    info = p495['lines'][1].get('display_text') or ''
    assert 'آياتها' in info
    assert info.startswith('مكية') or info.startswith('مدنية')

    p496 = client.get('/api/layout-studio/azhar/page/496').get_json()
    assert len(p496['lines']) == 15
    assert p496['lines_per_page'] == 15
    assert all(ln['line_type'] == 'ayah' for ln in p496['lines'])

    # Mid-page banner (e.g. النبأ on 498): name+info+basmala still inside 15,
    # with overflow ayah spilled onto the next page.
    p498 = client.get('/api/layout-studio/azhar/page/498').get_json()
    assert len(p498['lines']) == 15
    types498 = [ln['line_type'] for ln in p498['lines']]
    assert 'surah_name' in types498
    assert 'surah_info' in types498
    assert 'basmallah' in types498
    assert types498.count('ayah') == 12
    name_i = types498.index('surah_name')
    assert types498[name_i:name_i + 3] == ['surah_name', 'surah_info', 'basmallah']

    p499 = client.get('/api/layout-studio/azhar/page/499').get_json()
    assert len(p499['lines']) == 15

    # Same-page starts (e.g. المزمل) also get the info line and stay at 15.
    p490 = client.get('/api/layout-studio/azhar/page/490').get_json()
    assert [ln['line_type'] for ln in p490['lines'][:3]] == [
        'surah_name', 'surah_info', 'basmallah',
    ]
    assert len([ln for ln in p490['lines'] if ln['line_type'] == 'ayah']) == 12
    assert len(p490['lines']) == 15


def test_layout_engine_surah_fence_unit():
    from modules.layout_engine import ayah_segment_slots, is_surah_separator

    lines = [
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 3},
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 4},
        {'line_type': 'surah_name', 'page_number': 64, 'line_number': 5},
        {'line_type': 'surah_info', 'page_number': 64, 'line_number': 6},
        {'line_type': 'basmallah', 'page_number': 64, 'line_number': 7},
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 8},
    ]
    assert is_surah_separator(lines[2])
    assert is_surah_separator(lines[3])
    assert ayah_segment_slots(lines, 0) == [0, 1]
    assert ayah_segment_slots(lines, 1) == [1]
    assert ayah_segment_slots(lines, 5) == [5]


def test_layout_engine_module_imports():
    from modules import layout_engine
    from modules import azhar_layout
    from modules import layout_editions
    from modules import layout_studio

    assert callable(layout_engine.cascade_from)
    assert callable(layout_engine.push_undo)
    assert callable(layout_engine.ayah_segment_slots)
    assert callable(azhar_layout._cascade_from)
    assert layout_editions.get_edition('azhar') is not None
    assert callable(layout_studio.render_studio)


def test_seed_script_warns_on_force():
    script = (PROJECT_ROOT / 'pipeline' / 'seed_azhar_layout_db.py').read_text(encoding='utf-8')
    assert 'DESTRUCTIVE WARNING' in script
    assert 'wipe' in script.lower() or 'WIPE' in script
    db = PROJECT_ROOT / 'data' / 'mushaf-azhar-layout.db'
    assert db.is_file()


def test_seed_script_exists():
    script = PROJECT_ROOT / 'pipeline' / 'seed_azhar_layout_db.py'
    assert script.is_file()
    db = PROJECT_ROOT / 'data' / 'mushaf-azhar-layout.db'
    assert db.is_file()
