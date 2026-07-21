"""Kuwait editor edition uses DigitalKhatt Al-Shamiya (1978) webfont."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_editor_ui_references_al_shamiya_for_kuwait():
    css = (PROJECT_ROOT / 'static/css/mushaf_editor.css').read_text(encoding='utf-8')
    js = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    chrome = (PROJECT_ROOT / 'static/js/athar-page-chrome.js').read_text(encoding='utf-8')
    html = (PROJECT_ROOT / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    assert 'alshamiya.woff2' in css
    assert "font-family: 'Al Shamiya'" in css
    assert 'ed-font-kuwait' in css
    assert "classList.toggle('ed-font-kuwait', state.edition === 'الكويت')" in js
    assert 'alShamiyaFeatureCandidates' in js
    assert 'preferExpansion' in js
    assert 'function alShamiyaFeatureCandidates' in chrome
    assert 'preferExpansion' in chrome
    assert "'kt01'" in chrome and "'jt01'" in chrome
    assert 'fonts/alshamiya.woff2' in html
    assert (PROJECT_ROOT / 'static/fonts/alshamiya.woff2').is_file()


def test_kuwait_spread_api_reports_al_shamiya_font(client):
    data = client.get('/api/mushaf-editor/spread/1?edition=الكويت').get_json()
    assert data['edition'] == 'الكويت'
    assert data['right']['font_name'] == 'Al Shamiya'
    assert data['right']['source'] == 'qpc_v1'
    if data.get('left'):
        assert data['left']['font_name'] == 'Al Shamiya'
