#!/usr/bin/env python3
"""Seed data/mushaf-azhar-layout.db from الشمرلي page geometry.

Copies pages (and creates info + progress tables) from
mushaf_layout_inferred.db so /azhar-layout can reshape line breaks against
the physical مصحف الأزهر while rendering Amiri + الأزهر waqf.

DESTRUCTIVE WARNING
  --force deletes data/mushaf-azhar-layout.db entirely. That wipes:
    • every line-break / merge edit in the Azhar studio
    • reviewed / مطابِق للمطبوع progress flags
    • the undo stack
  Only use --force when you intentionally want a clean Shemrly reseed.
  Prefer page-scoped undo in /azhar-layout for ordinary corrections.

After the Shemrly clone, Azhar geometry is applied:
  • page 2 (الفاتحة): 6 lines including البسملة
  • page 3 (أول البقرة): 5 lines
  • surah starts: سورة + معلومات + بسملة + ١٢ سطر آية (١٥ كليًا);
    Shemrly split headers (name on N / basmala on N+1) are coalesced
  • the working range is extended safely through Azhar page 525; missing
    tail pages are created as empty 15-slot pages without touching prior edits

Usage:
  python3 pipeline/seed_azhar_layout_db.py
  python3 pipeline/seed_azhar_layout_db.py --force   # WIPE + recreate
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
    SHAMARLY_LAYOUT_DATABASE,
)
from modules.layout_editions import AZHAR  # noqa: E402
from modules import layout_engine as engine  # noqa: E402

_FORCE_WIPE_BANNER = (
    'WARNING: --force will DELETE {path} and wipe all Azhar layout edits, '
    'progress, and undo history. Prefer studio undo for corrections.'
)


def _apply_azhar_short_pages(dst: sqlite3.Connection) -> None:
    """Reshape الفاتحة (6 lines incl. basmala) and أول البقرة (5 lines)."""
    universe = engine.all_script_word_ids(QURAN_SCRIPT_DATABASE)
    cur = dst.cursor()
    for rule in AZHAR.closed_pages:
        info = engine.reshape_page_line_count(
            cur,
            rule.page,
            rule.target_lines,
            script_db=QURAN_SCRIPT_DATABASE,
            universe=universe,
        )
        print(
            f'  short page {rule.page}: {info["target_lines"]} lines '
            f'({info["header_lines"]} header + {info["ayah_lines"]} ayah, '
            f'{info["word_count"]} words)'
        )
    dst.commit()


def _apply_azhar_surah_headers(dst: sqlite3.Connection) -> None:
    """Name + info + basmala + 12 ayah on full pages; promote split headers."""
    universe = engine.all_script_word_ids(QURAN_SCRIPT_DATABASE)
    cur = dst.cursor()
    skip = {int(r.page) for r in AZHAR.closed_pages}
    info = engine.normalize_surah_header_pages(
        cur,
        script_db=QURAN_SCRIPT_DATABASE,
        universe=universe,
        default_lines=int(AZHAR.lines_per_page),
        skip_pages=skip,
    )
    print(
        f'  surah headers: promoted={info["promoted_split_headers"]} '
        f'repaired={info.get("repaired_boundary_pages", [])} '
        f'info_pages={info["info_pages"]} spilled={info["spilled_pages"]} '
        f'filled={info.get("filled_pages", 0)} clamped={info.get("clamped_pages", 0)} '
        f'orphan_banners={info.get("promoted_orphan_banners", 0)} '
        f'metadata={info.get("metadata_fixed", 0)}'
    )
    dst.commit()


def _ensure_azhar_page_range(dst: sqlite3.Connection) -> list[int]:
    """Add missing Azhar working pages without changing existing page rows."""
    existing_pages = {
        int(row[0])
        for row in dst.execute('SELECT DISTINCT page_number FROM pages')
    }
    last_surah_row = dst.execute(
        '''
        SELECT surah_number
        FROM pages
        WHERE surah_number IS NOT NULL
        ORDER BY page_number DESC, line_number DESC
        LIMIT 1
        '''
    ).fetchone()
    last_surah = int(last_surah_row[0]) if last_surah_row else 114
    added_pages = []
    for page_number in range(AZHAR.min_page, AZHAR.max_page + 1):
        if page_number in existing_pages:
            continue
        line_count = int(AZHAR.line_count_for(page_number))
        dst.executemany(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, 'ayah', 0, NULL, NULL, ?, '')
            ''',
            [
                (int(page_number), int(line_number), last_surah)
                for line_number in range(1, line_count + 1)
            ],
        )
        added_pages.append(page_number)

    page_count = AZHAR.max_page - AZHAR.min_page + 1
    dst.execute(
        '''
        UPDATE info
        SET number_of_pages = ?, lines_per_page = ?
        ''',
        (int(page_count), int(AZHAR.lines_per_page)),
    )
    dst.commit()
    return added_pages


def seed(force: bool = False) -> None:
    if not os.path.exists(SHAMARLY_LAYOUT_DATABASE):
        raise SystemExit(f'Missing source layout: {SHAMARLY_LAYOUT_DATABASE}')

    if os.path.exists(AZHAR_LAYOUT_DATABASE):
        if not force:
            with sqlite3.connect(AZHAR_LAYOUT_DATABASE) as dst:
                added_pages = _ensure_azhar_page_range(dst)
            if added_pages:
                print(
                    f'Extended {AZHAR_LAYOUT_DATABASE} with pages '
                    f'{added_pages[0]}..{added_pages[-1]} '
                    '(existing edits preserved)'
                )
            else:
                print(
                    f'Already covers pages {AZHAR.min_page}..{AZHAR.max_page}: '
                    f'{AZHAR_LAYOUT_DATABASE}'
                )
            return
        print(_FORCE_WIPE_BANNER.format(path=AZHAR_LAYOUT_DATABASE), file=sys.stderr)
        os.remove(AZHAR_LAYOUT_DATABASE)

    src = sqlite3.connect(SHAMARLY_LAYOUT_DATABASE)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        dst.execute(
            '''
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number INTEGER NOT NULL,
                line_number INTEGER NOT NULL,
                line_type TEXT NOT NULL CHECK(line_type IN ('ayah', 'surah_name', 'surah_info', 'basmallah')),
                is_centered INTEGER NOT NULL,
                first_word_id INTEGER,
                last_word_id INTEGER,
                surah_number INTEGER,
                line_text TEXT NOT NULL DEFAULT ''
            )
            '''
        )
        dst.execute('CREATE INDEX idx_azhar_page_line ON pages (page_number, line_number)')
        dst.execute('CREATE INDEX idx_azhar_surah_number ON pages (surah_number)')
        dst.execute(
            '''
            CREATE TABLE info (
                name TEXT,
                number_of_pages INTEGER,
                lines_per_page INTEGER,
                font_name TEXT
            )
            '''
        )
        dst.execute(
            '''
            CREATE TABLE azhar_layout_progress (
                page_number INTEGER PRIMARY KEY,
                reviewed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            '''
        )
        dst.execute(
            '''
            CREATE TABLE azhar_layout_undo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT,
                page_number INTEGER,
                snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            '''
        )

        rows = src.execute(
            '''
            SELECT page_number, line_number, line_type, is_centered,
                   first_word_id, last_word_id, surah_number, line_text
            FROM pages
            ORDER BY page_number ASC, line_number ASC
            '''
        ).fetchall()
        dst.executemany(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            [
                (
                    int(r['page_number']),
                    int(r['line_number']),
                    r['line_type'],
                    1 if r['is_centered'] else 0,
                    r['first_word_id'],
                    r['last_word_id'],
                    r['surah_number'],
                    r['line_text'] or '',
                )
                for r in rows
            ],
        )

        page_count = src.execute('SELECT COUNT(DISTINCT page_number) FROM pages').fetchone()[0]
        dst.execute(
            'INSERT INTO info (name, number_of_pages, lines_per_page, font_name) VALUES (?, ?, ?, ?)',
            ('مصحف الأزهر', int(page_count), 15, 'Amiri Quran'),
        )
        dst.commit()
        print(f'Seeded {len(rows)} lines / {page_count} pages → {AZHAR_LAYOUT_DATABASE}')
        print('Applying Azhar short-page geometry…')
        _apply_azhar_short_pages(dst)
        print('Applying Azhar surah-header geometry…')
        _apply_azhar_surah_headers(dst)
        added_pages = _ensure_azhar_page_range(dst)
        if added_pages:
            print(
                f'  extended working range with pages '
                f'{added_pages[0]}..{added_pages[-1]}'
            )
        final_lines = dst.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
        print(f'Done: {final_lines} lines after Azhar reshape')
    finally:
        src.close()
        dst.close()

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='DELETE existing DB and reseed (wipes all studio edits/progress/undo)',
    )
    args = parser.parse_args()
    seed(force=args.force)


if __name__ == '__main__':
    main()
