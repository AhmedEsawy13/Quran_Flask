"""Editor review UI for contemporary توجيه (not a classical book)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from core.config import CLASSICAL_WAQF_DATABASE
from core.tawjih import _shape_review_item, verse_words
from tests.test_tawjih import (
    UNIQUE_AYAH,
    UNIQUE_QUOTE,
    UNIQUE_SURAH,
    _published_fixture,
    _write_fixture,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _three_row_db(tmp_path, monkeypatch):
    db = tmp_path / 'tawjih.db'
    _write_fixture(db, [
        _published_fixture(),
        _published_fixture(
            tweet_id='fixture-review',
            status='review',
            align_conf=0,
            grade='كاف',
            surah=None,
            ayah=None,
            wpos=None,
            quote=None,
        ),
        _published_fixture(
            tweet_id='fixture-skipped',
            status='skipped',
            align_conf=0,
            surah=None,
            ayah=None,
            wpos=None,
            skip_reason='no_quote',
        ),
    ])
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))
    return db


def test_review_page_contains_tawjih(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    page = client.get('/tawjih-review')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert 'توجيه' in text
    assert 'noindex' in text


def test_summary_counts_from_fixture(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    payload = client.get('/api/tawjih-review/summary').get_json()
    assert payload['published'] == 1
    assert payload['review'] == 1
    assert payload['skipped'] == 1
    assert payload['total'] == 3
    assert payload['source']['author'] == 'د. أحمد صابر عبدالهادي'


def test_review_items_have_empty_verse_words(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    data = client.get('/api/tawjih-review/items?status=review').get_json()
    assert data['total'] == 1
    item = data['items'][0]
    assert item['status'] == 'review'
    assert item['tweet_id'] == 'fixture-review'
    assert item['surah'] is None
    assert item['verse_words'] == []
    assert item['tweet_body']
    assert item['attachments'] == []


def test_verse_endpoint_valid_invalid_and_missing(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    ok = client.get('/api/tawjih-review/verse/1/5')
    assert ok.status_code == 200
    payload = ok.get_json()
    assert payload['surah'] == 1 and payload['ayah'] == 5
    assert payload['words'] == verse_words(UNIQUE_SURAH, UNIQUE_AYAH)
    assert client.get('/api/tawjih-review/verse/115/1').status_code == 400
    missing = client.get('/api/tawjih-review/verse/2/287')
    assert missing.status_code == 404


def test_add_without_wpos_is_409_then_valid_add_publishes(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    review = client.get('/api/tawjih-review/items?status=review').get_json()['items'][0]
    missing = client.post('/api/tawjih-review/decision', json={
        'id': review['id'],
        'decision': 'add',
        'surah': UNIQUE_SURAH,
        'ayah': UNIQUE_AYAH,
    })
    assert missing.status_code == 409

    words = verse_words(UNIQUE_SURAH, UNIQUE_AYAH)
    added = client.post('/api/tawjih-review/decision', json={
        'id': review['id'],
        'decision': 'add',
        'surah': UNIQUE_SURAH,
        'ayah': UNIQUE_AYAH,
        'wpos': len(words) - 1,
        'quote': UNIQUE_QUOTE,
    })
    assert added.status_code == 200
    body = added.get_json()
    assert body['ok'] is True
    assert body['decision'] == 'add'
    assert body['status'] == 'published'
    assert body['surah'] == UNIQUE_SURAH
    assert body['ayah'] == UNIQUE_AYAH
    assert body['wpos'] == len(words) - 1

    live = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    tweet_ids = {entry['tweet_id'] for entry in live['entries']}
    assert 'fixture-review' in tweet_ids
    assert live['count'] >= 2


def test_discard_skips_and_stays_off_live_api(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    review = client.get('/api/tawjih-review/items?status=review').get_json()['items'][0]
    response = client.post('/api/tawjih-review/decision', json={
        'id': review['id'],
        'decision': 'discard',
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'skipped'

    skipped = client.get('/api/tawjih-review/items?status=skipped').get_json()
    row = next(item for item in skipped['items'] if item['id'] == review['id'])
    assert row['skip_reason'] == 'reviewer_discard'

    live = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    assert all(entry['tweet_id'] != 'fixture-review' for entry in live['entries'])


def test_unknown_id_is_404_and_bad_decision_is_400(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    unknown = client.post('/api/tawjih-review/decision', json={
        'id': 999999,
        'decision': 'discard',
    })
    assert unknown.status_code == 404
    bad = client.post('/api/tawjih-review/decision', json={
        'id': 1,
        'decision': 'approve',
    })
    assert bad.status_code == 400


def test_add_does_not_write_classical_waqf_db(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    before = _sha(Path(CLASSICAL_WAQF_DATABASE))
    review = client.get('/api/tawjih-review/items?status=review').get_json()['items'][0]
    words = verse_words(UNIQUE_SURAH, UNIQUE_AYAH)
    response = client.post('/api/tawjih-review/decision', json={
        'id': review['id'],
        'decision': 'add',
        'surah': UNIQUE_SURAH,
        'ayah': UNIQUE_AYAH,
        'wpos': len(words) - 1,
    })
    assert response.status_code == 200
    assert _sha(Path(CLASSICAL_WAQF_DATABASE)) == before

def test_shape_review_item_reply_sets_qa():
    row = {
        'id': 7,
        'tweet_id': 'reply-1',
        'status': 'review',
        'surah': UNIQUE_SURAH,
        'ayah': UNIQUE_AYAH,
        'wpos': None,
        'quote': '',
        'note': 'الوقف هنا تام.',
        'grade': None,
        'align_conf': 0,
        'skip_reason': None,
        'locator': '',
        'url': 'https://x.com/Dr_ahmed21/status/reply-1',
    }
    post = {
        'kind': 'رد',
        'post_text': 'ما حكم الوقف على رأس الآية أيها الشيخ؟',
        'reply_text': '@AmerNadwi الوقف هنا تام.',
        'reply_to_user': '@AmerNadwi',
        'reply_to_url': 'https://x.com/AmerNadwi/status/99',
        'url': row['url'],
        'media': '',
    }
    item = _shape_review_item(row, post)
    assert item['is_reply'] is True
    assert item['question'] == post['post_text']
    assert item['answer'] == 'الوقف هنا تام.'
    assert item['display_note'] == '@AmerNadwi الوقف هنا تام.'
    assert item['tweet_body'] == post['reply_text']


def test_review_items_filter_by_surah(client, tmp_path, monkeypatch):
    _three_row_db(tmp_path, monkeypatch)
    matched = client.get('/api/tawjih-review/items?status=published&surah=1').get_json()
    assert matched['total'] == 1
    assert matched['items'][0]['surah'] == UNIQUE_SURAH
    assert matched['items'][0]['tweet_id'] == 'fixture-published'
    empty = client.get('/api/tawjih-review/items?status=published&surah=2').get_json()
    assert empty['total'] == 0
    assert empty['items'] == []
    assert client.get('/api/tawjih-review/items?status=published&surah=115').status_code == 400
