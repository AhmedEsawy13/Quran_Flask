#!/usr/bin/env python3
"""Write the 1371 AH / 1952 Mesaha print's waqf signs into mushaf_waqf.db as the «المساحة ١٣٧١» column.

The 1952 print reuses the 1924 plates and revises part of the signs (pipeline/paw_split/mesaha1371.py), so the
column is the 1924 «المساحة» column with:
  - every 1952 review card's decision (data/mesaha-waqf/mesaha-waqf-1371, saved under «المساحة ١٣٧١ · فحص»);
    the cards cover every word some print marks whose 1952 reading differs from 1924;
  - data/mesaha-waqf/mesaha-waqf-1371/extra_marks.json: signs 1952 adds on words no print marks (103 «لا»
    before a verse ring) and 2:2, read by eye.
Every card must be decided. A mark on a word with no waqf row gets a new row.

Dry run by default; ``--apply`` writes, after a backup.

    python3 pipeline/add_mesaha1371_waqf_column.py
    python3 pipeline/add_mesaha1371_waqf_column.py --apply
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

COLUMN = 'المساحة ١٣٧١'
BASE = 'المساحة'
CARD_SET = 'mesaha-waqf-1371'
SIGNS = frozenset({'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع'})
PAGES = range(2, 828)


def _pos(key: str) -> tuple[int, int, int] | None:
    s, a, n = map(int, key.split(':'))
    pos = printed_position(SCRIPT_DB, s, a, n)
    return (s, a, pos) if pos else None


def target(conn, cards: list[dict], decisions: dict, extra: list[dict]) -> tuple[dict, list[str]]:
    """{(surah, ayah, word_index): mark} for the whole column, and the problems found."""
    marks = {(s, a, w): (m or '').strip() for s, a, w, m in conn.execute(
        f'SELECT "السورة", "الآية", word_index, "{BASE}" FROM waqf')}
    problems = []
    for c in cards:
        mark = decisions.get((int(c['page']), int(c['word_index'])))
        if mark is None:
            problems.append(f"{c['id']} ({c['group']}) has no decision")
            continue
        key = _pos(c['key'])
        if key is None or (mark and mark not in SIGNS):
            problems.append(f"{c['id']}: bad key or mark {mark!r}")
            continue
        marks[key] = mark
    for x in extra:
        key = _pos(x['key'])
        if key is None or x['mark'] not in SIGNS:
            problems.append(f"extra {x['key']}: bad key or mark")
            continue
        marks[key] = x['mark']
    return {k: v for k, v in marks.items()}, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--database', default=MUSHAF_WAQF_DATABASE)
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from modules import mesaha_waqf_review as mw

    folder = Path(MESAHA_WAQF_CARDS_DIR) / CARD_SET
    data = json.loads((folder / 'data.json').read_text(encoding='utf-8'))
    extra = json.loads((folder / 'extra_marks.json').read_text(encoding='utf-8'))
    decisions = {k: (r.get('correct_mark') or '') for k, r in mw.load_decisions(mw.set_edition(data)).items()}
    conn = sqlite3.connect(args.database)
    marks, problems = target(conn, data['cards'], decisions, extra)
    rows = {(s, a, w): rid for rid, s, a, w in conn.execute('SELECT rowid, "السورة", "الآية", word_index FROM waqf')}
    new_rows = sorted(k for k, v in marks.items() if v and k not in rows)
    base = {(s, a, w): (m or '').strip() for s, a, w, m in conn.execute(f'SELECT "السورة", "الآية", word_index, "{BASE}" FROM waqf')}
    diff = Counter(f"{base.get(k, '') or '-'}→{v or '-'}" for k, v in marks.items() if v != base.get(k, ''))
    print(f'cards {len(data["cards"])} · extra {len(extra)} · marks {sum(1 for v in marks.values() if v)}'
          f' · differ from «{BASE}» {sum(diff.values())} · new rows {len(new_rows)}')
    print('  ', dict(diff.most_common(10)))
    if problems:
        print(f'{len(problems)} problem(s), nothing written:', *problems[:20], sep='\n  ')
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
    qs = sqlite3.connect(SCRIPT_DB)
    with conn:
        if COLUMN not in {r[1] for r in conn.execute('PRAGMA table_info(waqf)')}:
            conn.execute(f'ALTER TABLE waqf ADD COLUMN "{COLUMN}" TEXT')
        for s, a, w in new_rows:
            # token_index counts a leading ۞ as a token, word_index does not (pipeline/build_indopak_waqf.py)
            first = (qs.execute('SELECT text FROM words WHERE surah=? AND ayah=? ORDER BY word_index LIMIT 1',
                                (s, a)).fetchone() or [''])[0].strip()
            token = w + (1 if first == '۞' else 0)
            text = (qs.execute('SELECT text FROM words WHERE word_key=?', (f'{s}:{a}:{token}',)).fetchone() or [''])[0]
            conn.execute('INSERT INTO waqf ("السورة", "الآية", "الكلمة", word_index, token_index) VALUES (?, ?, ?, ?, ?)',
                         (s, a, text, w, token))
        conn.execute(f'UPDATE waqf SET "{COLUMN}" = NULL')
        ids = {(s, a, w): rid for rid, s, a, w in conn.execute('SELECT rowid, "السورة", "الآية", word_index FROM waqf')}
        conn.executemany(f'UPDATE waqf SET "{COLUMN}" = ? WHERE rowid = ?',
                         [(v, ids[k]) for k, v in marks.items() if v and k in ids])
        conn.execute('DELETE FROM waqf_column_pages WHERE edition = ?', (COLUMN,))
        conn.executemany('INSERT INTO waqf_column_pages VALUES (?, ?)', [(COLUMN, p) for p in PAGES])
    n = conn.execute(f'SELECT COUNT(*) FROM waqf WHERE "{COLUMN}" <> \'\'').fetchone()[0]
    print(f'written: «{COLUMN}» has {n} marks on pages 2-827 · backup {backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
