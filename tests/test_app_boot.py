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


def test_editor_rejects_out_of_bounds_and_unknown_symbols(client):
    assert client.get('/api/mushaf-editor/spread/303?edition=%D9%82%D8%B7%D8%B1').status_code == 400
    assert client.post('/api/mushaf-editor/progress', json={
        'edition': 'قطر', 'page_number': 605, 'reviewed': True,
    }).status_code == 400
    assert client.post('/api/mushaf-editor/waqf', json={
        'word_id': 1, 'edition': 'قطر', 'symbol': '<script>',
    }).status_code == 400


def test_shared_frontend_layers_are_mounted(client):
    reading = client.get('/read').get_data(as_text=True)
    assert 'css/reading_athar.css' in reading
    assert 'js/athar-api.js' in reading
    assert '<body class="athar-reading">' in reading
    for url in ('/waqf', '/waqf-practice', '/memorize', '/mushaf-editor'):
        assert 'js/athar-api.js' in client.get(url).get_data(as_text=True)
    for url in ('/waqf', '/waqf-practice', '/memorize', '/mushaf-editor'):
        assert 'js/athar-ui.js' in client.get(url).get_data(as_text=True)
    for url in ('/read', '/memorize', '/mushaf-editor', '/waqf', '/waqf-practice'):
        assert 'js/athar-mushaf.js' in client.get(url).get_data(as_text=True)
    for url in ('/memorize', '/mushaf-editor'):
        page = client.get(url).get_data(as_text=True)
        assert 'js/athar-page-chrome.js' in page
        assert 'css/athar-page-chrome.css' in page
    assert 'js/mushaf-layout-core.js' not in client.get('/waqf-practice').get_data(as_text=True)


def test_shared_app_shell_is_consistent_and_route_aware(client):
    routes = {
        '/': (None, 'athar-main'),
        '/read': ('/read', 'athar-main'),
        '/memorize': ('/memorize', 'athar-main'),
        '/waqf': ('/waqf', 'wq-main'),
        '/waqf-practice': ('/waqf-practice', 'athar-main'),
        '/mushaf-editor': (None, 'athar-main'),
    }
    nav_paths = ('/read', '/memorize', '/waqf', '/waqf-practice')
    for route, (active, main_id) in routes.items():
        page = client.get(route).get_data(as_text=True)
        start = page.index('<header class="athar-bar"')
        shell = page[start:page.index('</header>', start)]
        assert shell.count('data-athar-shell="app"') == 1, route
        assert shell.count('data-athar-theme="cycle"') == 1, route
        assert 'aria-label="التنقل الرئيسي"' in shell, route
        assert f'class="athar-skip-link" href="#{main_id}"' in page, route
        assert f'id="{main_id}" tabindex="-1"' in page, route
        assert all(f'href="{path}"' in shell for path in nav_paths), route
        if active:
            assert f'href="{active}" class="is-active" aria-current="page"' in shell, route
            assert shell.count('aria-current="page"') == 1, route
        elif route == '/':
            assert 'class="athar-brand" href="/" title="أثَر — مع القرآن" aria-current="page"' in shell
        else:
            assert 'aria-current="page"' not in shell, route
        assert 'fonts/thmanyahsans/woff2/thmanyahsans-Medium.woff2' in page, route
        assert 'fonts/thmanyahserifdisplay/woff2/thmanyahserifdisplay-Black.woff2' in page, route


def test_waqf_lab_exposes_accessible_tabs_and_live_status(client):
    page = client.get('/waqf').get_data(as_text=True)
    assert 'role="tablist"' in page
    assert page.count('role="tab"') == 10
    assert page.count('role="tabpanel"') == 10
    assert 'id="wq-status" role="status" aria-live="polite" hidden' in page


def test_waqf_practice_exposes_live_async_state(client):
    page = client.get('/waqf-practice').get_data(as_text=True)
    assert 'id="wp-page-state" role="status" aria-live="polite" hidden' in page


def test_memorization_exposes_live_status(client):
    page = client.get('/memorize').get_data(as_text=True)
    assert 'id="mz-status" role="status" aria-live="polite" hidden' in page
    assert 'id="mz-asr-dev" hidden' in page
    assert 'id="mz-recite-btn"' in page
