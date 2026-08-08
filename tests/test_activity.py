"""Activity log page + filtered audit API."""
from __future__ import annotations

import pytest

from core import supabase_editor as sb
from modules.editor_auth import invalidate_editor_session_cache
from tests.test_supabase_editor import FakeSupabase, _login, _seed_invite


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-service-role')
    monkeypatch.setenv('EDITOR_SESSION_SECRET', 'test-editor-secret-at-least-32-chars')

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        return fake.handle(method, url, params=params, json_body=json)

    monkeypatch.setattr(sb.requests, 'request', fake_request)
    invalidate_editor_session_cache()
    yield fake
    invalidate_editor_session_cache()


def test_activity_page_renders(client):
    page = client.get('/activity')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'id="act-feed"' in body
    assert 'سجل التعديلات' in body
    assert 'js/activity.js' in body


def test_activity_api_requires_login_when_cloud(client, cloud):
    denied = client.get('/api/activity')
    assert denied.status_code == 401


def test_activity_api_filters_and_cursor(client, cloud):
    _seed_invite(cloud, name='Mac', role='admin', username='mac')
    _login(client, 'mac')

    sb.append_audit(
        actor_id='u-mac', actor_name='Mac', action='set_mark',
        edition='قطر', surah=1, ayah=1, old_symbol='', new_symbol='ج',
    )
    sb.append_audit(
        actor_id='u-mac', actor_name='Mac', action='layout_save',
        edition='bahrain', page_number=12,
    )
    sb.append_audit(
        actor_id='u-other', actor_name='Other', action='mark_review_decision',
        edition='الشمرلي', page_number=4, meta={'decision': 'ok'},
    )

    all_items = client.get('/api/activity?limit=10')
    assert all_items.status_code == 200
    assert all_items.headers['Cache-Control'] == 'no-store, max-age=0'
    payload = all_items.get_json()
    assert payload['cloud'] is True
    actions_seen = {row['action'] for row in payload['items']}
    assert {'set_mark', 'layout_save', 'mark_review_decision'} <= actions_seen
    assert 'layout_save' in payload['actions']

    layout_only = client.get('/api/activity?action=layout_save')
    assert layout_only.status_code == 200
    items = layout_only.get_json()['items']
    assert len(items) == 1
    assert items[0]['edition'] == 'bahrain'

    edition = client.get('/api/activity?edition=%D9%82%D8%B7%D8%B1')
    assert len(edition.get_json()['items']) == 1

    q = client.get('/api/activity?q=Other')
    assert len(q.get_json()['items']) == 1

    actors = all_items.get_json().get('actors') or []
    assert any(a.get('name') == 'Mac' for a in actors)

    actor_filter = client.get('/api/activity?actor_id=u-other')
    assert actor_filter.status_code == 200
    assert len(actor_filter.get_json()['items']) == 1

    first = client.get('/api/activity?limit=1').get_json()
    assert first['next_cursor']
    more = client.get(
        '/api/activity?limit=10'
        f"&before_at={first['next_cursor']['before_at']}"
        f"&before_id={first['next_cursor']['before_id']}"
    )
    assert more.status_code == 200
    assert len(more.get_json()['items']) >= 1


def test_list_audit_helpers_accept_new_actions():
    assert 'layout_save' in sb.AUDIT_ACTIONS
    assert 'mark_review_decision' in sb.AUDIT_ACTIONS


def test_activity_cursor_reaches_every_row_without_duplicates(client, cloud):
    _seed_invite(cloud, name='Mac', role='admin', username='mac-pages')
    _login(client, 'mac-pages')
    for page in range(1, 131):
        sb.append_audit(
            actor_id='u-mac',
            actor_name='Mac',
            action='layout_save',
            edition='bahrain',
            page_number=page,
        )

    seen = []
    cursor = None
    while True:
        query = '/api/activity?action=layout_save&limit=40'
        if cursor:
            query += (
                f"&before_at={cursor['before_at']}"
                f"&before_id={cursor['before_id']}"
            )
        payload = client.get(query).get_json()
        seen.extend(row['id'] for row in payload['items'])
        cursor = payload['next_cursor']
        if not cursor:
            break

    assert len(seen) == 130
    assert len(set(seen)) == 130


def test_activity_search_can_continue_past_empty_scan_window(client, cloud):
    _seed_invite(cloud, name='Mac', role='admin', username='mac-search')
    _login(client, 'mac-search')
    sb.append_audit(
        actor_id='needle',
        actor_name='Needle Editor',
        action='set_mark',
        edition='قطر',
    )
    for page in range(1, 231):
        sb.append_audit(
            actor_id='noise',
            actor_name='Other',
            action='layout_save',
            edition='bahrain',
            page_number=page,
        )

    first = client.get('/api/activity?q=Needle&limit=40').get_json()
    assert first['items'] == []
    assert first['next_cursor']
    second = client.get(
        '/api/activity?q=Needle&limit=40'
        f"&before_at={first['next_cursor']['before_at']}"
        f"&before_id={first['next_cursor']['before_id']}"
    ).get_json()
    assert [row['actor_name'] for row in second['items']] == ['Needle Editor']
    assert second['next_cursor'] is None


def test_activity_rejects_partial_cursor(client, cloud):
    _seed_invite(cloud, name='Mac', role='admin', username='mac-cursor')
    _login(client, 'mac-cursor')
    response = client.get('/api/activity?before_id=1')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'incomplete cursor'


def test_activity_js_avoids_append_duplicates_and_csv_formulas():
    from pathlib import Path

    js = (
        Path(__file__).resolve().parents[1] / 'static' / 'js' / 'activity.js'
    ).read_text(encoding='utf-8')
    assert 'const renderItems = append ? (newItems || []) : state.items;' in js
    assert 'renderFeed(!!append, items);' in js
    assert "/^[\\t\\r ]*[=+\\-@]/" in js
