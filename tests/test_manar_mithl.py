"""منار الهدى «ومثله / وكذا» inheritance: pinned fixes + the audit as a gate.

منار extends a ruling to later stops with «ومثله «X»»، «وكذا «Y»»، «، و «Z»»,
without verse numbers. pipeline/audit_manar_mithl.py re-resolves every such
item mechanically; these tests pin representative repairs and keep the
released DB from drifting back.
"""
import os
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE


@pytest.fixture(scope='module')
def db():
    if not os.path.exists(CLASSICAL_WAQF_DATABASE):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    yield conn
    conn.close()


def grades_at(db, surah, ayah, wpos):
    return {g for (g,) in db.execute(
        "SELECT grade FROM classical WHERE source='manar' AND conf=1 "
        "AND surah=? AND ayah=? AND wpos=?", (surah, ayah, wpos))}


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (28, 88, 14, 'تام'),    # {لا إله إلا هو} تام، ومثله «إلا وجهه»
    (36, 48, 6, 'تام'),     # {مبين (47)} تام، ومثله «صادقين» — next verse
    (4, 92, 32, 'كاف'),     # ومثله «مؤمنة» في الموضعين
    (4, 92, 46, 'كاف'),
    (7, 195, 18, 'كاف'),    # وكذا «بها» الأخيرة
    (39, 20, 13, 'كاف'),    # «الأنهار»: الأشموني كاف (تام عند أبي حاتم)
])
def test_inherited_ruling_present(db, surah, ayah, wpos, grade):
    assert grade in grades_at(db, surah, ayah, wpos)


@pytest.mark.parametrize('surah,ayah,right,wrong,grade', [
    (13, 16, 6, 38, 'تام'),     # «قل الله»: قُلِ ٱللَّهُۚ, not «قل الله خالق»
    (22, 2, 14, 17, 'حسن'),     # «سكارى» — «دون الثاني»
    (2, 282, 21, 124, 'حسن'),   # «علمه الله», not «ويعلمكم الله»
    (7, 99, 2, 6, 'كاف'),       # «أفأمنوا مكر الله», not «فلا يأمن مكر الله إلا»
    (2, 165, 15, 28, 'حسن'),    # «حبا لله», not «وأن الله شديد»
])
def test_misplaced_row_moved_to_named_occurrence(db, surah, ayah, right, wrong, grade):
    assert grade in grades_at(db, surah, ayah, right)
    assert grade not in grades_at(db, surah, ayah, wrong)


def test_bihaa_first_three_are_not_stops(db):
    # «وفي المواضع الثلاثة لا يجوز الوقف؛ لأن أم عاطفة»
    for wpos in (3, 8, 13):
        assert grades_at(db, 7, 195, wpos) == {'لا'}


def test_yaksibun_inherits_kaf(db):
    # «لا يعلمون» كاف، ومثله «يكسبون»، و «كسبوا» الأولى والثانية تام فيهما
    assert grades_at(db, 39, 50, 10) == {'كاف'}
    assert 'تام' in grades_at(db, 39, 51, 3)
    assert 'تام' in grades_at(db, 39, 51, 11)


def test_baad_repeat_keeps_the_marked_occurrence(db):
    # وكذا «ببعض»: «وتكفرون ببعضٖۚ», not «أفتؤمنون ببعض الكتاب»
    assert 'حسن' in grades_at(db, 2, 85, 26)
    assert not grades_at(db, 2, 85, 23)


def test_mithl_audit_is_clean():
    from pipeline import audit_manar_mithl as audit
    recs = audit.audit(audit.load_db(CLASSICAL_WAQF_DATABASE))
    by = {}
    for r in recs:
        by.setdefault(r['status'], []).append(r)
    assert not by.get('missing'), f"inherited rulings absent: {by['missing'][:5]}"
    assert not by.get('unaligned'), f"unplaced chain items: {by['unaligned'][:5]}"
    assert not by.get('grade_mismatch')
    assert len(recs) >= 1850


def test_no_repeated_word_suspects_left():
    from pipeline import audit_manar_mithl as audit
    recs = audit.audit(audit.load_db(CLASSICAL_WAQF_DATABASE))
    moves, review = audit.misplaced_rows(CLASSICAL_WAQF_DATABASE, recs)
    assert not moves and not review, (moves[:5], review[:5])


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (6, 57, 18, 'جائز'),    # «يقض الحق» — Hafs «يَقُصُّ ٱلۡحَقَّۖ»
    (81, 24, 4, 'كاف'),     # «بظنين» — Hafs «بِضَنِينٖ»
    (78, 20, 3, 'حسن'),     # «سراجا» — the edition's typo for «سَرَابًا»
    (49, 3, 6, 'لا'),       # {عند رسول الله} ليس بوقف, not «امتحن الله»
    (2, 138, 1, 'حسن'),     # {صبغة الله} حسن; {صبغة} أحسن is w8
])
def test_reviewed_seats(db, surah, ayah, wpos, grade):
    assert grade in grades_at(db, surah, ayah, wpos)
