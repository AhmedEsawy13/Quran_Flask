"""Font Lab — OpenType playground wiring."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_font_lab_route_and_catalog(client, monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')

    resp = client.get('/font-lab')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'مختبر الخط' in html
    assert 'font_lab_catalog.js' in html
    assert 'font_lab.js' in html
    assert 'id="fl-features"' in html
    assert 'id="fl-samples"' in html

    catalog = (PROJECT_ROOT / 'static/js/font_lab_catalog.js').read_text(encoding='utf-8')
    assert 'Digital Khatt' in catalog
    assert "'jalt'" in catalog or '"jalt"' in catalog or 'jalt' in catalog
    assert 'AtharFontLabCatalog' in catalog
    assert 'meem_khanjariyya' in catalog
    assert 'hakeem' in catalog
    assert 'كاف / اتصالات' in catalog
    assert 'max: 12' in catalog
    assert '\\u06E2' in catalog or '\u06E2' in catalog

    js = (PROJECT_ROOT / 'static/js/font_lab.js').read_text(encoding='utf-8')
    assert 'font-feature-settings' in js
    assert 'AtharFontLabCatalog' in js
    assert 'fl-stepper' in js or 'setFeatureValue' in js
    assert "'cv01'" in js or 'featureMax' in js or 'buildFeatureSettings' in js


def test_font_lab_gated_without_editor(client, monkeypatch):
    monkeypatch.delenv('ENABLE_EDITOR', raising=False)
    # App may already have editor registered from conftest — skip if blueprint always on.
    # When FEATURES exclude editor, /font-lab should 404.
    from app import create_app

    app = create_app(features={'core', 'reading'})
    with app.test_client() as bare:
        resp = bare.get('/font-lab')
        assert resp.status_code == 404


def test_font_lab_disallowed_in_robots(client):
    body = client.get('/robots.txt').get_data(as_text=True)
    assert 'Disallow: /font-lab' in body
