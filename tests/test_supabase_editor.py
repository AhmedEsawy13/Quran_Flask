"""Cloud mushaf-editor: invite auth, draft vs published, mock Supabase HTTP."""
from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from core import supabase_editor as sb
from core.mushaf_waqf import invalidate_cloud_waqf_cache, _fetch_single_mushaf_waqf
from modules.editor_auth import COOKIE_NAME


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


class FakeSupabase:
    """Minimal in-memory stand-in for PostgREST editor_* tables."""

    def __init__(self):
        self.invites = {}  # code_hash -> invite
        self.marks = {}  # (edition,surah,ayah,token_index,status) -> row
        self.progress = {}
        self.audit = []
        self.calls = []

    def handle(self, method, url, *, params=None, json_body=None, **_kw):
        self.calls.append((method, url, params, json_body))
        path = urlparse(url).path
        table = path.rstrip('/').split('/')[-1]
        params = params or {}

        class Resp:
            def __init__(self, status, payload=None):
                self.status_code = status
                self.content = b'x' if payload is not None else b''
                self._payload = payload
                self.text = json.dumps(payload) if payload is not None else ''

            def json(self):
                return self._payload

        if table == 'editor_invites':
            if method == 'GET':
                code_hash = (params.get('code_hash') or '').replace('eq.', '')
                active = params.get('active', 'eq.true')
                for inv in self.invites.values():
                    if inv['code_hash'] == code_hash and (
                        active != 'eq.true' or inv.get('active')
                    ):
                        return Resp(200, [{
                            'id': inv['id'],
                            'display_name': inv['display_name'],
                            'role': inv['role'],
                            'active': inv['active'],
                        }])
                return Resp(200, [])
            if method == 'PATCH':
                return Resp(204, None)
            if method == 'POST':
                body = json_body or {}
                inv = {
                    'id': body.get('id') or f"inv-{len(self.invites)+1}",
                    'code_hash': body['code_hash'],
                    'display_name': body['display_name'],
                    'role': body.get('role') or 'editor',
                    'active': True,
                }
                self.invites[inv['code_hash']] = inv
                return Resp(201, [inv])

        if table == 'editor_marks':
            if method == 'GET':
                edition = (params.get('edition') or '').replace('eq.', '')
                status = (params.get('status') or '').replace('eq.', '')
                surah = params.get('surah')
                ayah = params.get('ayah')
                out = []
                for key, row in self.marks.items():
                    if edition and row['edition'] != edition:
                        continue
                    if status and row['status'] != status:
                        continue
                    if surah and row['surah'] != int(surah.replace('eq.', '')):
                        continue
                    if ayah and row['ayah'] != int(ayah.replace('eq.', '')):
                        continue
                    out.append(dict(row))
                # single get with token_index
                ti = params.get('token_index')
                if ti:
                    ti_v = int(ti.replace('eq.', ''))
                    out = [r for r in out if r['token_index'] == ti_v]
                return Resp(200, out)
            if method == 'POST':
                body = dict(json_body or {})
                key = (
                    body['edition'], int(body['surah']), int(body['ayah']),
                    int(body['token_index']), body['status'],
                )
                self.marks[key] = body
                return Resp(201, [body])
            if method == 'DELETE':
                edition = params['edition'].replace('eq.', '')
                surah = int(params['surah'].replace('eq.', ''))
                ayah = int(params['ayah'].replace('eq.', ''))
                ti = int(params['token_index'].replace('eq.', ''))
                status = params['status'].replace('eq.', '')
                self.marks.pop((edition, surah, ayah, ti, status), None)
                return Resp(204, None)

        if table == 'editor_progress':
            if method == 'GET':
                edition = (params.get('edition') or '').replace('eq.', '')
                pages = [
                    {'page_number': p}
                    for (ed, p), row in self.progress.items()
                    if ed == edition and row.get('reviewed')
                ]
                return Resp(200, pages)
            if method == 'POST':
                body = json_body or {}
                self.progress[(body['edition'], int(body['page_number']))] = body
                return Resp(201, None)

        if table == 'editor_audit':
            if method == 'POST':
                self.audit.append(json_body or {})
                return Resp(201, None)
            if method == 'GET':
                items = list(reversed(self.audit))
                edition = params.get('edition')
                if edition:
                    ed = edition.replace('eq.', '')
                    items = [a for a in items if a.get('edition') == ed]
                limit = int(params.get('limit') or 30)
                return Resp(200, items[:limit])

        return Resp(404, {'error': f'unknown {table}'})


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-service-role')
    monkeypatch.setenv('EDITOR_SESSION_SECRET', 'test-editor-secret')

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        return fake.handle(method, url, params=params, json_body=json)

    monkeypatch.setattr(sb.requests, 'request', fake_request)
    invalidate_cloud_waqf_cache()
    return fake


def _seed_invite(fake: FakeSupabase, *, name='Helper', role='editor', code='helper-code'):
    h = sb.hash_invite_code(code)
    inv = {
        'id': f'uuid-{role}',
        'code_hash': h,
        'display_name': name,
        'role': role,
        'active': True,
    }
    fake.invites[h] = inv
    return inv, code


def _login(client, code):
    return client.post(
        '/api/mushaf-editor/login',
        json={'code': code},
        content_type='application/json',
    )


def test_spread_requires_auth_when_cloud(client, cloud):
    client.post('/api/mushaf-editor/logout')
    r = client.get('/api/mushaf-editor/spread/1?edition=قطر')
    assert r.status_code == 401
    _seed_invite(cloud, code='x')
    _login(client, 'x')
    r = client.get('/api/mushaf-editor/spread/1?edition=قطر')
    assert r.status_code == 200
    assert r.get_json().get('cloud') is True


def test_auth_status_requires_login_when_cloud(client, cloud):
    client.post('/api/mushaf-editor/logout')
    r = client.get('/api/mushaf-editor/auth/status')
    assert r.status_code == 200
    body = r.get_json()
    assert body['cloud'] is True
    assert body['login_required'] is True
    assert body['authenticated'] is False


def test_login_sets_cookie_and_gates_writes(client, cloud):
    client.post('/api/mushaf-editor/logout')
    _seed_invite(cloud, code='abc-123')
    # Unauthenticated write → 401
    r = client.post(
        '/api/mushaf-editor/waqf',
        json={'word_id': 1, 'edition': 'قطر', 'symbol': 'م'},
        content_type='application/json',
    )
    assert r.status_code == 401
    assert r.get_json().get('login_required') is True

    login = _login(client, 'abc-123')
    assert login.status_code == 200
    assert login.get_json()['user']['name'] == 'Helper'
    assert COOKIE_NAME in login.headers.get('Set-Cookie', '')

    # Bad code
    bad = _login(client, 'wrong')
    assert bad.status_code == 401


def test_draft_write_not_public_until_publish(client, cloud):
    client.post('/api/mushaf-editor/logout')
    inv, code = _seed_invite(cloud, name='Editor', role='editor', code='ed-1')
    admin, admin_code = _seed_invite(cloud, name='Admin', role='admin', code='ad-1')

    # Resolve a real word_id from layout (sura 1 ayah 1 first word)
    from modules.layouts import _get_dk_layout_word_map
    wmap = _get_dk_layout_word_map()
    first = wmap['first_id'][(1, 1)]
    word_id = first

    _login(client, code)
    wr = client.post(
        '/api/mushaf-editor/waqf',
        json={'word_id': word_id, 'edition': 'قطر', 'symbol': 'ج'},
        content_type='application/json',
    )
    assert wr.status_code == 200
    assert wr.get_json()['symbol'] == 'ج'

    # Draft stored
    draft_keys = [k for k in cloud.marks if k[4] == 'draft']
    assert draft_keys
    assert not any(k[4] == 'published' for k in cloud.marks)

    # Public fetch must not see draft
    invalidate_cloud_waqf_cache('قطر', 1, 1)
    public = _fetch_single_mushaf_waqf(1, 1, 'قطر')
    assert public == []

    # Editor publish requires admin
    pub = client.post(
        '/api/mushaf-editor/publish',
        json={'edition': 'قطر'},
        content_type='application/json',
    )
    assert pub.status_code == 403

    client.post('/api/mushaf-editor/logout')
    _login(client, admin_code)
    pub = client.post(
        '/api/mushaf-editor/publish',
        json={'edition': 'قطر'},
        content_type='application/json',
    )
    assert pub.status_code == 200
    assert pub.get_json()['published'] >= 1
    assert any(k[4] == 'published' for k in cloud.marks)

    invalidate_cloud_waqf_cache('قطر', 1, 1)
    public = _fetch_single_mushaf_waqf(1, 1, 'قطر')
    assert any(r.get('symbols') == 'ج' for r in public)

def test_editor_ui_has_login_and_publish(client):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    page = (root / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    script = (root / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    assert 'id="ed-login"' in page
    assert 'id="ed-publish"' in page
    assert 'id="ed-audit"' in page
    assert '/api/mushaf-editor/login' in script
    assert '/api/mushaf-editor/publish' in script
