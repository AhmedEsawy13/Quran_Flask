"""Bahrain editor edition uses Madinah 1421 (QPC v2) layout + Digital Khatt font."""
import os
import shutil
import sqlite3
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def restore_bahrain_layout_db(tmp_path):
    """Mutating tests must not consume a reviewer's saved Bahrain work."""
    from core.config import BAHRAIN_LAYOUT_DATABASE

    db = Path(BAHRAIN_LAYOUT_DATABASE)
    backup = tmp_path / db.name
    shutil.copy2(db, backup)
    try:
        yield
    finally:
        shutil.copy2(backup, db)


def test_editor_ui_references_digital_khatt_for_bahrain():
    css = (PROJECT_ROOT / 'static/css/mushaf_editor.css').read_text(encoding='utf-8')
    js = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    html = (PROJECT_ROOT / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    assert 'digitalkhatt.woff2' in css
    assert "font-family: 'Digital Khatt'" in css
    assert 'ed-font-bahrain' in css
    assert "classList.toggle('ed-font-bahrain', state.edition === 'البحرين')" in js
    assert 'digitalKhattFeatureCandidates' in js
    assert 'data-edition="البحرين"' in html
    assert 'مصحف البحرين' in html
    assert 'fonts/digitalkhatt.woff2' in html
    assert (PROJECT_ROOT / 'static/fonts/digitalkhatt.woff2').is_file()
    assert (PROJECT_ROOT / 'data/digital-khatt-15-lines.db').is_file()


def test_bahrain_in_editor_editions():
    from core.config import EDITOR_EDITIONS, CLOUD_EDITOR_EDITIONS
    assert 'البحرين' in EDITOR_EDITIONS
    assert 'البحرين' in CLOUD_EDITOR_EDITIONS


def test_bahrain_spread_api_uses_studio_layout_and_digital_khatt(client, monkeypatch):
    from core.config import BAHRAIN_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    data = client.get('/api/mushaf-editor/spread/1?edition=البحرين').get_json()
    assert data['edition'] == 'البحرين'
    assert data['right']['font_name'] == 'Digital Khatt'
    if Path(BAHRAIN_LAYOUT_DATABASE).is_file():
        assert data['right']['source'] == 'mushaf_bahrain'
        assert 'البحرين' in (data['right'].get('layout_name') or '')
    else:
        assert data['right']['source'] == 'qpc_v2'
    if data.get('left'):
        assert data['left']['font_name'] == 'Digital Khatt'
        assert data['left']['source'] == data['right']['source']


def test_bahrain_waqf_editor_follows_studio_line_breaks(client, monkeypatch):
    """Waqf-editor spread must mirror Layout Studio's Bahrain project lines."""
    from core.config import BAHRAIN_LAYOUT_DATABASE

    if not Path(BAHRAIN_LAYOUT_DATABASE).is_file():
        return

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)

    studio = client.get('/api/layout-studio/bahrain/page/358').get_json()
    editor = client.get('/api/mushaf-editor/spread/179?edition=البحرين').get_json()
    # spread 179 → right page 357, left page 358
    left = editor['left']
    assert left['page_number'] == 358
    assert left['source'] == 'mushaf_bahrain'

    def ayah_bounds(payload):
        ayah = [ln for ln in payload['lines'] if ln['line_type'] == 'ayah']
        return (
            [(ln['line_number'], ln['first_word_id'], ln['last_word_id']) for ln in ayah],
            len(payload['lines']),
        )

    assert ayah_bounds(left) == ayah_bounds(studio)


def test_bahrain_ref_route_and_ui_wiring(client, monkeypatch):
    from core.config import BAHRAIN_REF_PDF_URL
    from modules.layout_editions import BAHRAIN

    js = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    pdf_helper = (PROJECT_ROOT / 'static/js/athar-pdf-ref.js').read_text(encoding='utf-8')
    html = (PROJECT_ROOT / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    assert "'البحرين'" in js
    assert "type: 'pdf'" in js
    assert BAHRAIN_REF_PDF_URL in js
    assert 'pdfPageOffset: 5' in js
    assert 'AtharPdfRef' in js
    assert 'AtharPdfRef' in pdf_helper
    assert 'athar-pdf-ref.js' in html
    assert '/api/mushaf-editor/ref/bahrain/' not in js

    ref = BAHRAIN.client_config()['ref']
    assert ref['type'] == 'pdf'
    assert ref['pdfUrl'] == BAHRAIN_REF_PDF_URL
    assert ref['pdfPageOffset'] == 5
    assert not ref.get('imageTemplate')

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    studio_resp = client.get('/layout-studio/bahrain')
    studio_html = studio_resp.get_data(as_text=True)
    assert 'athar-pdf-ref.js' in studio_html
    assert BAHRAIN_REF_PDF_URL in studio_html
    assert '/api/layout-studio/bahrain/reference/{page}.jpg' not in studio_html
    csp = studio_resp.headers.get('Content-Security-Policy', '')
    assert 'd1.islamhouse.com' in csp
    assert 'blob:' in csp
    assert 'cdn.jsdelivr.net' in csp


def test_bahrain_layout_project_is_isolated_and_complete():
    from core.config import BAHRAIN_LAYOUT_DATABASE, QPC_V2_LAYOUT_DATABASE

    assert BAHRAIN_LAYOUT_DATABASE != QPC_V2_LAYOUT_DATABASE
    assert Path(BAHRAIN_LAYOUT_DATABASE).is_file()

    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as project:
        assert project.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert project.execute(
            'SELECT COUNT(DISTINCT page_number) FROM pages'
        ).fetchone()[0] == 604
        # Reviewed layouts may intentionally gain/consume structural rows
        # (for example Bahrain 548 has 14 rows rather than the QPC seed's 15).
        assert 9000 <= project.execute(
            'SELECT COUNT(*) FROM pages'
        ).fetchone()[0] <= 9100
        assert project.execute('SELECT COUNT(*) FROM words').fetchone()[0] == 83665
        tables = {
            row[0] for row in project.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {'bahrain_layout_undo', 'bahrain_layout_progress'} <= tables

    with sqlite3.connect(QPC_V2_LAYOUT_DATABASE) as source:
        source_tables = {
            row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert 'bahrain_layout_undo' not in source_tables
        assert 'bahrain_layout_progress' not in source_tables


def test_bahrain_layout_studio_registry_shell_and_pages(client, monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')

    editions = client.get('/api/layout-studio/editions').get_json()
    bahrain = next(e for e in editions['editions'] if e['id'] == 'bahrain')
    assert bahrain['profile']['page_end_mode'] == 'ayah'
    assert bahrain['profile']['lines_per_page'] == 15
    assert bahrain['short_pages'] == {'1': 8, '2': 8}

    shell = client.get('/layout-studio/bahrain')
    assert shell.status_code == 200
    html = shell.get_data(as_text=True)
    assert 'مصحف البحرين' in html
    assert '/layout-studio/azhar' in html
    assert '/layout-studio/bahrain' in html
    assert 'd1.islamhouse.com/data/ar/ih_books/single_02/ar-mushaf-albahrains.pdf' in html
    assert 'az-ref-frame' in html
    assert 'Digital Khatt' in html

    page1 = client.get('/api/layout-studio/bahrain/page/1').get_json()
    assert page1['source'] == 'layout_studio_bahrain'
    assert page1['font_name'] == 'Digital Khatt'
    assert page1['lines_per_page'] == 8
    assert len(page1['lines']) == 8
    assert page1['layout_profile']['page_end_mode'] == 'ayah'

    page3 = client.get('/api/layout-studio/bahrain/page/3').get_json()
    assert page3['lines_per_page'] == 15
    assert len(page3['lines']) == 15

    page358 = client.get('/api/layout-studio/bahrain/page/358').get_json()
    ayah_lines = [
        line for line in page358['lines'] if line['line_type'] == 'ayah'
    ]
    assert ayah_lines[0]['first_word_id'] == 48874
    assert ayah_lines[-1]['last_word_id'] == 48994

    by_ayah = client.get('/api/layout-studio/bahrain/page-by-ayah/2/255')
    assert by_ayah.status_code == 200
    assert by_ayah.get_json()['page_number'] == 42


def test_bahrain_line_edit_undo_and_fixed_page_boundary(
    client, monkeypatch, restore_bahrain_layout_db,
):
    from core.config import QPC_V2_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')

    with sqlite3.connect(QPC_V2_LAYOUT_DATABASE) as source:
        source_before = source.execute(
            '''
            SELECT line_number, line_type, first_word_id, last_word_id
            FROM pages
            WHERE page_number IN (358, 359)
            ORDER BY page_number, line_number
            '''
        ).fetchall()

    before358 = client.get('/api/layout-studio/bahrain/page/358').get_json()
    before359 = client.get('/api/layout-studio/bahrain/page/359').get_json()
    target = next(
        line for line in before358['lines']
        if line['line_type'] == 'ayah' and len(line.get('words') or []) > 3
    )
    cut_word = target['words'][len(target['words']) // 2]['word_index']

    def page_word_ids(payload):
        return [
            word['word_index']
            for line in payload['lines'] if line['line_type'] == 'ayah'
            for word in (line.get('words') or [])
        ]

    edited = client.post('/api/layout-studio/bahrain/line-break', json={
        'page_number': 358,
        'line_number': target['line_number'],
        'word_id': cut_word,
    })
    assert edited.status_code == 200, edited.get_json()
    edited_page = edited.get_json()['page']
    edited_target = next(
        line for line in edited_page['lines']
        if line['line_number'] == target['line_number']
    )
    assert edited_target['last_word_id'] == cut_word
    assert page_word_ids(edited_page) == page_word_ids(before358)
    assert (
        page_word_ids(client.get('/api/layout-studio/bahrain/page/359').get_json())
        == page_word_ids(before359)
    )

    last_line = [
        line for line in edited_page['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    before359_words = page_word_ids(before359)
    # Intentional print correction: push last word onto the next page.
    pushed = client.post(
        '/api/layout-studio/bahrain/push-last-word',
        json={
            'page_number': 358,
            'line_number': last_line['line_number'],
        },
    )
    assert pushed.status_code == 200, pushed.get_json()
    assert pushed.get_json()['crossed_page'] is True
    moved = pushed.get_json()['moved_word_id']
    after358 = pushed.get_json()['page']
    after359 = client.get('/api/layout-studio/bahrain/page/359').get_json()
    assert moved not in page_word_ids(after358)
    assert page_word_ids(after359)[0] == moved
    assert page_word_ids(after358) + page_word_ids(after359) == (
        page_word_ids(before358) + before359_words
    )

    last358 = [
        line for line in after358['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    pulled = client.post(
        '/api/layout-studio/bahrain/pull-next-word',
        json={
            'page_number': 358,
            'line_number': last358['line_number'],
        },
    )
    assert pulled.status_code == 200, pulled.get_json()
    assert pulled.get_json()['crossed_page'] is True
    assert page_word_ids(pulled.get_json()['page']) == page_word_ids(before358)
    assert (
        page_word_ids(client.get('/api/layout-studio/bahrain/page/359').get_json())
        == before359_words
    )

    # Undo pull, then push, then the in-page line-break.
    for _ in range(3):
        undone = client.post(
            '/api/layout-studio/bahrain/undo', json={'page_number': 358},
        )
        assert undone.status_code == 200
    assert page_word_ids(undone.get_json()['page']) == page_word_ids(before358)
    assert (
        page_word_ids(client.get('/api/layout-studio/bahrain/page/359').get_json())
        == before359_words
    )

    with sqlite3.connect(QPC_V2_LAYOUT_DATABASE) as source:
        source_after = source.execute(
            '''
            SELECT line_number, line_type, first_word_id, last_word_id
            FROM pages
            WHERE page_number IN (358, 359)
            ORDER BY page_number, line_number
            '''
        ).fetchall()
    assert source_after == source_before


def test_bahrain_push_last_word_page_262_boundary(
    client, monkeypatch, restore_bahrain_layout_db,
):
    """Printed Bahrain page 262 ends at ۝١٥; وَلَقَدْ opens page 263."""
    monkeypatch.setenv('ENABLE_EDITOR', '1')

    before262 = client.get('/api/layout-studio/bahrain/page/262').get_json()
    before263 = client.get('/api/layout-studio/bahrain/page/263').get_json()
    last = [
        line for line in before262['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    assert last['words'][-1]['text'].startswith('وَلَقَد')
    first263 = next(
        line for line in before263['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    )
    assert first263['words'][0]['text'].startswith('جَعَلْنَا')

    pushed = client.post('/api/layout-studio/bahrain/push-last-word', json={
        'page_number': 262,
        'line_number': last['line_number'],
    })
    assert pushed.status_code == 200, pushed.get_json()
    page262 = pushed.get_json()['page']
    page263 = client.get('/api/layout-studio/bahrain/page/263').get_json()
    last_after = [
        line for line in page262['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    ][-1]
    first_after = next(
        line for line in page263['lines']
        if line['line_type'] == 'ayah' and line.get('words')
    )
    assert last_after['words'][-1]['text'].endswith('١٥') or '١٥' in last_after['words'][-1]['text']
    assert first_after['words'][0]['text'].startswith('وَلَقَد')
    assert first_after['words'][1]['text'].startswith('جَعَلْنَا')
    assert pushed.get_json()['crossed_page'] is True


def test_bahrain_header_rows_move_across_pages_and_undo(
    client, monkeypatch, restore_bahrain_layout_db,
):
    from core.config import BAHRAIN_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')

    def positions():
        with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
            return conn.execute(
                '''
                SELECT id, page_number, line_number, line_type, surah_number,
                       first_word_id, last_word_id
                FROM pages
                WHERE page_number IN (76, 77)
                ORDER BY page_number, line_number
                '''
            ).fetchall()

    before = positions()
    page76_last = next(
        row for row in before
        if row[1] == 76 and row[2] == 15
    )
    page77_first = next(
        row for row in before
        if row[1] == 77 and row[2] == 1
    )
    assert page76_last[3] == 'surah_name'
    assert page77_first[3] == 'basmallah'

    moved = client.post('/api/layout-studio/bahrain/header-move', json={
        'page_number': 76,
        'line_number': 15,
        'direction': 'down',
    })
    assert moved.status_code == 200, moved.get_json()
    body = moved.get_json()
    assert body['crossed_page'] is True
    assert body['moved_to_page'] == 77
    assert body['moved_to_line'] == 1
    assert body['undo_available'] >= 1

    after = positions()
    page76_rows = [row for row in after if row[1] == 76]
    page77_rows = [row for row in after if row[1] == 77]
    assert len(page76_rows) == 15
    assert len(page77_rows) == 15
    assert page77_rows[0][0] == page76_last[0]
    assert page77_rows[0][3] == 'surah_name'
    assert page77_rows[1][0] == page77_first[0]
    assert page77_rows[1][3] == 'basmallah'

    undone = client.post(
        '/api/layout-studio/bahrain/undo', json={'page_number': 76},
    )
    assert undone.status_code == 200, undone.get_json()
    assert positions() == before


def test_bahrain_cross_page_header_move_consumes_empty_row(
    client, monkeypatch, restore_bahrain_layout_db,
):
    """The 548→549 pattern keeps name then basmallah, not an exchange."""
    from core.config import BAHRAIN_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        name = conn.execute(
            '''
            SELECT id FROM pages
            WHERE page_number = 76 AND line_number = 15
              AND line_type = 'surah_name'
            '''
        ).fetchone()
        basmallah = conn.execute(
            '''
            SELECT id FROM pages
            WHERE page_number = 77 AND line_number = 1
              AND line_type = 'basmallah'
            '''
        ).fetchone()
        last = conn.execute(
            '''
            SELECT id FROM pages
            WHERE page_number = 77
            ORDER BY line_number DESC LIMIT 1
            '''
        ).fetchone()
        assert name and basmallah and last

        # Recreate the user's former wrong-swap state in the test copy:
        # basmallah at the previous page's end, name at the next page's start,
        # and an empty ayah slot ready to be consumed.
        conn.execute(
            'UPDATE pages SET line_number = ? WHERE id = ?',
            (-int(name['id']), int(name['id'])),
        )
        conn.execute(
            '''
            UPDATE pages SET page_number = 76, line_number = 15
            WHERE id = ?
            ''',
            (int(basmallah['id']),),
        )
        conn.execute(
            '''
            UPDATE pages SET page_number = 77, line_number = 1
            WHERE id = ?
            ''',
            (int(name['id']),),
        )
        conn.execute(
            '''
            UPDATE pages
            SET first_word_id = NULL, last_word_id = NULL, line_text = ''
            WHERE id = ?
            ''',
            (int(last['id']),),
        )
        conn.commit()
        prepared = conn.execute(
            '''
            SELECT id, page_number, line_number, line_type, first_word_id,
                   last_word_id, line_text
            FROM pages WHERE page_number IN (76, 77)
            ORDER BY page_number, line_number
            '''
        ).fetchall()

    moved = client.post('/api/layout-studio/bahrain/header-move', json={
        'page_number': 76,
        'line_number': 15,
        'direction': 'down',
    })
    assert moved.status_code == 200, moved.get_json()
    body = moved.get_json()
    assert body['crossed_page'] is True
    assert body['removed_empty_line'] is True
    assert body['moved_to_page'] == 77
    assert body['moved_to_line'] == 2

    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        page76 = conn.execute(
            'SELECT line_type FROM pages WHERE page_number = 76 ORDER BY line_number'
        ).fetchall()
        page77 = conn.execute(
            '''
            SELECT line_type, first_word_id, last_word_id
            FROM pages WHERE page_number = 77 ORDER BY line_number
            '''
        ).fetchall()
    assert len(page76) == 15
    assert len(page77) == 15
    assert [row[0] for row in page77[:2]] == ['surah_name', 'basmallah']
    assert all(
        row[1] is not None or row[0] != 'ayah'
        for row in page77
    )

    undone = client.post(
        '/api/layout-studio/bahrain/undo', json={'page_number': 76},
    )
    assert undone.status_code == 200, undone.get_json()
    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        restored = conn.execute(
            '''
            SELECT id, page_number, line_number, line_type, first_word_id,
                   last_word_id, line_text
            FROM pages WHERE page_number IN (76, 77)
            ORDER BY page_number, line_number
            '''
        ).fetchall()
    assert restored == [tuple(row) for row in prepared]


def test_bahrain_header_move_controls_are_wired(client, monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')
    html = client.get('/layout-studio/bahrain').get_data(as_text=True)
    js = (PROJECT_ROOT / 'static/js/azhar_layout.js').read_text(encoding='utf-8')
    assert 'سهما العنوان' in html
    assert 'attachHeaderTools' in js
    assert '/header-move' in js
    assert 'az-header-move' in js

    ayah = next(
        line for line in client.get(
            '/api/layout-studio/bahrain/page/358'
        ).get_json()['lines']
        if line['line_type'] == 'ayah'
    )
    rejected = client.post('/api/layout-studio/bahrain/header-move', json={
        'page_number': 358,
        'line_number': ayah['line_number'],
        'direction': 'up',
    })
    assert rejected.status_code == 400


def test_bahrain_pull_word_stays_inside_surah_segment(
    client, monkeypatch, restore_bahrain_layout_db,
):
    """A pull before a mid-page surah banner must not copy the later surah."""
    from core.config import BAHRAIN_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    # The reviewer exposed an old duplicated range on page 551. Normalize that
    # one row in the disposable test copy to exercise the corrected operation.
    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        words = conn.execute(
            '''
            SELECT text FROM words
            WHERE word_index BETWEEN 76265 AND 76273
            ORDER BY word_index
            '''
        ).fetchall()
        conn.execute(
            '''
            UPDATE pages
            SET first_word_id = 76265, last_word_id = 76273, line_text = ?
            WHERE page_number = 551 AND line_number = 6
            ''',
            (' '.join(row[0] for row in words),),
        )
        conn.commit()

    def page_words():
        payload = client.get(
            '/api/layout-studio/bahrain/page/551'
        ).get_json()
        return payload, [
            word['word_index']
            for line in payload['lines']
            if line['line_type'] == 'ayah'
            for word in (line.get('words') or [])
        ]

    before, before_words = page_words()
    assert all(
        left < right for left, right in zip(before_words, before_words[1:])
    )
    target = next(
        line for line in before['lines']
        if line['line_type'] == 'ayah' and line['line_number'] == 1
    )
    pulled = client.post(
        '/api/layout-studio/bahrain/pull-next-word',
        json={'page_number': 551, 'line_number': target['line_number']},
    )
    assert pulled.status_code == 200, pulled.get_json()
    _, after_words = page_words()
    assert after_words == before_words
    assert len(after_words) == len(set(after_words))

    # The final ayah line before the banner must remain fenced.
    blocked = client.post(
        '/api/layout-studio/bahrain/pull-next-word',
        json={'page_number': 551, 'line_number': 6},
    )
    assert blocked.status_code == 400
    assert 'فاصل السورة' in blocked.get_json()['error']


def test_bahrain_rejects_edits_on_duplicated_page_stream(
    client, monkeypatch, restore_bahrain_layout_db,
):
    from core.config import BAHRAIN_LAYOUT_DATABASE

    monkeypatch.setenv('ENABLE_EDITOR', '1')
    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        conn.execute(
            '''
            UPDATE pages SET last_word_id = 76340
            WHERE page_number = 551 AND line_number = 6
            '''
        )
        conn.commit()

    rejected = client.post(
        '/api/layout-studio/bahrain/pull-next-word',
        json={'page_number': 551, 'line_number': 1},
    )
    assert rejected.status_code == 409
    assert 'مكررة' in rejected.get_json()['error']


def test_layout_line_actions_use_compact_menu():
    js = (PROJECT_ROOT / 'static/js/azhar_layout.js').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static/css/azhar_layout.css').read_text(encoding='utf-8')
    assert 'az-line-menu' in js
    assert 'az-line-actions' in js
    assert 'aria-expanded' in js
    assert '.az-tools-open .az-line-actions' in css
    assert 'left: 2px; right: auto' in css
    assert 'availableWidth: line => line.clientWidth' in js
    assert 'justify-content: flex-start' in css
    assert 'transform-origin: right center' in css
    assert 'left: -13px' in css
    assert 'opacity: 1' in css
