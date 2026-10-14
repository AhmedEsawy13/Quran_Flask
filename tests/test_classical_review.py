"""Local reviewer for promoting المكتفى without an LLM."""
import shutil
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


@pytest.fixture()
def pending_muktafa(tmp_path):
    """Every المكتفى row is resolved now; exercise the review workflow on one
    real, correctly aligned row marked pending for the test's duration.

    The live code paths read the shipped DB by path, so it is edited in place —
    but byte-for-byte restored afterwards. Any SQLite write bumps header bytes,
    which would otherwise leave the tracked file dirty after every run (and a
    crashed test would leave a real ruling flipped)."""
    db_path = review.CLASSICAL_WAQF_DATABASE
    snapshot = tmp_path / 'classical_waqf.snapshot.db'
    shutil.copyfile(db_path, snapshot)
    conn = sqlite3.connect(db_path)
    row_id = 116          # 2:81 «هم فيها خالدون»
    conn.execute('UPDATE classical SET conf=0 WHERE id=?', (row_id,))
    conn.commit()
    try:
        yield row_id
    finally:
        conn.close()
        shutil.copyfile(snapshot, db_path)


@pytest.fixture()
def pending_manar(tmp_path, monkeypatch):
    """Leave two real, already-corrected rows of the منار queue unverified."""
    import json
    data = json.loads(review.MANAR_VERIFIED.read_text(encoding='utf-8'))
    keep_pending = {'59559', '58065'}          # 83:2, 52:8
    data['ids'] = {k: v for k, v in data['ids'].items() if k not in keep_pending}
    path = tmp_path / 'verified.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(review, 'MANAR_VERIFIED', path)
    review.manar_review_queue.cache_clear()
    yield {int(i) for i in keep_pending}
    review.manar_review_queue.cache_clear()


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
    # +12 rulings recalled from the book (2026-10-07: «تمام القصة», «هما كافيان»…),
    # −1 blanket verse-end row an explicit ruling replaced; −3 blanket rows on
    # 33:45–47, which «ومثله {وكيلا}. وكذلك الفواصل إلى …» (33:48 on) never covered;
    # +21 الشعراء refrain rulings («وكذلك جميع ما في السورة من ذلك») − 14 blanket rows
    # they replace; +26 other «حيث وقع / جميع ما في السورة» occurrences (2:1, 10:1,
    # 27:61–64, 54 «من مدكر», 77 «ويل يومئذ للمكذبين» and the verse before each)
    # +2 Hafs-side rows (40:20, 91:14) − 1 blanket row under the moved «لدا» (19:97)
    # +3: «سيقولون لله» في الثلاثة (23:87، 89), 8:42 «وهو التمام»; +87 blanket verse ends
    # a single «ورأس الآية أكفى منه» no longer cuts off an open «بعد»; +2 «والتمام آخر
    # السورة» (110, 114); +5 «مثله {X}» / «{X} مثل {Y}» items (6:25, 45:10, 98:4, 111)
    # +30 الرحمن refrain («كل شيء في هذه السورة من فبأي آلاء ربكما تكذبان تام»), −1 «المر»
    # seated in 10:12, 70:21 «لا» (إلا المصلين) replacing its blanket كاف
    # +134 «والفواصل بين ذلك كافية» after surah-wide refrains (26, 37, 38, 54) and 74:3–7
    # «كل آية بعدها كافية»; +4 (9:30 [bracketed], 74:31 «[ومثله]», 74:53 «كلا», 89:14)
    # +7 seventh check: «[ومثله]» 7:74/7:176, 7:92, «وهو عندي كاف» 15:13 + 26:201, 60:1 «وكذلك هو
    # عندي», 60:4 «والتمام {X}»
    # +4 eighth check: 37:4 «وهو وقف كاف», 37:5 «{ورب المشارق} التمام», relayed 38:25 (يعقوب
    # والدينوري) and 68:6 (غيره)
    # +6 ninth check: 24:28 ×2 «شبيه بالتام ورأس الآية أتم», 24:45 «وآخر الآية أتم منهما»; relayed
    # 18:22 الزجاج, 18:44 الدينوري, 48:29 مجاهد
    # +63 tenth check: +54 blanket verse ends (81:1–13 «ورؤوس الآي بين ذلك», 72 «رأس كل آية كاف»
    # (بعض العلماء), 69 «هاءات الاستراحة» and 69:30–50, 112:4, 113:5), +7 «والآية أتم» verse ends
    # and 81:14, 77:7 (−4 blanket rows they replace), +4 relayed (72 ×3, 81:21 نافع), +2 «لا»
    # +64 sweep: «قبل ذلك» / «قبل وبعد» ranges start after the previous statement or at the
    # surah start, not at the «ومثله» head (50:1–28, 19:1–20, 9, 5, 16:78–88, 18:60–62, 59)
    # +1 eleventh check: 25:21 «وهو عندي تام» beside the relayed كاف; 12:52 «تمام الكلام» and 27:43
    # «ورأس الآية أتم» replace their blanket كاف (+2 −2)
    # +20 twelfth check: 53 «والوقف {X} وهو كاف. ومثله …» (7), «جواب القسم {…} فلا وقف دونه»
    # لا on 51:1–4, 52:1–6, 53:1 (11), 50:42, 83:28, 59:15 الأخفش; −1 20:77 jussive «لا تخف دركا»
    # +3 thirteenth check: 22:27 «صالح غير تام ولا كاف», 3:34 «[ {سميع عليم} ] . تام», 33:33 «والتمام
    # تطهيرا»; 22:41 and 11:109 «ورأس الآية أتم / والآية تمام» replace their blanket كاف (+2 −2)
    # +7 fourteenth check: 7:30 «[عليهم الضلالة] كاف», 4:157 «والوقف عندي على رسول الله», 7:172
    # relayed «التمام قالوا بلى», 3:156 «والتمام آخر الآية» (replaces its blanket), 4:155–160 «ورؤوس
    # الآي فيما بين ذلك كافية» (+4)
    # +5 fifteenth check: 4:8 «وآخر الآية أكفى», 4:24 «تمام القصة», 4:30 «[يسيرا] تام», 5:25 «وأخي»
    # كاف, 7:190 «وهو عندي تام»
    # +14 coverage sweep: «جواب القسم {X} وهو GRADE» heads and their «ومثله» items (82, 86, 90, 92,
    # 93, 95), «تام على القراءتين / في كلا الوجهين» (14:2, 28:68, 29:66)
    # +1 round 25: 6:3 «والتمام عندي آخر الآية», 2:141 «وكذلك [الذي] عند رأس الجزء», 12:92–93
    # «ورأس الآية أتم. وكذلك {…}», 3:79 Hafs «لم يقف على تدرسون» (+5 −4 blankets they replace),
    # 3:59 relayed النحاس (+1), 12:93's old كاف dropped (−1)
    assert result['total_extracted'] == 7252
    assert result['matched'] == 7252
    assert result['confident'] == 7252
    assert result['uncertain'] == 0
    assert result['source_traceable_rate'] == 100.0
    assert result['quran_aligned_rate'] == 100.0


def test_review_page_and_summary_are_editor_routes(client, review_db):
    page = client.get('/classical-review')
    assert page.status_code == 200
    assert 'المكتفى' in page.get_data(as_text=True)
    summary = client.get('/api/classical-review/muktafa/summary').get_json()
    assert summary['review']['pending'] == 0
    manar = client.get('/api/classical-review/manar/summary').get_json()
    assert manar['review']['pending'] == len(review.manar_review_queue())
    assert manar['review']['pending'] == 0      # every heuristic suspect read
    assert manar['source_traceable_rate'] == 100.0
    # exact-seat misses vs explicit_manar_rows' seat (exact spelling, then the
    # pause-marked occurrence). The 8 left were read by hand: 3:20 the checker
    # reads «أأسلمتم» as «أسلمت»; 4:78, 4:131, 5:41, 29:47, 29:53, 42:15, 59:18
    # sit on the other occurrence on purpose (audit_manar_mithl SEAT_KEEP).
    # the explicit-key aligner seats a repeated word on its last / pause-marked
    # occurrence; rows read against the book sit elsewhere: 43:32 «رحمت ربك»
    # (2026-09-28) and 2:69, 3:7, 4:11, 4:94, 7:146, 30:56 (2026-10-07), while
    # 4:78 and 29:47 now agree with it — 8 + 1 + 6 − 2 = 13; the book-order read
    # of repeated words adds 3:154, 20:10, 63:6 and settles 4:131 — 13 + 3 − 1 = 15
    assert manar['explicit_missing'] == 15


def test_reviewer_can_approve_a_matched_row(client, review_db, pending_muktafa):
    data = client.get(
        '/api/classical-review/muktafa/items?status=pending&alignment=matched&limit=50'
    ).get_json()
    item = next(
        it for it in data['items']
        if review.quote_matches_position(
            it['surah'], it['ayah'], it['wpos'], it['quote'])
    )
    response = client.post('/api/classical-review/muktafa/decision', json={
        'row_id': item['id'], 'decision': 'approve', 'ayah': item['ayah'],
        'wpos': item['wpos'], 'note': 'تحققت من النص والموضع',
    })
    assert response.status_code == 200
    saved = review.decisions(review_db=review_db)[item['id']]
    assert saved['decision'] == 'approve'


def test_reviewer_can_edit_waqf_grade_and_live_api_uses_it(client, review_db, pending_manar):
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


def test_reviewer_rejects_unknown_waqf_grade(client, review_db, pending_manar):
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
    payload = client.get(
        '/api/classical-review/muktafa/items?status=pending&alignment=unmatched&limit=1'
    ).get_json()
    if not payload['items']:
        pytest.skip('no unmatched muktafa rows left')
    item = payload['items'][0]
    response = client.post('/api/classical-review/muktafa/decision', json={
        'row_id': item['id'], 'decision': 'approve',
    })
    assert response.status_code == 409
    assert 'verified ayah' in response.get_json()['error']


def test_book_addition_is_blocked_until_queue_is_complete(client, review_db, pending_muktafa):
    response = client.post('/api/classical-review/muktafa/book-decision', json={
        'decision': 'add',
    })
    assert response.status_code == 409
    assert response.get_json()['pending'] == 1


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
    assert set(payload['sources']) == {'manar', 'muktafa', 'anbari', 'nahhas'}
    assert any(row['source'] == 'muktafa' for row in payload['entries'])


def test_manar_queue_has_stable_rows_and_source_context(client, review_db, pending_manar):
    payload = client.get('/api/classical-review/manar/items?limit=1').get_json()
    assert payload['total'] == len(review.manar_review_queue())
    item = payload['items'][0]
    assert item['id'] in review.manar_review_queue()
    assert item['source_context']
    assert item['alignment'] == 'matched'


def test_rejected_manar_ruling_is_suppressed_from_live_api(client, review_db, pending_manar):
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
