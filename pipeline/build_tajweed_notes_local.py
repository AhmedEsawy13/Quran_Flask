#!/usr/bin/env python3
"""Harvest Tafsir MCP tajweed *notes* into data/tajweed_notes_local.db.

Companion layer to data/tajweed_local.db (letter coloring). Notes are Arabic
prose explanations from مركز تفسير (Tafsir MCP), one row per ayah.

  python3 pipeline/build_tajweed_notes_local.py
  python3 pipeline/build_tajweed_notes_local.py --limit 50   # smoke
  python3 pipeline/build_tajweed_notes_local.py --resume     # skip existing

Requires network. Resume-safe: re-run continues from missing verse_keys.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from tafsir_mcp_client import TafsirMcpClient, TafsirMcpError  # noqa: E402

COLOR_DB = ROOT / "data" / "tajweed_local.db"
OUT_DB = ROOT / "data" / "tajweed_notes_local.db"

ATTRIBUTION = (
    "بيان تجويد — مركز تفسير للدراسات القرآنية (Tafsir MCP / mcp.tafsir.net)"
)
SOURCE = "tafsir_mcp"


def list_verse_keys() -> list[str]:
    conn = sqlite3.connect(str(COLOR_DB))
    try:
        rows = conn.execute(
            "SELECT verse_key FROM tajweed ORDER BY "
            "CAST(substr(verse_key, 1, instr(verse_key, ':') - 1) AS INT), "
            "CAST(substr(verse_key, instr(verse_key, ':') + 1) AS INT)"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tajweed_notes (
            verse_key   TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            attribution TEXT NOT NULL,
            source      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()


def existing_keys(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT verse_key FROM tajweed_notes WHERE length(trim(text)) > 0"
        )
    }


def fetch_one(key: str) -> tuple[str, str | None, str | None]:
    surah_s, ayah_s = key.split(":")
    client = TafsirMcpClient()
    try:
        payload = client.fetch_ayah(int(surah_s), int(ayah_s), include=["tajweed"])
        note = (payload.get("tajweed") or "").strip()
        if not note:
            return key, None, "empty"
        return key, note, None
    except TafsirMcpError as exc:
        return key, None, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--no-resume", action="store_false", dest="resume")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--commit-every", type=int, default=25)
    args = ap.parse_args()

    if not COLOR_DB.is_file():
        print(f"Missing coloring DB {COLOR_DB}", file=sys.stderr)
        return 1

    all_keys = list_verse_keys()
    keys = all_keys
    if args.limit > 0:
        keys = keys[: args.limit]

    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(OUT_DB))
    ensure_schema(conn)
    done = existing_keys(conn) if args.resume else set()
    todo = [k for k in keys if k not in done]
    print(f"target={len(keys)} already={len(done)} todo={len(todo)} workers={args.workers}")

    ok = fail = empty = 0
    empty_keys: list[str] = []
    pending: list[tuple[str, str]] = []
    previous_missing: set[str] = set()
    previous_missing_row = conn.execute(
        "SELECT value FROM meta WHERE key = 'reference_missing_keys'"
    ).fetchone()
    if previous_missing_row:
        try:
            value = json.loads(previous_missing_row[0])
            if isinstance(value, list):
                previous_missing = {str(key) for key in value}
        except (TypeError, json.JSONDecodeError):
            previous_missing = set()

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        conn.executemany(
            "INSERT OR REPLACE INTO tajweed_notes "
            "(verse_key, text, attribution, source, fetched_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            [(k, t, ATTRIBUTION, SOURCE) for k, t in pending],
        )
        conn.commit()
        pending = []

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(fetch_one, key): key for key in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                key, note, err = fut.result()
                if err == "empty":
                    empty += 1
                    empty_keys.append(key)
                    print(f"[{i}/{len(todo)}] empty {key}")
                elif err:
                    fail += 1
                    print(f"[{i}/{len(todo)}] FAIL {key}: {err}")
                else:
                    assert note is not None
                    pending.append((key, note))
                    ok += 1
                    if ok % 10 == 0 or i == len(todo):
                        print(f"[{i}/{len(todo)}] ok={ok} fail={fail} empty={empty} last={key}")
                if len(pending) >= args.commit_every:
                    flush()
                # light pacing so we don't stampede the hosted MCP
                if i % 40 == 0:
                    time.sleep(0.4)
        flush()
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('attribution', ?)",
            (ATTRIBUTION,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('source', ?)",
            (SOURCE,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('built_rows', ?)",
            (str(conn.execute('SELECT count(*) FROM tajweed_notes').fetchone()[0]),),
        )
        available_keys = {
            row[0]
            for row in conn.execute(
                "SELECT verse_key FROM tajweed_notes WHERE length(trim(text)) > 0"
            )
        }
        missing_keys = sorted(
            (previous_missing | set(empty_keys)) - available_keys,
            key=lambda key: tuple(int(part) for part in key.split(':')),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reference_total', ?)",
            (str(len(all_keys)),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reference_available', ?)",
            (str(len(available_keys & set(all_keys))),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reference_missing_keys', ?)",
            (json.dumps(missing_keys, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reference_scan_complete', ?)",
            ('1' if args.limit <= 0 and fail == 0 else '0',),
        )
        conn.commit()
    finally:
        conn.close()

    print(
        f"\ndone → {OUT_DB}  ok={ok} fail={fail} empty={empty}"
        f" reference_missing={len(empty_keys)}"
    )
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
