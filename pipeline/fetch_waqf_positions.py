#!/usr/bin/env python3
"""
Extract waqf (pause/stop) positions from the muaalem-annotated-v3 dataset.

Each audio segment is cut at a waqf point. Only text/span columns are fetched —
audio is never downloaded. Works as a CLI script or in a Kaggle/Jupyter notebook.

Output columns:
  segment_index          — unique segment ID
  moshaf_id / name       — Mushaf variant
  reciter_id/name        — reciter info
  start_sura/aya/word    — where reciter STARTS (resumes after previous waqf)
  end_sura/aya/word      — where reciter STOPS (the waqf point)
  transcript             — recited text (tarteel)
  imlaey_text            — Imlaey script text for the full segment
  uthmani_text           — Uthmanic script text for the full segment
  has_quran/istiaatha/bismillah — segment type flags
  duration_seconds       — audio clip length

CLI usage:
  python fetch_waqf_positions.py                        # moshaf 0.0
  python fetch_waqf_positions.py --moshaf 1.0
  python fetch_waqf_positions.py --moshaf all           # all 30 moshafs
  python fetch_waqf_positions.py --quran-only
  python fetch_waqf_positions.py --output waqf.json

Kaggle / notebook usage — edit the CONFIG block below, then run the file:
  MOSHAF_ID  = "0.0"
  QURAN_ONLY = True
  ...
"""

# ── CONFIG (edit here for Kaggle / notebook use) ────────────────────────────
MOSHAF_ID   = "0.0"    # "0.0" … "29.0"  or  "all"
QURAN_ONLY  = False    # True = skip istiaatha/bismillah-only rows
OUTPUT_DIR  = "."      # directory for output .db files (auto-named per reciter)
MAX_WORKERS = 4        # parallel shard downloads (4 is safe for HF)
HF_TOKEN    = None     # set to your token if dataset is private
# ────────────────────────────────────────────────────────────────────────────

import re
import sys
import json
import time
import random
import sqlite3
import argparse
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd

try:
    from tqdm.auto import tqdm
except ImportError:
    def tqdm(iterable=None, **kwargs):      # silent fallback
        return iterable if iterable is not None else _DummyTqdm()

class _DummyTqdm:
    def __init__(self): pass
    def update(self, n=1): pass
    def set_postfix_str(self, s): pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass


# ── Naming helpers ────────────────────────────────────────────────────────────

def _safe_name(s: str) -> str:
    """Turn any string into a safe, lowercase filename component."""
    s = str(s or "").strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s\-]+", "_", s)
    return s.strip("_").lower()


def _db_stem(reciter_en: str, moshaf_id) -> str:
    """e.g. 'husary_0_0' or 'moshaf_0_0' when reciter name is unknown."""
    name = _safe_name(reciter_en)
    mid  = str(moshaf_id).replace(".", "_")
    return f"{name}_{mid}" if name else f"moshaf_{mid}"


def save_to_db(df: pd.DataFrame, path: Path, table: str = "positions") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    df.to_sql(table, conn, if_exists="replace", index=False)
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────

DATASET_ID  = "obadx/muaalem-annotated-v3"
HF_API_BASE = "https://datasets-server.huggingface.co"

# Only these columns are fetched from parquet — audio bytes are excluded
TEXT_COLUMNS = [
    "segment_index", "moshaf_id", "moshaf_name",
    "reciter_id", "reciter_arabic_name", "reciter_english_name",
    "sura_or_aya_index", "index_type",
    "tarteel_transcript", "imlaey", "uthmani",
    "has_quran", "has_istiaatha", "has_bismillah", "has_sadaka",
    "start_span", "end_span",
    "duration_seconds", "match_ratio",
    "timestamp_seconds",   # absolute [start, end] of segment in the surah file
]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    if HF_TOKEN:
        s.headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return s


def _get_json(url: str, retries: int = 5) -> dict:
    """GET with exponential backoff for transient HF API errors."""
    sess = _session()
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            if e.response.status_code in (429, 503) and attempt < retries - 1:
                wait = 2 ** attempt + random.random()
                print(f"  Rate limited, retrying in {wait:.1f}s …", flush=True)
                time.sleep(wait)
            else:
                raise
    return {}


def get_parquet_urls(moshaf_id: str) -> list[str]:
    url = f"{HF_API_BASE}/parquet?dataset={DATASET_ID}&config=moshaf_{moshaf_id}&split=train"
    data = _get_json(url)
    return [f["url"] for f in data.get("parquet_files", [])]


def get_all_moshaf_ids() -> list[str]:
    data = _get_json(f"{HF_API_BASE}/info?dataset={DATASET_ID}")
    configs = data.get("dataset_info", {}).keys()
    ids = [c.replace("moshaf_", "") for c in configs if c.startswith("moshaf_")]
    return sorted(ids, key=float)


# ── Parquet loading ──────────────────────────────────────────────────────────

def _load_shard(url: str, retries: int = 3) -> pd.DataFrame:
    """Read one parquet shard, fetching text columns only."""
    for attempt in range(retries):
        try:
            return pd.read_parquet(url, engine="pyarrow", columns=TEXT_COLUMNS)
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** attempt + random.random()
                print(f"  Retry shard ({exc.__class__.__name__}), waiting {wait:.1f}s …")
                time.sleep(wait)
            else:
                # Fall back: load all cols and drop audio/heavy ones
                warnings.warn(f"Column filter failed for {url.split('/')[-1]}: {exc}. Loading without filter.")
                df = pd.read_parquet(url, engine="pyarrow")
                drop = [c for c in ["audio", "phonemes", "sifat"] if c in df.columns]
                return df.drop(columns=drop)
    return pd.DataFrame()


def load_moshaf_text(moshaf_id: str, max_workers: int = 4) -> pd.DataFrame:
    """Download all parquet shards in parallel, text columns only."""
    urls = get_parquet_urls(moshaf_id)
    if not urls:
        raise ValueError(f"No parquet files found for moshaf_{moshaf_id}")

    shards: list[pd.DataFrame] = [None] * len(urls)

    with tqdm(total=len(urls), desc=f"moshaf_{moshaf_id}", unit="shard") as bar:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
            futures = {pool.submit(_load_shard, url): i for i, url in enumerate(urls)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    shards[idx] = fut.result()
                    bar.set_postfix_str(f"{len(shards[idx]):,} rows")
                except Exception as e:
                    print(f"\n  Failed shard {idx}: {e}")
                bar.update(1)

    valid = [s for s in shards if s is not None and not s.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


# ── Span extraction (vectorized) ─────────────────────────────────────────────

def _safe_int(v):
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _expand_span(series: pd.Series, prefix: str) -> pd.DataFrame:
    """Vectorised: turn a column of span dicts into three flat int columns."""
    def extract(s):
        if isinstance(s, dict):
            return _safe_int(s.get("sura_idx")), _safe_int(s.get("aya_idx")), _safe_int(s.get("imlaey"))
        return None, None, None

    expanded = series.apply(extract)
    result = pd.DataFrame(expanded.tolist(), index=series.index,
                          columns=[f"{prefix}_sura", f"{prefix}_aya", f"{prefix}_word"])
    return result


def extract_waqf_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean DataFrame with flat start/end span columns."""
    # Flatten transcript list → string
    transcript = df.get("tarteel_transcript", pd.Series(dtype=str))
    def _transcript_to_str(t):
        if t is None:
            return ""
        # numpy arrays and lists are both iterable but not strings
        if hasattr(t, "__iter__") and not isinstance(t, str):
            return " ".join(str(x) for x in t)
        return str(t)

    transcript = transcript.apply(_transcript_to_str)

    # Expand span dicts
    start_cols = _expand_span(df["start_span"] if "start_span" in df.columns else pd.Series([None]*len(df)), "start")
    end_cols   = _expand_span(df["end_span"]   if "end_span"   in df.columns else pd.Series([None]*len(df)), "end")

    result = pd.DataFrame({
        "segment_index":    df.get("segment_index"),
        "moshaf_id":        df.get("moshaf_id"),
        "moshaf_name":      df.get("moshaf_name"),
        "reciter_id":       df.get("reciter_id"),
        "reciter_name_ar":  df.get("reciter_arabic_name"),
        "reciter_name_en":  df.get("reciter_english_name"),
        "index_type":       df.get("index_type"),
    })

    result = pd.concat([result, start_cols, end_cols], axis=1)

    result["transcript"]     = transcript.values
    result["imlaey_text"]    = df.get("imlaey")
    result["uthmani_text"]   = df.get("uthmani")
    result["has_quran"]      = df.get("has_quran")
    result["has_istiaatha"]  = df.get("has_istiaatha")
    result["has_bismillah"]  = df.get("has_bismillah")
    result["has_sadaka"]     = df.get("has_sadaka")
    result["duration_seconds"] = df.get("duration_seconds")
    result["match_ratio"]    = df.get("match_ratio")

    # Flatten timestamp_seconds: [start, end] array → two scalar columns
    # Falls back gracefully if the column is absent (older dataset versions).
    if "timestamp_seconds" in df.columns:
        def _ts_start(v):
            if v is None:
                return None
            try:
                arr = list(v)
                return float(arr[0]) if arr else None
            except Exception:
                return None

        def _ts_end(v):
            if v is None:
                return None
            try:
                arr = list(v)
                return float(arr[-1]) if arr else None
            except Exception:
                return None

        result["timestamp_start"] = df["timestamp_seconds"].apply(_ts_start).values
        result["timestamp_end"]   = df["timestamp_seconds"].apply(_ts_end).values
    else:
        result["timestamp_start"] = None
        result["timestamp_end"]   = None

    return result.reset_index(drop=True)


# ── Summary ──────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame) -> None:
    print("\n=== Summary ===")
    print(f"Total segments       : {len(df):,}")
    if "has_quran" in df.columns:
        print(f"  Quran              : {int(df['has_quran'].sum()):,}")
        print(f"  Istiaatha          : {int(df['has_istiaatha'].sum()):,}")
        print(f"  Bismillah          : {int(df['has_bismillah'].sum()):,}")
    valid = df.dropna(subset=["start_sura", "end_sura"])
    print(f"With span info       : {len(valid):,}")
    if len(valid):
        cross = valid[valid["start_aya"] != valid["end_aya"]]
        print(f"Cross-aya segments   : {len(cross):,}")
        print(f"Suras covered        : {int(valid['start_sura'].nunique())}")
    if "reciter_name_en" in df.columns:
        reciters = sorted(df["reciter_name_en"].dropna().unique())
        print(f"Reciters ({len(reciters)})         :")
        for r in reciters:
            print(f"  - {r}")


# ── Run (shared between CLI and notebook) ────────────────────────────────────

def run(moshaf_id: str, quran_only: bool, output_dir: str, max_workers: int) -> pd.DataFrame:
    if moshaf_id == "all":
        print("Discovering moshaf configs …")
        moshaf_ids = get_all_moshaf_ids()
        print(f"Found {len(moshaf_ids)} configs: {moshaf_ids}")
    else:
        moshaf_ids = [moshaf_id]

    base = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    all_frames = []
    for mid in tqdm(moshaf_ids, desc="Moshafs", unit="moshaf", disable=len(moshaf_ids) == 1):
        raw  = load_moshaf_text(mid, max_workers=max_workers)
        waqf = extract_waqf_positions(raw)
        if quran_only:
            waqf = waqf[waqf["has_quran"] == True].reset_index(drop=True)

        # Name the DB after the reciter + moshaf_id from the actual data
        reciter_en = waqf["reciter_name_en"].dropna().iloc[0] if not waqf.empty else ""
        stem = _db_stem(reciter_en, mid)
        out  = base / f"{stem}_positions.db"
        save_to_db(waqf, out, table="positions")
        print(f"  moshaf_{mid}: {len(waqf):,} rows → {out.name}")
        all_frames.append(waqf)

    result = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    print_summary(result)
    return result


# ── Entry points ─────────────────────────────────────────────────────────────

def _is_notebook() -> bool:
    try:
        shell = get_ipython().__class__.__name__  # type: ignore[name-defined]
        return shell in ("ZMQInteractiveShell", "TerminalInteractiveShell")
    except NameError:
        return False


if _is_notebook():
    result = run(MOSHAF_ID, QURAN_ONLY, OUTPUT_DIR, MAX_WORKERS)
elif __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch waqf positions from muaalem-annotated-v3")
    parser.add_argument("--moshaf",     default=MOSHAF_ID,  help="Moshaf ID or 'all'")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Directory for output .db files")
    parser.add_argument("--quran-only", action="store_true", default=QURAN_ONLY)
    parser.add_argument("--workers",    type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    run(args.moshaf, args.quran_only, args.output_dir, args.workers)
