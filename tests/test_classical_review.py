"""Local reviewer for promoting المكتفى without an LLM."""
import sqlite3

import pytest

from core import classical_review as review
from core import supabase_editor as sb


@pytest.fixture()
def review_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'review.db')
    monkeypatch.setattr(review, 'CLASSICAL_REVIEW_DATABASE', path)
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    return path


def uncertain_rows():
    conn = sqlite3.connect(review.CLASSICAL_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM classical WHERE source='muktafa' AND conf=0 ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def test_accuracy_baseline_is_fully_traceable_and_aligned(review_db):
    result = review.muktafa_accuracy(review_db=review_db)
    assert result['total_extracted'] == 4408
    assert result['matched'] == 4355
    assert result['confident'] == 4241
    assert result['uncertain'] == 167
    assert result['source_traceable_rate'] == 100.0
    assert result['quran_aligned_rate'] == 100.0


def test_review_page_and_summary_are_editor_routes(client, review_db):
    page = client.get('/classical-review')
    assert page.status_code == 200
    assert 'المكتفى' in page.get_data(as_text=True)
    summary = client.get('/api/classical-review/muktafa/summary').get_json()
    assert summary['review']['pending'] == 167
    manar = client.get('/api/classical-review/manar/summary').get_json()
    assert manar['review']['pending'] == len(review.manar_review_queue())
    assert manar['source_traceable_rate'] == 99.36
    assert manar['explicit_missing'] == 0


def test_reviewer_can_approve_a_matched_row(client, review_db):
    data = client.get(
        '/api/classical-review/muktafa/items?status=pending&alignment=matched&limit=1'
    ).get_json()
    item = data['items'][0]
    response = client.post('/api/classical-review/muktafa/decision', json={
        'row_id': item['id'], 'decision': 'approve', 'ayah': item['ayah'],
        'wpos': item['wpos'], 'note': 'تحققت من النص والموضع',
    })
    assert response.status_code == 200
    saved = review.decisions(review_db=review_db)[item['id']]
    assert saved['decision'] == 'approve'


def test_reviewer_can_edit_waqf_grade_and_live_api_uses_it(client, review_db):
    item = client.get(
        '/api/classical-review/manar/items?status=pending&limit=1'
    ).get_json()['items'][0]
    replacement = next(
        grade for grade in review.REVIEW_GRADE_LABELS
        if grade != item['effective_grade']
    )
    response = client.post('/api/classical-review/manar/decision', json={
        'row_id': item['id'], 'decision': 'approve',
        'ayah': item['effective_ayah'], 'wpos': item['effective_wpos'],
        'grade': replacement, 'note': 'راجعت نوع الوقف',
    })
    assert response.status_code == 200
    assert response.get_json()['grade'] == replacement
    saved = review.decisions('manar', review_db=review_db)[item['id']]
    assert saved['corrected_grade'] == replacement

    live = client.get(
        f'/api/classical-waqf/{item["surah"]}/{item["ayah"]}'
    ).get_json()
    live_item = next(
        row for row in live['entries']
        if row['source'] == 'manar' and row['wpos'] == item['wpos']
        and row['quote'] == item['quote']
    )
    assert live_item['grade'] == replacement
    assert live_item['grade_raw'] == review.REVIEW_GRADE_LABELS[replacement]


def test_reviewer_rejects_unknown_waqf_grade(client, review_db):
    item = client.get(
        '/api/classical-review/manar/items?status=pending&limit=1'
    ).get_json()['items'][0]
    response = client.post('/api/classical-review/manar/decision', json={
        'row_id': item['id'], 'decision': 'approve',
        'ayah': item['effective_ayah'], 'wpos': item['effective_wpos'],
        'grade': 'ممتاز',
    })
    assert response.status_code == 400
    assert 'grade' in response.get_json()['error']


def test_unmatched_row_cannot_be_approved_without_correction(client, review_db):
    item = client.get(
        '/api/classical-review/muktafa/items?status=pending&alignment=unmatched&limit=1'
    ).get_json()['items'][0]
    response = client.post('/api/classical-review/muktafa/decision', json={
        'row_id': item['id'], 'decision': 'approve',
    })
    assert response.status_code == 409
    assert 'verified ayah' in response.get_json()['error']


def test_book_addition_is_blocked_until_queue_is_complete(client, review_db):
    response = client.post('/api/classical-review/muktafa/book-decision', json={
        'decision': 'add',
    })
    assert response.status_code == 409
    assert response.get_json()['pending'] == 167


def test_completed_review_can_activate_muktafa(client, review_db):
    # Rejecting here only exercises the release gate; a real reviewer makes
    # each decision in the UI and may approve aligned/corrected rows instead.
    for row in uncertain_rows():
        review.save_decision(row['id'], 'reject', 'test decision', review_db=review_db)
    response = client.post('/api/classical-review/muktafa/book-decision', json={
        'decision': 'add', 'note': 'review complete',
    })
    assert response.status_code == 200
    payload = client.get('/api/classical-waqf/2/255').get_json()
    assert set(payload['sources']) == {'manar', 'muktafa'}
    assert any(row['source'] == 'muktafa' for row in payload['entries'])


def test_manar_queue_has_stable_rows_and_source_context(client, review_db):
    payload = client.get('/api/classical-review/manar/items?limit=1').get_json()
    assert payload['total'] == len(review.manar_review_queue())
    item = payload['items'][0]
    assert item['id'] in review.manar_review_queue()
    assert item['source_context']
    assert item['alignment'] == 'matched'


def test_rejected_manar_ruling_is_suppressed_from_live_api(client, review_db):
    item = client.get('/api/classical-review/manar/items?limit=1').get_json()['items'][0]
    before = client.get(f'/api/classical-waqf/{item["surah"]}/{item["ayah"]}').get_json()
    key = (item['wpos'], item['quote'], item['grade'])
    assert any((row['wpos'], row['quote'], row['grade']) == key for row in before['entries'])

    response = client.post('/api/classical-review/manar/decision', json={
        'row_id': item['id'], 'decision': 'reject', 'note': 'لم يثبت في المراجعة',
    })
    assert response.status_code == 200
    after = client.get(f'/api/classical-waqf/{item["surah"]}/{item["ayah"]}').get_json()
    assert not any((row['wpos'], row['quote'], row['grade']) == key for row in after['entries'])


def test_rejecting_manar_book_removes_it_from_active_sources(client, review_db):
    response = client.post('/api/classical-review/manar/book-decision', json={
        'decision': 'reject', 'note': 'اختبار قرار الكتاب',
    })
    assert response.status_code == 200
    payload = client.get('/api/classical-waqf/2/255').get_json()
    assert 'manar' not in payload['sources']
