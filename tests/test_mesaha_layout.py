"""Egyptian Survey Authority 1342H Layout Studio project."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from core.config import MESAHA_LAYOUT_DATABASE, QURAN_SCRIPT_DATABASE

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


def test_mesaha_registry_shell_and_reference(client):
    response = client.get('/api/layout-studio/editions')
    assert response.status_code == 200
    edition = next(
        item for item in response.get_json()['editions']
        if item['id'] == 'mesaha'
    )
    assert edition['min_page'] == 2
    assert edition['max_page'] == 827
    assert edition['lines_per_page'] == 12
    assert edition['profile']['page_end_mode'] == 'continuous'

    shell = client.get('/layout-studio/mesaha')
    assert shell.status_code == 200
    html = shell.get_data(as_text=True)
    assert 'مصحف المساحة الأميرية' in html
    assert 'mushafElMesaha46796794669_201703' in html
    assert 'id="az-import-confidence"' in html
    assert 'id="az-next-uncertain"' in html
    assert '"leafOffset": -1' in html


def test_mesaha_opening_middle_final_pages(client):
    opening = client.get('/api/layout-studio/mesaha/page/2')
    assert opening.status_code == 200
    page2 = opening.get_json()
    assert page2['source'] == 'layout_studio_mesaha'
    assert page2['font_name'] == 'Amiri Quran'
    assert page2['lines_per_page'] == 8
    assert len(page2['lines']) == 8
    assert [line['line_type'] for line in page2['lines'][:3]] == [
        'surah_name', 'surah_info', 'basmallah',
    ]
    assert page2['lines'][-1]['last_word_id'] == 38
    assert page2['import_confidence']['status'] in {'high', 'medium', 'low'}
    assert 'Selected OCR source=' in page2['import_confidence']['notes']

    page3 = client.get('/api/layout-studio/mesaha/page/3').get_json()
    assert page3['lines_per_page'] == 8
    assert page3['lines'][-1]['last_word_id'] == 76

    middle = client.get('/api/layout-studio/mesaha/page/171').get_json()
    assert middle['lines_per_page'] == 12
    assert len(middle['lines']) == 12
    assert middle['import_confidence']['estimated_line_ends'] >= 0

    final = client.get('/api/layout-studio/mesaha/page/827').get_json()
    assert final['lines'][-1]['last_word_id'] == 84554
    assert any(
        line['line_type'] == 'surah_name' and line['surah_number'] == 114
        for line in final['lines']
    )
    by_ayah = client.get('/api/layout-studio/mesaha/page-by-ayah/114/6')
    assert by_ayah.status_code == 200
    assert by_ayah.get_json()['page_number'] == 827



def test_mesaha_amiri_dammatan_matches_azhar(client):
    """Mesaha uses Amiri Quran — standing dammatan must be U+08F1 like Azhar."""
    page = client.get('/api/layout-studio/mesaha/page/61').get_json()
    assert page['font_name'] == 'Amiri Quran'
    joined = []
    for line in page['lines']:
        joined.append(line.get('display_text') or '')
        for word in line.get('words') or []:
            joined.append(word.get('text') or '')
    text = chr(10).join(joined)
    assert chr(0x065E) not in text
    assert chr(0x08F1) in text

def test_mesaha_database_has_exact_canonical_continuity():
    layout = sqlite3.connect(MESAHA_LAYOUT_DATABASE)
    script = sqlite3.connect(QURAN_SCRIPT_DATABASE)
    try:
        # Mushaf reading order — not raw word_index sort (three interleaved chunks).
        expected = [
            int(row[0]) for row in script.execute(
                'SELECT word_index FROM words ORDER BY surah, ayah, word_index'
            )
        ]
        position = {word_id: index for index, word_id in enumerate(expected)}
        emitted = []
        for first, last in layout.execute(
            '''
            SELECT first_word_id, last_word_id
            FROM pages
            WHERE first_word_id IS NOT NULL AND last_word_id IS NOT NULL
            ORDER BY page_number, line_number
            '''
        ):
            left = position.get(int(first))
            right = position.get(int(last))
            if left is None or right is None:
                continue  # Shamarly header IDs outside the ayah stream
            assert right >= left
            emitted.extend(expected[left:right + 1])
        assert emitted == expected
        assert len(emitted) == 83863
        assert layout.execute(
            'SELECT COUNT(DISTINCT page_number) FROM pages'
        ).fetchone()[0] == 826
        assert layout.execute(
            'SELECT COUNT(*) FROM layout_import_confidence'
        ).fetchone()[0] == 826
        assert layout.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        # Surah stream must not go backwards on ayah lines.
        prev_surah = 0
        for surah, in layout.execute(
            '''
            SELECT surah_number FROM pages
            WHERE line_type = 'ayah' AND surah_number IS NOT NULL
            ORDER BY page_number, line_number
            '''
        ):
            assert int(surah) >= prev_surah
            prev_surah = int(surah)
    finally:
        layout.close()
        script.close()


def test_mesaha_confidence_review_queue(client):
    response = client.get('/api/layout-studio/mesaha/import-confidence')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['available'] is True
    assert len(payload['pages']) == 826
    assert sum(payload['counts'].values()) == 826
    assert payload['pages'][0]['status'] == 'low'
    assert all(
        payload['pages'][i]['status'] != 'high'
        or payload['pages'][i + 1]['status'] == 'high'
        for i in range(len(payload['pages']) - 1)
    )


def test_mesaha_import_report_and_non_llm_pipeline():
    report_path = PROJECT_ROOT / 'data' / 'mushaf-mesaha-import-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['method']['uses_llm'] is False
    assert report['method']['canonical_text_is_authoritative'] is True
    assert report['method']['multi_source_selection'] is True
    assert report['method'].get('multi_source_fusion') is True
    assert report['method'].get(
        'stream_order'
    ) == 'surah,ayah,word_key-position'
    assert report['method']['canonical_word_key_interchange'] is True
    assert report['method']['canonical_integrity_bonus'] == 0.02
    assert report['confidence']['canonical_integrity_bonus'] == 0.02
    assert report['confidence']['mean_score'] > 0.7364
    assert len(report['source']['ocr_sources']) == 2
    assert sum(report['confidence']['source_selection'].values()) == 826
    assert report['validation']['missing'] == 0
    assert report['validation']['duplicates'] == 0
    assert report['validation']['out_of_order'] == 0
    assert report['validation']['canonical_word_keys_unique'] is True
    assert report['validation']['canonical_word_key_stream_exact'] is True
    assert report['validation'].get('surah_order_violations', 0) == 0
    assert sum(report['confidence']['status_counts'].values()) == 826

    importer = (
        PROJECT_ROOT / 'pipeline' / 'import_mesaha_layout.py'
    ).read_text(encoding='utf-8')
    assert 'partial_ratio_alignment' in importer
    assert 'uses_llm' in importer
    assert '--force' in importer
    assert 'canonical-multi-ocr-forced-alignment-v6' in importer
    assert 'LINE_Y_MERGE' in importer
    assert '--kraken-dir' in importer
    assert '--upgrade-confidence' in importer


def test_mesaha_confidence_upgrade_is_idempotent(tmp_path):
    from pipeline import import_mesaha_layout

    database = tmp_path / 'mesaha.db'
    report_path = tmp_path / 'report.json'
    shutil.copy2(MESAHA_LAYOUT_DATABASE, database)
    shutil.copy2(
        PROJECT_ROOT / 'data' / 'mushaf-mesaha-import-report.json',
        report_path,
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            "DELETE FROM layout_import_meta "
            "WHERE key = 'canonical_integrity_bonus'"
        )
        conn.execute(
            'UPDATE layout_import_confidence SET score = score - 0.02'
        )

    first = import_mesaha_layout.upgrade_existing_confidence(
        str(database), str(report_path),
    )
    second = import_mesaha_layout.upgrade_existing_confidence(
        str(database), str(report_path),
    )

    assert first['confidence']['mean_score'] == 0.7564
    assert second['confidence']['mean_score'] == 0.7564
    with sqlite3.connect(database) as conn:
        assert round(conn.execute(
            'SELECT AVG(score) FROM layout_import_confidence'
        ).fetchone()[0], 4) == 0.7564


def test_mesaha_banner_block_is_four_slots_so_a_banner_page_holds_eleven_rows():
    from modules import layout_studio as studio
    from modules.layout_editions import MESAHA

    profile = MESAHA.profile
    assert (profile.surah_name_lines, profile.surah_info_lines, profile.basmallah_lines) == (1, 1, 2)
    plain = [{'line_type': 'ayah'}] * 12
    banner = [{'line_type': 'ayah'}] * 7 + [
        {'line_type': 'surah_name'}, {'line_type': 'surah_info'}, {'line_type': 'basmallah'},
        {'line_type': 'ayah'},
    ]
    assert studio._page_row_budget(MESAHA, profile, 100, rows=plain) == 12
    assert studio._page_row_budget(MESAHA, profile, 62 + 0, rows=banner) == 11
    # No banner row, no extra reservation (surah Tawbah has a name box but no basmallah).
    assert studio._page_row_budget(MESAHA, profile, 100, rows=[{'line_type': 'surah_name'}] + plain[:11]) == 12


def test_other_editions_keep_one_row_per_slot():
    from modules import layout_studio as studio
    from modules.layout_editions import AZHAR

    rows = [{'line_type': 'ayah'}] * 12 + [{'line_type': 'surah_name'}, {'line_type': 'basmallah'}]
    assert studio._page_row_budget(AZHAR, AZHAR.profile, 10, rows=rows) == studio._page_line_budget(
        AZHAR, AZHAR.profile, 10)


def test_mesaha_banner_rows_carry_their_text_and_empty_rows_are_flagged():
    from modules import layout_studio as studio
    from modules.layout_editions import MESAHA

    page = studio._build_page_payload(MESAHA, 62)
    headers = {line['line_type']: line for line in page['lines'] if line['line_type'] != 'ayah'}
    # These rows carry reserved word ids outside the word map; they used to draw as nothing.
    assert headers['surah_name']['display_text'] == 'سورة آل عمران'
    assert headers['surah_info']['display_text'].startswith('مدنية')
    assert headers['basmallah']['display_text'].startswith('بِسْمِ')
    assert headers['basmallah']['slot_span'] == 2
    assert not any(line.get('empty') for line in page['lines'])


def test_ayah_row_without_words_is_flagged_empty(tmp_path, monkeypatch):
    from modules import layouts

    out = layouts._assemble_layout_page(
        [{'line_number': 1, 'line_type': 'ayah', 'is_centered': 0, 'first_word_id': None,
          'last_word_id': None, 'surah_number': 2, 'line_text': ''},
         {'line_number': 2, 'line_type': 'surah_info', 'is_centered': 1, 'first_word_id': None,
          'last_word_id': None, 'surah_number': 3, 'line_text': 'مدنية · آياتها ٢٠٠'}],
        None, 1, None, None, source='t', font_name_default='Amiri Quran',
        include_advance=False, mushaf_version='x', word_map={'id2tok': {}, 'ordered_ids': [],
                                                              'position_by_id': {}},
    )
    assert out['lines'][0].get('empty') is True
    assert out['lines'][1]['display_text'] == 'مدنية · آياتها ٢٠٠'


def test_draft_info_describes_relayout_drafts_not_the_old_seed(tmp_path):
    import json
    import sqlite3

    from modules import layout_studio as studio

    db = tmp_path / 'layout.db'
    conn = sqlite3.connect(db)
    assert studio._draft_info(conn, 100) is None                      # a print without drafts
    conn.executescript(
        'CREATE TABLE layout_import_meta (key TEXT PRIMARY KEY, value TEXT);'
        'CREATE TABLE relayout_drafts (page_number INTEGER PRIMARY KEY, kind TEXT, source TEXT, flags TEXT, drafted_at TEXT);'
    )
    conn.execute("INSERT INTO layout_import_meta VALUES ('draft_accuracy_kraken', ?)",
                 (json.dumps({'pages': 37, 'untouched_pages': 28, 'rows': 442, 'rows_exact': 419}),))
    conn.executemany(
        'INSERT INTO relayout_drafts VALUES (?, ?, ?, ?, ?)',
        [(100, 'draft', 'kraken', '', ''), (101, 'draft', 'kraken', 'end gap 2 with page 102, reconciled', ''),
         (102, 'draft', 'djvu', '', ''), (103, 'neighbour-edge', None, 'start gap 4', '')],
    )
    plain = studio._draft_info(conn, 100)
    assert (plain['kind'], plain['review_status'], plain['accuracy']['rows_exact']) == ('draft', 'medium', 419)
    assert studio._draft_info(conn, 101)['review_status'] == 'low'    # a boundary note
    assert studio._draft_info(conn, 102)['review_status'] == 'low' and 'accuracy' not in studio._draft_info(conn, 102)
    assert studio._draft_info(conn, 103)['kind'] == 'neighbour-edge'
    legacy = studio._draft_info(conn, 150)                            # not re-derived
    assert (legacy['kind'], legacy['review_status']) == ('legacy', 'low')


def test_mesaha_review_queue_carries_the_draft_priority(client):
    pages = client.get('/api/layout-studio/mesaha/import-confidence').get_json()['pages']
    with_status = [p for p in pages if 'review_status' in p]
    assert with_status and all(p['review_status'] in ('low', 'medium') for p in with_status)
    assert {p['draft_kind'] for p in with_status} <= {'draft', 'neighbour-edge', 'legacy'}


# --- edits must not reflow reviewed pages (2026-10-21: one edit rewrote 347-363, another 193-226) ---

@pytest.fixture
def restore_mesaha_layout_db(tmp_path):
    db = Path(MESAHA_LAYOUT_DATABASE)
    backup = tmp_path / db.name
    shutil.copy2(db, backup)
    try:
        yield db
    finally:
        shutil.copy2(backup, db)


def _rows(db, first, last):
    with sqlite3.connect(db) as conn:
        return conn.execute(
            'SELECT page_number, line_number, first_word_id, last_word_id, line_text FROM pages '
            'WHERE page_number BETWEEN ? AND ? ORDER BY page_number, line_number', (first, last)).fetchall()


def test_mesaha_word_moves_change_only_the_two_lines(client, restore_mesaha_layout_db):
    db = restore_mesaha_layout_db
    before = _rows(db, 350, 363)
    pulled = client.post('/api/layout-studio/mesaha/pull-next-word', json={'page_number': 350, 'line_number': 5})
    assert pulled.status_code == 200, pulled.get_json()
    after = _rows(db, 350, 363)
    changed = [(b[0], b[1]) for b, a in zip(before, after) if b != a]
    assert changed == [(350, 5), (350, 6)]
    assert after[4][3] == before[4][3] + 1 and after[5][2] == before[5][2] + 1

    pushed = client.post('/api/layout-studio/mesaha/push-last-word', json={'page_number': 350, 'line_number': 5})
    assert pushed.status_code == 200, pushed.get_json()
    assert _rows(db, 350, 363) == before


def test_mesaha_edit_refused_when_it_would_reflow_reviewed_pages(client, restore_mesaha_layout_db):
    db = restore_mesaha_layout_db
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT OR REPLACE INTO mesaha_layout_progress (page_number, reviewed) VALUES (?, 1)',
                         [(p,) for p in range(347, 364)])
    before = _rows(db, 347, 363)
    # a line break mid-surah reflows every later line of the surah (continuous profile)
    broken = client.post('/api/layout-studio/mesaha/line-break', json={
        'page_number': 350, 'line_number': 5, 'word_id': 36754})
    assert broken.status_code == 409, broken.get_json()
    body = broken.get_json()
    assert body.get('code') == 'reviewed_pages_changed' or 'reviewed_pages_changed' in str(body)
    assert _rows(db, 347, 363) == before


def test_mesaha_reflow_still_allowed_on_unreviewed_pages(client, restore_mesaha_layout_db):
    db = restore_mesaha_layout_db
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM mesaha_layout_progress')
    before = _rows(db, 350, 363)
    broken = client.post('/api/layout-studio/mesaha/line-break', json={
        'page_number': 350, 'line_number': 5, 'word_id': 36754})
    assert broken.status_code == 200, broken.get_json()
    assert _rows(db, 350, 363) != before


def test_triage_info_lists_flagged_lines():
    import json as _json
    import sqlite3 as _sqlite3
    from modules.layout_studio import _triage_info
    conn = _sqlite3.connect(':memory:')
    assert _triage_info(conn, 480) is None
    conn.execute('CREATE TABLE layout_triage (page_number INTEGER PRIMARY KEY, status TEXT, detail TEXT, checked_at TEXT)')
    detail = {'flags': {'unclaimed_bodies': [{'line': 9}], 'line_breaks': [{'lines': [8, 9], 'fix': 'move «في» to line 9'}],
                        'words_without_ink': ['مَا']}, 'start_fixed': True, 'breaks_moved': 1}
    conn.execute("INSERT INTO layout_triage VALUES (480, 'look', ?, 'now')", (_json.dumps(detail),))
    info = _triage_info(conn, 480)
    assert info['status'] == 'look' and info['lines'] == [8, 9]
    assert info['words_without_ink'] == ['مَا'] and info['start_fixed'] and info['breaks_moved'] == 1
