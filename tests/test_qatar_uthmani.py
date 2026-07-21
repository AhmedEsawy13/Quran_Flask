"""Qatar editor layout now uses Tanzil Uthmani text + KATypical Naskh."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_qatar_uthmani_word_map_covers_most_ayahs():
    from modules.layouts import (
        _get_qatar_uthmani_layout_word_map,
        _get_qpc_hafs_layout_word_map,
        _load_tanzil_uthmani_ayahs,
        _build_qatar_page_payload,
    )
    uth = _load_tanzil_uthmani_ayahs()
    assert len(uth) == 6236
    assert (1, 1) in uth and (2, 2) in uth and (9, 1) in uth

    qatar = _get_qatar_uthmani_layout_word_map()
    qpc = _get_qpc_hafs_layout_word_map()
    assert qatar['first_id'] == qpc['first_id']
    assert len(qatar['id2tok']) == len(qpc['id2tok'])

    first = qatar['first_id'][(2, 2)]
    last = qatar['last_id'][(2, 2)]
    texts = [qatar['id2tok'][wid]['text'] for wid in range(first, last + 1)]
    assert texts[0] == 'ذَٰلِكَ'
    assert texts[-1] == '٢'
    # Tanzil has no embedded waqf; QPC does on رَيۡبَۛ
    assert texts[3] == 'رَيْبَ'
    assert 'ۛ' not in texts[3]

    page = _build_qatar_page_payload(1)
    assert page['font_name'] == 'KATypical Naskh'
    assert page['source'] == 'mushaf_qatar'
    assert any(w.get('text') == 'بِسْمِ' for line in page['lines'] for w in line.get('words') or [])


def test_editor_ui_references_katypical_naskh_for_qatar():
    css = (PROJECT_ROOT / 'static/css/mushaf_editor.css').read_text(encoding='utf-8')
    js = (PROJECT_ROOT / 'static/js/mushaf_editor.js').read_text(encoding='utf-8')
    assert 'KATypicalNaskhv2.0-Regular.woff2' in css
    assert 'ed-font-qatar' in css
    assert "classList.toggle('ed-font-qatar', state.edition === 'قطر')" in js
    assert 'katypicalNaskhFeatureCandidates' not in js
    assert (PROJECT_ROOT / 'static/fonts/KATypicalNaskhv2.0-Regular.woff2').is_file()
    assert (PROJECT_ROOT / 'data/quran_text/quran-uthmani.txt').is_file()


def test_qatar_spread_api_reports_katypical_font(client):
    data = client.get('/api/mushaf-editor/spread/1?edition=قطر').get_json()
    assert data['edition'] == 'قطر'
    assert data['right']['font_name'] == 'KATypical Naskh'
    words = [w for line in data['right']['lines'] for w in (line.get('words') or [])]
    assert any(w.get('text') == 'بِسْمِ' for w in words)
