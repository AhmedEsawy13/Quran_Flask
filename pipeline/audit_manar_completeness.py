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

    sections = llm.load_shamela_sections()
    expected = set()
    per_surah = {}
    for surah in range(1, 115):
        rows = llm.explicit_manar_rows(surah, sections[str(surah)]['text'])
        keys = {(surah, r[1], r[2], r[5]) for r in rows}
        expected.update(keys)
        per_surah[surah] = len(keys)

    conn = sqlite3.connect(args.db)
    try:
        actual = set(conn.execute(
            'SELECT surah, ayah, wpos, grade FROM classical WHERE source=? AND conf=1',
            (args.source,)))
        db_surahs = {r[0] for r in actual}
    finally:
        conn.close()

    missing = sorted(expected - actual)
    print(f'DB source={args.source}: {len(actual)} unique confident ruling keys, '
          f'{len(db_surahs)}/114 surahs')
    print(f'Authoritative explicit source: {len(expected)} aligned unique ruling keys, '
          f'{sum(1 for n in per_surah.values() if n)}/114 surahs with explicit entries')
    print(f'Missing mechanically verifiable explicit rulings: {len(missing)}')
    for row in missing[:args.samples]:
        print(' ', row)
    if args.strict and missing:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
