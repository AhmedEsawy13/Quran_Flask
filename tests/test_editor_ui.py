"""Editor-only UI contracts for the shared أثَر workspace."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_editor_uses_shared_workspace_and_accessible_editing(client):
    page = client.get('/mushaf-editor').get_data(as_text=True)
    script = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')

    assert '<body class="athar-editor">' in page
    assert page.index('css/athar-components.css') < page.index('css/athar-page-chrome.css')
    assert page.index('css/athar-page-chrome.css') < page.index('css/mushaf_editor.css')
    assert '<section class="ed-bar" id="ed-bar" aria-labelledby="ed-title">' in page
    assert '<header class="ed-bar"' not in page
    assert 'id="ed-title" aria-label="راجع المصحف، واضبط الوقف."' in page
    assert 'راجِع المصحــف، واضبط الوقف.' in page
    assert 'id="ed-edition-toggle" role="group" aria-label="نسخة المصحف"' in page
    assert page.count('class="ed-edition-btn athar-tab"') == 2
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
    assert 'REF_LEAF_OFFSET' in script
    assert 'MushafQatar_20150445776437' in script
    assert 'trapPopupFocus(e)' in script
