"""«المدينة الجديد» must match the pause signs printed on the QVP pages the
reader draws (pipeline/audit_qvp_waqf.py; data/qvp_waqf_ink.json)."""
import json

from pipeline.audit_qvp_waqf import INK, PIN, compare


def test_ink_file_matches_the_pinned_release():
    # After bumping the QVP release, re-run: python3 pipeline/audit_qvp_waqf.py
    pinned = json.loads(PIN.read_text(encoding='utf-8'))['pages']['release']
    assert json.loads(INK.read_text(encoding='utf-8'))['release'] == pinned


def test_new_madinah_matches_the_printed_ink():
    diffs = compare(json.loads(INK.read_text(encoding='utf-8')))
    assert diffs == [], diffs[:10]
