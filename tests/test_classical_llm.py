"""Guards for the AI-re-extracted classical waqf rows, built by
pipeline/build_classical_llm.py. These verify the DETERMINISTIC gates the
pipeline applies — they don't call any model.

Covers TWO forms of the same data: any pilot `source` ending in `_llm` (a
book still being trialled, written to the sibling pilot db so the shipped db
stays untouched until release), AND the bare `source='manar'` rows in the
shipped db itself — منار's own regex extraction was RETIRED and replaced by
this AI extraction on 2026-07-12 (see CLASSICAL_LLM_PILOT.md), so what's now
live in production needs these same gates to keep guarding it, not just the
pre-release pilot data. ALSO_AI_SOURCES lists which bare source keys (beyond
any `_llm` suffix) are AI-shaped once released — add to it if another book's
pilot is ever promoted the same way.

Skips cleanly if neither pilot nor released AI rows are present yet."""
import os
import re
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE

# The pilot writes to a sibling db (data/classical_waqf_llm.db) so the shipped db
# stays pristine until release; test whichever one actually holds the AI rows.
_PILOT_DB = os.path.join(os.path.dirname(CLASSICAL_WAQF_DATABASE), 'classical_waqf_llm.db')
ALSO_AI_SOURCES = {'manar'}  # released bare-source keys that are now AI-shaped


def _rows(where=''):
    also = ' OR '.join(f"source = '{s}'" for s in ALSO_AI_SOURCES)
    cond = f"(source LIKE '%\\_llm' ESCAPE '\\'" + (f' OR {also}' if also else '') + ')'
    for db in (CLASSICAL_WAQF_DATABASE, _PILOT_DB):
        if not os.path.exists(db):
            continue
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(f'SELECT * FROM classical WHERE {cond} ' + where).fetchall()
        finally:
            conn.close()
        if r:
            return r
    return []


_GRADES = {'تام', 'كاف', 'حسن', 'جائز', 'صالح', 'قبيح', 'لا'}


@pytest.fixture(scope='module')
def llm_rows():
    rows = _rows()
    if not rows:
        pytest.skip('no _llm rows built yet (run pipeline/build_classical_llm.py --write)')
    return rows


def test_every_grade_is_in_the_lexicon(llm_rows):
    bad = {r['grade'] for r in llm_rows} - _GRADES
    assert not bad, f'unknown grades: {bad}'


def test_grade_spelling_variants_are_canonicalized():
    from pipeline.build_classical_llm import align_stops  # type: ignore
    rows, stats = align_stops(28, [
        {'ayah': 1, 'stop_phrase': 'طسمٓ', 'grade': 'la'},
        {'ayah': 2, 'stop_phrase': 'ٱلۡمُبِينِ', 'grade': 'kaf'},
    ])
    assert [r[5] for r in rows] == ['لا', 'كاف']
    assert stats['bad_grade'] == 0


def test_cleanup_preserves_rulings_but_consolidates_repeated_reasons():
    from pipeline.classical_cleanup import clean_rows

    long_note = 'على استئناف ما بعده، وقيل ليس بوقف لأن الكلام كله متعلق بما قبله'
    short_note = 'وقيل ليس بوقف لأن الكلام كله متعلق بما قبله'
    rows = [
        ('manar', 9, 59, 9, 'الله', 'حسبنا الله', 'حسن', 'حسن',
         long_note, 1, 1, None),
        ('manar', 9, 59, 14, 'ورسوله', 'ورسوله', 'حسن', 'حسن',
         short_note, 2, 1, None),
        ('manar', 9, 59, 17, 'الله', 'الله', 'حسن', 'حسن',
         short_note, 3, 1, None),
        # Same position and grade, but a genuinely different reading/reason:
        # it must remain a separate ruling.
        ('manar', 9, 59, 17, 'الله', 'لله', 'حسن', 'حسن',
         'على قراءة أخرى معتبرة', 4, 1, None),
        # Exact duplicate extraction row: this one alone is removed.
        ('manar', 9, 59, 9, 'الله', 'حسبنا الله', 'حسن', 'حسن',
         long_note, 5, 1, None),
    ]

    cleaned, stats = clean_rows(rows)
    assert len(cleaned) == 4
    assert stats['exact_rows_removed'] == 1
    assert stats['notes_suppressed'] == 2
    assert [row[3] for row in cleaned] == [9, 14, 17, 17]
    assert [row[8] for row in cleaned] == [
        long_note, '', '', 'على قراءة أخرى معتبرة',
    ]


def test_released_manar_has_no_repeated_or_contained_reasons(llm_rows):
    """The live learner view must not repeat one explanation within an ayah."""
    grouped = {}
    for row in llm_rows:
        if row['source'] != 'manar' or not (row['note'] or '').strip():
            continue
        note = ' '.join(row['note'].split())
        key = (row['surah'], row['ayah'], row['reported_from'] or '')
        grouped.setdefault(key, []).append(note)

    duplicates = []
    for key, notes in grouped.items():
        ordered = sorted(notes, key=len, reverse=True)
        for index, note in enumerate(ordered):
            if any(note == prior or (len(note) >= 30 and note in prior)
                   for prior in ordered[:index]):
                duplicates.append((*key[:2], note[:80]))
    assert not duplicates, f'repeated Manar explanations remain: {duplicates[:5]}'


def test_all_completed_manar_cache_items_pass_validation():
    """A completed LLM cache must not silently lose rows during replay."""
    from pipeline import build_classical_llm as builder  # type: ignore
    rejected = []
    for surah, _, chunk_idx, _, _ in builder.chunk_blocks('manar'):
        stops = builder.load_cached('manar', surah, chunk_idx)
        assert stops is not None, f'missing cache for surah {surah}, chunk {chunk_idx}'
        _, stats = builder.align_stops(surah, stops)
        if stats['bad_grade'] or stats['bad_ayah'] or stats['unaligned']:
            rejected.append((surah, chunk_idx, stats))
    assert not rejected, f'completed Manar cache still has rejected rows: {rejected[:10]}'


def test_every_row_aligned_to_a_word_position(llm_rows):
    # the pipeline rejects unaligned phrases, so every stored row must carry a wpos
    assert all(r['wpos'] is not None and r['wpos'] >= 0 for r in llm_rows)


def test_stop_phrase_words_occur_in_the_verse(app, llm_rows):
    """Anti-hallucination: the stored phrase must be a real run of words in its
    verse — re-checked here independently of the build step."""
    import modules.reading  # noqa: F401 — ensure app helpers loaded
    from pipeline.build_classical_waqf import quote_words, align_in_ayah  # type: ignore
    with app.test_request_context():
        miss = []
        for r in llm_rows:
            wpos, _ = align_in_ayah(r['surah'], r['ayah'], quote_words(r['quote']))
            if wpos is None:
                miss.append((r['surah'], r['ayah'], r['quote']))
    assert not miss, f'phrases not found in their verse: {miss[:5]}'


def test_released_manar_contains_every_aligned_explicit_source_ruling(llm_rows):
    """The LLM may omit an item; direct source syntax must not disappear."""
    from pipeline import build_classical_llm as builder  # type: ignore
    live = {(r['surah'], r['ayah'], r['wpos'], r['grade']) for r in llm_rows
            if r['source'] == 'manar'}
    expected = set()
    sections = builder.load_shamela_sections()
    for surah in range(1, 115):
        for r in builder.explicit_manar_rows(surah, sections[str(surah)]['text']):
            expected.add((surah, r[1], r[2], r[5]))
    missing = expected - live
    assert not missing, f'{len(missing)} explicit Manar rulings missing, e.g. {sorted(missing)[:10]}'


def test_manar_discursive_rulings_recovered(llm_rows):
    """Pin source rulings that do not use the explicit syntax backstop."""
    rows = [r for r in llm_rows if r['source'] == 'manar']
    keys = {(r['surah'], r['ayah'], r['wpos'], r['grade'], r['reported_from']) for r in rows}
    # الأخفش: no stop at إحسانا or ابن السبيل in 4:36.
    assert (4, 36, 7, 'لا', 'الأخفش') in keys
    assert (4, 36, 20, 'لا', 'الأخفش') in keys
    # Manar gives both حسن and the alternative كاف at هوىٰه in 7:176.
    assert {(r['wpos'], r['grade']) for r in rows if r['surah'] == 7 and r['ayah'] == 176} \
        >= {(9, 'حسن'), (9, 'كاف')}
    # A cache typo had put this ruling in 12:15 instead of 12:81.
    assert (12, 81, 12, 'حسن', None) in keys


_LATIN_RUN_RE = re.compile(r'[A-Za-z]{2,}')


def test_no_stray_latin_words(llm_rows):
    """Found live in production منار data (2026-07-12): the model occasionally
    code-switches a single word into English mid-Arabic-sentence instead of
    copying the source verbatim — e.g. سورة الكهف 18:63's note read «ويقوي
    this خبر» where the source says «ويقوي هذا خبر». Rare (6/13,008 rows on
    the released book) but a real data-quality defect the alignment/lexicon
    gates don't catch (they check grade validity and word position, not
    language purity) — guard against it recurring in any future AI-sourced
    book."""
    bad = [(r['surah'], r['ayah'], r['wpos'], field, r[field])
           for r in llm_rows for field in ('quote', 'note', 'reported_from')
           if r[field] and _LATIN_RUN_RE.search(r[field])]
    assert not bad, f'stray Latin-script text in Arabic fields: {bad[:5]}'


def test_alfatiha_repeated_alayhim_disambiguates(llm_rows):
    """The two «عليهم» in 1:7 must land on different positions with different
    grades — the exact repeated-word case the regex aligner mis-hit. Only runs
    if al-Fatiha was built."""
    f7 = {(r['wpos'], r['grade']) for r in llm_rows if r['surah'] == 1 and r['ayah'] == 7}
    if not f7:
        pytest.skip('al-Fatiha not built in this run')
    assert (3, 'جائز') in f7   # أنعمت عليهم — first occurrence, permitted
    assert (6, 'لا') in f7     # المغضوب عليهم — second occurrence, not a stop


def test_alfatiha_has_real_reasons(llm_rows):
    """al-Fatiha (0 rows in the regex extraction) must now carry graded stops
    WITH non-trivial علل. Repeated reasons shared by several stops are stored
    once, so this measures substantial coverage rather than requiring the same
    paragraph to be copied onto every ruling."""
    fat = [r for r in llm_rows if r['surah'] == 1]
    if not fat:
        pytest.skip('al-Fatiha not built in this run')
    assert len(fat) >= 10
    with_reason = [r for r in fat if r['note'] and len(r['note'].strip()) >= 18]
    assert len(with_reason) >= len(fat) * 0.75
