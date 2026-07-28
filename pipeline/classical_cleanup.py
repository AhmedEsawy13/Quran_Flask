#!/usr/bin/env python3
"""Deterministic cleanup for duplicate classical-waqf extraction output.

The books often state one explanation and then apply it to several stopping
points with wording such as ``ومثله``.  Extraction can consequently copy the
same explanation onto every row, making the learner UI repeat a paragraph
several times.  Keep every distinct ruling/position, but keep an identical or
fully-contained explanation only on its richest row in that verse.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import os
import sqlite3


ROW_FIELDS = (
    'source', 'surah', 'ayah', 'wpos', 'stop_word', 'quote', 'grade',
    'grade_raw', 'note', 'seq', 'conf', 'reported_from',
)
_EXACT_FIELDS = (
    'source', 'surah', 'ayah', 'wpos', 'stop_word', 'quote', 'grade',
    'grade_raw', 'note', 'conf', 'reported_from',
)


def _clean_text(value):
    return ' '.join((value or '').split())


def clean_rows(rows):
    """Return cleaned 12-column build rows plus cleanup statistics.

    Exact duplicate judgments are removed. Distinct grades, readings,
    attributions, positions, and explanations are never merged. Within one
    verse and one attribution, repeated or verbatim-contained explanations
    are retained only once; the other judgments remain with an empty note.
    """
    records = [dict(zip(ROW_FIELDS, row)) for row in rows]

    unique = []
    seen = set()
    exact_rows_removed = 0
    for record in records:
        key = tuple(record[field] for field in _EXACT_FIELDS)
        if key in seen:
            exact_rows_removed += 1
            continue
        seen.add(key)
        unique.append(record)

    groups = defaultdict(list)
    for order, record in enumerate(unique):
        note = _clean_text(record['note'])
        if note:
            groups[(
                record['source'], record['surah'], record['ayah'],
                record['reported_from'] or '',
            )].append((order, record, note))

    notes_suppressed = 0
    exact_notes_suppressed = 0
    contained_notes_suppressed = 0
    affected_verses = set()
    for group, items in groups.items():
        accepted = []
        items.sort(key=lambda item: (
            -len(item[2]),
            item[1]['seq'] if item[1]['seq'] is not None else 10**9,
            item[0],
        ))
        for _, record, note in items:
            exact = any(note == kept for kept in accepted)
            contained = len(note) >= 30 and any(note in kept for kept in accepted)
            if exact or contained:
                record['note'] = ''
                notes_suppressed += 1
                exact_notes_suppressed += int(exact)
                contained_notes_suppressed += int(contained and not exact)
                affected_verses.add((group[1], group[2]))
            else:
                accepted.append(note)

    cleaned = [tuple(record[field] for field in ROW_FIELDS) for record in unique]
    return cleaned, {
        'exact_rows_removed': exact_rows_removed,
        'notes_suppressed': notes_suppressed,
        'exact_notes_suppressed': exact_notes_suppressed,
        'contained_notes_suppressed': contained_notes_suppressed,
        'affected_verses': len(affected_verses),
    }


def clean_database(path, source='manar'):
    """Apply the same cleanup in place while preserving stable review IDs."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        stored = [dict(row) for row in conn.execute(
            'SELECT id, source, surah, ayah, wpos, stop_word, quote, grade, '
            'grade_raw, note, seq, conf, reported_from FROM classical '
            'WHERE source=? ORDER BY surah, ayah, seq, id',
            (source,),
        ).fetchall()]

        unique = []
        seen = set()
        deleted_ids = []
        for record in stored:
            key = tuple(record[field] for field in _EXACT_FIELDS)
            if key in seen:
                deleted_ids.append(record['id'])
            else:
                seen.add(key)
                unique.append(record)

        groups = defaultdict(list)
        for record in unique:
            note = _clean_text(record['note'])
            if note:
                groups[(
                    record['source'], record['surah'], record['ayah'],
                    record['reported_from'] or '',
                )].append((record, note))

        blank_ids = []
        exact_notes = 0
        contained_notes = 0
        affected_verses = set()
        for group, items in groups.items():
            accepted = []
            items.sort(key=lambda item: (
                -len(item[1]),
                item[0]['seq'] if item[0]['seq'] is not None else 10**9,
                item[0]['id'],
            ))
            for record, note in items:
                exact = any(note == kept for kept in accepted)
                contained = len(note) >= 30 and any(note in kept for kept in accepted)
                if exact or contained:
                    blank_ids.append(record['id'])
                    exact_notes += int(exact)
                    contained_notes += int(contained and not exact)
                    affected_verses.add((group[1], group[2]))
                else:
                    accepted.append(note)

        if deleted_ids:
            conn.executemany('DELETE FROM classical WHERE id=?',
                             [(row_id,) for row_id in deleted_ids])
        if blank_ids:
            conn.executemany("UPDATE classical SET note='' WHERE id=?",
                             [(row_id,) for row_id in blank_ids])
        conn.commit()
        return {
            'source': source,
            'before': len(stored),
            'after': len(stored) - len(deleted_ids),
            'exact_rows_removed': len(deleted_ids),
            'notes_suppressed': len(blank_ids),
            'exact_notes_suppressed': exact_notes,
            'contained_notes_suppressed': contained_notes,
            'affected_verses': len(affected_verses),
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('db')
    parser.add_argument('--source', default='manar')
    args = parser.parse_args()
    if not os.path.exists(args.db):
        parser.error(f'database not found: {args.db}')
    print(clean_database(args.db, args.source))


if __name__ == '__main__':
    main()
