"""Boot / feature-flag / robustness tests for the split app.

After carving app.py into core/ + modules/, guard that the app still assembles
under every deployment shape and that the newer endpoints refuse bad input
cleanly instead of 500-ing.
"""
from pathlib import Path

import app as quran_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_all_features_including_editor_boot(client):
    """Every module's landing endpoint resolves on the fully-mounted app."""
    for url in ('/', '/memorize', '/waqf', '/waqf-practice', '/mushaf-editor',
                '/api/surahs', '/api/surahs/2/ayahs/255', '/api/classical-waqf/2/2',
                '/api/waqf-practice/passage/2/1/3',
                '/api/mushaf-editor/spread/2?edition=%D9%82%D8%B7%D8%B1'):
        assert client.get(url).status_code == 200, url


def test_release_workflows_cover_push_smoke_and_supabase_readiness():
    ci = (
        PROJECT_ROOT / '.github' / 'workflows' / 'ci.yml'
    ).read_text(encoding='utf-8')
    smoke = (
        PROJECT_ROOT / '.github' / 'workflows' / 'production-smoke.yml'
    ).read_text(encoding='utf-8')
    assert 'push:' in ci and 'pull_request:' in ci
    assert 'python3 -m pytest -q' in ci
    assert 'audit_release_readiness.py' in ci
    assert 'smoke_test.py --local --include-editor' in ci
    assert 'PRODUCTION_BASE_URL' in smoke
    assert 'check_supabase_readiness.py' in smoke


def test_enabled_features_env(monkeypatch):
    monkeypatch.setenv('FEATURES', 'reading,memorize')
    monkeypatch.delenv('ENABLE_EDITOR', raising=False)
    feats = quran_app.enabled_features()
    assert 'core' in feats and 'reading' in feats and 'memorize' in feats
    assert 'editor' not in feats                      # editor never mounts without ENABLE_EDITOR
    monkeypatch.setenv('ENABLE_EDITOR', '1')
    assert 'editor' in quran_app.enabled_features()


def test_create_app_returns_an_isolated_feature_set():
    core_only = quran_app.create_app({'core'})
    assert set(core_only.blueprints) == {'core'}
    assert core_only.test_client().get('/api/surahs').status_code == 200
    assert core_only.test_client().get('/memorize').status_code == 404

    # Core is mandatory even when the explicit set omits it.
    reading_only = quran_app.create_app({'reading'})
    assert set(reading_only.blueprints) == {'core', 'reading'}


def test_false_editor_env_values_do_not_enable_writer(monkeypatch):
    monkeypatch.delenv('FEATURES', raising=False)
    for value in ('0', 'false', 'no', 'off'):
        monkeypatch.setenv('ENABLE_EDITOR', value)
        assert 'editor' not in quran_app.enabled_features()


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
    assert client.post('/api/waqf-practice/grade', json=[]).status_code == 400
    assert client.post('/api/waqf-practice/grade', json={
        'surah': 1, 'from_ayah': 1, 'to_ayah': 1, 'stops': 42,
    }).status_code == 400


def test_practice_tajweed_rejects_malformed_json(client):
    assert client.post('/api/waqf-practice/tajweed', json={
        'surah': 'not-a-number', 'from_ayah': 1, 'to_ayah': 1, 'phonemes': 'a',
    }).status_code == 400
    assert client.post('/api/waqf-practice/tajweed', json={
        'surah': 1, 'from_ayah': 1, 'to_ayah': 1, 'phonemes': [],
    }).status_code == 400


def test_error_responses_stay_uncached_across_modules(client):
    r = client.get('/api/waqf-practice/passage/999/1/1')
    assert r.status_code == 400
    assert 'no-store' in r.headers.get('Cache-Control', '')


def test_static_assets_are_cdn_cacheable(client):
    r = client.get('/static/css/brand.css')
    assert r.status_code == 200
    cc = r.headers.get('Cache-Control', '')
    assert 'public' in cc and 'immutable' in cc


def test_editor_html_is_not_cdn_cached(client, monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')
    from app import create_app
    app = create_app()
    r = app.test_client().get('/mushaf-editor')
    assert r.status_code == 200
    assert 'no-store' in r.headers.get('Cache-Control', '')


def test_editor_rejects_out_of_bounds_and_unknown_symbols(client):
    assert client.get('/api/mushaf-editor/spread/303?edition=%D9%82%D8%B7%D8%B1').status_code == 400
    assert client.post('/api/mushaf-editor/progress', json={
        'edition': 'قطر', 'page_number': 605, 'reviewed': True,
    }).status_code == 400
    assert client.post('/api/mushaf-editor/waqf', json={
        'word_id': 1, 'edition': 'قطر', 'symbol': '<script>',
    }).status_code == 400
    assert client.post('/api/mushaf-editor/waqf', json=[]).status_code == 400
    assert client.post('/api/mushaf-editor/waqf', json={
        'word_id': 1, 'edition': [], 'symbol': '',
    }).status_code == 400
    assert client.post('/api/mushaf-editor/progress', json=[]).status_code == 400


def test_shared_frontend_layers_are_mounted(client):
    reading = client.get('/read').get_data(as_text=True)
    assert 'css/reading_athar.css' in reading
    assert 'js/athar-api.js' in reading
    assert '<body class="athar-reading">' in reading
    for url in ('/waqf', '/waqf-practice', '/memorize', '/mushaf-editor'):
        assert 'js/athar-api.js' in client.get(url).get_data(as_text=True)
    for url in ('/', '/read', '/waqf', '/waqf-practice', '/memorize', '/mushaf-editor'):
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
        assert 'css/athar-components.css' in page, route


def test_ui_foundation_exposes_thmanyah_alternates_and_components(client):
    components = (PROJECT_ROOT / 'static/css/athar-components.css').read_text(encoding='utf-8')
    brand = (PROJECT_ROOT / 'static/css/brand.css').read_text(encoding='utf-8')
    landing = client.get('/').get_data(as_text=True)

    # Thmanyah documents الحروف المرسلة as OpenType Stylistic Alternates.
    assert 'font-feature-settings: "salt" 1' in components
    assert 'font-feature-settings: "ss01" 1' not in brand
    # Manual Tatweel remains authored content and is not synthesized by CSS.
    assert 'الأثـر' in landing
    assert 'من تجويد الحروف' in landing
    assert 'إلى معرفة الوقوف' in landing
    assert 'مواضع الوقف بثقة' in landing
    assert 'data-src="qpc_v1"' in landing
    assert 'id="lp-tajweed"' in landing
    assert 'class="athar-button" href="/read"' in landing
    assert 'class="athar-button athar-button-ghost" href="/waqf-practice"' in landing
    for primitive in ('athar-page-intro', 'athar-toolbar', 'athar-surface',
                      'athar-field', 'athar-chip', 'athar-tabs', 'athar-sheet'):
        assert f'.{primitive}' in components


def test_reader_uses_shared_editorial_structure_and_accessible_tools(client):
    page = client.get('/read').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/script.js').read_text(encoding='utf-8')

    assert page.index('css/athar-components.css') < page.index('css/reading_athar.css')
    assert 'class="reader-intro athar-tool-intro" aria-labelledby="reader-title"' in page
    assert 'id="reader-title" aria-label="اقرأ المصحف، وتدبّر المعنى."' in page
    assert 'اقرأ المصحــف، وتدبّر المعنى.' in page
    assert 'class="reader-primary athar-tool-chrome"' in page
    assert 'class="reader-drawer athar-surface" id="reader-waqf-drawer"' in page
    assert 'class="reader-drawer athar-surface" id="reader-study-drawer"' in page
    assert 'class="ayah-container reader-canvas athar-surface"' in page
    for target in ('transliteration-container', 'tafseer-container', 'eerab-container',
                   'mutashabihat-container', 'word-meaning-text',
                   'waqf-verse-table-container'):
        assert f'aria-controls="{target}"' in page
    assert "setAttribute('aria-expanded'" in script
    assert "setAttribute('aria-pressed'" in script


def test_reader_indopak_legend_shows_real_unicode_marks(client):
    """الهندي legend must show DB glyphs (ؕ/ؗ), not letter stand-ins ط/ز."""
    page = client.get('/read').get_data(as_text=True)
    assert 'waqf-legend-indopak' in page
    assert 'ؕ — ط المطلق' in page
    assert 'ؗ — ز المجوَّز' in page
    assert 'ۖ — ص المرخّص' in page
    assert 'ط — المطلق' not in page


def test_reader_indopak_waqf_uses_overlay_stack_like_other_mushafs():
    """IndoPak must strip inline ruling marks and show الهندي via .waqf-stack
    overlays — not suppress overlays while displaying cleaned text (which hid
    mid-verse stops). Empty waqf-only tokens must be dropped to avoid gaps."""
    script = (PROJECT_ROOT / 'static/js/script.js').read_text(encoding='utf-8')
    assert "if (isIndoPak) return symbols.filter(s => (s.version || '') === 'الهندي')" in script
    assert "if (isIndoPak && v === 'الهندي') return true" in script
    assert "if (isIndoPak && v === 'الهندي') return false" not in script
    assert "indopak_nastaleeq: ['الهندي']" in script
    assert '.filter(Boolean)' in script
    assert 'INDOPAK_INLINE_WAQF_STRIP' in script
    assert "(isIndoPak || mode === 'selected' || mode === 'none')" in script


def test_reader_preserves_nbsp_glued_ayah_number_for_shemrly_glyphs():
    """displayQuranicText must not split on NBSP — Shemrly glyph upgrade needs
    the trailing ayah-number glued to the last word (API drops it as its own
    row). Using JS \\s+ regressed production: fonts loaded, glyphs never applied."""
    script = (PROJECT_ROOT / 'static/js/script.js').read_text(encoding='utf-8')
    assert 'split(/[ \\t\\n\\r\\f\\v]+/)' in script
    assert "String(text || '').split(/\\s+/).filter(Boolean)" not in script
    assert 'applyShamarlyGlyphs' in script


def test_waqf_lab_exposes_accessible_tabs_and_live_status(client):
    page = client.get('/waqf-lab').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/waqf_guide.js').read_text(encoding='utf-8')
    assert 'athar-waqf-lab' in page
    assert 'role="tablist"' in page
    assert page.count('role="tab"') >= 13  # 3 families + 10 tools
    assert page.count('role="tabpanel"') == 10
    assert 'id="wq-lab-picker"' in page
    assert 'id="wq-lab-sheet-root"' in page
    assert 'aria-controls="wq-lab-sheet-root"' in page
    assert 'id="wq-status" role="status" aria-live="polite" hidden' in page
    assert 'wq-lab-families' in page
    assert 'wq-lab-chrome' in page
    assert 'wq-lab-family-sub' in page
    assert 'wq-presets-disclosure' in page
    assert 'wq-research-free-lead' in page
    assert 'data-family="words"' in page
    assert 'data-family="reciters"' in page
    assert 'data-family="mushafs"' in page
    assert 'hitRowFromOcc' in script
    assert 'paginateList' in script
    assert 'wq-cl-mobile' in script
    assert 'wq-agree-mobile' in script
    assert 'wq-solos-rank-row' in script
    assert 'applyVerseHighlight' in script
    assert 'optsFromHitEl' in script
    assert "searchParams.set('q'" in script
    assert "searchParams.set('hl'" in script
    assert "searchParams.set('wpos'" in script


def test_waqf_uses_shared_research_workspace_structure(client):
    page = client.get('/waqf').get_data(as_text=True)
    lab = client.get('/waqf-lab').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/waqf_guide.js').read_text(encoding='utf-8')

    assert 'class="athar-waqf"' in page
    assert 'wq-research-body' not in page
    assert 'href="/waqf-lab"' in page
    assert 'id="wq-lab-cta-card"' in page
    assert 'href="/mushaf-editor"' in page
    assert 'id="wq-editor-cta"' in page
    assert 'data-editor-enabled="1"' in page
    assert 'data-editor-enabled="1"' in lab
    assert 'href="/mushaf-editor"' in lab
    assert 'editorJumpHtml' in script
    assert 'EDITOR_ENABLED' in script
    assert page.index('id="wq-verse-card"') < page.index('id="wq-lab-cta-card"')
    assert 'IBM+Plex' not in page
    assert page.index('css/athar-components.css') < page.index('css/waqf_guide.css')
    assert 'wq-bar athar-tool-chrome' in page
    assert 'aria-labelledby="wq-title"' in page
    assert '<header class="wq-bar"' not in page
    assert 'id="wq-title" aria-label="ادرس وقوفهم، وافهم الاختلاف."' in page
    assert 'ادرس وقوفــهم، وافهم الاختلاف.' in page
    assert 'id="wq-matrix-mobile"' in page
    assert 'renderMatrixMobile' in script
    assert 'wq-matrix-desktop' in page
    assert 'wq-picker athar-toolbar-group' in page
    assert page.count('athar-surface') >= 6
    assert 'role="combobox" aria-autocomplete="list"' in page
    assert 'id="wq-search-results" role="listbox"' in page
    assert 'function selectLabTab' in script
    assert 'setLabSheetOpen' in script
    assert 'IS_LAB' in script
    assert 'setFamily' in script
    assert "setAttribute('aria-activedescendant'" in script
    assert "setAttribute('aria-pressed'" in script
    assert 'wq-lab-workspace' in lab
    assert 'id="wq-research-body"' in lab
    assert 'IBM+Plex' not in lab

def test_waqf_practice_exposes_live_async_state(client):
    page = client.get('/waqf-practice').get_data(as_text=True)
    assert 'id="wp-page-state" role="status" aria-live="polite" hidden' in page


def test_waqf_practice_uses_shared_training_foundation(client):
    page = client.get('/waqf-practice').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/waqf_practice.js').read_text(encoding='utf-8')

    assert '<body class="athar-training">' in page
    assert 'css/athar-components.css' in page
    assert 'css/athar-page-chrome.css' in page
    assert 'js/athar-page-chrome.js' in page
    assert 'css/waqf_practice.css' in page
    assert 'css/mushaf_memorize.css' not in page
    assert page.index('css/athar-components.css') < page.index('css/waqf_practice.css')
    assert 'wp-ml-pages' in script
    assert 'AtharPageChrome.sizePages' in script
    assert 'id="wp-layout"' not in page
    assert 'id="wp-intro" aria-labelledby="wp-title"' in page
    assert 'id="wp-title" aria-label="اختبر وقفك، ثم افهم النتيجة."' in page
    assert 'اختبر وقفــك، ثم افهم النتيجة.' in page
    assert 'class="wp-toolbar athar-tool-chrome"' in page
    assert page.count('class="wp-section athar-surface') == 3
    assert 'aria-controls="wp-range-panel"' in page
    assert 'aria-controls="wp-mushaf-panel"' in page
    assert 'class="athar-button" id="wp-grade"' in page
    assert '.wp-pop' in script and '.mz-pop' not in script
    assert "classList.toggle('is-listening'" in script


def test_waqf_practice_invalidates_stale_grade_when_stops_change():
    script = (PROJECT_ROOT / 'static/js/waqf_practice.js').read_text(encoding='utf-8')

    assert 'function invalidateGradeResult()' in script
    assert 'gradeRequests.cancel();' in script
    assert 'els.resultSec.hidden = true;' in script
    assert script.count('invalidateGradeResult();') >= 3


def test_memorization_exposes_live_status(client):
    page = client.get('/memorize').get_data(as_text=True)
    assert 'id="mz-status" role="status" aria-live="polite" hidden' in page
    assert 'id="mz-asr-dev" hidden' in page
    assert 'id="mz-recite-btn"' in page


def test_memorization_uses_shared_workspace_structure(client):
    page = client.get('/memorize').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/mushaf_memorize.js').read_text(encoding='utf-8')

    assert '<body class="athar-memorize">' in page
    assert page.index('css/athar-components.css') < page.index('css/athar-page-chrome.css')
    assert page.index('css/athar-page-chrome.css') < page.index('css/mushaf_memorize.css')
    assert 'id="mz-bar"' in page and 'aria-labelledby="mz-title"' in page
    assert 'mz-bar athar-tool-chrome' in page
    assert '<header class="mz-bar"' not in page
    assert 'id="mz-title" aria-label="ثبّت حفظك."' in page
    assert 'ثبّت حفظــك.' in page
    assert 'mz-title-sr' in page
    assert 'class="mz-range-guide" role="note"' in page
    assert 'اضغط آية البداية، ثم آية النهاية' in page
    assert 'class="mz-context"' not in page
    assert 'class="mz-bar-settings" aria-label="إعدادات الجلسة"' in page
    assert 'class="mz-bar-view" role="group" aria-label="خيارات العرض"' in page
    assert 'aria-controls="mz-reciter-panel"' in page
    assert 'aria-controls="mz-src-panel"' in page
    assert 'aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"' in page
    assert script.count("els.progress.addEventListener('click'") == 1
    assert "els.progress.setAttribute('aria-valuenow'" in script
    assert "els.bar?.getBoundingClientRect().height" in script


def test_memorization_old_madina_justification_is_adaptive():
    memorize = (PROJECT_ROOT / 'static/js/mushaf_memorize.js').read_text(encoding='utf-8')
    landing = (PROJECT_ROOT / 'static/js/landing.js').read_text(encoding='utf-8')
    shared = (PROJECT_ROOT / 'static/js/athar-page-chrome.js').read_text(encoding='utf-8')

    # Madinah OpenType ladders live once in AtharPageChrome (تثبيت source of truth).
    assert 'function digitalKhattFeatureCandidates(strength)' in shared
    assert 'function oldMadinaFeatureCandidates(strength)' in shared
    assert "`'jalt' 1, 'cv01' 1, 'cv02' 1, 'cv03' 1`" in shared
    assert "['cv02', 'cv03']" in shared
    assert 'return variants.map(tags =>' in shared
    assert 'oldMadinaFeatureCandidates(state.justify)' in memorize
    assert 'digitalKhattFeatureCandidates(state.justify)' in memorize
    assert 'oldMadinaFeatureCandidates(100)' in landing
    assert 'digitalKhattFeatureCandidates(100)' in landing
    assert 'khattFeatureSettings(100)' not in memorize
    assert 'const OLD_MADINA_PAGE_RATIO = 0.72' in memorize
    assert "ratio: state.src === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO : PAGE_RATIO" in memorize
    assert "cacheKey: () => `${state.src}|${state.layoutMode}|${state.focusPage || 0}`" in memorize
    assert "const MADINAH_SOURCES = new Set(['qpc_v1', 'qpc_v2', 'digital_khatt'])" in memorize
    assert "const DIGITAL_KHATT_SOURCES = new Set(['qpc_v2', 'digital_khatt'])" in memorize
    assert 'isMadinahSource(state.src) ? 0.95 : 0' in memorize
    assert 'if (!isMadinahSource(state.src)) return Infinity' in memorize
    assert 'isDigitalKhattSource(state.src) ? 1.15' in memorize
    assert "state.src === 'qpc_v1' ? 1.18" in memorize
    assert 'applySrcClass();\n            syncBarLabels();' in memorize
    assert 'linesPerPage = 15, cacheKey = () => \'\', fitScale = 1' in shared
    assert 'minLineScale = 0' in shared
    assert 'minFontSize = 11' in shared
    assert 'minFontSize: 9.5' in memorize
    assert 'minFontSize: 9.5' in landing
    assert 'sharedSize = true' in shared
    assert 'sharedSize: false' in memorize
    assert 'maxPageFitRatio = Infinity' in shared
    assert 'maxPageFitRatio: 1.15' in memorize
    assert 'maxPageFitRatio: 1.15' in landing
    assert "state.layoutMode === 'dual' ? 1.20" in memorize
    assert 'fs * ratios[0] * 0.99 / resolvedMinLineScale' in shared
    assert 'minFeatureScale = 1, minLineScale = 0.5' in shared
    assert 'fontSize * rawScale / lineScaleFloor' in shared
    assert 'isMadinahSource(state.src) ? 0.95 : 0.5' in memorize
    assert 'featureCandidates = null' in shared
    assert 'const spacing = Math.min(slack / gaps, spacingCap)' in shared
