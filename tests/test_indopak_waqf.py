"""«الهندي» must equal the IndoPak source text, mark for mark, on the right word."""
from __future__ import annotations

import json
import sqlite3

from pipeline.build_indopak_waqf import (
    INDOPAK_JSON, MUSHAF_WAQF_DB, QURAN_SCRIPT_DB, derive_marks, stored_marks,
)


def test_indopak_column_equals_the_source():
    indopak = json.loads(INDOPAK_JSON.read_text(encoding='utf-8'))
    marks, unplaced = derive_marks(indopak, sqlite3.connect(QURAN_SCRIPT_DB))
    assert unplaced == []
    assert stored_marks(sqlite3.connect(MUSHAF_WAQF_DB)) == marks


def test_marks_follow_the_words_not_the_count():
    # Verses where the IndoPak text splits words differently (2026-10-15): counting
    # put these one word off (27:20 on «أم», 72:16 on the verse number).
    have = stored_marks(sqlite3.connect(MUSHAF_WAQF_DB))
    qs = sqlite3.connect(QURAN_SCRIPT_DB)
    word = lambda s, a, t: qs.execute('SELECT text FROM words WHERE word_key=?', (f'{s}:{a}:{t}',)).fetchone()[0]
    assert word(27, 20, 7) == 'ٱلۡهُدۡهُدَ' and have[(27, 20, 7)] == 'ۖؗ'
    assert (72, 16, 7) in have and word(72, 16, 7) == 'غَدَقٗا'
    assert have[(2, 286, 6)] == 'ؕ'          # one of the 32 that were never written
