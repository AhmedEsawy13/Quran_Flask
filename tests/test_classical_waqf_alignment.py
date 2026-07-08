"""Word-position alignment in the classical waqf books — pipeline/
build_classical_waqf.py. A DIFFERENT concern from text quality (see
test_classical_waqf_quality.py) or attribution (see
test_classical_waqf_attribution.py): these tests pin down that a citation
lands on the CORRECT occurrence of its word(s), not just any occurrence.

Triggered by a user report on 2:255 (آية الكرسي) that several stops were
missing or misaligned — «إلا بما شاء», «السماوات والأرض» (وما في الأرض
appears TWICE in this ayah), and «حفظهما». Root causes, all fixed in
build_classical_waqf.py:

  - align_cursor() (شared by مكتفى + نحاس): when a short word repeats near
    the cursor, scanning a fixed direction (back-window first, or forward-
    only) returns whichever occurrence the scan reaches first — not the one
    nearest the cursor. مكتفى's «والأرض» landed on the FIRST «الأرض» in
    2:255 (wpos 18), 25 words before the intended second occurrence (wpos
    43, «السماوات والأرض» — spelled WITH the و, matching the quote exactly).
    Fixed by picking whichever match is closest to the cursor by absolute
    distance, regardless of direction.
  - _MITHL_RE (منار's ومثله/وكذا chain-inheritance trigger) didn't recognise
    «وكذا» at all, and multi-item chains under ONE «وكذا ... و X، و Y» trigger
    only ever captured the first item — «ما شاء»، «الأرض»، «حفظهما» were all
    silently dropped for 2:255. Fixed by adding «وكذا» to the trigger set and
    a distance-bounded chain-continuation check (_CHAIN_GAP_RE/_CHAIN_WINDOW)
    for the bare «، و» connector.
  - harvest_manar()'s confidence rule distrusted EVERY single-word guillemet
    match (`len(qwords) >= 2` required), even when explicitly chain-linked —
    so the recovered «الأرض»/«حفظهما» entries above existed in the DB but
    were filtered out of the API (`WHERE conf=1`) and never reached the user.
    Fixed by also trusting a single word when it's chain-linked (is_mithl).
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


@pytest.fixture(scope='module')
def rows_2_255():
    if not os.path.exists(DB_PATH):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            'SELECT * FROM classical WHERE surah=2 AND ayah=255').fetchall()
    finally:
        conn.close()


# ── align_cursor() unit tests ────────────────────────────────────────────

def test_align_cursor_prefers_closest_match_forward():
    """A repeated short word AHEAD of the cursor: the occurrence nearer the
    cursor must win, not simply the first one a forward scan reaches."""
    stream = [(1, 0, 'كلمة'), (1, 1, 'وسط'), (1, 2, 'كلمة'), (1, 3, 'اخر')]
    hit, _ = pcw.align_cursor(stream, 0, ['كلمة'])
    assert hit == 0  # nearer the cursor than index 2


def test_align_cursor_prefers_closest_match_when_true_hit_is_behind():
    """The true match sits just BEHIND the cursor, but the same word recurs
    much further ahead. A naive forward-only search would jump to the
    distant, unrelated occurrence; closest-by-distance must not."""
    stream = [(1, 0, 'مشترك')] + [(1, i, f'حشو{i}') for i in range(1, 30)] + [(1, 30, 'مشترك')]
    hit, _ = pcw.align_cursor(stream, 2, ['مشترك'])
    assert hit == 0  # distance 2, vs distance 28 to the far occurrence


def test_align_cursor_finds_the_second_of_two_close_occurrences():
    """Mirror of the reported bug: the SAME word twice in a tight span, with
    the cursor already advanced past the first — must pick the one closer to
    the cursor, not re-hit the earlier, already-consumed occurrence."""
    stream = [(1, 0, 'ارض'), (1, 1, 'حشو1'), (1, 2, 'حشو2'), (1, 3, 'وارض')]
    hit, _ = pcw.align_cursor(stream, 3, ['وارض'])
    assert hit == 3


# ── the exact reported case, pinned end-to-end ───────────────────────────

def test_muktafa_al_ard_lands_on_the_second_occurrence(rows_2_255):
    """مكتفى's «والأرض» in 2:255 must land on wpos 43 («وَٱلۡأَرۡضَۖ» in
    «وسع كرسيه السماوات والأرض»), NOT wpos 18 (the first، unrelated «الأرض»
    in «وما في الأرض»)."""
    row = next((r for r in rows_2_255 if r['source'] == 'muktafa'
                and r['quote'] == 'والأرض'), None)
    assert row is not None
    assert row['conf'] == 1
    assert row['wpos'] == 43


def test_manar_recovers_the_full_kadha_chain(rows_2_255):
    """منار's «وكذا ب «ما شاء»، و «الأرض»، و «حفظهما»» chain — all three
    items must be extracted, correctly graded كاف, and confidently visible
    (not just present but filtered out by conf=0)."""
    manar = [r for r in rows_2_255 if r['source'] == 'manar']
    by_quote = {r['quote']: r for r in manar}
    for quote, expected_wpos in (('ما شاء', 39), ('الأرض', 43), ('حفظهما', 46)):
        assert quote in by_quote, f'منار is missing the chained «{quote}» stop for 2:255'
        row = by_quote[quote]
        assert row['grade'] == 'كاف'
        assert row['wpos'] == expected_wpos
        assert row['conf'] == 1, f'«{quote}» is extracted but not confident/visible'


def test_manar_al_ard_chain_item_is_the_second_occurrence(rows_2_255):
    """منار's chained «الأرض» must land on the SAME word as مكتفى's «والأرض»
    (wpos 43) — the second occurrence, not the first (wpos 18)."""
    row = next(r for r in rows_2_255 if r['source'] == 'manar' and r['quote'] == 'الأرض')
    assert row['wpos'] == 43


# ── confidence-rule regressions across the whole corpus ─────────────────

def test_chain_linked_single_word_confidence_is_a_small_fraction():
    """Trusting chain-linked (ومثله/وكذا) single-word matches recovers real
    data, but should still only affect a modest slice of منار — a large
    fraction would suggest is_mithl is over-firing on ordinary prose."""
    if not os.path.exists(DB_PATH):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        manar = conn.execute("SELECT quote, conf FROM classical WHERE source='manar'").fetchall()
    finally:
        conn.close()
    single_word_confident = sum(1 for r in manar if r['conf'] and ' ' not in r['quote'].strip())
    frac = single_word_confident / len(manar)
    assert 0 < frac < 0.6, f'{single_word_confident}/{len(manar)} ({frac:.1%}) — unexpected range'
