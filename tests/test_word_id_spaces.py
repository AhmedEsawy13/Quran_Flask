"""Word identifiers are meaningful only inside their owning database."""
from __future__ import annotations

from core.config import (
    BAHRAIN_LAYOUT_DATABASE,
    QURAN_SCRIPT_DATABASE,
)
from core import layout_persistence
from core import supabase_editor
from core.mushaf_waqf import get_mushaf_waqf_symbols
from modules import layout_engine
from modules.layout_editions import BAHRAIN, MESAHA
from modules.layouts import _find_mushaf_row_match_index
import pytest


def test_quran_script_spans_follow_reading_order_not_numeric_order():
    universe = layout_engine.all_script_word_ids(QURAN_SCRIPT_DATABASE)

    # 2:285 is split around IDs allocated to the opening of surah 3.
    assert layout_engine.existing_word_ids_between(
        6399, 6485, universe=universe,
    ) == [6399, 6400, 6401, 6481, 6482, 6483, 6484, 6485]


def test_layout_editions_expose_distinct_word_id_spaces(client):
    editions = {
        row['id']: row
        for row in client.get('/api/layout-studio/editions').get_json()['editions']
    }
    assert editions['mesaha']['word_id_space'] == 'quran-script-stable-v1'
    assert editions['bahrain']['word_id_space'] == 'qpc-layout-global-v1'

    mesaha = client.get('/api/layout-studio/mesaha/page/61').get_json()
    bahrain = client.get('/api/layout-studio/bahrain/page/61').get_json()
    assert mesaha['word_id_space'] != bahrain['word_id_space']


def test_mesaha_split_span_does_not_inject_another_surah(client):
    page = client.get('/api/layout-studio/mesaha/page/61').get_json()
    line = next(row for row in page['lines'] if row['line_number'] == 12)

    assert [word['word_index'] for word in line['words']] == [
        6399, 6400, 6401, 6481, 6482, 6483, 6484, 6485,
    ]
    assert {word['surah'] for word in line['words']} == {2}
    assert [word['word_key'] for word in line['words']] == [
        '2:285:12', '2:285:13', '2:285:14', '2:285:15',
        '2:285:16', '2:285:17', '2:285:18', '2:285:19',
    ]
    assert client.get(
        '/api/layout-studio/mesaha/page-by-ayah/3/1'
    ).get_json()['page_number'] == 62


def test_bahrain_uses_its_own_qpc_word_universe():
    qpc = layout_engine.script_word_map(BAHRAIN_LAYOUT_DATABASE)
    script = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)

    qpc_word = qpc['id2tok'][7958]
    script_word = script['id2tok'][7958]
    assert (qpc_word['surah'], qpc_word['ayah']) == (3, 84)
    assert (script_word['surah'], script_word['ayah']) != (3, 84)


def test_word_ids_translate_only_through_canonical_keys():
    assert layout_engine.canonical_word_key_for_id(
        BAHRAIN_LAYOUT_DATABASE, 6373,
    ) == '2:285:12'
    assert layout_engine.translate_word_id(
        BAHRAIN_LAYOUT_DATABASE,
        QURAN_SCRIPT_DATABASE,
        6373,
    ) == 6399


def test_cloud_lines_persist_and_translate_canonical_endpoints():
    qpc_line = {
        'line_number': 1,
        'line_type': 'ayah',
        'is_centered': 0,
        'first_word_id': 6373,
        'last_word_id': 6374,
        'first_word_key': '2:285:12',
        'last_word_key': '2:285:13',
        'word_id_space': 'qpc-layout-global-v1',
        'surah_number': 2,
        'line_text': '',
    }

    translated = layout_persistence._normalize_cloud_word_keys(
        MESAHA, 61, [qpc_line],
    )[0]
    assert translated['word_id_space'] == 'quran-script-stable-v1'
    assert translated['first_word_id'] == 6399
    assert translated['last_word_id'] == 6400

    annotated = layout_persistence._cloud_lines_with_word_keys(
        MESAHA, 61, [translated],
    )[0]
    assert annotated['first_word_key'] == '2:285:12'
    assert annotated['last_word_key'] == '2:285:13'


def test_cloud_foreign_namespace_requires_canonical_keys():
    with pytest.raises(
        supabase_editor.SupabaseEditorError,
        match='canonical keys missing',
    ):
        layout_persistence._normalize_cloud_word_keys(
            MESAHA,
            61,
            [{
                'line_type': 'ayah',
                'word_id_space': 'qpc-layout-global-v1',
                'first_word_id': 6373,
                'last_word_id': 6374,
                'surah_number': 2,
            }],
        )


def test_cloud_layout_rejects_ids_from_another_namespace():
    script = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    wrong = script['id2tok'][37]

    with pytest.raises(
        supabase_editor.SupabaseEditorError,
        match='namespace mismatch',
    ):
        layout_persistence._validate_page_word_space(
            BAHRAIN,
            61,
            [{
                'line_type': 'ayah',
                'first_word_id': 37,
                'last_word_id': 37,
                'surah_number': wrong['surah'],
            }],
        )


def test_enrich_ayah_line_fills_blank_surah_and_text():
    from modules.layout_editions import BAHRAIN
    from modules import layout_engine

    word_map = layout_engine.script_word_map(BAHRAIN.script_db)
    line = {
        'line_type': 'ayah',
        'first_word_id': 7958,
        'last_word_id': 7960,
        'surah_number': '',
        'line_text': '',
    }
    enriched = layout_persistence._enrich_ayah_line_metadata(line, word_map)
    assert enriched['surah_number'] == 3
    assert 'قُلْ' in (enriched.get('line_text') or '')


def test_validate_page_word_space_skips_blank_declared_surah():
    # Cloud rows sometimes ship surah_number="" — must not crash hydration.
    layout_persistence._validate_page_word_space(
        BAHRAIN,
        1,
        [{
            'line_type': 'ayah',
            'first_word_id': 1,
            'last_word_id': 4,
            'surah_number': '',
        }],
    )
    layout_persistence._validate_page_word_space(
        BAHRAIN,
        1,
        [{
            'line_type': 'ayah',
            'first_word_id': 1,
            'last_word_id': 4,
            'surah_number': '  ',
        }],
    )


def test_mushaf_waqf_word_index_is_labeled_as_within_ayah():
    rows = get_mushaf_waqf_symbols(2, 255, 'المدينة الجديد')
    marked = next(row for row in rows if row.get('symbols'))

    assert marked['index_space'] == 'ayah-content-word-1based'
    assert marked['word_position'] == marked['word_index']
    assert marked['word_position'] < 100


def test_waqf_word_position_is_not_compared_to_layout_global_id():
    words = [
        {
            'word_index': 5436 + index,
            'word_id_space': 'qpc-layout-global-v1',
            'surah': 2,
            'ayah': 255,
            'text': text,
        }
        for index, text in enumerate(
            ['ٱللَّهُ', 'لَآ', 'إِلَٰهَ', 'إِلَّا', 'هُوَ', 'ٱلۡحَيُّ', 'ٱلۡقَيُّومُۚ']
        )
    ]
    row = {
        'word_position': 7,
        'word_index': 7,  # legacy mushaf_waqf column, not global ID 7
        'index_space': 'ayah-content-word-1based',
        'clean_token': 'ٱلۡقَيُّومُۚ',
    }

    assert _find_mushaf_row_match_index(words, row) == 6
