"""Cloud mushaf-editor: invite auth, draft vs published, mock Supabase HTTP."""
from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from core import supabase_editor as sb
from core.mushaf_waqf import invalidate_cloud_waqf_cache, _fetch_single_mushaf_waqf
from modules.editor_auth import COOKIE_NAME, invalidate_editor_session_cache


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


class FakeSupabase:
    """Minimal in-memory stand-in for PostgREST editor_* tables."""

    def __init__(self):
        self.invites = {}  # id -> invite
        self.marks = {}  # (edition,surah,ayah,token_index,status) -> row
        self.progress = {}
        self.audit = []
        self.calls = []
        self.fail_atomic_publish = False

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

        if table == 'publish_editor_edition' and method == 'POST':
            body = json_body or {}
            edition = body.get('p_edition')
            changes = []
            for key, draft in self.marks.items():
                if key[0] != edition or key[4] != 'draft':
                    continue
                published = self.marks.get((key[0], key[1], key[2], key[3], 'published'))
                old_symbol = ((published or {}).get('symbol') or '').strip()
                new_symbol = (draft.get('symbol') or '').strip()
                if old_symbol == new_symbol:
                    continue
                changes.append({
                    'surah': int(key[1]),
                    'ayah': int(key[2]),
                    'token_index': int(key[3]),
                    'old_symbol': old_symbol,
                    'new_symbol': new_symbol,
                })
            changes.sort(key=lambda c: (c['surah'], c['ayah'], c['token_index']))
            if body.get('p_expected_changes') != changes:
                return Resp(400, {
                    'code': '40001',
                    'message': 'publish snapshot changed; refresh pending changes',
                })

            # Work against copies, as PostgreSQL would, so an error cannot leave
            # a partially published edition or audit event behind.
            next_marks = {key: dict(row) for key, row in self.marks.items()}
            next_audit = list(self.audit)
            for change in changes:
                key = (
                    edition, change['surah'], change['ayah'],
                    change['token_index'], 'published',
                )
                draft = self.marks[(
                    edition, change['surah'], change['ayah'],
                    change['token_index'], 'draft',
                )]
                if not change['new_symbol']:
                    next_marks.pop(key, None)
                else:
                    next_marks[key] = {
                        'edition': edition,
                        'surah': change['surah'],
                        'ayah': change['ayah'],
                        'token_index': change['token_index'],
                        'status': 'published',
                        'symbol': change['new_symbol'],
                        'word_text': draft.get('word_text'),
                        'updated_by': body.get('p_actor_id'),
                    }
            next_audit.append({
                'actor_id': body.get('p_actor_id'),
                'actor_name': body.get('p_actor_name'),
                'action': 'publish',
                'edition': edition,
                'meta': {'count': len(changes), 'changes': changes},
            })
            if self.fail_atomic_publish:
                return Resp(500, {'message': 'simulated transaction failure'})
            self.marks = next_marks
            self.audit = next_audit
            return Resp(200, {
                'edition': edition,
                'published': len(changes),
                'changes': changes,
            })

        if table == 'editor_invites':
            if method == 'GET':
                code_hash = (params.get('code_hash') or '').replace('eq.', '')
                username = (params.get('username') or '').replace('eq.', '').lower()
                invite_id = (params.get('id') or '').replace('eq.', '')
                active = params.get('active', 'eq.true')
                if invite_id:
                    out = [
                        {
                            'id': inv['id'],
                            'display_name': inv['display_name'],
                            'role': inv['role'],
                            'active': inv.get('active', True),
                            'username': inv.get('username') or '',
                        }
                        for inv in self.invites.values()
                        if inv['id'] == invite_id and (
                            active != 'eq.true' or inv.get('active', True)
                        )
                    ]
                    return Resp(200, out[:1])
                if username:
                    for inv in self.invites.values():
                        if (inv.get('username') or '').lower() == username and (
                            active != 'eq.true' or inv.get('active', True)
                        ):
                            return Resp(200, [{
                                'id': inv['id'],
                                'display_name': inv['display_name'],
                                'role': inv['role'],
                                'active': inv['active'],
                                'username': inv.get('username') or '',
                                'password_hash': inv.get('password_hash'),
                            }])
                    return Resp(200, [])
                if code_hash:
                    for inv in self.invites.values():
                        if inv.get('code_hash') == code_hash and (
                            active != 'eq.true' or inv.get('active')
                        ):
                            return Resp(200, [{
                                'id': inv['id'],
                                'display_name': inv['display_name'],
                                'role': inv['role'],
                                'active': inv['active'],
                                'username': inv.get('username') or '',
                            }])
                    return Resp(200, [])
                # list all
                out = []
                for inv in self.invites.values():
                    out.append({
                        'id': inv['id'],
                        'display_name': inv['display_name'],
                        'role': inv['role'],
                        'active': inv.get('active', True),
                        'username': inv.get('username') or '',
                        'created_at': inv.get('created_at'),
                        'last_used_at': inv.get('last_used_at'),
                    })
                return Resp(200, out)
            if method == 'PATCH':
                invite_id = (params.get('id') or '').replace('eq.', '')
                display_name = (params.get('display_name') or '').replace('eq.', '')
                body = json_body or {}
                for inv in self.invites.values():
                    match = (
                        (invite_id and inv['id'] == invite_id)
                        or (display_name and inv['display_name'] == display_name)
                    )
                    if not match:
                        continue
                    if 'active' in body:
                        inv['active'] = bool(body['active'])
                    if 'last_used_at' in body:
                        inv['last_used_at'] = body['last_used_at']
                    if 'username' in body:
                        inv['username'] = body['username']
                    if 'password_hash' in body:
                        inv['password_hash'] = body['password_hash']
                    return Resp(200, [{
                        'id': inv['id'],
                        'display_name': inv['display_name'],
                        'role': inv['role'],
                        'active': inv.get('active', True),
                        'username': inv.get('username') or '',
                    }])
                return Resp(200, [])
            if method == 'POST':
                body = json_body or {}
                uname = (body.get('username') or '').lower()
                if uname and any(
                    (inv.get('username') or '').lower() == uname
                    for inv in self.invites.values()
                ):
                    return Resp(409, {'code': '23505', 'message': 'duplicate username'})
                inv = {
                    'id': body.get('id') or f"inv-{len(self.invites)+1}",
                    'code_hash': body.get('code_hash'),
                    'username': uname,
                    'password_hash': body.get('password_hash'),
                    'display_name': body['display_name'],
                    'role': body.get('role') or 'editor',
                    'active': True,
                    'created_at': '2026-01-01T00:00:00Z',
                }
                self.invites[inv['id']] = inv
                return Resp(201, [inv])

        if table == 'editor_marks':
            if method == 'GET':
                edition = (params.get('edition') or '').replace('eq.', '')
                status_raw = params.get('status') or ''
                status_set = None
                status = None
                if status_raw.startswith('in.(') and status_raw.endswith(')'):
                    status_set = {
                        part.strip()
                        for part in status_raw[4:-1].split(',')
                        if part.strip()
                    }
                elif status_raw.startswith('eq.'):
                    status = status_raw.replace('eq.', '')
                surah = params.get('surah')
                ayah = params.get('ayah')
                or_filter = params.get('or') or ''
                ayah_pairs = None
                if or_filter.startswith('(') and or_filter.endswith(')'):
                    import re
                    ayah_pairs = {
                        (int(s), int(a))
                        for s, a in re.findall(r'surah\.eq\.(\d+),ayah\.eq\.(\d+)', or_filter)
                    }
                out = []
                for key, row in self.marks.items():
                    if edition and row['edition'] != edition:
                        continue
                    if status_set is not None:
                        if row['status'] not in status_set:
                            continue
                    elif status and row['status'] != status:
                        continue
                    if ayah_pairs is not None:
                        if (int(row['surah']), int(row['ayah'])) not in ayah_pairs:
                            continue
                    else:
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
                out.sort(key=lambda r: (r['surah'], r['ayah'], r['token_index']))
                limit = params.get('limit')
                offset = int(params.get('offset') or 0)
                if limit is not None:
                    out = out[offset:offset + int(limit)]
                elif offset:
                    out = out[offset:]
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
                body = dict(json_body or {})
                body.setdefault('id', len(self.audit) + 1)
                seq = len(self.audit)
                body.setdefault(
                    'at',
                    f'2026-07-30T12:{seq // 60:02d}:{seq % 60:02d}Z',
                )
                self.audit.append(body)
                return Resp(201, None)
            if method == 'GET':
                items = list(reversed(self.audit))
                edition = params.get('edition')
                if edition:
                    ed = edition.replace('eq.', '')
                    items = [a for a in items if a.get('edition') == ed]
                action = params.get('action')
                if action:
                    act = action.replace('eq.', '')
                    items = [a for a in items if a.get('action') == act]
                actor = params.get('actor_id')
                if actor:
                    aid = actor.replace('eq.', '')
                    items = [a for a in items if a.get('actor_id') == aid]
                cursor = params.get('or')
                if cursor:
                    prefix = '(at.lt.'
                    middle = ',and(at.eq.'
                    suffix = ',id.lt.'
                    assert cursor.startswith(prefix) and cursor.endswith('))')
                    before_at, rest = cursor[len(prefix):].split(middle, 1)
                    same_at, before_id = rest[:-2].split(suffix, 1)
                    assert same_at == before_at
                    bid = int(before_id)
                    items = [
                        row for row in items
                        if (
                            row.get('at', '') < before_at
                            or (
                                row.get('at', '') == before_at
                                and int(row.get('id') or 0) < bid
                            )
                        )
                    ]
                limit = int(params.get('limit') or 30)
                return Resp(200, items[:limit])

        return Resp(404, {'error': f'unknown {table}'})


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-service-role')
    monkeypatch.setenv('EDITOR_SESSION_SECRET', 'test-editor-secret-at-least-32-chars')

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        return fake.handle(method, url, params=params, json_body=json)

    monkeypatch.setattr(sb.requests, 'request', fake_request)
    invalidate_cloud_waqf_cache()
    sb.invalidate_mark_cache()
    invalidate_editor_session_cache()
    return fake


def _seed_invite(fake: FakeSupabase, *, name='Helper', role='editor',
                 username=None, password='password1'):
    uname = (username or f'{role}_user').lower()
    inv = {
        'id': f'uuid-{role}-{uname}',
        'username': uname,
        'password_hash': sb.hash_password(password),
        'display_name': name,
        'role': role,
        'active': True,
    }
    fake.invites[inv['id']] = inv
    return inv, uname, password


def _login(client, username, password='password1'):
    return client.post(
        '/api/mushaf-editor/login',
        json={'username': username, 'password': password},
        content_type='application/json',
    )


def _pending_snapshot(client, edition='قطر'):
    response = client.get(f'/api/mushaf-editor/pending?edition={edition}')
    assert response.status_code == 200
    return response.get_json()['publish_snapshot']


def test_spread_requires_auth_when_cloud(client, cloud):
    client.post('/api/mushaf-editor/logout')
    r = client.get('/api/mushaf-editor/spread/1?edition=قطر')
    assert r.status_code == 401
    _seed_invite(cloud, username='x')
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


def test_cloud_auth_rejects_missing_or_weak_session_secret(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: True)
    monkeypatch.delenv('EDITOR_SESSION_SECRET', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'generic-flask-secret-does-not-count')
    isolated = app.test_client()

    missing = isolated.get('/api/mushaf-editor/auth/status')
    assert missing.status_code == 503
    assert missing.get_json()['auth_available'] is False
    assert missing.headers['Cache-Control'] == 'no-store, max-age=0'

    monkeypatch.setenv('EDITOR_SESSION_SECRET', 'too-short')
    weak = isolated.post('/api/mushaf-editor/login', json={})
    assert weak.status_code == 503
    assert weak.get_json()['error'] == 'auth service unavailable'

    monkeypatch.setenv(
        'EDITOR_SESSION_SECRET',
        'dedicated-editor-session-secret-32-chars',
    )
    ready = isolated.get('/api/mushaf-editor/auth/status')
    assert ready.status_code == 200
    assert ready.get_json()['auth_available'] is True


def test_login_sets_cookie_and_gates_writes(client, cloud):
    client.post('/api/mushaf-editor/logout')
    _seed_invite(cloud, username='abc-123')
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

    # Bad credentials
    bad = _login(client, 'wrong')
    assert bad.status_code == 401
    assert bad.get_json().get('error') == 'invalid credentials'


def test_draft_write_not_public_until_publish(client, cloud):
    client.post('/api/mushaf-editor/logout')
    inv, username, _pwd = _seed_invite(cloud, name='Editor', role='editor', username='ed-1')
    admin, admin_user, _ap = _seed_invite(cloud, name='Admin', role='admin', username='ad-1')

    # Resolve a real word_id from layout (sura 1 ayah 1 first word)
    from modules.layouts import _get_dk_layout_word_map
    wmap = _get_dk_layout_word_map()
    first = wmap['first_id'][(1, 1)]
    word_id = first

    _login(client, username)
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
    _login(client, admin_user)
    snapshot = _pending_snapshot(client)
    calls_before = len(cloud.calls)
    pub = client.post(
        '/api/mushaf-editor/publish',
        json={'edition': 'قطر', 'expected_changes': snapshot},
        content_type='application/json',
    )
    assert pub.status_code == 200
    assert pub.get_json()['published'] >= 1
    assert any(k[4] == 'published' for k in cloud.marks)
    publish_calls = cloud.calls[calls_before:]
    assert len(publish_calls) == 1
    assert '/rpc/publish_editor_edition' in publish_calls[0][1]

    invalidate_cloud_waqf_cache('قطر', 1, 1)
    public = _fetch_single_mushaf_waqf(1, 1, 'قطر')
    assert any(r.get('symbols') == 'ج' for r in public)


def test_clear_published_mark_creates_draft_tombstone(client, cloud):
    """Clearing a published mark must survive reload and publish as deletion."""
    client.post('/api/mushaf-editor/logout')
    _inv, username, _pwd = _seed_invite(cloud, name='Editor', role='editor', username='clear-ed')
    _admin, admin_user, _ap = _seed_invite(cloud, name='Admin', role='admin', username='clear-admin')

    from modules.layouts import _get_dk_layout_word_map
    wmap = _get_dk_layout_word_map()
    word_id = wmap['first_id'][(1, 1)]
    cloud.marks[('قطر', 1, 1, 0, 'published')] = {
        'edition': 'قطر', 'surah': 1, 'ayah': 1, 'token_index': 0,
        'status': 'published', 'symbol': 'ج', 'word_text': 'بِسْمِ',
    }

    _login(client, username)
    cleared = client.post(
        '/api/mushaf-editor/waqf',
        json={'word_id': word_id, 'edition': 'قطر', 'symbol': ''},
        content_type='application/json',
    )
    assert cleared.status_code == 200
    tombstone = cloud.marks[('قطر', 1, 1, 0, 'draft')]
    assert tombstone['symbol'] == ''
    diff = sb.pending_publish_diff('قطر')
    assert len(diff) == 1 and diff[0]['old_symbol'] == 'ج' and diff[0]['new_symbol'] == ''

    client.post('/api/mushaf-editor/logout')
    _login(client, admin_user)
    snapshot = _pending_snapshot(client)
    published = client.post(
        '/api/mushaf-editor/publish',
        json={'edition': 'قطر', 'expected_changes': snapshot},
    )
    assert published.status_code == 200
    assert ('قطر', 1, 1, 0, 'published') not in cloud.marks


def test_transient_cloud_read_failure_is_not_cached(cloud, monkeypatch):
    invalidate_cloud_waqf_cache('قطر', 1, 1)
    real_fetch = sb.fetch_marks

    def fail_once(**_kwargs):
        raise sb.SupabaseEditorError('temporary outage')

    monkeypatch.setattr(sb, 'fetch_marks', fail_once)
    assert _fetch_single_mushaf_waqf(1, 1, 'قطر') == []

    cloud.marks[('قطر', 1, 1, 0, 'published')] = {
        'edition': 'قطر', 'surah': 1, 'ayah': 1, 'token_index': 0,
        'status': 'published', 'symbol': 'م', 'word_text': 'بِسْمِ',
    }
    monkeypatch.setattr(sb, 'fetch_marks', real_fetch)
    recovered = _fetch_single_mushaf_waqf(1, 1, 'قطر')
    assert [row['symbols'] for row in recovered] == ['م']

def test_editor_ui_has_login_and_publish(client):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    page = (root / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    script = (root / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    css = (root / 'static/css/mushaf_editor.css').read_text(encoding='utf-8')
    assert 'id="ed-login"' in page
    assert 'id="ed-login-username"' in page
    assert 'id="ed-login-password"' in page
    assert 'id="ed-publish"' in page
    assert 'id="ed-pending-panel"' in page
    assert 'id="ed-pending-backdrop"' in page
    assert 'id="ed-pending-dismiss"' in page
    assert 'id="ed-invites-panel"' in page
    assert 'id="ed-audit"' in page
    assert '/api/mushaf-editor/login' in script
    assert '/api/mushaf-editor/publish' in script
    assert '/api/mushaf-editor/pending' in script
    assert '/api/mushaf-editor/invites' in script
    assert 'jumpToPendingChange' in script
    assert 'المنشور' in script
    assert 'ed-pending-prev' in page
    assert 'ed-pending-next' in page
    assert 'ed-pending-drawer' in page
    assert 'ed-drafts-open' in page
    assert 'loadPendingPages' in script
    assert 'goToDraftPage' in script
    assert 'ed-pending-focus' in css
    assert 'ed-pending-drawer' in css
    assert 'ed-drafts-panel' in css
    assert 'اعتماد ونشر' in script


def test_pending_api_includes_pages_summary(client, cloud):
    """Pending endpoint groups changes by mushaf page for draft navigation."""
    from modules.editor_auth import COOKIE_NAME
    inv, username, _pwd = _seed_invite(cloud, name='Nav', role='editor', username='nav-1')
    cloud.marks[('قطر', 2, 2, 0, 'draft')] = {
        'edition': 'قطر', 'surah': 2, 'ayah': 2, 'token_index': 0,
        'status': 'draft', 'symbol': 'ج', 'word_text': 'ذَٰلِكَ',
    }
    _login(client, username)
    r = client.get('/api/mushaf-editor/pending?edition=قطر')
    assert r.status_code == 200
    body = r.get_json()
    assert body['count'] >= 1
    assert body['page_count'] >= 1
    assert isinstance(body.get('pages'), list)
    assert body['pages'][0]['page_number'] >= 1
    assert body['pages'][0]['count'] >= 1
    assert body['publish_snapshot'] == [{
        'surah': 2,
        'ayah': 2,
        'token_index': 0,
        'old_symbol': '',
        'new_symbol': 'ج',
    }]
    assert COOKIE_NAME  # keep import used / session cookie path exercised


def test_publish_rejects_stale_review_snapshot(client, cloud):
    """A draft edit after review must abort without changing published rows."""
    _seed_invite(cloud, name='Admin', role='admin', username='stale-admin')
    cloud.marks[('قطر', 2, 2, 0, 'published')] = {
        'edition': 'قطر', 'surah': 2, 'ayah': 2, 'token_index': 0,
        'status': 'published', 'symbol': 'ج', 'word_text': 'ذَٰلِكَ',
    }
    cloud.marks[('قطر', 2, 2, 0, 'draft')] = {
        'edition': 'قطر', 'surah': 2, 'ayah': 2, 'token_index': 0,
        'status': 'draft', 'symbol': 'ص', 'word_text': 'ذَٰلِكَ',
    }
    _login(client, 'stale-admin')
    reviewed = _pending_snapshot(client)

    cloud.marks[('قطر', 2, 2, 0, 'draft')]['symbol'] = 'ق'
    response = client.post('/api/mushaf-editor/publish', json={
        'edition': 'قطر',
        'expected_changes': reviewed,
    })

    assert response.status_code == 409
    assert response.get_json()['refresh_required'] is True
    assert cloud.marks[('قطر', 2, 2, 0, 'published')]['symbol'] == 'ج'
    assert not any(item.get('action') == 'publish' for item in cloud.audit)


def test_atomic_publish_failure_rolls_back_every_change(client, cloud):
    """An RPC error cannot expose a prefix of the reviewed changes."""
    _seed_invite(cloud, name='Admin', role='admin', username='rollback-admin')
    for token_index, symbol in ((0, 'ج'), (1, 'ص')):
        cloud.marks[('قطر', 2, 2, token_index, 'draft')] = {
            'edition': 'قطر', 'surah': 2, 'ayah': 2,
            'token_index': token_index, 'status': 'draft',
            'symbol': symbol, 'word_text': f'w{token_index}',
        }
    _login(client, 'rollback-admin')
    reviewed = _pending_snapshot(client)
    marks_before = {key: dict(row) for key, row in cloud.marks.items()}
    audit_before = list(cloud.audit)
    cloud.fail_atomic_publish = True

    response = client.post('/api/mushaf-editor/publish', json={
        'edition': 'قطر',
        'expected_changes': reviewed,
    })

    assert response.status_code == 503
    assert cloud.marks == marks_before
    assert cloud.audit == audit_before
    assert not any(key[4] == 'published' for key in cloud.marks)


def test_publish_requires_review_snapshot(client, cloud):
    _seed_invite(cloud, name='Admin', role='admin', username='snapshot-admin')
    _login(client, 'snapshot-admin')
    response = client.post('/api/mushaf-editor/publish', json={'edition': 'قطر'})
    assert response.status_code == 400
    assert response.get_json()['error'] == 'expected_changes is required'


def test_schema_installs_service_role_only_atomic_publish_rpc():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for sql_path in (
        root / 'pipeline' / 'supabase_editor_schema.sql',
        root / 'pipeline' / 'supabase_atomic_publish.sql',
    ):
        sql = sql_path.read_text(encoding='utf-8').lower()
        assert 'function public.publish_editor_edition' in sql
        assert 'lock table public.editor_marks in share row exclusive mode' in sql
        assert "errcode = '40001'" in sql
        assert 'revoke all on function public.publish_editor_edition' in sql
        assert 'to service_role' in sql


def test_supabase_schema_readiness_is_versioned_and_service_role_only():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sql = (
        root / 'pipeline' / 'supabase_schema_readiness.sql'
    ).read_text(encoding='utf-8').lower()
    assert 'create table if not exists public.athar_schema_versions' in sql
    assert "('editor', 4, now())" in sql
    assert "('layout', 2, now())" in sql
    assert 'greatest(athar_schema_versions.version, excluded.version)' in sql
    assert 'enable row level security' in sql
    assert 'revoke all' in sql
    assert 'grant select' in sql and 'to service_role' in sql


def test_activity_audit_migration_bumps_editor_schema_without_downgrades():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sql = (
        root / 'pipeline' / 'supabase_editor_audit_actions.sql'
    ).read_text(encoding='utf-8').lower()
    assert 'editor_audit_action_check' in sql
    assert "values ('editor', 4, now())" in sql
    assert 'greatest(athar_schema_versions.version, excluded.version)' in sql
    assert 'editor_audit_actor_at_idx' in sql
    assert 'editor_audit_action_at_idx' in sql


def test_pending_publish_diff_keeps_published_old_symbol(cloud):
    """Drafts mid-mushaf must compare against published even past the 1000-row page."""
    # Seed many early published rows + the real published mark for 33:36.
    for i in range(5):
        cloud.marks[('قطر', 1, i + 1, 0, 'published')] = {
            'edition': 'قطر', 'surah': 1, 'ayah': i + 1, 'token_index': 0,
            'status': 'published', 'symbol': 'ج', 'word_text': 'x',
        }
    cloud.marks[('قطر', 33, 36, 15, 'published')] = {
        'edition': 'قطر', 'surah': 33, 'ayah': 36, 'token_index': 15,
        'status': 'published', 'symbol': 'ق', 'word_text': 'أَمْرِهِمْۗ',
    }
    cloud.marks[('قطر', 33, 36, 15, 'draft')] = {
        'edition': 'قطر', 'surah': 33, 'ayah': 36, 'token_index': 15,
        'status': 'draft', 'symbol': 'ق', 'word_text': 'أَمْرِهِمْۗ',
    }
    cloud.marks[('قطر', 33, 37, 12, 'draft')] = {
        'edition': 'قطر', 'surah': 33, 'ayah': 37, 'token_index': 12,
        'status': 'draft', 'symbol': 'ص', 'word_text': 'ٱللَّهَ',
    }

    changes = sb.pending_publish_diff('قطر')
    assert len(changes) == 1
    assert changes[0]['surah'] == 33 and changes[0]['ayah'] == 37
    assert changes[0]['old_symbol'] == ''
    assert changes[0]['new_symbol'] == 'ص'


def test_fetch_draft_and_published_combined(cloud):
    sb.invalidate_mark_cache()
    cloud.marks[('قطر', 2, 2, 0, 'draft')] = {
        'edition': 'قطر', 'surah': 2, 'ayah': 2, 'token_index': 0,
        'status': 'draft', 'symbol': 'ج', 'word_text': 'a',
    }
    cloud.marks[('قطر', 2, 2, 0, 'published')] = {
        'edition': 'قطر', 'surah': 2, 'ayah': 2, 'token_index': 0,
        'status': 'published', 'symbol': 'ص', 'word_text': 'a',
    }
    drafts, published = sb.fetch_draft_and_published_for_ayahs(
        edition='قطر', ayah_keys=[(2, 2)],
    )
    assert len(drafts) == 1 and drafts[0]['symbol'] == 'ج'
    assert len(published) == 1 and published[0]['symbol'] == 'ص'
    # Second call should hit cache (no extra HTTP needed for same ayah).
    before = len(cloud.calls)
    drafts2, published2 = sb.fetch_draft_and_published_for_ayahs(
        edition='قطر', ayah_keys=[(2, 2)],
    )
    assert len(cloud.calls) == before
    assert drafts2[0]['symbol'] == 'ج' and published2[0]['symbol'] == 'ص'

def test_admin_can_create_and_revoke_invite(client, cloud):
    client.post('/api/mushaf-editor/logout')
    _seed_invite(cloud, name='Admin', role='admin', username='ad-inv')
    _seed_invite(cloud, name='Helper', role='editor', username='ed-inv')

    # Editor cannot create
    _login(client, 'ed-inv')
    denied = client.post(
        '/api/mushaf-editor/invites',
        json={'name': 'Someone', 'role': 'editor', 'username': 'someone'},
        content_type='application/json',
    )
    assert denied.status_code == 403

    client.post('/api/mushaf-editor/logout')
    _login(client, 'ad-inv')
    created = client.post(
        '/api/mushaf-editor/invites',
        json={
            'name': 'Fatima',
            'role': 'editor',
            'username': 'fatima',
            'password': 'fatima-pass-9',
        },
        content_type='application/json',
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body['username'] == 'fatima'
    assert body['password'] == 'fatima-pass-9'
    assert body['invite']['name'] == 'Fatima'
    invite_id = body['invite']['id']

    listed = client.get('/api/mushaf-editor/invites')
    assert listed.status_code == 200
    names = {i['name'] for i in listed.get_json()['invites']}
    assert 'Fatima' in names
    usernames = {i['username'] for i in listed.get_json()['invites']}
    assert 'fatima' in usernames

    # New account works; logout + re-login also works
    client.post('/api/mushaf-editor/logout')
    ok = _login(client, 'fatima', 'fatima-pass-9')
    assert ok.status_code == 200
    client.post('/api/mushaf-editor/logout')
    again = _login(client, 'Fatima', 'fatima-pass-9')  # case-insensitive username
    assert again.status_code == 200

    client.post('/api/mushaf-editor/logout')
    _login(client, 'ad-inv')
    revoked = client.patch(
        f'/api/mushaf-editor/invites/{invite_id}',
        json={'active': False},
        content_type='application/json',
    )
    assert revoked.status_code == 200
    assert revoked.get_json()['invite']['active'] is False

    client.post('/api/mushaf-editor/logout')
    blocked = _login(client, 'fatima', 'fatima-pass-9')
    assert blocked.status_code == 401


def test_revocation_invalidates_an_existing_session(client, cloud):
    client.post('/api/mushaf-editor/logout')
    _seed_invite(cloud, name='Admin', role='admin', username='live-admin')
    invite, helper_user, _hp = _seed_invite(cloud, name='Helper', role='editor', username='live-helper')
    helper_client = client.application.test_client()
    assert _login(helper_client, helper_user).status_code == 200

    assert _login(client, 'live-admin').status_code == 200
    revoked = client.patch(
        f"/api/mushaf-editor/invites/{invite['id']}",
        json={'active': False},
        content_type='application/json',
    )
    assert revoked.status_code == 200
    denied = helper_client.get('/api/mushaf-editor/spread/1?edition=قطر')
    assert denied.status_code == 401
