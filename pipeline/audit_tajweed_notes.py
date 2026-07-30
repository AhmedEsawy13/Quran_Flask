#!/usr/bin/env python3
"""Audit Athar tajweed *coloring* vs Tafsir MCP *prose notes*.

These are complementary layers (spans vs teaching text). This script does a
keyword-level consistency check on a curated sample:

  - note mentions rule R, Athar HTML for that ayah has class R  → agree
  - note mentions R, Athar lacks R                              → soft (note_extra)
  - Athar has "major" R, note never mentions any overlapping family → soft (color_only)

Usage:
  python3 pipeline/audit_tajweed_notes.py
  python3 pipeline/audit_tajweed_notes.py --limit 20 --sleep 0.2
  python3 pipeline/audit_tajweed_notes.py --json-out /tmp/tajweed_audit.json

Does not modify app data. Requires network to mcp.tafsir.net.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from tafsir_mcp_client import TafsirMcpClient, TafsirMcpError  # noqa: E402

TAJWEED_DB = ROOT / "data" / "tajweed_local.db"

# Arabic phrase → Athar CSS class (cpfair-mapped). Order matters for overlaps
# (more specific phrases first).
RULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"إدغام\s*شفو"), "idgham_shafawi"),
    (re.compile(r"إخفاء\s*شفو"), "ikhafa_shafawi"),
    (re.compile(r"إدغام\s*متجانس"), "idgham_mutajanisayn"),
    (re.compile(r"إدغام\s*متقارب"), "idgham_mutaqaribayn"),
    (re.compile(r"إدغام\s*(?:بغير|بلا)\s*غن"), "idgham_wo_ghunnah"),
    (re.compile(r"إدغام\s*بغن"), "idgham_ghunnah"),
    (re.compile(r"مد\s*منفصل|المنفصل"), "madda_munfasil"),
    (re.compile(r"مد\s*متصل|المتصل"), "madda_obligatory"),
    (re.compile(r"مد\s*لازم|اللازم|مد(?:ّ|ً)?ا?\s*لازم"), "madda_necessary"),
    (re.compile(r"مد\s*عارض|عارض\s*للسكون|مد\s*جائز"), "madda_permissible"),
    (re.compile(r"مد\s*طبيعي|مد\s*بدل|صلة\s*(?:صغرى|كبرى)"), "madda_normal"),
    (re.compile(r"إقلاب"), "iqlab"),
    (re.compile(r"إخفاء"), "ikhafa"),
    (re.compile(r"قلقلة"), "qalaqah"),
    (re.compile(r"همزة\s*وصل"), "ham_wasl"),
    (re.compile(r"لام\s*شمس|الشمسي"), "laam_shamsiyah"),
    (re.compile(r"غن[ةّ]"), "ghunnah"),
]

# Classes that are often present in coloring but rarely named in short notes.
COLOR_ONLY_OK = {
    "ham_wasl",
    "laam_shamsiyah",
    "slnt",
    "madda_normal",
    "ghunnah",
}

# If the note claims these, coloring should usually show them.
STRICT_NOTE_RULES = {
    "madda_munfasil",
    "madda_obligatory",
    "madda_necessary",
    "madda_permissible",
    "idgham_ghunnah",
    "idgham_wo_ghunnah",
    "ikhafa",
    "ikhafa_shafawi",
    "iqlab",
    "qalaqah",
    "idgham_shafawi",
}

# Curated sample: Fatiha, openings, Kursi, dense tajweed-ish verses.
DEFAULT_KEYS = [
    "1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7",
    "2:1", "2:2", "2:3", "2:4", "2:5",
    "2:255", "2:256", "2:257",
    "3:1", "3:2", "18:1", "36:1", "36:2",
    "55:1", "55:2", "67:1",
    "112:1", "112:2", "112:3", "112:4",
    "113:1", "114:1",
    "4:1", "5:1", "9:1", "19:1", "20:1",
    "24:31", "33:56", "48:1", "56:1", "78:1",
    "96:1", "97:1", "108:1", "109:1", "110:1", "111:1",
]


def parse_key(key: str) -> tuple[int, int]:
    s, a = key.split(":")
    return int(s), int(a)


def classes_from_html(html: str) -> set[str]:
    return set(re.findall(r'class=["\']([^"\']+)["\']', html or ""))


def rules_from_note(note: str) -> set[str]:
    found: set[str] = set()
    text = note or ""
    for pattern, cls in RULE_PATTERNS:
        if pattern.search(text):
            found.add(cls)
    return found


def load_athar_html(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT html FROM tajweed WHERE verse_key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def audit_one(client: TafsirMcpClient, conn: sqlite3.Connection, key: str) -> dict:
    surah, ayah = parse_key(key)
    html = load_athar_html(conn, key)
    if html is None:
        return {"verse_key": key, "status": "missing_athar"}

    color = classes_from_html(html)
    try:
        payload = client.fetch_ayah(surah, ayah, include=["tajweed"])
    except TafsirMcpError as exc:
        return {"verse_key": key, "status": "mcp_error", "error": str(exc)}

    note = (payload.get("tajweed") or "").strip()
    if not note:
        return {
            "verse_key": key,
            "status": "missing_note",
            "color_classes": sorted(color),
        }

    claimed = rules_from_note(note)
    note_extra = sorted((claimed & STRICT_NOTE_RULES) - color)
    # Major color rules with no lexical echo in the note (informational only).
    color_major = (color & STRICT_NOTE_RULES) - claimed
    color_only = sorted(color_major - COLOR_ONLY_OK)

    if note_extra:
        status = "soft_note_extra"
    else:
        status = "agree"

    return {
        "verse_key": key,
        "status": status,
        "color_classes": sorted(color),
        "note_rules": sorted(claimed),
        "note_extra": note_extra,
        "color_only_major": color_only,
        "note_chars": len(note),
        "note_preview": note.replace("\n", " ")[:160],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="Cap sample size (0 = all DEFAULT_KEYS)")
    ap.add_argument("--sleep", type=float, default=0.15, help="Pause between MCP calls")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--keys", nargs="*", default=None, help="Override verse keys")
    args = ap.parse_args()

    if not TAJWEED_DB.is_file():
        print(f"Missing {TAJWEED_DB}", file=sys.stderr)
        return 1

    keys = args.keys or list(DEFAULT_KEYS)
    if args.limit > 0:
        keys = keys[: args.limit]

    client = TafsirMcpClient()
    conn = sqlite3.connect(str(TAJWEED_DB))
    rows: list[dict] = []
    try:
        for i, key in enumerate(keys, 1):
            row = audit_one(client, conn, key)
            rows.append(row)
            mark = {
                "agree": "✓",
                "soft_note_extra": "~",
                "missing_note": "?",
                "missing_athar": "!",
                "mcp_error": "x",
            }.get(row["status"], "·")
            extra = ""
            if row.get("note_extra"):
                extra = f" note_extra={row['note_extra']}"
            print(f"[{i}/{len(keys)}] {mark} {key} {row['status']}{extra}")
            if args.sleep > 0 and i < len(keys):
                time.sleep(args.sleep)
    finally:
        conn.close()

    counts = Counter(r["status"] for r in rows)
    print("\n=== summary ===")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    soft = [r for r in rows if r["status"] == "soft_note_extra"]
    if soft:
        print("\nsoft note→color gaps (note claims rule absent from Athar spans):")
        for r in soft:
            print(f"  {r['verse_key']}: {r['note_extra']} | {r.get('note_preview', '')}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"summary": dict(counts), "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}")

    # Non-zero only on hard failures (MCP / missing Athar), not soft gaps.
    hard = counts.get("mcp_error", 0) + counts.get("missing_athar", 0)
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
