"""Guards for the AI-re-extracted classical waqf rows (source ending in _llm),
built by pipeline/build_classical_llm.py. These verify the DETERMINISTIC gates
the pipeline applies — they don't call any model. Skips cleanly if no _llm rows
are present yet (the pilot only builds a few surahs)."""
import os
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE

# The pilot writes to a sibling db (data/classical_waqf_llm.db) so the shipped db
# stays pristine until release; test whichever one actually holds the _llm rows.
_PILOT_DB = os.path.join(os.path.dirname(CLASSICAL_WAQF_DATABASE), 'classical_waqf_llm.db')


def _rows(where=''):
    for db in (CLASSICAL_WAQF_DATABASE, _PILOT_DB):
        if not os.path.exists(db):
            continue
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(
                "SELECT * FROM classical WHERE source LIKE '%\\_llm' ESCAPE '\\' " + where).fetchall()
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
    WITH a non-trivial علّة — the whole point of the re-extraction."""
    fat = [r for r in llm_rows if r['surah'] == 1]
    if not fat:
        pytest.skip('al-Fatiha not built in this run')
    assert len(fat) >= 10
    with_reason = [r for r in fat if r['note'] and len(r['note'].strip()) >= 18]
    assert len(with_reason) >= len(fat) * 0.8
