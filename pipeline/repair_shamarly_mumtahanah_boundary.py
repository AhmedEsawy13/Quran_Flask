#!/usr/bin/env python3
"""Repair the Shemrly Al-Hashr/Al-Mumtahanah boundary on page 465.

The Quran word IDs around this boundary are intentionally non-monotonic:
60:1:1-41 use IDs 76379-76419, while the end of surah 59 uses later IDs.
The word spans are correct, but four rows retained surah 59 as stale metadata
and the basmala row between the surah header and 60:1 was absent.

This migration is idempotent and refuses to write unless the affected word
spans still match quran_script.db.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYOUT = ROOT / "data" / "mushaf_layout_inferred.db"
DEFAULT_SCRIPT = ROOT / "data" / "quran_script.db"
BASMALA = "بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ"

EXPECTED_SPANS = {
    (465, 9): ("59:24:9", "59:24:18"),
    (465, 12): ("60:1:1", "60:1:10"),
    (465, 13): ("60:1:11", "60:1:20"),
    (465, 14): ("60:1:21", "60:1:31"),
    (465, 15): ("60:1:32", "60:1:41"),
}


def _word_key(cursor: sqlite3.Cursor, word_id: int) -> str:
    row = cursor.execute(
        "SELECT word_key FROM words WHERE word_index = ?",
        (int(word_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown Quran word ID: {word_id}")
    return str(row[0])


def repair_boundary(
    layout_database: str | Path = DEFAULT_LAYOUT,
    script_database: str | Path = DEFAULT_SCRIPT,
) -> dict[str, int]:
    layout = sqlite3.connect(str(layout_database))
    script = sqlite3.connect(f"file:{Path(script_database).resolve()}?mode=ro", uri=True)
    try:
        layout.row_factory = sqlite3.Row
        layout_cursor = layout.cursor()
        script_cursor = script.cursor()

        rows = {
            (int(row["page_number"]), int(row["line_number"])): row
            for row in layout_cursor.execute(
                """
                SELECT id, page_number, line_number, line_type,
                       first_word_id, last_word_id, surah_number, line_text
                FROM pages
                WHERE page_number = 465
                """
            )
        }

        for location, expected_keys in EXPECTED_SPANS.items():
            row = rows.get(location)
            if row is None or row["line_type"] != "ayah":
                raise ValueError(f"Missing expected ayah row at {location}")
            actual_keys = (
                _word_key(script_cursor, row["first_word_id"]),
                _word_key(script_cursor, row["last_word_id"]),
            )
            if actual_keys != expected_keys:
                raise ValueError(
                    f"Unexpected Quran span at {location}: "
                    f"expected {expected_keys}, found {actual_keys}"
                )

        header = rows.get((465, 10))
        if (
            header is None
            or header["line_type"] != "surah_name"
            or int(header["surah_number"] or 0) != 60
        ):
            raise ValueError("Missing the expected Al-Mumtahanah header on page 465")

        existing_basmala = rows.get((465, 11))
        inserted = 0
        if existing_basmala is None:
            layout_cursor.execute(
                """
                INSERT INTO pages (
                    page_number, line_number, line_type, is_centered,
                    first_word_id, last_word_id, surah_number, line_text
                ) VALUES (465, 11, 'basmallah', 1, NULL, NULL, 60, ?)
                """,
                (BASMALA,),
            )
            inserted = 1
        elif not (
            existing_basmala["line_type"] == "basmallah"
            and int(existing_basmala["surah_number"] or 0) == 60
            and existing_basmala["line_text"] == BASMALA
        ):
            raise ValueError("Page 465 line 11 exists but is not the expected basmala")

        updated = layout_cursor.execute(
            """
            UPDATE pages
            SET surah_number = 60
            WHERE page_number = 465
              AND line_number BETWEEN 12 AND 15
              AND line_type = 'ayah'
              AND surah_number != 60
            """
        ).rowcount

        if updated not in (0, 4):
            raise ValueError(f"Expected to update zero or four ayah rows, updated {updated}")

        layout.commit()
        return {"basmala_rows_inserted": inserted, "ayah_rows_updated": updated}
    except Exception:
        layout.rollback()
        raise
    finally:
        script.close()
        layout.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    args = parser.parse_args()
    result = repair_boundary(args.layout, args.script)
    print(
        "Shemrly page 465 repaired: "
        f"{result['ayah_rows_updated']} metadata rows updated, "
        f"{result['basmala_rows_inserted']} basmala row inserted."
    )


if __name__ == "__main__":
    main()
