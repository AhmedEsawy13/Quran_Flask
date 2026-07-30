"""reading_bp (modules/reading.py): tajweed-annotated text, tafseer/eerab
in-process caching, and word-meaning ordering. المتشابهات is covered
separately in test_mutashabihat.py.

Tafseer is served from local data (data/tafseer_local.db) and exercised for
real. Eerab still hits an external API (SurahApp) — this suite deliberately
does not make live network calls for it, instead pre-populating the module's
own LRU cache and verifying the route serves the cached entry verbatim.
"""
import modules.reading as reading
from core.text import _normalize_for_search


def test_tajweed_known_verse_and_caching_header(client):
    j = client.get('/api/tajweed/1/1').get_json()
    assert '<tajweed class="ham_wasl">' in j['html']
    assert 'بِسْمِ' in j['html']
    r = client.get('/api/tajweed/1/1')
    assert 'public' in r.headers.get('Cache-Control', '')


def test_tajweed_bounds_and_missing(client):
    assert client.get('/api/tajweed/115/1').status_code == 400
    assert client.get('/api/tajweed/1/0').status_code == 400


def test_tajweed_notes_bounds(client):
    assert client.get('/api/tajweed-notes/115/1').status_code == 400
    assert client.get('/api/tajweed-notes/1/0').status_code == 400


def test_tajweed_notes_serves_local_companion_text(client, tmp_path, monkeypatch):
    """Coloring stays in tajweed_local.db; notes are a separate companion DB."""
    db = tmp_path / 'tajweed_notes_local.db'
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE tajweed_notes '
        '(verse_key TEXT PRIMARY KEY, text TEXT NOT NULL, '
        'attribution TEXT NOT NULL, source TEXT NOT NULL)'
    )
    conn.execute(
        'INSERT INTO tajweed_notes VALUES (?,?,?,?)',
        ('1:1', 'لام الجلالة مرققة — اختبار.', 'نسبة اختبار', 'test'),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reading, 'TAJWEED_NOTES_DATABASE', str(db))
    # Drop any prior cached miss/hit for 1:1 from other tests.
    for key in list(reading._tajweed_notes_cache.keys()):
        del reading._tajweed_notes_cache[key]

    r = client.get('/api/tajweed-notes/1/1')
    assert r.status_code == 200
    j = r.get_json()
    assert j['verse_key'] == '1:1'
    assert 'مرققة' in j['text']
    assert j['attribution'] == 'نسبة اختبار'
    assert 'public' in r.headers.get('Cache-Control', '')

    assert client.get('/api/tajweed-notes/1/2').status_code == 404


def test_asbab_bounds_and_empty(client, tmp_path, monkeypatch):
    assert client.get('/api/asbab/115/1').status_code == 400
    assert client.get('/api/asbab/1/0').status_code == 400

    db = tmp_path / 'asbab_local.db'
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE asbab ('
        'verse_key TEXT NOT NULL, source TEXT NOT NULL, '
        'text TEXT NOT NULL, attribution TEXT NOT NULL, '
        'PRIMARY KEY (verse_key, source))'
    )
    conn.execute(
        'INSERT INTO asbab VALUES (?,?,?,?)',
        ('2:6', 'wahidi_asbab', 'نزلت في أبي جهل — اختبار.', 'الواحدي'),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reading, 'ASBAB_DATABASE', str(db))
    for key in list(reading._asbab_cache.keys()):
        del reading._asbab_cache[key]

    r = client.get('/api/asbab/2/6')
    assert r.status_code == 200
    j = r.get_json()
    assert j['available'] is True
    assert j['entries'][0]['text'].startswith('نزلت')
    assert client.get('/api/asbab/1/1').status_code == 404


def test_word_meanings_ordered_matches_db_order(app):
    """1:1 has three word-meaning entries; get_word_meanings_ordered must
    preserve the DB's own id ASC order, which get_ayah_text's dict form
    (word -> meaning) then can't distinguish — this is the one place order
    is actually verified."""
    with app.test_request_context():
        ordered = reading.get_word_meanings_ordered(1, 1)
    assert len(ordered) == 3
    # first entry is the بسم الله compound, folded to skeleton to sidestep
    # exact-diacritic transcription (sukun-glyph variants etc.).
    assert _normalize_for_search(ordered[0]['word']) == _normalize_for_search('بسم الله')
    assert all(o['word'] and o['meaning'] for o in ordered)


def test_get_waqf_symbols_indopak_embedded_marks_labelled_hindi(app):
    """IndoPak sources carry their own embedded الهندي waqf marks distinct
    from the mushaf_version overlay system — verify the label and that a
    non-IndoPak source returns nothing from this path."""
    with app.test_request_context('/?'):
        hindi = reading.get_waqf_symbols(1, 1, 'indopak_nastaleeq')
        assert all(s['version'] == 'الهندي' for s in hindi)
        assert reading.get_waqf_symbols(1, 1, 'qpc_hafs') == []


def test_tafseer_returns_all_five_local_tafsirs(client):
    j = client.get('/api/tafseer/1/1').get_json()
    assert set(j) == set(reading.TAFSEER_NAMES)
    for name in reading.TAFSEER_NAMES:
        assert j[name]['text'], name


def test_tafseer_resolves_grouped_verse_to_its_representative_text(client):
    """Baghawi covers all of al-Fatiha (1:1-1:7) under a single heading — a
    member ayah like 1:2 must resolve to the same stored text as 1:1's own
    row, proving the verse->group->text lookup actually joins correctly."""
    j1 = client.get('/api/tafseer/1/1').get_json()
    j2 = client.get('/api/tafseer/1/2').get_json()
    assert j1['تفسير البغوي']['text']
    assert j1['تفسير البغوي']['text'] == j2['تفسير البغوي']['text']


def test_tafseer_bounds(client):
    assert client.get('/api/tafseer/115/1').status_code == 400
    assert client.get('/api/tafseer/1/0').status_code == 400


def test_eerab_serves_from_cache_without_network(client):
    reading._eerab_cache[(113, 1)] = {'content': 'cached-eerab'}
    j = client.get('/api/eerab/113/1').get_json()
    assert j['content'] == 'cached-eerab'


def test_eerab_bounds(client):
    assert client.get('/api/eerab/115/1').status_code == 400
    assert client.get('/api/eerab/1/0').status_code == 400


def test_index_page_renders(client):
    assert client.get('/').status_code == 200


def test_read_page_renders(client):
    assert client.get('/read').status_code == 200
