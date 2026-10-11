"""Reviewer helper: the DB rows and numbered verse words for a span.

    python3 pipeline/review/random_check/show_rows.py BOOK SURAH FIRST_AYAH LAST_AYAH

BOOK is muktafa | manar | anbari | nahhas. wpos is 0-based. conf=0 rows are held
back (not shown to users); they are listed with [held].
"""
import os
import sqlite3
import sys

sys.path.insert(0, '.')
from core.verse_words import verse_word_texts  # noqa: E402

book, surah, a0, a1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
# CLASSICAL_WAQF_DB points at a copy (reviewer calibration with planted errors)
con = sqlite3.connect(os.environ.get('CLASSICAL_WAQF_DB', 'data/classical_waqf.db'))
for a in range(a0, a1 + 1):
    words = verse_word_texts(f'{surah}:{a}')[1]
    if not words:
        continue
    print(f'\n{surah}:{a}  ' + ' '.join(f'{i}:{w}' for i, w in enumerate(words)))
    for rid, w, q, g, raw, by, conf, note in con.execute(
            "SELECT id, wpos, quote, grade, grade_raw, COALESCE(reported_from,''), conf, "
            "substr(COALESCE(note,''),1,140) FROM classical WHERE source=? AND surah=? AND ayah=? "
            "ORDER BY wpos, id", (book, surah, a)):
        held = '' if conf else ' [held]'
        print(f'   id={rid} wpos={w} «{q}» {g} (raw {raw}){" by " + by if by else ""}{held}  | {note}')
unseated = con.execute("SELECT id, quote, grade, COALESCE(reported_from,'') FROM classical WHERE source=? "
                       "AND surah=? AND ayah IS NULL", (book, surah)).fetchall()
if unseated:
    print('\nunseated (held) rows in this surah:', unseated)
