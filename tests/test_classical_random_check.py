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


# ── second round: attribution and reading conditions (2026-10-08) ─────────────

def test_manar_11_18_ibn_jarir_tamm_on_the_second_rabbihim(con):
    # «{على ربهم} الأول كاف … {على ربهم} الثاني، قال محمد بن جرير: تم الكلام …
    # فعلى قوله لا يوقف على «الظالمين»»
    got = rulings(con, 'manar', 11, 18)
    assert {(10, 'كاف', ''), (17, 'تام', 'محمد بن جرير'), (22, 'لا', 'محمد بن جرير')} <= got
    assert (17, 'لا', 'محمد بن جرير') not in got


@pytest.mark.parametrize('surah,ayah,wpos,expected', [
    (12, 105, 4, {(4, 'جائز', ''), (4, 'لا', '')}),   # جائز for رفع/نصب «والأرض» (note says so); Hafs جر: لا
    (13, 33, 28, {(28, 'لا', '')}),       # كاف only for «وصَدّوا»; Hafs «وصُدّوا»: ليس بوقف
    (13, 33, 23, {(23, 'كاف', '')}),
    (2, 7, 5, {(5, 'تام', ''), (5, 'جائز', '')}),   # no «لا» credited to الفراء (نصب «غشاوة»)
    (30, 25, 10, {(10, 'جائز', '')}),     # «{ثم إذا دعاكم دعوة} جائز», the author's own
])
def test_manar_hafs_side_of_reading_splits(con, surah, ayah, wpos, expected):
    assert rulings(con, 'manar', surah, ayah, wpos) == expected


def test_manar_30_25_no_duplicate_on_al_ard(con):
    assert not rulings(con, 'manar', 30, 25, 12)


def test_muktafa_29_58_relayed_from_ibn_al_anbari(con):
    # «{أجر العاملين} تام عند ابن الأنباري. وليس كذلك …»
    assert rulings(con, 'muktafa', 29, 58, 16) == {(16, 'تام', 'ابن الأنباري')}


@pytest.mark.parametrize('surah,ayah,wpos,grade,by', [
    (2, 259, 55, 'حسن', 'نافع'),       # «وعن نافع … {ثم نكسوها لحما} قطع حسن وكذا قال {…}»
    (2, 259, 66, 'حسن', 'نافع'),       # «وكذا قال {أعلم أن الله على كل شيء قدير}»
    (35, 35, 13, 'تام', 'الأخفش'),     # «… إلى {ولا يمسنا فيها لغوب} هذا التمام عنده»
    (38, 45, 7, 'كاف', 'بعضهم'),       # «وقال بعض أهل التمام … ومن قرأ {عبادنا} فوقفه الكافي …»
])
def test_nahhas_relayed_views(con, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, 'nahhas', surah, ayah, wpos)


def test_nahhas_non_hafs_abdana_dropped(con):
    # «من قرأ بقراءة ابن عباس {واذكر عبدنا} فوقفه الكافي {واذكر عبدنا إبراهيم}»
    assert not rulings(con, 'nahhas', 38, 45, 2)


# ── third round: wide check weighted toward منار (2026-10-08) ─────────────────

_ORD = {'الأول': 0, 'الأولى': 0, 'الثاني': 1, 'الثانية': 1, 'الثالث': 2, 'الثالثة': 2}


def test_manar_ordinal_heads_sit_on_the_named_occurrence(con):
    """Every «{X} [n] الأول/الأولى/الثاني…» head has a row on THAT occurrence of X
    in ayah n (the extraction used to put them on the last one)."""
    import json
    import re
    import sys
    from core.verse_words import verse_word_texts
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
    import build_classical_waqf as rx
    path = os.path.join(os.path.dirname(__file__), '..', 'pipeline', 'classical_sources',
                        'manar_shamela_sections.json')
    sections = json.load(open(path, encoding='utf-8'))
    head = re.compile(r'\{([^{}]{1,80})\}\s*\[(\d{1,3})\]\s*(الأولى|الأول|الثانية|الثاني|الثالثة|الثالث)(?![ء-ي])')
    bad = []
    for s in range(1, 115):
        sec = sections[str(s)]
        text = re.sub(r'[ً-ٰٟۖ-ۭ]', '', sec['text'] if isinstance(sec, dict) else sec)
        for m in head.finditer(text):
            a, o = int(m.group(2)), _ORD[m.group(3)]
            if a > rx.surah_ayah_count(s):
                continue
            q = [rx.norm(t) for t in re.sub(r'\s*\(\d+\)\s*$', '', m.group(1)).split()]
            w = [rx.norm(x) for x in verse_word_texts(f'{s}:{a}')[1]]
            occ = [i + len(q) - 1 for i in range(len(w) - len(q) + 1) if w[i:i + len(q)] == q]
            if len(occ) < 2 or o >= len(occ):
                continue
            if not con.execute("SELECT 1 FROM classical WHERE source='manar' AND surah=? AND ayah=? AND wpos=?",
                               (s, a, occ[o])).fetchone():
                bad.append((s, a, m.group(1), m.group(3)))
    assert not bad


def test_manar_names_are_nominative(con):
    assert not con.execute("SELECT 1 FROM classical WHERE source='manar' AND "
                           "(reported_from LIKE 'أبي %' OR reported_from LIKE '% وأبي %')").fetchone()


@pytest.mark.parametrize('surah,ayah,wpos,grade,by', [
    (9, 55, 4, 'حسن', 'أبو حاتم'),       # «… متصلا بالعذاب … وهو قول أبي حاتم»
    (43, 32, 24, 'تام', 'أبو حاتم'),     # «{سخريا} تام عند أبي حاتم، ومثله: «مما يجمعون»»
    (56, 10, 1, 'كاف', ''),              # «{ما أصحاب الميمنة} كاف، ومثله … «والسابقون السابقون»»
    (2, 89, 15, 'لا', ''),               # «ومثله في عدم الوقف «كفروا»؛ لأن جواب «لما» الأولى …»
    (2, 33, 6, 'لا', ''),                # «والثاني ليس بوقف»
    (38, 26, 22, 'لا', ''),
])
def test_manar_third_round(con, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, 'manar', surah, ayah, wpos)


def test_manar_third_round_drops(con):
    assert not rulings(con, 'manar', 5, 116, 34)              # «في نفسي» is not named
    assert (15, 'كاف', '') not in rulings(con, 'manar', 2, 69, 15)   # the كاف is «ما لونها»


@pytest.mark.parametrize('ayah', [67, 103, 121, 139, 158, 174, 190])
def test_muktafa_shuara_refrain(con, ayah):
    # «{إن في ذلك لآية} كاف. {مؤمنين} تام. {العزيز الرحيم} أتم منه. وكذلك جميع ما في السورة من ذلك»
    got = rulings(con, 'muktafa', 26, ayah)
    end = max(w for w, _, _ in got)
    assert (end, 'تام', '') in got                              # «مؤمنين»
    assert any(g == 'كاف' and w < end for w, g, _ in got)       # «لآية»
    assert rulings(con, 'muktafa', 26, ayah + 1, 4) == {(4, 'تام', '')}


@pytest.mark.parametrize('surah,ayah,quote,by', [
    (5, 95, 'أو عدل ذلك صياما', 'الأخفش'),
    (58, 8, 'حسبهم جهنم يصلونها', 'يعقوب'),
])
def test_nahhas_third_round(con, surah, ayah, quote, by):
    assert con.execute("SELECT reported_from FROM classical WHERE source='nahhas' AND surah=? AND ayah=? "
                       "AND quote=?", (surah, ayah, quote)).fetchone() == (by,)


@pytest.mark.parametrize('surah,ayah,grade', [
    (2, 1, 'تام'), (10, 1, 'تام'),                       # «{الم} حيث وقع»، «{الر} حيث وقع»
    (27, 61, 'كاف'), (27, 64, 'كاف'),                    # «{أإله مع الله} حيث وقع»
    (54, 15, 'تام'), (54, 51, 'تام'),                    # «وكذلك ما فيها ((من مدكر))»
    (77, 15, 'تام'), (77, 49, 'تام'), (77, 48, 'تام'),   # «{للمكذبين} … وكذلك ما قبل {ويل …}»
])
def test_muktafa_surah_wide_statements_reach_every_occurrence(con, surah, ayah, grade):
    assert any(g == grade and by == '' for _, g, by in rulings(con, 'muktafa', surah, ayah))


# ── fourth round: book → DB passages (2026-10-11) ─────────────────────────────

def test_manar_prose_nostops_all_have_a_row(con):
    """Every «فلا يوقف على «X»، ولا على «Y»» item the book lists in prose (and that
    sits on one occurrence near its entry) has a row on that word."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
    import audit_manar_mithl as mm
    missing = [x[:4] for x in mm.prose_nostops()
               if not con.execute("SELECT 1 FROM classical WHERE source='manar' AND surah=? AND ayah=? AND wpos=?",
                                  x[:3]).fetchone()]
    assert not missing


@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    # المكتفى: a blanket «وكذلك رؤوس الآي إلى قوله {يصنعون}» after «{العزيز الحكيم} تام» is تام
    # (it took the كاف of the next ruling «{فاتخذوه عدوا} كاف»)
    ('muktafa', 35, 3, 20, 'تام', ''),
    ('muktafa', 16, 63, 16, 'تام', ''),
    ('muktafa', 40, 20, 2, 'لا', ''),            # Hafs «يدعون»: «فلا يقطع»
    ('muktafa', 91, 14, 6, 'لا', ''),            # Hafs «ولا يخاف»: الواو حال
    ('muktafa', 19, 97, 9, 'تام', ''),           # «لدا» (sat on «ودا»)
    ('muktafa', 4, 123, 5, 'كاف', 'أصحاب التمام'),
    ('manar', 7, 54, 18, 'لا', ''),              # Hafs نصب «والشمس»
    ('manar', 47, 31, 5, 'لا', ''),              # Hafs «ونبلوَ»
    ('manar', 47, 31, 7, 'تام', ''),
    ('manar', 9, 72, 8, 'لا', ''),               # «فلا يوقف على «الأنهار»»
    ('manar', 9, 71, 19, 'كاف', 'قيل'),
    ('manar', 47, 27, 6, 'كاف', ''),
    ('nahhas', 2, 144, 33, 'تام', ''),           # «… الأولى والثانية جميعا تمام»
    ('nahhas', 2, 149, 16, 'تام', ''),
    ('nahhas', 2, 144, 19, 'كاف', ''),           # «{… شطره} مثله»
    ('nahhas', 32, 5, 5, 'تام', 'الأخفش'),
    ('nahhas', 32, 10, 13, 'كاف', ''),           # range from the book-spelled «والأفئدة»
    ('nahhas', 32, 9, 13, 'تام', ''),            # … which leaves the explicit تام alone
    ('nahhas', 5, 45, 15, 'تام', 'يعقوب'),
    ('nahhas', 18, 19, 14, 'كاف', ''),           # «وكذا {…} تم الكلام متصل» = ثم
    ('nahhas', 77, 43, 5, 'تام', ''),            # «… رؤوس الآيات تمام إلى آخر السورة»
    ('nahhas', 15, 25, 6, 'تام', ''),            # «… وكذا الآيات التي بعدها إلى {فسجد …}»
])
def test_fourth_round(con, book, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, book, surah, ayah, wpos)


def test_fourth_round_negatives(con):
    assert (14, 'تام', '') not in rulings(con, 'nahhas', 18, 19, 14)
    assert (9, 'كاف', '') not in rulings(con, 'nahhas', 32, 9, 13)
    assert con.execute("SELECT conf FROM classical WHERE source='nahhas' AND surah=5 AND ayah=47 "
                       "AND wpos=6 AND grade='حسن'").fetchone() == (1,)
