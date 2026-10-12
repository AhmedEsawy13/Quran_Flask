#!/usr/bin/env python3
"""Compare the Bahrain Layout Studio pages in git with Supabase (read-only on the cloud).

The cloud keeps a full snapshot of every page edited in Layout Studio, and a
Supabase-connected server copies those snapshots over the local SQLite file
(core/layout_persistence.working_db_path). On 2026-10-12 the two sides had
drifted both ways:

* git has the 2026-09-30 word-map fix (dacb375: surahs 15/27/36 sat one word
  early) on pages the cloud still holds in their old form — git wins there;
* the cloud has Layout Studio edits that never reached git — the cloud wins;
* a few cloud edits were saved with the drifted ids (they fail validation and
  hydration skips them): keep the cloud's line breaks, renumbered over git's
  word ids («rebreak»; pages 443 and 445, checked against the scan).

Pages in FIX_PAGES (plus --keep-git) keep git's version; every other differing
page is cloud-newer. ``--pull`` copies the cloud-newer pages into the local
file; afterwards ``python pipeline/seed_bahrain_layout_supabase.py`` uploads
the merged file so the cloud equals git (this script never writes the cloud).

    python pipeline/reconcile_bahrain_layout.py           # show the differences
    python pipeline/reconcile_bahrain_layout.py --pull    # merge cloud edits into git's file
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import layout_persistence as lp  # noqa: E402
from core import supabase_editor as sb  # noqa: E402

# Pages dacb375 rewrote (its commit message: 262-267, 378-385, 441-445).
FIX_PAGES = frozenset([*range(262, 268), *range(378, 386), *range(441, 446)])


def _rows(cur, page: int) -> list[tuple]:
    return cur.execute(
        f'SELECT {", ".join(lp._LINE_COLUMNS)} FROM pages WHERE page_number = ? ORDER BY line_number',
        (page,),
    ).fetchall()


def _as_rows(lines: list[dict]) -> list[tuple]:
    """Cloud lines in the shape of ``_rows`` (what hydration would write)."""
    tmp = sqlite3.connect(':memory:')
    tmp.execute('CREATE TABLE pages (page_number, line_number, line_type, is_centered, '
                'first_word_id, last_word_id, surah_number, line_text)')
    lp._replace_page(tmp.cursor(), 0, lines)
    return _rows(tmp.cursor(), 0)


def _words(text: str) -> int:
    """Layout word ids on a line: one per token, ۝ verse numbers included (true for
    8816 of 8819 Bahrain lines; the 3 others hold the tokens dacb375 splits in two)."""
    return len((text or '').split())


def rebreak(git_rows: list[tuple], cloud_lines: list[dict]) -> list[dict] | None:
    """The cloud's line breaks over git's word ids, or None when they don't fit."""
    if [(r[0], r[1]) for r in git_rows] != [(int(c.get('line_number') or i), c['line_type'])
                                           for i, c in enumerate(cloud_lines, 1)]:
        return None
    ayah = [r for r in git_rows if r[1] == 'ayah']
    if not ayah or any(_words(r[6]) != r[4] - r[3] + 1 for r in ayah):
        return None
    nxt, out = ayah[0][3], []
    for r, c in zip(git_rows, cloud_lines):
        line = dict(zip(lp._LINE_COLUMNS, r))
        if r[1] == 'ayah':
            n = _words(c.get('line_text'))
            line.update(first_word_id=nxt, last_word_id=nxt + n - 1, line_text=c.get('line_text') or '')
            nxt += n
        out.append(line)
    return out if nxt == ayah[-1][4] + 1 else None


def plan(edition, db_path: str, keep_git: set[int]) -> tuple[list[dict], list[str]]:
    """[{page, winner, updated_at, git, cloud, cloud_lines}] for every page whose sides differ."""
    cloud = sb.fetch_layout_pages(edition=edition.id, force=True)
    saved = {int(r['page_number']): r.get('updated_at')
             for r in sb.fetch_layout_page_index(edition=edition.id, force=True)}
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    out, skipped = [], []
    for row in sorted(cloud, key=lambda r: int(r['page_number'])):
        page = int(row['page_number'])
        try:
            lines = lp._normalize_cloud_word_keys(edition, page, row.get('lines') or [])
        except sb.SupabaseEditorError as exc:
            raw = row.get('lines') or []
            git = _rows(cur, page)
            if [r[6] for r in git] == [c.get('line_text') or '' for c in raw]:
                continue                       # only the stale ids differ: git is right
            fixed = rebreak(git, raw)
            if fixed is None:
                skipped.append(f'{page}: {exc}')
                continue
            out.append({'page': page, 'winner': 'rebreak', 'updated_at': saved.get(page), 'git': git,
                        'cloud': _as_rows(fixed), 'cloud_lines': fixed})
            continue
        if not lines or lp._page_matches(cur, page, lines):
            continue
        out.append({'page': page, 'winner': 'git' if page in FIX_PAGES | keep_git else 'cloud',
                    'updated_at': saved.get(page), 'git': _rows(cur, page), 'cloud': _as_rows(lines),
                    'cloud_lines': lines})
    conn.close()
    return out, skipped


def show(diffs: list[dict]) -> None:
    for d in diffs:
        print(f"\n=== page {d['page']}  keep {d['winner']}  (cloud saved {str(d['updated_at'])[:16]})")
        git = {r[0]: r for r in d['git']}
        cloud = {r[0]: r for r in d['cloud']}
        for n in sorted(set(git) | set(cloud)):
            if git.get(n) == cloud.get(n):
                continue
            for tag, r in (('git  ', git.get(n)), ('cloud', cloud.get(n))):
                print(f'  {tag} L{n:<2} ' + ('—' if r is None else f'{r[1]:<10} {r[3]}..{r[4]}  {r[6]}'))


def pull(db_path: str, diffs: list[dict]) -> list[int]:
    """Write the cloud-newer pages into the local file (backup first)."""
    backup = Path(tempfile.gettempdir()) / 'mushaf-bahrain-layout.before-reconcile.db'
    shutil.copy2(db_path, backup)
    print(f'local backup: {backup}')
    pages = [d for d in diffs if d['winner'] in ('cloud', 'rebreak')]
    with sqlite3.connect(db_path) as conn:
        for d in pages:
            lp._replace_page(conn.cursor(), d['page'], d['cloud_lines'])
    return [d['page'] for d in pages]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pull', action='store_true', help='copy cloud-newer pages into the local file')
    p.add_argument('--keep-git', default='', help='more pages where git wins, e.g. 548,549')
    args = p.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not sb.is_configured():
        print('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured')
        return 2
    from modules.layout_editions import BAHRAIN
    keep_git = {int(x) for x in args.keep_git.split(',') if x.strip()}
    diffs, skipped = plan(BAHRAIN, BAHRAIN.layout_db, keep_git)
    show(diffs)
    for s in skipped:
        print('skipped (invalid cloud page):', s)
    print(f"\n{len(diffs)} pages differ — keep git: {[d['page'] for d in diffs if d['winner'] == 'git']}, "
          f"keep cloud: {[d['page'] for d in diffs if d['winner'] == 'cloud']}, "
          f"cloud breaks on git ids: {[d['page'] for d in diffs if d['winner'] == 'rebreak']}")
    if args.pull and diffs:
        print('pulled into the local file:', pull(BAHRAIN.layout_db, diffs))
        print('next: python pipeline/seed_bahrain_layout_supabase.py  (uploads it; then --verify-only)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
