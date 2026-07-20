#!/usr/bin/env python3
"""
build_indopak_waqf.py
----------------------
Extracts all waqf/pause symbols from the IndoPak Nastaleeq Quran text
(QUL_data/indopak-nastaleeq 2.json) and writes them as a new column
"الهندي" in QUL_data/mushaf_waqf.db — making IndoPak waqf available
in the mushaf version selector alongside المدينة / الأزهر / الشمرلي / ورش.

IndoPak waqf symbol inventory
──────────────────────────────
Standalone (space-separated) tokens found between words.
Traditional IndoPak letter names ↔ Unicode marks stored in DB:

  ؕ  U+0615  ARABIC SMALL HIGH TAH        → ط  مطلق   (absolute stop; IndoPak-only)
  ؗ  U+0617  ARABIC SMALL HIGH ZAIN       → ز  مجوَّز  (permitted for a reason)
  ۘ  U+06D8  ARABIC SMALL HIGH MEEM       → م  لازم   (mandatory)
  ۚ  U+06DA  ARABIC SMALL HIGH JEEM       → ج         (permitted stop)
  ۙ  U+06D9  ARABIC SMALL HIGH LAM ALEF   → لا        (no-stop)
  ۖ  U+06D6  ...SAD WITH LAM              → ص  مرخّص  (licensed for necessity)
  ۗ  U+06D7  ...QAF WITH LAM              → قلى       (prefer stop)
  ۛ  U+06DB  ARABIC SMALL HIGH THREE DOTS → ع         (muʿānaqah)

  ۟  U+06DF  ROUNDED ZERO                 = verse-end marker (not a waqf stop — SKIPPED)
  ۠  U+06E0  RECTANGULAR ZERO             = sajda/ruku marker (SKIPPED)
  Private Use Area U+F500–U+F6FF          = font ligatures for verse numbers (SKIPPED)

Usage:
  python pipeline/build_indopak_waqf.py
  python pipeline/build_indopak_waqf.py --dry-run
  python pipeline/build_indopak_waqf.py --reset
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

BASE            = Path(__file__).parent.parent
INDOPAK_JSON    = BASE / "QUL_data/indopak-nastaleeq 2.json"
MUSHAF_WAQF_DB  = BASE / "QUL_data/mushaf_waqf.db"
QURAN_SCRIPT_DB = BASE / "QUL_data/quran_script.db"
SURAHS_JSON     = BASE / "QUL_data/surahs.json"

INDOPAK_COL = "الهندي"

# ── Codepoint sets ────────────────────────────────────────────────────────────

# Standard waqf range + IndoPak-specific marks
WAQF_CPS = set(range(0x06D6, 0x06EE))   # U+06D6–U+06ED
WAQF_CPS |= {
    0x0615,  # ؕ  ط مطلق (absolute stop)
    0x0617,  # ؗ  ز مجوَّز
    0x0614,  # ؔ  takhallus / قف mark
    0x06EA,  # ۪  empty centre low stop
    0x06EB,  # ۫  empty centre high stop
    0x06EC,  # ۬  rounded high stop
}

# These appear in standalone tokens but are NOT waqf stop marks — skip them
SKIP_CPS = {
    0x06DF,  # ۟  rounded zero  = verse-end marker
    0x06E0,  # ۠  rectangular zero = sajda/ruku marker
}
SKIP_CPS |= set(range(0xF500, 0xF700))  # private-use font ligatures
SKIP_CPS |= {0xF61E, 0xF68F}

# Arabic base letters (including Urdu/Persian extensions)
ARABIC_BASE = (
    set(range(0x0621, 0x063B)) |
    set(range(0x0641, 0x064B)) |
    {0x06CC, 0x06A9, 0x06AF, 0x06BA, 0x06BE, 0x06C1, 0x06C3}
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_content_word(token: str) -> bool:
    """True if the token contains at least one Arabic base letter."""
    return any(ord(c) in ARABIC_BASE for c in token)


def extract_waqf_symbol(token: str) -> str | None:
    """Strip verse-end / private-use chars from a standalone waqf token.

    Returns the cleaned symbol string, or None if nothing remains after stripping.
    """
    cleaned = "".join(c for c in token if ord(c) not in SKIP_CPS)
    return cleaned.strip() or None


def load_sura_names(surahs_path: Path) -> dict[int, str]:
    with open(surahs_path, encoding="utf-8") as f:
        return {s["number"]: s["name"] for s in json.load(f)}


def ensure_column(conn: sqlite3.Connection, reset: bool) -> None:
    existing = [c[1] for c in conn.execute("PRAGMA table_info(waqf)").fetchall()]
    if INDOPAK_COL not in existing:
        conn.execute(f'ALTER TABLE waqf ADD COLUMN "{INDOPAK_COL}" TEXT')
        conn.commit()
        print(f"  Added column '{INDOPAK_COL}'")
    elif reset:
        conn.execute(f'UPDATE waqf SET "{INDOPAK_COL}" = NULL')
        conn.commit()
        print(f"  Reset existing '{INDOPAK_COL}' values")
    else:
        print(f"  Column '{INDOPAK_COL}' already exists — appending (use --reset to rebuild)")


def get_word_text(qs_cur: sqlite3.Cursor, sura: int, aya: int, pos: int) -> str:
    row = qs_cur.execute(
        "SELECT text FROM words WHERE word_key=?",
        (f"{sura}:{aya}:{pos}",)
    ).fetchone()
    return row[0] if row else ""


def place_symbol(
    waqf_cur: sqlite3.Cursor,
    qs_cur: sqlite3.Cursor,
    sura_names: dict,
    sura: int, aya: int, word_pos: int,
    symbol: str,
) -> None:
    """Insert/update a symbol at (sura, aya, word_pos) in mushaf_waqf.db."""
    row = waqf_cur.execute(
        f'SELECT rowid, "{INDOPAK_COL}" FROM waqf WHERE "السورة"=? AND "الآية"=? AND word_index=?',
        (sura, aya, word_pos),
    ).fetchone()

    if row:
        rowid, existing = row
        new_val = (existing + symbol) if (existing and existing != symbol) else symbol
        waqf_cur.execute(
            f'UPDATE waqf SET "{INDOPAK_COL}"=? WHERE rowid=?',
            (new_val, rowid),
        )
    else:
        word_text = get_word_text(qs_cur, sura, aya, word_pos)
        waqf_cur.execute(
            f"""INSERT INTO waqf
                ("السورة", "السورة.1", "الآية", "الكلمة", "{INDOPAK_COL}", word_index, token_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sura, sura_names.get(sura, ""), aya, word_text, symbol, word_pos, word_pos),
        )


# ── Main ─────────────────────────────────────────────────────────────────────

def build(dry_run: bool = False, reset: bool = False) -> None:
    print(f"Loading {INDOPAK_JSON.name} …")
    with open(INDOPAK_JSON, encoding="utf-8") as f:
        indopak = json.load(f)
    print(f"  {len(indopak):,} verses")

    if dry_run:
        print("\n=== DRY RUN — first 10 waqf finds ===")
        found = 0
        for vk, entry in sorted(indopak.items(),
                                  key=lambda x: (int(x[0].split(':')[0]), int(x[0].split(':')[1]))):
            sura, aya = map(int, vk.split(':'))
            tokens = entry.get('text', '').split()
            word_pos = 0
            for tok in tokens:
                if is_content_word(tok):
                    word_pos += 1
                elif sym := extract_waqf_symbol(tok):
                    print(f"  {vk} word {word_pos}: '{sym}' (raw={tok!r})")
                    found += 1
                    if found >= 10:
                        print("[DRY RUN] No changes written.")
                        return
        print("[DRY RUN] No changes written.")
        return

    sura_names = load_sura_names(SURAHS_JSON)
    waqf_conn  = sqlite3.connect(MUSHAF_WAQF_DB)
    qs_conn    = sqlite3.connect(QURAN_SCRIPT_DB)
    qs_cur     = qs_conn.cursor()
    waqf_cur   = waqf_conn.cursor()

    print(f"\nOpening {MUSHAF_WAQF_DB.name} …")
    ensure_column(waqf_conn, reset)

    total_placed = 0
    for vk, entry in sorted(indopak.items(),
                              key=lambda x: (int(x[0].split(':')[0]), int(x[0].split(':')[1]))):
        sura, aya = map(int, vk.split(':'))
        tokens = entry.get('text', '').split()

        word_pos = 0  # 1-based position matching quran_script.db word_key
        for tok in tokens:
            if is_content_word(tok):
                word_pos += 1
            elif sym := extract_waqf_symbol(tok):
                if word_pos > 0:
                    place_symbol(waqf_cur, qs_cur, sura_names, sura, aya, word_pos, sym)
                    total_placed += 1

        if sura == 1 and aya <= 3:  # progress sample
            print(f"  Sample {vk}: {tokens}")

    waqf_conn.commit()
    waqf_cur.close()
    qs_cur.close()
    waqf_conn.close()
    qs_conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    verify = sqlite3.connect(MUSHAF_WAQF_DB)
    total = verify.execute(
        f'SELECT COUNT(*) FROM waqf WHERE "{INDOPAK_COL}" IS NOT NULL'
    ).fetchone()[0]
    breakdown = verify.execute(
        f'SELECT "{INDOPAK_COL}", COUNT(*) FROM waqf '
        f'WHERE "{INDOPAK_COL}" IS NOT NULL GROUP BY "{INDOPAK_COL}" ORDER BY COUNT(*) DESC LIMIT 20'
    ).fetchall()
    verify.close()

    print(f"\n=== Done ===")
    print(f"Symbols placed during scan: {total_placed:,}")
    print(f"Total rows with '{INDOPAK_COL}': {total:,}")
    print("\nTop symbol breakdown:")
    for sym, cnt in breakdown:
        print(f"  {sym!r:<20} : {cnt:,}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build الهندي waqf column from IndoPak JSON")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.add_argument("--reset",   action="store_true", help="Clear existing symbols first")
    args = p.parse_args()
    build(dry_run=args.dry_run, reset=args.reset)
