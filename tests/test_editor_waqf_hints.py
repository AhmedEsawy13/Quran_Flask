"""Kuwait surah-end ركوع seed + editor peer-mark payloads."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_editor(monkeypatch):
    monkeypatch.setenv('ENABLE_EDITOR', '1')


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
