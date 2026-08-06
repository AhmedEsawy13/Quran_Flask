"""Regression gates for the MCP-backed Quran integrity audit.

The exhaustive MCP snapshot is an ignored build artifact.  Tests that need it
skip clean checkouts and become active automatically after the snapshot has
been harvested.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from pipeline import audit_quran_integrity as audit


def test_mcp_boundary_manifest_has_6236_ayahs():
    keys = audit.expected_verse_keys()
    assert len(keys) == audit.MCP_TOTAL_AYAHS
    assert keys[0] == "1:1"
    assert keys[-1] == "114:6"


def test_tracked_digital_source_has_exact_verse_key_coverage():
    path = audit.JSON_SOURCES["digital_khatt"]
    if not path.exists():
        pytest.skip("Digital Khatt source artifact is not installed")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == set(audit.expected_verse_keys())
    assert all(value.get("verse_key") == key for key, value in data.items())


def test_quran_script_word_keys_are_unique_and_self_consistent():
    path = audit.DB_SOURCES["quran_script"]
    if not path.exists():
        pytest.skip("quran_script.db is not installed")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT word_index,word_key,surah,ayah FROM words"
        ).fetchall()
    finally:
        conn.close()
    ids = [int(row[0]) for row in rows]
    keys = [row[1] for row in rows]
    expected_verses = set(audit.expected_verse_keys())
    assert len(ids) == len(set(ids))
    assert len(keys) == len(set(keys))
    for _, word_key, surah, ayah in rows:
        assert audit._parse_word_key(word_key)[:2] == (int(surah), int(ayah))
        assert f"{surah}:{ayah}" in expected_verses


def test_qpc_layout_namespaces_have_complete_local_ranges():
    existing = {
        name: path
        for name, path in audit.LAYOUT_SOURCES.items()
        if name in {"digital_khatt", "qpc_v4", "qpc_v1", "qatar"}
        and path.exists()
    }
    if not existing:
        pytest.skip("QPC layout artifacts are not installed")
    report = audit.audit_layouts(existing, audit.DB_SOURCES["quran_script"])
    for item in report.values():
        assert item["namespace"] == "qpc-layout-global-v1"
        assert item["missing_id_count"] == 0
        assert item["foreign_id_count"] == 0
        assert item["unknown_ayah_endpoint_count"] == 0
        assert item["cross_surah_line_count"] == 0


def test_stable_layout_audit_uses_canonical_span_expansion():
    path = audit.LAYOUT_SOURCES["mesaha"]
    if not path.exists() or not audit.DB_SOURCES["quran_script"].exists():
        pytest.skip("stable layout artifacts are not installed")
    report = audit.audit_layouts(
        {"mesaha": path},
        audit.DB_SOURCES["quran_script"],
    )["mesaha"]
    assert report["namespace"] == "quran-script-stable-v1"
    assert report["cross_surah_line_count"] == 0
    assert report["foreign_id_count"] == 0


def test_cached_mcp_snapshot_has_resume_checksum_metadata():
    path = audit.REFERENCE_PATH
    manifest_path = path.with_name(audit.MANIFEST_PATH.name)
    if not path.exists() or not manifest_path.exists():
        pytest.skip("run --fetch-reference to install the MCP snapshot")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["cached_ayahs"] == audit.MCP_TOTAL_AYAHS
    assert manifest["jsonl_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(audit.load_reference(path)) == audit.MCP_TOTAL_AYAHS


def test_candidate_rebuild_is_separate_and_not_approved_for_replacement():
    path = audit.CANDIDATE_DB_PATH
    if not path.exists():
        pytest.skip("run --audit to build the candidate artifact")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        namespace = conn.execute(
            "SELECT value FROM meta WHERE key='namespace'"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT value FROM meta WHERE key='replacement_approved'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert namespace == "qpc-canonical-token-v2"
    assert approved == "0"


def test_layout_candidates_are_review_only():
    path = audit.LAYOUT_CANDIDATE_PATH
    if not path.exists():
        pytest.skip("run --audit to build layout candidates")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["namespace"] == "quran-script-stable-v1"
    assert report["replacement_approved"] is False
