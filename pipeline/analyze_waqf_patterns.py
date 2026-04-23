#!/usr/bin/env python3
"""
Analyze waqf (pause) patterns from waqf_positions.csv.

Each row in the output represents one waqf event (transition between two
consecutive audio segments for the same reciter+moshaf).

Four boolean columns classify each event:

  is_genuine_waqf  — reciter stopped mid-aya and resumed from the very next word
                     (وقف جائز: paused, no repetition, continued forward)

  is_repetition    — reciter stopped, went BACK to an earlier word in the same aya,
                     and re-read (وقف للإعادة: pause + repeat + continue)

  is_verse_done    — reciter stopped at the END of an aya; next segment starts at the
                     beginning of the following aya (وقف على رأس آية)

  is_more_verse    — a single segment spans two or more ayas, meaning the reciter
                     connected them without pausing at the aya boundary (الوصل)

These flags are NOT mutually exclusive:
  - is_more_verse can combine with any of the three transition flags.
  - is_genuine_waqf / is_repetition / is_verse_done are mutually exclusive with
    each other (they describe different transition types).

Usage (CLI):
  python analyze_waqf_patterns.py waqf_positions.csv
  python analyze_waqf_patterns.py waqf_positions.csv --output waqf_transitions.csv
  python analyze_waqf_patterns.py waqf_positions.csv --threshold 2

Kaggle / notebook:
  Edit the CONFIG block and run the file.
"""

# ── CONFIG ───────────────────────────────────────────────────────────────────
INPUT_FILE  = "mahmoud_khalil_al_husari_0_3_positions.db"  # .db or .csv from fetch_waqf_positions.py
OUTPUT_DIR  = "."                        # directory for output .db files (auto-named)
REPETITION_THRESHOLD = 2                 # min words overlap to count as repetition
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3
import argparse
from pathlib import Path
import pandas as pd


# ── Naming helpers (same logic as fetch_waqf_positions.py) ───────────────────



def save_to_db(df: pd.DataFrame, path: Path, table: str = "transitions") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    df.to_sql(table, conn, if_exists="replace", index=False)
    conn.close()


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(path: str) -> pd.DataFrame:
    """Load positions from a .db (SQLite table 'positions') or .csv file."""
    p = Path(path)
    if p.suffix.lower() == ".db":
        conn = sqlite3.connect(p)
        df = pd.read_sql("SELECT * FROM positions", conn)
        conn.close()
    else:
        df = pd.read_csv(p)

    df = df[df["has_quran"] == True].copy()
    df = df.dropna(subset=["start_sura", "start_aya", "start_word",
                            "end_sura",   "end_aya",   "end_word"])
    for col in ["start_sura", "start_aya", "start_word",
                "end_sura",   "end_aya",   "end_word",
                "reciter_id"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("segment_index").reset_index(drop=True)


# ── Transition classifier ─────────────────────────────────────────────────────

def classify(curr: pd.Series, nxt: pd.Series, threshold: int) -> dict:
    """
    Compare two consecutive segments and return classification flags.

    is_more_verse    — property of `curr` segment itself (spans multiple ayas)
    is_genuine_waqf  — transition: same aya, nxt starts exactly where curr ended
    is_repetition    — transition: same aya, nxt starts BEFORE where curr ended
    is_verse_done    — transition: nxt starts at the beginning of the next aya
    """
    # ── is_more_verse: current segment spans more than one aya ───────────────
    is_more_verse = (
        curr["start_sura"] != curr["end_sura"] or
        curr["start_aya"]  != curr["end_aya"]
    )

    cs, ca, cw = int(curr["end_sura"]),  int(curr["end_aya"]),  int(curr["end_word"])
    ns, na, nw = int(nxt["start_sura"]), int(nxt["start_aya"]), int(nxt["start_word"])

    is_genuine_waqf = False
    is_repetition   = False
    is_verse_done   = False
    overlap_words   = 0

    same_sura = (cs == ns)
    same_aya  = same_sura and (ca == na)

    if same_aya:
        overlap_words = cw - nw          # positive = went back, 0 = exact, negative = gap
        if nw == cw:
            # Stopped at word W, resumed at word W — exact forward continuation
            is_genuine_waqf = True
        elif nw < cw and (cw - nw) >= threshold:
            # Went back by at least `threshold` words → repetition
            is_repetition = True
        elif nw == 0 and cw > 0:
            # Full aya restart (word 0 again) → repetition regardless of threshold
            is_repetition = True

    elif same_sura and na == ca + 1 and nw == 0:
        # Moved cleanly to the first word of the very next aya
        is_verse_done = True

    elif not same_sura and ns == cs + 1 and nw == 0:
        # Crossed a sura boundary cleanly (end of last aya of sura)
        is_verse_done = True

    return {
        "is_genuine_waqf": is_genuine_waqf,
        "is_repetition":   is_repetition,
        "is_verse_done":   is_verse_done,
        "is_more_verse":   is_more_verse,
        "overlap_words":   overlap_words,
        # Human-readable summary
        "waqf_type": (
            "repetition"   if is_repetition   else
            "verse_done"   if is_verse_done   else
            "genuine_waqf" if is_genuine_waqf else
            "other"
        ),
    }


# ── Main analysis ─────────────────────────────────────────────────────────────

def analyze(df: pd.DataFrame, threshold: int) -> pd.DataFrame:
    records = []

    for (reciter_id, moshaf_id), group in df.groupby(["reciter_id", "moshaf_id"]):
        group = group.sort_values("segment_index").reset_index(drop=True)

        for i in range(len(group) - 1):
            curr = group.iloc[i]
            nxt  = group.iloc[i + 1]
            flags = classify(curr, nxt, threshold)

            records.append({
                # Identity
                "reciter_id":       reciter_id,
                "reciter_name_ar":  curr.get("reciter_name_ar", ""),
                "reciter_name_en":  curr.get("reciter_name_en", ""),
                "moshaf_id":        moshaf_id,

                # Waqf type flags
                "waqf_type":        flags["waqf_type"],
                "is_genuine_waqf":  flags["is_genuine_waqf"],
                "is_repetition":    flags["is_repetition"],
                "is_verse_done":    flags["is_verse_done"],
                "is_more_verse":    flags["is_more_verse"],
                "overlap_words":    flags["overlap_words"],

                # Where the waqf occurs (end of current segment)
                "waqf_sura":        curr["end_sura"],
                "waqf_aya":         curr["end_aya"],
                "waqf_word":        curr["end_word"],

                # Where the reciter resumes (start of next segment)
                "resume_sura":      nxt["start_sura"],
                "resume_aya":       nxt["start_aya"],
                "resume_word":      nxt["start_word"],

                # Segment references
                "seg_before":       curr["segment_index"],
                "seg_after":        nxt["segment_index"],

                # Text on both sides of the waqf
                "text_before":      curr.get("transcript", ""),
                "text_after":       nxt.get("transcript", ""),

                # Audio durations
                "dur_before":       curr.get("duration_seconds"),
                "dur_after":        nxt.get("duration_seconds"),
            })

    return pd.DataFrame(records)


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame, threshold: int) -> None:
    total = len(df)
    print("\n=== Waqf Pattern Summary ===")
    print(f"Total waqf events        : {total:,}")
    print(f"Repetition threshold     : {threshold} words\n")

    counts = {
        "Genuine waqf (mid-aya, forward)  [is_genuine_waqf]": df["is_genuine_waqf"].sum(),
        "Repetition (went back, re-read)  [is_repetition]  ": df["is_repetition"].sum(),
        "Verse-end waqf (رأس آية)         [is_verse_done]  ": df["is_verse_done"].sum(),
        "Connected verses (وصل)           [is_more_verse]  ": df["is_more_verse"].sum(),
        "Other (skip / cross-sura gap)                     ": (df["waqf_type"] == "other").sum(),
    }
    for label, n in counts.items():
        pct = 100 * n / total if total else 0
        print(f"  {label}: {int(n):>6,}  ({pct:.1f}%)")

    reps = df[df["is_repetition"]]
    if not reps.empty:
        print(f"\nTop 10 suras with most repetitions:")
        top = reps.groupby("waqf_sura").size().sort_values(ascending=False).head(10)
        for sura, cnt in top.items():
            print(f"  Sura {int(sura):>3}: {cnt:>4,}")
        print(f"\nMean overlap on repetitions : {reps['overlap_words'].mean():.1f} words")
        print(f"Max  overlap on repetitions : {int(reps['overlap_words'].max())} words")


# ── Entry points ──────────────────────────────────────────────────────────────

def _is_notebook() -> bool:
    try:
        shell = get_ipython().__class__.__name__  # type: ignore[name-defined]
        return shell in ("ZMQInteractiveShell", "TerminalInteractiveShell")
    except NameError:
        return False


def run(input_file: str, output_dir: str, threshold: int) -> pd.DataFrame:
    print(f"Loading {input_file} …")
    df = load_data(input_file)
    print(f"  {len(df):,} Quran segments, "
          f"{df['reciter_id'].nunique()} reciter(s), "
          f"{df['moshaf_id'].nunique()} moshaf(s)")

    print("Classifying waqf transitions …")
    transitions = analyze(df, threshold)

    # Derive output name from input filename: husary_0_0_positions.db → husary_0_0_transitions.db
    input_stem = Path(input_file).stem.replace("_positions", "")
    base = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    out  = base / f"{input_stem}_transitions.db"
    save_to_db(transitions, out, table="transitions")
    print(f"Saved → {out}  ({len(transitions):,} rows)")

    print_summary(transitions, threshold)
    return transitions


if _is_notebook():
    transitions = run(INPUT_FILE, OUTPUT_DIR, REPETITION_THRESHOLD)
elif __name__ == "__main__":
    p = argparse.ArgumentParser(description="Classify waqf patterns from positions DB/CSV")
    p.add_argument("input",        nargs="?", default=INPUT_FILE)
    p.add_argument("--output-dir", default=OUTPUT_DIR, help="Directory for output .db file")
    p.add_argument("--threshold",  type=int,  default=REPETITION_THRESHOLD,
                   help="Min word overlap to count as repetition (default: 2)")
    args = p.parse_args()
    run(args.input, args.output_dir, args.threshold)
