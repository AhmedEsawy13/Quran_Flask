"""Layout audit meta summaries for the activity feed."""
from __future__ import annotations

from core.layout_persistence import build_layout_audit_meta


def test_layout_audit_meta_summarizes_endpoint_changes():
    before = {
        12: [
            {
                'line_number': 3, 'line_type': 'ayah',
                'first_word_key': '1:1:1', 'last_word_key': '1:1:4',
            },
            {
                'line_number': 4, 'line_type': 'ayah',
                'first_word_key': '1:1:5', 'last_word_key': '1:1:8',
            },
        ],
    }
    after_pages = [{
        'page_number': 12,
        'lines': [
            {
                'line_number': 3, 'line_type': 'ayah',
                'first_word_key': '1:1:1', 'last_word_key': '1:1:5',
            },
            {
                'line_number': 4, 'line_type': 'ayah',
                'first_word_key': '1:1:6', 'last_word_key': '1:1:8',
            },
            {'line_number': 1, 'line_type': 'surah_name'},
        ],
    }]
    meta = build_layout_audit_meta(
        after_pages, before_by_page=before, op='line-break',
    )
    assert meta['op'] == 'line-break'
    assert meta['page_from'] == 12
    assert meta['line_count'] == 2
    assert meta['changed_lines'] == 2
    assert meta['first_key'] == '1:1:1'
    assert meta['last_key'] == '1:1:8'
    assert 'كسر سطر' in meta['change_summary']
    assert 'تغيّر 2 سطر' in meta['change_summary']
    assert meta['pages'][0]['changed'][0]['line'] == 3
