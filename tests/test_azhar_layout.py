"""Azhar / Layout Studio — seeded from الشمرلي, Amiri render, editor writes."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


@pytest.fixture
def restore_azhar_layout_db(tmp_path):
    """Mutating tests restore the exact pre-test DB, including reviewer work."""
    import shutil

    from core.config import AZHAR_LAYOUT_DATABASE

    db = Path(AZHAR_LAYOUT_DATABASE)
    backup = tmp_path / db.name
    shutil.copy2(db, backup)
    try:
        yield
    finally:
        shutil.copy2(backup, db)


def test_layout_studio_registry_and_shell(client):
    from modules.layout_editions import AZHAR

    editions = client.get('/api/layout-studio/editions').get_json()
    assert editions['default'] == 'azhar'
    azhar_edition = next(e for e in editions['editions'] if e['id'] == 'azhar')
    assert azhar_edition['profile']['page_end_mode'] == 'continuous'
    assert AZHAR.cloud_enabled is True
    assert azhar_edition['profile']['lines_per_page'] == 15
    assert azhar_edition['profile']['full_banner_lines'] == 3
    assert azhar_edition['max_page'] == 525

    bounced = client.get('/layout-studio')
    assert bounced.status_code in (301, 302)
    assert '/layout-studio/azhar' in bounced.headers.get('Location', '')

    page = client.get('/layout-studio/azhar').get_data(as_text=True)
    assert 'AtharLayoutStudio' in page
    assert 'استوديو التخطيط' in page
    assert 'مصحف الأزهر' in page
    assert 'id="az-undo"' in page
    assert 'id="az-profile-form"' in page
    assert 'name="az-page-end-mode"' in page
    assert '/api/layout-studio/azhar' in page

    unknown = client.get('/layout-studio/not-an-edition')
    assert unknown.status_code == 404

    api = client.get('/api/layout-studio/azhar/page/2')
    assert api.status_code == 200
    assert api.get_json()['source'] == 'azhar'


def test_azhar_working_range_extends_through_page_525(client):
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE

    for page_number in (523, 524, 525):
        response = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        )
        assert response.status_code == 200
        page = response.get_json()
        assert page['page_number'] == page_number
        assert page['max_page'] == 525
        assert len(page['lines']) == 15

    assert client.get('/api/azhar/page/526').status_code == 400
    with sqlite3.connect(AZHAR_LAYOUT_DATABASE) as conn:
        info = conn.execute(
            'SELECT number_of_pages, lines_per_page FROM info LIMIT 1'
        ).fetchone()
    assert info == (524, 15)


def test_azhar_layout_page_and_api(client):
    page = client.get('/azhar-layout').get_data(as_text=True)
    assert 'id="az-title"' in page
    assert 'استوديو التخطيط' in page
    assert 'azhar_layout.css' in page
    assert 'azhar_layout.js' in page
    assert 'az-cancel' in page
    assert 'id="az-undo"' in page
    assert 'az-reseed-note' in page
    assert 'AtharLayoutStudio' in page
    assert 'اسحب كلمة' in page
    assert 'id="az-compare"' in page
    assert 'id="az-ref-panel"' in page
    assert 'id="az-ref-img"' in page
    js = (PROJECT_ROOT / 'static/js/azhar_layout.js').read_text(encoding='utf-8')
    assert 'AtharLayoutStudio' in js
    assert 'apiBase' in js
    assert 'shamarlyshamarly' in js
    assert 'az-compare' in (PROJECT_ROOT / 'static/css/azhar_layout.css').read_text(encoding='utf-8')
    assert 'undoLast' in js
    assert 'pullNextWord' in js
    assert 'transferLineToNextPage' in js
    assert '/transfer-line' in js
    assert 'setLineCentered' in js
    assert 'saveProfile' in js
    assert 'juzFromAyah' in js

    r = client.get('/api/azhar/page/2')
    assert r.status_code == 200
    data = r.get_json()
    assert data['source'] == 'azhar'
    assert data['font_name'] == 'Amiri Quran'
    assert data['lines']
    assert data['lines'][0]['line_type'] == 'surah_name'
    assert data['lines'][1]['line_type'] == 'basmallah'
    assert data['lines_per_page'] == 6
    ayah_lines = [ln for ln in data['lines'] if ln['line_type'] == 'ayah']
    assert len(ayah_lines) == 4
    assert ayah_lines[-1]['last_word_id'] == 38
    assert any(line.get('words') for line in data['lines'])

    by_ayah = client.get('/api/azhar/page-by-ayah/1/1')
    assert by_ayah.status_code == 200
    assert by_ayah.get_json()['page_number'] == 2

    baqarah = client.get('/api/azhar/page/3').get_json()
    assert baqarah['lines_per_page'] == 5
    assert len(baqarah['lines']) == 5
    baq_ayah = [ln for ln in baqarah['lines'] if ln['line_type'] == 'ayah']
    assert len(baq_ayah) == 3
    assert baq_ayah[-1]['last_word_id'] == 76
    page4 = client.get('/api/azhar/page/4').get_json()
    first4 = next(ln for ln in page4['lines'] if ln['line_type'] == 'ayah')
    assert first4['first_word_id'] == 77


def test_azhar_basmala_uses_uthmani_script_and_fatiha_ayah_number(client):
    fatiha = client.get('/api/azhar/page/2').get_json()
    basmala = next(line for line in fatiha['lines'] if line['line_type'] == 'basmallah')
    assert 'ٱللَّهِ' in basmala['display_text']
    assert [word['text'] for word in basmala['words']] == [
        'بِسۡمِ',
        'ٱللَّهِ',
        'ٱلرَّحۡمَٰنِ',
        'ٱلرَّحِيمِ',
        '١',
    ]
    assert all(int(word['surah']) == 1 and int(word['ayah']) == 1 for word in basmala['words'])

    baqarah = client.get('/api/azhar/page/3').get_json()
    header = next(line for line in baqarah['lines'] if line['line_type'] == 'basmallah')
    assert header['display_text'] == 'بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ'
    assert header['words'] == []
    assert not header['display_text'].rstrip().endswith('١')


def test_azhar_payload_clamps_phantom_last_word_id(client):
    page = client.get('/api/azhar/page/193').get_json()
    line = next(row for row in page['lines'] if row['line_number'] == 9)
    assert line['last_word_id'] == 31788
    assert line['words']
    assert line['words'][-1]['word_index'] == 31788


def test_azhar_line_surah_follows_script_words(client):
    page = client.get('/api/azhar/page/521').get_json()
    fil_line = next(
        line for line in page['lines']
        if any(int(word.get('surah') or 0) == 105 for word in line['words'])
    )
    assert fil_line['surah_number'] == 105


def test_azhar_uthmani_basmala_fallback_upgrades_imlaey():
    from core.text import UTHMANI_BASMALA
    from modules.layouts import _azhar_uthmani_basmala_text

    assert _azhar_uthmani_basmala_text({
        'line_text': 'بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ',
        'surah_number': 97,
    }) == UTHMANI_BASMALA
    assert _azhar_uthmani_basmala_text({
        'line_text': '',
        'surah_number': 1,
    }) == f'{UTHMANI_BASMALA} ١'


def test_azhar_line_break_and_progress(client, restore_azhar_layout_db):
    page = client.get('/api/layout-studio/azhar/page/2').get_json()
    ayah_line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words') and len(line['words']) > 2
    )
    mid = ayah_line['words'][len(ayah_line['words']) // 2]
    before_last = ayah_line['last_word_id']
    r = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 2,
        'line_number': ayah_line['line_number'],
        'word_id': mid['word_index'],
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert body.get('undo_available', 0) >= 1
    updated = body['page']
    updated_line = next(
        line for line in updated['lines']
        if line['line_number'] == ayah_line['line_number']
    )
    assert updated_line['last_word_id'] == mid['word_index']
    fatiha = client.get('/api/azhar-layout/page/2').get_json()
    ayah_words = [
        w['word_index']
        for ln in fatiha['lines'] if ln['line_type'] == 'ayah'
        for w in (ln.get('words') or [])
    ]
    assert ayah_words[0] == 8
    assert ayah_words[-1] == 38
    assert max(ayah_words) == 38
    page3 = client.get('/api/azhar-layout/page/3').get_json()
    first_ayah = next(ln for ln in page3['lines'] if ln['line_type'] == 'ayah')
    assert first_ayah['first_word_id'] == 45

    undone = client.post('/api/layout-studio/azhar/undo', json={'page_number': 2})
    assert undone.status_code == 200
    restored = next(
        line for line in undone.get_json()['page']['lines']
        if line['line_number'] == ayah_line['line_number']
    )
    assert restored['last_word_id'] == before_last

    prog = client.post('/api/azhar-layout/progress', json={'page_number': 2, 'reviewed': True})
    assert prog.status_code == 200
    listed = client.get('/api/layout-studio/azhar/progress').get_json()
    assert 2 in listed['reviewed_pages']


def test_pull_next_word_across_page_and_undo(client, restore_azhar_layout_db):
    before_492 = client.get('/api/layout-studio/azhar/page/492').get_json()
    before_493 = client.get('/api/layout-studio/azhar/page/493').get_json()
    target = [
        line for line in before_492['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    following = next(
        line for line in before_493['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    )
    assert target['surah_number'] == following['surah_number']
    moved = following['words'][0]['word_index']

    def page_words(payload):
        return [
            word['word_index']
            for line in payload['lines'] if line['line_type'] == 'ayah'
            for word in (line.get('words') or [])
        ]

    before_stream = page_words(before_492) + page_words(before_493)
    result = client.post('/api/layout-studio/azhar/pull-next-word', json={
        'page_number': 492,
        'line_number': target['line_number'],
    })
    assert result.status_code == 200, result.get_json()
    body = result.get_json()
    assert body['moved_word_id'] == moved
    assert body['from_page'] == 493
    updated_target = next(
        line for line in body['page']['lines']
        if line['line_number'] == target['line_number']
    )
    assert updated_target['last_word_id'] == moved

    after_493 = client.get('/api/layout-studio/azhar/page/493').get_json()
    assert moved not in page_words(after_493)
    assert page_words(body['page']) + page_words(after_493) == before_stream

    undone = client.post(
        '/api/layout-studio/azhar/undo', json={'page_number': 492},
    )
    assert undone.status_code == 200
    restored_493 = client.get('/api/layout-studio/azhar/page/493').get_json()
    assert page_words(undone.get_json()['page']) == page_words(before_492)
    assert page_words(restored_493) == page_words(before_493)


def test_pull_next_word_refuses_surah_boundary(client, restore_azhar_layout_db):
    page = client.get('/api/layout-studio/azhar/page/494').get_json()
    target = [
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    result = client.post('/api/layout-studio/azhar/pull-next-word', json={
        'page_number': 494,
        'line_number': target['line_number'],
    })
    assert result.status_code == 400
    assert 'سور' in (result.get_json().get('error') or '')


def test_transfer_complete_last_line_to_next_page_and_undo(
    client, restore_azhar_layout_db,
):
    before_493 = client.get(
        '/api/layout-studio/azhar/page/493'
    ).get_json()
    before_494 = client.get(
        '/api/layout-studio/azhar/page/494'
    ).get_json()
    target = next(
        line for line in before_493['lines']
        if line['line_number'] == before_493['lines_per_page']
    )
    assert target['line_type'] == 'ayah'
    assert target.get('words')

    def page_words(payload):
        return [
            word['word_index']
            for line in payload['lines']
            if line['line_type'] == 'ayah'
            for word in (line.get('words') or [])
        ]

    before_stream = page_words(before_493) + page_words(before_494)
    moved_words = [
        word['word_index'] for word in target['words']
    ]
    result = client.post(
        '/api/layout-studio/azhar/transfer-line',
        json={
            'page_number': 493,
            'line_number': target['line_number'],
        },
    )
    assert result.status_code == 200, result.get_json()
    body = result.get_json()
    assert body['crossed_page'] is True
    assert body['to_page'] == 494
    assert body['undo_available'] >= 1

    after_493 = body['page']
    after_494 = client.get(
        '/api/layout-studio/azhar/page/494'
    ).get_json()
    assert len(after_493['lines']) == 15
    assert len(after_494['lines']) == 15
    assert all(
        line['line_type'] == 'ayah' and not line.get('words')
        for line in after_494['lines'][-2:]
    )
    source_last = after_493['lines'][-1]
    assert source_last['line_type'] == 'ayah'
    assert not source_last.get('words')
    destination_first = after_494['lines'][0]
    assert [
        word['word_index'] for word in destination_first.get('words') or []
    ] == moved_words
    assert page_words(after_493) + page_words(after_494) == before_stream

    undone = client.post(
        '/api/layout-studio/azhar/undo',
        json={'page_number': 493},
    )
    assert undone.status_code == 200, undone.get_json()
    restored_494 = client.get(
        '/api/layout-studio/azhar/page/494'
    ).get_json()
    assert page_words(undone.get_json()['page']) == page_words(before_493)
    assert page_words(restored_494) == page_words(before_494)


def test_header_down_cascades_following_rows_and_undo(
    client, restore_azhar_layout_db,
):
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE

    def positions():
        with sqlite3.connect(AZHAR_LAYOUT_DATABASE) as conn:
            return conn.execute(
                '''
                SELECT id, page_number, line_number, line_type, is_centered,
                       first_word_id, last_word_id, surah_number, line_text
                FROM pages
                WHERE page_number IN (493, 494)
                ORDER BY page_number, line_number
                '''
            ).fetchall()

    before = positions()
    source_last = next(
        row for row in before
        if row[1] == 493 and row[2] == 15
    )
    header = next(
        row for row in before
        if row[1] == 493 and row[3] == 'surah_name'
    )
    result = client.post(
        '/api/layout-studio/azhar/header-move',
        json={
            'page_number': 493,
            'line_number': header[2],
            'direction': 'down',
        },
    )
    assert result.status_code == 200, result.get_json()
    body = result.get_json()
    assert body['cascaded'] is True
    assert body['moved_to_page'] == 493
    assert body['moved_to_line'] == header[2] + 1

    after = positions()
    assert len([row for row in after if row[1] == 493]) == 15
    assert len([row for row in after if row[1] == 494]) == 15
    page494_tail = [
        row for row in after
        if row[1] == 494 and row[2] in (14, 15)
    ]
    assert len(page494_tail) == 2
    assert all(
        row[3] == 'ayah' and row[5] is None and row[6] is None
        for row in page494_tail
    )
    inserted = next(
        row for row in after
        if row[1] == 493 and row[2] == header[2]
    )
    moved_header = next(row for row in after if row[0] == header[0])
    spilled = next(row for row in after if row[0] == source_last[0])
    assert inserted[3] == 'ayah'
    assert inserted[5] is None and inserted[6] is None
    assert moved_header[1:4] == (493, header[2] + 1, 'surah_name')
    assert spilled[1] == 494 and spilled[2] == 1

    undone = client.post(
        '/api/layout-studio/azhar/undo',
        json={'page_number': 493},
    )
    assert undone.status_code == 200, undone.get_json()
    assert positions() == before


def test_azhar_intentional_trailing_lines_are_registered_and_guarded(
    client, restore_azhar_layout_db,
):
    editions = client.get('/api/layout-studio/editions').get_json()['editions']
    azhar = next(item for item in editions if item['id'] == 'azhar')
    assert azhar['protected_trailing_lines'] == {
        '494': 2,
        '516': 2,
        '518': 2,
        '521': 2,
        '522': 2,
    }
    for page_number in (494, 516, 518, 521, 522):
        page = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        ).get_json()
        assert len(page['lines']) == 15
        assert [line['line_number'] for line in page['lines'][-2:]] == [14, 15]

    page_494 = client.get(
        '/api/layout-studio/azhar/page/494'
    ).get_json()
    assert all(not line.get('words') for line in page_494['lines'][-2:])

    before_516 = client.get('/api/layout-studio/azhar/page/516').get_json()
    before_517 = client.get('/api/layout-studio/azhar/page/517').get_json()
    result = client.post(
        '/api/layout-studio/azhar/transfer-line',
        json={'page_number': 516, 'line_number': 15},
    )
    assert result.status_code == 200, result.get_json()
    moved = result.get_json()
    assert moved['from_page'] == 516
    assert moved['to_page'] == 517

    undone = client.post(
        '/api/layout-studio/azhar/undo',
        json={'page_number': 516},
    )
    assert undone.status_code == 200, undone.get_json()
    assert client.get(
        '/api/layout-studio/azhar/page/516'
    ).get_json()['lines'] == before_516['lines']
    assert client.get(
        '/api/layout-studio/azhar/page/517'
    ).get_json()['lines'] == before_517['lines']


def test_azhar_reviewer_confirmed_tail_page_starts(client):
    expected = {
        519: ('surah_name', 100),
        521: ('surah_name', 104),
        522: ('surah_name', 106),
        523: ('surah_name', 108),
        524: ('basmallah', 110),
        525: ('surah_name', 113),
    }
    for page_number, (line_type, surah_number) in expected.items():
        page = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        ).get_json()
        first = page['lines'][0]
        assert first['line_number'] == 1
        assert first['line_type'] == line_type
        assert first['surah_number'] == surah_number


def test_azhar_reviewer_confirmed_pages_511_and_517(client):
    page_511 = client.get(
        '/api/layout-studio/azhar/page/511'
    ).get_json()['lines']
    assert (page_511[0]['line_type'], page_511[0]['surah_number']) == (
        'surah_name', 89,
    )
    assert page_511[-1]['last_word_id'] == 83267
    assert page_511[-1]['words'][-1]['text'] == 'قَدَّمۡتُ'

    page_517 = client.get(
        '/api/layout-studio/azhar/page/517'
    ).get_json()['lines']
    assert (page_517[0]['line_type'], page_517[0]['surah_number']) == (
        'surah_name', 97,
    )
    assert page_517[-1]['last_word_id'] == 83920
    assert page_517[-1]['words'][-2]['text'] == 'وَذَٰلِكَ'
    assert page_517[-1]['words'][-1]['text'] == 'دِينُ'


def test_azhar_reviewer_confirmed_page_endings(client):
    expected = {
        505: (82458, ['إِنَّ', 'ٱلۡأَبۡرَارَ']),
        506: (82580, ['٦', 'فَأَمَّا']),
        507: (82718, ['شُهُودࣱ', '٧']),
        508: (82845, ['فَلۡيَنظُرِ', 'ٱلۡإِنسَٰنُ']),
        509: (82990, ['خَيۡرࣱ', 'وَأَبۡقَىٰٓ', '١٧']),
        514: (83617, ['٧', 'وَوَجَدَكَ']),
        515: (83711, ['فَلَهُمۡ', 'أَجۡرٌ']),
    }
    for page_number, (last_word_id, ending) in expected.items():
        lines = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        ).get_json()['lines']
        assert len(lines) == 15
        assert all(
            line['line_type'] != 'ayah' or line.get('words')
            for line in lines
        )
        assert lines[-1]['last_word_id'] == last_word_id
        assert [
            word['text'] for word in lines[-1]['words'][-len(ending):]
        ] == ending


def test_azhar_amiri_text_normalizes_unsupported_dammatan(client):
    page = client.get('/api/layout-studio/azhar/page/510').get_json()
    line = next(
        line for line in page['lines']
        if any(word.get('word_key') == '88:14:1' for word in line['words'])
    )
    words = {
        word['word_key']: word['text']
        for word in line['words']
        if word.get('word_key') in {'88:14:1', '88:14:2'}
    }

    assert words == {
        '88:14:1': 'وَأَكۡوَابࣱ',
        '88:14:2': 'مَّوۡضُوعَةࣱ',
    }
    assert '\u065e' not in line['display_text']


def test_azhar_amiri_font_covers_normalized_quran_script():
    import sqlite3

    from fontTools.ttLib import TTFont

    from core.config import QURAN_SCRIPT_DATABASE
    from core.text import normalize_amiri_quran_text

    font = TTFont(PROJECT_ROOT / 'static/fonts/amiri_quran.woff2')
    supported_codepoints = {
        codepoint
        for table in font['cmap'].tables
        for codepoint in table.cmap
    }
    with sqlite3.connect(QURAN_SCRIPT_DATABASE) as conn:
        texts = (
            row[0]
            for row in conn.execute('SELECT text FROM words')
            if row[0]
        )
        used_codepoints = {
            ord(character)
            for text in texts
            for character in normalize_amiri_quran_text(text)
        }

    assert 0x08F1 in used_codepoints
    assert used_codepoints <= supported_codepoints


def test_amiri_reader_dataset_uses_font_safe_open_dammatan():
    from core.datasets import amiri_quran_data

    text = ' '.join(
        verse.get('text', '')
        for verse in amiri_quran_data.values()
        if isinstance(verse, dict)
    )

    assert '\u065e' not in text
    assert '\u08f1' in text


def test_azhar_review_alignment_migration_preserves_word_stream(tmp_path):
    import shutil
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE
    from pipeline.align_azhar_review_endings import align_review_endings

    database = tmp_path / 'azhar-review-alignment.db'
    shutil.copy2(AZHAR_LAYOUT_DATABASE, database)

    result = align_review_endings(str(database))
    assert result['endings'][514] == 83617

    with sqlite3.connect(database) as conn:
        page_513_end = conn.execute(
            '''
            SELECT last_word_id FROM pages
            WHERE page_number = 513 AND line_type = 'ayah'
              AND last_word_id IS NOT NULL
            ORDER BY line_number DESC LIMIT 1
            '''
        ).fetchone()[0]
        page_514_start = conn.execute(
            '''
            SELECT first_word_id FROM pages
            WHERE page_number = 514 AND line_type = 'ayah'
              AND first_word_id IS NOT NULL
            ORDER BY line_number LIMIT 1
            '''
        ).fetchone()[0]

    assert (page_513_end, page_514_start) == (83497, 83498)


def test_line_center_is_undoable(client, restore_azhar_layout_db):
    import json
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE

    page = client.get('/api/layout-studio/azhar/page/492').get_json()
    line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    )
    original = bool(line['is_centered'])
    result = client.post('/api/layout-studio/azhar/line-center', json={
        'page_number': 492,
        'line_number': line['line_number'],
        'is_centered': not original,
    })
    assert result.status_code == 200, result.get_json()
    updated = next(
        item for item in result.get_json()['page']['lines']
        if item['line_number'] == line['line_number']
    )
    assert bool(updated['is_centered']) is not original

    conn = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        snapshot = conn.execute(
            'SELECT snapshot FROM azhar_layout_undo ORDER BY id DESC LIMIT 1'
        ).fetchone()[0]
        assert all('is_centered' in row for row in json.loads(snapshot)['rows'])
    finally:
        conn.close()

    undone = client.post(
        '/api/layout-studio/azhar/undo', json={'page_number': 492},
    )
    assert undone.status_code == 200
    restored = next(
        item for item in undone.get_json()['page']['lines']
        if item['line_number'] == line['line_number']
    )
    assert bool(restored['is_centered']) is original


def test_azhar_undo_is_page_scoped(client, restore_azhar_layout_db):
    """Fatiha edits snapshot only pages 2–3 (not the whole mushaf)."""
    import json
    import sqlite3

    from core.config import AZHAR_LAYOUT_DATABASE

    page = client.get('/api/layout-studio/azhar/page/2').get_json()
    ayah_line = next(
        line for line in page['lines']
        if line['line_type'] == 'ayah' and line.get('words') and len(line['words']) > 2
    )
    mid = ayah_line['words'][len(ayah_line['words']) // 2]
    r = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 2,
        'line_number': ayah_line['line_number'],
        'word_id': mid['word_index'],
    })
    assert r.status_code == 200

    conn = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        row = conn.execute(
            'SELECT snapshot FROM azhar_layout_undo ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert isinstance(payload, dict)
        assert payload['page_from'] == 2
        assert payload['page_to'] == 3
        pages = {int(r['page_number']) for r in payload['rows']}
        assert pages <= {2, 3}
        assert 2 in pages
        assert len(payload['rows']) < 80
    finally:
        conn.close()

    status = client.get('/api/layout-studio/azhar/undo-status?page_number=2').get_json()
    assert status['undo_available'] >= 1
    other = client.get('/api/layout-studio/azhar/undo-status?page_number=10').get_json()
    assert other['undo_available'] == 0

    # A page-scoped undo must never consume another page's latest edit.
    wrong_page = client.post(
        '/api/layout-studio/azhar/undo',
        json={'page_number': 10},
    )
    assert wrong_page.status_code == 400
    still_available = client.get(
        '/api/layout-studio/azhar/undo-status?page_number=2'
    ).get_json()
    assert still_available['undo_available'] >= 1


def test_line_break_does_not_spill_into_next_surah(client, restore_azhar_layout_db):
    """Page 64: Al-Imran ends mid-page; a break must not push words onto An-Nisa."""
    page = client.get('/api/layout-studio/azhar/page/64').get_json()
    line3 = next(
        ln for ln in page['lines']
        if ln['line_number'] == 3 and ln['line_type'] == 'ayah'
    )
    assert len(line3['words']) > 2
    mid = line3['words'][1]

    def imran_ayah_ids(payload):
        ids = []
        for ln in payload['lines']:
            if ln['line_type'] in ('surah_name', 'surah_info', 'basmallah'):
                break
            if ln['line_type'] == 'ayah':
                ids.extend(w['word_index'] for w in (ln.get('words') or []))
        return ids

    before_ids = imran_ayah_ids(page)

    nisa_line = next(
        ln for ln in page['lines']
        if ln['line_type'] == 'ayah' and ln.get('surah_number') == 4
    )
    assert nisa_line['first_word_id'] == 10169
    nisa_line_no = nisa_line['line_number']

    r = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 64,
        'line_number': 3,
        'word_id': mid['word_index'],
        'role': 'end',
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['ok'] is True

    after = client.get('/api/layout-studio/azhar/page/64').get_json()
    updated_l3 = next(ln for ln in after['lines'] if ln['line_number'] == 3)
    assert updated_l3['last_word_id'] == mid['word_index']

    assert imran_ayah_ids(after) == before_ids  # same words, redistributed — none deleted

    nisa_after = next(ln for ln in after['lines'] if ln['line_number'] == nisa_line_no)
    assert nisa_after['first_word_id'] == 10169
    nisa_words = [w['word_index'] for w in (nisa_after.get('words') or [])]
    assert all(w >= 10169 for w in nisa_words)
    assert not any(w <= 10162 for w in nisa_words)

    # Last ayah of Al-Imran before the banner: shortening would drop words — reject.
    last_imran = None
    for ln in after['lines']:
        if ln['line_type'] in ('surah_name', 'surah_info', 'basmallah'):
            break
        if ln['line_type'] == 'ayah':
            last_imran = ln
    assert last_imran and len(last_imran['words']) > 2
    bad = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 64,
        'line_number': last_imran['line_number'],
        'word_id': last_imran['words'][1]['word_index'],
        'role': 'end',
    })
    assert bad.status_code == 400
    assert 'سور' in (bad.get_json().get('error') or '')

    # Merge across the surah header must be rejected.
    bad_merge = client.post('/api/layout-studio/azhar/merge-line', json={
        'page_number': 64,
        'line_number': last_imran['line_number'],
    })
    assert bad_merge.status_code == 400
    assert 'سور' in (bad_merge.get_json().get('error') or '')


def test_azhar_short_page_geometry(client):
    editions = client.get('/api/layout-studio/editions').get_json()
    azhar = next(e for e in editions['editions'] if e['id'] == 'azhar')
    assert azhar['short_pages'] == {'2': 6, '3': 5}

    p2 = client.get('/api/layout-studio/azhar/page/2').get_json()
    assert len(p2['lines']) == 6
    assert p2['lines_per_page'] == 6
    p3 = client.get('/api/layout-studio/azhar/page/3').get_json()
    assert len(p3['lines']) == 5
    assert p3['lines_per_page'] == 5


def test_universal_layout_profile_and_fixed_page_boundary(
    client, restore_azhar_layout_db,
):
    current = client.get('/api/layout-studio/azhar/profile')
    assert current.status_code == 200
    body = current.get_json()
    assert body['profile'] == {
        'lines_per_page': 15,
        'page_end_mode': 'continuous',
        'surah_name_lines': 1,
        'surah_info_lines': 1,
        'basmallah_lines': 1,
        'full_banner_lines': 3,
    }
    presets = {preset['id']: preset for preset in body['presets']}
    assert {'azhar', 'madinah_qatar', 'shemrly'} <= set(presets)
    assert presets['madinah_qatar']['profile']['page_end_mode'] == 'ayah'
    assert presets['madinah_qatar']['profile']['surah_info_lines'] == 0

    invalid = client.post('/api/layout-studio/azhar/profile', json={
        'lines_per_page': 3,
        'page_end_mode': 'ayah',
        'surah_name_lines': 1,
        'surah_info_lines': 1,
        'basmallah_lines': 1,
    })
    assert invalid.status_code == 400
    assert 'at least one ayah line' in invalid.get_json()['error']

    saved = client.post('/api/layout-studio/azhar/profile', json={
        'profile': {
            'lines_per_page': 15,
            'page_end_mode': 'ayah',
            'surah_name_lines': 1,
            'surah_info_lines': 1,
            'basmallah_lines': 1,
        },
    })
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()['profile']['page_end_mode'] == 'ayah'

    page = client.get('/api/layout-studio/azhar/page/495').get_json()
    assert page['layout_profile']['page_end_mode'] == 'ayah'
    assert page['occupied_line_slots'] == 15
    assert all(line['slot_span'] == 1 for line in page['lines'])

    before = client.get('/api/layout-studio/azhar/page/492').get_json()
    last = [
        line for line in before['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    next_before = client.get('/api/layout-studio/azhar/page/493').get_json()

    def word_stream(payload):
        return [
            word['word_index']
            for line in payload['lines'] if line['line_type'] == 'ayah'
            for word in (line.get('words') or [])
        ]

    # Ayah mode still allows an intentional one-word page-boundary correction.
    pushed = client.post('/api/layout-studio/azhar/push-last-word', json={
        'page_number': 492,
        'line_number': last['line_number'],
    })
    assert pushed.status_code == 200, pushed.get_json()
    assert pushed.get_json()['crossed_page'] is True
    moved = pushed.get_json()['moved_word_id']
    assert moved not in word_stream(pushed.get_json()['page'])
    assert word_stream(
        client.get('/api/layout-studio/azhar/page/493').get_json()
    )[0] == moved

    last_after = [
        line for line in pushed.get_json()['page']['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    pulled = client.post('/api/layout-studio/azhar/pull-next-word', json={
        'page_number': 492,
        'line_number': last_after['line_number'],
    })
    assert pulled.status_code == 200, pulled.get_json()
    assert word_stream(pulled.get_json()['page']) == word_stream(before)
    assert word_stream(
        client.get('/api/layout-studio/azhar/page/493').get_json()
    ) == word_stream(next_before)

    target = next(
        line for line in before['lines']
        if line['line_type'] == 'ayah' and len(line.get('words') or []) > 3
    )
    cut = target['words'][1]['word_index']
    edited = client.post('/api/layout-studio/azhar/line-break', json={
        'page_number': 492,
        'line_number': target['line_number'],
        'word_id': cut,
        'role': 'end',
    })
    assert edited.status_code == 200, edited.get_json()
    assert word_stream(edited.get_json()['page']) == word_stream(before)
    next_after = client.get('/api/layout-studio/azhar/page/493').get_json()
    assert word_stream(next_after) == word_stream(next_before)


def test_azhar_surah_header_takes_three_lines(client):
    """Every page is 15 lines; a leading banner uses 3 of them (12 ayah left).

    Page 495 (الانسان): name + info + basmala + 12 ayah.
    Page 496 (continuation): still 15 ayah lines — never left short after spill.
    """
    p494 = client.get('/api/layout-studio/azhar/page/494').get_json()
    assert p494['lines']
    assert p494['lines'][-1]['line_type'] != 'surah_name'
    assert len(p494['lines']) == 15

    p495 = client.get('/api/layout-studio/azhar/page/495').get_json()
    types = [ln['line_type'] for ln in p495['lines']]
    assert types[:3] == ['surah_name', 'surah_info', 'basmallah']
    assert len(p495['lines']) == 15
    assert p495['lines_per_page'] == 15
    ayah = [ln for ln in p495['lines'] if ln['line_type'] == 'ayah']
    assert len(ayah) == 12
    assert (p495['lines'][0].get('display_text') or '').startswith('سورة')
    info = p495['lines'][1].get('display_text') or ''
    assert 'آياتها' in info
    assert info.startswith('مكية') or info.startswith('مدنية')

    p496 = client.get('/api/layout-studio/azhar/page/496').get_json()
    assert len(p496['lines']) == 15
    assert p496['lines_per_page'] == 15
    assert all(ln['line_type'] == 'ayah' for ln in p496['lines'])

    # Mid-page banner (e.g. النبأ on 498): name+info+basmala still inside 15,
    # with overflow ayah spilled onto the next page.
    p498 = client.get('/api/layout-studio/azhar/page/498').get_json()
    assert len(p498['lines']) == 15
    types498 = [ln['line_type'] for ln in p498['lines']]
    assert 'surah_name' in types498
    assert 'surah_info' in types498
    assert 'basmallah' in types498
    assert types498.count('ayah') == 12
    name_i = types498.index('surah_name')
    assert types498[name_i:name_i + 3] == ['surah_name', 'surah_info', 'basmallah']

    p499 = client.get('/api/layout-studio/azhar/page/499').get_json()
    assert len(p499['lines']) == 15

    # Same-page starts (e.g. المزمل) also get the info line and stay at 15.
    p490 = client.get('/api/layout-studio/azhar/page/490').get_json()
    assert [ln['line_type'] for ln in p490['lines'][:3]] == [
        'surah_name', 'surah_info', 'basmallah',
    ]
    assert len([ln for ln in p490['lines'] if ln['line_type'] == 'ayah']) == 12
    assert len(p490['lines']) == 15


def test_azhar_repairs_displaced_surah_boundaries(client):
    """Numeric Shemrly blocks must not reorder Quran text around three boundaries."""

    def assert_canonical_page(page_number, outgoing, incoming):
        payload = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        ).get_json()
        assert len(payload['lines']) == 15
        word_surahs = []
        for line in payload['lines']:
            if line['line_type'] != 'ayah':
                continue
            actual = {int(word['surah']) for word in (line.get('words') or [])}
            assert actual == {int(line['surah_number'])}
            word_surahs.extend(actual)
        assert word_surahs == sorted(word_surahs)
        assert outgoing in word_surahs
        assert incoming in word_surahs

        types = [line['line_type'] for line in payload['lines']]
        name_i = next(
            i for i, line in enumerate(payload['lines'])
            if line['line_type'] == 'surah_name'
            and int(line['surah_number']) == incoming
        )
        assert types[name_i:name_i + 3] == [
            'surah_name', 'surah_info', 'basmallah',
        ]

    # Al-Baqarah tail precedes Aal-Imran, and Sad tail precedes Az-Zumar.
    assert_canonical_page(42, 2, 3)
    assert_canonical_page(385, 38, 39)

    # Al-Hashr / Al-Mumtahanah was ordered but carried incorrect line metadata
    # and an incomplete banner.
    assert_canonical_page(465, 59, 60)

    # Spilling Al-Insan onto page 496 must not retain Al-Mursalat metadata.
    page496 = client.get('/api/layout-studio/azhar/page/496').get_json()
    assert all(
        line['surah_number'] == 76
        and {word['surah'] for word in line.get('words') or []} == {76}
        for line in page496['lines']
        if line['line_type'] == 'ayah'
    )


def test_azhar_completes_missing_banners_without_orphans(client):
    for page_number, surah in ((465, 60), (515, 95), (517, 97)):
        payload = client.get(
            f'/api/layout-studio/azhar/page/{page_number}'
        ).get_json()
        lines = payload['lines']
        name_i = next(
            i for i, line in enumerate(lines)
            if line['line_type'] == 'surah_name'
            and int(line['surah_number']) == surah
        )
        assert [line['line_type'] for line in lines[name_i:name_i + 3]] == [
            'surah_name', 'surah_info', 'basmallah',
        ]
        assert any(line['line_type'] == 'ayah' for line in lines[name_i + 3:])

    tawbah = client.get('/api/layout-studio/azhar/page/153').get_json()
    name_i = next(
        i for i, line in enumerate(tawbah['lines'])
        if line['line_type'] == 'surah_name' and line['surah_number'] == 9
    )
    assert tawbah['lines'][name_i + 1]['line_type'] == 'surah_info'
    assert tawbah['lines'][name_i + 2]['line_type'] == 'ayah'


def test_layout_engine_surah_fence_unit():
    from modules.layout_engine import ayah_segment_slots, is_surah_separator

    lines = [
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 3},
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 4},
        {'line_type': 'surah_name', 'page_number': 64, 'line_number': 5},
        {'line_type': 'surah_info', 'page_number': 64, 'line_number': 6},
        {'line_type': 'basmallah', 'page_number': 64, 'line_number': 7},
        {'line_type': 'ayah', 'page_number': 64, 'line_number': 8},
    ]
    assert is_surah_separator(lines[2])
    assert is_surah_separator(lines[3])
    assert ayah_segment_slots(lines, 0) == [0, 1]
    assert ayah_segment_slots(lines, 1) == [1]
    assert ayah_segment_slots(lines, 5) == [5]


def test_layout_engine_module_imports():
    from modules import layout_engine
    from modules import azhar_layout
    from modules import layout_editions
    from modules import layout_studio

    assert callable(layout_engine.cascade_from)
    assert callable(layout_engine.push_undo)
    assert callable(layout_engine.ayah_segment_slots)
    assert callable(azhar_layout._cascade_from)
    assert layout_editions.get_edition('azhar') is not None
    assert callable(layout_studio.render_studio)


def test_seed_script_warns_on_force():
    script = (PROJECT_ROOT / 'pipeline' / 'seed_azhar_layout_db.py').read_text(encoding='utf-8')
    assert 'DESTRUCTIVE WARNING' in script
    assert 'wipe' in script.lower() or 'WIPE' in script
    db = PROJECT_ROOT / 'data' / 'mushaf-azhar-layout.db'
    assert db.is_file()


def test_seed_script_exists():
    script = PROJECT_ROOT / 'pipeline' / 'seed_azhar_layout_db.py'
    assert script.is_file()
    db = PROJECT_ROOT / 'data' / 'mushaf-azhar-layout.db'
    assert db.is_file()
