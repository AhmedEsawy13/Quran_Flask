"""Text quality of the classical waqf books (المكتفى، منار الهدى، القطع
والائتناف، إيضاح الوقف) — pipeline/build_classical_waqf.py.

These pin down a real bug audit (2026-07): source-extraction noise was
leaking into the quotes/notes shown in مُكْث's «لماذا يُوقف هنا؟» card, and
the frontend was silently cropping the front off longer citations. Root
causes, all fixed in build_classical_waqf.py:

  - النحاس's edition marks page breaks as «[vol/ page]» (e.g. [1/ 57]) — a
    DIFFERENT format from the PageV\\dP\\d markers load_book() already
    stripped, so it landed verbatim mid-sentence: «وإذ واعدنا[1/ 57]موسى».
    Was in 21 quotes + 465 (26%) notes.
  - منار's ayah-end/footnote digits like «(1)» were stripped for WORD-
    MATCHING only, never from the stored/displayed quote — «الم (1)» instead
    of «الم». Was 4447/11194 (40%) of منار's quotes.
  - The quote field never got the whitespace-collapsing clean_note() already
    applied to notes, so an un-marked source line break left a raw newline
    or double-space inside the displayed text.

A quote/note that still contains one of these artifacts is not a "trimmed
word" in the sense of missing content, but it reads as visibly broken to
someone recognising the classical text — which is what triggered the report.
The traceability test below is the deeper guarantee the report actually
asked for: every quote genuinely IS a verbatim excerpt of the underlying
book, not a regex artifact.
"""
import os
import re
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'pipeline'))
sys.path.insert(0, _ROOT)
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_waqf as pcw  # noqa: E402

DB_PATH = os.path.join(_ROOT, 'data', 'classical_waqf.db')
SOURCES = ('muktafa', 'manar', 'nahhas', 'anbari')

_PAGE_MARKER_RE = re.compile(r'\[\s*\d+\s*/\s*\d+\s*\]')
_FOOTNOTE_DIGIT_RE = re.compile(r'\(\s*\d+\s*\)')


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


def test_db_has_all_four_books(rows):
    present = {r['source'] for r in rows}
    assert present == set(SOURCES)
    assert len(rows) > 15000  # sanity floor; each book harvests thousands


# ── text-quality regressions ────────────────────────────────────────────

def test_no_page_break_markers_in_quotes_or_notes(rows):
    bad = [(r['source'], r['surah'], r['ayah'], 'quote', r['quote']) for r in rows
           if r['quote'] and _PAGE_MARKER_RE.search(r['quote'])]
    bad += [(r['source'], r['surah'], r['ayah'], 'note', r['note']) for r in rows
            if r['note'] and _PAGE_MARKER_RE.search(r['note'])]
    assert not bad, f'page-break markers leaked into {len(bad)} rows, e.g. {bad[:5]}'


def test_no_footnote_digits_in_quotes(rows):
    bad = [(r['source'], r['surah'], r['ayah'], r['quote']) for r in rows
           if r['quote'] and _FOOTNOTE_DIGIT_RE.search(r['quote'])]
    assert not bad, f'footnote digits leaked into {len(bad)} quotes, e.g. {bad[:5]}'


def test_no_raw_whitespace_artifacts(rows):
    bad = []
    for r in rows:
        for field in ('quote', 'note'):
            v = r[field]
            if v and ('\n' in v or '\t' in v or '  ' in v):
                bad.append((r['source'], r['surah'], r['ayah'], field, v))
    assert not bad, f'{len(bad)} rows have raw newlines/double-spaces, e.g. {bad[:5]}'


# ── note truncation regressions (2026-07 second pass) ────────────────────
# «...ولما يأت» / «...وكررت» reports: notes were being cut mid-thought at a
# harvester-internal boundary — not clean_note()'s own word-boundary/ellipsis
# logic, which only ever engages past its 500-char limit. Two distinct causes,
# both in build_classical_waqf.py: نحاس pre-sliced every note to a flat 400
# raw chars BEFORE clean_note() ever saw it (91% of его notes landed in
# [390,400] and never got an ellipsis); منار/ابن الأنباري bounded a note by
# the RAW next quote-delimiter match, which can be the author citing a single
# word inline within his OWN prose (e.g. «وكررت "لا" في قوله...») rather than
# a genuine next citation.

def test_no_note_dangles_at_an_open_bracket(rows):
    """A note ending with a literal `{`/`(` is unambiguous — Arabic prose
    never legitimately ends a sentence there, so this can only mean the
    extraction window cut off right as the NEXT citation's quote began.
    (A word-list check for BARE grade-connectors like «التمام»/«الحسن» was
    tried and dropped — both are also ordinary vocabulary, «التمام» as a
    sentence predicate and «الحسن» as a scholar's name, الحسن البصري — so it
    false-positived on legitimate prose. Only the bracket itself is safe.)"""
    bad = [(r['source'], r['surah'], r['ayah'], (r['note'] or '')[-20:]) for r in rows
           if (r['note'] or '').rstrip().endswith(('{', '('))]
    assert not bad, f'{len(bad)} notes dangle at an open bracket, e.g. {bad[:5]}'


def test_nahhas_notes_are_not_clustered_at_a_flat_length_cap(rows):
    """Regression guard for the specific 400-char hard pre-slice bug: 91% of
    نحاس's notes used to land in exactly [390, 400] chars. A healthy
    boundary-based extraction produces a spread of lengths, not a wall."""
    lens = [len(r['note']) for r in rows if r['source'] == 'nahhas' and r['note']]
    clustered = sum(1 for l in lens if 390 <= l <= 400)
    assert clustered / len(lens) < 0.10, (
        f'{clustered}/{len(lens)} نحاس notes are clustered at 390-400 chars — '
        f'looks like the flat note_from+400 slice bug is back'
    )


def test_quotes_and_notes_are_not_empty_or_whitespace(rows):
    bad = [(r['source'], r['surah'], r['ayah']) for r in rows if not (r['quote'] or '').strip()]
    assert not bad, f'{len(bad)} rows have a blank quote, e.g. {bad[:5]}'


# ── clean_note() unit behavior (the shared cleaner for quote AND note) ──

def test_clean_note_never_cuts_mid_word():
    long_text = ('كلمة طويلة جدا ' * 60).strip()
    out = pcw.clean_note(long_text, limit=50)
    assert out.endswith('…')
    body = out[:-1].strip()
    words_in_source = set(long_text.split())
    assert all(w in words_in_source for w in body.split()), \
        f'truncated output contains a word not in the source: {out!r}'


def test_clean_note_strips_page_markers_and_footnote_digits():
    raw = 'وإذ واعدنا[1/ 57]  \nموسى (٤) أربعين'
    out = pcw.clean_note(raw)
    assert '[' not in out and ']' not in out
    assert '(' not in out and ')' not in out
    assert '\n' not in out and '  ' not in out
    assert out == 'وإذ واعدنا موسى أربعين'


def test_clean_note_short_text_passthrough():
    assert pcw.clean_note('  الحمد لله  .') == 'الحمد لله'


# ── traceability: every confident quote is a REAL excerpt of its book ───

@pytest.fixture(scope='module')
def source_word_streams():
    """Each book's text, tokenized + normalized the same way the harvester
    does, joined with padding spaces so `in` is a safe whole-word substring
    test (no accidental match across a word boundary)."""
    streams = {}
    for name, fname in pcw.SOURCES.items():
        body = pcw.load_book(fname)
        words = [pcw.norm(t) for t in re.findall(r'[؀-ۿ]+', body)]
        streams[name] = ' ' + ' '.join(w for w in words if w) + ' '
    return streams


@pytest.mark.parametrize('source', SOURCES)
def test_quotes_are_traceable_to_the_source_book(source, rows, source_word_streams):
    """The whole point of citing a classical book is that the citation is
    real. Every CONFIDENT row's quote — normalised the same way the aligner
    does — must occur, in order, as a contiguous run in that book's actual
    text. This is the guard against a regex capturing garbage instead of a
    genuine excerpt; it would have caught both bugs this file documents."""
    missing = []
    for r in rows:
        if r['source'] != source or not r['conf']:
            continue
        qwords = pcw.quote_words(r['quote'])
        if not qwords:
            continue
        needle = ' ' + ' '.join(qwords) + ' '
        if needle not in source_word_streams[source]:
            missing.append((r['surah'], r['ayah'], r['quote']))
    assert not missing, (
        f'{len(missing)} {source} quote(s) not found verbatim in the source book, '
        f'e.g. {missing[:5]}'
    )


def test_traceability_check_actually_detects_a_fabricated_quote(source_word_streams):
    """Guard against the traceability test above being accidentally vacuous
    (e.g. a bug that makes `needle in stream` always True)."""
    qwords = pcw.quote_words('هذا كلام مختلق ليس في الكتاب أبدا إطلاقا')
    needle = ' ' + ' '.join(qwords) + ' '
    assert needle not in source_word_streams['muktafa']


# ── frontend display cap: regression guard on the data side ─────────────

def test_no_confident_quote_exceeds_the_display_safety_cap(rows):
    """waqf_guide.js caps the displayed phrase at 24 mushaf words (raised
    from a bug-causing 8 — see the module docstring). If a future source
    update ever produces a longer confident quote, the frontend cap needs
    raising in lockstep, or citations will silently truncate again."""
    def qwc(q):
        return len(re.findall(r'[؀-ۿ]{2,}', q or ''))
    too_long = [(r['source'], r['surah'], r['ayah'], qwc(r['quote'])) for r in rows
                if r['conf'] and qwc(r['quote']) > 24]
    assert not too_long, (
        f'{len(too_long)} confident quotes exceed the frontend display cap '
        f'(static/js/waqf_guide.js maxW) — raise it: {too_long[:5]}'
    )
