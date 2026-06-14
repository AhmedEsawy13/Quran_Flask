#!/usr/bin/env python3
"""Add مصحف قطر / مصحف الكويت الحديث waqf columns to mushaf_waqf.db.

Both editions are being built starting from the Madinah v1 layout
(qpc-v1-15-lines.db) with وقوف المدينة as the initial baseline — differences
are then adjusted manually via the /mushaf-editor tool.

This migration:
  1. Adds two new TEXT columns to waqf: قطر, الكويت (no-ops if already present).
  2. Seeds every existing row's new columns from المدينة (only where the new
     column is currently empty, so re-running is safe).
  3. Creates mushaf_editor_progress(page_number, edition) to track which pages
     of the 604-page layout have been manually reviewed for each edition.
"""

from __future__ import annotations

import os
import sqlite3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSHAF_WAQF_DB = os.path.join(ROOT_DIR, "data", "mushaf_waqf.db")

NEW_COLUMNS = ["قطر", "الكويت"]
SEED_FROM = "المدينة"


def main() -> int:
    if not os.path.exists(MUSHAF_WAQF_DB):
        print(f"ERROR: mushaf waqf db not found: {MUSHAF_WAQF_DB}")
        return 1

    conn = sqlite3.connect(MUSHAF_WAQF_DB)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(waqf)")
        existing_cols = {row[1] for row in cur.fetchall()}

        for col in NEW_COLUMNS:
            if col not in existing_cols:
                cur.execute(f'ALTER TABLE waqf ADD COLUMN "{col}" TEXT')
                print(f"Added column: {col}")
            else:
                print(f"Column already exists: {col}")

            cur.execute(
                f'UPDATE waqf SET "{col}" = "{SEED_FROM}" '
                f'WHERE ("{col}" IS NULL OR "{col}" = \'\') '
                f'AND "{SEED_FROM}" IS NOT NULL AND "{SEED_FROM}" <> \'\''
            )
            print(f"Seeded {cur.rowcount} rows for {col} from {SEED_FROM}")

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

        for col in NEW_COLUMNS:
            cur.execute(f'SELECT COUNT(*) FROM waqf WHERE "{col}" IS NOT NULL AND "{col}" <> \'\'')
            print(f"{col}: {cur.fetchone()[0]} marked words")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
