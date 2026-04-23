#!/usr/bin/env python3
"""
Build the Husary waqf column in QUL_data/mushaf_waqf.db.

Reads reciters/husary/transitions.db and writes a 'الحصري' column into the
existing waqf table alongside المدينة / الأزهر / الشمرلي / ورش.

Symbols used:
  ج   — genuine mid-aya waqf (is_genuine_waqf)     وقف جائز
  ↺   — stop for repetition  (is_repetition, stop word)   وقف إعادة
  ▶   — start of repetition  (is_repetition, resume word)  بداية الإعادة

Word-index mapping:
  waqf_word and resume_word in transitions.db come from the HuggingFace dataset
  which may split words differently from quran_script.db (e.g. "يَا أَيُّهَا"
  is one token in quran_script but two in the transcript).  Raw numeric mapping
  therefore drifts.  We instead match by the last/first word TEXT of the
  transcript segments and look that up in quran_script.db via normalised Arabic,
  using the numeric value only as a fallback hint for disambiguation.

Usage:
  python pipeline/build_husary_mushaf.py              # run
  python pipeline/build_husary_mushaf.py --dry-run    # preview only
  python pipeline/build_husary_mushaf.py --reset      # clear and rebuild
"""

import json
import re
import sqlite3
import argparse
from pathlib import Path

import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
BASE            = Path(__file__).parent.parent
TRANSITIONS_DB  = BASE / "reciters/husary/transitions.db"
POSITIONS_DB    = BASE / "reciters/husary/positions.db"
MUSHAF_WAQF_DB  = BASE / "QUL_data/mushaf_waqf.db"
QURAN_SCRIPT_DB = BASE / "QUL_data/quran_script.db"
SURAHS_JSON     = BASE / "QUL_data/surahs.json"

# ── Symbols ───────────────────────────────────────────────────────────────────
SYM_GENUINE_WAQF = "ج"
SYM_STOP_REPEAT  = "↺"
SYM_START_REPEAT = "▶"
HUSARY_COL       = "الحصري"

# ── Arabic normalisation ──────────────────────────────────────────────────────
_DIACRITICS = re.compile(
    r'[ً-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ]'
)

def _norm(text: str) -> str:
    """Strip diacritics and normalise alef/taa variants for fuzzy matching."""
    text = _DIACRITICS.sub('', text)
    text = re.sub(r'[أإآٱ]', 'ا', text)
    text = text.replace('ة', 'ه')
    text = text.replace('ى', 'ي')
    text = text.replace('ـ', '')   # tatweel
    return text.strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_sura_names() -> dict[int, str]:
    with open(SURAHS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {s["number"]: s["name"] for s in data}


def load_uthmani_lookup() -> dict[str, str]:
    """Map segment_index → uthmani_text from positions.db."""
    conn = sqlite3.connect(POSITIONS_DB)
    rows = conn.execute("SELECT segment_index, uthmani_text FROM positions").fetchall()
    conn.close()
    return {seg: text or "" for seg, text in rows}


def get_word_text(qs_cur: sqlite3.Cursor, sura: int, aya: int, word_pos: int) -> str:
    """Fetch Arabic word text from quran_script.db by 1-based position."""
    row = qs_cur.execute(
        "SELECT text FROM words WHERE word_key=?",
        (f"{sura}:{aya}:{word_pos}",)
    ).fetchone()
    return row[0] if row else ""


def find_word_pos(
    qs_cur: sqlite3.Cursor,
    sura: int, aya: int,
    word_text: str,
    approx: int,
) -> tuple[int, bool]:
    """
    Return (1-based word position, matched) where matched=True means a text
    match was found.  When multiple words match, pick the one closest to approx.
    Returns (approx, False) if nothing matches.
    """
    rows = qs_cur.execute(
        "SELECT word_key, text FROM words WHERE surah=? AND ayah=? ORDER BY word_key",
        (sura, aya),
    ).fetchall()

    target = _norm(word_text)
    candidates: list[int] = []

    for word_key, text in rows:
        pos = int(word_key.split(':')[2])
        if _norm(text) == target:
            candidates.append(pos)

    if not candidates:
        # Partial / containment fallback for slight orthography differences
        for word_key, text in rows:
            pos = int(word_key.split(':')[2])
            n = _norm(text)
            if target and (target in n or n in target):
                candidates.append(pos)

    if not candidates:
        return approx, False

    return min(candidates, key=lambda p: abs(p - approx)), True


def ensure_column(conn: sqlite3.Connection, reset: bool) -> None:
    existing = [c[1] for c in conn.execute("PRAGMA table_info(waqf)").fetchall()]
    if HUSARY_COL not in existing:
        conn.execute(f'ALTER TABLE waqf ADD COLUMN "{HUSARY_COL}" TEXT')
        conn.commit()
        print(f"  Added column '{HUSARY_COL}'")
    elif reset:
        conn.execute(f'UPDATE waqf SET "{HUSARY_COL}" = NULL')
        conn.commit()
        print(f"  Reset existing '{HUSARY_COL}' values")
    else:
        print(f"  Column '{HUSARY_COL}' already exists — appending (use --reset to rebuild)")


def place_symbol(
    waqf_cur: sqlite3.Cursor,
    qs_cur: sqlite3.Cursor,
    sura_names: dict,
    sura: int, aya: int, word_pos: int,
    symbol: str,
) -> None:
    """
    Insert or update a Husary waqf symbol on (sura, aya, word_pos).
    word_pos is 1-based — same scale as word_index in mushaf_waqf.db.
    """
    row = waqf_cur.execute(
        f'SELECT rowid, "{HUSARY_COL}" FROM waqf WHERE السورة=? AND الآية=? AND word_index=?',
        (sura, aya, word_pos),
    ).fetchone()

    if row:
        rowid, existing = row
        if existing and existing != symbol:
            new_val = existing + symbol
        else:
            new_val = symbol
        waqf_cur.execute(
            f'UPDATE waqf SET "{HUSARY_COL}"=? WHERE rowid=?',
            (new_val, rowid),
        )
    else:
        word_text = get_word_text(qs_cur, sura, aya, word_pos)
        waqf_cur.execute(
            f"""INSERT INTO waqf
                (السورة, "السورة.1", الآية, الكلمة, "{HUSARY_COL}", word_index, token_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sura, sura_names.get(sura, ""), aya, word_text, symbol, word_pos, word_pos),
        )


def _last_word(text: str) -> str:
    parts = (text or "").split()
    return parts[-1] if parts else ""


def _first_word(text: str) -> str:
    parts = (text or "").split()
    return parts[0] if parts else ""


# ── Main build ────────────────────────────────────────────────────────────────

def build(dry_run: bool = False, reset: bool = False) -> None:
    print(f"Loading {TRANSITIONS_DB.name} …")
    tconn = sqlite3.connect(TRANSITIONS_DB)
    df = pd.read_sql("SELECT * FROM transitions", tconn)
    tconn.close()

    genuine  = df[df["is_genuine_waqf"] == 1]
    reps     = df[df["is_repetition"]   == 1]
    # overlap_words=1 transitions: reciter re-reads the boundary word before continuing.
    # These are waqf_type='other' rows where overlap_words >= 1.
    overlaps = df[(df["is_repetition"] == 0) & (df["is_genuine_waqf"] == 0) & (df["overlap_words"] >= 1)]

    print(f"  {len(df):,} total transitions")
    print(f"  {len(genuine):,} genuine waqf       (ج)")
    print(f"  {len(reps):,} repetitions         (↺ stop + ▶ resume)")
    print(f"  {len(overlaps):,} word-boundary repeats (↺ + ▶ on same word)\n")

    if dry_run:
        print("=== DRY RUN — first 5 genuine waqf ===")
        print(genuine[["waqf_sura", "waqf_aya", "waqf_word", "text_before"]].head().to_string())
        print("\n=== first 5 repetitions ===")
        print(reps[["waqf_sura", "waqf_aya", "waqf_word", "resume_sura", "resume_aya",
                     "resume_word", "overlap_words", "text_before"]].head().to_string())
        print("\n=== first 5 word-boundary repeats ===")
        print(overlaps[["waqf_sura", "waqf_aya", "waqf_word", "resume_word", "text_before"]].head().to_string())
        print("\n[DRY RUN] No changes written.")
        return

    sura_names    = load_sura_names()
    uthmani_index = load_uthmani_lookup()
    waqf_conn  = sqlite3.connect(MUSHAF_WAQF_DB)
    qs_conn    = sqlite3.connect(QURAN_SCRIPT_DB)
    qs_cur     = qs_conn.cursor()
    waqf_cur   = waqf_conn.cursor()

    print(f"Opening {MUSHAF_WAQF_DB.name} …")
    ensure_column(waqf_conn, reset)

    # ── Genuine waqf → ج ────────────────────────────────────────────────────
    print(f"\nWriting {len(genuine):,} genuine waqf symbols (ج) …")
    misses = 0
    for _, row in genuine.iterrows():
        sura = int(row["waqf_sura"])
        aya  = int(row["waqf_aya"])
        u_text = uthmani_index.get(str(row["seg_before"]), "")
        last   = _last_word(u_text)
        approx = int(row["waqf_word"])
        if last:
            pos, matched = find_word_pos(qs_cur, sura, aya, last, approx)
            if not matched:
                misses += 1
        else:
            pos = approx
        place_symbol(waqf_cur, qs_cur, sura_names, sura, aya, pos, SYM_GENUINE_WAQF)
    waqf_conn.commit()
    if misses:
        print(f"  ({misses} fallback to raw index — no text match)")

    # ── Repetitions → ↺ at stop word, ▶ at resume word ──────────────────────
    print(f"Writing {len(reps):,} repetition symbols (↺ / ▶) …")
    misses = 0
    for _, row in reps.iterrows():
        sura = int(row["waqf_sura"])
        aya  = int(row["waqf_aya"])

        # ↺ stop: last word of the segment's uthmani_text
        u_before = uthmani_index.get(str(row["seg_before"]), "")
        last     = _last_word(u_before)
        approx_stop = int(row["waqf_word"])
        if last:
            stop_pos, m = find_word_pos(qs_cur, sura, aya, last, approx_stop)
            if not m: misses += 1
        else:
            stop_pos = approx_stop
        place_symbol(waqf_cur, qs_cur, sura_names, sura, aya, stop_pos, SYM_STOP_REPEAT)

        # ▶ resume: first word of the next segment's uthmani_text
        u_after = uthmani_index.get(str(row["seg_after"]), "")
        first   = _first_word(u_after)
        r_sura  = int(row["resume_sura"])
        r_aya   = int(row["resume_aya"])
        approx_resume = int(row["resume_word"]) + 1
        if first:
            resume_pos, m = find_word_pos(qs_cur, r_sura, r_aya, first, approx_resume)
            if not m: misses += 1
        else:
            resume_pos = approx_resume
        place_symbol(waqf_cur, qs_cur, sura_names, r_sura, r_aya, resume_pos, SYM_START_REPEAT)

    waqf_conn.commit()
    if misses:
        print(f"  ({misses} fallback to raw index — no text match)")

    # ── Word-boundary repeats → ↺ at stop word, ▶ at resume word (often same word) ──
    print(f"Writing {len(overlaps):,} word-boundary repeat symbols (↺ / ▶) …")
    misses = 0
    for _, row in overlaps.iterrows():
        sura = int(row["waqf_sura"])
        aya  = int(row["waqf_aya"])

        # ↺ stop: last word of seg_before's uthmani_text
        u_before = uthmani_index.get(str(row["seg_before"]), "")
        last     = _last_word(u_before)
        approx_stop = int(row["waqf_word"])
        if last:
            stop_pos, m = find_word_pos(qs_cur, sura, aya, last, approx_stop)
            if not m: misses += 1
        else:
            stop_pos = approx_stop
        place_symbol(waqf_cur, qs_cur, sura_names, sura, aya, stop_pos, SYM_STOP_REPEAT)

        # ▶ resume: first word of seg_after's uthmani_text
        u_after = uthmani_index.get(str(row["seg_after"]), "")
        first   = _first_word(u_after)
        r_sura  = int(row["resume_sura"])
        r_aya   = int(row["resume_aya"])
        approx_resume = int(row["resume_word"]) + 1
        if first:
            resume_pos, m = find_word_pos(qs_cur, r_sura, r_aya, first, approx_resume)
            if not m: misses += 1
        else:
            resume_pos = approx_resume
        place_symbol(waqf_cur, qs_cur, sura_names, r_sura, r_aya, resume_pos, SYM_START_REPEAT)

    waqf_conn.commit()
    if misses:
        print(f"  ({misses} fallback to raw index — no text match)")

    waqf_cur.close()
    qs_cur.close()
    waqf_conn.close()
    qs_conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    verify = sqlite3.connect(MUSHAF_WAQF_DB)
    total = verify.execute(
        f'SELECT COUNT(*) FROM waqf WHERE "{HUSARY_COL}" IS NOT NULL'
    ).fetchone()[0]
    breakdown = verify.execute(
        f'SELECT "{HUSARY_COL}", COUNT(*) FROM waqf '
        f'WHERE "{HUSARY_COL}" IS NOT NULL GROUP BY "{HUSARY_COL}" ORDER BY COUNT(*) DESC'
    ).fetchall()
    verify.close()

    print(f"\n=== Done ===")
    print(f"Total words with '{HUSARY_COL}' symbol: {total:,}")
    for sym, cnt in breakdown:
        label = {"ج": "genuine waqf", "↺": "stop-repeat", "▶": "start-repeat"}.get(sym, sym)
        print(f"  {sym}  {label:<20}: {cnt:,}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build الحصري waqf column from Husary transitions")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.add_argument("--reset",   action="store_true", help="Clear existing Husary symbols first")
    args = p.parse_args()
    build(dry_run=args.dry_run, reset=args.reset)
