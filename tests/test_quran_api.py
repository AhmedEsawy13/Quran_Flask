"""core_bp (modules/quran_api.py): surah/ayah data, waqf-symbol enrichment,
audio-URL security allowlists, and search. This is the foundational layer
every other module builds on — get_ayah_text alone pulls in word meanings
and waqf symbols via two separate subsystems, so a regression here is
invisible to any single-module test. Reciter audio moved to
core/memorization.py's per-surah system — see test_memorize_api.py.
"""
import urllib.parse as _u


def _q(s):
    return _u.quote(s)


def test_get_surahs_returns_all_114(client):
    j = client.get('/api/surahs').get_json()
    assert len(j) == 114
    assert j[0]['number'] == 1 and j[0]['name'] == 'الفاتحة'
    assert j[-1]['number'] == 114


def test_get_ayahs_matches_known_surah_lengths(client):
    assert client.get('/api/surahs/1/ayahs').get_json() == [1, 2, 3, 4, 5, 6, 7]
    assert len(client.get('/api/surahs/2/ayahs').get_json()) == 286
    assert client.get('/api/surahs/115/ayahs').status_code == 400
    assert client.get('/api/surahs/0/ayahs').status_code == 400


def test_get_ayah_text_shape_and_content(client):
    """1:1 pulls together text, word meanings (ordered + dict), transliteration,
    and waqf symbols in one payload — verify all four are present and mutually
    consistent, not just that the route returns 200. Reciter audio is served
    separately by /api/memorization (see test_memorize_api.py), not carried here."""
    j = client.get('/api/surahs/1/ayahs/1').get_json()
    assert j['verse_key'] == '1:1'
    assert j['surah_number'] == 1 and j['ayah_number'] == 1
    assert 'بِسۡمِ' in j['text']
    assert j['transliteration'].get('t', '').lower().startswith('bismi')
    # word_meanings_ordered and word_meanings must agree (dict is built FROM the list).
    assert j['word_meanings'] == {r['word']: r['meaning'] for r in j['word_meanings_ordered']}
    assert len(j['word_meanings_ordered']) >= 3


def test_get_ayah_text_bounds_and_missing(client):
    assert client.get('/api/surahs/0/ayahs/1').status_code == 400
    assert client.get('/api/surahs/115/ayahs/1').status_code == 400
    assert client.get('/api/surahs/1/ayahs/0').status_code == 400
    # a wildly out-of-range ayah within the valid MAX_AYAH_NUMBER ceiling but
    # past surah 1's actual 7 ayahs → verse simply doesn't exist.
    assert client.get('/api/surahs/1/ayahs/50').status_code == 404


def test_ayah_text_waqf_symbols_align_with_known_ayat_al_kursi_marks(client):
    """2:255 (آية الكرسي) has well-documented المدينة الجديد marks — cross-checked
    against the classical-waqf alignment work: الأرض (token 18) carries ق,
    and the second الأرض (token 43, «السماوات والأرض») carries ص."""
    url = '/api/surahs/2/ayahs/255/waqf?mushaf_version=' + _q('المدينة الجديد')
    j = client.get(url).get_json()
    by_token = {s['token_index']: s['symbols'] for s in j['waqf_symbols']}
    assert by_token.get(18) == 'ق'   # وما في الأرض
    assert by_token.get(43) == 'ص'   # السماوات والأرض
    assert by_token.get(6) == 'ج'    # القيوم


def test_shamarly_api_only_advertises_bundled_page_fonts(client):
    with_font = client.get('/api/shamarly/ayah/1/1').get_json()
    assert with_font['pages'] == [2]
    assert with_font['font_pages'] == [2]
    assert with_font['font_name'] == 'Shemrly-Page002'

    without_font = client.get('/api/shamarly/ayah/2/255').get_json()
    assert without_font['pages'] == [36]
    assert without_font['font_pages'] == []
    assert without_font['font_name'] is None
    assert not any(word.get('glyph_page') for word in without_font['words'])


def test_ayah_waqf_symbols_route_bounds(client):
    assert client.get('/api/surahs/115/ayahs/1/waqf').status_code == 400
    assert client.get('/api/surahs/1/ayahs/0/waqf').status_code == 400
    j = client.get('/api/surahs/1/ayahs/1/waqf').get_json()
    assert j['surah_number'] == 1 and j['ayah_number'] == 1
    assert 'waqf_symbols' in j


def test_health_check_reports_all_datasets_loaded(client):
    r = client.get('/api/health')
    j = r.get_json()
    assert r.status_code == 200
    assert j['status'] == 'healthy'
    assert all(j['checks'].values()), j['checks']


def test_quran_text_and_transliteration_are_nonempty_dicts(client):
    qt = client.get('/api/quran-text').get_json()
    assert isinstance(qt, dict) and '1:1' in qt
    tl = client.get('/api/transliteration').get_json()
    assert isinstance(tl, dict) and '1:1' in tl


def test_search_verses_finds_known_text(client):
    j = client.get('/api/search?q=' + _q('بسم') + '&limit=10').get_json()
    assert j['total_results'] > 0
    assert '1:1' in {r['verse_key'] for r in j['results']}
    # unvocalised query still matches fully-vocalised text (normalised search).
    assert all(r['highlight'] for r in j['results'])


def test_search_restores_letters_encoded_as_uthmani_dagger_alif(client):
    """A normal-keyboard alif must match its Uthmani dagger-alif spelling."""
    j = client.get('/api/search?q=' + _q('الصدقات') + '&limit=10').get_json()
    keys = {r['verse_key'] for r in j['results']}
    assert {'9:58', '9:60'} <= keys


def test_search_verses_validates_input(client):
    assert client.get('/api/search').status_code == 400            # missing q
    assert client.get('/api/search?q=' + 'x' * 501).status_code == 400  # too long
    # limit is clamped, not rejected.
    j = client.get('/api/search?q=' + _q('الله') + '&limit=0').get_json()
    assert len(j['results']) <= 50


def test_word_search_finds_known_word(client):
    j = client.get('/api/word-search?q=' + _q('الله') + '&limit=5').get_json()
    assert j['total_results'] > 0
    assert all('الله' in r['word'] or 'الله' in r['meaning'] for r in j['results'])
    assert client.get('/api/word-search').status_code == 400


def test_word_meanings_have_valid_references_for_all_surahs(client):
    # These three surahs previously had NULL surah_number values in word_name.db.
    for surah, ayah in ((34, 2), (47, 1), (78, 1)):
        j = client.get(f'/api/surahs/{surah}/ayahs/{ayah}').get_json()
        assert j['word_meanings_ordered'], (surah, ayah)


def test_audio_proxy_rejects_everything_but_the_allowlist(client):
    """SSRF/open-redirect guard: only https + a fixed domain allowlist +
    default port + no embedded credentials may be redirected to."""
    good = 'https://audio.qurancdn.com/AbdulBaset/Mujawwad/mp3/001001.mp3'
    assert client.get('/api/audio-proxy?url=' + _q(good)).status_code == 307

    assert client.get('/api/audio-proxy').status_code == 400  # missing url
    # wrong scheme
    bad = 'http://audio.qurancdn.com/x.mp3'
    assert client.get('/api/audio-proxy?url=' + _q(bad)).status_code == 400
    # domain not on the allowlist (classic SSRF probe)
    bad = 'https://evil.example.com/x.mp3'
    assert client.get('/api/audio-proxy?url=' + _q(bad)).status_code == 400
    # non-default port
    bad = 'https://audio.qurancdn.com:8443/x.mp3'
    assert client.get('/api/audio-proxy?url=' + _q(bad)).status_code == 400
    # credentials embedded in the URL
    bad = 'https://user:pass@audio.qurancdn.com/x.mp3'
    assert client.get('/api/audio-proxy?url=' + _q(bad)).status_code == 400


def test_yt_audio_rejects_urls_outside_the_reciter_catalog(client):
    """Only YouTube URLs already present in an installed reciter's catalog may
    be resolved — arbitrary YouTube (or non-YouTube) URLs must be rejected
    without ever invoking yt-dlp."""
    assert client.get('/api/yt-audio').status_code == 400  # missing url
    r = client.get('/api/yt-audio?url=' + _q('https://www.youtube.com/watch?v=dQw4w9WgXcQ'))
    assert r.status_code in (403, 503)  # 403 = not in catalog, 503 = yt-dlp not installed
    r = client.get('/api/yt-audio?url=' + _q('https://evil.example.com/watch?v=x'))
    assert r.status_code in (403, 503)
