#!/usr/bin/env python3
"""Fail CI when a versioned database or canonical layout stream is damaged."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import MESAHA_LAYOUT_DATABASE, QURAN_SCRIPT_DATABASE  # noqa: E402
from modules import layout_engine  # noqa: E402


def _tracked_databases() -> list[Path]:
    result = subprocess.run(
        ['git', 'ls-files', 'data/*.db'],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def _sqlite_integrity(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return str(conn.execute('PRAGMA integrity_check').fetchone()[0])


def _mesaha_stream() -> tuple[int, int]:
    word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    expected = word_map['ordered_ids']
    positions = word_map['position_by_id']
    emitted: list[int] = []
    with sqlite3.connect(MESAHA_LAYOUT_DATABASE) as conn:
        rows = conn.execute(
            '''
            SELECT first_word_id, last_word_id
            FROM pages
            WHERE first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ORDER BY page_number, line_number
            '''
        ).fetchall()
    for first, last in rows:
        lo = positions.get(int(first))
        hi = positions.get(int(last))
        # Imported decorative/header glyph spans may use IDs outside the
        # canonical recitation stream. They do not participate in continuity.
        if lo is None or hi is None:
            continue
        if hi < lo:
            raise RuntimeError(f'invalid Mesaha endpoint span: {first}..{last}')
        emitted.extend(expected[lo:hi + 1])
    if emitted != expected:
        raise RuntimeError(
            f'Mesaha canonical stream mismatch: {len(emitted)} != {len(expected)}'
        )
    return len(rows), len(emitted)


def audit() -> dict:
    errors: list[str] = []
    checked = []
    for path in _tracked_databases():
        if not path.exists():
            errors.append(f'missing tracked database: {path.relative_to(ROOT)}')
            continue
        try:
            result = _sqlite_integrity(path)
        except sqlite3.DatabaseError as exc:
            errors.append(f'{path.relative_to(ROOT)}: {exc}')
            continue
        if result != 'ok':
            errors.append(f'{path.relative_to(ROOT)}: integrity={result}')
        checked.append(str(path.relative_to(ROOT)))

    try:
        mesaha_lines, canonical_words = _mesaha_stream()
    except (RuntimeError, sqlite3.DatabaseError) as exc:
        errors.append(str(exc))
        mesaha_lines = canonical_words = 0

    report_path = ROOT / 'data' / 'mushaf-mesaha-import-report.json'
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
        validation = report['validation']
        if validation.get('canonical_word_key_stream_exact') is not True:
            errors.append('Mesaha report does not certify canonical key continuity')
        if validation.get('canonical_word_keys_unique') is not True:
            errors.append('Mesaha report does not certify unique canonical keys')
        confidence = float(report['confidence']['mean_score'])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid Mesaha import report: {exc}')
        confidence = 0.0

    result = {
        'databases_checked': len(checked),
        'mesaha_ayah_lines': mesaha_lines,
        'canonical_words': canonical_words,
        'mesaha_import_confidence': confidence,
        'errors': errors,
    }
    if errors:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    try:
        result = audit()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'RELEASE AUDIT FAILED\n{exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
