"""Write the Kraken/DjVu relayout's rows for Mesaha as *draft* pages in the layout DB.

``relayout_drafts`` (page_number, kind draft|neighbour-edge, source, flags) records which pages
were drafted or had an edge moved to meet a draft; ``layout_import_confidence`` is left alone.

    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_drafts            # dry run, prints the plan
    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_drafts --apply    # writes data/mushaf-mesaha-layout.db

Only the local layout DB is written (the one Layout Studio edits); Supabase holds the
*reviewed* pages and is never touched. Pages the relayout did not cover keep the OCR
import's rows. Pages up to ``REVIEWED_THROUGH`` are the reviewed ones and are skipped.

Page boundaries: the relayout may move a page's first/last word, so two neighbouring
drafts can overlap or leave a gap. Where both are drafts they are made contiguous
(the next page's first word wins: a verse's leading word is what the relayout tends
to leave on the previous row). Where a draft meets a page that was not redrafted the
draft keeps its own boundary and the mismatch is recorded in the page's notes.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from pathlib import Path

from pipeline.cv_waqf import layout_geo, relayout
from pipeline.cv_waqf.config import EDITIONS, ROOT

EDITION = 'المساحة'
REVIEWED_THROUGH = 62            # Layout Studio pages 2-62 are in Supabase
FIRST_PAGE, LAST_PAGE = REVIEWED_THROUGH + 1, 827
MAX_RECONCILE = 4                # words a boundary between two drafts may be moved
DEFAULT_COLLECTED = ROOT / 'artifacts' / 'cv-waqf' / 'mesaha-relayout-drafts' / 'collected.json'
AYAH_TYPES = (None, '', 'ayah', 'verse')


def collect(pages=range(FIRST_PAGE, LAST_PAGE + 1)) -> dict[int, dict]:
    """The relayout's row bounds per page (first/last word id of each printed row)."""
    import cv2

    from pipeline.cv_waqf.pages import ensure_page_image
    from pipeline.cv_waqf.preprocess import preprocess_page

    spec = EDITIONS[EDITION]
    out: dict[int, dict] = {}
    for page in pages:
        prepared = preprocess_page(cv2.imread(str(ensure_page_image(spec, page))), spec, page)
        relayout.LAST_DEBUG.clear()
        words = layout_geo.estimate_layout_words(spec, page, prepared)
        rows: dict[int, list[int]] = collections.defaultdict(list)
        for w in sorted(words, key=lambda w: (w.line_number, w.word_on_line)):
            rows[w.line_number].append(w.word_id)
        out[page] = {
            'source': relayout.LAST_DEBUG.get('source'),
            'rows': {k: [v[0], v[-1], len(v)] for k, v in rows.items()},
        }
    return out


def _move_edge(rows: dict[int, list[int]], which: str, boundary: int) -> tuple[int, int]:
    """Make a page's first (``which='start'``) or last (``'end'``) word position equal
    ``boundary`` (the page's first position / one past its last), trimming or extending
    its edge rows. Returns ``(words moved, rows emptied)``; an emptied row has a > b."""
    ks = sorted(rows)
    moved = emptied = 0
    if which == 'start':
        cur = rows[ks[0]][0]
        if boundary < cur:                       # extend backwards
            rows[ks[0]][0] = boundary
            return cur - boundary, 0
        need = boundary - cur
        moved = need
        for k in ks:
            a, b = rows[k]
            take = min(need, b - a + 1)
            rows[k][0] = a + take
            need -= take
            emptied += rows[k][0] > rows[k][1]
            if need <= 0:
                break
    else:
        cur = rows[ks[-1]][1]
        end = boundary - 1
        if end > cur:                            # extend forwards
            rows[ks[-1]][1] = end
            return end - cur, 0
        need = cur - end
        moved = need
        for k in reversed(ks):
            a, b = rows[k]
            take = min(need, b - a + 1)
            rows[k][1] = b - take
            need -= take
            emptied += rows[k][1] < rows[k][0]
            if need <= 0:
                break
    return moved, emptied


def plan(collected: dict[int, dict], db_path: str, script_db: str,
         fixed: frozenset[int] | set[int] = frozenset()) -> dict:
    """Draft rows per covered page, boundaries reconciled; no database writes.

    ``fixed`` pages (reviewed ones, or pages whose draft cannot be saved) keep their rows
    as they are; their neighbours' edges move to meet them."""
    fixed = set(fixed) | set(range(1, REVIEWED_THROUGH + 1))
    ids, pos = layout_geo._ordered_word_ids(script_db)
    conn = sqlite3.connect(db_path)
    try:
        old_lines = collections.defaultdict(list)
        for page, ln, typ, ctr, a, b, sur, txt in conn.execute(
            'SELECT page_number, line_number, line_type, is_centered, first_word_id, '
            'last_word_id, surah_number, line_text FROM pages WHERE page_number >= ? '
            'ORDER BY page_number, line_number', (REVIEWED_THROUGH - 1,),
        ):
            old_lines[page].append(
                {'line_number': ln, 'line_type': typ, 'is_centered': ctr,
                 'first_word_id': a, 'last_word_id': b, 'surah_number': sur, 'line_text': txt},
            )
    finally:
        conn.close()

    def ayah_old(page):
        return [l for l in old_lines[page]
                if l['line_type'] in AYAH_TYPES and l['first_word_id'] is not None]

    pages: dict[int, dict] = {}
    for page, rec in collected.items():
        page = int(page)
        if not rec.get('source') or not FIRST_PAGE <= page <= LAST_PAGE or page in fixed:
            continue
        old_ayah = {l['line_number']: l for l in ayah_old(page)}
        rows = {}
        for k, (first, last, _n) in rec['rows'].items():
            k = int(k)
            if k in old_ayah and first in pos and last in pos:
                rows[k] = [pos[first], pos[last]]
        if not rows or set(rows) != set(old_ayah):
            continue                       # the rows no longer match the layout's lines
        ks = sorted(rows)
        if any(rows[a][1] + 1 != rows[b][0] for a, b in zip(ks, ks[1:])):
            continue                       # not contiguous: not a usable draft
        pages[page] = {'source': rec['source'], 'rows': rows, 'notes': []}

    def edge(page):
        """(first, last) position of a page's ayah rows: draft if drafted, else the old rows."""
        if page in pages:
            ks = sorted(pages[page]['rows'])
            return pages[page]['rows'][ks[0]][0], pages[page]['rows'][ks[-1]][1]
        rows = ayah_old(page)
        if not rows:
            return None
        return pos.get(rows[0]['first_word_id']), pos.get(rows[-1]['last_word_id'])

    stats = collections.Counter()
    adjusted: dict[int, dict] = {}
    adjusted_notes: dict[int, list] = collections.defaultdict(list)
    # Every page boundary that touches a draft (the left page may be untouched).
    for page in sorted({q for d in pages for q in (d - 1, d)}):
        nxt = page + 1
        if nxt > LAST_PAGE or page < REVIEWED_THROUGH or (page in fixed and nxt in fixed):
            continue
        a, b = edge(page), edge(nxt)
        if not a or not b or a[1] is None or b[0] is None:
            continue
        delta = b[0] - a[1] - 1             # 0 contiguous, <0 overlap, >0 gap
        if delta == 0:
            stats['contiguous'] += 1
            continue
        kind = 'overlap' if delta < 0 else 'gap'
        if page in fixed or nxt in fixed:
            # A reviewed (or unsavable) page never moves: its neighbour meets it.
            if page in fixed:
                other, which, boundary, fixed_page = nxt, 'start', a[1] + 1, page
            else:
                other, which, boundary, fixed_page = page, 'end', b[0], nxt
            if other in pages:
                _, emptied = _move_edge(pages[other]['rows'], which, boundary)
                pages[other]['notes'].append(
                    f'{which} {kind} {abs(delta)} moved to meet fixed page {fixed_page}'
                    + (f' ({emptied} row(s) emptied)' if emptied else ''))
                stats['draft aligned to a fixed page'] += 1
                stats['rows emptied'] += emptied
            else:
                rows = adjusted.get(other) or {
                    l['line_number']: [pos[l['first_word_id']], pos[l['last_word_id']]]
                    for l in ayah_old(other) if l['first_word_id'] in pos and l['last_word_id'] in pos
                }
                if rows:
                    _, emptied = _move_edge(rows, which, boundary)
                    adjusted[other] = rows
                    adjusted_notes[other].append(
                        f'{which} {kind} {abs(delta)} moved to meet fixed page {fixed_page}'
                        + (f' ({emptied} row(s) emptied)' if emptied else ''))
                    stats['rows emptied'] += emptied
            continue
        if page in pages and nxt in pages and abs(delta) <= MAX_RECONCILE:
            boundary = min(b[0], a[1] + 1)  # the next page's first word wins an overlap
            ks, kn = sorted(pages[page]['rows']), sorted(pages[nxt]['rows'])
            last_row, first_row = pages[page]['rows'][ks[-1]], pages[nxt]['rows'][kn[0]]
            if boundary - 1 - last_row[0] >= 3 and first_row[1] - boundary >= 3:
                last_row[1] = boundary - 1
                first_row[0] = boundary
                stats['reconciled'] += 1
                continue
        if nxt in pages and page in pages:
            # Two drafts that disagree by more than a stray word: the next page's
            # first word still wins (trim the earlier page's end / extend the
            # next page's start), and both pages say so in their notes.
            boundary = min(b[0], a[1] + 1)
            rows_n, rows_p = pages[nxt]['rows'], pages[page]['rows']
            if delta < 0:
                _, emptied = _move_edge(rows_p, 'end', boundary)
            else:
                _, emptied = _move_edge(rows_n, 'start', boundary)
            for q, side in ((page, 'end'), (nxt, 'start')):
                pages[q]['notes'].append(
                    f'{side} {kind} {abs(delta)} with page {nxt if q == page else page}, reconciled'
                    + (f' ({emptied} row(s) emptied)' if emptied else ''))
            stats[f'draft boundary reconciled by force ({kind})'] += 1
            stats['rows emptied'] += emptied
            continue
        # A draft meets a page the relayout did not cover: the draft's boundary
        # stands, the untouched page's edge rows follow it (trim an overlap,
        # extend into a gap) so every word still sits on exactly one page.
        if page in pages:
            other, which, boundary = nxt, 'start', a[1] + 1
        else:
            other, which, boundary = page, 'end', b[0]
        rows = adjusted.get(other) or {
            l['line_number']: [pos[l['first_word_id']], pos[l['last_word_id']]]
            for l in ayah_old(other) if l['first_word_id'] in pos and l['last_word_id'] in pos
        }
        if not rows:
            stats['untouched page without usable rows'] += 1
            continue
        moved, emptied = _move_edge(rows, which, boundary)
        adjusted[other] = rows
        adjusted_notes[other].append(
            f'{which} {kind} {abs(delta)} with draft page {nxt if other == page else page}'
            + (f' ({emptied} row(s) emptied)' if emptied else ''),
        )
        stats[f'untouched page adjusted ({kind})'] += 1
        stats['rows emptied'] += emptied
    return {'pages': pages, 'adjusted': adjusted, 'adjusted_notes': dict(adjusted_notes),
            'stats': dict(stats), 'ids': ids}


def reviewed_pages(db_path: str, offline: bool = False) -> set[int]:
    """Pages whose rows must never be rewritten: the reviewed ones (2..REVIEWED_THROUGH),
    anything saved to Supabase's Layout Studio store, pages marked reviewed there or in
    the local progress table. Without the cloud answer the run stops (``offline`` skips it)."""
    import os

    out = set(range(1, REVIEWED_THROUGH + 1))
    conn = sqlite3.connect(db_path)
    try:
        out |= {int(r[0]) for r in conn.execute(
            'SELECT page_number FROM mesaha_layout_progress WHERE reviewed = 1')}
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    if offline:
        return out
    env = ROOT / '.env'
    if env.is_file():
        for raw in env.read_text(encoding='utf-8').splitlines():
            raw = raw.strip()
            if raw and not raw.startswith('#') and '=' in raw:
                k, v = raw.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    from core import supabase_editor as sb

    if not sb.is_configured():
        raise SystemExit('Supabase is not configured: cannot tell which pages are reviewed '
                         '(pass --offline to use only the local progress table)')
    out |= {int(r['page_number']) for r in sb.fetch_layout_page_index(edition='mesaha', force=True)}
    out |= set(sb.list_reviewed_pages('mesaha'))
    return out


def crossing_pages(drafts: dict, script_db: str) -> set[int]:
    """Drafted/adjusted pages with an ayah row that spans two surahs: Layout Studio rejects
    those on save (a surah change needs its banner row), so they cannot be drafts."""
    ids, _pos = layout_geo._ordered_word_ids(script_db)
    conn = sqlite3.connect(script_db)
    try:
        surah = {int(w): int(sr) for w, sr in conn.execute('SELECT word_index, surah FROM words')}
    finally:
        conn.close()
    bad = set()
    groups = [(p, d['rows']) for p, d in drafts['pages'].items()]
    groups += list(drafts.get('adjusted', {}).items())
    for page, rows in groups:
        for a, b in rows.values():
            if a <= b and len({surah.get(ids[i]) for i in range(a, b + 1)}) > 1:
                bad.add(page)
    return bad


def make_plan(collected, spec, offline: bool = False) -> tuple[dict, set[int]]:
    """``plan`` with the reviewed pages fixed, repeated with every page whose draft would
    not save also fixed (its neighbours then meet it) until none is left."""
    fixed = reviewed_pages(spec.layout_db, offline)
    unsavable: set[int] = set()
    for _ in range(12):
        drafts = plan(collected, spec.layout_db, spec.script_db, fixed | unsavable)
        bad = crossing_pages(drafts, spec.script_db) - fixed - unsavable
        if not bad:
            drafts['stats']['kept as imported (draft would not save)'] = len(unsavable)
            return drafts, unsavable
        unsavable |= bad
    raise SystemExit(f'surah-crossing rows remain after 12 passes: {sorted(bad)}')


def apply(drafts: dict, db_path: str, script_db: str) -> int:
    """Replace the drafted pages' ayah rows and tag them in layout_import_confidence."""
    ids = drafts['ids']
    pages = drafts['pages']
    adjusted = drafts.get('adjusted') or {}
    need = sorted({ids[p] for d in list(pages.values()) + [{'rows': r} for r in adjusted.values()]
                   for r in d['rows'].values() if r[0] <= r[1] for p in range(r[0], r[1] + 1)})
    words: dict[int, dict] = {}
    for i in range(0, len(need), 500):
        words.update(layout_geo._word_rows(EDITIONS[EDITION], need[i:i + 500]))
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # The OCR import's confidence table is a record of the import (a test pins
        # its mean); the draft provenance lives in its own table.
        cur.execute(
            'CREATE TABLE IF NOT EXISTS relayout_drafts ('
            'page_number INTEGER PRIMARY KEY, kind TEXT NOT NULL, source TEXT, '
            "flags TEXT NOT NULL DEFAULT '', drafted_at TEXT NOT NULL)",
        )
        cur.execute('DELETE FROM relayout_drafts')
        written = 0
        for page, d in sorted(pages.items()):
            for line, (a, b) in d['rows'].items():
                span = ids[a:b + 1]
                if not span:
                    continue
                text = ' '.join(str((words.get(w) or {}).get('text') or '') for w in span).strip()
                surah = (words.get(span[0]) or {}).get('surah')
                cur.execute(
                    'UPDATE pages SET first_word_id=?, last_word_id=?, line_text=?, '
                    'surah_number=COALESCE(?, surah_number) '
                    'WHERE page_number=? AND line_number=?',
                    (span[0], span[-1], text, surah, page, line),
                )
            cur.execute(
                'INSERT OR REPLACE INTO relayout_drafts (page_number, kind, source, flags, drafted_at) '
                "VALUES (?, 'draft', ?, ?, datetime('now'))",
                (page, d['source'], '; '.join(d['notes'])),
            )
            written += 1
        for page, rows in sorted(adjusted.items()):
            for line, (a, b) in rows.items():
                span = ids[a:b + 1] if a <= b else []
                text = ' '.join(str((words.get(w) or {}).get('text') or '') for w in span).strip()
                surah = (words.get(span[0]) or {}).get('surah') if span else None
                cur.execute(
                    'UPDATE pages SET first_word_id=?, last_word_id=?, line_text=?, '
                    'surah_number=COALESCE(?, surah_number) WHERE page_number=? AND line_number=?',
                    (span[0] if span else None, span[-1] if span else None, text, surah, page, line),
                )
            cur.execute(
                'INSERT OR REPLACE INTO relayout_drafts (page_number, kind, source, flags, drafted_at) '
                "VALUES (?, 'neighbour-edge', NULL, ?, datetime('now'))",
                (page, '; '.join((drafts.get('adjusted_notes') or {}).get(page, []))),
            )
            written += 1
        conn.commit()
        return written
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--collected', default=str(DEFAULT_COLLECTED),
                        help='relayout rows per page (JSON); regenerated when missing or --recollect')
    parser.add_argument('--recollect', action='store_true')
    parser.add_argument('--apply', action='store_true', help='write the drafts (default: dry run)')
    parser.add_argument('--offline', action='store_true',
                        help='do not ask Supabase which pages are reviewed (local progress only)')
    args = parser.parse_args(argv)
    spec = EDITIONS[EDITION]
    path = Path(args.collected)
    if path.is_file() and not args.recollect:
        collected = {int(k): v for k, v in json.loads(path.read_text(encoding='utf-8')).items()}
    else:
        collected = collect()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(collected), encoding='utf-8')
    drafts, unsavable = make_plan(collected, spec, args.offline)
    by_source = collections.Counter(d['source'] for d in drafts['pages'].values())
    flagged = sum(1 for d in drafts['pages'].values() if d['notes'])
    print({'drafts': len(drafts['pages']), 'by_source': dict(by_source),
           'boundary_notes': flagged, 'untouched pages adjusted': len(drafts['adjusted']), 'kept as imported': sorted(unsavable),
           **drafts['stats']})
    if args.apply:
        print('written', apply(drafts, spec.layout_db, spec.script_db), 'pages to', spec.layout_db)


if __name__ == '__main__':
    main()
