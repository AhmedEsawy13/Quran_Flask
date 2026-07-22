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

After the Shemrly clone, Azhar short-page geometry is applied:
  • page 2 (الفاتحة): 6 lines including البسملة
  • page 3 (أول البقرة): 5 lines

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


def seed(force: bool = False) -> None:
    if not os.path.exists(SHAMARLY_LAYOUT_DATABASE):
        raise SystemExit(f'Missing source layout: {SHAMARLY_LAYOUT_DATABASE}')

    if os.path.exists(AZHAR_LAYOUT_DATABASE):
        if not force:
            print(f'Already exists: {AZHAR_LAYOUT_DATABASE} (pass --force to recreate)')
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
                line_type TEXT NOT NULL CHECK(line_type IN ('ayah', 'surah_name', 'basmallah')),
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
        final_lines = dst.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
        print(f'Done: {final_lines} lines after short-page reshape')
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
