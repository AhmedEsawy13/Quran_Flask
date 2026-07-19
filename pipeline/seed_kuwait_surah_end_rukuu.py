#!/usr/bin/env python3
"""Put ركوع on the last ayah-end word of every surah for مصحف الكويت only.

Does not clear existing mid-surah ركوع marks. Skips words that already have a
non-empty الكويت mark other than ركوع (so real waqf is not overwritten).

Usage:
  python3 pipeline/seed_kuwait_surah_end_rukuu.py
  python3 pipeline/seed_kuwait_surah_end_rukuu.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from modules.editor import _get_or_set_word_waqf  # noqa: E402
from modules.layouts import _get_dk_layout_word_map  # noqa: E402

EDITION = 'الكويت'
SYMBOL = 'ركوع'


def surah_end_word_ids():
    wmap = _get_dk_layout_word_map()
    max_ayah = defaultdict(int)
    for surah, ayah in wmap['last_id']:
        if ayah > max_ayah[surah]:
            max_ayah[surah] = ayah
    out = []
    for surah in sorted(max_ayah):
        ayah = max_ayah[surah]
        word_id = wmap['last_id'].get((surah, ayah))
        if word_id is None:
            continue
        tok = wmap['id2tok'].get(word_id) or {}
        out.append((surah, ayah, word_id, tok.get('text') or ''))
    return out


def seed(dry_run: bool = False) -> dict:
    targets = surah_end_word_ids()
    stats = {'targets': len(targets), 'set': 0, 'already': 0, 'skipped': 0}
    for surah, ayah, word_id, text in targets:
        current = _get_or_set_word_waqf(word_id, EDITION, None)
        current = (current or '').strip()
        if current == SYMBOL:
            stats['already'] += 1
            continue
        if current:
            stats['skipped'] += 1
            print(f'  skip {surah}:{ayah} word {word_id} ({text!r}) — already {current!r}')
            continue
        if dry_run:
            print(f'  would set {surah}:{ayah} word {word_id} ({text!r}) → {SYMBOL}')
            stats['set'] += 1
            continue
        result = _get_or_set_word_waqf(word_id, EDITION, SYMBOL)
        if result == SYMBOL:
            stats['set'] += 1
        else:
            stats['skipped'] += 1
            print(f'  failed {surah}:{ayah} word {word_id}')
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    stats = seed(dry_run=args.dry_run)
    mode = 'dry-run' if args.dry_run else 'applied'
    print(
        f'[{mode}] الكويت surah-end {SYMBOL}: '
        f'{stats["set"]} set, {stats["already"]} already, '
        f'{stats["skipped"]} skipped / {stats["targets"]} surahs'
    )


if __name__ == '__main__':
    main()
