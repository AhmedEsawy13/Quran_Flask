"""منار الهدى 2:26 pins: the book's «ما» rulings must not sit on the later مثلًا.

Book (Shamela 6496 JSON, surah 2): «مثلًا ما بعوضة» يُبنى الوقف على «ما»…
فمن رفع «بعوضةٌ» … كان الوقف على «ما» تامًّا، ومن نصبها … كان كافيًا …
ففي هذه الأوجه السبعة لا يوقف على «ما». Explicit markers keep فوقها كاف,
ربهم جائز, {بهذا مثلًا} كاف, كثيرًا الثاني حسن.
"""
import os
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE

MA = 'مَّا'
FAWQAHA = 'فَوۡقَهَا'
RABBIHIM = 'رَّبِّهِمۡ'
KATHEERA = 'كَثِيرٗا'
MITHLA = 'مَثَلٗا'


@pytest.fixture(scope='module')
def manar_226():
    if not os.path.exists(CLASSICAL_WAQF_DATABASE):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM classical WHERE source='manar' AND surah=2 AND ayah=26"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        pytest.skip('no manar rows for 2:26')
    return rows


def _norm_key(tok):
    from pipeline.build_classical_waqf import norm
    return norm(tok or '')


def test_la_on_ma_is_wpos_7_not_27(manar_226):
    la = [r for r in manar_226 if r['grade'] in ('لا',) or r['grade_raw'] == 'ليس بوقف']
    assert la, 'expected a ليس بوقف / لا row on 2:26'
    assert any(r['wpos'] == 7 for r in la)
    assert all(r['wpos'] != 27 for r in la if 'لا يوقف على' in (r['note'] or '') and 'ما' in (r['note'] or ''))
    ma_la = [r for r in la if r['wpos'] == 7]
    assert ma_la
    assert all(_norm_key(r['stop_word']) == _norm_key(MA) for r in ma_la)


def test_fawqaha_kaf_rabbhim_jaiz_second_katheera_hasan(manar_226):
    pairs = {(r['wpos'], r['grade']) for r in manar_226}
    assert (10, 'كاف') in pairs
    assert (18, 'جائز') in pairs
    assert (33, 'حسن') in pairs
    by_wpos = {10: FAWQAHA, 18: RABBIHIM, 33: KATHEERA}
    for r in manar_226:
        if r['wpos'] in by_wpos:
            assert _norm_key(r['stop_word']) == _norm_key(by_wpos[r['wpos']])


def test_no_la_yuqaf_ala_ma_pinned_to_mithla(manar_226):
    bad = [
        r for r in manar_226
        if r['note'] and 'لا يوقف على' in r['note'] and 'ما' in r['note']
        and _norm_key(r['stop_word']) == _norm_key(MITHLA)
    ]
    assert not bad, f'لا يوقف على «ما» still pinned to مثلًا: {[r["id"] for r in bad]}'


def test_ma_rulings_sit_on_recited_ma(manar_226):
    import app as quran_app
    _, words, _ = quran_app._verse_word_texts('2:26')
    assert _norm_key(words[7]) == _norm_key(MA)
    assert words[7] == MA
    ma_rows = [r for r in manar_226 if r['wpos'] == 7]
    grades = {r['grade'] for r in ma_rows}
    assert 'لا' in grades
    assert 'كاف' in grades
    assert 'تام' in grades
    assert all(_norm_key(r['stop_word']) == _norm_key(MA) for r in ma_rows)


def test_tighten_did_not_move_ma_off_wpos_7(manar_226):
    """Last-token tighten must not demote or move the recited «ما» pins."""
    ma_rows = [r for r in manar_226 if r['wpos'] == 7]
    assert ma_rows
    assert all(r['conf'] == 1 for r in ma_rows)
    from pipeline.build_classical_waqf import align_in_ayah, quote_words
    hit, level = align_in_ayah(2, 255, quote_words('الأرض'))
    assert hit == 43
    assert level == 1

