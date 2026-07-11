"""Reported-opinion attribution in the classical waqf books — a DIFFERENT
concern from text-quality (see test_classical_waqf_quality.py): these books
constantly RELAY other scholars' rulings inline, e.g. المكتفى on 38:24:

    وقال ابن الأنباري: {إلا الذين آمنوا وعملوا الصالحات} تام. ثم يبتدأ
    {وقليل ما هم} على معنى: ... والتمام عندي: ((وقليل ما هم)) ...

Before this fix, build_classical_waqf.py attributed EVERY extracted grade
flatly to the book's own author (`source` column) — so «تام» here rendered
as "تام — الداني", when the text explicitly introduces it as ابن الأنباري's
opinion (as reported by الداني), not necessarily الداني's own settled view.
That is a real "wrong waqf type" risk, not just a display nicety: a relayed
opinion the author may even go on to disagree with can look like the book's
own endorsement.

Fix: `reported_scholar()` in build_classical_waqf.py detects when a citation
is the immediate, unambiguous direct object of «وقال/وقالت NAME:» and tags
the row's new `reported_from` column with NAME. Deliberately conservative —
only the citation DIRECTLY following the colon is tagged; later citations in
the same paragraph that might still be in that scholar's reported voice are
left untagged (no reliable way to detect where reported speech ends without
real semantic understanding — under-tagging is safe, over-tagging isn't).
"""
import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'pipeline'))
sys.path.insert(0, _ROOT)
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_waqf as pcw  # noqa: E402

DB_PATH = os.path.join(_ROOT, 'data', 'classical_waqf.db')

# A book referring to ITS OWN author must never show up as ITS OWN
# reported_from — that would mean the self-reference exclusion regressed
# (e.g. نحاس calling himself «أبو جعفر» within القطع والائتناف).
_SELF_NAMES = {
    'muktafa': {'الداني', 'أبو عمرو', 'أبو عمرو الداني'},
    'manar': {'الأشموني', 'أحمد بن محمد', 'الأشموني رحمه الله'},
    'nahhas': {'أبو جعفر', 'النحاس', 'أبو جعفر النحاس'},
    'anbari': {'ابن الأنباري', 'أبو بكر', 'ابن الأنباري رحمه الله'},
}


# ── unit tests on reported_scholar() itself ──────────────────────────────

def test_reported_scholar_detects_direct_citation():
    text = 'وقال ابن الأنباري: {إلا الذين آمنوا وعملوا الصالحات} تام.'
    pos = text.index('{')
    assert pcw.reported_scholar(text, pos) == 'ابن الأنباري'


def test_reported_scholar_none_without_the_pattern():
    text = '{إلا الذين آمنوا وعملوا الصالحات} تام.'
    pos = text.index('{')
    assert pcw.reported_scholar(text, pos) is None


def test_reported_scholar_none_when_something_intervenes():
    """«وقال X: مثلا» then a NEW sentence, then the quote — the quote is NOT
    the direct object of «قال» anymore, must not be tagged."""
    text = 'وقال ابن الأنباري: هذا كلام طويل جدا جدا لا علاقة له بالحكم على الإطلاق. {X} تام.'
    pos = text.index('{')
    assert pcw.reported_scholar(text, pos) is None


def test_reported_scholar_respects_self_names():
    """نحاس refers to himself as «أبو جعفر» — that's his own voice, not a
    citation of someone else."""
    text = 'وقال أبو جعفر: {X} تام.'
    pos = text.index('{')
    assert pcw.reported_scholar(text, pos, self_names={'أبو جعفر'}) is None
    # but the SAME name, unlisted, is a real (if ambiguous) attribution
    assert pcw.reported_scholar(text, pos, self_names=()) == 'أبو جعفر'


# ── the exact reported example, pinned end-to-end ────────────────────────

@pytest.fixture(scope='module')
def rows():
    if not os.path.exists(DB_PATH):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute('SELECT * FROM classical').fetchall()
    finally:
        conn.close()


def test_the_reported_example_is_tagged(rows):
    """مكتفى 38:24: «وقال ابن الأنباري: {إلا الذين آمنوا وعملوا الصالحات}
    تام» — must be tagged reported_from='ابن الأنباري', not attributed flatly
    to الداني."""
    row = next((r for r in rows if r['source'] == 'muktafa' and r['surah'] == 38
                and r['ayah'] == 24 and 'الصالحات' in r['quote']), None)
    assert row is not None, 'expected row not found — did the source/parsing change?'
    assert row['reported_from'] == 'ابن الأنباري'


def test_muktafa_grade_before_ana_construction_is_extracted(rows):
    """Same 38:24 passage, a few sentences later: «والتمام عندي: ((وقليل ما
    هم))» — ENTRY_RE only ever looks at the text AFTER a quote for a grade
    word, so this grade-BEFORE construction was invisible; the stop simply
    never appeared. «عندي» ("in MY view") is unambiguously الداني's OWN
    voice — even though it comes right after quoting ابن الأنباري — so this
    row must have grade=تام AND reported_from=None (not still tagged as
    ابن الأنباري's relayed opinion)."""
    row = next((r for r in rows if r['source'] == 'muktafa' and r['surah'] == 38
                and r['ayah'] == 24 and r['quote'] == 'وقليل ما هم'), None)
    assert row is not None, 'expected «والتمام عندي» row not found'
    assert row['grade'] == 'تام'
    assert row['reported_from'] is None
    assert row['wpos'] == 22  # the last word of «وقليل ما هم» — هُمْ


def test_muktafa_own_re_unit():
    text = 'والتمام عندي: ((وقليل ما هم)) لأن ذلك من الكلام الأول'
    m = pcw._MUKTAFA_OWN_RE.search(text)
    assert m is not None
    assert (m.group(2) or m.group(3)) == 'وقليل ما هم'
    assert m.group(1) == 'والتمام'


def test_muktafa_own_re_ignores_ambiguous_third_person():
    """«عنده» (his view, third person) is deliberately NOT handled — it's
    ambiguous whom "he" refers to without deeper context tracking."""
    text = 'والتمام عنده: ((وقليل ما هم)) لأن ذلك'
    assert pcw._MUKTAFA_OWN_RE.search(text) is None


def test_manar_own_analysis_on_the_same_ayah_is_not_tagged(rows):
    """منار's OWN independent entry for «وقليل ما هم» on the same ayah is
    stated directly («تام، ف «قليل» خبر مقدم...») — no «وقال X:» prefix, so
    it must NOT be (mis-)tagged as anyone else's relayed opinion.

    منار is AI-extracted now (released, see CLASSICAL_LLM_PILOT.md); its
    `quote` for this stop is the aligned mushaf word at wpos 22 («هُمۡۗ»,
    the last word of «وقليل ما هم»), not the regex pipeline's bare
    multi-word phrase — so this is matched by position, and by the note
    carrying the same «قليل» إعراب analysis, rather than by a `quote`
    substring."""
    row = next((r for r in rows if r['source'] == 'manar' and r['surah'] == 38
                and r['ayah'] == 24 and r['wpos'] == 22), None)
    assert row is not None
    assert row['grade'] == 'تام'
    assert 'قليل' in (row['note'] or '')
    assert row['reported_from'] is None


# ── regressions across the whole corpus ──────────────────────────────────

def test_no_book_is_tagged_as_reporting_its_own_author(rows):
    bad = [(r['source'], r['surah'], r['ayah'], r['reported_from']) for r in rows
           if r['reported_from'] and r['reported_from'] in _SELF_NAMES.get(r['source'], set())]
    assert not bad, f'{len(bad)} rows misattribute a self-reference as reported speech: {bad[:5]}'


def test_reported_from_is_a_small_conservative_fraction(rows):
    """The detector is deliberately narrow (only the direct object of «وقال
    NAME:»). A large fraction would mean the pattern went too broad and is
    now catching ordinary prose."""
    for src in pcw.SOURCES:
        sub = [r for r in rows if r['source'] == src]
        tagged = sum(1 for r in sub if r['reported_from'])
        frac = tagged / len(sub) if sub else 0
        assert frac < 0.05, f'{src}: {tagged}/{len(sub)} ({frac:.1%}) tagged — regex may be over-matching'


def test_reported_from_values_look_like_names_not_grade_words():
    """A detected 'name' that is actually one of the grade vocabulary words
    would mean the regex matched the wrong span (e.g. captured part of a
    grade phrase as if it were a scholar's name)."""
    grade_words = {g for g, _ in pcw.GRADES}
    conn = sqlite3.connect(DB_PATH)
    try:
        names = {row[0] for row in conn.execute(
            'SELECT DISTINCT reported_from FROM classical WHERE reported_from IS NOT NULL')}
    finally:
        conn.close()
    bad = names & grade_words
    assert not bad, f'reported_from values collide with grade vocabulary: {bad}'
