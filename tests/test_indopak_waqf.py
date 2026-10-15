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


def test_signs_typed_without_a_space_count():
    # 15 signs in the source sit on their word with no space (2:219 «الْعَفْوَؕ» …);
    # an attached ؔ (76:15 «قَوَارِیْرَاۡؔ») is a spelling sign, not a stop.
    have = stored_marks(sqlite3.connect(MUSHAF_WAQF_DB))
    assert have[(2, 219, 20)] == 'ؕ' and have[(3, 2, 5)] == 'ۙ'
    assert 'ؔ' not in have.get((76, 15, 8), '') and (76, 16, 1) not in have


def test_two_source_corrections_are_applied():
    # quranwbw.com and quran.com agree against the source here (2026-10-15)
    have = stored_marks(sqlite3.connect(MUSHAF_WAQF_DB))
    assert have[(41, 24, 5)] == 'ؕ' and have[(58, 4, 10)] == 'ؕ'
    assert have[(11, 94, 10)] == 'ۚ' and have[(3, 4, 18)] == 'ؕ'


def test_printed_page_corrections_are_applied():
    # settled on the printed IndoPak pages (app.quranflash.com NaskhTaleek), 2026-10-15
    have = stored_marks(sqlite3.connect(MUSHAF_WAQF_DB))
    assert have[(49, 10, 6)] == 'ۚ' and have[(9, 18, 17)] == '۫' and have[(43, 45, 7)] == 'ۗ'
    assert have[(42, 13, 39)] == 'ؕ' and have[(42, 34, 7)] == 'ؗۙ' and have[(79, 27, 6)] == '۫'
    assert have[(20, 88, 11)] == 'ۙۚ۬'                # «موسى»: ۵ with لا and ج above
    assert (59, 2, 28) not in have                    # «يحتسبوا»: stray ۗ, nothing printed
    assert have[(59, 2, 12)] == 'ؔؕ'                  # «لأول الحشر»: the margin «وقف النبي»
    assert have[(19, 31, 11)] == 'ۙ'                  # «حيًّا»: only لا over the verse circle
    assert (37, 35, 9) not in have and (69, 7, 7) not in have   # «الله», «حسومًا»: nothing printed


def test_indopak_meanings_follow_the_printed_key():
    """«رموز اوقاف قرآن مجید» at the end of the IndoPak mushaf, checked on its pages."""
    from modules.waqf_research import _mushaf_sem_class as sem
    assert sem('الهندي', 'ۗ') == 'NOSTOP'         # ق قيل عليه الوقف (2:5 «ربهم»)
    assert sem('الهندي', '۪') == 'CONT'           # ص مرخَّص (2:16, 2:23)
    assert sem('الهندي', 'ۖۚ') == 'CONT'          # صلے over ج (2:2 «ريب»)
    assert sem('الهندي', '۫') == 'STOP'           # قف (9:18, 79:27)
    assert sem('الهندي', 'ۥ') == 'SAKTA'          # وقفہ (2:286)
    assert sem('الهندي', '۬') is None             # ۵ — verse end for non-Kufans
    assert sem('الهندي', 'ؔؕ') == 'ABS'            # ؔ is a margin-note flag; ط is the ruling
