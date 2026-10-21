#!/usr/bin/env python3
"""Upload chosen Layout Studio pages from the local SQLite file to Supabase (one edition).

Dry run by default: shows, line by line, how each page differs from the cloud. ``--apply`` uploads
exactly those pages (the same upsert Layout Studio uses) and then re-checks that the cloud equals the
local file. Pages that already match are skipped.

Made for 2026-10-21: one Layout Studio action rewrote Mesaha pages 347-363 (every line shifted by a
word or more); the reviewed versions were restored locally from git and checked with the word split.

    python3 pipeline/push_layout_pages.py mesaha 346-363             # what would change
    python3 pipeline/push_layout_pages.py mesaha 346-363 --apply     # upload them
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import layout_persistence as lp  # noqa: E402
from core import supabase_editor as sb  # noqa: E402


def _edition(edition_id: str):
    import modules.layout_editions as le
    for value in vars(le).values():
        if getattr(value, 'id', None) == edition_id and hasattr(value, 'layout_db'):
            return value
    raise SystemExit(f'unknown layout edition {edition_id!r}')


def _pages(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(','):
        lo, _, hi = part.partition('-')
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


def _local_lines(edition, conn, page: int) -> list[dict]:
    """The page as Layout Studio would save it (word keys included), validated the same way."""
    lines = lp._page_payload(edition, conn.cursor(), page)['lines']
    if lines:
        lp._validate_page_word_space(edition, page, lines)
    return lines


def _show(page: int, cloud: list[dict], local: list[dict]) -> None:
    c = {int(x.get('line_number') or i): x for i, x in enumerate(cloud, 1)}
    l_ = {int(x['line_number']): x for x in local}
    print(f'\n=== page {page}')
    for n in sorted(set(c) | set(l_)):
        a, b = c.get(n), l_.get(n)
        if a and b and a.get('line_text') == b.get('line_text') and a.get('first_word_id') == b.get('first_word_id'):
            continue
        for tag, r in (('cloud', a), ('local', b)):
            print(f'  {tag} L{n:<2} ' + ('—' if r is None else f"{r.get('first_word_id')}..{r.get('last_word_id')}  {r.get('line_text')}"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edition')
    ap.add_argument('pages', help='e.g. 346-363 or 12,40-42')
    ap.add_argument('--apply', action='store_true', help='upload the differing pages')
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not sb.is_configured():
        print('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured')
        return 2
    edition = _edition(args.edition)
    pages = _pages(args.pages)
    remote = {int(r['page_number']): r.get('lines') or [] for r in sb.fetch_layout_pages(edition=edition.id, force=True)}
    with sqlite3.connect(edition.layout_db) as conn:
        differing = []
        for page in pages:
            local = _local_lines(edition, conn, page)
            if not local:
                print(f'page {page}: not in the local file, skipped')
                continue
            if page in remote and lp._page_matches(conn.cursor(), page, lp._normalize_cloud_word_keys(edition, page, remote[page])):
                continue
            differing.append((page, local))
            _show(page, remote.get(page, []), local)
    print(f'\n{len(differing)} of {len(pages)} pages differ from the cloud: {[p for p, _ in differing]}')
    if not args.apply or not differing:
        if differing:
            print('dry run: nothing uploaded (add --apply)')
        return 0
    sb.upsert_layout_pages(edition=edition.id, pages=[{'page_number': p, 'lines': lines} for p, lines in differing],
                           updated_by=None)
    sb.invalidate_layout_cache(edition.id)
    remote = {int(r['page_number']): r.get('lines') or [] for r in sb.fetch_layout_pages(edition=edition.id, force=True)}
    with sqlite3.connect(edition.layout_db) as conn:
        still = [p for p, _ in differing
                 if not lp._page_matches(conn.cursor(), p, lp._normalize_cloud_word_keys(edition, p, remote.get(p, [])))]
    print('uploaded', [p for p, _ in differing], '· still differing after upload:', still)
    return 1 if still else 0


if __name__ == '__main__':
    raise SystemExit(main())
