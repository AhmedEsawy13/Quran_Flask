"""Kuwait surah-end ركوع seed + editor peer-mark payloads."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')
    # Spread API requires login when Supabase env is present in the shell;
    # force local (no-cloud) mode for these layout/peer payload checks.
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)


def test_spread_includes_peer_versions(client):
    r = client.get('/api/mushaf-editor/spread/1?edition=قطر')
    assert r.status_code == 200
    body = r.get_json()
    peers = body.get('peer_versions') or []
    assert 'الأزهر' in peers
    assert 'الشمرلي' in peers
    assert 'المدينة الجديد' in peers
    assert 'المدينة القديم' in peers

    # Spread 1 = pages 1–2; peer marks appear once البقرة starts (left page).
    pages = [p for p in (body.get('right'), body.get('left')) if p]
    with_marks = [
        w for page in pages for line in page.get('lines') or []
        for w in (line.get('words') or [])
        if isinstance(w.get('waqf_symbols'), list) and w['waqf_symbols']
    ]
    assert with_marks
    versions = {e['version'] for w in with_marks for e in w['waqf_symbols']}
    assert 'المدينة الجديد' in versions
    assert 'الأزهر' in versions or 'الشمرلي' in versions


def test_kuwait_surah_end_rukuu_seed_targets():
    from pipeline.seed_kuwait_surah_end_rukuu import surah_end_word_ids, SYMBOL, EDITION

    targets = surah_end_word_ids()
    assert len(targets) == 114
    assert targets[0][0] == 1 and targets[0][1] == 7
    assert targets[-1][0] == 114
    assert EDITION == 'الكويت'
    assert SYMBOL == 'ركوع'


def test_editor_ui_mentions_peer_hints():
    page = (PROJECT_ROOT / 'templates/mushaf_editor.html').read_text(encoding='utf-8')
    script = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    assert 'ed-popup-peers' in page
    assert 'ed-peer-hint' in script
    assert 'PEER_VERSIONS' in script


def test_muzzammil_20_peer_marks_not_shifted_by_sqlite_token_index():
    """SQLite token_index must not pull peer marks one word past the target.

    Regression for 73:20 — preferring DB token_index as a layout offset put
    Madinah ج on وَٱللَّهُ instead of مَعَكَ, which showed green underline
    with no edition glyph.
    """
    from modules.layouts import (
        _build_page_waqf_map,
        _find_mushaf_row_match_index,
        _get_dk_layout_word_map,
    )

    wmap = _get_dk_layout_word_map()
    first = wmap['first_id'][(73, 20)]
    last = wmap['last_id'][(73, 20)]
    words = []
    for gid in range(first, last + 1):
        info = wmap['id2tok'][gid]
        words.append({
            'word_index': gid,
            'surah': 73,
            'ayah': 20,
            'text': info['text'],
            'text_original': info['text'],
        })

    # Synthetic SQLite-shaped row: token_index after the usual -1 conversion
    # points at وَٱللَّهُ (15), but word_index + text say مَعَكَ (14).
    row = {
        'clean_token': 'مَعَكَۚ',
        'symbols': 'ج',
        'token_index': 15,
        'word_index': 15,
        'version': 'المدينة الجديد',
    }
    idx = _find_mushaf_row_match_index(words, row)
    assert idx == 14
    assert 'مَعَكَ' in words[14]['text']
    assert 'وَٱللَّهُ' in words[15]['text']

    waqf_map = _build_page_waqf_map(words, ['المدينة الجديد', 'الأزهر'])
    assert any(e.get('symbols') == 'ج' for e in (waqf_map.get(first + 14) or []))
    assert not (waqf_map.get(first + 15) or [])
