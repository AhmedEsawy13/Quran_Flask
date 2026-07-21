#!/usr/bin/env python3
"""Export قطر/الكويت marks from local mushaf_waqf.db into Supabase editor_marks.

Default status=draft (public unchanged until admin publish).
Pass --as-published to seed public marks directly.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import CLOUD_EDITOR_EDITIONS, MUSHAF_WAQF_DATABASE  # noqa: E402
from core import supabase_editor as sb  # noqa: E402
from modules.layouts import (  # noqa: E402
    _find_mushaf_row_match_index,
    _get_dk_layout_word_map,
)


def _ayah_words(surah: int, ayah: int) -> list[dict]:
    wmap = _get_dk_layout_word_map()
    first_id = wmap['first_id'].get((surah, ayah))
    last_id = wmap['last_id'].get((surah, ayah))
    if first_id is None or last_id is None:
        return []
    id2tok = wmap['id2tok']
    words = []
    for word_id in range(first_id, last_id + 1):
        tok = id2tok.get(word_id)
        if tok:
            words.append({'word_id': word_id, 'text': tok['text']})
    return words


def migrate_edition(edition: str, *, status: str, dry_run: bool) -> int:
    quoted = f'"{edition}"'
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f'SELECT "السورة" AS surah, "الآية" AS ayah, "الكلمة" AS word, '
        f'token_index, word_index, {quoted} AS symbol '
        f'FROM waqf WHERE {quoted} IS NOT NULL AND {quoted} != "" '
        f'ORDER BY surah, ayah, rowid'
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    count = 0
    by_ayah: dict[tuple[int, int], list] = {}
    for row in rows:
        by_ayah.setdefault((int(row['surah']), int(row['ayah'])), []).append(row)

    for (surah, ayah), ayah_rows in by_ayah.items():
        words = _ayah_words(surah, ayah)
        if not words:
            continue
        search_start = 0
        for row in ayah_rows:
            symbol = (row.get('symbol') or '').strip()
            if not symbol:
                continue
            matched = _find_mushaf_row_match_index(words, {
                'clean_token': row.get('word') or '',
                'word_index': row.get('word_index'),
                'token_index': None,
            }, search_start)
            if matched is None:
                # Fallback: SQLite token_index is often 1-based.
                ti = row.get('token_index')
                try:
                    ti = int(ti) - 1 if ti is not None else None
                except (TypeError, ValueError):
                    ti = None
                if ti is None or not (0 <= ti < len(words)):
                    continue
                matched = ti
            search_start = matched + 1
            word_text = words[matched]['text']
            if dry_run:
                count += 1
                continue
            sb.upsert_mark(
                edition=edition,
                surah=surah,
                ayah=ayah,
                token_index=matched,
                status=status,
                symbol=symbol,
                word_text=word_text,
                updated_by=None,
            )
            count += 1
    return count


def main() -> int:
    p = argparse.ArgumentParser(description='Migrate Qatar/Kuwait waqf marks to Supabase')
    p.add_argument('--as-published', action='store_true',
                   help='Write status=published instead of draft')
    p.add_argument('--edition', action='append', dest='editions',
                   help='Limit to one edition (repeatable). Default: all cloud editions')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    if not sb.is_configured() and not args.dry_run:
        print('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first.', file=sys.stderr)
        return 1
    if not Path(MUSHAF_WAQF_DATABASE).exists():
        print(f'Missing {MUSHAF_WAQF_DATABASE}', file=sys.stderr)
        return 1

    editions = args.editions or sorted(CLOUD_EDITOR_EDITIONS)
    status = 'published' if args.as_published else 'draft'
    total = 0
    for edition in editions:
        if edition not in CLOUD_EDITOR_EDITIONS:
            print(f'Skip unknown edition {edition!r}', file=sys.stderr)
            continue
        n = migrate_edition(edition, status=status, dry_run=args.dry_run)
        print(f'{edition}: {n} marks → {status}' + (' (dry-run)' if args.dry_run else ''))
        total += n
    print(f'Total: {total}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
