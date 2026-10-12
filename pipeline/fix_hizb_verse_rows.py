"""Repair marks that two builders put one word early in verses opening with ۞.

In a ۞ verse the waqf table's token_index counts the ۞ while word_index does
not (token = word + 1). Some base rows instead carry token == word. Both
build_indopak_waqf.py («الهندي») and build_madinah_qadeem.py («المدينة
القديم», copied into «المدينة ١٤٢٧») looked rows up by the content word
position, so on those token == word rows their mark landed on — or a new row
was inserted for — the word BEFORE the intended one. The UI then matched the
row's label and drew the mark one word early (e.g. 2:26 «بِهِۦ» for كَثِيرٗا,
2:158 «شَعَآئِرِ» for ٱللَّهِ).

For those columns on token == word rows, the intended QPC position is
word_index + 1. The mark is moved onto the row that represents that word,
merged when the row exists, and a row left without marks is deleted. Rows
whose label already names the intended word are left alone. Empty labels on
rows outside ۞ verses get the QPC word text. Idempotent.
    python3 pipeline/fix_hizb_verse_rows.py [--dry-run]
"""
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'mushaf_waqf.db')
SCRIPT_DB = os.path.join(ROOT, 'data', 'quran_script.db')
SHIFTED_COLS = ('الهندي', 'المدينة القديم', 'المدينة ١٤٢٧')
_MARKS = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـࣰ-ࣲ‍]')


def _fold(word):
    word = re.sub('[أإآٱءؤئا]', '', _MARKS.sub('', word or ''))
    return word.replace('ى', 'ي').replace('ة', 'ه').strip()


def _qpc_words(script):
    words = {}
    for key, text in script.execute('SELECT word_key, text FROM words'):
        s, a, p = map(int, key.split(':'))
        words.setdefault((s, a), {})[p] = text
    return words


def main(dry_run=False):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    qpc = _qpc_words(sqlite3.connect(SCRIPT_DB))
    hizb = {v for v, ws in qpc.items() if (ws.get(1) or '').strip() == '۞'}
    mark_cols = [r[1] for r in conn.execute('PRAGMA table_info(waqf)')][5:]
    log, skipped = [], []

    def verse_rows(s, a):
        return conn.execute('SELECT rowid, * FROM waqf WHERE السورة=? AND الآية=?', (s, a)).fetchall()

    def representative(s, a, pos):
        want = _fold(qpc[(s, a)].get(pos))
        rows = verse_rows(s, a)
        labelled = [r for r in rows if r['الكلمة'] and _fold(r['الكلمة']) == want
                    and abs(r['token_index'] - pos) <= 1]
        if labelled:
            return min(labelled, key=lambda r: abs(r['token_index'] - pos))
        bare = [r for r in rows if not r['الكلمة'] and r['token_index'] == pos]
        return bare[0] if bare else None

    # Plan every move from one snapshot so a mark moved onto another
    # token == word row is not moved a second time.
    moves = []
    for (s, a) in sorted(hizb):
        for row in verse_rows(s, a):
            if row['token_index'] != row['word_index']:
                continue
            for col in SHIFTED_COLS:
                if not row[col]:
                    continue
                pos = row['word_index'] + 1
                if pos not in qpc[(s, a)]:
                    skipped.append(f'{s}:{a} {col}: no QPC word at {pos}')
                    continue
                target = representative(s, a, pos)
                if target is None or target['rowid'] != row['rowid']:
                    moves.append((s, a, row, col, row[col], pos, target))

    leaving = {(row['rowid'], col) for _, _, row, col, _, _, _ in moves}
    for s, a, row, col, value, pos, target in moves:
        if target is not None:
            have = conn.execute(f'SELECT "{col}" FROM waqf WHERE rowid=?', (target['rowid'],)).fetchone()[0]
            if have and have != value and (target['rowid'], col) not in leaving:
                skipped.append(f'{s}:{a} {col}: token {pos} already has {have}, not {value}')
                leaving.discard((row['rowid'], col))
                continue
    for s, a, row, col, value, pos, target in moves:
        if (row['rowid'], col) in leaving:
            conn.execute(f'UPDATE waqf SET "{col}"=NULL WHERE rowid=?', (row['rowid'],))
    for s, a, row, col, value, pos, target in moves:
        if (row['rowid'], col) not in leaving:
            continue
        if target is not None:
            conn.execute(f'UPDATE waqf SET "{col}"=? WHERE rowid=?', (value, target['rowid']))
        else:
            taken = conn.execute('SELECT rowid FROM waqf WHERE السورة=? AND الآية=? AND token_index=?',
                                 (s, a, pos)).fetchone()
            if taken:
                skipped.append(f'{s}:{a} {col}: token {pos} taken by an unrelated row; {value} dropped back')
                conn.execute(f'UPDATE waqf SET "{col}"=? WHERE rowid=?', (value, row['rowid']))
                continue
            conn.execute(
                f'INSERT INTO waqf (السورة, الآية, الكلمة, token_index, word_index, "{col}") '
                'VALUES (?,?,?,?,?,?)', (s, a, qpc[(s, a)][pos], pos, pos - 1, value))
        log.append(f'{s}:{a} {col} {value}: «{row["الكلمة"] or "—"}» (token {row["token_index"]}) '
                   f'→ «{qpc[(s, a)][pos]}» (token {pos})')
    for rowid in {r for r, _ in leaving}:
        left = conn.execute('SELECT ' + ','.join(f'"{c}"' for c in mark_cols) +
                            ' FROM waqf WHERE rowid=?', (rowid,)).fetchone()
        if left is not None and not any(left):
            conn.execute('DELETE FROM waqf WHERE rowid=?', (rowid,))

    # Normalise the rows that stay: in a ۞ verse token = word + 1. A row
    # labelled with the word at its token keeps the token (word_index - 1);
    # one labelled with the next word moves its token up when that is free.
    for (s, a) in sorted(hizb):
        for row in verse_rows(s, a):
            t = row['token_index']
            if t != row['word_index'] or not row['الكلمة']:
                continue
            label = _fold(row['الكلمة'])
            here, nxt = _fold(qpc[(s, a)].get(t)), _fold(qpc[(s, a)].get(t + 1))
            if label == here and label != nxt:
                conn.execute('UPDATE waqf SET word_index=? WHERE rowid=?', (t - 1, row['rowid']))
                log.append(f'{s}:{a} «{row["الكلمة"]}»: word_index {t} → {t - 1}')
            elif label == nxt and label != here:
                if conn.execute('SELECT 1 FROM waqf WHERE السورة=? AND الآية=? AND token_index=?',
                                (s, a, t + 1)).fetchone():
                    skipped.append(f'{s}:{a} «{row["الكلمة"]}»: token {t + 1} taken, index left')
                    continue
                conn.execute('UPDATE waqf SET token_index=? WHERE rowid=?', (t + 1, row['rowid']))
                log.append(f'{s}:{a} «{row["الكلمة"]}»: token_index {t} → {t + 1}')
            else:
                skipped.append(f'{s}:{a} «{row["الكلمة"]}» token {t}: label ambiguous, index left')

    for row in conn.execute("SELECT rowid, * FROM waqf WHERE coalesce(الكلمة,'')=''").fetchall():
        s, a, t = row['السورة'], row['الآية'], row['token_index']
        if (s, a) in hizb or t not in qpc.get((s, a), {}):
            skipped.append(f'{s}:{a} token {t}: empty label left as is')
            continue
        conn.execute('UPDATE waqf SET الكلمة=? WHERE rowid=?', (qpc[(s, a)][t], row['rowid']))
        log.append(f'{s}:{a} token {t}: label set to «{qpc[(s, a)][t]}»')

    print('\n'.join(log) or 'nothing to change')
    if skipped:
        print('skipped:\n  ' + '\n  '.join(skipped))
    if dry_run:
        conn.rollback()
        print(f'dry run: {len(log)} changes not written')
    else:
        conn.commit()
        print(f'{len(log)} changes')
    conn.close()


if __name__ == '__main__':
    main(dry_run='--dry-run' in sys.argv)
