"""Which unreviewed Mesaha draft pages need a close look in Layout Studio, and which look right.

1. Page start: a draft whose first word is not the word after the reviewed previous page's last
   word is fixed (``--apply``): on 37 reviewed pages whose Kraken draft started wrong, 25 became
   exactly right with this alone (only their first line was wrong).
2. Ink check: the word split (mesaha_split.py) runs on each draft page in artifacts/mesaha-triage
   and its flags mark the page. On 90 reviewed pages it flagged 40 of the 45 wrong drafts and left
   40 of the 45 right ones clean; the 5 it missed were a wrong first word (step 1) or one word off
   at an inner line break.
3. Line breaks: where the ink and Kraken agree a word sits on the neighbouring line ("move «في»
   to line 9") the break is moved (``--apply``); all 23 such fixes on those 90 pages were right.
   Fixed pages are checked again. With steps 1 and 3, 68 of the 90 drafts were exactly right
   (45 before); 4 wrong ones looked clean.

Writes artifacts/mesaha-triage/triage.json and the ``layout_triage`` table of the layout DB, which
Layout Studio shows on the page. Pages with a surah header are listed but not ink-checked (the
split handles plain pages only).

    python3 pipeline/paw_split/mesaha_layout_triage.py                 # every unreviewed page
    python3 pipeline/paw_split/mesaha_layout_triage.py 475-520
    python3 pipeline/paw_split/mesaha_layout_triage.py --apply         # also fix draft page starts
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT  # noqa: E402

LAYOUT_DB = ROOT / 'data' / 'mushaf-mesaha-layout.db'
WORK = 'mesaha-triage'
SPLIT = str(Path(__file__).with_name('mesaha_split.py'))
IGNORED = {'line_break_hints', 'kraken_flags'}       # weak signals, not flags


def cloud_state() -> tuple[set[int], set[int]]:
    """(reviewed pages, pages saved in the cloud). Layout Studio shows a cloud page instead of the
    local draft, so those are neither fixed nor badged here."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from core import supabase_editor as sb
    if not sb.is_configured():
        raise SystemExit('the reviewed-page list is in the cloud: SUPABASE_* not configured')
    reviewed = {int(p) for p in sb.list_reviewed_pages('layout:mesaha')}
    saved = {int(r['page_number']) for r in sb.fetch_layout_pages(edition='mesaha', force=True)}
    return reviewed, saved


def _rows(db, page):
    return db.execute("SELECT id, line_number, first_word_id, last_word_id FROM pages "
                      "WHERE page_number = ? AND line_type = 'ayah' ORDER BY line_number", (page,)).fetchall()


def start_fixes(db, pages: list[int], reviewed: set[int]) -> dict[int, tuple[int, int]]:
    """{page: (draft first word, expected first word)} where the previous page is reviewed."""
    from pipeline.cv_waqf.layout_geo import _ordered_word_ids
    from pipeline.cv_waqf.config import EDITIONS
    ids, pos = _ordered_word_ids(EDITIONS['المساحة'].script_db)
    out = {}
    for page in pages:
        prev, rows = _rows(db, page - 1), _rows(db, page)
        if page - 1 not in reviewed or not prev or not rows:
            continue
        expected = ids[pos[prev[-1][3]] + 1]
        if rows[0][2] != expected:
            out[page] = (rows[0][2], expected)
    return out


def rewrite_text(db, page: int) -> None:
    """Each line's stored text from its words (Layout Studio and the split read line_text)."""
    from pipeline.cv_waqf import layout_geo
    from pipeline.cv_waqf.config import EDITIONS
    spec = EDITIONS['المساحة']
    for rid, _ln, first, last in _rows(db, page):
        span = layout_geo._ids_between(spec.script_db, first, last)
        words = layout_geo._word_rows(spec, span)
        text = ' '.join(str((words.get(w) or {}).get('text') or '') for w in span).strip()
        db.execute('UPDATE pages SET line_text = ? WHERE id = ?', (text, rid))


def apply_start(db, page: int, expected: int) -> None:
    """The first line starts at ``expected``; it must stay a non-empty line."""
    from pipeline.cv_waqf.layout_geo import _ordered_word_ids
    from pipeline.cv_waqf.config import EDITIONS
    _ids, pos = _ordered_word_ids(EDITIONS['المساحة'].script_db)
    rid, _ln, _first, last = _rows(db, page)[0]
    if pos[expected] > pos[last]:
        raise ValueError(f'page {page}: the first line would be empty')
    db.execute('UPDATE pages SET first_word_id = ? WHERE id = ?', (expected, rid))
    rewrite_text(db, page)


def apply_line_breaks(db, page: int, fixes: list[dict]) -> int:
    """Move each line-break fix's word across its boundary (start of the lower line ±1 word)."""
    from pipeline.cv_waqf.layout_geo import _ordered_word_ids
    from pipeline.cv_waqf.config import EDITIONS
    ids, pos = _ordered_word_ids(EDITIONS['المساحة'].script_db)
    rows = _rows(db, page)
    by_line = {ln: (rid, first, last) for rid, ln, first, last in rows}
    done = 0
    for f in fixes:
        upper, lower = f['lines']
        if upper not in by_line or lower not in by_line:
            continue
        down = f'to line {lower}' in f['fix']
        rid_u, first_u, last_u = by_line[upper]
        rid_l, first_l, last_l = by_line[lower]
        start = ids[pos[first_l] - 1] if down else ids[pos[first_l] + 1]
        end_u = ids[pos[start] - 1]
        if pos[end_u] < pos[first_u] or pos[start] > pos[last_l]:
            continue                                   # a line would be emptied: leave it to the reviewer
        db.execute('UPDATE pages SET last_word_id = ? WHERE id = ?', (end_u, rid_u))
        db.execute('UPDATE pages SET first_word_id = ? WHERE id = ?', (start, rid_l))
        by_line[upper], by_line[lower] = (rid_u, first_u, end_u), (rid_l, start, last_l)
        done += 1
    if done:
        rewrite_text(db, page)
    return done


def save_triage(db, report: dict) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS layout_triage (page_number INTEGER PRIMARY KEY, '
               'status TEXT NOT NULL, detail TEXT NOT NULL, checked_at TEXT NOT NULL)')
    with db:
        db.executemany("INSERT OR REPLACE INTO layout_triage VALUES (?, ?, ?, datetime('now'))",
                       [(p, e['status'], json.dumps(e, ensure_ascii=False)) for p, e in report.items()])


def split(page: int) -> tuple[int, dict | str]:
    env = dict(os.environ, PAW_WORK=WORK)
    done = subprocess.run([sys.executable, SPLIT, str(page)], capture_output=True, text=True, env=env)
    if done.returncode:
        return page, (done.stderr.strip().splitlines() or ['failed'])[-1]
    d = json.loads((ROOT / 'artifacts' / WORK / f'paw-words-{page:03d}.json').read_text(encoding='utf-8'))
    return page, {k: v for k, v in d.get('checks', {}).items() if v and k not in IGNORED}


def _pages(spec: str | None, reviewed: set[int]) -> list[int]:
    if not spec:
        return [p for p in range(3, 828) if p not in reviewed]
    out = []
    for part in spec.split(','):
        lo, _, hi = part.partition('-')
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pages', nargs='?', help='e.g. 475-520 (default: every unreviewed page)')
    ap.add_argument('--apply', action='store_true', help='fix draft page starts in the local layout DB')
    ap.add_argument('--jobs', type=int, default=8)
    args = ap.parse_args(argv)

    reviewed, in_cloud = cloud_state()
    skipped = sorted(p for p in _pages(args.pages, reviewed) if p in in_cloud and p not in reviewed)
    if skipped:
        print('saved in the cloud (Layout Studio shows that copy), skipped:', skipped)
    pages = [p for p in _pages(args.pages, reviewed) if p not in reviewed and p not in in_cloud]
    db = sqlite3.connect(LAYOUT_DB)
    fixes = start_fixes(db, pages, reviewed)
    if args.apply and fixes:
        with db:
            for page, (_old, new) in fixes.items():
                apply_start(db, page, new)
        print('page starts fixed:', sorted(fixes))
    headers = {r[0] for r in db.execute("SELECT DISTINCT page_number FROM pages WHERE line_type != 'ayah'")}
    db.close()

    plain = [p for p in pages if p not in headers]
    with ThreadPoolExecutor(args.jobs) as pool:
        results = dict(pool.map(split, plain))
    moved = {}
    if args.apply:
        db = sqlite3.connect(LAYOUT_DB)
        with db:
            for page, r in results.items():
                if isinstance(r, dict) and r.get('line_breaks'):
                    moved[page] = apply_line_breaks(db, page, r['line_breaks'])
        db.close()
        moved = {p: n for p, n in moved.items() if n}
        if moved:
            print('line breaks moved:', moved)
        again = sorted(set(moved) | {p for p in fixes if p in results})
        with ThreadPoolExecutor(args.jobs) as pool:
            results.update(dict(pool.map(split, again)))
    report = {}
    for page in pages:
        r = results.get(page)
        entry = {'header': page in headers, 'start_fix': fixes.get(page),
                 'start_fixed': bool(args.apply and page in fixes), 'breaks_moved': moved.get(page, 0),
                 'flags': r if isinstance(r, dict) else {}, 'error': r if isinstance(r, str) else None}
        entry['status'] = ('header' if entry['header'] else 'error' if entry['error']
                           else 'look' if entry['flags'] or (fixes.get(page) and not entry['start_fixed']) else 'clean')
        report[page] = entry
        print(page, entry['status'], *(f'{k}={v}' for k, v in entry['flags'].items()),
              *(['start: word after previous page'] if page in fixes else []),
              *([f'moved {moved[page]} break(s)'] if page in moved else []))
    if args.apply:
        save_triage(sqlite3.connect(LAYOUT_DB), report)
    out = ROOT / 'artifacts' / WORK / 'triage.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    counts = {}
    for e in report.values():
        counts[e['status']] = counts.get(e['status'], 0) + 1
    print(counts, '->', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
