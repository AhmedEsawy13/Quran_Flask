#!/usr/bin/env python3
"""
Add per-line width data from DigitalKhatt's precomputed madina.json layout
into digital-khatt-15-lines.db.

Two new columns are added to the `pages` table:
  total_advance  INTEGER  — line content width in font units (sum of glyph
                            x_advance values, i.e. the pre-justified line width)
  x_offset       INTEGER  — left indent in font units for centered/special lines
                            (0 for normal justified ayah lines)

Source data:
  https://raw.githubusercontent.com/DigitalKhatt/digitalkhatt.org/master/
  ClientApp/src/assets/layouts/madina.json

Both 'digital_khatt' (New Madina 1441H) and 'old_madina' (Old Madina 1405H)
share the same 604-page / 15-line-per-page layout structure, so the same
total_advance values apply to both fonts.

Usage:
  python pipeline/add_line_widths.py             # download fresh copy
  python pipeline/add_line_widths.py --cached    # use /tmp/madina_layout.json
  python pipeline/add_line_widths.py --dry-run   # show stats, no DB changes
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request

LAYOUT_URL = (
    "https://raw.githubusercontent.com/DigitalKhatt/digitalkhatt.org"
    "/master/ClientApp/src/assets/layouts/madina.json"
)
CACHE_PATH = "/tmp/madina_layout.json"
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "digital-khatt-15-lines.db",
)


def fetch_layout(use_cache: bool) -> dict:
    if use_cache and os.path.exists(CACHE_PATH):
        print(f"Using cached layout: {CACHE_PATH}")
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    print(f"Downloading layout from {LAYOUT_URL} ...")
    with urllib.request.urlopen(LAYOUT_URL, timeout=60) as resp:
        raw = resp.read()
    data = json.loads(raw)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Saved to {CACHE_PATH}")
    return data


def compute_line_widths(layout_data: dict) -> dict:
    """
    Returns dict keyed by (page_number, line_number) → (total_advance, x_offset).
    page_number and line_number are 1-based (matching the DB).
    """
    result = {}
    for page_idx, page in enumerate(layout_data["pages"]):
        page_number = page_idx + 1  # DB is 1-based
        for line_idx, line in enumerate(page["lines"]):
            line_number = line_idx + 1  # DB is 1-based
            total_advance = sum(g.get("x_advance", 0) for g in line.get("glyphs", []))
            x_offset = line.get("x", 0)
            result[(page_number, line_number)] = (total_advance, x_offset)
    return result


def add_columns_if_missing(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
    if "total_advance" not in existing:
        conn.execute("ALTER TABLE pages ADD COLUMN total_advance INTEGER")
        print("Added column: total_advance")
    else:
        print("Column already exists: total_advance")
    if "x_offset" not in existing:
        conn.execute("ALTER TABLE pages ADD COLUMN x_offset INTEGER DEFAULT 0")
        print("Added column: x_offset")
    else:
        print("Column already exists: x_offset")


def main():
    parser = argparse.ArgumentParser(description="Add line width data to digital-khatt-15-lines.db")
    parser.add_argument("--cached", action="store_true", help="Use cached /tmp/madina_layout.json")
    parser.add_argument("--dry-run", action="store_true", help="Show stats only, no DB changes")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    layout_data = fetch_layout(use_cache=args.cached)
    widths = compute_line_widths(layout_data)

    json_pages = len(layout_data["pages"])
    json_lines = len(widths)
    print(f"\nLayout: {json_pages} pages, {json_lines} total lines")

    # Stats on justified lines (x_offset == 0)
    justified = [v[0] for v in widths.values() if v[1] == 0]
    if justified:
        import statistics
        print(f"Justified line total_advance — min: {min(justified)}, max: {max(justified)}, "
              f"median: {statistics.median(justified):.0f}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        add_columns_if_missing(conn)

        # Load DB rows to cross-check
        db_rows = conn.execute(
            "SELECT page_number, line_number FROM pages ORDER BY page_number, line_number"
        ).fetchall()
        print(f"\nDB rows: {len(db_rows)}")

        missing = [(p, l) for (p, l) in db_rows if (p, l) not in widths]
        if missing:
            print(f"WARNING: {len(missing)} DB rows have no matching JSON entry (e.g. {missing[:3]})")

        updates = [
            (widths[(p, l)][0], widths[(p, l)][1], p, l)
            for (p, l) in db_rows
            if (p, l) in widths
        ]
        conn.executemany(
            "UPDATE pages SET total_advance = ?, x_offset = ? WHERE page_number = ? AND line_number = ?",
            updates,
        )
        conn.commit()
        print(f"Updated {len(updates)} rows.")

        # Verify
        null_count = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE total_advance IS NULL"
        ).fetchone()[0]
        print(f"Rows still NULL total_advance: {null_count}")
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
