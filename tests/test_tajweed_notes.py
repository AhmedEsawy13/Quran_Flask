"""Integrity checks for the local بيان التجويد companion layer."""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOTES_DB = ROOT / "data" / "tajweed_notes_local.db"
FORMATTER = ROOT / "static" / "js" / "tajweed_notes_format.js"


def test_all_stored_tajweed_notes_survive_display_partitioning():
    """Visual grouping must not drop an Arabic word from the reference text."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to exercise the shared browser formatter")

    with sqlite3.connect(NOTES_DB) as conn:
        rows = conn.execute(
            "SELECT verse_key, text FROM tajweed_notes "
            "WHERE length(trim(text)) > 0 ORDER BY verse_key"
        ).fetchall()

    script = r"""
const fs = require('fs');
const vm = require('vm');
const window = {};
vm.runInNewContext(
  fs.readFileSync(process.argv[1], 'utf8'),
  { window }
);
const api = window.AtharTajweedNotes;
const rows = JSON.parse(fs.readFileSync(0, 'utf8'));
const bad = [];
for (const row of rows) {
  const units = api.splitUnits(api.normalizeSource(row.text));
  if (!api.isLossless(row.text, units)) bad.push(row.key);
}
process.stdout.write(JSON.stringify(bad));
"""
    result = subprocess.run(
        [node, "-e", script, str(FORMATTER)],
        input=json.dumps(
            [{"key": key, "text": text} for key, text in rows],
            ensure_ascii=False,
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == []
