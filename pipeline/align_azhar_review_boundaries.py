#!/usr/bin/env python3
"""Apply reviewer-confirmed Azhar page boundaries around pages 511 and 517.

Confirmed boundaries:
  * page 511 starts with سورة الفجر and ends at قَدَّمْتُ (word 83267)
  * page 517 starts with سورة القدر and ends at دِينُ (word 83920)

The repair reuses the existing page-row IDs and Quran word IDs. Oversized
ayah ranges created by the old two-page cascade are split evenly into the
available physical rows; no Quran text is generated.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.config import (  # noqa: E402
    AZHAR_LAYOUT_DATABASE,
    QURAN_SCRIPT_DATABASE,
)
from modules import layout_engine as engine  # noqa: E402
from pipeline.align_azhar_tail_anchors import align_tail  # noqa: E402


def _load_page(cur, page_number: int) -> list[dict]:
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number
        ''',
        (int(page_number),),
    )
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _header(rows: list[dict], line_type: str, surah_number: int) -> dict:
    matches = [
        row for row in rows
        if row['line_type'] == line_type
        and int(row.get('surah_number') or 0) == int(surah_number)
    ]
    if len(matches) != 1:
        raise ValueError(
            f'Expected one {line_type} row for surah {surah_number}, '
            f'found {len(matches)}'
        )
    return matches[0]


def _ayah_rows(
    row_pool: list[dict],
    start_word: int,
    end_word: int,
    line_count: int,
    surah_number: int,
) -> list[dict]:
    if len(row_pool) < line_count:
        raise ValueError('Not enough physical rows for ayah split')
    word_ids = list(range(int(start_word), int(end_word) + 1))
    chunks = engine.split_words_evenly(word_ids, int(line_count))
    text_map = engine.word_texts(QURAN_SCRIPT_DATABASE, word_ids)
    output = []
    for row, chunk in zip(row_pool[:line_count], chunks):
        row['line_type'] = 'ayah'
        row['is_centered'] = 0
        row['surah_number'] = int(surah_number)
        engine.assign_words_to_line(row, chunk, text_map)
        output.append(row)
    del row_pool[:line_count]
    return output


def _persist_pages(cur, pages: dict[int, list[dict]]) -> None:
    expected_ids = {
        int(row['id'])
        for rows in pages.values()
        for row in rows
    }
    if len(expected_ids) != sum(len(rows) for rows in pages.values()):
        raise ValueError('A row ID was reused during page reconstruction')
    page_numbers = sorted(pages)
    placeholders = ','.join('?' * len(page_numbers))
    cur.execute(
        f'UPDATE pages SET line_number = -id '
        f'WHERE page_number IN ({placeholders})',
        page_numbers,
    )
    for page_number in page_numbers:
        rows = pages[page_number]
        if len(rows) != 15:
            raise ValueError(
                f'Page {page_number} reconstructed with {len(rows)} rows'
            )
        for line_number, row in enumerate(rows, 1):
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


def align_review_boundaries(database: str = AZHAR_LAYOUT_DATABASE) -> dict:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        pages = {
            page: _load_page(cur, page)
            for page in (511, 512, 517, 518)
        }
        if any(len(rows) != 15 for rows in pages.values()):
            raise ValueError('Expected exactly 15 rows on each affected page')
        before_stream = [
            word_id
            for page in range(511, 526)
            for row in _load_page(cur, page)
            if row['line_type'] == 'ayah'
            and row.get('first_word_id') is not None
            and row.get('last_word_id') is not None
            for word_id in range(
                int(row['first_word_id']),
                int(row['last_word_id']) + 1,
            )
        ]

        engine.push_undo(
            cur,
            'azhar-review-boundaries-511-517',
            511,
            511,
            525,
            undo_table='azhar_layout_undo',
        )

        # Page 511: three header rows plus 12 ayah rows ending at قَدَّمْتُ.
        rows_511 = pages[511]
        headers_89 = [
            _header(rows_511, line_type, 89)
            for line_type in ('surah_name', 'surah_info', 'basmallah')
        ]
        pool_511 = [row for row in rows_511 if row not in headers_89]
        output_511 = headers_89 + _ayah_rows(
            pool_511, 83131, 83267, 12, 89,
        )

        # The remaining words of سورة الفجر occupy the three existing slots
        # before سورة البلد on page 512.
        rows_512 = pages[512]
        prefix_512 = rows_512[:3]
        headers_90 = rows_512[3:6]
        pool_90 = rows_512[6:]
        output_512 = (
            _ayah_rows(prefix_512, 83268, 83297, 3, 89)
            + headers_90
            + _ayah_rows(pool_90, 83304, 83405, 9, 90)
        )

        # Pages 517–518: use their existing row pool to give both pages
        # complete, continuous Quran word streams. Page 516 is intentionally
        # outside this repair because its reviewer-confirmed boundary is
        # maintained by align_azhar_review_endings.py.
        region = pages[517] + pages[518]
        headers = {
            (line_type, surah): _header(region, line_type, surah)
            for surah in (97, 98, 99)
            for line_type in ('surah_name', 'surah_info', 'basmallah')
        }
        reserved_ids = {
            int(row['id'])
            for row in headers.values()
        }
        pool = [
            row for row in region
            if int(row['id']) not in reserved_ids
        ]

        output_517 = [
            headers[('surah_name', 97)],
            headers[('surah_info', 97)],
            headers[('basmallah', 97)],
        ]
        output_517 += _ayah_rows(pool, 83829, 83863, 4, 97)
        output_517 += [
            headers[('surah_name', 98)],
            headers[('surah_info', 98)],
            headers[('basmallah', 98)],
        ]
        output_517 += _ayah_rows(pool, 83870, 83920, 5, 98)

        output_518 = _ayah_rows(pool, 83921, 83971, 6, 98)
        output_518 += [
            headers[('surah_name', 99)],
            headers[('surah_info', 99)],
            headers[('basmallah', 99)],
        ]
        output_518 += _ayah_rows(pool, 83978, 84021, 6, 99)
        if pool:
            raise ValueError(f'{len(pool)} physical rows were not consumed')

        _persist_pages(cur, {
            511: output_511,
            512: output_512,
            517: output_517,
            518: output_518,
        })
        after_stream = [
            word_id
            for page in range(511, 526)
            for row in _load_page(cur, page)
            if row['line_type'] == 'ayah'
            and row.get('first_word_id') is not None
            and row.get('last_word_id') is not None
            for word_id in range(
                int(row['first_word_id']),
                int(row['last_word_id']) + 1,
            )
        ]
        if after_stream != before_stream:
            raise ValueError(
                'Boundary reconstruction changed the Quran word stream'
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    tail = align_tail(database)
    return {
        'page_511': (89, 83267),
        'page_517': (97, 83920),
        'tail': tail,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=AZHAR_LAYOUT_DATABASE)
    args = parser.parse_args()
    result = align_review_boundaries(args.database)
    print(
        'page 511: سورة الفجر → word '
        f'{result["page_511"][1]} (قَدَّمْتُ)'
    )
    print(
        'page 517: سورة القدر → word '
        f'{result["page_517"][1]} (دِينُ)'
    )
    for expected_page, actual in result['tail']['anchors'].items():
        print(f'page {expected_page}: anchor at {actual[0]}:{actual[1]}')


if __name__ == '__main__':
    main()
