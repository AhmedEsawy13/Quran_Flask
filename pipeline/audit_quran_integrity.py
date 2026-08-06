#!/usr/bin/env python3
"""Exhaustive Quran text, word-key, and mushaf-layout integrity audit.

The audit uses a one-time snapshot of the Tafsir Center MCP ``fetch_ayah``
responses as its external reference.  The snapshot is intentionally an
ignored artifact: the Flask application never depends on MCP at request time.

Examples:

    python3 pipeline/audit_quran_integrity.py --fetch-reference
    python3 pipeline/audit_quran_integrity.py --audit
    python3 pipeline/audit_quran_integrity.py --fetch-reference --audit

The script is read-only with respect to shipped Quran databases.  It writes
only the ignored reference/report artifacts under ``artifacts/``.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import difflib
from functools import lru_cache
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MCP_URL = os.environ.get("TAFSIR_MCP_URL", "https://mcp.tafsir.net/mcp")
REFERENCE_PATH = ROOT / "artifacts" / "quran-integrity" / "mcp-ayah-reference.jsonl"
MANIFEST_PATH = ROOT / "artifacts" / "quran-integrity" / "mcp-reference-manifest.json"
CANDIDATE_MAPPING_PATH = ROOT / "artifacts" / "quran-integrity" / "quran-script-candidate-mapping.json"
CANDIDATE_DB_PATH = ROOT / "artifacts" / "quran-integrity" / "quran_script_candidate.db"
LAYOUT_CANDIDATE_PATH = ROOT / "artifacts" / "quran-integrity" / "layout-candidate-repairs.json"
REPORT_PATH = ROOT / "artifacts" / "quran-integrity" / "integrity-report.json"

MCP_TOTAL_SURAHS = 114
MCP_TOTAL_AYAHS = 6236
MCP_TOTAL_WORDS = 77432
# Harvested from Tafsir MCP ``fetch_surah_info``/``quran://surahs``.  Keeping
# the boundary manifest in the audit code makes an offline audit deterministic
# after the ayah snapshot has been downloaded.
MCP_AYAH_COUNTS = {
    1: 7, 2: 286, 3: 200, 4: 176, 5: 120, 6: 165, 7: 206, 8: 75,
    9: 129, 10: 109, 11: 123, 12: 111, 13: 43, 14: 52, 15: 99,
    16: 128, 17: 111, 18: 110, 19: 98, 20: 135, 21: 112, 22: 78,
    23: 118, 24: 64, 25: 77, 26: 227, 27: 93, 28: 88, 29: 69,
    30: 60, 31: 34, 32: 30, 33: 73, 34: 54, 35: 45, 36: 83,
    37: 182, 38: 88, 39: 75, 40: 85, 41: 54, 42: 53, 43: 89,
    44: 59, 45: 37, 46: 35, 47: 38, 48: 29, 49: 18, 50: 45,
    51: 60, 52: 49, 53: 62, 54: 55, 55: 78, 56: 96, 57: 29,
    58: 22, 59: 24, 60: 13, 61: 14, 62: 11, 63: 11, 64: 18,
    65: 12, 66: 12, 67: 30, 68: 52, 69: 52, 70: 44, 71: 28,
    72: 28, 73: 20, 74: 56, 75: 40, 76: 31, 77: 50, 78: 40,
    79: 46, 80: 42, 81: 29, 82: 19, 83: 36, 84: 25, 85: 22,
    86: 17, 87: 19, 88: 26, 89: 30, 90: 20, 91: 15, 92: 21,
    93: 11, 94: 8, 95: 8, 96: 19, 97: 5, 98: 8, 99: 8, 100: 11,
    101: 11, 102: 8, 103: 3, 104: 9, 105: 5, 106: 4, 107: 7,
    108: 3, 109: 6, 110: 3, 111: 5, 112: 4, 113: 5, 114: 6,
}

ARABIC_DIGITS = set("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹")
WAQF_MARKS = set("ۖۗۘۙۚۛۜ۟۠ۡۢۤۥۦ۪۫۬ؕؔؗ")
STRUCTURAL_MARKS = set("۝۩۞")
DROP_CODEPOINTS = WAQF_MARKS | STRUCTURAL_MARKS | {"ـ", "\u00a0"}
PRESENTATION_PUNCTUATION = set("/-.,،؛؟")
LETTER_FOLD = {
    "ٱ": "ا",
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ء": "ا",
    "ى": "ي",
    "ئ": "ا",
    "ؤ": "ا",
    "ة": "ه",
    "ی": "ي",
    "ے": "ي",
    "ک": "ك",
    "ہ": "ه",
}

JSON_SOURCES = {
    "digital_khatt": ROOT / "data" / "quran_text" / "Digital_Khatt_Aya_Space.json",
    "qpc_hafs": ROOT / "data" / "quran_text" / "QPC Hafs.json",
    "indopak": ROOT / "data" / "quran_text" / "Indopak Nastaleeq_Waqf.json",
    "transliteration": ROOT / "data" / "quran_text" / "Transliteration.json",
}
TANZIL_PATH = ROOT / "data" / "quran_text" / "quran-uthmani.txt"

DB_SOURCES = {
    "quran_script": ROOT / "data" / "quran_script.db",
    "word_name": ROOT / "data" / "word_name.db",
    "waqf_symbols": ROOT / "data" / "waqf_symbols.db",
    "mushaf_waqf": ROOT / "data" / "mushaf_waqf.db",
    "classical_waqf": ROOT / "data" / "classical_waqf.db",
}

LAYOUT_SOURCES = {
    "digital_khatt": ROOT / "data" / "digital-khatt-15-lines.db",
    "qpc_v4": ROOT / "data" / "qpc-v4-15-lines.db",
    "qpc_v1": ROOT / "data" / "qpc-v1-15-lines.db",
    "qatar": ROOT / "data" / "mushaf-qatar-layout.db",
    "bahrain": ROOT / "data" / "mushaf-bahrain-layout.db",
    "shamarly": ROOT / "data" / "mushaf_layout_inferred.db",
    "azhar": ROOT / "data" / "mushaf-azhar-layout.db",
    "mesaha": ROOT / "data" / "mushaf-mesaha-layout.db",
}


def _json_load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def expected_verse_keys() -> list[str]:
    """Return the expected 6236 keys from the MCP surah boundary manifest."""
    keys: list[str] = []
    for surah, count in MCP_AYAH_COUNTS.items():
        keys.extend(f"{surah}:{ayah}" for ayah in range(1, count + 1))
    return keys


def _sse_json(raw: bytes) -> dict[str, Any]:
    """Extract the first JSON-RPC response from an MCP SSE response."""
    text = raw.decode("utf-8", "replace")
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line[5:].strip())
        if "error" in payload:
            raise RuntimeError(str(payload["error"]))
        return payload
    raise RuntimeError(f"MCP returned no data event: {text[:500]}")


def mcp_call(tool_name: str, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Call one Tafsir MCP tool over its stateless streamable HTTP endpoint."""
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
        MCP_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rpc = _sse_json(response.read())
    result = rpc.get("result") or {}
    if result.get("isError"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    content = result.get("content") or []
    text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
    if not text_parts:
        raise RuntimeError(f"MCP response had no text content: {rpc}")
    try:
        value = json.loads(text_parts[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MCP tool returned non-JSON content: {text_parts[0][:500]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"MCP tool returned {type(value).__name__}, expected object")
    return value


def _fetch_reference_one(key: str, retries: int, delay: float) -> dict[str, Any]:
    surah, ayah = (int(part) for part in key.split(":"))
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            value = mcp_call(
                "fetch_ayah",
                {"surah": surah, "ayah": ayah},
                request_id=f"athar-{surah}-{ayah}-{time.time_ns()}",
            )
            if value.get("surah") != surah or value.get("ayah") != ayah:
                raise RuntimeError(f"wrong MCP key for {key}: {value.get('surah')}:{value.get('ayah')}")
            if not isinstance(value.get("text"), str):
                raise RuntimeError(f"MCP text missing for {key}")
            if not isinstance(value.get("word_count"), int):
                raise RuntimeError(f"MCP word_count missing for {key}")
            return {
                "surah": surah,
                "ayah": ayah,
                "verse_key": key,
                "text": value["text"],
                "text_uthmani": value.get("text_uthmani"),
                "text_simple": value.get("text_simple"),
                "word_count": value["word_count"],
            }
        except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (2**attempt))
    raise RuntimeError(f"{key}: {last_error}")


def load_reference(path: Path) -> dict[str, dict[str, Any]]:
    """Load only successful, structurally valid records; tolerate partial files."""
    result: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
                key = str(row["verse_key"])
                if (
                    row.get("surah") == int(key.split(":")[0])
                    and row.get("ayah") == int(key.split(":")[1])
                    and isinstance(row.get("text"), str)
                    and isinstance(row.get("word_count"), int)
                ):
                    result[key] = row
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                print(f"warning: ignoring malformed reference line {line_number}", file=sys.stderr)
    return result


def _reference_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_reference_manifest(
    path: Path,
    *,
    cached: int,
    expected: int,
    errors: list[str],
    complete: bool,
) -> None:
    manifest = {
        "schema_version": 1,
        "mcp_url": MCP_URL,
        "tool": "fetch_ayah",
        "expected_surahs": MCP_TOTAL_SURAHS,
        "expected_ayahs": expected,
        "expected_words": MCP_TOTAL_WORDS,
        "cached_ayahs": cached,
        "missing_ayahs": expected - cached,
        "errors": errors[:100],
        "complete": complete,
        "jsonl_sha256": _reference_sha256(path),
        "updated_at_epoch": time.time(),
    }
    manifest_path = path.with_name(MANIFEST_PATH.name)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def harvest_reference(path: Path, workers: int, retries: int, delay: float) -> dict[str, Any]:
    keys = expected_verse_keys()
    if len(keys) != MCP_TOTAL_AYAHS:
        raise RuntimeError(f"local surah index has {len(keys)} keys, expected {MCP_TOTAL_AYAHS}")
    existing = load_reference(path)
    missing = [key for key in keys if key not in existing]
    path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    _write_reference_manifest(
        path,
        cached=len(existing),
        expected=len(keys),
        errors=[],
        complete=not missing,
    )
    print(f"MCP reference: {len(existing)}/{len(keys)} cached; fetching {len(missing)}")
    if missing:
        with path.open("a", encoding="utf-8", buffering=1) as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {
                    pool.submit(_fetch_reference_one, key, retries, delay): key
                    for key in missing
                }
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    key = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:
                        errors.append(str(exc))
                        continue
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    existing[key] = row
                    completed += 1
                    if completed % 100 == 0 or completed == len(missing):
                        _write_reference_manifest(
                            path,
                            cached=len(existing),
                            expected=len(keys),
                            errors=errors,
                            complete=len(existing) == len(keys) and not errors,
                        )
                        print(f"MCP reference: fetched {completed}/{len(missing)}")
    missing_after = [key for key in keys if key not in existing]
    _write_reference_manifest(
        path,
        cached=len(existing),
        expected=len(keys),
        errors=errors,
        complete=not missing_after and not errors,
    )
    return {
        "expected": len(keys),
        "cached": len(existing),
        "missing": missing_after,
        "errors": errors[:100],
        "complete": not missing_after and not errors,
    }


@lru_cache(maxsize=100_000)
def _strip_comparison_noise(
    text: str,
    *,
    expand_small_alif: bool = False,
    collapse_waw_small_alif: bool = False,
    expand_shadda: bool = False,
) -> str:
    """Fold presentation differences without inventing a new orthography."""
    out: list[str] = []
    # NFC first composes source spellings such as أ/ئ into أ/ئ.  A
    # decomposed hamza that cannot compose (for example رٔ) is retained as the
    # consonant ء instead of being mistaken for a vowel mark.
    normalized_text = unicodedata.normalize("NFC", text or "")
    if collapse_waw_small_alif:
        normalized_text = re.sub(
            r"و[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u08d3-\u08ff\u034f]*ٰ",
            "ا",
            normalized_text,
        )
    chars = list(normalized_text)
    for index, char in enumerate(chars):
        if (
            char in DROP_CODEPOINTS
            or char in ARABIC_DIGITS
            or char in PRESENTATION_PUNCTUATION
        ):
            continue
        if char == "ٰ" and expand_small_alif:
            # Small alif is a Quranic orthographic mark, but it represents
            # the alif in the plain MCP word skeleton (e.g. كَتَٰب).
            out.append("ا")
            continue
        if char == "ٰ":
            continue
        if char == "\u0654":
            next_base_index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(chars[index + 1:], index + 1)
                    if candidate not in DROP_CODEPOINTS
                    and candidate not in ARABIC_DIGITS
                    and not unicodedata.combining(candidate)
                    and not unicodedata.category(candidate).startswith("M")
                ),
                None,
            )
            next_base = (
                chars[next_base_index] if next_base_index is not None else None
            )
            between = (
                chars[index + 1:next_base_index]
                if next_base_index is not None
                else []
            )
            # Digital Khatt writes the hamza above a following alif as
            # tatweel + combining hamza + alif; NFC cannot compose that form.
            # A tanween carrier alif after the hamza is different: preserve
            # the hamza in words such as شيئا.
            if next_base in {"ا", "ٱ"} and not between:
                continue
            if "ٰ" in between:
                out.append("ا")
                continue
            out.append("ا")
            continue
        if char == "ء":
            next_base = next(
                (
                    candidate
                    for candidate in chars[index + 1:]
                    if candidate not in DROP_CODEPOINTS
                    and candidate not in ARABIC_DIGITS
                    and not unicodedata.combining(candidate)
                    and not unicodedata.category(candidate).startswith("M")
                ),
                None,
            )
            if next_base == "ا":
                # The source spelling ءا corresponds to plain آ.
                continue
            if next_base in {"أ", "إ", "آ"}:
                out.append("ا")
                continue
        if char == "\u0651" and expand_shadda and out:
            out.append(out[-1])
            continue
        if unicodedata.combining(char) or unicodedata.category(char).startswith("M"):
            continue
        if 0xE000 <= ord(char) <= 0xF8FF:
            continue
        out.append(LETTER_FOLD.get(char, char))
    return "".join(out)


@lru_cache(maxsize=100_000)
def _word_variants(text: str) -> frozenset[str]:
    variants: set[str] = set()
    for expand_shadda in (False, True):
        for expand_small_alif in (False, True):
            for collapse_waw in (False, True):
                value = _strip_comparison_noise(
                    text,
                    expand_small_alif=expand_small_alif,
                    collapse_waw_small_alif=collapse_waw,
                    expand_shadda=expand_shadda,
                )
                variants.add(value)
                if value.endswith("ت"):
                    variants.add(value[:-1] + "ه")
                if value.endswith("ءوا"):
                    variants.add(value[:-3] + "ء")
                if value.endswith("ءا"):
                    variants.add(value[:-2] + "ء")
                variants.add("".join(char for char in value if char not in "اوي"))
    return frozenset(variants)


def _alignment_key(text: str) -> str:
    """Stable loose key for candidate sequence alignment only."""
    return min(_word_variants(text), key=lambda value: (len(value), value))


def _token_is_marker(token: str) -> bool:
    return not _strip_comparison_noise(token)


def _split_words(text: str, *, drop_leading_basmala: bool = False) -> list[str]:
    tokens = [token for token in re.split(r"\s+", (text or "").strip()) if token]
    if drop_leading_basmala and len(tokens) >= 5:
        first = _strip_comparison_noise(tokens[0])
        if first.startswith("بسم"):
            tokens = tokens[4:]
    return [token for token in tokens if not _token_is_marker(token)]


def _reference_words(row: dict[str, Any]) -> list[str]:
    return _split_words(str(row.get("text") or ""))


def _compare_words(actual: list[str], expected: list[str]) -> dict[str, Any]:
    actual_norm = [_strip_comparison_noise(word) for word in actual]
    expected_norm = [_strip_comparison_noise(word) for word in expected]
    actual_variants = [_word_variants(word) for word in actual]
    expected_variants = [_word_variants(word) for word in expected]
    normalization_variants = (
        {
            "expand_small_alif": expand_small_alif,
            "collapse_waw_small_alif": collapse_waw,
            "expand_shadda": expand_shadda,
        }
        for expand_shadda in (False, True)
        for expand_small_alif in (False, True)
        for collapse_waw in (False, True)
    )
    normalization_variants = tuple(normalization_variants)
    skeleton_match = any(
        "".join(
            _strip_comparison_noise(
                word,
                expand_small_alif=actual_options["expand_small_alif"],
                collapse_waw_small_alif=actual_options["collapse_waw_small_alif"],
            )
            for word in actual
        )
        == "".join(
            _strip_comparison_noise(
                word,
                expand_small_alif=expected_options["expand_small_alif"],
                collapse_waw_small_alif=expected_options["collapse_waw_small_alif"],
            )
            for word in expected
        )
        for actual_options in normalization_variants
        for expected_options in normalization_variants
    )
    mismatches = []
    strict_mismatches = []
    normalization_only_count = 0
    for index in range(max(len(actual_norm), len(expected_norm))):
        left = actual_norm[index] if index < len(actual_norm) else None
        right = expected_norm[index] if index < len(expected_norm) else None
        equivalent = (
            index < len(actual_variants)
            and index < len(expected_variants)
            and bool(actual_variants[index] & expected_variants[index])
        )
        strict_equal = (
            index < len(actual_norm)
            and index < len(expected_norm)
            and actual_norm[index] == expected_norm[index]
        )
        if not strict_equal:
            strict_mismatches.append(
                {
                    "position": index + 1,
                    "actual": actual[index] if index < len(actual) else None,
                    "expected": expected[index] if index < len(expected) else None,
                }
            )
            if equivalent:
                normalization_only_count += 1
        if not equivalent:
            mismatches.append(
                {
                    "position": index + 1,
                    "actual": actual[index] if index < len(actual) else None,
                    "expected": expected[index] if index < len(expected) else None,
                }
            )
            if len(mismatches) >= 20:
                break
    tokenization_only = skeleton_match and (
        bool(mismatches) or len(actual) != len(expected)
    )
    return {
        "actual_count": len(actual),
        "expected_count": len(expected),
        "count_match": len(actual) == len(expected),
        "word_skeleton_match": skeleton_match,
        "tokenization_only": tokenization_only,
        "word_match": not mismatches and len(actual) == len(expected),
        "strict_mismatch_count": len(strict_mismatches),
        "normalization_only_count": normalization_only_count,
        "strict_mismatches": strict_mismatches[:20],
        "mismatches": mismatches,
    }


def load_tanzil() -> dict[str, str]:
    result: dict[str, str] = {}
    if not TANZIL_PATH.exists():
        return result
    with TANZIL_PATH.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            try:
                surah, ayah = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            result[f"{surah}:{ayah}"] = parts[2]
    return result


def source_words(source: str, key: str, value: Any) -> list[str]:
    text = value.get("text", "") if isinstance(value, dict) else str(value or "")
    if source == "tanzil":
        surah, ayah = (int(part) for part in key.split(":"))
        return _split_words(
            text,
            drop_leading_basmala=ayah == 1 and surah not in (1, 9),
        )
    return _split_words(text)


def audit_json_sources(reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = set(reference)
    reports: dict[str, Any] = {}
    for name, path in JSON_SOURCES.items():
        if not path.exists():
            reports[name] = {"status": "missing_file", "path": str(path)}
            continue
        data = _json_load(path)
        keys = set(data) if isinstance(data, dict) else set()
        if name == "transliteration":
            reports[name] = {
                "path": str(path),
                "verse_count": len(keys),
                "missing_verses": sorted(expected - keys),
                "extra_verses": sorted(keys - expected),
                "status": "ok" if keys == expected else "mismatch",
            }
            continue
        mismatches = []
        tokenization_variances = []
        normalization_variances = []
        metadata_errors = []
        seen_ids: collections.Counter[int] = collections.Counter()
        for key, value in data.items() if isinstance(data, dict) else []:
            if not isinstance(value, dict):
                metadata_errors.append({"verse_key": key, "reason": "value_not_object"})
                continue
            if value.get("verse_key") not in (None, key):
                metadata_errors.append({
                    "verse_key": key,
                    "embedded_verse_key": value.get("verse_key"),
                })
            if "surah" in value and "ayah" in value:
                try:
                    embedded = f"{int(value['surah'])}:{int(value['ayah'])}"
                except (TypeError, ValueError):
                    embedded = None
                if embedded != key:
                    metadata_errors.append({
                        "verse_key": key,
                        "embedded_surah_ayah": embedded,
                    })
            if isinstance(value.get("id"), int):
                seen_ids[value["id"]] += 1
        for key in sorted(expected & keys, key=lambda value: tuple(map(int, value.split(":")))):
            actual = source_words(name, key, data[key])
            check = _compare_words(actual, _reference_words(reference[key]))
            if check["tokenization_only"]:
                tokenization_variances.append({"verse_key": key, **check})
            elif not check["word_match"]:
                mismatches.append({"verse_key": key, **check})
            if check["normalization_only_count"]:
                normalization_variances.append({"verse_key": key, **check})
        reports[name] = {
            "path": str(path),
            "verse_count": len(keys),
            "missing_verses": sorted(expected - keys),
            "extra_verses": sorted(keys - expected),
            "word_mismatch_count": len(mismatches),
            "word_mismatches": mismatches[:100],
            "tokenization_variance_count": len(tokenization_variances),
            "tokenization_variances": tokenization_variances[:100],
            "normalization_variance_count": len(normalization_variances),
            "normalization_variances": normalization_variances[:100],
            "metadata_error_count": len(metadata_errors),
            "metadata_errors": metadata_errors[:100],
            "duplicate_id_count": sum(count - 1 for count in seen_ids.values() if count > 1),
            "status": "ok" if (
                keys == expected
                and not mismatches
                and not metadata_errors
                and not any(count > 1 for count in seen_ids.values())
            ) else "mismatch",
        }

    tanzil = load_tanzil()
    mismatches = []
    tokenization_variances = []
    normalization_variances = []
    for key in sorted(expected & set(tanzil), key=lambda value: tuple(map(int, value.split(":")))):
        check = _compare_words(source_words("tanzil", key, tanzil[key]), _reference_words(reference[key]))
        if check["tokenization_only"]:
            tokenization_variances.append({"verse_key": key, **check})
        elif not check["word_match"]:
            mismatches.append({"verse_key": key, **check})
        if check["normalization_only_count"]:
            normalization_variances.append({"verse_key": key, **check})
    reports["tanzil_uthmani"] = {
        "path": str(TANZIL_PATH),
        "verse_count": len(tanzil),
        "missing_verses": sorted(expected - set(tanzil)),
        "extra_verses": sorted(set(tanzil) - expected),
        "word_mismatch_count": len(mismatches),
        "word_mismatches": mismatches[:100],
        "tokenization_variance_count": len(tokenization_variances),
        "tokenization_variances": tokenization_variances[:100],
        "normalization_variance_count": len(normalization_variances),
        "normalization_variances": normalization_variances[:100],
        "status": "ok" if set(tanzil) == expected and not mismatches else "mismatch",
    }
    return reports


def _ro_connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


def _sample(values: Iterable[Any], limit: int = 100) -> list[Any]:
    return list(values)[:limit]


def _parse_word_key(value: str) -> tuple[int, int, int] | None:
    parts = str(value or "").split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def audit_quran_script(path: Path, reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT word_index,word_key,surah,ayah,text,text_original "
            "FROM words ORDER BY word_index"
        ).fetchall()
    finally:
        conn.close()
    by_key: dict[tuple[int, int, int], list[dict[str, Any]]] = collections.defaultdict(list)
    by_id: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    by_verse: dict[tuple[int, int], list[dict[str, Any]]] = collections.defaultdict(list)
    malformed = []
    for word_id, word_key, surah, ayah, text, text_original in rows:
        key = _parse_word_key(word_key)
        row = {
            "word_index": int(word_id),
            "word_key": word_key,
            "surah": int(surah),
            "ayah": int(ayah),
            "text": text or "",
            "text_original": text_original or "",
        }
        if key is None or key[:2] != (int(surah), int(ayah)):
            malformed.append(row)
            continue
        by_key[key].append(row)
        by_id[int(word_id)].append(row)
        by_verse[key[:2]].append(row)

    verse_mismatches = []
    for key, reference_row in reference.items():
        s, a = (int(part) for part in key.split(":"))
        local = sorted(
            (row for row in by_verse.get((s, a), []) if not _token_is_marker(row["text"])),
            key=lambda row: (_parse_word_key(row["word_key"]) or (s, a, 0))[2],
        )
        check = _compare_words(
            [row["text"] for row in local],
            _reference_words(reference_row),
        )
        if not check["word_match"]:
            verse_mismatches.append({"verse_key": key, **check})

    duplicate_keys = [key for key, values in by_key.items() if len(values) > 1]
    duplicate_ids = [key for key, values in by_id.items() if len(values) > 1]
    local_verses = {f"{surah}:{ayah}" for surah, ayah in by_verse}
    expected_verses = set(reference)
    canonical_rows = sorted(
        rows,
        key=lambda row: (
            int(row[2]),
            int(row[3]),
            (_parse_word_key(row[1]) or (int(row[2]), int(row[3]), 0))[2],
            int(row[0]),
        ),
    )
    canonical_position = {
        int(row[0]): position for position, row in enumerate(canonical_rows)
    }
    id_order_violations = []
    previous_position: int | None = None
    for row in rows:
        position = canonical_position[int(row[0])]
        if previous_position is not None and position < previous_position:
            id_order_violations.append({
                "word_index": int(row[0]),
                "word_key": row[1],
                "canonical_position": position,
                "previous_canonical_position": previous_position,
            })
        previous_position = position
    missing_positions = []
    for verse, verse_rows in by_verse.items():
        positions = sorted(
            (_parse_word_key(row["word_key"]) or verse + (0,))[2]
            for row in verse_rows
        )
        if positions and positions != list(range(1, max(positions) + 1)):
            missing_positions.append({
                "verse_key": f"{verse[0]}:{verse[1]}",
                "positions": positions,
            })
    content_row_count = sum(
        not _token_is_marker(row[4] or "") for row in rows
    )
    marker_verses = {
        f"{row[2]}:{row[3]}"
        for row in rows
        if any(char in ARABIC_DIGITS for char in str(row[4] or ""))
    }
    waqf_orphans = []
    waqf_rows: list[tuple[Any, ...]] = []
    conn = _ro_connect(path)
    try:
        if _table_exists(conn, "waqf"):
            waqf_rows = conn.execute(
                "SELECT word_index,waqf_char,waqf_type FROM waqf"
            ).fetchall()
    finally:
        conn.close()
    known_ids = set(by_id)
    for word_id, waqf_char, waqf_type in waqf_rows:
        if int(word_id) not in known_ids:
            waqf_orphans.append({
                "word_index": word_id,
                "waqf_char": waqf_char,
                "waqf_type": waqf_type,
            })
    return {
        "path": str(path),
        "row_count": len(rows),
        "verse_count": len(local_verses),
        "missing_verses": sorted(expected_verses - local_verses),
        "extra_verses": sorted(local_verses - expected_verses),
        "content_row_count": content_row_count,
        "reference_content_word_count": sum(
            int(row["word_count"]) for row in reference.values()
        ),
        "marker_verse_count": len(marker_verses),
        "max_word_index": max((int(row[0]) for row in rows), default=None),
        "duplicate_word_keys": _sample(sorted(duplicate_keys)),
        "duplicate_word_ids": _sample(sorted(duplicate_ids)),
        "malformed_word_keys": _sample(malformed),
        "missing_word_positions": _sample(missing_positions),
        "id_order_violation_count": len(id_order_violations),
        "id_order_violations": _sample(id_order_violations),
        "verse_word_mismatch_count": len(verse_mismatches),
        "verse_word_mismatches": verse_mismatches[:100],
        "waqf_row_count": len(waqf_rows),
        "waqf_orphan_count": len(waqf_orphans),
        "waqf_orphans": _sample(waqf_orphans),
        "status": "ok" if (
            not duplicate_keys
            and not duplicate_ids
            and not malformed
            and local_verses == expected_verses
            and not missing_positions
            and not id_order_violations
            and content_row_count == sum(
                int(row["word_count"]) for row in reference.values()
            )
            and not verse_mismatches
            and not waqf_orphans
        ) else "mismatch",
    }


def build_quran_script_candidate_mapping(
    path: Path,
    reference: dict[str, dict[str, Any]],
    reference_sha256: str,
    output_path: Path,
) -> dict[str, Any]:
    """Write a non-live mapping report for the legacy token namespace.

    Exact normalized runs are deliberately omitted.  Only joins/splits and
    unresolved replacement/insert/delete runs are emitted, so a reviewer can
    distinguish a deterministic tokenization repair from a guessed rewrite.
    """
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT word_index,word_key,surah,ayah,text FROM words "
            "ORDER BY surah,ayah,word_index"
        ).fetchall()
    finally:
        conn.close()
    by_verse: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    all_by_verse: dict[str, list[tuple[Any, ...]]] = collections.defaultdict(list)
    marker_anomalies = []
    for word_index, word_key, surah, ayah, text in rows:
        row = {
            "word_index": int(word_index),
            "word_key": word_key,
            "text": text or "",
        }
        key = f"{surah}:{ayah}"
        all_by_verse[key].append((word_index, word_key, surah, ayah, text))
        if not _token_is_marker(row["text"]):
            by_verse[key].append(row)

    joins: list[dict[str, Any]] = []
    splits: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for key, reference_row in reference.items():
        local = by_verse.get(key, [])
        actual = [_alignment_key(row["text"]) for row in local]
        expected = [_alignment_key(word) for word in _reference_words(reference_row)]
        matcher = difflib.SequenceMatcher(None, actual, expected, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            local_text = [row["text"] for row in local[i1:i2]]
            expected_text = _reference_words(reference_row)[j1:j2]
            local_skeleton = "".join(actual[i1:i2])
            expected_skeleton = "".join(expected[j1:j2])
            entry = {
                "verse_key": key,
                "local_word_indices": [row["word_index"] for row in local[i1:i2]],
                "local_word_keys": [row["word_key"] for row in local[i1:i2]],
                "local_text": local_text,
                "reference_positions": list(range(j1 + 1, j2 + 1)),
                "reference_text": expected_text,
                "opcode": tag,
            }
            if tag == "replace" and len(local_text) == 1 and len(expected_text) > 1:
                if local_skeleton == expected_skeleton:
                    joins.append(entry)
                    continue
            if tag == "replace" and len(expected_text) == 1 and len(local_text) > 1:
                if local_skeleton == expected_skeleton:
                    splits.append(entry)
                    continue
            unresolved.append(entry)

        verse_rows = all_by_verse.get(key, [])
        digit_bearing = [
            row for row in verse_rows
            if any(char in ARABIC_DIGITS for char in str(row[4] or ""))
        ]
        if len(digit_bearing) != 1:
            marker_anomalies.append({
                "verse_key": key,
                "digit_bearing_row_count": len(digit_bearing),
                "word_keys": [row[1] for row in digit_bearing],
            })

    result = {
        "schema_version": 1,
        "namespace": "quran-script-stable-v1",
        "source": str(path),
        "source_sha256": _reference_sha256(path),
        "reference_sha256": reference_sha256,
        "reference_verse_count": len(reference),
        "joined_candidates": joins,
        "split_candidates": splits,
        "unresolved": unresolved,
        "marker_anomalies": marker_anomalies,
        "status": "review_required" if unresolved or joins or splits or marker_anomalies else "no_changes",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "joined_candidate_count": len(joins),
        "split_candidate_count": len(splits),
        "unresolved_count": len(unresolved),
        "marker_anomaly_count": len(marker_anomalies),
        "status": result["status"],
    }


def build_quran_script_candidate_db(
    source_path: Path,
    output_path: Path,
    reference_sha256: str,
) -> dict[str, Any]:
    """Build a separate QPC-token candidate; never replace the live DB.

    The candidate has an explicit ``qpc-canonical-token-v2`` namespace.  It
    is intentionally not presented as a drop-in replacement for
    ``quran-script-stable-v1``: a reviewer must first approve the key/ID
    migration and any layout translations.
    """
    source_path = Path(source_path)
    qpc_path = JSON_SOURCES["qpc_hafs"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    source_conn = _ro_connect(source_path)
    try:
        old_rows = source_conn.execute(
            "SELECT word_index,word_key,surah,ayah,text,text_original "
            "FROM words ORDER BY word_index"
        ).fetchall()
        old_waqf = source_conn.execute(
            "SELECT word_index,waqf_char,waqf_type,waqf_name,waqf_unicode "
            "FROM waqf ORDER BY word_index"
        ).fetchall() if _table_exists(source_conn, "waqf") else []
    finally:
        source_conn.close()

    qpc = _json_load(qpc_path)
    candidate_rows: list[tuple[int, str, int, int, str, str]] = []
    new_id_by_key: dict[str, int] = {}
    next_id = 1
    for verse_key in expected_verse_keys():
        value = qpc.get(verse_key)
        if not isinstance(value, dict):
            continue
        surah, ayah = (int(part) for part in verse_key.split(":"))
        for position, token in enumerate(str(value.get("text") or "").split(), 1):
            word_key = f"{verse_key}:{position}"
            candidate_rows.append((next_id, word_key, surah, ayah, token, token))
            new_id_by_key[word_key] = next_id
            next_id += 1

    conn = sqlite3.connect(output_path)
    try:
        conn.executescript(
            """
            CREATE TABLE words (
                word_index INTEGER PRIMARY KEY,
                word_key TEXT NOT NULL UNIQUE,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                text TEXT NOT NULL,
                text_original TEXT
            );
            CREATE TABLE waqf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_index INTEGER NOT NULL,
                waqf_char TEXT NOT NULL,
                waqf_type TEXT NOT NULL,
                waqf_name TEXT,
                waqf_unicode TEXT,
                FOREIGN KEY (word_index) REFERENCES words(word_index),
                UNIQUE(word_index)
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        conn.executemany(
            "INSERT INTO words(word_index,word_key,surah,ayah,text,text_original) "
            "VALUES (?,?,?,?,?,?)",
            candidate_rows,
        )

        old_id_to_key = {
            int(row[0]): str(row[1]) for row in old_rows if row[1]
        }
        old_key_to_row = {
            str(row[1]): row for row in old_rows if row[1]
        }
        migrated_waqf = []
        orphan_waqf = []
        for row in old_waqf:
            old_id = int(row[0])
            word_key = old_id_to_key.get(old_id)
            new_id = new_id_by_key.get(word_key or "")
            if new_id is None:
                orphan_waqf.append({
                    "old_word_index": old_id,
                    "old_word_key": word_key,
                })
                continue
            migrated_waqf.append((new_id, row[1], row[2], row[3], row[4]))
        conn.executemany(
            "INSERT INTO waqf(word_index,waqf_char,waqf_type,waqf_name,waqf_unicode) "
            "VALUES (?,?,?,?,?)",
            migrated_waqf,
        )
        meta = {
            "namespace": "qpc-canonical-token-v2",
            "source_database": str(source_path),
            "source_database_sha256": _reference_sha256(source_path),
            "qpc_source": str(qpc_path),
            "reference_sha256": reference_sha256,
            "replacement_approved": "0",
        }
        conn.executemany(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            sorted(meta.items()),
        )
        conn.commit()
    finally:
        conn.close()

    exact_key_count = 0
    text_mismatch_count = 0
    for old_row in old_rows:
        word_key = str(old_row[1] or "")
        new_id = new_id_by_key.get(word_key)
        if new_id is None:
            continue
        exact_key_count += 1
        new_text = candidate_rows[new_id - 1][4]
        if _strip_comparison_noise(str(old_row[4] or "")) != _strip_comparison_noise(new_text):
            text_mismatch_count += 1
    old_keys = {str(row[1]) for row in old_rows if row[1]}
    new_keys = set(new_id_by_key)
    return {
        "path": str(output_path),
        "namespace": "qpc-canonical-token-v2",
        "old_row_count": len(old_rows),
        "candidate_row_count": len(candidate_rows),
        "old_key_count": len(old_keys),
        "candidate_key_count": len(new_keys),
        "keys_mapped": exact_key_count,
        "old_keys_unmapped": len(old_keys - new_keys),
        "new_keys_not_in_old": len(new_keys - old_keys),
        "text_mismatch_on_shared_keys": text_mismatch_count,
        "old_waqf_count": len(old_waqf),
        "migrated_waqf_count": len(migrated_waqf),
        "orphan_waqf_count": len(orphan_waqf),
        "orphan_waqf": orphan_waqf[:100],
        "replacement_approved": False,
    }


def audit_word_name(path: Path, reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT surah_number,ayah_number,word,meaning FROM verses"
        ).fetchall()
    finally:
        conn.close()
    orphan = []
    expected_words = {
        key: _reference_words(row)
        for key, row in reference.items()
    }
    grouped_phrase_count = 0
    for surah, ayah, word, meaning in rows:
        key = f"{surah}:{ayah}"
        tokens = _split_words(str(word or ""))
        if len(tokens) > 1:
            grouped_phrase_count += 1
        matches = False
        if key in expected_words and tokens:
            expected = expected_words[key]
            for start in range(len(expected) - len(tokens) + 1):
                if all(
                    _word_variants(token) & _word_variants(expected[start + offset])
                    for offset, token in enumerate(tokens)
                ):
                    matches = True
                    break
        if key not in expected_words or not matches:
            orphan.append({"surah": surah, "ayah": ayah, "word": word})
    return {
        "path": str(path),
        "row_count": len(rows),
        "grouped_phrase_count": grouped_phrase_count,
        "orphan_count": len(orphan),
        "orphan_rows": _sample(orphan),
        "status": "ok" if not orphan else "mismatch",
    }


def audit_waqf_symbols(path: Path, reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT source,verse_key,surah_number,ayah_number,token_index,"
            "word_index,symbols,clean_token FROM waqf_symbols"
        ).fetchall()
    finally:
        conn.close()
    bad = []
    for source, key, surah, ayah, token_index, word_index, symbols, clean_token in rows:
        if key not in reference or (int(surah), int(ayah)) != tuple(map(int, key.split(":"))):
            bad.append({"source": source, "verse_key": key, "reason": "invalid_verse_key"})
            continue
        if int(token_index) < 0 or (word_index is not None and int(word_index) <= 0):
            bad.append({"source": source, "verse_key": key, "reason": "invalid_position"})
        if not symbols:
            bad.append({"source": source, "verse_key": key, "reason": "empty_symbol"})
        if word_index is not None:
            words = _reference_words(reference[key])
            if int(word_index) > len(words):
                bad.append({
                    "source": source,
                    "verse_key": key,
                    "word_index": word_index,
                    "reason": "word_position_out_of_range",
                })
            elif clean_token and not (
                _word_variants(str(clean_token))
                & _word_variants(words[int(word_index) - 1])
            ):
                bad.append({
                    "source": source,
                    "verse_key": key,
                    "word_index": word_index,
                    "clean_token": clean_token,
                    "expected": words[int(word_index) - 1],
                    "reason": "clean_token_mismatch",
                })
    return {
        "path": str(path),
        "row_count": len(rows),
        "invalid_count": len(bad),
        "invalid_rows": _sample(bad),
        "status": "ok" if not bad else "mismatch",
    }


def audit_mushaf_waqf(path: Path, reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    conn = _ro_connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            'SELECT "السورة" AS surah,"الآية" AS ayah,"الكلمة" AS word,'
            "token_index,word_index FROM waqf"
        ).fetchall()
    finally:
        conn.close()
    bad = []
    for row in rows:
        key = f"{row['surah']}:{row['ayah']}"
        words = _reference_words(reference[key]) if key in reference else []
        try:
            position = int(row["word_index"] or row["token_index"])
        except (TypeError, ValueError):
            position = 0
        if key not in reference:
            reason = "invalid_verse_key"
        elif position < 1 or position > len(words):
            reason = "position_out_of_range"
        elif row["word"] and not (
            _word_variants(str(row["word"]))
            & _word_variants(words[position - 1])
        ):
            reason = "word_text_mismatch"
        else:
            continue
        bad.append({
            "surah": row["surah"],
            "ayah": row["ayah"],
            "word": row["word"],
            "word_index": row["word_index"],
            "token_index": row["token_index"],
            "reason": reason,
        })
    return {
        "path": str(path),
        "row_count": len(rows),
        "invalid_count": len(bad),
        "invalid_rows": _sample(bad),
        "status": "ok" if not bad else "mismatch",
    }


def audit_classical(path: Path, reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    conn = _ro_connect(path)
    try:
        rows = conn.execute(
            "SELECT source,surah,ayah,wpos,stop_word,conf FROM classical"
        ).fetchall()
    finally:
        conn.close()
    bad = []
    by_source = collections.Counter()
    for source, surah, ayah, wpos, stop_word, conf in rows:
        key = f"{surah}:{ayah}"
        by_source[source] += 1
        words = _reference_words(reference[key]) if key in reference else []
        try:
            position = int(wpos)
        except (TypeError, ValueError):
            position = -1
        if key not in reference:
            reason = "invalid_verse_key"
        elif not 0 <= position < len(words):
            reason = "wpos_out_of_range"
        elif stop_word and not (
            _word_variants(str(stop_word))
            & _word_variants(words[position])
        ):
            reason = "stop_word_mismatch"
        else:
            continue
        bad.append({
            "source": source,
            "surah": surah,
            "ayah": ayah,
            "wpos": wpos,
            "stop_word": stop_word,
            "conf": conf,
            "reason": reason,
        })
    return {
        "path": str(path),
        "row_count": len(rows),
        "rows_by_source": dict(sorted(by_source.items())),
        "invalid_count": len(bad),
        "invalid_rows": _sample(bad),
        "status": "ok" if not bad else "mismatch",
    }


def _layout_rows(path: Path) -> list[sqlite3.Row]:
    conn = _ro_connect(path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(pages)").fetchall()
        }
        line_text = "line_text" if "line_text" in columns else "'' AS line_text"
        return conn.execute(
            "SELECT page_number,line_number,line_type,first_word_id,last_word_id,"
            f"surah_number,{line_text} FROM pages ORDER BY page_number,line_number"
        ).fetchall()
    finally:
        conn.close()


def _layout_universe(rows: list[sqlite3.Row]) -> tuple[set[int], list[dict[str, Any]]]:
    ids: set[int] = set()
    errors = []
    for row in rows:
        if row["first_word_id"] in (None, "") or row["last_word_id"] in (None, ""):
            continue
        try:
            first, last = int(row["first_word_id"]), int(row["last_word_id"])
        except (TypeError, ValueError):
            errors.append({"page": row["page_number"], "line": row["line_number"], "reason": "non_numeric_span"})
            continue
        if last < first:
            errors.append({"page": row["page_number"], "line": row["line_number"], "reason": "reversed_span"})
            continue
        ids.update(range(first, last + 1))
    return ids, errors


def _qpc_token_records() -> dict[int, tuple[int, int, str]]:
    """Build the QPC/Digital-Khatt local ID namespace from its own source."""
    path = JSON_SOURCES["qpc_hafs"]
    if not path.exists():
        return {}
    data = _json_load(path)
    records: dict[int, tuple[int, int, str]] = {}
    next_id = 1
    for key in expected_verse_keys():
        value = data.get(key)
        if not isinstance(value, dict):
            continue
        surah, ayah = (int(part) for part in key.split(":"))
        for token in str(value.get("text") or "").split():
            # ۞ is a rubʿ marker present in the raw source but not in the
            # 1..83668 layout token namespace.
            if token == "۞":
                continue
            records[next_id] = (surah, ayah, token)
            next_id += 1
    return records


def audit_layouts(paths: dict[str, Path], quran_script_path: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    script_ids: set[int] = set()
    script_positions: dict[int, int] = {}
    script_order_ids: list[int] = []
    script_records: dict[int, tuple[int, int, str]] = {}
    if quran_script_path.exists():
        conn = _ro_connect(quran_script_path)
        try:
            script_rows = conn.execute(
                "SELECT word_index,word_key,surah,ayah,text FROM words"
            ).fetchall()
        finally:
            conn.close()
        script_rows.sort(
            key=lambda row: (
                int(row[2]),
                int(row[3]),
                (_parse_word_key(row[1]) or (int(row[2]), int(row[3]), 0))[2],
                int(row[0]),
            )
        )
        script_ids = {int(row[0]) for row in script_rows}
        script_positions = {
            int(row[0]): position for position, row in enumerate(script_rows)
        }
        script_order_ids = [int(row[0]) for row in script_rows]
        script_records = {
            int(row[0]): (int(row[2]), int(row[3]), str(row[4] or ""))
            for row in script_rows
        }
    qpc_records = _qpc_token_records()

    for name, path in paths.items():
        if not path.exists():
            reports[name] = {"status": "missing_file", "path": str(path)}
            continue
        rows = _layout_rows(path)
        namespace = "qpc-layout-global-v1" if name in {
            "digital_khatt", "qpc_v4", "qpc_v1", "qatar", "bahrain"
        } else "quran-script-stable-v1"
        ids, span_errors = _layout_universe(rows)
        ayah_ids: set[int] = set()
        header_ids: set[int] = set()
        endpoint_errors = []
        canonical_spans: dict[tuple[int, int], list[int]] = {}
        for row in rows:
            if row["first_word_id"] in (None, "") or row["last_word_id"] in (None, ""):
                continue
            try:
                first, last = int(row["first_word_id"]), int(row["last_word_id"])
            except (TypeError, ValueError):
                continue
            if last < first:
                continue
            if namespace == "qpc-layout-global-v1":
                span_ids = list(range(first, last + 1))
            else:
                first_position = script_positions.get(first)
                last_position = script_positions.get(last)
                if first_position is None or last_position is None or last_position < first_position:
                    span_ids = []
                else:
                    span_ids = script_order_ids[first_position:last_position + 1]
            canonical_spans[(int(row["page_number"]), int(row["line_number"]))] = span_ids
            target = ayah_ids if row["line_type"] == "ayah" else header_ids
            target.update(span_ids)
            # Header endpoints in the stable namespace can be synthetic, but
            # a header may also intentionally reserve real 1:1 rows.
            if namespace == "quran-script-stable-v1" and row["line_type"] != "ayah":
                target.update(
                    word_id for word_id in range(first, last + 1)
                    if word_id in script_ids
                )
        if namespace == "qpc-layout-global-v1":
            expected_ids = set(range(1, 83669))
            expected_ayah_ids = expected_ids
        else:
            expected_ids = script_ids
            # Printed layouts reserve numeric spans for the surah name and
            # basmala.  In the stable namespace those spans can overlap the
            # first verse's quran_script rows (1:1) or be fully synthetic.
            # They are not missing ayah rows and must be excluded explicitly.
            expected_ayah_ids = expected_ids - header_ids
        missing_ids = expected_ayah_ids - ayah_ids
        foreign_ids = ayah_ids - expected_ids
        synthetic_header_ids = header_ids - expected_ids
        ordering_errors = []
        unresolved_order = []
        cross_surah_lines = []
        line_text_mismatches = []
        empty_ayah_lines = []
        previous_last: int | None = None
        for row in rows:
            first, last = row["first_word_id"], row["last_word_id"]
            if first in (None, "") or last in (None, ""):
                if row["line_type"] == "ayah":
                    empty_ayah_lines.append({
                        "page": row["page_number"],
                        "line": row["line_number"],
                    })
                continue
            try:
                first, last = int(first), int(last)
            except (TypeError, ValueError):
                continue
            if row["line_type"] == "ayah":
                unknown_endpoints = [
                    endpoint for endpoint in (first, last)
                    if endpoint not in expected_ids
                ]
                if unknown_endpoints:
                    endpoint_errors.append({
                        "page": row["page_number"],
                        "line": row["line_number"],
                        "first": first,
                        "last": last,
                        "unknown_endpoints": unknown_endpoints,
                    })
                records = qpc_records if namespace == "qpc-layout-global-v1" else script_records
                known_surahs = {
                    records[word_id][0]
                    for word_id in canonical_spans.get(
                        (int(row["page_number"]), int(row["line_number"])),
                        [],
                    )
                    if word_id in records
                }
                try:
                    row_surah = int(row["surah_number"])
                except (TypeError, ValueError):
                    row_surah = None
                if row_surah and known_surahs - {row_surah}:
                    cross_surah_lines.append({
                        "page": row["page_number"],
                        "line": row["line_number"],
                        "declared_surah": row_surah,
                        "contained_suras": sorted(known_surahs),
                        "first": first,
                        "last": last,
                    })
                if (
                    namespace != "qpc-layout-global-v1"
                    and row["line_text"]
                    and canonical_spans.get(
                        (int(row["page_number"]), int(row["line_number"])),
                        [],
                    )
                ):
                    expected_text = " ".join(
                        records[word_id][2]
                        for word_id in canonical_spans[
                            (int(row["page_number"]), int(row["line_number"]))
                        ]
                        if word_id in records
                    ).strip()
                    line_check = _compare_words(
                        _split_words(row["line_text"]),
                        _split_words(expected_text),
                    )
                    if not line_check["word_match"] and not line_check["tokenization_only"]:
                        line_text_mismatches.append({
                            "page": row["page_number"],
                            "line": row["line_number"],
                            "actual": row["line_text"],
                            "expected": expected_text,
                            "comparison": line_check,
                        })
            else:
                continue
            if namespace == "qpc-layout-global-v1":
                first_position, last_position = first, last
            else:
                first_position = script_positions.get(first)
                last_position = script_positions.get(last)
                if first_position is None or last_position is None:
                    unresolved_order.append({
                        "page": row["page_number"],
                        "line": row["line_number"],
                        "first": first,
                        "last": last,
                    })
                    continue
            if previous_last is not None and first_position < previous_last:
                ordering_errors.append({
                    "page": row["page_number"],
                    "line": row["line_number"],
                    "first": first,
                    "previous_last": previous_last,
                })
            previous_last = max(previous_last or last_position, last_position)
        reports[name] = {
            "path": str(path),
            "namespace": namespace,
            "line_count": len(rows),
            "id_count": len(ids),
            "ayah_id_count": len(ayah_ids),
            "header_id_count": len(header_ids),
            "min_id": min(ids) if ids else None,
            "max_id": max(ids) if ids else None,
            "missing_id_count": len(missing_ids),
            "missing_ids": _sample(sorted(missing_ids)),
            "foreign_id_count": len(foreign_ids),
            "foreign_ids": _sample(sorted(foreign_ids)),
            "synthetic_header_id_count": len(synthetic_header_ids),
            "synthetic_header_ids": _sample(sorted(synthetic_header_ids)),
            "unknown_ayah_endpoint_count": len(endpoint_errors),
            "unknown_ayah_endpoints": _sample(endpoint_errors),
            "cross_surah_line_count": len(cross_surah_lines),
            "cross_surah_lines": _sample(cross_surah_lines),
            "line_text_mismatch_count": len(line_text_mismatches),
            "line_text_mismatches": _sample(line_text_mismatches),
            "span_error_count": len(span_errors),
            "span_errors": _sample(span_errors),
            "ordering_error_count": len(ordering_errors),
            "ordering_errors": _sample(ordering_errors),
            "unresolved_order_count": len(unresolved_order),
            "unresolved_order": _sample(unresolved_order),
            "empty_ayah_line_count": len(empty_ayah_lines),
            "empty_ayah_lines": _sample(empty_ayah_lines),
            "status": "ok" if (
                not span_errors
                and not ordering_errors
                and not empty_ayah_lines
                and not endpoint_errors
                and not cross_surah_lines
                and not foreign_ids
                and not line_text_mismatches
            ) else "mismatch",
        }
    return reports


def build_layout_candidate_repairs(
    paths: dict[str, Path],
    quran_script_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Suggest endpoint-only repairs without mutating layout databases."""
    if not quran_script_path.exists():
        return {"path": str(output_path), "status": "missing_source"}
    conn = _ro_connect(quran_script_path)
    try:
        script_rows = conn.execute(
            "SELECT word_index,word_key,surah,ayah FROM words"
        ).fetchall()
    finally:
        conn.close()
    script_rows.sort(
        key=lambda row: (
            int(row[2]),
            int(row[3]),
            (_parse_word_key(row[1]) or (int(row[2]), int(row[3]), 0))[2],
            int(row[0]),
        )
    )
    ordered_ids = [int(row[0]) for row in script_rows]
    positions = {word_id: index for index, word_id in enumerate(ordered_ids)}
    keys = {int(row[0]): str(row[1]) for row in script_rows}
    repairs = []
    for name, path in paths.items():
        if name not in {"shamarly", "azhar"} or not path.exists():
            continue
        rows = _layout_rows(path)
        for index, row in enumerate(rows):
            if row["line_type"] != "ayah":
                continue
            first = row["first_word_id"]
            last = row["last_word_id"]
            try:
                first_i, last_i = int(first), int(last)
            except (TypeError, ValueError):
                continue
            first_known = first_i in positions
            last_known = last_i in positions
            if first_known and last_known:
                continue
            previous_last = None
            for previous in reversed(rows[:index]):
                if previous["line_type"] != "ayah":
                    continue
                try:
                    previous_last = int(previous["last_word_id"])
                except (TypeError, ValueError):
                    continue
                if previous_last in positions:
                    break
            next_first = None
            for following in rows[index + 1:]:
                if following["line_type"] != "ayah":
                    continue
                try:
                    next_first = int(following["first_word_id"])
                except (TypeError, ValueError):
                    continue
                if next_first in positions:
                    break
            candidate_first = first_i if first_known else None
            candidate_last = last_i if last_known else None
            if candidate_first is None and previous_last is not None:
                candidate_first = ordered_ids[positions[previous_last] + 1]
            if candidate_last is None and next_first is not None:
                candidate_last = ordered_ids[positions[next_first] - 1]
            if candidate_first is None or candidate_last is None:
                continue
            if positions[candidate_first] > positions[candidate_last]:
                continue
            span = ordered_ids[
                positions[candidate_first]:positions[candidate_last] + 1
            ]
            try:
                declared_surah = int(row["surah_number"])
            except (TypeError, ValueError):
                declared_surah = None
            contained = {
                int(_parse_word_key(keys[word_id])[0])
                for word_id in span
                if _parse_word_key(keys[word_id])
            }
            if declared_surah and contained != {declared_surah}:
                continue
            repairs.append({
                "edition": name,
                "page": row["page_number"],
                "line": row["line_number"],
                "current_first_word_id": first_i,
                "current_last_word_id": last_i,
                "candidate_first_word_id": candidate_first,
                "candidate_last_word_id": candidate_last,
                "candidate_first_word_key": keys.get(candidate_first),
                "candidate_last_word_key": keys.get(candidate_last),
                "basis": "canonical predecessor/successor in quran-script-stable-v1",
            })
    result = {
        "schema_version": 1,
        "namespace": "quran-script-stable-v1",
        "replacement_approved": False,
        "candidate_count": len(repairs),
        "candidates": repairs,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "candidate_count": len(repairs),
        "replacement_approved": False,
    }


def audit_all(reference_path: Path, report_path: Path) -> dict[str, Any]:
    reference = load_reference(reference_path)
    expected = expected_verse_keys()
    if len(reference) != len(expected):
        raise RuntimeError(
            f"reference snapshot incomplete: {len(reference)}/{len(expected)}; "
            "run with --fetch-reference"
        )
    reference_text_words = sum(len(_reference_words(row)) for row in reference.values())
    reference_words = sum(int(row["word_count"]) for row in reference.values())
    reference_count_discrepancies = [
        {
            "verse_key": key,
            "text_token_count": len(_reference_words(row)),
            "mcp_word_count": int(row["word_count"]),
        }
        for key, row in reference.items()
        if len(_reference_words(row)) != int(row["word_count"])
    ]
    reference_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    quran_script_report = audit_quran_script(DB_SOURCES["quran_script"], reference)
    quran_script_candidate = build_quran_script_candidate_mapping(
        DB_SOURCES["quran_script"],
        reference,
        reference_sha256,
        reference_path.with_name(CANDIDATE_MAPPING_PATH.name),
    )
    quran_script_rebuilt_candidate = build_quran_script_candidate_db(
        DB_SOURCES["quran_script"],
        reference_path.with_name(CANDIDATE_DB_PATH.name),
        reference_sha256,
    )
    layout_candidates = build_layout_candidate_repairs(
        LAYOUT_SOURCES,
        DB_SOURCES["quran_script"],
        reference_path.with_name(LAYOUT_CANDIDATE_PATH.name),
    )
    report = {
        "reference": {
            "path": str(reference_path),
            "sha256": reference_sha256,
            "verse_count": len(reference),
            "word_count": reference_words,
            "text_token_count": reference_text_words,
            "word_count_discrepancy_count": len(reference_count_discrepancies),
            "word_count_discrepancies": reference_count_discrepancies,
            "mcp_expected_word_count": MCP_TOTAL_WORDS,
            "word_count_matches_mcp": reference_words == MCP_TOTAL_WORDS,
        },
        "json_sources": audit_json_sources(reference),
        "databases": {
            "quran_script": quran_script_report,
            "word_name": audit_word_name(DB_SOURCES["word_name"], reference),
            "waqf_symbols": audit_waqf_symbols(DB_SOURCES["waqf_symbols"], reference),
            "mushaf_waqf": audit_mushaf_waqf(DB_SOURCES["mushaf_waqf"], reference),
            "classical_waqf": audit_classical(DB_SOURCES["classical_waqf"], reference),
        },
        "layouts": audit_layouts(LAYOUT_SOURCES, DB_SOURCES["quran_script"]),
        "quran_script_candidate_mapping": quran_script_candidate,
        "quran_script_rebuilt_candidate": quran_script_rebuilt_candidate,
        "layout_candidate_repairs": layout_candidates,
    }
    failures = []
    if report["reference"]["word_count"] != MCP_TOTAL_WORDS:
        failures.append("reference_word_count")
    if report["reference"]["word_count_discrepancy_count"]:
        failures.append("reference_text_word_count")
    for group_name in ("json_sources", "databases", "layouts"):
        for source, item in report[group_name].items():
            if item.get("status") != "ok":
                failures.append(f"{group_name}.{source}")
    report["failure_count"] = len(failures)
    report["failures"] = failures
    report["status"] = "ok" if not failures else "review_required"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-reference", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--reference", type=Path, default=REFERENCE_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args(argv)
    if not args.fetch_reference and not args.audit:
        parser.error("choose --fetch-reference, --audit, or both")

    if args.fetch_reference:
        result = harvest_reference(
            args.reference,
            workers=max(1, args.workers),
            retries=max(0, args.retries),
            delay=max(0.0, args.delay),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["complete"]:
            return 2

    if args.audit:
        report = audit_all(args.reference, args.report)
        print(json.dumps({
            "status": report["status"],
            "failure_count": report["failure_count"],
            "report": str(args.report),
        }, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
