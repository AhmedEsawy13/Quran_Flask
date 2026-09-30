#!/usr/bin/env python3
"""Realign the Bahrain Layout Studio project with the corrected 1421 word map.

Until 2026-09-30 the shared Digital Khatt word map drifted by one word in
surahs 15, 27 and 36: three verses QUL splits into two words (`_DK_TOKEN_SPLITS`
in modules/layouts.py) were treated as one, so every later verse in the surah
sat one layout id early and each surah appeared to end on a "phantom" id
(36047, 52844, 61191 — really the closing ۝ markers).

The Bahrain project was seeded from that map and then reviewed against the
printed edition *through* it. Its line ranges in those surahs therefore
compensate for the drift: every range after the split verse is one id lower
than the true QUL id, and each surah's last line stops one short of the marker.
Its `words` table carries the same shifted text.

Now that the map is correct, this script moves the project into true ids while
preserving exactly what each reviewed line displayed:

  * lines wholly after the split token:   first_word_id += 1, last_word_id += 1
  * the line containing the split token:  last_word_id  += 1  (it gains 2nd half)
  * lines before it, and every other surah: untouched
  * `words` rows for the three surahs are regenerated from the corrected map.

    python3 pipeline/repair_bahrain_word_alignment.py            # dry run
    python3 pipeline/repair_bahrain_word_alignment.py --apply    # backup + write

Idempotent (a repaired DB reports nothing to do) and it refuses to run on a DB
whose closing lines are in neither the compensated nor the repaired state.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import BAHRAIN_LAYOUT_DATABASE  # noqa: E402
from modules.layouts import (  # noqa: E402
    _DK_TOKEN_SPLITS,
    _SYNTHETIC_AYAH_MARKER_BASE,
    _get_dk_layout_word_map,
)

AFFECTED_SURAHS = {surah for surah, _ayah in _DK_TOKEN_SPLITS}


def expected_words():
    """{word_index: (word_key, surah, ayah, text)} from the corrected map."""
    id2tok = _get_dk_layout_word_map()['id2tok']
    positions, rows = {}, {}
    for word_id in sorted(id2tok):
        if word_id >= _SYNTHETIC_AYAH_MARKER_BASE:
            continue
        tok = id2tok[word_id]
        key = (int(tok['surah']), int(tok['ayah']))
        positions[key] = positions.get(key, 0) + 1
        rows[word_id] = (f'{key[0]}:{key[1]}:{positions[key]}', key[0], key[1], tok['text'])
    return rows


def _surah_end(surah):
    """True (QUL) id of the surah's last word — its closing ۝ marker."""
    word_map = _get_dk_layout_word_map()
    return max(v for (s, _a), v in word_map['last_id'].items() if s == surah)


def plan(conn):
    """Return (word_changes, line_changes); ({}, []) means already aligned."""
    word_map = _get_dk_layout_word_map()
    line_changes = []  # (page, line, old_first, old_last, new_first, new_last)
    for (surah, ayah), (index, _offset) in sorted(_DK_TOKEN_SPLITS.items()):
        end_true = _surah_end(surah)
        closing = conn.execute(
            'SELECT page_number, line_number FROM pages WHERE line_type="ayah" '
            'AND CAST(last_word_id AS INT) = ?', (end_true,)).fetchall()
        compensated = conn.execute(
            'SELECT page_number, line_number FROM pages WHERE line_type="ayah" '
            'AND CAST(last_word_id AS INT) = ?', (end_true - 1,)).fetchall()
        if closing and not compensated:
            continue                                   # already in true ids
        if len(compensated) != 1 or closing:
            raise SystemExit(
                f'Surah {surah}: closing line is in neither the compensated nor the '
                f'repaired state ({len(compensated)} lines end at {end_true - 1}, '
                f'{len(closing)} at {end_true}). Refusing to guess.')

        split_id = word_map['first_id'][(surah, ayah)] + index
        rows = conn.execute(
            'SELECT page_number, line_number, CAST(first_word_id AS INT), CAST(last_word_id AS INT) '
            'FROM pages WHERE line_type="ayah" AND first_word_id IS NOT NULL AND first_word_id <> "" '
            'AND CAST(last_word_id AS INT) BETWEEN ? AND ? ORDER BY page_number, line_number',
            (split_id, end_true - 1)).fetchall()
        for page, line, first, last in rows:
            if first > split_id:
                line_changes.append((page, line, first, last, first + 1, last + 1))
            else:                                      # contains the split token
                line_changes.append((page, line, first, last, first, last + 1))

    expected = expected_words()
    current = {
        row[0]: row[1:]
        for row in conn.execute('SELECT word_index, word_key, surah, ayah, text FROM words')
    }
    word_changes = {i: row for i, row in expected.items() if current.get(i) != row}
    stray = {i for i, row in word_changes.items() if row[1] not in AFFECTED_SURAHS}
    if stray:
        raise SystemExit(f'Refusing: {len(stray)} word changes outside surahs '
                         f'{sorted(AFFECTED_SURAHS)} (e.g. {sorted(stray)[:5]}).')
    return word_changes, line_changes


def apply(conn, word_changes, line_changes):
    conn.executemany(
        'INSERT OR REPLACE INTO words (word_index, word_key, surah, ayah, text, text_original) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        [(wid, key, s, a, text, text) for wid, (key, s, a, text) in word_changes.items()],
    )
    conn.executemany(
        'UPDATE pages SET first_word_id = ?, last_word_id = ? WHERE page_number = ? AND line_number = ?',
        [(nf, nl, page, line) for page, line, _of, _ol, nf, nl in line_changes],
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--apply', action='store_true', help='write changes (a backup is made first)')
    parser.add_argument('--db', default=BAHRAIN_LAYOUT_DATABASE)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        word_changes, line_changes = plan(conn)
        by_surah = {}
        for row in word_changes.values():
            by_surah[row[1]] = by_surah.get(row[1], 0) + 1
        pages = sorted({c[0] for c in line_changes})
        print(f'words to rewrite: {len(word_changes)} {dict(sorted(by_surah.items()))}')
        print(f'lines to shift: {len(line_changes)} on {len(pages)} pages')
        if not word_changes and not line_changes:
            print('Already aligned — nothing to do.')
            return
        if not args.apply:
            print('Dry run. Re-run with --apply to write.')
            return
        backup = f'{args.db[:-3]}.backup_alignment_{time.strftime("%Y%m%dT%H%M%S")}.db'
        shutil.copyfile(args.db, backup)
        print(f'backup: {backup}')
        apply(conn, word_changes, line_changes)
        assert plan(conn) == ({}, []), 'repair did not converge'
        print(f'applied; integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
