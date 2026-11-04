#!/usr/bin/env python3
"""Apply the reviewer's decisions on the mesaha-waqf-prints-check cards (Qatar / Kuwait / Bahrain) to the waqf
columns: the local mushaf_waqf.db rows and the cloud's published marks.

Only the decided cards whose sign differs from the column are written. In the cloud each change is a draft,
then the edition is published with the editor's atomic publish; the run stops first if the edition already has
other unpublished drafts, so nothing else gets published with them.

Dry run by default; ``--apply`` writes (local backup first).

    python3 pipeline/apply_print_check.py
    python3 pipeline/apply_print_check.py --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402
from core.config import MUSHAF_WAQF_DATABASE  # noqa: E402

SET = 'mesaha-waqf-prints-check'


def changes() -> list[dict]:
    from modules import mesaha_waqf_review as mw
    data = mw._load_set(SET)
    decided = mw.set_decisions(data)
    out = []
    for c in data['cards']:
        row = decided.get(c['id'])
        if row is None:
            continue
        mark = (row.get('correct_mark') or '').strip()
        if mark != (c['model'] or ''):
            s, a, w = map(int, c['key'].split(':'))
            out.append({'edition': c['print'], 'key': (s, a, w), 'old': c['model'] or '', 'new': mark, 'text': c['text']})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not sb.is_configured():
        print('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured')
        return 2
    from pipeline.sync_published_waqf import load_local_state

    todo = changes()
    for c in todo:
        print(f"{c['edition']} {':'.join(map(str, c['key']))} {c['text']}: {c['old'] or '-'} → {c['new'] or '-'}")
    if not todo:
        print('nothing to change')
        return 0
    editions = sorted({c['edition'] for c in todo})
    for ed in editions:
        pending = sb.pending_publish_diff(ed)
        if pending:
            print(f'{ed}: {len(pending) if hasattr(pending, "__len__") else pending} unpublished draft(s) already in the cloud; publish or clear them first')
            return 1
    if not args.apply:
        print('dry run: nothing written (add --apply)')
        return 0

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / 'artifacts' / 'backups' / f'mushaf_waqf.{stamp}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MUSHAF_WAQF_DATABASE, backup)
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    with conn:
        for c in todo:
            n = conn.execute(f'UPDATE waqf SET "{c["edition"]}" = ? WHERE "السورة" = ? AND "الآية" = ? AND word_index = ?',
                             (c['new'] or None, *c['key'])).rowcount
            if n != 1:
                raise SystemExit(f"no single waqf row for {c['key']}")
    conn.close()

    state = load_local_state(Path(MUSHAF_WAQF_DATABASE), editions)
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    rowid_of = {c['key']: conn.execute('SELECT rowid FROM waqf WHERE "السورة" = ? AND "الآية" = ? AND word_index = ?',
                                       c['key']).fetchone()[0] for c in todo}
    conn.close()
    # the cloud is keyed by its own token numbering: the local row's mapped token (by rowid)
    token_of = {r['rowid']: k for k, r in state['rows'].items()}
    for ed in editions:
        rows = []
        for c in (x for x in todo if x['edition'] == ed):
            k = token_of.get(rowid_of[c['key']])
            if k is None:
                raise SystemExit(f'{ed} {c["key"]}: no cloud token for the word')
            rows.append({'edition': ed, 'surah': k[0], 'ayah': k[1], 'token_index': k[2], 'status': 'draft',
                         'symbol': c['new'], 'word_text': state['rows'][k]['canonical_word']})
        sb.upsert_marks_batch(rows)
        pending = sb.pending_publish_diff(ed)
        n = sb.publish_edition(ed, actor_id=None, actor_name='Print check cards', expected_changes=pending)
        print(f'{ed}: published {n}')
    print(f'local backup {backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
