#!/usr/bin/env python3
"""Strict, local audit for every released classical waqf book.

This is intentionally model-free and network-free.  It checks immutable
source hashes, catalog/DB agreement, coverage floors, the closed grade
lexicon, valid Qur'an coordinates, and phrase alignment for every confident
row.  A non-zero exit makes it suitable as a CI release gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / 'pipeline'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PIPELINE))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_waqf as classical  # noqa: E402

CATALOG = PIPELINE / 'classical_books.json'
DEFAULT_DB = ROOT / 'data' / 'classical_waqf.db'
GRADES = {canonical for _, canonical in classical.GRADES}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def audit(db_path: Path, catalog_path: Path) -> tuple[list[str], dict]:
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    books = catalog.get('books') or {}
    errors: list[str] = []
    report: dict = {'sources': {}, 'errors': errors}

    if catalog.get('schema_version') != 1:
        errors.append('unsupported catalog schema_version')
    for key, spec in books.items():
        for file_field, hash_field in (
                ('source_file', 'source_sha256'),
                ('cross_check_file', 'cross_check_sha256')):
            if file_field not in spec:
                continue
            path = PIPELINE / spec[file_field]
            if not path.is_file():
                errors.append(f'{key}: missing {file_field} {path}')
                continue
            actual = digest(path)
            if actual != spec.get(hash_field):
                errors.append(f'{key}: {file_field} checksum changed; '
                              f'expected {spec.get(hash_field)}, got {actual}')

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        db_sources = {row[0] for row in conn.execute(
            'SELECT DISTINCT source FROM classical')}
        missing = set(books) - db_sources
        extra = db_sources - set(books)
        if missing:
            errors.append(f'DB missing catalog sources: {sorted(missing)}')
        if extra:
            errors.append(f'DB has uncataloged sources: {sorted(extra)}')

        for key, spec in books.items():
            rows = conn.execute(
                'SELECT id,surah,ayah,wpos,quote,grade,conf FROM classical '
                'WHERE source=? ORDER BY id', (key,)).fetchall()
            surahs = {row['surah'] for row in rows}
            confident = [row for row in rows if row['conf'] == 1]
            source_report = {
                'rows': len(rows), 'surahs': len(surahs),
                'confident': len(confident), 'review': len(rows) - len(confident),
            }
            report['sources'][key] = source_report
            if len(rows) < int(spec['minimum_rows']):
                errors.append(f'{key}: {len(rows)} rows below floor {spec["minimum_rows"]}')
            if len(surahs) < int(spec['minimum_surahs']):
                errors.append(f'{key}: {len(surahs)} surahs below floor {spec["minimum_surahs"]}')

            bad_grade = [row['id'] for row in rows if row['grade'] not in GRADES]
            if bad_grade:
                errors.append(f'{key}: {len(bad_grade)} rows have invalid grades')
            bad_coordinates = [row['id'] for row in confident
                               if row['ayah'] is None or row['wpos'] is None]
            if bad_coordinates:
                errors.append(f'{key}: {len(bad_coordinates)} confident rows lack coordinates')

            unaligned = []
            for row in confident:
                if row['ayah'] is None or row['wpos'] is None:
                    continue
                hit, _ = classical.align_in_ayah(
                    row['surah'], row['ayah'], classical.quote_words(row['quote']))
                if hit is None:
                    unaligned.append(row['id'])
            source_report['unaligned'] = len(unaligned)
            if unaligned:
                errors.append(f'{key}: {len(unaligned)} confident quotes do not align')

        # New deterministic imports must have complete row-level provenance.
        if table_exists(conn, 'classical_provenance') and table_exists(conn, 'classical_editions'):
            imported = {row[0] for row in conn.execute('SELECT source FROM classical_editions')}
            for key in imported:
                missing_prov = conn.execute(
                    'SELECT COUNT(*) FROM classical c LEFT JOIN classical_provenance p '
                    'ON p.classical_id=c.id WHERE c.source=? AND p.classical_id IS NULL',
                    (key,)).fetchone()[0]
                if missing_prov:
                    errors.append(f'{key}: {missing_prov} imported rows lack provenance')
    finally:
        conn.close()
    return errors, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    ap.add_argument('--catalog', type=Path, default=CATALOG)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    errors, report = audit(args.db, args.catalog)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, stats in report['sources'].items():
            print(f'{key:8} rows={stats["rows"]:5} surahs={stats["surahs"]:3} '
                  f'confident={stats["confident"]:5} review={stats["review"]:3} '
                  f'unaligned={stats["unaligned"]}')
        if errors:
            print('\nFAIL')
            for error in errors:
                print(f'  - {error}')
        else:
            print('\nPASS: catalog, sources, coverage, grades, and alignments are valid')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
