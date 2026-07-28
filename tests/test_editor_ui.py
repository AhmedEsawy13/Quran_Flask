"""Editor-only UI contracts for the shared أثَر workspace."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_editor_uses_shared_workspace_and_accessible_editing(client):
    page = client.get('/mushaf-editor').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')

    assert '<body class="athar-editor">' in page
    assert page.index('css/athar-components.css') < page.index('css/athar-page-chrome.css')
    assert page.index('css/athar-page-chrome.css') < page.index('css/mushaf_editor.css')
    assert 'id="ed-bar"' in page and 'aria-labelledby="ed-title"' in page
    assert '<header class="ed-bar"' not in page
    assert 'id="ed-bar-toggle"' in page
    assert 'id="ed-zoom-in"' in page
    assert 'id="ed-zoom-out"' in page
    assert 'id="ed-zoom-reset"' in page
    assert 'setPageZoom' in script
    assert 'ed-bar--compact' in script
    assert 'id="ed-title" aria-label="طابق المطبوع، واضبط الوقف."' in page
    assert 'طابِق المطبــوع، واضبط الوقف.' in page
    assert 'محرّر الوقف' in page
    assert 'محرّر المصحف' not in page
    assert 'IBM Plex' not in page
    assert 'id="ed-studio-link"' in page
    assert 'href="/waqf-lab"' in page
    assert 'href="/waqf"' in page
    assert 'id="ed-compare-mode"' in page
    assert 'data-mode="madinah"' in page
    assert 'data-mode="print"' in page
    assert 'compareMode' in script
    assert "state.compareMode === 'madinah'" in script
    assert 'STUDIO_BY_EDITION' in script
    assert 'id="ed-edition-toggle" role="group" aria-label="نسخة المصحف"' in page
    assert page.count('class="ed-edition-btn athar-tab"') == 3
    for edition in ('قطر', 'الكويت', 'البحرين'):
        assert f'data-edition="{edition}"' in page
    assert 'id="ed-progress" role="progressbar"' in page
    assert 'aria-valuemin="0" aria-valuemax="604" aria-valuenow="0"' in page
    assert 'id="athar-main" tabindex="-1" aria-labelledby="ed-title"' in page
    assert 'role="dialog" aria-modal="true" aria-labelledby="ed-popup-title"' in page
    assert "wordElement.setAttribute('role', 'button')" in script
    assert 'wordElement.tabIndex = 0' in script
    assert "b.setAttribute('aria-pressed'" in script
    assert "window.AtharUi.setBusy(els.main" in script
    assert "window.matchMedia('(max-width: 720px)')" in script
    assert 'pages: stacked ? 1 : 2' in script
    assert 'id="ed-compare"' in page
    assert 'id="ed-ref-img"' in page
    assert 'نسختك · التحرير' in page
    assert 'المطبوع · المرجع' in page
    assert 'REF_SOURCES' in script
    assert 'leafOffset: 3' in script
    assert "'البحرين': {" in script
    assert 'MushafQatar_20150445776437' in script
    assert 'trapPopupFocus(e)' in script
    assert 'syncWaqfPreview' in script
    assert 'mukthHref' in script
    assert 'id="ed-waqf-preview"' in page
    assert 'id="ed-popup-preview"' in page
    assert 'مُكْث — كيف يقف القرّاء' in page
    assert 'initialEdition' in script
    assert 'resolveVerseHint' in script
    assert '/api/mushaf-editor/page-by-ayah/' in script


def test_editor_page_by_ayah_resolves(client):
    r = client.get('/api/mushaf-editor/page-by-ayah/2/255?edition=%D9%82%D8%B7%D8%B1')
    assert r.status_code == 200
    data = r.get_json()
    assert data['edition'] == 'قطر'
    assert data['surah'] == 2 and data['ayah'] == 255
    assert isinstance(data['page_number'], int) and 1 <= data['page_number'] <= 604
    bad = client.get('/api/mushaf-editor/page-by-ayah/2/255?edition=madinah')
    assert bad.status_code == 400


def test_waqf_hides_editor_cta_when_editor_disabled():
    from app import create_app
    bare = create_app({'core', 'breathing'}).test_client()
    page = bare.get('/waqf').get_data(as_text=True)
    lab = bare.get('/waqf-lab').get_data(as_text=True)
    assert 'id="wq-editor-cta"' not in page
    assert 'data-editor-enabled' not in page
    assert 'محرّر الوقف' not in lab
    assert bare.get('/mushaf-editor').status_code == 404
