"""Rows corrected after the 240-row random check of the four books (2026-10-08,
artifacts/waqf-random-check/). Each case was read against the book."""
import os
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE

pytestmark = pytest.mark.skipif(not os.path.exists(CLASSICAL_WAQF_DATABASE),
                                reason='classical_waqf.db not built')


@pytest.fixture(scope='module')
def con():
    c = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    yield c
    c.close()


def rulings(con, source, surah, ayah, wpos=None):
    q = ("SELECT wpos, grade, COALESCE(reported_from, '') FROM classical "
         "WHERE source=? AND surah=? AND ayah=?")
    args = [source, surah, ayah]
    if wpos is not None:
        q += ' AND wpos=?'
        args.append(wpos)
    return set(con.execute(q, args).fetchall())


def test_muktafa_blanket_starts_after_the_mithl_it_follows(con):
    # «ومثله {وكيلا}. وكذلك الفواصل إلى قوله {تكون قريبا}»: {وكيلا} is 33:48
    # (also 33:3), so 33:45–47 have no المكتفى ruling
    for ayah in (45, 46, 47):
        assert not rulings(con, 'muktafa', 33, ayah)
    assert rulings(con, 'muktafa', 33, 49)


def test_manar_43_80_abu_hatim_is_on_bala(con):
    # «{ونجواهم بلى} كاف عند أبي حاتم، وقيل: الوقف على «نجواهم»»
    assert rulings(con, 'manar', 43, 80, 7) == {(7, 'كاف', 'أبو حاتم')}
    assert not rulings(con, 'manar', 43, 80, 6)


def test_manar_3_45_akhira_is_jaiz_only(con):
    assert rulings(con, 'manar', 3, 45, 17) == {(17, 'جائز', '')}


def test_manar_17_104_lafifa_is_the_authors_own(con):
    # «و «لفيفا» كلها وقوف كافية. قال السجاوندي: …» — السجاوندي gives the reason
    assert rulings(con, 'manar', 17, 104, 13) == {(13, 'كاف', '')}


def test_anbari_25_22_own_hasan_and_relayed_tamm(con):
    # «(ويقولون حجرا محجورا) [22 ي حسن … وروي عن الحسن أنه قال: (ويقولون حجرا) وقف تام»
    assert rulings(con, 'anbari', 25, 22) == {(9, 'حسن', ''), (8, 'تام', 'الحسن')}


def test_anbari_2_210_non_hafs_reading_dropped(con):
    # «لا يحسن» is for معاذ's «والملائكةِ وقضاءِ الأمر»; Hafs: «يحسن أن تقف على (الملائكة)»
    assert rulings(con, 'anbari', 2, 210, 10) == {(10, 'حسن', '')}


@pytest.mark.parametrize('surah,ayah,wpos,grade,by', [
    (11, 3, 16, 'كاف', 'أبو حاتم'),     # «وقف كاف حسن عند أبي حاتم وتمام عند الأخفش»
    (4, 162, 15, 'تام', 'سيبويه'),      # «{والمقيمين الصلاة} تمام على مذهب سيبويه»
    (35, 12, 18, 'صالح', ''),           # the copy's «حلبة» for «حِلۡيَةٗ»
    (34, 14, 12, 'كاف', ''),            # the copy's «سأته» for «مِنسَأَتَهُۥ»
    (19, 31, 4, 'تام', 'أحمد بن موسى'),  # «أينما كنت» — the stop is «كنت», not «ما»
    (2, 210, 9, 'تام', 'يعقوب'),        # «قال: من الوقف {…الغمام} … وقد خولف يعقوب في هذا»
])
def test_nahhas_seated_and_attributed(con, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, 'nahhas', surah, ayah, wpos)
    assert con.execute("SELECT conf FROM classical WHERE source='nahhas' AND surah=? AND ayah=? AND wpos=? "
                       "AND grade=?", (surah, ayah, wpos, grade)).fetchone() == (1,)


def test_nahhas_rejected_held_quotes_stay_unseated(con):
    # الأخفش's تمام is on «من آمن منهم بالله واليوم الآخر», not «آمنا»; «قالوا
    # طائركم أين ذكرتم» is a reading of الحسن, not a ruling on that phrase
    for q in ('وإذ قال إبراهيم رب اجعل هذا البلد آمنا', 'قالوا طائركم أين ذكرتم'):
        rows = con.execute("SELECT wpos, conf FROM classical WHERE source='nahhas' AND quote=?", (q,)).fetchall()
        assert rows and all(w is None and c == 0 for w, c in rows)
