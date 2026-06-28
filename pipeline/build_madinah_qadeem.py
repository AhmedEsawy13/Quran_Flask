"""Add the «المدينة القديم» waqf column to data/mushaf_waqf.db.

Source: the Tanzil "Simple Clean" text (quran-simple-clean.sql), whose embedded
waqf marks are the OLD Madinah print's set — notably it still carries the ۙ (لا)
sign that the current «المدينة» (now «المدينة الجديد») dropped.

Marks are aligned to the project's QPC word positions: each Simple-Clean word is
matched to its QPC counterpart with a normalized diff (exact where the spelling
matches, positional inside replace/delete blocks), then the mark is written at
that word's token_index/word_index — the same basis every other mushaf column
uses. Run once:  python3 pipeline/build_madinah_qadeem.py path/to/quran-simple-clean.sql
"""
import os
import re
import sys
import sqlite3
import difflib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402  (for _verse_word_texts + _normalize_for_search)

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'mushaf_waqf.db')
OLD_COL = 'المدينة القديم'
NEW_COL = 'المدينة الجديد'

# Tanzil embedded waqf glyph → the letter form the mushaf_waqf DB stores.
WAQF = {'ۖ': 'ص', 'ۗ': 'ق', 'ۘ': 'م', 'ۙ': 'لا', 'ۚ': 'ج', 'ۛ': 'ع', 'ۜ': 'س'}


def parse_sql(path):
    txt = open(path, encoding='utf-8').read()
    rows = re.findall(r"\((\d+),\s*(\d+),\s*(\d+),\s*'((?:[^'\\]|\\.)*)'\)", txt)
    return [(int(s), int(a), t) for _, s, a, t in rows]


def verse_marks(text):
    """(word_index_0based, mark_letter) for each embedded waqf mark."""
    words, marks = [], []
    for tok in text.split():
        core = ''.join(c for c in tok if c not in WAQF)
        tm = [c for c in tok if c in WAQF]
        if core.strip():
            words.append(core)
            for c in tm:
                marks.append((len(words) - 1, WAQF[c]))
        else:
            for c in tm:
                if words:
                    marks.append((len(words) - 1, WAQF[c]))
    return words, marks


def align(sc_words, qpc_words):
    """Map each Simple-Clean word index → QPC word index (full coverage)."""
    fold = app._normalize_for_search
    a = [fold(w) for w in sc_words]
    b = [fold(w) for w in qpc_words]
    mp = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        for k in range(i1, i2):
            if tag == 'equal':
                mp[k] = j1 + (k - i1)
            elif tag == 'replace' and j2 > j1:
                mp[k] = j1 + min(k - i1, j2 - j1 - 1)
            else:  # delete (or empty replace) → nearest QPC word
                mp[k] = max(0, min(j1, len(qpc_words) - 1))
    return mp


def main(sql_path):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute('PRAGMA table_info(waqf)')]

    if 'المدينة' in cols and NEW_COL not in cols:
        cur.execute(f'ALTER TABLE waqf RENAME COLUMN "المدينة" TO "{NEW_COL}"')
        print(f'renamed المدينة → {NEW_COL}')
    if OLD_COL not in [r[1] for r in cur.execute('PRAGMA table_info(waqf)')]:
        cur.execute(f'ALTER TABLE waqf ADD COLUMN "{OLD_COL}" TEXT')
        print(f'added column {OLD_COL}')

    # token_index / word_index per (sura,aya,wpos) from the QPC text.
    updated = inserted = unmapped = 0
    for sura, aya, text in parse_sql(sql_path):
        _, marks = verse_marks(text)
        if not marks:
            continue
        sc_words, _m2 = verse_marks(text)  # sc_words from same parse
        _, qpc_words, raw_to_wpos = app._verse_word_texts(f'{sura}:{aya}')
        if not qpc_words:
            continue
        wpos_to_raw = {}
        for raw_i, wp in enumerate(raw_to_wpos):
            if wp is not None and wp not in wpos_to_raw:
                wpos_to_raw[wp] = raw_i
        mp = align(sc_words, qpc_words)

        # one mark per QPC word (last wins), to avoid dup rows
        by_wpos = {}
        for sc_wp, letter in marks:
            j = mp.get(sc_wp)
            if j is None:
                unmapped += 1
                continue
            by_wpos[j] = letter

        for j, letter in by_wpos.items():
            word_index = j + 1
            raw_i = wpos_to_raw.get(j)
            token_index = (raw_i + 1) if raw_i is not None else word_index
            word_text = qpc_words[j] if 0 <= j < len(qpc_words) else ''
            row = cur.execute(
                'SELECT rowid FROM waqf WHERE "السورة"=? AND "الآية"=? AND word_index=?',
                (sura, aya, word_index)).fetchone()
            if row:
                cur.execute(f'UPDATE waqf SET "{OLD_COL}"=? WHERE rowid=?', (letter, row[0]))
                updated += 1
            else:
                cur.execute(
                    f'INSERT INTO waqf ("السورة","الآية","الكلمة",token_index,word_index,"{OLD_COL}") '
                    'VALUES (?,?,?,?,?,?)',
                    (sura, aya, word_text, token_index, word_index, letter))
                inserted += 1

    conn.commit()
    total = cur.execute(f'SELECT COUNT(*) FROM waqf WHERE "{OLD_COL}" IS NOT NULL').fetchone()[0]
    la = cur.execute(f'SELECT COUNT(*) FROM waqf WHERE "{OLD_COL}"=?', ('لا',)).fetchone()[0]
    conn.close()
    print(f'updated={updated} inserted={inserted} unmapped={unmapped} → {OLD_COL} marks={total} (لا={la})')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/Users/mac/Downloads/quran-simple-clean.sql')
