"""
build_tadabur_alignments.py
----------------------------
Reads the Tadabur HuggingFace parquet shards in parallel (metadata columns
only — no audio bytes downloaded) and builds audio JSON files for the app.

Usage:
    python3 pipeline/build_tadabur_alignments.py

Output:
    QUL_data/ibrahim-al-akhdar.json
    QUL_data/ayman-rushdi-suwaid.json

Audio CDN:
    Ibrahim Al-Akhdar → https://everyayah.com/data/Ibrahim_Akhdar_32kbps/SSSAAA.mp3
    Ayman Suwaid      → https://everyayah.com/data/Ayman_Sowaid_64kbps/SSSAAA.mp3

Tadabur reciter IDs (from sheikh_dict.json):
    إبراهيم الأخضر = 240
    أيمن سويد      = 661

Parquet schema: audio, reciter_id, surah_id, ayah_id, text_ar_*, ayah_duration_s, metadata
  - metadata: JSON string containing word_alignments, reciter_id, surah_id, ayah_id
  - word_alignments: [{"word": str, "start": float, "end": float}, ...]  (seconds)

Segment format used by the app (same as AbdulBaset / Tablawi):
    [start_word_0based, end_word_0based+1, start_ms, end_ms]
    e.g. word 0 at 0.0–0.62s → [0, 1, 0, 620]

Tadabur surah_id is 0-based (الفاتحة = 0) → app surah_number = surah_id + 1
"""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fsspec
import pyarrow.parquet as pq

# ── Config ────────────────────────────────────────────────────────────────────

TARGET_RECITER_IDS = {240, 661, 145, 61}

RECITERS = [
    {
        "name_ar":      "إبراهيم الأخضر",
        "name_en":      "Ibrahim Al-Akhdar",
        "tadabur_id":   240,
        "audio_url_fn": lambda s, a: f"https://everyayah.com/data/Ibrahim_Akhdar_32kbps/{s:03d}{a:03d}.mp3",
        "output_file":  "QUL_data/ibrahim-al-akhdar.json",
    },
    {
        "name_ar":      "أيمن رشدي سويد",
        "name_en":      "Ayman Rushdi Suwaid",
        "tadabur_id":   661,
        "audio_url_fn": lambda s, a: f"https://everyayah.com/data/Ayman_Sowaid_64kbps/{s:03d}{a:03d}.mp3",
        "output_file":  "QUL_data/ayman-rushdi-suwaid.json",
    },
    {
        "name_ar":      "محمود علي البنا",
        "name_en":      "Mahmoud Ali Al-Banna",
        "tadabur_id":   145,
        "audio_url_fn": lambda s, a: f"https://everyayah.com/data/mahmoud_ali_al_banna_32kbps/{s:03d}{a:03d}.mp3",
        "output_file":  "QUL_data/mahmoud-ali-al-banna.json",
    },
    {
        "name_ar":      "مصطفى إسماعيل",
        "name_en":      "Mustafa Ismaeel",
        "tadabur_id":   61,
        "audio_url_fn": lambda s, a: f"https://everyayah.com/data/Mustafa_Ismail_48kbps/{s:03d}{a:03d}.mp3",
        "output_file":  "QUL_data/mustafa-ismaeel.json",
    },
]

OUTPUT_DIR    = Path(__file__).parent.parent   # repo root
MAX_WORKERS   = 20                              # parallel shard fetches
READ_COLS     = ["reciter_id", "surah_id", "ayah_id", "ayah_duration_s", "metadata"]

PARQUET_BASE  = (
    "https://huggingface.co/datasets/FaisaI/tadabur/resolve/"
    "refs%2Fconvert%2Fparquet/default/train"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_shard_urls() -> list[str]:
    """Fetch the authoritative list of train shard URLs from the HF datasets-server."""
    api = "https://datasets-server.huggingface.co/parquet?dataset=FaisaI/tadabur"
    req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return [
        f["url"]
        for f in data.get("parquet_files", [])
        if f.get("config") == "default" and f.get("split") == "train"
    ]


def word_alignments_to_segments(word_alignments: list) -> list:
    """[{word, start, end}, …] (seconds) → [[idx, idx+1, start_ms, end_ms], …]"""
    out = []
    for i, wa in enumerate(word_alignments):
        if not isinstance(wa, dict):
            continue
        out.append([i, i + 1,
                    round((wa.get("start") or 0) * 1000),
                    round((wa.get("end")   or 0) * 1000)])
    return out


def process_shard(url: str) -> list[dict]:
    """
    Open one parquet shard via HTTP Range requests (no audio bytes downloaded),
    read metadata columns, return rows for our target reciters only.
    """
    results = []
    try:
        fs = fsspec.filesystem("https", skip_instance_cache=True)
        with fs.open(url, "rb", cache_type="bytes", block_size=2**20) as f:
            pf = pq.ParquetFile(f)
            for rg in range(pf.metadata.num_row_groups):
                tbl = pf.read_row_group(rg, columns=READ_COLS)
                df  = tbl.to_pandas()
                # Quick filter by reciter_id before JSON parsing
                df  = df[df["reciter_id"].isin(TARGET_RECITER_IDS)]
                for _, row in df.iterrows():
                    meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else {}
                    results.append({
                        "reciter_id":      int(row["reciter_id"]),
                        "surah_number":    int(row["surah_id"]) + 1,
                        "ayah_number":     int(row["ayah_id"]),
                        "ayah_duration_s": row.get("ayah_duration_s"),
                        "word_alignments": meta.get("word_alignments") or [],
                    })
    except Exception as exc:
        # Log but don't abort — some shards may be temporarily unavailable
        print(f"  [WARN] {url.split('/')[-1]}: {exc}")
    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    t_start = time.time()

    # 1. Get all shard URLs
    print("Fetching shard list from HuggingFace…")
    urls = get_shard_urls()
    print(f"  {len(urls)} shards to scan")

    # 2. Scan shards in parallel
    print(f"\nScanning with {MAX_WORKERS} workers (metadata columns only, no audio)…")
    all_rows: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_shard, url): url for url in urls}
        for fut in as_completed(futures):
            rows = fut.result()
            all_rows.extend(rows)
            done += 1
            if done % 50 == 0 or done == len(urls):
                elapsed = time.time() - t_start
                print(f"  {done}/{len(urls)} shards  |  {len(all_rows)} target rows  |  {elapsed:.0f}s")

    print(f"\nTotal rows collected: {len(all_rows)}")

    # Known ayah count per surah (1-based surah index)
    AYAH_COUNTS = [
        7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99,
        128, 111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34,
        30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18,
        45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30,
        52, 52, 44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22,
        17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5,
        4, 7, 3, 6, 3, 5, 4, 5, 6,
    ]  # 114 surahs, sum = 6236

    # 3. Build and save JSON per reciter
    for reciter in RECITERS:
        rid         = reciter["tadabur_id"]
        audio_fn    = reciter["audio_url_fn"]
        subset      = [r for r in all_rows if r["reciter_id"] == rid]
        print(f"\n{'='*60}")
        print(f"  {reciter['name_ar']} ({reciter['name_en']})  —  {len(subset)} raw rows")

        # Build Tadabur data index (best take per ayah = most words)
        tadabur: dict[str, dict] = {}
        for row in subset:
            s, a   = row["surah_number"], row["ayah_number"]
            segs   = word_alignments_to_segments(row["word_alignments"])
            dur_s  = row.get("ayah_duration_s")
            key    = f"{s}:{a}"
            if key not in tadabur or len(segs) > len(tadabur[key]["segments"]):
                dur_ms = round(float(dur_s) * 1000) if dur_s and dur_s == dur_s else None
                tadabur[key] = {"duration": dur_ms, "segments": segs}

        # Generate complete JSON for all 6236 ayahs; overlay Tadabur where available
        data: dict[str, dict] = {}
        for surah_idx, ayah_count in enumerate(AYAH_COUNTS, start=1):
            for ayah in range(1, ayah_count + 1):
                key   = f"{surah_idx}:{ayah}"
                td    = tadabur.get(key, {})
                data[key] = {
                    "surah_number": surah_idx,
                    "ayah_number":  ayah,
                    "audio_url":    audio_fn(surah_idx, ayah),
                    "duration":     td.get("duration"),
                    "segments":     td.get("segments", []),
                }

        out_path = OUTPUT_DIR / reciter["output_file"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        covered = sum(1 for v in data.values() if v["segments"])
        print(f"  Total ayahs: {len(data)} | With word segments: {covered}  →  {out_path}")
        sorted_keys = sorted(data, key=lambda k: (int(k.split(':')[0]), int(k.split(':')[1])))
        for key in sorted_keys[:3]:
            e = data[key]
            seg_info = f"segs={e['segments'][:2]}" if e['segments'] else "no segments"
            print(f"    {key}: {e['audio_url'].split('/')[-1]}  {seg_info}")

    print(f"\nAll done in {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
