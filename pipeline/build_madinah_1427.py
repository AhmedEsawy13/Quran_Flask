"""Add the «المدينة ١٤٢٧» waqf column (print B) to data/mushaf_waqf.db.

The Madinah mushaf has three waqf states:
  A  «المدينة القديم»  the 1405 edition (copies up to ~1421)
  B  «المدينة ١٤٢٧»    the 1420 edition as printed ~1421–1428
  C  «المدينة الجديد»  the revised print (~1429 → now, current QPC)

No machine-readable copy of B exists, so it is RECONSTRUCTED: A, minus every
«لا» (B dropped them all), plus the 171 seats that the ملتقى أهل التفسير thread
16711 lists as changed between A and a 1427 copy of B
(data/research_cache/madinah_waqf_diff_forum.json). Every other seat keeps A's
mark, because the thread's author says the list is complete.

Each forum seat is located by its QPC word text near its word position. The
script refuses to write unless every seat's A mark equals the forum's «أ».
Re-runnable: it overwrites the column.  python3 pipeline/build_madinah_1427.py
"""
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'mushaf_waqf.db')
FORUM = os.path.join(ROOT, 'data', 'research_cache', 'madinah_waqf_diff_forum.json')
OLD_COL = 'المدينة القديم'
B_COL = 'المدينة ١٤٢٧'

_MARKS = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')


def _fold(word):
    word = re.sub('[أإآٱءؤئا]', '', _MARKS.sub('', word or ''))
    return word.replace('ى', 'ي').replace('ة', 'ه').strip()


def locate(conn, seat):
    """rowid of the waqf row for a forum seat (text match, nearest index)."""
    rows = conn.execute(
        'SELECT rowid, word_index, الكلمة FROM waqf WHERE السورة=? AND الآية=?',
        (seat['surah'], seat['ayah'])).fetchall()
    want = _fold(seat['word'])
    cands = [r for r in rows
             if r[2] and _fold(r[2]) == want and abs(r[1] - seat['word_pos']) <= 2]
    if not cands:
        return None
    return min(cands, key=lambda r: abs(r[1] - seat['word_pos']))[0]


def main():
    seats = json.load(open(FORUM, encoding='utf-8'))['entries']
    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(waqf)')}

    plan, problems = [], []
    for seat in seats:
        rowid = locate(conn, seat)
        if rowid is None:
            problems.append(f"{seat['id']} {seat['surah']}:{seat['ayah']} {seat['word']}: no DB row")
            continue
        old = conn.execute(f'SELECT coalesce("{OLD_COL}", "") FROM waqf WHERE rowid=?',
                           (rowid,)).fetchone()[0]
        if old != seat['old_mark']:
            problems.append(f"{seat['id']} {seat['surah']}:{seat['ayah']} {seat['word']}: "
                            f"DB أ={old or '—'} forum أ={seat['old_mark'] or '—'}")
        plan.append((seat['new_mark'] or None, rowid))
    if problems:
        sys.exit('refusing to write:\n  ' + '\n  '.join(problems))

    if B_COL not in cols:
        conn.execute(f'ALTER TABLE waqf ADD COLUMN "{B_COL}" TEXT')
    conn.execute(f'''UPDATE waqf SET "{B_COL}" =
                     CASE WHEN "{OLD_COL}" = 'لا' OR "{OLD_COL}" = '' THEN NULL
                          ELSE "{OLD_COL}" END''')
    conn.executemany(f'UPDATE waqf SET "{B_COL}" = ? WHERE rowid = ?', plan)
    conn.commit()

    count = lambda col: conn.execute(
        f'SELECT count(*) FROM waqf WHERE coalesce("{col}", "") <> ""').fetchone()[0]
    differ = conn.execute(
        f'SELECT count(*) FROM waqf WHERE coalesce("{OLD_COL}","") <> coalesce("{B_COL}","")'
    ).fetchone()[0]
    print(f'{B_COL}: {count(B_COL)} marks ({OLD_COL}: {count(OLD_COL)}); '
          f'{len(plan)} forum seats applied; {differ} seats differ from {OLD_COL}')
    conn.close()


if __name__ == '__main__':
    main()
