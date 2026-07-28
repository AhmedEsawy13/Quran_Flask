#!/usr/bin/env python3
"""Create an isolated Bahrain Layout Studio project from Madinah 1421/QPC V2.

The source ``data/digital-khatt-15-lines.db`` remains untouched. The generated
project uses the canonical Layout Studio schema (stable row IDs, line text,
undo/progress tables) and embeds the QPC word map required by the shared layout
engine.

Usage:
  python3 pipeline/seed_bahrain_layout_db.py
  python3 pipeline/seed_bahrain_layout_db.py --force  # destructive rebuild
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import (  # noqa: E402
    BAHRAIN_LAYOUT_DATABASE,
    QPC_V2_LAYOUT_DATABASE,
)
from modules.layouts import _get_dk_layout_word_map  # noqa: E402


def seed(*, force: bool = False) -> None:
    if not os.path.exists(QPC_V2_LAYOUT_DATABASE):
        raise SystemExit(f'Missing QPC V2 source: {QPC_V2_LAYOUT_DATABASE}')
    if os.path.exists(BAHRAIN_LAYOUT_DATABASE):
        if not force:
            print(
                f'Already exists: {BAHRAIN_LAYOUT_DATABASE} '
                '(pass --force to rebuild)'
            )
            return
        print(
            'WARNING: --force deletes all Bahrain line edits, progress, '
            f'and undo history in {BAHRAIN_LAYOUT_DATABASE}',
            file=sys.stderr,
        )
        os.remove(BAHRAIN_LAYOUT_DATABASE)

    source = sqlite3.connect(QPC_V2_LAYOUT_DATABASE)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(BAHRAIN_LAYOUT_DATABASE)
    try:
        target.executescript(
            '''
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number INTEGER NOT NULL,
                line_number INTEGER NOT NULL,
                line_type TEXT NOT NULL
                    CHECK(line_type IN (
                        'ayah', 'surah_name', 'surah_info', 'basmallah'
                    )),
                is_centered INTEGER NOT NULL,
                first_word_id INTEGER,
                last_word_id INTEGER,
                surah_number INTEGER,
                line_text TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX idx_bahrain_page_line
                ON pages (page_number, line_number);
            CREATE INDEX idx_bahrain_surah_number
                ON pages (surah_number);

            CREATE TABLE info (
                name TEXT,
                number_of_pages INTEGER,
                lines_per_page INTEGER,
                font_name TEXT
            );

            CREATE TABLE bahrain_layout_progress (
                page_number INTEGER PRIMARY KEY,
                reviewed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            );

            CREATE TABLE bahrain_layout_undo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT,
                page_number INTEGER,
                snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE words (
                word_index INTEGER PRIMARY KEY,
                word_key TEXT NOT NULL UNIQUE,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                text TEXT NOT NULL,
                text_original TEXT
            );
            CREATE INDEX idx_bahrain_words_surah_ayah
                ON words (surah, ayah, word_index);
            '''
        )

        word_map = _get_dk_layout_word_map()['id2tok']
        positions: dict[tuple[int, int], int] = {}
        word_rows = []
        for word_id in sorted(word_map):
            token = word_map[word_id]
            surah = int(token['surah'])
            ayah = int(token['ayah'])
            key = (surah, ayah)
            positions[key] = positions.get(key, 0) + 1
            word_rows.append((
                int(word_id),
                f'{surah}:{ayah}:{positions[key]}',
                surah,
                ayah,
                token.get('text') or '',
                token.get('text') or '',
            ))
        target.executemany(
            '''
            INSERT INTO words (
                word_index, word_key, surah, ayah, text, text_original
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            word_rows,
        )

        page_rows = source.execute(
            '''
            SELECT page_number, line_number, line_type, is_centered,
                   first_word_id, last_word_id, surah_number
            FROM pages
            ORDER BY page_number, line_number
            '''
        ).fetchall()
        copied = []
        for row in page_rows:
            first = (
                int(row['first_word_id'])
                if row['first_word_id'] not in (None, '') else None
            )
            last = (
                int(row['last_word_id'])
                if row['last_word_id'] not in (None, '') else None
            )
            text = ''
            if first is not None and last is not None:
                text = ' '.join(
                    (word_map.get(word_id) or {}).get('text') or ''
                    for word_id in range(first, last + 1)
                ).strip()
            copied.append((
                int(row['page_number']),
                int(row['line_number']),
                row['line_type'],
                1 if row['is_centered'] else 0,
                first,
                last,
                row['surah_number'],
                text,
            ))
        target.executemany(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            copied,
        )
        page_count = source.execute(
            'SELECT COUNT(DISTINCT page_number) FROM pages'
        ).fetchone()[0]
        target.execute(
            '''
            INSERT INTO info (
                name, number_of_pages, lines_per_page, font_name
            ) VALUES (?, ?, ?, ?)
            ''',
            (
                'مصحف البحرين · تخطيط المدينة ١٤٢١',
                int(page_count),
                15,
                'Digital Khatt',
            ),
        )
        target.commit()
        integrity = target.execute('PRAGMA integrity_check').fetchone()[0]
        print(
            f'Seeded Bahrain: {len(copied)} lines / {page_count} pages / '
            f'{len(word_rows)} words; integrity={integrity}'
        )
    except Exception:
        target.close()
        source.close()
        if os.path.exists(BAHRAIN_LAYOUT_DATABASE):
            os.remove(BAHRAIN_LAYOUT_DATABASE)
        raise
    finally:
        try:
            source.close()
        except Exception:
            pass
        try:
            target.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--force',
        action='store_true',
        help='delete and rebuild the Bahrain project database',
    )
    args = parser.parse_args()
    seed(force=args.force)


if __name__ == '__main__':
    main()
