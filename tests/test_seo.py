"""SEO / AI crawler surfaces + shared page meta."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_robots_sitemap_llms(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://example.test')
    robots = client.get('/robots.txt')
    assert robots.status_code == 200
    text = robots.get_data(as_text=True)
    assert 'Sitemap: https://example.test/sitemap.xml' in text
    assert 'Disallow: /api/' in text
    assert 'Disallow: /mushaf-editor' in text
    assert 'Disallow: /activity' in text
    assert 'Disallow: /waqf-mark-review' in text
    assert 'Disallow: /cv-waqf' in text

    sitemap = client.get('/sitemap.xml')
    assert sitemap.status_code == 200
    xml = sitemap.get_data(as_text=True)
    assert 'https://example.test/' in xml
    assert 'https://example.test/waqf' in xml
    assert 'https://example.test/waqf-practice' in xml
    assert 'https://example.test/read' in xml
    assert 'https://example.test/memorize' in xml
    assert 'https://example.test/credits' in xml
    assert 'waqf-lab' not in xml
    assert 'mushaf-editor' not in xml

    llms = client.get('/llms.txt')
    assert llms.status_code == 200
    body = llms.get_data(as_text=True)
    assert 'أثَر' in body or 'Athar' in body
    assert 'https://example.test/waqf' in body
    assert 'https://example.test/credits' in body
    assert 'knowing where to stop' in body


def test_credits_page_lists_key_sources(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://example.test')
    r = client.get('/credits')
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'المصادر والشكر' in page
    assert 'cpfair/quran-tajweed' in page
    assert 'مركز تفسير' in page
    assert 'Tafsir MCP' in page or 'tafsir-mcp' in page
    assert 'OpenITI' in page
    assert 'أسباب النزول' in page or 'سبب النزول' in page
    assert 'الحصري' in page or 'القرّاء' in page


def test_landing_has_social_and_canonical(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://example.test')
    page = client.get('/').get_data(as_text=True)
    assert 'rel="canonical"' in page
    assert 'https://example.test/' in page
    assert 'property="og:title"' in page
    assert 'property="og:description"' in page
    assert 'property="og:image"' in page
    assert '/static/img/og-default.png' in page
    assert 'application/ld+json' in page
    assert (PROJECT_ROOT / 'static/img/og-default.png').is_file()
