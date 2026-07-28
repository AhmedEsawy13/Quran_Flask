#!/usr/bin/env python3
"""Add مصحف البحرين waqf column to mushaf_waqf.db.

البحرين uses the Madinah 1421 layout (digital-khatt-15-lines.db / QPC v2) and
the Digital Khatt webfont — same pairing as تثبيت's qpc_v2 source. Marks are
seeded from المدينة الجديد so the editor's orange baseline-diff highlighting
starts clean.

This migration:
  1. Adds TEXT column البحرين (no-op if already present).
  2. Seeds empty cells from المدينة الجديد (re-run safe).
"""

from __future__ import annotations

import os
import sqlite3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSHAF_WAQF_DB = os.path.join(ROOT_DIR, "data", "mushaf_waqf.db")

NEW_COLUMN = "البحرين"
SEED_FROM = "المدينة الجديد"


def main() -> int:
    if not os.path.exists(MUSHAF_WAQF_DB):
        print(f"ERROR: mushaf waqf db not found: {MUSHAF_WAQF_DB}")
        return 1

    conn = sqlite3.connect(MUSHAF_WAQF_DB)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(waqf)")
        existing_cols = {row[1] for row in cur.fetchall()}

        if NEW_COLUMN not in existing_cols:
            cur.execute(f'ALTER TABLE waqf ADD COLUMN "{NEW_COLUMN}" TEXT')
            print(f"Added column: {NEW_COLUMN}")
        else:
            print(f"Column already exists: {NEW_COLUMN}")

        if SEED_FROM not in existing_cols:
            print(f"ERROR: seed source column missing: {SEED_FROM}")
            return 1

        cur.execute(
            f'UPDATE waqf SET "{NEW_COLUMN}" = "{SEED_FROM}" '
            f'WHERE ("{NEW_COLUMN}" IS NULL OR "{NEW_COLUMN}" = \'\') '
            f'AND "{SEED_FROM}" IS NOT NULL AND "{SEED_FROM}" <> \'\''
        )
        print(f"Seeded {cur.rowcount} rows for {NEW_COLUMN} from {SEED_FROM}")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mushaf_editor_progress (
                page_number INTEGER NOT NULL,
                edition TEXT NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                PRIMARY KEY (page_number, edition)
            )
            """
        )

        conn.commit()

        cur.execute(
            f'SELECT COUNT(*) FROM waqf WHERE "{NEW_COLUMN}" IS NOT NULL AND "{NEW_COLUMN}" <> \'\''
        )
        print(f"{NEW_COLUMN}: {cur.fetchone()[0]} marked words")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
