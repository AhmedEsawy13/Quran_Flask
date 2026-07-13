"""Boot / feature-flag / robustness tests for the split app.

After carving app.py into core/ + modules/, guard that the app still assembles
under every deployment shape and that the newer endpoints refuse bad input
cleanly instead of 500-ing.
"""
import app as quran_app


def test_all_features_including_editor_boot(client):
    """Every module's landing endpoint resolves on the fully-mounted app."""
    for url in ('/', '/memorize', '/waqf', '/waqf-practice', '/mushaf-editor',
                '/api/surahs', '/api/surahs/2/ayahs/255', '/api/classical-waqf/2/2',
                '/api/waqf-practice/passage/2/1/3',
                '/api/mushaf-editor/spread/2?edition=%D9%82%D8%B7%D8%B1'):
        assert client.get(url).status_code == 200, url


def test_practice_page_links_specialist_recitation_tools(client):
    page = client.get('/waqf-practice').get_data(as_text=True)
    assert 'https://www.tarteel.ai/quran-feedback' in page
    assert 'https://quran.com/learn/tajweed' in page
    assert page.count('rel="noopener noreferrer"') >= 2


def test_enabled_features_env(monkeypatch):
    monkeypatch.setenv('FEATURES', 'reading,memorize')
    monkeypatch.delenv('ENABLE_EDITOR', raising=False)
    feats = quran_app.enabled_features()
    assert 'core' in feats and 'reading' in feats and 'memorize' in feats
    assert 'editor' not in feats                      # editor never mounts without ENABLE_EDITOR
    monkeypatch.setenv('ENABLE_EDITOR', '1')
    assert 'editor' in quran_app.enabled_features()


def test_practice_grade_edge_cases(client):
    # no stops → valid, full score, no crash.
    r = client.post('/api/waqf-practice/grade',
                    json={'surah': 1, 'from_ayah': 1, 'to_ayah': 7, 'stops': []}).get_json()
    assert r['score'] == 100 and r['summary']['errors'] == 0 and r['stops'] == []
    # stop wpos outside the verse is simply ignored (never indexes past the words).
    r = client.post('/api/waqf-practice/grade',
                    json={'surah': 1, 'from_ayah': 1, 'to_ayah': 1,
                          'stops': [{'ayah': 1, 'wpos': 999}]}).get_json()
    assert r['stops'] == []
    # garbage stop entries are dropped, not fatal.
    r = client.post('/api/waqf-practice/grade',
                    json={'surah': 2, 'from_ayah': 1, 'to_ayah': 2,
                          'stops': [{'ayah': 'x'}, {}, {'ayah': 2, 'wpos': 6}]}).get_json()
    assert len(r['stops']) == 1
    # unknown mushaf falls back to the default rather than erroring.
    r = client.post('/api/waqf-practice/grade',
                    json={'surah': 2, 'from_ayah': 2, 'to_ayah': 2, 'mushaf': 'DROP TABLE',
                          'stops': [{'ayah': 2, 'wpos': 6}]}).get_json()
    assert r['mushaf'] == 'المدينة الجديد'
    # malformed body / bad range → 400, not 500.
    assert client.post('/api/waqf-practice/grade', json={}).status_code == 400
    assert client.post('/api/waqf-practice/grade',
                       json={'surah': 2, 'from_ayah': 3, 'to_ayah': 1}).status_code == 400


def test_error_responses_stay_uncached_across_modules(client):
    r = client.get('/api/waqf-practice/passage/999/1/1')
    assert r.status_code == 400
    assert 'no-store' in r.headers.get('Cache-Control', '')
