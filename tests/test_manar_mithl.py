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


# ── ابن الأنباري (pipeline/audit_anbari.py) ─────────────────────────────────
@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (23, 1, 2, 'حسن'),       # «قد أفلح المؤمنون» — المؤمنون had been filed under غافر
    (13, 11, 28, 'تام'),     # «فلا مرد له» — the book's [16] lags; the verse is 11
    (34, 12, 9, 'تام'),      # «ومثله: (عين القطر)» after «(وقدر في السرد) [11] [تام]»
    (18, 24, 3, 'حسن'),      # «(غدا. إلا أن يشاء الله)» rules on the phrase's end
    (114, 6, 2, 'تام'),      # «والوقف التام في سورة الإخلاص والفلق والناس آخر السورة»
])
def test_anbari_rulings(db, surah, ayah, wpos, grade):
    assert grade in {g for (g,) in db.execute(
        "SELECT grade FROM classical WHERE source='anbari' AND conf=1 "
        "AND surah=? AND ayah=? AND wpos=?", (surah, ayah, wpos))}


def test_anbari_negated_chain_items_are_not_served(db):
    # «(في إبراهيم والذين معه) [4] غير تام. وكذلك: (إنا براء منكم …)»
    assert not db.execute("SELECT 1 FROM classical WHERE source='anbari' AND conf=1 "
                          "AND surah=60 AND ayah=4 AND quote LIKE 'إنا براء%'").fetchone()


def test_anbari_relayed_sijistani_labelled(db):
    rows = db.execute("SELECT reported_from FROM classical WHERE source='anbari' AND surah=36 "
                      "AND ayah=58 AND wpos=0 AND grade='تام'").fetchall()
    assert rows and all(r[0] == 'السجستاني' for r in rows)


def test_anbari_audit_is_stable():
    from pipeline import audit_anbari as audit
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    try:
        recs = audit.audit(conn)
        assert not [r for r in recs if r['status'] in ('moved', 'relayed', 'regrade', 'negated_head')]
        assert not audit.missing_before_rulings(conn)
        assert not audit.missing_graded_entries(conn)
    finally:
        conn.close()


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (3, 36, 6, 'قبيح'),     # «وضعتُ» (أبو بكر) — Hafs reads «وضعَتْ»
    (23, 111, 4, 'حسن'),    # «إنهم» (حمزة والكسائي) — Hafs reads «أنهم»
    (8, 19, 19, 'حسن'),     # «وإن الله» — Hafs reads «وأنَّ»
    (7, 186, 5, 'قبيح'),    # «ويذرهم» بالجزم — Hafs reads it رفعًا
    (29, 41, 15, 'قبيح'),   # الفراء، about the first «العنكبوت»
])
def test_anbari_conditional_grade_before_rulings_are_held(db, surah, ayah, wpos, grade):
    # «فمن قرأ … يحسن الوقف على (X)» depends on a reading; not served as the book's ruling
    assert not db.execute("SELECT 1 FROM classical WHERE source='anbari' AND conf=1 AND surah=? "
                          "AND ayah=? AND wpos=? AND grade=? AND grade_raw IN "
                          "('يحسن الوقف','لا يحسن الوقف','يتم الوقف','يكفي الوقف')",
                          (surah, ayah, wpos, grade)).fetchone()


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (3, 36, 6, 'حسن'),      # Hafs «وضعَتْ»: كلام الله يبتدأ به
    (23, 111, 4, 'قبيح'),   # Hafs «أنَّهم»
    (8, 19, 19, 'قبيح'),    # Hafs «وأنَّ الله»
    (7, 186, 5, 'حسن'),     # Hafs «ويذرُهم» بالياء والرفع
    (10, 90, 14, 'قبيح'),   # the first «آمنت» (عامل في «أنَّه»)
    (59, 17, 4, 'حسن'),     # Hafs «خالدَين»
])
def test_anbari_hafs_side_of_reading_splits_is_served(db, surah, ayah, wpos, grade):
    assert db.execute("SELECT 1 FROM classical WHERE source='anbari' AND conf=1 AND surah=? "
                      "AND ayah=? AND wpos=? AND grade=?", (surah, ayah, wpos, grade)).fetchone()


def test_anbari_non_hafs_grade_after_rulings_dropped(db):
    # «فمن أخذ بهذه القراءة (أنى صببنا) قال: الوقف على (طعامه) تام»
    assert not db.execute("SELECT 1 FROM classical WHERE source='anbari' AND conf=1 AND surah=80 "
                          "AND ayah=24 AND wpos=3 AND grade='تام'").fetchone()
