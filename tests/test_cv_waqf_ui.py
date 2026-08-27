"""Security and robustness checks for the hand-labeling editor UI."""
from __future__ import annotations

import json
from pathlib import Path

from core import supabase_editor as sb
from modules import cv_waqf_ui
from pipeline.cv_waqf import sync_supabase


def test_cv_waqf_cloud_apis_require_editor_session(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: True)
    monkeypatch.setenv(
        'EDITOR_SESSION_SECRET',
        'test-editor-session-secret-at-least-32-chars',
    )
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
    assert '/api/mushaf-editor/login' in js
    assert 'يلزم تسجيل الدخول' in js
    assert 'QUICK_BOX_SIZE = 32' in js
    assert 'suggestNearestWord()' in js
    assert 'review_marks' in js

    html = client.get('/cv-waqf').get_data(as_text=True)
    assert 'cvw-login-form' in html
    assert 'تسجيل دخول المراجع' in html
    assert 'انقر على العلامة' in html
    assert 'cvw-show-review' in html

    css = Path('static/css/cv_waqf.css').read_text(encoding='utf-8')
    assert '.cvw-body [hidden]' in css
    assert '@media (min-width: 560px)' in css
    assert '.tag.review' in css


def test_cv_waqf_live_routes_are_never_browser_cached(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    # Match CI: no OpenCV in the Flask env and no .venv-cv.
    monkeypatch.setattr(cv_waqf_ui, 'CV_VENV_PYTHON', Path('/nonexistent/.venv-cv/bin/python'))
    client = app.test_client()

    page = client.get('/cv-waqf')
    labels = client.get('/api/cv-waqf/labels?edition=الشمرلي&page=2')

    assert page.status_code == 200
    assert labels.status_code == 200
    assert page.headers['Cache-Control'] == 'no-store, max-age=0'
    assert labels.headers['Cache-Control'] == 'no-store, max-age=0'
    first_word = labels.get_json()['words'][0]
    assert first_word['word_key'].count(':') == 2
    assert first_word['word_id_space'] == 'quran-script-stable-v1'


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


def test_cv_hand_label_requires_and_persists_canonical_word_anchor(
    app, tmp_path, monkeypatch,
):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    monkeypatch.setattr(cv_waqf_ui, 'ROOT', tmp_path)
    monkeypatch.setattr(
        cv_waqf_ui, 'HAND_ROOT', tmp_path / 'data' / 'cv' / 'crops_hand',
    )
    monkeypatch.setattr(
        cv_waqf_ui,
        '_build_word_payload',
        lambda *_args: {
            'words': [{
                'word_id': 77,
                'word_key': '2:2:1',
                'word_id_space': 'quran-script-stable-v1',
                'surah': 2,
                'ayah': 2,
                'text': 'ذَٰلِكَ',
                'line': 1,
            }],
        },
    )

    def fake_crop(slug, label):
        path = cv_waqf_ui.HAND_ROOT / slug / 'j' / f"{label['id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'png')
        return path

    monkeypatch.setattr(cv_waqf_ui, '_save_crop_png', fake_crop)
    monkeypatch.setattr(cv_waqf_ui, '_ensure_image', lambda *_args: tmp_path)
    client = app.test_client()
    base = {
        'edition': 'الشمرلي', 'page': 2, 'symbol': 'ج',
        'box': [10, 10, 30, 30],
    }

    assert client.post('/api/cv-waqf/labels', json=base).status_code == 400
    response = client.post(
        '/api/cv-waqf/labels', json={**base, 'word_key': '2:2:1'},
    )

    assert response.status_code == 200
    label = response.get_json()['label']
    assert label['word_key'] == '2:2:1'
    assert label['local_word_id'] == 77
    assert label['word_id_space'] == 'quran-script-stable-v1'
    assert label['attachment_status'] == 'reviewer-confirmed'


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


def test_cv_review_queue_has_live_label_counts(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    monkeypatch.setattr(
        cv_waqf_ui,
        '_load_labels',
        lambda slug, page=None: [
            {'page': 1, 'symbol': 'ج'},
            {'page': 1, 'symbol': 'none'},
        ] if slug == 'bahrain' else [],
    )
    client = app.test_client()
    response = client.get('/api/cv-waqf/review-queue?edition=البحرين')

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload['pages']) == 43
    assert payload['targeted_size'] == 13
    assert [row['page'] for row in payload['pages'][:3]] == [17, 18, 33]
    assert any(
        row['page'] == 437 and row.get('priority')
        for row in payload['pages']
    )
    page_one = next(row for row in payload['pages'] if row['page'] == 1)
    assert page_one['label_count'] == 2
    assert payload['total_labels'] == 2
