#!/usr/bin/env python3
"""Build/migrate derived runtime databases explicitly, never during app boot."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DATABASE  # noqa: E402
from core.datasets import (  # noqa: E402
    waqf_rows_digital,
    waqf_rows_indopak,
    waqf_rows_qpc,
)
from core.text import initialize_waqf_database  # noqa: E402


def prepare() -> dict[str, int | str]:
    """Ensure required indexes and rebuild the derived waqf-symbol artifact."""
    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_verses_surah_ayah '
            'ON verses(surah_number, ayah_number)'
        )
        conn.commit()
    finally:
        conn.close()

    rows = waqf_rows_digital + waqf_rows_qpc + waqf_rows_indopak
    initialize_waqf_database(rows)
    return {'word_database': DATABASE, 'waqf_rows': len(rows)}


def main() -> int:
    result = prepare()
    print(
        f"Prepared {result['word_database']} and "
        f"{result['waqf_rows']} derived waqf rows."
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
