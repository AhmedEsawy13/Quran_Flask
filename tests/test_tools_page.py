"""/tools lists the editor's tools; the nav links to it only where the editor runs."""
from __future__ import annotations

from app import create_app


def test_tools_page_lists_every_tool(client):
    page = client.get('/tools')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    for href in ('/mushaf-editor', '/mushaf-editor/book-audit', '/waqf-mark-review', '/azhar-waqf-review',
                 '/cv-waqf', '/layout-studio', '/font-lab', '/classical-review', '/tawjih-review',
                 '/quran-integrity-review', '/activity'):
        assert f'href="{href}"' in body, href
    assert '/layout-studio/bahrain' in body


def test_every_listed_tool_page_exists(client):
    from modules.tools import tool_groups
    for group in tool_groups():
        for tool in group['tools']:
            assert client.get(tool['href']).status_code in (200, 302), tool['href']


def test_nav_shows_tools_only_with_the_editor(client):
    assert 'href="/tools"' in client.get('/read').get_data(as_text=True)
    public = create_app({'core', 'reading', 'memorize', 'breathing'}).test_client()
    body = public.get('/read').get_data(as_text=True)
    assert 'href="/tools"' not in body
    assert public.get('/tools').status_code == 404


def test_every_tool_page_uses_the_shared_shell_and_sign_in(client):
    """Same head (fonts, tokens, theme), app bar and sign-in panel on every tool."""
    from modules.tools import tool_groups
    for group in tool_groups():
        for tool in group['tools']:
            body = client.get(tool['href'], follow_redirects=True).get_data(as_text=True)
            assert 'css/brand.css' in body, tool['href']
            assert 'class="athar-bar"' in body, tool['href']
            assert 'js/athar-auth.js' in body, tool['href']
            assert 'fonts.googleapis.com' not in body, tool['href']


def test_public_pages_do_not_load_the_sign_in_script():
    public = create_app({'core', 'reading', 'memorize', 'breathing'}).test_client()
    assert 'athar-auth.js' not in public.get('/read').get_data(as_text=True)


def test_every_tool_page_loads_the_app_bar_icons(client):
    from modules.tools import tool_groups
    for group in tool_groups():
        for tool in group['tools']:
            body = client.get(tool['href'], follow_redirects=True).get_data(as_text=True)
            assert 'font-awesome/6.4.0' in body, tool['href']
