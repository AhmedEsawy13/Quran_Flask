#!/usr/bin/env python3
"""Migrate the runtime word-meaning DB to the official Tafsir MCP snapshot.

The input is the completed, reviewable JSONL snapshot produced by
``compare_word_meanings.py --fetch --source python``.  The migration keeps the
existing ``verses`` table contract used by the Flask app, but changes its
granularity to one canonical MCP word per row.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from pipeline.audit_quran_integrity import DB_SOURCES, REFERENCE_PATH
from pipeline.compare_word_meanings import (
    ARTIFACT_DIR,
    WORD_MANIFEST_PATH,
    WORD_REFERENCE_PATH,
    _reference_sha256,
    _word_tasks,
    load_reference,
    load_word_manifest,
    load_word_reference,
)


ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = DB_SOURCES["word_name"]
BACKUP_PATH = ARTIFACT_DIR / "word_name.db.pre-mcp.sqlite"
MIGRATION_PATH = ARTIFACT_DIR / "word-name-migration.json"
SURAH_NAMES_PATH = ROOT / "data" / "quran_text" / "surahs.json"


def _surah_names() -> dict[int, str]:
    try:
        value = json.loads(SURAH_NAMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        int(row["number"]): str(row.get("name") or "")
        for row in value
        if isinstance(row, dict) and row.get("number") is not None
    }


def _validated_rows(
    *,
    reference_path: Path = REFERENCE_PATH,
    word_reference_path: Path = WORD_REFERENCE_PATH,
    manifest_path: Path = WORD_MANIFEST_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = load_word_manifest(manifest_path)
    if manifest.get("source") != "python":
        raise RuntimeError(
            "The word snapshot was not harvested from the official offline "
            "tafsir-mcp package; run --fetch --source python first."
        )
    if not manifest.get("complete"):
        raise RuntimeError("The MCP word snapshot is incomplete.")
    if manifest.get("reference_sha256") != _reference_sha256(reference_path):
        raise RuntimeError("The MCP word snapshot uses a different ayah reference.")
    if manifest.get("jsonl_sha256") != _reference_sha256(word_reference_path):
        raise RuntimeError("The MCP word snapshot checksum is stale.")

    tasks = _word_tasks(load_reference(reference_path))
    records = load_word_reference(word_reference_path)
    missing = [task["key"] for task in tasks if task["key"] not in records]
    if missing:
        raise RuntimeError(f"MCP word snapshot is missing {len(missing)} canonical rows.")
    rows = [
        records[task["key"]]
        for task in tasks
        if records[task["key"]].get("analysis_status") != "unavailable"
    ]
    if any(not row.get("word") for row in rows):
        raise RuntimeError("The MCP word snapshot contains a usable row without a word.")
    return rows, manifest


def _write_migration_report(report: dict[str, Any]) -> None:
    MIGRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    MIGRATION_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def migrate_word_name_database(
    *,
    target_path: Path = TARGET_PATH,
    backup_path: Path = BACKUP_PATH,
    apply: bool = False,
) -> dict[str, Any]:
    rows, manifest = _validated_rows()
    names = _surah_names()
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "provider": "Tafsir Center for Quranic Studies",
            "tool": "analyze_word",
            "package": manifest.get("package"),
            "package_version": manifest.get("package_version"),
            "jsonl_path": str(WORD_REFERENCE_PATH),
            "jsonl_sha256": manifest.get("jsonl_sha256"),
        },
        "target_path": str(target_path),
        "backup_path": str(backup_path),
        "row_count": len(rows),
        "replacement_approved": bool(apply),
        "applied": False,
    }
    if not apply:
        _write_migration_report(report)
        return report

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path)

    temporary_path = target_path.with_name(f".{target_path.name}.mcp.tmp")
    temporary_path.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary_path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode = DELETE;
            PRAGMA synchronous = FULL;
            CREATE TABLE verses (
                id INTEGER PRIMARY KEY,
                surah_name TEXT,
                ayah_number INTEGER NOT NULL,
                word TEXT NOT NULL,
                meaning TEXT NOT NULL,
                surah_number INTEGER NOT NULL,
                word_no INTEGER NOT NULL
            );
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO verses (
                id, surah_name, ayah_number, word, meaning, surah_number, word_no
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    index,
                    names.get(int(row["surah"]), ""),
                    int(row["ayah"]),
                    str(row.get("word") or row.get("reference_word") or ""),
                    str(row.get("meaning") or ""),
                    int(row["surah"]),
                    int(row.get("mcp_word_no") or row["word_no"]),
                )
                for index, row in enumerate(rows, 1)
            ),
        )
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        metadata = {
            "source_provider": "Tafsir Center for Quranic Studies",
            "source_tool": "analyze_word",
            "source_package": str(manifest.get("package") or ""),
            "source_package_version": str(manifest.get("package_version") or ""),
            "source_jsonl_sha256": str(manifest.get("jsonl_sha256") or ""),
            "row_count": str(len(rows)),
            "granularity": "mcp_word",
            "migrated_at": now,
            "replacement_approved": "1",
        }
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            metadata.items(),
        )
        connection.execute(
            "CREATE INDEX idx_verses_surah_ayah ON verses(surah_number, ayah_number)"
        )
        connection.execute("CREATE INDEX idx_verses_word ON verses(word)")
        connection.commit()
    finally:
        connection.close()

    os.replace(temporary_path, target_path)
    report.update({
        "applied": True,
        "target_sha256": _reference_sha256(target_path),
        "backup_sha256": _reference_sha256(backup_path) if backup_path.exists() else None,
    })
    _write_migration_report(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="replace data/word_name.db after creating a preserved backup",
    )
    args = parser.parse_args(argv)
    result = migrate_word_name_database(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
