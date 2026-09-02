"""Contemporary توجيه: alignment policy, sqlite fallback, and /api/tawjih."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from core.config import CLASSICAL_WAQF_DATABASE
from core.tawjih import TAWJIH_SOURCE, _shape_entry, ensure_sqlite_schema, verse_words
from modules.breathing import _ACTIVE_CLASSICAL_SOURCES
from pipeline import build_tawjih as tawjih


# Unique across the Quran (1:5). Shorter «الحمد لله رب العالمين» is not.
UNIQUE_QUOTE = 'إِيَّاكَ نَعۡبُدُ وَإِيَّاكَ نَسۡتَعِينُ'
UNIQUE_SURAH, UNIQUE_AYAH = 1, 5


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(**overrides):
    row = {
        'tweet_id': '1001',
        'seq': 1,
        'posted_at': '2026-01-01T00:00:00+00:00',
        'kind': 'منشور',
        'post_text': f'قوله تعالى: "{UNIQUE_QUOTE}" وقف تام.',
        'reply_text': '',
        'url': 'https://x.com/Dr_ahmed21/status/1001',
        'related_waqf': False,
    }
    row.update(overrides)
    return row


def _write_fixture(db: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(db)
    try:
        ensure_sqlite_schema(conn)
        conn.execute('DELETE FROM tawjih')
        for row in rows:
            conn.execute(
                'INSERT INTO tawjih ('
                'tweet_id,surah,ayah,wpos,quote,note,grade,status,align_conf,'
                'skip_reason,locator,url,created_at) '
                'VALUES (:tweet_id,:surah,:ayah,:wpos,:quote,:note,:grade,:status,'
                ':align_conf,:skip_reason,:locator,:url,:created_at)',
                row,
            )
        conn.commit()
    finally:
        conn.close()


def _published_fixture(**overrides):
    words = verse_words(UNIQUE_SURAH, UNIQUE_AYAH)
    row = {
        'tweet_id': 'fixture-published',
        'surah': UNIQUE_SURAH,
        'ayah': UNIQUE_AYAH,
        'wpos': len(words) - 1,
        'quote': UNIQUE_QUOTE,
        'note': 'توجيه اختباري على رأس الآية.',
        'grade': 'تام',
        'status': 'published',
        'align_conf': 1,
        'skip_reason': None,
        'locator': 'tweet:fixture-published',
        'url': 'https://x.com/Dr_ahmed21/status/fixture-published',
        'created_at': '2026-01-01T00:00:00+00:00',
    }
    row.update(overrides)
    return row


def test_unique_explicit_quote_publishes_with_explicit_grade():
    rows = tawjih.classify_post(_post())
    assert len(rows) == 1
    row = rows[0]
    assert row.status == 'published'
    assert row.align_conf == 1
    assert row.surah == UNIQUE_SURAH and row.ayah == UNIQUE_AYAH
    assert row.wpos == len(verse_words(UNIQUE_SURAH, UNIQUE_AYAH)) - 1
    assert row.grade == 'تام'
    assert tawjih.classical.quote_words(row.quote) == tawjih.classical.quote_words(UNIQUE_QUOTE)
    assert row.skip_reason is None


def test_grade_is_not_inferred_from_prose():
    rows = tawjih.classify_post(_post(
        post_text=f'قوله تعالى: "{UNIQUE_QUOTE}" وهذا وقف صحيح ويجوز في حق العوام.',
    ))
    assert rows[0].status == 'published'
    assert rows[0].grade is None


def test_reply_uses_reply_text_not_post_text():
    rows = tawjih.classify_post(_post(
        kind='رد',
        post_text='متن التغريدة الأصلية بلا اقتباس.',
        reply_text=f'قوله تعالى: "{UNIQUE_QUOTE}" وقف كاف.',
    ))
    assert rows[0].status == 'published'
    assert rows[0].grade == 'كاف'
    assert rows[0].ayah == UNIQUE_AYAH


def test_retweet_zoom_whatsapp_and_empty_are_skipped():
    assert tawjih.classify_post(_post(kind='إعادة تغريد'))[0].skip_reason == 'retweet'
    assert tawjih.classify_post(_post(
        post_text='لقاء بعنوان الوقف عبر Zoom https://us06web.zoom.us/j/1',
    ))[0].skip_reason == 'zoom'
    assert tawjih.classify_post(_post(
        post_text='التسجيل على واتساب https://chat.whatsapp.com/abc',
    ))[0].skip_reason == 'whatsapp'
    assert tawjih.classify_post(_post(post_text='https://t.co/abc'))[0].skip_reason == 'empty'
    assert tawjih.classify_post(_post(post_text='لقاء بعنوان الوقف والابتداء للتسجيل'))[0].skip_reason == 'event'


def test_related_waqf_is_not_a_publish_filter():
    published = tawjih.classify_post(_post(related_waqf=False))
    assert published[0].status == 'published'
    also = tawjih.classify_post(_post(tweet_id='1002', related_waqf=True))
    assert also[0].status == 'published'


def test_ambiguous_or_unquoted_text_is_not_published():
    ambiguous = tawjih.classify_post(_post(
        post_text='قوله تعالى: "ٱللَّهِ" وقف تام.',
    ))
    assert ambiguous[0].status == 'review'
    assert ambiguous[0].align_conf == 0
    assert ambiguous[0].skip_reason in {'ambiguous_verse', 'ambiguous_repeated_phrase', 'unaligned_quote'}

    no_quote = tawjih.classify_post(_post(
        post_text='كلام عن الوقف والابتداء بلا اقتباس قرآني صريح.',
    ))
    assert no_quote[0].status == 'skipped'
    assert no_quote[0].skip_reason == 'no_quote'


def test_explicit_verse_locator_disambiguates_repeated_phrase():
    """الحمد لله رب العالمين occurs in several surahs; the locator is required."""
    rows = tawjih.classify_post(_post(
        post_text='سورة الفاتحة آية ٢ قوله تعالى: "ٱلۡحَمۡدُ لِلَّهِ رَبِّ ٱلۡعَٰلَمِينَ" وقف تام.',
    ))
    assert rows[0].status == 'published'
    assert rows[0].surah == 1 and rows[0].ayah == 2
    assert rows[0].align_conf == 1


def test_surah_name_then_ayah_number_still_locates():
    rows = tawjih.classify_post(_post(
        post_text='سورة الفاتحة قوله تعالى: "ٱلۡحَمۡدُ لِلَّهِ رَبِّ ٱلۡعَٰلَمِينَ" الآية ٢ وقف تام.',
    ))
    assert rows[0].status == 'published'
    assert rows[0].surah == 1 and rows[0].ayah == 2


def test_guillemet_quote_publishes_when_the_span_is_unique():
    rows = tawjih.classify_post(_post(
        post_text=f'«{UNIQUE_QUOTE}» وقف تام.',
    ))
    assert rows[0].status == 'published'
    assert rows[0].surah == UNIQUE_SURAH and rows[0].ayah == UNIQUE_AYAH
    assert rows[0].wpos == len(verse_words(UNIQUE_SURAH, UNIQUE_AYAH)) - 1


def test_align_quote_returns_the_full_span_not_only_the_last_word():
    hits = tawjih.align_quote(UNIQUE_QUOTE)
    assert hits == [(UNIQUE_SURAH, UNIQUE_AYAH, 0, len(verse_words(UNIQUE_SURAH, UNIQUE_AYAH)) - 1)]


def test_pipeline_never_writes_classical_waqf_db():
    before = _sha(Path(CLASSICAL_WAQF_DATABASE))
    tawjih.classify_posts([_post(), _post(kind='إعادة تغريد', tweet_id='9')])
    assert _sha(Path(CLASSICAL_WAQF_DATABASE)) == before
    assert 'tawjih' not in _ACTIVE_CLASSICAL_SOURCES
    assert _ACTIVE_CLASSICAL_SOURCES == {'manar'}


def test_sqlite_write_roundtrip(tmp_path):
    db = tmp_path / 'tawjih.db'
    rows = tawjih.classify_posts([_post()])
    tawjih.write_sqlite(db, rows)
    conn = sqlite3.connect(db)
    try:
        stored = conn.execute(
            'SELECT surah,ayah,status,align_conf,grade FROM tawjih'
        ).fetchall()
    finally:
        conn.close()
    assert stored == [(UNIQUE_SURAH, UNIQUE_AYAH, 'published', 1, 'تام')]


def test_api_returns_fixture_published_row(client, tmp_path, monkeypatch):
    db = tmp_path / 'tawjih.db'
    fixture = _published_fixture()
    _write_fixture(db, [
        fixture,
        _published_fixture(
            tweet_id='fixture-review', status='review', align_conf=0, grade='كاف',
        ),
        _published_fixture(
            tweet_id='fixture-skipped', status='skipped', align_conf=0,
            surah=None, ayah=None, wpos=None,
        ),
        _published_fixture(
            tweet_id='fixture-lowconf', align_conf=0, status='published',
        ),
    ])
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))

    response = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['surah'] == UNIQUE_SURAH and payload['ayah'] == UNIQUE_AYAH
    assert payload['count'] == 1
    assert payload['source'] == TAWJIH_SOURCE
    assert payload['source']['author'] == 'د. أحمد صابر عبدالهادي'
    assert payload['source']['url'] == 'https://x.com/Dr_ahmed21'
    assert len(payload['entries']) == 1
    entry = payload['entries'][0]
    words = verse_words(UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['wpos'] == fixture['wpos']
    assert entry['wpos_start'] == 0
    assert entry['phrase'] == words
    assert entry['tweet_id'] == fixture['tweet_id']
    assert entry['stop_word'] == words[fixture['wpos']]
    assert entry['quote'] == UNIQUE_QUOTE
    assert entry['grade'] == 'تام'
    assert entry['url'] == fixture['url']
    assert entry['created_at'] == fixture['created_at']
    assert entry['note'] == fixture['note']
    assert entry['display_note'] == fixture['note']
    assert entry['attachments'] == []
    assert 'source' not in entry


def test_api_empty_verse_is_200(client, tmp_path, monkeypatch):
    db = tmp_path / 'tawjih.db'
    _write_fixture(db, [_published_fixture()])
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))
    response = client.get('/api/tawjih/2/2')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        'surah': 2,
        'ayah': 2,
        'source': TAWJIH_SOURCE,
        'count': 0,
        'entries': [],
    }


def test_api_invalid_verse_is_400(client):
    assert client.get('/api/tawjih/115/1').status_code == 400
    assert client.get('/api/tawjih/2/0').status_code == 400
    assert client.get('/api/tawjih/2/287').status_code == 400
    body = client.get('/api/tawjih/0/1').get_json()
    assert body == {'error': 'invalid verse'}


def test_api_does_not_mix_into_classical_sources(client, tmp_path, monkeypatch):
    db = tmp_path / 'tawjih.db'
    _write_fixture(db, [_published_fixture()])
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))
    classical = client.get(f'/api/classical-waqf/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    assert 'tawjih' not in classical['sources']
    assert set(classical['sources'].keys()) <= _ACTIVE_CLASSICAL_SOURCES
    tawjih_payload = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    assert tawjih_payload['count'] == 1
    assert tawjih_payload['source']['title'] == 'توجيه معاصر'


def test_api_parses_drive_url_in_note(client, tmp_path, monkeypatch):
    db = tmp_path / 'tawjih.db'
    note = (
        'الوقف هنا تام.\n'
        'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/view?usp=sharing'
    )
    _write_fixture(db, [_published_fixture(note=note)])
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))
    entry = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()['entries'][0]
    assert entry['note'] == note
    assert entry['display_note'] == 'الوقف هنا تام.'
    assert len(entry['attachments']) == 1
    att = entry['attachments'][0]
    assert att['type'] == 'drive'
    assert att['file_id'] == '1AbCDefGhIJKlmnoPQRstuVWX'
    assert att['href'] == 'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/view'
    assert att['preview'] == 'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/preview'
    assert att['label'] == 'ملف على درايف'

def _reply_row(**overrides):
    question = 'ما حكم الوقف على رأس الآية أيها الشيخ الفاضل بارك الله فيكم؟'
    row = _published_fixture()
    row.update({
        'kind': 'رد',
        'post_text': question,
        'reply_text': '@AmerNadwi الوقف هنا تام.',
        'reply_to_user': '@AmerNadwi',
        'reply_to_url': 'https://x.com/AmerNadwi/status/42',
        'media': '',
    })
    row.update(overrides)
    return row


def test_shape_entry_reply_sets_question_and_answer():
    row = _reply_row()
    entry = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['is_reply'] is True
    assert entry['question'] == row['post_text']
    assert entry['question_author'] == '@AmerNadwi'
    assert entry['question_url'] == 'https://x.com/AmerNadwi/status/42'
    assert entry['answer'] == 'الوقف هنا تام.'
    assert entry['display_note'] == '@AmerNadwi الوقف هنا تام.'
    assert row['post_text'] not in entry['display_note']


def test_shape_entry_non_reply_has_no_qa():
    row = _published_fixture()
    row.update({
        'kind': 'منشور',
        'post_text': 'قوله تعالى وقف تام.',
        'reply_text': '',
    })
    entry = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['is_reply'] is False
    assert entry['question'] is None
    assert entry['answer'] is None
    assert entry['display_note'] == row['note']


def test_shape_entry_reply_without_parent_text_is_not_qa():
    row = _reply_row(post_text='')
    entry = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['is_reply'] is False
    assert entry['question'] is None
    assert entry['answer'] is None


def test_shape_entry_rejects_unsafe_question_url():
    row = _reply_row(reply_to_url='https://evil.example/phish')
    entry = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['is_reply'] is True
    assert entry['question_url'] is None
    http_row = _reply_row(reply_to_url='http://x.com/AmerNadwi/status/42')
    assert _shape_entry(http_row, UNIQUE_SURAH, UNIQUE_AYAH)['question_url'] is None


def test_shape_entry_does_not_double_at_on_author():
    row = _reply_row(reply_to_user='AmerNadwi', reply_text='@AmerNadwi الوقف هنا تام.')
    entry = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    assert entry['question_author'] == 'AmerNadwi'
    assert entry['answer'] == 'الوقف هنا تام.'


def test_api_reply_entry_exposes_qa(client, monkeypatch):
    row = _reply_row()
    shaped = _shape_entry(row, UNIQUE_SURAH, UNIQUE_AYAH)
    monkeypatch.setattr('modules.breathing._list_published_tawjih', lambda s, a: [shaped])
    payload = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    assert payload['count'] == 1
    entry = payload['entries'][0]
    assert entry['is_reply'] is True
    assert entry['question'] == row['post_text']
    assert entry['answer'] == 'الوقف هنا تام.'
    assert entry['question_author'] == '@AmerNadwi'
    assert entry['question_url'] == 'https://x.com/AmerNadwi/status/42'
    assert entry['display_note'] == '@AmerNadwi الوقف هنا تام.'

