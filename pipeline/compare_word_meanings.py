#!/usr/bin/env python3
"""Harvest MCP word analysis and compare it with the local meaning database.

The output is deliberately review-only.  ``word_name.db`` stores grouped
phrases, while ``analyze_word`` returns one canonical word position at a time,
so this script reports verse, phrase, and directly comparable word levels
separately instead of pretending that every row has a one-to-one match.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import difflib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from pipeline.audit_quran_integrity import (
    DB_SOURCES,
    MCP_URL,
    REFERENCE_PATH,
    _alignment_key,
    _reference_sha256,
    _reference_words,
    _ro_connect,
    _split_words,
    expected_verse_keys,
    load_reference,
    mcp_call,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "quran-integrity"
WORD_REFERENCE_PATH = ARTIFACT_DIR / "mcp-word-meaning-reference.jsonl"
WORD_MANIFEST_PATH = ARTIFACT_DIR / "mcp-word-meaning-manifest.json"
COMPARISON_PATH = ARTIFACT_DIR / "word-meaning-comparison.json"
MIGRATION_REPORT_PATH = ARTIFACT_DIR / "word-name-migration.json"


def _word_tasks(reference: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for verse_key in expected_verse_keys():
        row = reference.get(verse_key)
        if not row:
            continue
        surah, ayah = (int(part) for part in verse_key.split(":"))
        for word_no, word in enumerate(_reference_words(row), 1):
            tasks.append({
                "key": f"{verse_key}:{word_no}",
                "verse_key": verse_key,
                "surah": surah,
                "ayah": ayah,
                "word_no": word_no,
                "reference_word": word,
            })
    return tasks


def load_word_reference(path: Path = WORD_REFERENCE_PATH) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                key = str(row["word_key"])
                if (
                    isinstance(row.get("surah"), int)
                    and isinstance(row.get("ayah"), int)
                    and isinstance(row.get("word_no"), int)
                ):
                    records[key] = row
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
    return records


def load_word_manifest(path: Path = WORD_MANIFEST_PATH) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_word_migration(path: Path = MIGRATION_REPORT_PATH) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _unavailable_word_record(task: dict[str, Any]) -> dict[str, Any]:
    """Keep a canonical position when MCP has no lexical row for it."""
    return {
        "word_key": task["key"],
        "verse_key": task["verse_key"],
        "surah": task["surah"],
        "ayah": task["ayah"],
        "word_no": task["word_no"],
        "mcp_word_no": None,
        "reference_word": task["reference_word"],
        "word": None,
        "meaning": None,
        "irab": None,
        "sarf": None,
        "root": None,
        "frequency": None,
        "rasm_note": None,
        "meaning_available": False,
        "analysis_status": "unavailable",
    }


def _python_word_record(
    task: dict[str, Any],
    row: sqlite3.Row | None,
) -> dict[str, Any]:
    if row is None:
        return _unavailable_word_record(task)
    rasm = row["rasm"] if row["rasm"] and row["rasm"] != "-" else None
    return {
        "word_key": task["key"],
        "verse_key": task["verse_key"],
        "surah": task["surah"],
        "ayah": task["ayah"],
        "word_no": task["word_no"],
        "mcp_word_no": int(row["wordNo"]),
        "reference_word": task["reference_word"],
        "word": row["word"],
        "meaning": row["meaning"],
        "irab": row["irabMushakkal"],
        "sarf": row["sarf"],
        "root": row["root"],
        "frequency": row["repeatitionCount"],
        "rasm_note": rasm,
        "meaning_available": bool(row["meaning"]),
        "analysis_status": "ok",
    }


def _load_python_word_records(
    tasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Path, str, int]:
    """Read all meanings from the official tafsir-mcp SQLite database at once."""
    try:
        from tafsir.data_loader import get_db_path
        from tafsir.db import get_connection
    except ImportError as exc:
        raise RuntimeError(
            "The offline Tafsir MCP backend is unavailable. "
            "Install it with: python3 -m pip install tafsir-mcp"
        ) from exc

    db_path = Path(get_db_path())
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT r.surahNo, r.ayahNo, r.wordNo, r.word, r.rasm, "
            "m.meaning, i.irabMushakkal, s.sarf, "
            "ws.root, ws.repeatitionCount "
            "FROM word_content_rasm r "
            "LEFT JOIN word_content_meaning m "
            "  ON m.surahNo=r.surahNo AND m.ayahNo=r.ayahNo AND m.wordNo=r.wordNo "
            "LEFT JOIN word_content_irab i "
            "  ON i.surahNo=r.surahNo AND i.ayahNo=r.ayahNo AND i.wordNo=r.wordNo "
            "LEFT JOIN word_content_sarf s "
            "  ON s.surahNo=r.surahNo AND s.ayahNo=r.ayahNo AND s.wordNo=r.wordNo "
            "LEFT JOIN word_statistics ws "
            "  ON ws.surahNo=r.surahNo AND ws.ayahNo=r.ayahNo AND ws.wordNo=r.wordNo "
            "ORDER BY r.surahNo, r.ayahNo, r.wordNo"
        ).fetchall()
    finally:
        conn.close()

    by_key = {
        f"{int(row['surahNo'])}:{int(row['ayahNo'])}:{int(row['wordNo'])}": row
        for row in rows
    }
    by_verse: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in rows:
        by_verse[f"{int(row['surahNo'])}:{int(row['ayahNo'])}"].append(row)
    used_keys: set[str] = set()
    records = []
    for task in tasks:
        row = by_key.get(task["key"])
        if row is None:
            candidates = [
                candidate
                for candidate in by_verse.get(task["verse_key"], [])
                if (
                    f"{int(candidate['surahNo'])}:{int(candidate['ayahNo'])}:"
                    f"{int(candidate['wordNo'])}"
                ) not in used_keys
                and _alignment_key(str(candidate["word"] or ""))
                == _alignment_key(str(task["reference_word"] or ""))
            ]
            if len(candidates) == 1:
                row = candidates[0]
        if row is not None:
            used_keys.add(
                f"{int(row['surahNo'])}:{int(row['ayahNo'])}:{int(row['wordNo'])}"
            )
        records.append(_python_word_record(task, row))
    unavailable = sum(not row["meaning_available"] for row in records)
    try:
        from importlib.metadata import version

        package_version = version("tafsir-mcp")
    except Exception:
        package_version = "unknown"
    return records, db_path, package_version, unavailable


def _write_word_reference(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _write_manifest(
    *,
    expected: int,
    cached: int,
    errors: list[str],
    complete: bool,
    reference_sha256: str | None,
    word_reference_path: Path = WORD_REFERENCE_PATH,
    source: str = "http",
    database_path: Path | None = None,
    package_version: str | None = None,
    unavailable_words: int = 0,
) -> None:
    manifest = {
        "schema_version": 1,
        "mcp_url": MCP_URL if source == "http" else None,
        "tool": "analyze_word",
        "aspects": ["meaning"],
        "source": source,
        "database_path": str(database_path) if database_path else None,
        "package": "tafsir-mcp" if source == "python" else None,
        "package_version": package_version,
        "reference_path": str(REFERENCE_PATH),
        "reference_sha256": reference_sha256,
        "expected_words": expected,
        "cached_words": cached,
        "missing_words": expected - cached,
        "analysis_unavailable_words": unavailable_words,
        "errors": errors[:100],
        "complete": complete,
        "jsonl_sha256": _reference_sha256(word_reference_path),
        "updated_at_epoch": time.time(),
    }
    WORD_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fetch_word_one(task: dict[str, Any], retries: int, delay: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            value = mcp_call(
                "analyze_word",
                {
                    "surah": task["surah"],
                    "ayah": task["ayah"],
                    "word_no": task["word_no"],
                    "aspects": ["meaning"],
                },
                request_id=f"athar-word-{task['surah']}-{task['ayah']}-{task['word_no']}-{time.time_ns()}",
            )
            if not isinstance(value.get("word"), str):
                # Some tokens (for example isolated disjoint letters) have no
                # lexical analysis. Preserve their canonical position so this
                # appears as an unavailable meaning, not a retryable fetch
                # failure.
                return _unavailable_word_record(task)
            if delay:
                time.sleep(delay)
            return {
                "word_key": task["key"],
                "verse_key": task["verse_key"],
                "surah": task["surah"],
                "ayah": task["ayah"],
                "word_no": task["word_no"],
                "reference_word": task["reference_word"],
                "word": value.get("word"),
                "meaning": value.get("meaning"),
                "irab": value.get("irab"),
                "sarf": value.get("sarf"),
                "root": value.get("root"),
                "frequency": value.get("frequency"),
                "rasm_note": value.get("rasm_note"),
                "meaning_available": bool(value.get("meaning")),
            }
        except Exception as exc:  # network, JSON-RPC, or a missing MCP word
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (2**attempt))
    raise RuntimeError(f"{task['key']}: {last_error}")


def _python_backend_available() -> bool:
    try:
        import tafsir.data_loader  # noqa: F401
    except ImportError:
        return False
    return True


def _harvest_word_meanings_python(
    *,
    tasks: list[dict[str, Any]],
    reference_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    records, database_path, package_version, unavailable = _load_python_word_records(tasks)
    _write_word_reference(output_path, records)
    reference_sha256 = _reference_sha256(reference_path)
    _write_manifest(
        expected=len(tasks),
        cached=len(records),
        errors=[],
        complete=True,
        reference_sha256=reference_sha256,
        word_reference_path=output_path,
        source="python",
        database_path=database_path,
        package_version=package_version,
        unavailable_words=unavailable,
    )
    print(
        f"Official Tafsir MCP database: {len(records):,}/{len(tasks):,} "
        f"word records loaded locally; {unavailable:,} meanings unavailable",
        file=sys.stderr,
    )
    return {
        "path": str(output_path),
        "manifest": str(WORD_MANIFEST_PATH),
        "source": "python",
        "database_path": str(database_path),
        "package_version": package_version,
        "expected_words": len(tasks),
        "cached_words": len(records),
        "missing_words": 0,
        "analysis_unavailable_words": unavailable,
        "errors": 0,
        "complete": True,
    }


def harvest_word_meanings(
    *,
    reference_path: Path = REFERENCE_PATH,
    output_path: Path = WORD_REFERENCE_PATH,
    workers: int = 4,
    retries: int = 3,
    delay: float = 0.15,
    source: str = "auto",
) -> dict[str, Any]:
    reference = load_reference(reference_path)
    expected = _word_tasks(reference)
    if not expected:
        raise RuntimeError("reference snapshot is empty; run --fetch-reference first")
    if source not in {"auto", "python", "http"}:
        raise ValueError("source must be one of: auto, python, http")
    if source == "python" or (source == "auto" and _python_backend_available()):
        try:
            return _harvest_word_meanings_python(
                tasks=expected,
                reference_path=reference_path,
                output_path=output_path,
            )
        except Exception:
            if source == "python":
                raise
            print(
                "Offline Tafsir MCP backend failed; falling back to HTTP harvest.",
                file=sys.stderr,
            )
    existing = load_word_reference(output_path)
    missing = [task for task in expected if task["key"] not in existing]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    reference_sha256 = _reference_sha256(reference_path)
    _write_manifest(
        expected=len(expected),
        cached=len(existing),
        errors=[],
        complete=not missing,
        reference_sha256=reference_sha256,
        word_reference_path=output_path,
        source="http",
    )
    print(f"MCP word meanings: {len(existing)}/{len(expected)} cached; fetching {len(missing)}")
    if missing:
        with output_path.open("a", encoding="utf-8", buffering=1) as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {
                    pool.submit(_fetch_word_one, task, retries, delay): task
                    for task in missing
                }
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    task = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:
                        errors.append(str(exc))
                        continue
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    existing[task["key"]] = row
                    completed += 1
                    if completed % 250 == 0 or completed == len(missing):
                        _write_manifest(
                            expected=len(expected),
                            cached=len(existing),
                            errors=errors,
                            complete=len(existing) == len(expected) and not errors,
                            reference_sha256=reference_sha256,
                            word_reference_path=output_path,
                            source="http",
                        )
                        print(f"MCP word meanings: fetched {completed}/{len(missing)}")
    missing_after = [task["key"] for task in expected if task["key"] not in existing]
    _write_manifest(
        expected=len(expected),
        cached=len(existing),
        errors=errors,
        complete=not missing_after and not errors,
        reference_sha256=reference_sha256,
        word_reference_path=output_path,
        source="http",
    )
    return {
        "path": str(output_path),
        "manifest": str(WORD_MANIFEST_PATH),
        "source": "http",
        "expected_words": len(expected),
        "cached_words": len(existing),
        "missing_words": len(missing_after),
        "errors": len(errors),
        "complete": not missing_after and not errors,
    }


def _local_meaning_rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT id,surah_number,ayah_number,word,meaning "
            "FROM verses ORDER BY surah_number,ayah_number,id"
        ).fetchall()
    finally:
        conn.close()
    for row_id, surah, ayah, word, meaning in rows:
        grouped[f"{int(surah)}:{int(ayah)}"].append({
            "id": int(row_id),
            "surah": int(surah),
            "ayah": int(ayah),
            "word": word or "",
            "meaning": meaning or "",
        })
    return grouped


def _meaning_key(value: Any) -> str:
    # This is a text comparison only.  Equal normalized strings do not prove
    # scholarly equivalence, and unequal strings are sent to human review.
    return " ".join(str(value or "").split())


def compare_word_meanings(
    *,
    reference_path: Path = REFERENCE_PATH,
    word_reference_path: Path = WORD_REFERENCE_PATH,
    local_path: Path = DB_SOURCES["word_name"],
    output_path: Path = COMPARISON_PATH,
) -> dict[str, Any]:
    reference = load_reference(reference_path)
    tasks = _word_tasks(reference)
    mcp_rows = load_word_reference(word_reference_path)
    manifest = load_word_manifest()
    migration = load_word_migration()
    runtime_uses_mcp = bool(
        migration.get("applied")
        and (migration.get("source") or {}).get("jsonl_sha256")
        == _reference_sha256(word_reference_path)
    )
    local_rows = _local_meaning_rows(local_path)
    by_mcp_verse: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for task in tasks:
        row = mcp_rows.get(task["key"])
        if row:
            by_mcp_verse[task["verse_key"]].append(row)
    for rows in by_mcp_verse.values():
        rows.sort(key=lambda row: int(row["word_no"]))

    verse_findings: list[dict[str, Any]] = []
    phrase_findings: list[dict[str, Any]] = []
    word_findings: list[dict[str, Any]] = []
    local_token_count = 0
    local_phrase_count = 0
    phrase_group_count = 0
    comparable_word_count = 0
    meaning_comparison_count = 0
    exact_meaning_count = 0
    meaning_difference_count = 0
    meaning_unavailable_count = 0
    unresolved_alignment_count = 0

    for verse_key in expected_verse_keys():
        mcp = by_mcp_verse.get(verse_key, [])
        local = local_rows.get(verse_key, [])
        local_phrase_count += len(local)
        local_tokens: list[str] = []
        token_spans: list[tuple[int, int]] = []
        for row_index, row in enumerate(local):
            tokens = _split_words(row["word"])
            start = len(local_tokens)
            local_tokens.extend(tokens)
            token_spans.append((start, len(local_tokens)))
            if len(tokens) > 1:
                phrase_group_count += 1
        local_token_count += len(local_tokens)
        mcp_tokens = [
            str(row.get("word") or row.get("reference_word") or "")
            for row in mcp
        ]
        matcher = difflib.SequenceMatcher(
            None,
            [_alignment_key(token) for token in local_tokens],
            [_alignment_key(token) for token in mcp_tokens],
            autojunk=False,
        )
        token_mapping: dict[int, int] = {}
        opcodes = matcher.get_opcodes()
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                token_mapping.update({
                    local_index: mcp_index
                    for local_index, mcp_index in zip(range(i1, i2), range(j1, j2))
                })
        if len(local_tokens) != len(mcp_tokens) or any(tag != "equal" for tag, *_ in opcodes):
            verse_findings.append({
                "level": "verse",
                "verse_key": verse_key,
                "local_phrase_count": len(local),
                "local_token_count": len(local_tokens),
                "mcp_word_count": len(mcp_tokens),
                "opcodes": [
                    {
                        "operation": tag,
                        "local_positions": list(range(i1 + 1, i2 + 1)),
                        "mcp_positions": list(range(j1 + 1, j2 + 1)),
                    }
                    for tag, i1, i2, j1, j2 in opcodes
                    if tag != "equal"
                ],
            })

        for row, (start, end) in zip(local, token_spans):
            positions = [token_mapping[index] for index in range(start, end) if index in token_mapping]
            if len(positions) != end - start or not positions:
                unresolved_alignment_count += 1
                phrase_findings.append({
                    "level": "phrase",
                    "verse_key": verse_key,
                    "local_id": row["id"],
                    "local_word": row["word"],
                    "local_meaning": row["meaning"],
                    "mcp_positions": [position + 1 for position in positions],
                    "status": "alignment_review_required",
                })
                continue
            mcp_slice = [mcp[position] for position in positions]
            if end - start != 1:
                phrase_findings.append({
                    "level": "phrase",
                    "verse_key": verse_key,
                    "local_id": row["id"],
                    "local_word": row["word"],
                    "local_meaning": row["meaning"],
                    "mcp_positions": [position + 1 for position in positions],
                    "mcp_words": [item.get("word") for item in mcp_slice],
                    "mcp_meanings": [item.get("meaning") for item in mcp_slice],
                    "status": "grouped_phrase_review_required",
                })
                continue

            comparable_word_count += 1
            mcp_word = mcp_slice[0]
            if not mcp_word.get("meaning"):
                meaning_unavailable_count += 1
                continue
            meaning_comparison_count += 1
            exact = _meaning_key(row["meaning"]) == _meaning_key(mcp_word["meaning"])
            if exact:
                exact_meaning_count += 1
            else:
                meaning_difference_count += 1
                word_findings.append({
                    "level": "word",
                    "verse_key": verse_key,
                    "word_no": int(mcp_word["word_no"]),
                    "word": mcp_word.get("word"),
                    "local_word": row["word"],
                    "local_meaning": row["meaning"],
                    "mcp_meaning": mcp_word.get("meaning"),
                    "status": "meaning_text_difference",
                })

    result = {
        "schema_version": 1,
        "status": (
            "not_harvested" if not mcp_rows else "review_required"
            if verse_findings or phrase_findings or word_findings or meaning_unavailable_count
            else "no_text_differences"
        ),
        "recommendation": (
            "runtime_uses_mcp_snapshot"
            if runtime_uses_mcp
            else "keep_local_until_human_review"
        ),
        "replacement_approved": runtime_uses_mcp,
        "mcp_source": {
            "tool": "analyze_word",
            "aspects": ["meaning"],
            "path": str(word_reference_path),
            "sha256": _reference_sha256(word_reference_path),
            "reference_sha256": _reference_sha256(reference_path),
            "manifest_complete": bool(manifest.get("complete")),
            "harvest_source": manifest.get("source", "http"),
            "database_path": manifest.get("database_path"),
            "package": manifest.get("package"),
            "package_version": manifest.get("package_version"),
            "analysis_unavailable_words": int(
                manifest.get("analysis_unavailable_words") or 0
            ),
            "runtime_active": runtime_uses_mcp,
        },
        "errors": manifest.get("errors", []),
        "local_source": {
            "path": str(local_path),
            "row_count": sum(len(rows) for rows in local_rows.values()),
            "runtime_uses_mcp": runtime_uses_mcp,
        },
        "runtime_migration": migration or None,
        "coverage": {
            "verse_count": len(expected_verse_keys()),
            "mcp_word_count": len(tasks),
            "mcp_cached_word_count": len(mcp_rows),
            "local_phrase_count": local_phrase_count,
            "local_token_count": local_token_count,
        },
        "verse_level": {
            "finding_count": len(verse_findings),
            "findings": verse_findings[:100],
        },
        "phrase_level": {
            "group_count": phrase_group_count,
            "unresolved_alignment_count": unresolved_alignment_count,
            "findings": phrase_findings[:100],
        },
        "word_level": {
            "comparable_word_count": comparable_word_count,
            "meaning_comparison_count": meaning_comparison_count,
            "exact_text_match_count": exact_meaning_count,
            "meaning_difference_count": meaning_difference_count,
            "meaning_unavailable_count": meaning_unavailable_count,
            "findings": word_findings[:100],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="harvest MCP analyze_word records")
    parser.add_argument("--compare", action="store_true", help="compare MCP records with word_name.db")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--source",
        choices=("auto", "python", "http"),
        default="auto",
        help="word source: official offline package, or remote MCP HTTP",
    )
    args = parser.parse_args(argv)
    if not args.fetch and not args.compare:
        parser.error("choose --fetch, --compare, or both")
    if args.fetch:
        print(json.dumps(
            harvest_word_meanings(
                workers=max(1, args.workers),
                retries=max(0, args.retries),
                delay=max(0.0, args.delay),
                source=args.source,
            ),
            ensure_ascii=False,
            indent=2,
        ))
    if args.compare:
        result = compare_word_meanings()
        print(json.dumps({
            "status": result["status"],
            "output": str(COMPARISON_PATH),
            "verse_findings": result["verse_level"]["finding_count"],
            "phrase_groups": result["phrase_level"]["group_count"],
            "word_meaning_differences": result["word_level"]["meaning_difference_count"],
        }, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "no_text_differences" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
