"""Public SEO / AI-crawler surfaces: robots.txt, sitemap.xml, llms.txt."""
from __future__ import annotations

import os

from flask import Response, request

from core.blueprints import core_bp

# Indexable product pages only — tools with noindex stay out of the sitemap.
_SITEMAP_PATHS = (
    ('/', 'weekly', '1.0'),
    ('/read', 'weekly', '0.9'),
    ('/memorize', 'weekly', '0.8'),
    ('/waqf', 'weekly', '0.8'),
    ('/waqf-lab', 'weekly', '0.6'),
    ('/waqf-practice', 'weekly', '0.7'),
)


def public_base_url() -> str:
    """Canonical site origin (no trailing slash).

    Prefer PUBLIC_BASE_URL in production (Heroku dyno hostnames change;
    custom domains should be set explicitly). Falls back to the current
    request's url_root when serving.
    """
    configured = (os.environ.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
    if configured:
        return configured
    try:
        return request.url_root.rstrip('/')
    except RuntimeError:
        return 'https://waqfquran-d0b6fce4874e.herokuapp.com'


def public_absolute(path: str = '/') -> str:
    if not path.startswith('/'):
        path = '/' + path
    return public_base_url() + path


@core_bp.route('/robots.txt')
def robots_txt():
    base = public_base_url()
    body = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /api/\n'
        'Disallow: /mushaf-editor\n'
        'Disallow: /classical-review\n'
        'Disallow: /azhar-layout\n'
        'Disallow: /layout-studio\n'
        'Disallow: /font-lab\n'
        '\n'
        f'Sitemap: {base}/sitemap.xml\n'
    )
    return Response(body, mimetype='text/plain; charset=utf-8')


@core_bp.route('/sitemap.xml')
def sitemap_xml():
    urls = []
    for path, changefreq, priority in _SITEMAP_PATHS:
        loc = public_absolute(path)
        urls.append(
            '  <url>\n'
            f'    <loc>{loc}</loc>\n'
            f'    <changefreq>{changefreq}</changefreq>\n'
            f'    <priority>{priority}</priority>\n'
            '  </url>'
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls)
        + '\n</urlset>\n'
    )
    return Response(body, mimetype='application/xml; charset=utf-8')


@core_bp.route('/llms.txt')
def llms_txt():
    base = public_base_url()
    body = f"""# أثَر (Athar)

> Interactive Quran reading, visual memorization, and waqf (stopping) study —
> built on documented mushaf drawings, tajweed rules, and classical scholarly sources.

## Site

- Home: {base}/
- Mushaf reader: {base}/read
- Memorization (تثبيت): {base}/memorize
- Waqf guide (مُكْث): {base}/waqf
- Waqf lab (مختبر الوقف): {base}/waqf-lab
- Waqf practice (تدريب): {base}/waqf-practice

## Product summary

Athar helps Arabic readers and students of tajweed/waqf:
1. Read the mushaf with synchronized recitation and word highlighting.
2. Memorize using page-accurate Madinah layouts (Digital Khatt / Old Madina).
3. Compare printed-mushaf waqf marks and classical opinions (e.g. al-Dānī).
4. Practice placing stops and get graded feedback.

## Preferred citations

- Prefer the canonical URLs above (not ephemeral Heroku review hosts when a custom domain is configured).
- Do not index or summarize `/api/*`, `/mushaf-editor`, `/classical-review`, `/azhar-layout`, `/layout-studio`, or `/font-lab`.

## Contact / project

Open-source Flask app. Public sitemap: {base}/sitemap.xml
"""
    return Response(body, mimetype='text/plain; charset=utf-8')
