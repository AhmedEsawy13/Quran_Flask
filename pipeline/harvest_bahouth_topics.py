#!/usr/bin/env python3
"""Harvest Bahouth verse topics and precompute contiguous context spans.

Bahouth MCP is used offline here only.  Flask serves the resulting SQLite DB
with no runtime dependency on https://bahouth.tafsir.net/mcp.

The contiguous-span scorer approximates مصحف التفصيل الموضوعي-style local
discourse blocks: for each ayah, pick the best same-surah topic run containing
that ayah (prefer length 2–20, penalize cross-surah / huge runs).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from pipeline.audit_quran_integrity import MCP_AYAH_COUNTS, expected_verse_keys


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "bahouth-topics"
JSONL_PATH = ARTIFACT_DIR / "verse-topics.jsonl"
MANIFEST_PATH = ARTIFACT_DIR / "verse-topics-manifest.json"
DB_PATH = ROOT / "data" / "verse_topics.db"

BAHOUTH_URL = os.environ.get("BAHOUTH_MCP_URL", "https://bahouth.tafsir.net/mcp")
ATTRIBUTION = "باحوث · مركز تفسير للدراسات القرآنية"


def bahouth_key(surah: int, ayah: int) -> str:
    return f"{surah}-{ayah}"


def athar_key(surah: int, ayah: int) -> str:
    return f"{surah}:{ayah}"


def _parse_rpc_body(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", "replace")
    if "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
        else:
            raise RuntimeError(f"Bahouth SSE had no data event: {text[:400]}")
    else:
        payload = json.loads(text)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload


def bahouth_call(tool_name: str, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        BAHOUTH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rpc = _parse_rpc_body(response.read())
    result = rpc.get("result") or {}
    if result.get("isError"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    content = result.get("content") or []
    text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
    if not text_parts and isinstance(result, dict) and "topics" in result:
        return result
    if not text_parts:
        raise RuntimeError(f"Bahouth response had no text content: {rpc}")
    value = json.loads(text_parts[0])
    if not isinstance(value, dict):
        raise RuntimeError(f"Bahouth tool returned {type(value).__name__}")
    return value


def load_jsonl(path: Path = JSONL_PATH) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = str(row.get("verse_key_colon") or "")
            if key:
                rows[key] = row
    return rows


def _write_manifest(cached: int, errors: list[str], complete: bool) -> None:
    expected = sum(MCP_AYAH_COUNTS.values())
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "source": "bahouth",
                "url": BAHOUTH_URL,
                "tool": "list_verse_topics",
                "expected_ayahs": expected,
                "cached_ayahs": cached,
                "missing_ayahs": expected - cached,
                "errors": errors[:100],
                "complete": complete,
                "updated_at_epoch": time.time(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def harvest_topics(workers: int = 8, retries: int = 3, delay: float = 0.05) -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_jsonl()
    keys = expected_verse_keys()
    missing = [key for key in keys if key not in existing]
    errors: list[str] = []

    def one(verse_key_colon: str) -> dict[str, Any]:
        surah, ayah = (int(part) for part in verse_key_colon.split(":"))
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                payload = bahouth_call(
                    "list_verse_topics",
                    {"verse_key": bahouth_key(surah, ayah)},
                    request_id=f"topics-{verse_key_colon}-{attempt}",
                )
                topics = payload.get("topics") or []
                return {
                    "verse_key_colon": verse_key_colon,
                    "verse_key_bahouth": bahouth_key(surah, ayah),
                    "surah": surah,
                    "ayah": ayah,
                    "topics": [
                        {
                            "topic_id": int(t["topic_id"]),
                            "category_id": int(t.get("category_id") or 0),
                            "subcategory_id": int(t.get("subcategory_id") or 0),
                            "title_raw": str(t.get("title_raw") or ""),
                        }
                        for t in topics
                        if t.get("topic_id") is not None
                    ],
                }
            except Exception as exc:  # noqa: BLE001 — harvest must continue
                last_err = exc
                time.sleep(delay * attempt)
        raise RuntimeError(f"{verse_key_colon}: {last_err}")

    if missing:
        with JSONL_PATH.open("a", encoding="utf-8") as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(one, key): key for key in missing}
                done = 0
                for future in concurrent.futures.as_completed(futures):
                    key = futures[future]
                    done += 1
                    try:
                        row = future.result()
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                        handle.flush()
                        existing[key] = row
                    except Exception as exc:  # noqa: BLE001
                        errors.append(str(exc))
                    if done % 100 == 0 or done == len(missing):
                        print(f"harvested {done}/{len(missing)} missing ({len(existing)} cached)")

    complete = len(existing) == len(keys) and not errors
    _write_manifest(len(existing), errors, complete)
    return {
        "cached": len(existing),
        "expected": len(keys),
        "errors": len(errors),
        "complete": complete,
    }


def _global_verse_id(surah: int, ayah: int) -> int:
    total = 0
    for s in range(1, surah):
        total += MCP_AYAH_COUNTS[s]
    return total + ayah


def score_span(
    *,
    length: int,
    verse_surah: int,
    start_surah: int,
    end_surah: int,
    title: str,
) -> float:
    same = start_surah == end_surah == verse_surah
    if length == 1:
        base = 1.0
    elif 2 <= length <= 20:
        base = 30.0 + length
    elif length <= 40:
        base = 40.0 - (length - 20)
    else:
        base = 10.0 - min(length - 40, 20)
    if not same:
        base -= 25.0
    depth = title.count(":")
    return base + depth * 2 + min(len(title), 40) / 40.0


def contiguous_run(
    verse_ids: list[int],
    target_id: int,
    id_to_sa: dict[int, tuple[int, int]],
) -> dict[str, int] | None:
    idset = set(verse_ids)
    if target_id not in idset:
        return None
    left = right = target_id
    while left - 1 in idset:
        left -= 1
    while right + 1 in idset:
        right += 1
    start_s, start_a = id_to_sa[left]
    end_s, end_a = id_to_sa[right]
    return {
        "start_surah": start_s,
        "start_ayah": start_a,
        "end_surah": end_s,
        "end_ayah": end_a,
        "run_length": right - left + 1,
    }


def build_database(jsonl_path: Path = JSONL_PATH, db_path: Path = DB_PATH) -> dict[str, Any]:
    rows = load_jsonl(jsonl_path)
    if not rows:
        raise RuntimeError(f"no harvested rows at {jsonl_path}")

    topics: dict[int, dict[str, Any]] = {}
    verse_topic_pairs: list[tuple[int, int, int, int]] = []
    id_to_sa: dict[int, tuple[int, int]] = {}
    topic_to_ids: dict[int, list[int]] = {}

    for key in expected_verse_keys():
        row = rows.get(key)
        if not row:
            continue
        surah = int(row["surah"])
        ayah = int(row["ayah"])
        verse_id = _global_verse_id(surah, ayah)
        id_to_sa[verse_id] = (surah, ayah)
        for topic in row.get("topics") or []:
            tid = int(topic["topic_id"])
            topics[tid] = {
                "topic_id": tid,
                "category_id": int(topic.get("category_id") or 0),
                "subcategory_id": int(topic.get("subcategory_id") or 0),
                "title_raw": str(topic.get("title_raw") or ""),
            }
            verse_topic_pairs.append((surah, ayah, verse_id, tid))
            topic_to_ids.setdefault(tid, []).append(verse_id)

    for tid in topic_to_ids:
        topic_to_ids[tid] = sorted(set(topic_to_ids[tid]))

    spans: list[dict[str, Any]] = []
    for key in expected_verse_keys():
        row = rows.get(key)
        if not row:
            continue
        surah = int(row["surah"])
        ayah = int(row["ayah"])
        verse_id = _global_verse_id(surah, ayah)
        candidates: list[dict[str, Any]] = []
        for topic in row.get("topics") or []:
            tid = int(topic["topic_id"])
            title = str(topic.get("title_raw") or "")
            run = contiguous_run(topic_to_ids.get(tid, []), verse_id, id_to_sa)
            if not run:
                continue
            score = score_span(
                length=run["run_length"],
                verse_surah=surah,
                start_surah=run["start_surah"],
                end_surah=run["end_surah"],
                title=title,
            )
            candidates.append({
                "topic_id": tid,
                "title_raw": title,
                "score": score,
                **run,
            })
        if not candidates:
            spans.append({
                "surah": surah,
                "ayah": ayah,
                "topic_id": None,
                "title_raw": "",
                "start_surah": surah,
                "start_ayah": ayah,
                "end_surah": surah,
                "end_ayah": ayah,
                "run_length": 1,
                "score": 0.0,
            })
            continue
        best = max(candidates, key=lambda item: item["score"])
        spans.append({
            "surah": surah,
            "ayah": ayah,
            "topic_id": best["topic_id"],
            "title_raw": best["title_raw"],
            "start_surah": best["start_surah"],
            "start_ayah": best["start_ayah"],
            "end_surah": best["end_surah"],
            "end_ayah": best["end_ayah"],
            "run_length": best["run_length"],
            "score": best["score"],
        })

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".db.tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = DELETE;
            CREATE TABLE topics (
                topic_id INTEGER PRIMARY KEY,
                category_id INTEGER NOT NULL,
                subcategory_id INTEGER NOT NULL,
                title_raw TEXT NOT NULL
            );
            CREATE TABLE verse_topics (
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                verse_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                PRIMARY KEY (surah, ayah, topic_id)
            );
            CREATE INDEX idx_verse_topics_topic ON verse_topics(topic_id, verse_id);
            CREATE TABLE context_spans (
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                topic_id INTEGER,
                title_raw TEXT NOT NULL,
                start_surah INTEGER NOT NULL,
                start_ayah INTEGER NOT NULL,
                end_surah INTEGER NOT NULL,
                end_ayah INTEGER NOT NULL,
                run_length INTEGER NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (surah, ayah)
            );
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO topics(topic_id, category_id, subcategory_id, title_raw) VALUES (?,?,?,?)",
            [
                (t["topic_id"], t["category_id"], t["subcategory_id"], t["title_raw"])
                for t in topics.values()
            ],
        )
        conn.executemany(
            "INSERT INTO verse_topics(surah, ayah, verse_id, topic_id) VALUES (?,?,?,?)",
            verse_topic_pairs,
        )
        conn.executemany(
            """
            INSERT INTO context_spans(
                surah, ayah, topic_id, title_raw,
                start_surah, start_ayah, end_surah, end_ayah, run_length, score
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    s["surah"],
                    s["ayah"],
                    s["topic_id"],
                    s["title_raw"],
                    s["start_surah"],
                    s["start_ayah"],
                    s["end_surah"],
                    s["end_ayah"],
                    s["run_length"],
                    s["score"],
                )
                for s in spans
            ],
        )
        multi = sum(1 for s in spans if s["run_length"] >= 2)
        meta = {
            "source_provider": "Bahouth Quranic Linguistic",
            "source_tool": "list_verse_topics",
            "source_url": BAHOUTH_URL,
            "attribution": ATTRIBUTION,
            "verse_count": str(len(spans)),
            "topic_count": str(len(topics)),
            "multi_ayah_span_count": str(multi),
            "built_at_epoch": str(time.time()),
        }
        conn.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        conn.commit()
    finally:
        conn.close()
    tmp.replace(db_path)
    return {
        "db_path": str(db_path),
        "verse_count": len(spans),
        "topic_count": len(topics),
        "multi_ayah_span_count": multi,
        "attribution": ATTRIBUTION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harvest", action="store_true", help="Fetch/resume Bahouth topics")
    parser.add_argument("--build-db", action="store_true", help="Build data/verse_topics.db")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args(argv)

    if not args.harvest and not args.build_db:
        args.harvest = True
        args.build_db = True

    if args.harvest:
        report = harvest_topics(workers=args.workers, retries=args.retries)
        print(json.dumps({"harvest": report}, ensure_ascii=False, indent=2))
        if not report["complete"]:
            print("harvest incomplete; re-run --harvest to resume", file=sys.stderr)
            if args.build_db and report["cached"] < report["expected"]:
                return 1

    if args.build_db:
        report = build_database()
        print(json.dumps({"database": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
