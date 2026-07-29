"""Egyptian Survey Authority 1342H Layout Studio project."""
from __future__ import annotations

import json
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
    assert report['method'].get('stream_order') == 'surah,ayah,word_index'
    assert len(report['source']['ocr_sources']) == 2
    assert sum(report['confidence']['source_selection'].values()) == 826
    assert report['validation']['missing'] == 0
    assert report['validation']['duplicates'] == 0
    assert report['validation']['out_of_order'] == 0
    assert report['validation'].get('surah_order_violations', 0) == 0
    assert sum(report['confidence']['status_counts'].values()) == 826

    importer = (
        PROJECT_ROOT / 'pipeline' / 'import_mesaha_layout.py'
    ).read_text(encoding='utf-8')
    assert 'partial_ratio_alignment' in importer
    assert 'uses_llm' in importer
    assert '--force' in importer
    assert 'canonical-multi-ocr-forced-alignment-v3' in importer
