"""
fetch_hf_timestamps.py
----------------------
Fetches per-surah word-level timestamps from the HuggingFace dataset:
  zaibihassan/Quranic-Recitation-Data

Decodes the .pb (protobuf) files using pure Python (no external deps),
normalises timestamps to be relative to each ayah's start, and merges
the segments into an existing reciter JSON file (keeping audio_url, etc.).

Usage:
    python3 pipeline/fetch_hf_timestamps.py

Config is set in the RECITER dict at the top of this file.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse

# ── Configuration ────────────────────────────────────────────────────────────

# HuggingFace folder name (exact, case-sensitive)
HF_RECITER_FOLDER = "Ayman Suwaid (Muallim)"

# Path to the existing reciter JSON (will be updated in-place)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_JSON = os.path.join(BASE_DIR, "QUL_data", "word_timestamps", "ayman-rushdi-suwaid.json")

# HuggingFace CDN base
HF_BASE = "https://huggingface.co/datasets/zaibihassan/Quranic-Recitation-Data/resolve/main"

# Delay between requests (seconds) — be polite to the CDN
REQUEST_DELAY = 0.3

# ── Pure-Python protobuf decoder ─────────────────────────────────────────────
# Decodes the SurahTimestamps proto defined in the dataset README:
#
#   message WordSegment   { int32 word_index_0_based=1; word_index_1_based=2;
#                           int32 timestamp_from=3; int32 timestamp_to=4; }
#   message VerseSegments { repeated WordSegment segments = 1; }
#   message SurahTimestamps { map<string, VerseSegments> verses = 1; }


def _read_varint(data: bytes, pos: int):
    result = 0
    shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _decode_word_segment(data: bytes) -> list:
    """Returns [word_0based, word_1based, start_ms, end_ms]."""
    fields = {}
    p = 0
    while p < len(data):
        tag, p = _read_varint(data, p)
        wire = tag & 0x7
        field = tag >> 3
        if wire == 0:
            val, p = _read_varint(data, p)
            fields[field] = val
        else:
            break  # unexpected wire type — stop
    return [fields.get(1, 0), fields.get(2, 0), fields.get(3, 0), fields.get(4, 0)]


def _decode_verse_segments(data: bytes) -> list:
    """Returns list of [word_0based, word_1based, start_ms, end_ms]."""
    segments = []
    p = 0
    while p < len(data):
        tag, p = _read_varint(data, p)
        wire = tag & 0x7
        field = tag >> 3
        if wire == 2:
            length, p = _read_varint(data, p)
            chunk = data[p:p + length]
            if field == 1:  # WordSegment
                segments.append(_decode_word_segment(chunk))
            p += length
        elif wire == 0:
            _, p = _read_varint(data, p)
        else:
            break
    return segments


def decode_surah_pb(data: bytes) -> dict:
    """
    Decodes a SurahTimestamps protobuf blob.
    Returns dict: {"s:a" -> [[w0, w1, start_ms, end_ms], ...], ...}
    Timestamps are ABSOLUTE within the surah audio (not per-ayah relative).
    """
    verses = {}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        wire = tag & 0x7
        field = tag >> 3
        if wire == 2:
            length, pos = _read_varint(data, pos)
            chunk = data[pos:pos + length]
            if field == 1:  # map entry
                key = None
                verse_segs = []
                p2 = 0
                while p2 < len(chunk):
                    t2, p2 = _read_varint(chunk, p2)
                    w2 = t2 & 0x7
                    f2 = t2 >> 3
                    if w2 == 2:
                        l2, p2 = _read_varint(chunk, p2)
                        sub = chunk[p2:p2 + l2]
                        if f2 == 1:    # key (string)
                            key = sub.decode("utf-8")
                        elif f2 == 2:  # VerseSegments
                            verse_segs = _decode_verse_segments(sub)
                        p2 += l2
                    elif w2 == 0:
                        _, p2 = _read_varint(chunk, p2)
                    else:
                        break
                if key:
                    verses[key] = verse_segs
            pos += length
        elif wire == 0:
            _, pos = _read_varint(data, pos)
        else:
            break
    return verses


def normalise_segments(raw_segments: list) -> list:
    """
    Convert absolute-within-surah timestamps → relative-to-ayah timestamps.
    Subtracts the first word's start_ms from every segment so that
    the first word always starts at 0ms (matching the per-ayah audio files).
    """
    if not raw_segments:
        return []
    offset = raw_segments[0][2]  # start_ms of first word
    return [
        [s[0], s[1], max(0, s[2] - offset), max(0, s[3] - offset)]
        for s in raw_segments
    ]


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def _build_url(reciter_folder: str, surah: int) -> str:
    folder_enc = urllib.parse.quote(reciter_folder)
    surah_str = f"{surah:03d}"
    return f"{HF_BASE}/{folder_enc}/{surah_str}/{surah_str}.pb"


def fetch_surah_pb(reciter_folder: str, surah: int, retries: int = 3) -> bytes | None:
    url = _build_url(reciter_folder, surah)
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Quran-Flask/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            print(f"    [attempt {attempt}/{retries}] Error fetching surah {surah:03d}: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading existing JSON: {TARGET_JSON}")
    with open(TARGET_JSON, encoding="utf-8") as f:
        data = json.load(f)

    # data is {"1:1": {...}, "1:2": {...}, ...}
    total = len(data)
    print(f"  {total} verse entries loaded")

    filled = 0
    skipped = 0
    failed_surahs = []

    for surah in range(1, 115):
        surah_str = f"{surah:03d}"
        print(f"  Surah {surah_str}/114 ...", end=" ", flush=True)

        raw = fetch_surah_pb(HF_RECITER_FOLDER, surah)
        if raw is None:
            print("FAILED — skipping")
            failed_surahs.append(surah)
            continue

        decoded = decode_surah_pb(raw)
        if not decoded:
            print(f"empty decode — skipping")
            failed_surahs.append(surah)
            continue

        surah_filled = 0
        for verse_key, raw_segs in decoded.items():
            if verse_key not in data:
                # verse exists in HF but not in our JSON — unlikely but safe to skip
                skipped += 1
                continue
            norm = normalise_segments(raw_segs)
            if norm:
                data[verse_key]["segments"] = norm
                # update duration from last segment's end_ms
                data[verse_key]["duration"] = norm[-1][3]
                filled += 1
                surah_filled += 1

        print(f"filled {surah_filled} verses  ({len(decoded)} in HF)")
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. Filled: {filled} | Skipped: {skipped} | Failed surahs: {failed_surahs or 'none'}")

    print(f"Writing updated JSON to {TARGET_JSON} ...")
    with open(TARGET_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(TARGET_JSON) / 1024
    print(f"Saved ({size_kb:.0f} KB)")

    if failed_surahs:
        print(f"\nWARNING: {len(failed_surahs)} surah(s) failed to fetch: {failed_surahs}")
        print("Re-run the script to retry only the failed surahs, or fetch manually.")


if __name__ == "__main__":
    main()
