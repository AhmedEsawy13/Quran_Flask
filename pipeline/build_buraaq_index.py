"""
build_buraaq_index.py
----------------------
Scans Buraaq/quran-md-ayahs HuggingFace parquet shards (metadata columns
only — no audio bytes downloaded) to build an absolute row-offset index for
مصطفى إسماعيل (reciter_id = "mostafa_ismail").

The Flask app uses this index to redirect audio requests to HuggingFace's
datasets-server signed CDN URLs — no local audio storage needed.

Usage:
    python3 pipeline/build_buraaq_index.py

Output:
    QUL_data/mustafa_ismaeel_row_index.json  — {"S:A": absolute_row_offset, ...}
    QUL_data/mustafa-ismaeel.json            — app reciter JSON with proxy URLs

Audio proxy URL (served by Flask):
    /api/audio/mustafa-ismaeel/<surah>/<ayah>
    → Flask looks up offset → calls HF rows API → 302 redirect to signed CDN URL

Dataset: https://huggingface.co/datasets/Buraaq/quran-md-ayahs
Reciter: mostafa_ismail  (Mostafa_Ismail_128kbps)
Shards:  0000.parquet … 0070.parquet  (71 total)
Total rows in split: 187,080  (30 reciters × 6,236 ayahs)
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fsspec
import pyarrow.parquet as pq

# ── Config ──────────────────────────────────────────────────────────────────
DATASET_REPO = "Buraaq/quran-md-ayahs"
BASE_URL = (
    "https://huggingface.co/datasets/Buraaq/quran-md-ayahs"
    "/resolve/refs%2Fconvert%2Fparquet/default/train"
)
RECITER_ID = "mostafa_ismail"
NUM_SHARDS = 71
META_COLS = ["reciter_id", "surah_id", "ayah_id"]

OUT_DIR = Path(__file__).parent.parent / "QUL_data"
INDEX_PATH = OUT_DIR / "mustafa_ismaeel_row_index.json"
JSON_PATH = OUT_DIR / "mustafa-ismaeel.json"

PROXY_BASE = "/api/audio/mustafa-ismaeel"

# ── Helpers ──────────────────────────────────────────────────────────────────

def scan_shard(shard_num: int) -> tuple[int, list[tuple[int, int, int]]]:
    """
    Read metadata columns for one shard.
    Returns (shard_num, [(local_row_index, surah_id, ayah_id), ...])
    for rows where reciter_id == RECITER_ID.
    """
    url = f"{BASE_URL}/{shard_num:04d}.parquet"
    fs = fsspec.filesystem("https", skip_instance_cache=True)
    rows = []
    local_offset = 0
    try:
        with fs.open(url, "rb", cache_type="bytes", block_size=2 ** 20) as f:
            pf = pq.ParquetFile(f)
            for rg in range(pf.num_row_groups):
                tbl = pf.read_row_group(rg, columns=META_COLS)
                df = tbl.to_pandas()
                for i, row in df.iterrows():
                    if row["reciter_id"] == RECITER_ID:
                        rows.append((local_offset + (i - df.index[0]), int(row["surah_id"]), int(row["ayah_id"])))
                local_offset += len(df)
    except Exception as exc:
        print(f"  [shard {shard_num:04d}] ERROR: {exc}")
    return shard_num, rows


def shard_row_count(shard_num: int) -> int:
    """Fast: just read parquet footer to get total row count for this shard."""
    url = f"{BASE_URL}/{shard_num:04d}.parquet"
    fs = fsspec.filesystem("https", skip_instance_cache=True)
    try:
        with fs.open(url, "rb", cache_type="bytes", block_size=2 ** 20) as f:
            pf = pq.ParquetFile(f)
            return pf.metadata.num_rows
    except Exception as exc:
        print(f"  [shard {shard_num:04d}] row count ERROR: {exc}")
        return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Scanning {NUM_SHARDS} parquet shards for reciter_id='{RECITER_ID}'")
    print("(Only metadata columns downloaded — no audio bytes)\n")

    # Step 1: Get total row counts per shard to compute cumulative offsets.
    # We need this before scanning because shards are processed in parallel.
    print("Step 1/3 — Fetching row counts for each shard…")
    shard_counts: list[int] = [0] * NUM_SHARDS
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(shard_row_count, i): i for i in range(NUM_SHARDS)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            shard_counts[i] = fut.result()
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{NUM_SHARDS} shards counted…")

    # Cumulative offsets: shard_start[i] = sum of row counts for shards 0..i-1
    shard_start: list[int] = [0] * NUM_SHARDS
    for i in range(1, NUM_SHARDS):
        shard_start[i] = shard_start[i - 1] + shard_counts[i - 1]

    total_rows = shard_start[-1] + shard_counts[-1]
    print(f"  Total rows in split: {total_rows:,}\n")

    # Step 2: Scan each shard for mostafa_ismail rows.
    print("Step 2/3 — Scanning shards for mostafa_ismail rows…")
    index: dict[str, int] = {}  # "S:A" → absolute_row_offset

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(scan_shard, i): i for i in range(NUM_SHARDS)}
        done = 0
        for fut in as_completed(futures):
            shard_num, local_rows = fut.result()
            abs_start = shard_start[shard_num]
            for (local_idx, surah, ayah) in local_rows:
                key = f"{surah}:{ayah}"
                index[key] = abs_start + local_idx
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{NUM_SHARDS} shards scanned…")

    print(f"  Found {len(index):,} entries for '{RECITER_ID}'\n")

    if not index:
        print("ERROR: No rows found. Check reciter_id and dataset access.")
        return

    # Step 3: Write outputs
    print("Step 3/3 — Writing output files…")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # row_index JSON
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Saved: {INDEX_PATH}")

    # reciter JSON for the app
    reciter_data: dict[str, dict] = {}
    for key, _offset in sorted(index.items(), key=lambda x: tuple(map(int, x[0].split(":")))):
        surah, ayah = key.split(":")
        reciter_data[key] = {
            "surah_number": int(surah),
            "ayah_number": int(ayah),
            "audio_url": f"{PROXY_BASE}/{surah}/{ayah}",
            "duration": None,
            "segments": [],
        }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(reciter_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {JSON_PATH} ({len(reciter_data):,} entries)")

    print("\nDone! Run the Flask app to serve audio via /api/audio/mustafa-ismaeel/<surah>/<ayah>")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
