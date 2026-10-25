#!/usr/bin/env python3
"""Upload a Mesaha waqf column («المساحة», or «المساحة ١٣٧١» with --edition) from mushaf_waqf.db to the cloud and publish it.

The local column (built by add_mesaha_waqf_column.py from the reviewed cards) is the source:
each local mark is mapped onto the cloud's word numbering (the canonical within-ayah token, as
sync_published_waqf.py does), compared with the cloud's published marks, and the differences are
written as drafts and then published with the same atomic publish the editor uses. A published
mark with no local mark is cleared (the cloud copy only ever comes from this column).

Needs the «المساحة» row in editor_edition_capabilities (pipeline/supabase_add_mesaha_edition.sql).
Dry run by default; ``--apply`` uploads, publishes, and re-checks that the cloud equals the column.

    python3 pipeline/push_mesaha_waqf_cloud.py
    python3 pipeline/push_mesaha_waqf_cloud.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402
from core.config import MUSHAF_WAQF_DATABASE  # noqa: E402

EDITION = 'المساحة'


def local_marks() -> dict[tuple[int, int, int], dict]:
    from pipeline.sync_published_waqf import load_local_state
    state = load_local_state(Path(MUSHAF_WAQF_DATABASE), [EDITION])
    if state['errors']:
        raise SystemExit('cannot map local rows onto cloud tokens:\n  ' + '\n  '.join(state['errors'][:20]))
    return state['marks'][EDITION]


def cloud_marks(status: str) -> dict[tuple[int, int, int], str]:
    rows = sb.fetch_marks(edition=EDITION, status=status)
    return {(int(r['surah']), int(r['ayah']), int(r['token_index'])): (r.get('symbol') or '') for r in rows}


def diff(local: dict, published: dict[tuple[int, int, int], str]) -> list[dict]:
    """Draft rows that make the published marks equal the local column."""
    out = []
    for key, m in sorted(local.items()):
        if published.get(key, '') != m['symbol']:
            out.append({'edition': EDITION, 'surah': key[0], 'ayah': key[1], 'token_index': key[2],
                        'status': 'draft', 'symbol': m['symbol'], 'word_text': m['word_text']})
    for key, symbol in sorted(published.items()):
        if symbol and key not in local:
            out.append({'edition': EDITION, 'surah': key[0], 'ayah': key[1], 'token_index': key[2],
                        'status': 'draft', 'symbol': '', 'word_text': None})
    return out


def main(argv: list[str] | None = None) -> int:
    global EDITION
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='upload the differences and publish them')
    ap.add_argument('--edition', default='المساحة', choices=['المساحة', 'المساحة ١٣٧١'])
    args = ap.parse_args(argv)
    EDITION = args.edition
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not sb.is_configured():
        print('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured')
        return 2

    local = local_marks()
    published = cloud_marks('published')
    changes = diff(local, published)
    print(f'local marks {len(local)} · cloud published {sum(1 for s in published.values() if s)}')
    print(f'to upload {len(changes)}:', dict(Counter(c["symbol"] or 'clear' for c in changes)))
    if not changes:
        print('the cloud already equals the local column')
        return 0
    if not args.apply:
        print('dry run: nothing uploaded (add --apply)')
        return 0

    sb.upsert_marks_batch(changes)
    pending = sb.pending_publish_diff(EDITION)
    n = sb.publish_edition(EDITION, actor_id=None, actor_name='Mesaha review import', expected_changes=pending)
    left = diff(local, cloud_marks('published'))
    print(f'published {n} · still differing after publish: {len(left)}')
    return 1 if left else 0


if __name__ == '__main__':
    raise SystemExit(main())
