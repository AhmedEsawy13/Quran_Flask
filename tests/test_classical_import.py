"""Shared deterministic, no-LLM classical-book importer."""
import json
import sqlite3

from pipeline import import_classical_book as importer


def candidate(**overrides):
    raw = {
        'surah': 1, 'ayah': 2, 'quote': 'ٱلۡحَمۡدُ لِلَّهِ',
        'grade': 'تام', 'grade_raw': 'تام', 'locator': 'PageV01P001:p1',
    }
    raw.update(overrides)
    return importer.candidate_from_dict(raw)


def test_accepts_unique_exact_quran_alignment():
    row, reason = importer.validate(candidate())
    assert reason is None
    assert row is not None
    assert row.wpos == 1


def test_rejects_unknown_grade():
    row, reason = importer.validate(candidate(grade='ممتاز'))
    assert row is None and reason == 'unknown_grade'


def test_rejects_candidate_without_source_locator():
    row, reason = importer.validate(candidate(locator=''))
    assert row is None and reason == 'missing_source_locator'


def test_repeated_phrase_requires_explicit_position():
    # «عليهم» occurs twice in 1:7. A deterministic importer may not guess.
    row, reason = importer.validate(candidate(
        ayah=7, quote='عَلَيۡهِمۡ', grade='جائز'))
    assert row is None and reason == 'ambiguous_repeated_phrase'

    row, reason = importer.validate(candidate(
        ayah=7, quote='عَلَيۡهِمۡ', grade='جائز', expected_wpos=3))
    assert reason is None and row is not None and row.wpos == 3


def test_rejected_candidates_are_written_to_review_queue(tmp_path):
    source = tmp_path / 'candidates.jsonl'
    source.write_text(json.dumps({
        'surah': 1, 'ayah': 7, 'quote': 'عليهم', 'grade': 'جائز',
        'locator': 'page:1',
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    accepted, rejected = importer.read_candidates(source)
    assert not accepted
    assert rejected[0]['reason'] == 'ambiguous_repeated_phrase'


def test_transactional_import_stores_checksum_and_row_provenance(tmp_path):
    db = tmp_path / 'classical.db'
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE classical (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, surah INTEGER NOT NULL,
        ayah INTEGER, wpos INTEGER, stop_word TEXT, quote TEXT NOT NULL,
        grade TEXT NOT NULL, grade_raw TEXT NOT NULL, note TEXT, seq INTEGER,
        conf INTEGER NOT NULL DEFAULT 1, reported_from TEXT)''')
    conn.commit()
    conn.close()
    source_file = importer.ROOT / 'pipeline' / 'classical_sources' / \
        'muktafa_dani_shamela26461.md'
    accepted, reason = importer.validate(candidate())
    assert reason is None and accepted is not None
    importer.replace_source(db, 'testbook', 'كتاب', 'مؤلف', 'test_v1',
                            source_file, [accepted])

    conn = sqlite3.connect(db)
    try:
        edition = conn.execute(
            'SELECT source_sha256,parser FROM classical_editions WHERE source="testbook"'
        ).fetchone()
        provenance = conn.execute(
            'SELECT source_locator,evidence FROM classical_provenance'
        ).fetchone()
    finally:
        conn.close()
    assert edition == (importer.sha256_file(source_file), 'test_v1')
    assert provenance == ('PageV01P001:p1', 'ٱلۡحَمۡدُ لِلَّهِ')
