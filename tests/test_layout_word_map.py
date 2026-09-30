"""The 1421 (Digital Khatt / QPC v1) layout's word-id map must stay in step.

The layout DB numbers words 1..83668 in QUL's tokenisation; we assign those ids
to our Digital Khatt text token by token, anchored at each surah's first id.
If one verse is tokenised differently, every later verse in the surah lands a
word early — page 442 once ended on the first word of 36:41 instead of ۝٤٠, and
يس's last id looked like a "phantom" with no word.
"""
import re
import sqlite3

from core.config import QPC_V2_LAYOUT_DATABASE
from core.datasets import digital_khatt_data
from modules import layouts

SYNTHETIC_BASE = layouts._SYNTHETIC_AYAH_MARKER_BASE


def _surah_spans():
    conn = sqlite3.connect(QPC_V2_LAYOUT_DATABASE)
    try:
        rows = conn.execute(
            'SELECT line_type, surah_number, first_word_id, last_word_id '
            'FROM pages ORDER BY page_number, line_number'
        ).fetchall()
    finally:
        conn.close()
    spans, current = {}, None
    for line_type, surah, first, last in rows:
        if line_type == 'surah_name' and surah:
            current = int(surah)
        if line_type == 'ayah' and current and first not in (None, ''):
            lo, hi = spans.setdefault(current, [int(first), int(last)])
            spans[current] = [min(lo, int(first)), max(hi, int(last))]
    return spans


def test_every_layout_id_of_every_surah_maps_to_a_word():
    """Layout span == mapped words, for every surah.

    الصافات is the only surah whose final ayah marker falls outside the layout
    ids (a synthetic marker covers it, and it is excluded here). Any other
    surplus or shortfall means a verse is tokenised differently from the layout
    and every later verse in that surah drifts by a word.
    """
    word_map = layouts._get_dk_layout_word_map()
    mapped = {}
    for word_id, tok in word_map['id2tok'].items():
        if word_id < SYNTHETIC_BASE:
            mapped[tok['surah']] = mapped.get(tok['surah'], 0) + 1

    spans = _surah_spans()
    assert len(spans) == 114
    problems = {
        surah: (last - first + 1, mapped.get(surah, 0))
        for surah, (first, last) in spans.items()
        if mapped.get(surah, 0) != last - first + 1
    }
    assert problems == {}, f'surah: (layout ids, mapped words) {problems}'
    # 37:182's closing marker is the documented overflow case (synthetic id).
    assert word_map['append_after_id']


def test_verse_splits_are_lossless_and_only_where_declared():
    """A split token keeps every codepoint DK wrote; nothing else is split."""
    word_map = layouts._get_dk_layout_word_map()
    assert set(layouts._DK_TOKEN_SPLITS) == {(15, 7), (27, 20), (36, 22)}
    for (surah, ayah), (index, offset) in layouts._DK_TOKEN_SPLITS.items():
        tokens = [w for w in re.split(r'\s+', digital_khatt_data[f'{surah}:{ayah}']['text'].strip()) if w]
        first = word_map['first_id'][(surah, ayah)]
        last = word_map['last_id'][(surah, ayah)]
        assert last - first + 1 == len(tokens) + 1            # one extra layout id
        id_a, id_b = first + index, first + index + 1
        joined = word_map['id2tok'][id_a]['text'] + word_map['id2tok'][id_b]['text']
        assert joined == tokens[index]
        assert word_map['id2tok'][id_a]['text'] == tokens[index][:offset]
        assert all(word_map['id2tok'][first + i]['text'] == tokens[i] for i in range(index))
        assert word_map['id2tok'][last]['ayah'] == ayah        # verse still closes on its own last id


def test_page_442_ends_on_the_verse_mark_and_443_starts_verse_41(client):
    """Regression: 36:22 (`وَمَا لِيَ` = two layout words) shifted the rest of Ya-Sin."""
    last = client.get('/api/digital-khatt/page/442').get_json()['lines'][-1]
    assert last['display_text'].endswith('۝٤٠')
    first = client.get('/api/digital-khatt/page/443').get_json()['lines'][0]
    assert first['display_text'].startswith('وَءَايَةࣱ')
    assert first['words'][0]['ayah'] == 41


def test_qpc_v1_shares_the_fixed_map(client):
    """1405 (V1) has different line breaks but the same word numbering."""
    last = client.get('/api/qpc-v1/page/442').get_json()['lines'][-1]
    assert last['display_text'].endswith('٤٠')
    first = client.get('/api/qpc-v1/page/443').get_json()['lines'][0]
    assert first['words'][0]['ayah'] == 41


def test_yasin_closes_with_its_real_final_marker():
    """61191 used to be an unmapped 'phantom'; it is the real ۝٨٣ marker."""
    word_map = layouts._get_dk_layout_word_map()
    assert word_map['id2tok'][61191]['ayah'] == 83
    assert word_map['id2tok'][61191]['text'].endswith('٨٣')


def test_bahrain_project_words_and_closing_lines_match_the_map():
    """The Bahrain studio DB must not carry the old shifted words again."""
    import importlib.util
    import pathlib
    from core.config import BAHRAIN_LAYOUT_DATABASE

    script = pathlib.Path(__file__).resolve().parents[1] / 'pipeline' / 'repair_bahrain_word_alignment.py'
    spec = importlib.util.spec_from_file_location('repair_bahrain_word_alignment', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(f'file:{BAHRAIN_LAYOUT_DATABASE}?mode=ro', uri=True)
    try:
        assert module.plan(conn) == ({}, [])
    finally:
        conn.close()
