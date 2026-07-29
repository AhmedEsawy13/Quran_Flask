#!/usr/bin/env python3
"""Align the final Azhar pages to reviewer-confirmed printed-page anchors.

The operation is deliberately conservative:
  * Quran/header rows keep their current order, word ranges, text, and IDs.
  * Only empty ayah slots are redistributed.
  * Pages 517..525 remain exactly 15 rows each.
  * A page-range undo snapshot is stored before any write.

Confirmed starts:
  519 سورة العاديات
  521 سورة الهمزة
  522 سورة قريش
  523 سورة الكوثر
  524 بسملة سورة النصر
  525 سورة الفلق
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.config import AZHAR_LAYOUT_DATABASE  # noqa: E402
from modules import layout_engine as engine  # noqa: E402

PAGE_FROM = 517
PAGE_TO = 525
LINES_PER_PAGE = 15
ANCHORS = (
    (519, 'surah_name', 100),
    (521, 'surah_name', 104),
    (522, 'surah_name', 106),
    (523, 'surah_name', 108),
    (524, 'basmallah', 110),
    (525, 'surah_name', 113),
)


def _is_empty_ayah(row: dict) -> bool:
    return (
        row['line_type'] == 'ayah'
        and row.get('first_word_id') is None
        and row.get('last_word_id') is None
        and not (row.get('line_text') or '').strip()
    )


def _blank_row(row: dict, surah_number: int | None) -> dict:
    row.update({
        'line_type': 'ayah',
        'is_centered': 0,
        'first_word_id': None,
        'last_word_id': None,
        'surah_number': surah_number,
        'line_text': '',
    })
    return row


def align_tail(database: str = AZHAR_LAYOUT_DATABASE) -> dict:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = [
            dict(row) for row in cur.execute(
                '''
                SELECT id, page_number, line_number, line_type, is_centered,
                       first_word_id, last_word_id, surah_number, line_text
                FROM pages
                WHERE page_number BETWEEN ? AND ?
                ORDER BY page_number, line_number
                ''',
                (PAGE_FROM, PAGE_TO),
            ).fetchall()
        ]
        expected_slots = (PAGE_TO - PAGE_FROM + 1) * LINES_PER_PAGE
        if len(rows) != expected_slots:
            raise ValueError(
                f'Expected {expected_slots} rows on pages '
                f'{PAGE_FROM}..{PAGE_TO}, found {len(rows)}'
            )

        content = [row for row in rows if not _is_empty_ayah(row)]
        empty_pool = [row for row in rows if _is_empty_ayah(row)]

        def anchor_index(line_type: str, surah_number: int) -> int:
            matches = [
                index for index, row in enumerate(content)
                if row['line_type'] == line_type
                and int(row.get('surah_number') or 0) == surah_number
            ]
            if len(matches) != 1:
                raise ValueError(
                    f'Expected one {line_type} anchor for surah '
                    f'{surah_number}, found {len(matches)}'
                )
            return matches[0]

        anchor_indices = [
            anchor_index(line_type, surah_number)
            for _, line_type, surah_number in ANCHORS
        ]
        if anchor_indices != sorted(anchor_indices):
            raise ValueError('Tail anchors are not in Quran order')

        prefix = content[:anchor_indices[0]]
        if len(prefix) > 2 * LINES_PER_PAGE:
            raise ValueError('Content before سورة العاديات exceeds pages 517–518')

        segments = []
        for index, (page_number, _, _) in enumerate(ANCHORS):
            start = anchor_indices[index]
            end = (
                anchor_indices[index + 1]
                if index + 1 < len(anchor_indices)
                else len(content)
            )
            capacity = (
                (ANCHORS[index + 1][0] - page_number) * LINES_PER_PAGE
                if index + 1 < len(ANCHORS)
                else (PAGE_TO - page_number + 1) * LINES_PER_PAGE
            )
            segment = content[start:end]
            if len(segment) > capacity:
                raise ValueError(
                    f'Anchor block at page {page_number} needs '
                    f'{len(segment)} rows but has {capacity} slots'
                )
            segments.append((page_number, capacity, segment))

        needed_blanks = (
            2 * LINES_PER_PAGE - len(prefix)
            + sum(capacity - len(segment) for _, capacity, segment in segments)
        )
        if needed_blanks != len(empty_pool):
            raise ValueError(
                f'Need {needed_blanks} empty rows but found {len(empty_pool)}'
            )

        blank_cursor = 0

        def take_blanks(count: int, surah_number: int | None) -> list[dict]:
            nonlocal blank_cursor
            selected = empty_pool[blank_cursor:blank_cursor + count]
            if len(selected) != count:
                raise ValueError('Empty-row pool exhausted')
            blank_cursor += count
            return [_blank_row(row, surah_number) for row in selected]

        prefix_surah = int(prefix[-1].get('surah_number') or 99) if prefix else 99
        # Keep any content immediately before سورة العاديات at the bottom of
        # the two-page prefix. Reviewer-confirmed upstream reconstruction can
        # fill the whole prefix; older compressed data leaves honest blank
        # review slots instead of invented Quran text.
        output = take_blanks(
            2 * LINES_PER_PAGE - len(prefix),
            prefix_surah,
        )
        output.extend(prefix)

        padding_by_page = {}
        for page_number, capacity, segment in segments:
            output.extend(segment)
            pad = capacity - len(segment)
            padding_by_page[page_number] = pad
            segment_surah = (
                int(segment[-1].get('surah_number') or 0)
                if segment else None
            )
            output.extend(take_blanks(pad, segment_surah))

        if len(output) != expected_slots or blank_cursor != len(empty_pool):
            raise ValueError('Tail reconstruction did not consume every row')
        if sorted(row['id'] for row in output) != sorted(row['id'] for row in rows):
            raise ValueError('Tail reconstruction changed the row-ID set')

        engine.push_undo(
            cur,
            'azhar-tail-anchor-alignment',
            519,
            PAGE_FROM,
            PAGE_TO,
            undo_table='azhar_layout_undo',
        )
        cur.execute(
            '''
            UPDATE pages
            SET line_number = -id
            WHERE page_number BETWEEN ? AND ?
            ''',
            (PAGE_FROM, PAGE_TO),
        )
        for offset, row in enumerate(output):
            page_number = PAGE_FROM + offset // LINES_PER_PAGE
            line_number = offset % LINES_PER_PAGE + 1
            cur.execute(
                '''
                UPDATE pages
                SET page_number = ?, line_number = ?, line_type = ?,
                    is_centered = ?, first_word_id = ?, last_word_id = ?,
                    surah_number = ?, line_text = ?
                WHERE id = ?
                ''',
                (
                    page_number,
                    line_number,
                    row['line_type'],
                    int(bool(row.get('is_centered'))),
                    row.get('first_word_id'),
                    row.get('last_word_id'),
                    row.get('surah_number'),
                    row.get('line_text') or '',
                    int(row['id']),
                ),
            )
        conn.commit()

        resolved = {}
        for page_number, line_type, surah_number in ANCHORS:
            position = cur.execute(
                '''
                SELECT page_number, line_number
                FROM pages
                WHERE line_type = ? AND surah_number = ?
                ORDER BY page_number, line_number
                LIMIT 1
                ''',
                (line_type, surah_number),
            ).fetchone()
            resolved[page_number] = tuple(position)
        return {
            'pages': (PAGE_FROM, PAGE_TO),
            'anchors': resolved,
            'padding': padding_by_page,
            'undo_page': 519,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=AZHAR_LAYOUT_DATABASE)
    args = parser.parse_args()
    result = align_tail(args.database)
    print(f'Aligned pages {result["pages"][0]}..{result["pages"][1]}')
    for expected_page, actual in result['anchors'].items():
        print(f'  page {expected_page}: anchor at {actual[0]}:{actual[1]}')
    print(f'  trailing empty slots by block: {result["padding"]}')
    print(f'  undo available from page {result["undo_page"]}')


if __name__ == '__main__':
    main()
