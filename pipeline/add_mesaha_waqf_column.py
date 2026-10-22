#!/usr/bin/env python3
"""Write the reviewed Mesaha waqf signs into mushaf_waqf.db as the «المساحة» column.

Source: the review cards (data/mesaha-waqf/mesaha-waqf-all) and the decisions saved for them in
``waqf_mark_review_decisions`` under «المساحة · فحص» (/mushaf-editor/mesaha-waqf). A word's mark
is the decision when there is one; an undecided (أ) card takes the model's reading (what
«اعتماد الكل» would save — 1,346 (أ) cards were checked by eye with no error); an undecided
(ب)/(ن) card stops the run.

Only the pages the cards cover are written (the Mesaha pages whose layout was checked); they
are recorded in ``waqf_column_pages`` so a reader can tell "no mark" from "not covered yet".
Every card sits on a word some other print marks, i.e. on an existing waqf row.

Dry run by default (prints what would change); ``--apply`` writes, after a backup.

    python3 pipeline/add_mesaha_waqf_column.py
    python3 pipeline/add_mesaha_waqf_column.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import MESAHA_WAQF_CARDS_DIR, MUSHAF_WAQF_DATABASE  # noqa: E402
from pipeline.cv_waqf.word_space import printed_position  # noqa: E402
from pipeline.paw_split.mesaha_waqf import SCRIPT_DB  # noqa: E402

COLUMN = 'المساحة'
DECISION_EDITION = 'المساحة · فحص'
CARD_SET = 'mesaha-waqf-all'
SIGNS = frozenset({'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع'})


def load_decisions() -> dict[tuple[int, int], str]:
    """{(page, word_index): mark} from the cloud, or the local review store without one."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from modules import mesaha_waqf_review as mw
    return {k: (r.get('correct_mark') or '') for k, r in mw.load_decisions().items()}


def resolve(cards: list[dict], decisions: dict[tuple[int, int], str]) -> tuple[dict, list[str]]:
    """{(surah, ayah, word_index): mark} for every card, and the cards that cannot be resolved."""
    marks, problems = {}, []
    for c in cards:
        key = (int(c['page']), int(c['word_index']))
        if key in decisions:
            mark = decisions[key]
        elif c['group'] == 'A':
            mark = c['model'] or ''
        else:
            problems.append(f"{c['id']} ({c['group']}) has no decision")
            continue
        if mark and mark not in SIGNS:
            problems.append(f"{c['id']}: unknown mark {mark!r}")
            continue
        s, a, n = map(int, c['key'].split(':'))
        pos = printed_position(SCRIPT_DB, s, a, n)
        if pos is None:
            problems.append(f"{c['id']}: {c['key']} has no printed position")
            continue
        marks[(s, a, pos)] = mark
    return marks, problems


def plan(conn: sqlite3.Connection, marks: dict) -> tuple[list[tuple], list[str]]:
    rows = {(s, a, w): (rid, cur) for rid, s, a, w, cur in conn.execute(
        f'SELECT rowid, "السورة", "الآية", word_index, "{COLUMN}" FROM waqf')} if _has_column(conn) else {
        (s, a, w): (rid, None) for rid, s, a, w in conn.execute(
            'SELECT rowid, "السورة", "الآية", word_index FROM waqf')}
    updates, missing = [], []
    for key, mark in sorted(marks.items()):
        if key not in rows:
            missing.append('%d:%d word %d' % key)
            continue
        rid, cur = rows[key]
        if (cur or '') != mark:
            updates.append((mark or None, rid))
    return updates, missing


def _has_column(conn) -> bool:
    return COLUMN in {r[1] for r in conn.execute('PRAGMA table_info(waqf)')}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='write the column (after a backup)')
    ap.add_argument('--database', default=MUSHAF_WAQF_DATABASE)
    args = ap.parse_args(argv)

    data = json.loads((Path(MESAHA_WAQF_CARDS_DIR) / CARD_SET / 'data.json').read_text(encoding='utf-8'))
    decisions = load_decisions()
    marks, problems = resolve(data['cards'], decisions)
    pages = sorted(set(data['pages']))
    conn = sqlite3.connect(args.database)
    updates, missing = plan(conn, marks)
    problems += [f'no waqf row for {m}' for m in missing]

    decided = sum((int(c['page']), int(c['word_index'])) in decisions for c in data['cards'])
    print(f'cards {len(data["cards"])} · decided {decided} · model-accepted (أ) {len(data["cards"]) - decided}')
    print(f'pages covered {len(pages)} ({pages[0]}-{pages[-1]}) · marks', dict(Counter(m for m in marks.values() if m)))
    print(f'rows to change {len(updates)}')
    if problems:
        print(f'{len(problems)} problem(s), nothing written:')
        for p in problems[:30]:
            print('  ', p)
        return 1
    if not args.apply:
        print('dry run: nothing written (add --apply)')
        return 0

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / 'artifacts' / 'backups' / f'mushaf_waqf.{stamp}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    conn.close()
    shutil.copy2(args.database, backup)
    conn = sqlite3.connect(args.database)
    with conn:
        if not _has_column(conn):
            conn.execute(f'ALTER TABLE waqf ADD COLUMN "{COLUMN}" TEXT')
        conn.execute('CREATE TABLE IF NOT EXISTS waqf_column_pages ('
                     'edition TEXT NOT NULL, page_number INTEGER NOT NULL, PRIMARY KEY (edition, page_number))')
        conn.executemany(f'UPDATE waqf SET "{COLUMN}" = ? WHERE rowid = ?', updates)
        conn.executemany('INSERT OR IGNORE INTO waqf_column_pages VALUES (?, ?)', [(COLUMN, p) for p in pages])
    n = conn.execute(f'SELECT COUNT(*) FROM waqf WHERE "{COLUMN}" <> \'\'').fetchone()[0]
    print(f'written: {len(updates)} rows; «{COLUMN}» now has {n} marks on {len(pages)} pages · backup {backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
