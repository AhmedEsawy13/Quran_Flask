"""Security and robustness checks for the hand-labeling editor UI."""
from __future__ import annotations

import json
from pathlib import Path

from core import supabase_editor as sb
from modules import cv_waqf_ui
from pipeline.cv_waqf import sync_supabase


def test_cv_waqf_cloud_apis_require_editor_session(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: True)
    client = app.test_client()

    assert client.get('/cv-waqf').status_code == 200
    assert client.get(
        '/api/cv-waqf/labels?edition=الشمرلي&page=2'
    ).status_code == 401
    assert client.get('/api/cv-waqf/image/shamarly/2.jpg').status_code == 401
    assert client.get('/api/cv-waqf/page/2?edition=الشمرلي').status_code == 401
    assert client.post('/api/cv-waqf/labels', json={}).status_code == 401
    assert client.delete('/api/cv-waqf/labels/shamarly-p002-test').status_code == 401

    js = Path('static/js/cv_waqf.js').read_text(encoding='utf-8')
    assert '/api/mushaf-editor/auth/status' in js
    assert 'يلزم تسجيل الدخول' in js


def test_cv_waqf_live_routes_are_never_browser_cached(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    client = app.test_client()

    page = client.get('/cv-waqf')
    labels = client.get('/api/cv-waqf/labels?edition=الشمرلي&page=2')

    assert page.status_code == 200
    assert labels.status_code == 200
    assert page.headers['Cache-Control'] == 'no-store, max-age=0'
    assert labels.headers['Cache-Control'] == 'no-store, max-age=0'


def test_cv_waqf_ignores_a_malformed_local_label(tmp_path, monkeypatch):
    monkeypatch.setattr(cv_waqf_ui, 'HAND_ROOT', tmp_path)
    path = tmp_path / 'shamarly' / 'labels.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({'id': 'bad', 'page': 'not-a-page'}) + '\n'
        + json.dumps({'id': 'good', 'page': 2, 'symbol': 'ج'}) + '\n',
        encoding='utf-8',
    )

    assert [row['id'] for row in cv_waqf_ui._load_local_labels('shamarly')] == ['good']


def test_cv_waqf_rejects_unknown_gallery_slug(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    client = app.test_client()

    assert client.get('/cv-waqf/labels/not-an-edition').status_code == 404
    assert client.get('/cv-waqf/crops/not-an-edition').status_code == 404
    assert client.get(
        '/cv-waqf/labels-assets/not-an-edition/example.png'
    ).status_code == 404


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = [] if payload is None else payload
        self.text = ''

    def json(self):
        return self._payload


def test_cv_sync_status_bucket_probe_is_read_only(monkeypatch):
    calls = []

    def fake_storage(path, *, method='GET', **_kwargs):
        calls.append((path, method))
        return _Response(payload=[{'id': sync_supabase.BUCKET}])

    monkeypatch.setattr(sync_supabase, '_storage', fake_storage)
    sync_supabase.require_bucket()

    assert calls == [('bucket', 'GET')]


def test_cv_storage_root_listing_is_not_requested_twice(monkeypatch):
    calls = []

    def fake_storage(path, *, method='GET', **_kwargs):
        calls.append((path, method))
        return _Response(payload=[])

    monkeypatch.setattr(sync_supabase, '_storage', fake_storage)

    assert sync_supabase.list_objects('') == []
    assert calls == [(f'object/list/{sync_supabase.BUCKET}', 'POST')]
