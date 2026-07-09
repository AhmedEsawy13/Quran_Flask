"""reading_bp (modules/reading.py): tajweed-annotated text, tafseer/eerab
in-process caching, and word-meaning ordering. المتشابهات is covered
separately in test_mutashabihat.py.

Tafseer and eerab hit external APIs (quran.com, quranenc.com, SurahApp) —
this suite deliberately does not make live network calls. Instead it
pre-populates the module's own LRU caches and verifies the route serves the
cached entry verbatim, which exercises the real caching/lookup logic without
depending on a third party being up.
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


def test_tafseer_serves_from_cache_without_network(client):
    """Pre-populate the in-process cache directly, then confirm the route
    returns exactly that payload — proves the cache-hit path works without
    ever making an HTTP request."""
    verse_key = '114:1'  # an obscure verse unlikely to collide with other tests
    for name in list(reading.TAFSEER_API_IDS) + list(reading.TAFSEER_QURANENC_IDS):
        reading._tafseer_cache[(name, verse_key)] = {'text': f'cached-{name}'}
    j = client.get('/api/tafseer/114/1').get_json()
    for name in reading.TAFSEER_API_IDS:
        assert j[name]['text'] == f'cached-{name}'


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
