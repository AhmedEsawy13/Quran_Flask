#!/usr/bin/env python3
"""Upload the current Bahrain Layout Studio database to Supabase.

Run after ``pipeline/supabase_layout_schema.sql``. The operation is idempotent:
every page is upserted by (edition, page_number), so rerunning refreshes the
cloud baseline without creating duplicates.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402
from core.config import BAHRAIN_LAYOUT_DATABASE  # noqa: E402


def _load_dotenv() -> None:
    path = ROOT / '.env'
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _pages() -> list[dict]:
    columns = (
        'line_number',
        'line_type',
        'is_centered',
        'first_word_id',
        'last_word_id',
        'surah_number',
        'line_text',
    )
    with sqlite3.connect(BAHRAIN_LAYOUT_DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        page_numbers = [
            int(row[0]) for row in conn.execute(
                'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
            )
        ]
        return [
            {
                'page_number': page,
                'lines': [
                    {
                        column: row[column]
                        for column in columns
                    }
                    for row in conn.execute(
                        f'''
                        SELECT {", ".join(columns)}
                        FROM pages
                        WHERE page_number = ?
                        ORDER BY line_number
                        ''',
                        (page,),
                    )
                ],
            }
            for page in page_numbers
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--chunk-size', type=int, default=40,
        help='Pages per PostgREST request (default: 40)',
    )
    parser.add_argument(
        '--verify-only', action='store_true',
        help='Compare Supabase with SQLite without uploading',
    )
    args = parser.parse_args()
    _load_dotenv()
    if not sb.is_configured():
        print('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured')
        return 2

    pages = _pages()
    if args.verify_only:
        remote = sb.fetch_layout_pages(edition='bahrain', force=True)
        local_by_page = {
            int(page['page_number']): page['lines'] for page in pages
        }
        remote_by_page = {
            int(page['page_number']): page.get('lines') or []
            for page in remote
        }
        mismatched = [
            page for page, lines in local_by_page.items()
            if remote_by_page.get(page) != lines
        ]
        extra = sorted(set(remote_by_page) - set(local_by_page))
        if mismatched or extra:
            print(
                'Verification failed: '
                f'{len(mismatched)} mismatched/missing, {len(extra)} extra'
            )
            if mismatched:
                print(f'First mismatched pages: {mismatched[:10]}')
            return 1
        print(f'Verified: all {len(pages)} Bahrain pages match Supabase')
        return 0

    chunk_size = max(1, min(int(args.chunk_size), 100))
    completed = 0
    for offset in range(0, len(pages), chunk_size):
        chunk = pages[offset:offset + chunk_size]
        sb.upsert_layout_pages(
            edition='bahrain',
            pages=chunk,
            updated_by=None,
        )
        completed += len(chunk)
        print(f'Uploaded {completed}/{len(pages)} pages')
    print(f'Bahrain layout cloud baseline ready: {completed} pages')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
