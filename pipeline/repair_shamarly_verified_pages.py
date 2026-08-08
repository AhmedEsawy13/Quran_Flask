#!/usr/bin/env python3
"""Apply the remaining PDF-verified Shemrly layout repairs.

The companion ``ShemrlyMushaf`` project records three damaged page layouts
verified against ``BOOK_27111_1.pdf``.  Pages 42 and 385 were circularly
ordered; page 496 retained the next surah number on the preceding surah's
lines.  Eight other rows used a non-existent numeric ID as their final word,
and page 516 contained an invisible ZWJ in its cached line text.

This migration preserves the stable Quran word IDs.  It is idempotent and
refuses to write when the expected page inventory or Quran endpoints drift.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYOUT = ROOT / "data" / "mushaf_layout_inferred.db"
DEFAULT_SCRIPT = ROOT / "data" / "quran_script.db"

PAGE_ORDERS = {
    42: [*range(9, 15), 1, 2, *range(3, 9)],
    385: [*range(9, 14), 14, 1, *range(2, 9)],
}

PAGE_SURAHS = {
    42: {**{line: 2 for line in range(9, 15)}, **{line: 3 for line in range(1, 9)}},
    385: {
        **{line: 38 for line in range(9, 14)},
        **{line: 39 for line in [14, 1, *range(2, 9)]},
    },
}

# (page, line): (expected first key, stale non-existent last ID,
#                corrected final word ID, corrected final key)
ENDPOINT_REPAIRS = {
    (193, 8): ("12:1:1", 31789, 31788, "12:2:5"),
    (205, 3): ("13:1:13", 33701, 33700, "13:2:7"),
    (206, 14): ("13:15:6", 33985, 33984, "13:16:3"),
    (216, 9): ("15:6:4", 35530, 35529, "15:7:5"),
    (225, 8): ("16:50:6", 36952, 36949, "16:51:11"),
    (243, 4): ("17:109:2", 39855, 39854, "17:110:6"),
    (506, 9): ("84:21:5", 82666, 82665, "84:23:3"),
    (515, 7): ("96:18:3", 83822, 83821, "96:19:6"),
}


def _word_key(cursor: sqlite3.Cursor, word_id: int) -> str | None:
    row = cursor.execute(
        "SELECT word_key FROM words WHERE word_index = ?", (int(word_id),)
    ).fetchone()
    return str(row[0]) if row else None


def _repair_page_order(
    cursor: sqlite3.Cursor,
    script_cursor: sqlite3.Cursor,
    page: int,
    original_order: list[int],
) -> int:
    rows = {
        int(row["line_number"]): row
        for row in cursor.execute(
            """
            SELECT id, line_number, line_type, surah_number,
                   first_word_id, last_word_id
            FROM pages WHERE page_number = ?
            """,
            (page,),
        )
    }
    if sorted(rows) != list(range(1, 15)):
        raise ValueError(f"Unexpected line inventory on Shemrly page {page}")

    repaired_signature = {
        42: ("2:285:15", 7),
        385: ("38:79:4", 6),
    }
    expected_first_key, expected_header_line = repaired_signature[page]
    first_key = _word_key(script_cursor, rows[1]["first_word_id"])
    if (
        first_key == expected_first_key
        and rows[expected_header_line]["line_type"] == "surah_name"
    ):
        return 0

    original_signature_ok = (
        (page == 42 and rows[1]["line_type"] == "surah_name"
         and _word_key(script_cursor, rows[9]["first_word_id"]) == expected_first_key)
        or
        (page == 385 and rows[14]["line_type"] == "surah_name"
         and _word_key(script_cursor, rows[9]["first_word_id"]) == expected_first_key)
    )
    if not original_signature_ok:
        raise ValueError(f"Page {page} is neither original nor already repaired")

    cursor.execute(
        "UPDATE pages SET line_number = -id WHERE page_number = ?", (page,)
    )
    updated = 0
    for new_line, old_line in enumerate(original_order, 1):
        row = rows[old_line]
        updated += cursor.execute(
            """
            UPDATE pages
            SET line_number = ?, surah_number = ?
            WHERE id = ?
            """,
            (new_line, PAGE_SURAHS[page][old_line], int(row["id"])),
        ).rowcount
    return updated


def repair_verified_pages(
    layout_database: str | Path = DEFAULT_LAYOUT,
    script_database: str | Path = DEFAULT_SCRIPT,
) -> dict[str, int]:
    layout = sqlite3.connect(str(layout_database))
    script = sqlite3.connect(f"file:{Path(script_database).resolve()}?mode=ro", uri=True)
    try:
        layout.row_factory = sqlite3.Row
        layout_cursor = layout.cursor()
        script_cursor = script.cursor()

        reordered = sum(
            _repair_page_order(layout_cursor, script_cursor, page, order)
            for page, order in PAGE_ORDERS.items()
        )

        page_496 = layout_cursor.execute(
            """
            SELECT line_number, first_word_id, last_word_id, surah_number
            FROM pages WHERE page_number = 496 ORDER BY line_number
            """
        ).fetchall()
        if len(page_496) != 14:
            raise ValueError("Unexpected line inventory on Shemrly page 496")
        for row in page_496[:13]:
            if (
                _word_key(script_cursor, row["first_word_id"]) or ""
            ).split(":", 1)[0] != "76":
                raise ValueError("Page 496 no longer has the verified surah 76 spans")
        metadata_updated = layout_cursor.execute(
            """
            UPDATE pages SET surah_number = 76
            WHERE page_number = 496 AND line_number BETWEEN 1 AND 13
              AND surah_number != 76
            """
        ).rowcount

        endpoints_updated = 0
        for (page, line), (first_key, stale_last, new_last, new_key) in ENDPOINT_REPAIRS.items():
            row = layout_cursor.execute(
                """
                SELECT first_word_id, last_word_id FROM pages
                WHERE page_number = ? AND line_number = ? AND line_type = 'ayah'
                """,
                (page, line),
            ).fetchone()
            if row is None or _word_key(script_cursor, row["first_word_id"]) != first_key:
                raise ValueError(f"Unexpected Shemrly span start at page {page}, line {line}")
            if _word_key(script_cursor, new_last) != new_key:
                raise ValueError(f"Corrected Quran endpoint drifted at page {page}, line {line}")
            current_last = int(row["last_word_id"])
            if current_last == new_last:
                continue
            if current_last != stale_last or _word_key(script_cursor, stale_last) is not None:
                raise ValueError(f"Unexpected Shemrly span end at page {page}, line {line}")
            endpoints_updated += layout_cursor.execute(
                """
                UPDATE pages SET last_word_id = ?
                WHERE page_number = ? AND line_number = ?
                """,
                (new_last, page, line),
            ).rowcount

        zwj_updated = layout_cursor.execute(
            """
            UPDATE pages SET line_text = REPLACE(line_text, char(8205), '')
            WHERE page_number = 516 AND line_number = 4
              AND instr(line_text, char(8205)) > 0
            """
        ).rowcount

        layout.commit()
        return {
            "page_rows_reordered": reordered,
            "surah_metadata_updated": metadata_updated,
            "endpoints_updated": endpoints_updated,
            "zwj_rows_cleaned": zwj_updated,
        }
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
    result = repair_verified_pages(args.layout, args.script)
    print("Shemrly verified-page repair complete:", result)


if __name__ == "__main__":
    main()
