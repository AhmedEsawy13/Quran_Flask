#!/usr/bin/env python3
"""Apply reviewer-confirmed Azhar page endings on pages 505–509 and 514–515.

Every Quran range comes from quran-script.db. Existing physical row IDs are
reused and only the line partitions/page assignments are changed.
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
from pipeline.align_azhar_review_boundaries import (  # noqa: E402
    align_review_boundaries,
)


REVIEWED_ENDINGS = {
    505: 82458,  # إِنَّ ٱلۡأَبۡرَارَ
    506: 82580,  # فَمُلَٰقِيهِ ٦ فَأَمَّا
    507: 82718,  # شُهُودٞ ٧
    508: 82845,  # فَلۡيَنظُرِ ٱلۡإِنسَٰنُ
    509: 82990,  # خَيۡرٞ وَأَبۡقَىٰٓ ١٧
    514: 83617,  # ٧ وَوَجَدَكَ (سورة الضحى)
    515: 83711,  # فَلَهُمۡ أَجۡرٌ
}


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


def _word_stream(cur, page_from: int = 505, page_to: int = 525) -> list[int]:
    stream = []
    for page in range(int(page_from), int(page_to) + 1):
        for row in _load_page(cur, page):
            if (
                row['line_type'] == 'ayah'
                and row.get('first_word_id') is not None
                and row.get('last_word_id') is not None
            ):
                stream.extend(range(
                    int(row['first_word_id']),
                    int(row['last_word_id']) + 1,
                ))
    return stream


def _persist_pages(cur, pages: dict[int, list[dict]]) -> None:
    all_rows = [row for rows in pages.values() for row in rows]
    if len({int(row['id']) for row in all_rows}) != len(all_rows):
        raise ValueError('A physical row ID was reused')
    page_numbers = sorted(pages)
    placeholders = ','.join('?' * len(page_numbers))
    cur.execute(
        f'UPDATE pages SET line_number = -id '
        f'WHERE page_number IN ({placeholders})',
        page_numbers,
    )
    for page_number in page_numbers:
        if len(pages[page_number]) != 15:
            raise ValueError(f'Page {page_number} does not have 15 rows')
        for line_number, row in enumerate(pages[page_number], 1):
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


def align_review_endings(database: str = AZHAR_LAYOUT_DATABASE) -> dict:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        affected = tuple(range(505, 511)) + (514, 515, 516)
        pages = {page: _load_page(cur, page) for page in affected}
        if any(len(rows) != 15 for rows in pages.values()):
            raise ValueError('Expected 15 physical rows on every affected page')
        before_stream = _word_stream(cur)

        engine.push_undo(
            cur,
            'azhar-review-endings-505-515',
            505,
            505,
            525,
            undo_table='azhar_layout_undo',
        )

        early_region = [
            row for page in range(505, 511) for row in pages[page]
        ]
        early_headers = {
            (line_type, surah): _header(early_region, line_type, surah)
            for surah in range(83, 89)
            for line_type in ('surah_name', 'surah_info', 'basmallah')
        }
        early_header_ids = {
            int(row['id']) for row in early_headers.values()
        }
        early_pool = [
            row for row in early_region
            if int(row['id']) not in early_header_ids
        ]

        output = {}
        output[505] = _ayah_rows(early_pool, 82321, 82332, 1, 82)
        output[505] += [
            early_headers[(kind, 83)]
            for kind in ('surah_name', 'surah_info', 'basmallah')
        ]
        output[505] += _ayah_rows(early_pool, 82339, 82458, 11, 83)

        page_specs = {
            506: ((82459, 82543, 9, 83), 84, (82550, 82580, 3, 84)),
            507: ((82581, 82682, 9, 84), 85, (82689, 82718, 3, 85)),
            508: ((82719, 82819, 10, 85), 86, (82826, 82845, 2, 86)),
            509: ((82846, 82903, 5, 86), 87, (82910, 82990, 7, 87)),
            510: ((82991, 83000, 1, 87), 88, (83007, 83124, 11, 88)),
        }
        for page, (before, header_surah, after) in page_specs.items():
            rows = _ayah_rows(early_pool, *before)
            rows += [
                early_headers[(kind, header_surah)]
                for kind in ('surah_name', 'surah_info', 'basmallah')
            ]
            rows += _ayah_rows(early_pool, *after)
            output[page] = rows
        if early_pool:
            raise ValueError(f'{len(early_pool)} early rows were not consumed')

        late_region = [
            row for page in (514, 515, 516) for row in pages[page]
        ]
        late_headers = {
            (line_type, surah): _header(late_region, line_type, surah)
            for surah in (93, 94, 95, 96)
            for line_type in ('surah_name', 'surah_info', 'basmallah')
        }
        late_header_ids = {int(row['id']) for row in late_headers.values()}
        late_pool = [
            row for row in late_region
            if int(row['id']) not in late_header_ids
        ]

        # Page 513 ends at ٱلذَّكَرَ (83497), so page 514 must retain
        # وَٱلۡأُنثَىٰٓ and the ayah number (83498–83499) before ayah 4.
        output[514] = _ayah_rows(late_pool, 83498, 83578, 8, 92)
        output[514] += [
            late_headers[(kind, 93)]
            for kind in ('surah_name', 'surah_info', 'basmallah')
        ]
        output[514] += _ayah_rows(late_pool, 83585, 83617, 4, 93)

        output[515] = _ayah_rows(late_pool, 83618, 83635, 2, 93)
        output[515] += [
            late_headers[(kind, 94)]
            for kind in ('surah_name', 'surah_info', 'basmallah')
        ]
        output[515] += _ayah_rows(late_pool, 83642, 83676, 4, 94)
        output[515] += [
            late_headers[(kind, 95)]
            for kind in ('surah_name', 'surah_info', 'basmallah')
        ]
        output[515] += _ayah_rows(late_pool, 83683, 83711, 3, 95)

        output[516] = _ayah_rows(late_pool, 83712, 83724, 2, 95)
        output[516] += [
            late_headers[(kind, 96)]
            for kind in ('surah_name', 'surah_info', 'basmallah')
        ]
        output[516] += _ayah_rows(late_pool, 83731, 83821, 10, 96)
        if late_pool:
            raise ValueError(f'{len(late_pool)} late rows were not consumed')

        _persist_pages(cur, output)
        if _word_stream(cur) != before_stream:
            raise ValueError('Page reconstruction changed the Quran word stream')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    downstream = align_review_boundaries(database)
    return {'endings': REVIEWED_ENDINGS, 'downstream': downstream}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=AZHAR_LAYOUT_DATABASE)
    args = parser.parse_args()
    result = align_review_endings(args.database)
    for page, word_id in result['endings'].items():
        print(f'page {page}: ends at word {word_id}')
    for expected_page, actual in result['downstream']['tail']['anchors'].items():
        print(f'page {expected_page}: anchor at {actual[0]}:{actual[1]}')


if __name__ == '__main__':
    main()
