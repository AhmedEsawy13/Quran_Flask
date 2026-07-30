#!/usr/bin/env python3
"""Harvest أسباب النزول from Tafsir MCP into data/asbab_local.db.

Stores only ayahs that have text in nuzool and/or wahidi_asbab (sparse).
Resume-safe.

  python3 pipeline/build_asbab_local.py
  python3 pipeline/build_asbab_local.py --limit 200
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from tafsir_mcp_client import TafsirMcpClient, TafsirMcpError  # noqa: E402

COLOR_DB = ROOT / "data" / "tajweed_local.db"
OUT_DB = ROOT / "data" / "asbab_local.db"
SOURCES = ["nuzool", "wahidi_asbab"]


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
        CREATE TABLE IF NOT EXISTS asbab (
            verse_key   TEXT NOT NULL,
            source      TEXT NOT NULL,
            text        TEXT NOT NULL,
            attribution TEXT NOT NULL,
            fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (verse_key, source)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asbab_checked (
            verse_key TEXT PRIMARY KEY,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()


def checked_keys(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT verse_key FROM asbab_checked")}


def fetch_parts(client: TafsirMcpClient, surah: int, ayah: int, source: str) -> tuple[str, str] | None:
    """Return (full_text, attribution) or None if unavailable."""
    parts: list[str] = []
    attribution = ""
    part = 1
    while True:
        payload = client.fetch_nuzool_reason(surah, ayah, sources=[source], part=part)
        entries = payload.get("sources") or []
        entry = None
        for item in entries:
            if item.get("source") == source:
                entry = item
                break
        if entry is None and len(entries) == 1:
            entry = entries[0]
        if not entry:
            return None
        if entry.get("available") is False:
            return None
        text = (entry.get("text") or "").strip()
        if not text:
            return None
        attribution = entry.get("attribution") or attribution or source
        parts.append(text)
        if not entry.get("has_more"):
            break
        part = int(entry.get("next_part") or (part + 1))
        if part > 20:
            break
    return ("\n".join(parts), attribution)


def fetch_one(key: str) -> tuple[str, list[tuple[str, str, str]], str | None]:
    """(verse_key, [(source, text, attribution), ...], error|None)"""
    surah_s, ayah_s = key.split(":")
    surah, ayah = int(surah_s), int(ayah_s)
    client = TafsirMcpClient()
    found: list[tuple[str, str, str]] = []
    try:
        for source in SOURCES:
            got = fetch_parts(client, surah, ayah, source)
            if got:
                found.append((source, got[0], got[1]))
        return key, found, None
    except TafsirMcpError as exc:
        return key, [], str(exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--no-resume", action="store_false", dest="resume")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--commit-every", type=int, default=40)
    args = ap.parse_args()

    if not COLOR_DB.is_file():
        print(f"Missing {COLOR_DB}", file=sys.stderr)
        return 1

    keys = list_verse_keys()
    if args.limit > 0:
        keys = keys[: args.limit]

    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(OUT_DB))
    ensure_schema(conn)
    done = checked_keys(conn) if args.resume else set()
    todo = [k for k in keys if k not in done]
    print(f"target={len(keys)} checked={len(done)} todo={len(todo)} workers={args.workers}")

    ok_with = empty = fail = 0
    pending_rows: list[tuple[str, str, str, str]] = []
    pending_checked: list[str] = []

    def flush() -> None:
        nonlocal pending_rows, pending_checked
        if pending_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO asbab "
                "(verse_key, source, text, attribution, fetched_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                pending_rows,
            )
        if pending_checked:
            conn.executemany(
                "INSERT OR REPLACE INTO asbab_checked (verse_key, fetched_at) "
                "VALUES (?, datetime('now'))",
                [(k,) for k in pending_checked],
            )
        conn.commit()
        pending_rows = []
        pending_checked = []

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(fetch_one, key): key for key in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                key, found, err = fut.result()
                if err:
                    fail += 1
                    print(f"[{i}/{len(todo)}] FAIL {key}: {err}")
                    continue
                pending_checked.append(key)
                if found:
                    ok_with += 1
                    for source, text, attr in found:
                        pending_rows.append((key, source, text, attr))
                    print(f"[{i}/{len(todo)}] hit {key} sources={[s for s,_,_ in found]}")
                else:
                    empty += 1
                    if i % 100 == 0 or i == len(todo):
                        print(f"[{i}/{len(todo)}] ok_with={ok_with} empty={empty} fail={fail}")
                if len(pending_checked) >= args.commit_every:
                    flush()
                if i % 50 == 0:
                    time.sleep(0.35)
        flush()
        n = conn.execute("SELECT count(*) FROM asbab").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_rows', ?)", (str(n),))
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('source', ?)",
            ("tafsir_mcp",),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"\ndone → {OUT_DB}  with_text={ok_with} empty={empty} fail={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
