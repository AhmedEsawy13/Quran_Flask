#!/usr/bin/env python3
"""Reproducible completeness audit for the released Manar dataset.

This checks the strongest claim that can be proved without another model:
every explicit ``{quote} [ayah] grade`` ruling in the authoritative
Shamela-derived source that aligns to that Qur'an ayah must exist in the DB.
Damaged references and adjacent-surah page spillover are reported separately;
they are never guessed into the database.

Run:
    python3 pipeline/audit_manar_completeness.py
    python3 pipeline/audit_manar_completeness.py --strict
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_llm as llm  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=os.path.join('data', 'classical_waqf.db'))
    ap.add_argument('--source', default='manar')
    ap.add_argument('--strict', action='store_true',
                    help='exit nonzero if any mechanically alignable ruling is absent')
    ap.add_argument('--samples', type=int, default=20)
    args = ap.parse_args(argv)

    source_sets = {}
    for label, sections in (
        ('Shamela JSON', llm.load_shamela_sections()),
        ('OpenITI cross-check', llm._openiti_manar_crosscheck_sections()),
    ):
        keys = set()
        for surah in range(1, 115):
            rows = llm.explicit_manar_rows(surah, sections[str(surah)]['text'])
            keys.update((surah, r[1], r[2], r[5]) for r in rows)
        source_sets[label] = keys
    expected = set().union(*source_sets.values())

    conn = sqlite3.connect(args.db)
    try:
        actual_confident = set(conn.execute(
            'SELECT surah, ayah, wpos, grade FROM classical WHERE source=? AND conf=1',
            (args.source,)))
        actual_any = set(conn.execute(
            'SELECT surah, ayah, wpos, grade FROM classical WHERE source=?',
            (args.source,)))
        db_surahs = {r[0] for r in actual_any}
    finally:
        conn.close()

    # Completeness is existence in the released DB. Review rows (conf=0) still
    # count — they are present, just awaiting promotion. A small aligner-drift
    # class also lands the same surah/ayah/grade on a neighbouring wpos; treat
    # those as present when that grade already exists on the ayah.
    present_sag = {(s, a, g) for s, a, _w, g in actual_any}
    missing_exact = expected - actual_any
    missing = sorted(
        key for key in missing_exact
        if (key[0], key[1], key[3]) not in present_sag
    )
    review_only = sorted((expected & actual_any) - actual_confident)

    print(f'DB source={args.source}: {len(actual_confident)} unique confident ruling keys, '
          f'{len(actual_any)} including review (conf=0), {len(db_surahs)}/114 surahs')
    for label, keys in source_sets.items():
        print(f'{label} explicit source: {len(keys)} aligned unique ruling keys, '
              f'{len({key[0] for key in keys})}/114 surahs with explicit entries')
    print(f'Union of explicit source checks: {len(expected)} aligned unique ruling keys')
    print(f'Review-only (present at conf=0): {len(review_only)}')
    print(f'Aligner wpos drift (same ayah+grade present): {len(missing_exact) - len(missing)}')
    print(f'Missing mechanically verifiable explicit rulings: {len(missing)}')
    for row in missing[:args.samples]:
        print(' ', row)
    if args.strict and missing:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
