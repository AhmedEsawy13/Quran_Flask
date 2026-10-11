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


# ── follow-up: ابن الأنباري and النحاس recall patterns (2026-10-11) ────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('anbari', 30, 58, 18, 'تام', ''),            # «… تام، وأتم منه: (إلا مبطلون)»
    ('anbari', 23, 11, 5, 'تام', ''),             # «وأتم منه: (هم فيها خالدون)»
    ('anbari', 64, 1, 16, 'حسن', ''),             # «وأحسن منه: (وهو على كل شيء قدير)»
    ('anbari', 27, 34, 10, 'تام', ''),            # «(وجعلوا أعزة أهلها أذلة) [34] هذا وقف تام»
    ('anbari', 48, 29, 27, 'تام', 'الفراء'),       # «قال الفراء: … تمام الكلام على قوله: (ذلك مثلهم في التوراة)»
    ('anbari', 30, 25, 10, 'تام', 'المفسرون'),     # «وقال المفسرون: الكلام يتم على (ثم إذا دعاكم دعوة)»
    ('nahhas', 11, 83, 7, 'تام', 'غيره'),          # «والتمام عند أبي حاتم {…} وعند غيره {وما هي من الظالمين ببعيد}»
    ('nahhas', 19, 65, 11, 'تام', 'غيره'),         # «… وعند غيره {هل تعلم له سميا}»
])
def test_recall_followup(con, book, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, book, surah, ayah, wpos)


# ── second passage check (2026-10-11) ─────────────────────────────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('anbari', 61, 4, 10, 'تام', ''),             # «ومثله: (…) [3] (كأنهم بنيان مرصوص) [4] (…)»
    ('anbari', 61, 5, 17, 'تام', ''),             # … «(أزاغ الله قلوبهم)، وأتم منه»
    ('anbari', 2, 255, 25, 'حسن', ''),            # «وكذلك (…) [255]، (سنة ولا نوم)، (وما في الأرض)، (إلا بإذنه)…»
    ('anbari', 2, 257, 17, 'حسن', ''),            # «[وكذلك] (يخرجونهم من النور إلى الظلمات)»
    ('anbari', 58, 2, 18, 'حسن', ''),             # المجادلة quotes in {…}: «{… وزورا} [2] حسن»
    ('anbari', 58, 7, 46, 'تام', ''),
    ('nahhas', 83, 26, 1, 'كاف', ''),             # «(ختامه مسك) قطع كاف وكذا {المتنافسون}»
    ('nahhas', 83, 26, 5, 'كاف', ''),
    ('nahhas', 13, 16, 36, 'تام', 'الأخفش'),       # «… وبعده {فتشابه الخلق عليهم} هذا كله عن الأخفش»
    ('nahhas', 6, 30, 12, 'تام', 'نافع'),          # «… {قالوا بلى وربنا} … هذا كله عن نافع»
    ('nahhas', 81, 21, 2, 'تام', 'أبو حاتم'),      # «قال أبو حاتم … والتمام بعده عنده {مطاع ثم أمين}»
    ('nahhas', 35, 10, 13, 'تام', 'أبو حاتم'),     # «{والعمل الصالح يرفعه} هذا اختيار أبي حاتم»
    ('muktafa', 23, 89, 1, 'كاف', ''),            # «{سيقولون لله} كاف في الثلاثة»
    ('muktafa', 8, 42, 30, 'تام', ''),            # «{ويحيى من حي عن بينة} … وهو التمام»
    ('muktafa', 21, 20, 1, 'تام', 'أحمد بن موسى'),
])
def test_second_passage_check(con, book, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, book, surah, ayah, wpos)


def test_anbari_chain_heads_precede_items(con):
    """An inserted chain item takes the book-order seq after every row seated
    before it, so «قد تبين» (2:256) is not taken to follow «يخرجونهم» (2:257)."""
    follows = con.execute("SELECT COALESCE(follows, '') FROM classical WHERE source='anbari' AND surah=2 "
                          "AND ayah=256 AND wpos=8").fetchone()[0]
    assert '257' not in follows


# ── third passage check: النحاس ranges and «على ما روى عن» (2026-10-11) ───────

@pytest.mark.parametrize('surah,ayah,wpos,grade,by', [
    (52, 30, 6, 'صالح', ''),        # «تم القطع على رؤوس الايات صالح إلى {سحاب مركوم}» (no madda)
    (52, 42, 6, 'صالح', ''),
    (29, 43, 7, 'تام', ''),         # «قطع تام وكذا رؤوس الآيات إلى {…}»: the previous grade
    (91, 13, 6, 'صالح', ''),        # «قطع صالح وكذا آخر الايات إلى {فسواها}»
    (52, 13, 5, 'تام', 'نافع'),     # «والتمام على ما روى عن نافع {يوم يدعون إلى نار جهنم دعا}»
    (8, 74, 13, 'تام', 'نافع'),
])
def test_nahhas_ranges_and_relays(con, surah, ayah, wpos, grade, by):
    assert (wpos, grade, by) in rulings(con, 'nahhas', surah, ayah, wpos)


def test_nahhas_range_stops_before_its_target(con):
    # «إلى {سحاب مركوم} فإنه تمام، {يومهم الذي فيه يصعقون} ليس بتمام»
    assert not any(g == 'صالح' for _, g, _ in rulings(con, 'nahhas', 52, 45))


# ── fourth passage check: منار، المكتفى، ابن الأنباري (2026-10-11) ────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('anbari', 20, 53, 18, 'حسن', ''),        # «ومثله: (…) [36].\n(…) [40]\n(من نبات شتى) [53]» — list over lines
    ('anbari', 93, 8, 2, 'تام', ''),         # «ومثله: (من الأولى) [4]. (فترضى) [5] (فإغنى) [8]»
    ('muktafa', 27, 45, None, 'كاف', ''),    # «ورؤوس الآي بعد كافية» (34) not cut off by «ورأس الآية أتم» (43)
    ('muktafa', 114, 6, 2, 'تام', ''),       # «والتمام آخر السورة»
    ('muktafa', 45, 10, 15, 'كاف', ''),      # «{كأن لم يسمعها} كاف. مثله {من دون الله أولياء}»
    ('muktafa', 111, 4, 0, 'كاف', ''),       # Hafs «حمالةَ»: «يكفي الوقف على قوله {وامرأته}»
    ('manar', 3, 81, 9, 'لا', ''),           # «ولا يوقف على قوله: «وحكمة»»
    ('manar', 95, 3, 2, 'لا', ''),           # «ولا وقف من أولها إلى «تقويم» فلا يوقف على «الأمين»» (no [n] yet)
    ('manar', 31, 14, 2, 'كاف', 'أبو حاتم'),  # «قال أبو حاتم السجستاني: هذه الثلاثة كافية»
    ('manar', 31, 14, 14, 'حسن', 'العماني'),
    ('manar', 5, 64, 4, 'جائز', 'بعضهم'),
    ('manar', 8, 65, 25, 'حسن', ''),         # «و «لا يفقهون» كذلك» (of حسن)
])
def test_fourth_passage_check(con, book, surah, ayah, wpos, grade, by):
    if wpos is None:
        assert any(g == grade and b == by for _, g, b in rulings(con, book, surah, ayah))
    else:
        assert (wpos, grade, by) in rulings(con, book, surah, ayah, wpos)


def test_manar_33_13_no_duplicate_on_biawra(con):
    assert (20, 'حسن', '') not in rulings(con, 'manar', 33, 13, 20)


# ── fifth passage check (2026-10-11) ──────────────────────────────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 55, 13, None, 'تام', ''),     # «كل شيء في هذه السورة من {فبأي آلاء ربكما تكذبان} تام»
    ('muktafa', 55, 75, None, 'تام', ''),
    ('muktafa', 70, 21, 3, 'لا', ''),         # «{إلا المصلين} استثناء … فلا يكفي الوقف قبله»
    ('muktafa', 43, 81, 4, 'تام', 'الحسن وقتادة'),
    ('muktafa', 55, 62, 2, 'تام', 'ابن الأنباري'),
    ('manar', 53, 45, None, 'لا', ''),        # «ولا يوقف على شيء من أواخر الآيات … في ثلاثة عشر موضعا»
    ('manar', 89, 7, 0, 'جائز', 'نافع'),       # «{بعاد (6) إرم} [6، 7] وقف عند نافع»
    ('manar', 89, 14, 2, 'تام', 'الأخفش'),
])
def test_fifth_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


def test_fifth_passage_check_drops(con):
    assert not rulings(con, 'muktafa', 10, 12, 14)       # «المر» of 13:1 seated on «ضره مر»
    assert not rulings(con, 'manar', 89, 6, 5)           # «بعاد» — the stop is «إرم»
    assert ('كاف' not in {g for _, g, _ in rulings(con, 'muktafa', 70, 21, 3)})


def test_anbari_chain_skips_discussed_or_negated_quotes(con):
    # «(… الله ربكم) [125، 126] كان الربيع … يقرؤون»; «(… وأهلك) [40] قال السجستاني: هو وقف …
    # وليس يوقف»; «(وأن الله ليس بظلام للعبيد) [51] غير تام»
    assert not rulings(con, 'anbari', 37, 126, 1)
    assert not rulings(con, 'anbari', 11, 40, 13)
    assert not rulings(con, 'anbari', 8, 51, 8)


# ── sixth passage check (2026-10-11, reviewed by gpt-6-luna) ─────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    # «والفواصل بين ذلك كافية» after a surah-wide refrain: between its first and last occurrence
    ('muktafa', 26, 15, None, 'كاف', ''),
    ('muktafa', 37, 90, None, 'كاف', ''),
    ('muktafa', 38, 35, None, 'كاف', ''),
    ('muktafa', 54, 20, None, 'كاف', ''),
    ('muktafa', 74, 4, None, 'كاف', ''),       # «وكذلك كل آية بعدها كافية إلى {ولربك فاصبر}»
    ('muktafa', 9, 30, 9, 'كاف', ''),          # «[وقالت النصارى المسيح ابن الله. كاف]»
    ('muktafa', 74, 31, 45, 'كاف', ''),        # «[ومثله] {ويهدي من يشاء}»
    ('muktafa', 74, 53, 0, 'تام', ''),         # «{كلا} أيضا تام»
    ('muktafa', 89, 14, 2, 'تام', ''),         # «جواب القسم {إن ربك لبالمرصاد} وهو تام»
    ('muktafa', 56, 27, 4, 'تام', ''),         # the second «اليمين» of «… ما أصحاب اليمين»
    ('manar', 52, 29, 7, 'كاف', ''),           # «كاف؛ للابتداء بالاستفهام، قال الخليل: …» (reason only)
    ('anbari', 16, 116, 21, 'تام', ''),        # «[116]. وقف تام» — not the list's حسن
    ('anbari', 12, 43, 14, 'حسن', ''),         # «[43 ي حسن غير تام» — a scan slip for «[43]»
    ('anbari', 82, 5, 4, 'تام', ''),           # «… [5] جواب (إذا) [1] وهو وقف التمام»
    ('anbari', 82, 12, 2, 'تام', ''),          # «ومثله: (يعلمون ما تفعلون)»
])
def test_sixth_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


def test_sixth_passage_check_drops(con):
    assert not rulings(con, 'muktafa', 56, 27, 1)        # first «اليمين»
    assert not rulings(con, 'anbari', 68, 14, 4)         # «(أن كان ذا مال وبنين) [14] قرأ …»
    assert 'حسن' not in {g for _, g, _ in rulings(con, 'anbari', 16, 116, 21)}


# ── seventh passage check (2026-10-11, reviewed by gpt-6-luna) ───────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 7, 74, 16, 'كاف', ''),         # «[ومثله] {وتنحتون الجبال بيوتا}»
    ('muktafa', 7, 176, 19, 'كاف', ''),        # «[ومثله] {أو تتركه يلهث}»
    ('muktafa', 7, 92, 6, 'تام', ''),          # bare quote between two «ومثله» items
    ('muktafa', 7, 39, 13, 'تام', ''),         # «{ومن فوقهم غواش} {يكسبون} تام» — 7:39, not 7:96
    ('muktafa', 15, 13, 2, 'كاف', ''),         # «… تام. وهو عندي كاف»
    ('muktafa', 15, 25, 6, 'تام', ''),         # Hafs «حكيم عليم»: the verse end
    ('muktafa', 60, 1, 7, 'كاف', 'نصير بن يوسف ومحمد بن عيسى'),
    ('muktafa', 60, 1, 19, 'حسن', ''),         # «وقال ابن الأنباري: هو حسن. وكذلك هو عندي»
    ('muktafa', 60, 4, 44, 'تام', ''),         # «والتمام {وما أملك لك من الله من شيء}»
    ('muktafa', 60, 11, 14, 'تام', ''),        # «{عليم حكيم} تام. ومثله {ما أنفقوا}»
    ('manar', 15, 72, 0, 'قبيح', ''),          # «والوقف على «لعمرك» قبيح»
    ('manar', 44, 5, 5, 'حسن', ''),            # the author's, not سعيد بن جبير's
    ('anbari', 79, 36, 3, 'حسن', ''),          # «(وبرزت الجحيم لمن يرى) [36] مثله»
    ('anbari', 11, 44, 5, 'حسن', ''),          # «ومثله: (يا سماء أقلعي) [44] قال السجستاني: …»
])
def test_seventh_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


def test_seventh_passage_check_drops(con):
    assert 'تام' not in {g for _, g, _ in rulings(con, 'muktafa', 7, 96, 17)}
    assert 'تام' not in {g for _, g, _ in rulings(con, 'muktafa', 60, 10, 46)}
    assert not rulings(con, 'muktafa', 15, 25, 5)
    assert not rulings(con, 'anbari', 74, 53, 0)          # «و (كلا) [53] قد استقصينا أمرها …»


# ── eighth passage check (2026-10-11, reviewed by gpt-6-luna) ────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 37, 4, 2, 'كاف', ''),          # «جواب القسم: {إن إلهكم لواحد} وهو وقف كاف»
    ('muktafa', 37, 5, 6, 'تام', ''),          # «{ورب المشارق} التمام»
    ('muktafa', 38, 25, 1, 'تام', 'يعقوب والدينوري'),   # «التمام ((فغفرنا له))»
    ('muktafa', 68, 5, 1, 'تام', 'المازني'),
    ('muktafa', 68, 6, 1, 'تام', 'غيره'),      # «وقال غيره {بأيكم المفتون} التمام. ومثله …»
    ('muktafa', 68, 9, 3, 'تام', 'غيره'),
    ('manar', 34, 13, 8, 'لا', ''),            # ابن كثير is cited for the ياء, not the ruling
    ('anbari', 65, 1, 11, 'حسن', ''),          # «[ومثله]: (وأحصوا العدة واتقوا الله ربكم)، …»
    ('anbari', 65, 1, 25, 'حسن', ''),
])
def test_eighth_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


def test_eighth_passage_check_drops(con):
    assert 'جائز' not in {g for _, g, _ in rulings(con, 'manar', 57, 4, 31)}   # stray beside «أحسن»


# ── wrong-word check (seat_check.py, 2026-10-11) ─────────────────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos', [
    ('muktafa', 4, 78, 28),      # «قل كل من عند الله» — the second «من عند الله»
    ('muktafa', 6, 158, 13),     # «بعض آيات ربك»
    ('muktafa', 9, 37, 21),      # «فيحلوا ما حرم الله»
    ('muktafa', 20, 69, 10),     # «كيد ساحر», not «الساحر»
])
def test_wrong_word_check_moves(con, book, surah, ayah, wpos):
    assert rulings(con, book, surah, ayah, wpos)


# ── ninth passage check (2026-10-11, reviewed by gpt-6-luna) ─────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 24, 28, 17, 'كاف', ''),        # «{هو أزكى لكم} شبيه بالتام
    ('muktafa', 24, 28, 21, 'تام', ''),        #  ورأس الآية أتم»
    ('muktafa', 24, 45, 30, 'تام', ''),        # «وآخر الآية أتم منهما»
    ('muktafa', 18, 22, 11, 'تام', 'أبو إسحاق الزجاج'),
    ('muktafa', 18, 44, 0, 'تام', 'الدينوري'),  # «{وما كان منتصرا. هنالك} تمام»
    ('muktafa', 48, 29, 30, 'تام', 'مجاهد'),   # «والتمام على قول مجاهد: {ومثلهم في الإنجيل}»
    ('muktafa', 18, 63, 19, 'تام', 'بعض أهل التأويل'),
    ('manar', 104, 4, 0, 'تام', ''),           # «{أخلده (3) كلا} [3، 4] تام» — on «كلا»
    ('anbari', 7, 150, 38, 'حسن', ''),         # «وأحسن منهن: (ولا تجعلني مع القوم الظالمين)»
    ('anbari', 7, 151, 7, 'حسن', ''),          # «[151]. حسن»
    ('anbari', 75, 30, 3, 'حسن', ''),          # «[30] [حسني.» — a scan slip
    ('anbari', 19, 6, 7, 'تام', ''),           # «ب 6] وقف تام»
    ('anbari', 19, 79, 0, 'تام', ''),          # «(… عهدا. كلا) [78، 79] وقف التمام»
    ('anbari', 42, 2, 0, 'حسن', ''),           # «(حم. عسق) [1، 2] وقف حسن»
    ('anbari', 15, 85, 13, 'تام', ''),         # «… تام. مثله: (فاصفح الصفح الجميل)»
])
def test_ninth_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


# ── tenth passage check (2026-10-11, reviewed by gpt-6-luna) ─────────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 81, 5, None, 'كاف', ''),       # «ورؤوس الآي بين ذلك كافية» before the answer
    ('muktafa', 81, 14, 3, 'تام', ''),         # «جواب {إذا} {علمت نفس ما أحضرت} … وهو تام»
    ('muktafa', 81, 21, 1, 'تام', 'نافع'),     # «وقال نافع: {مطاع ثم} تم»
    ('muktafa', 81, 27, 4, 'لا', ''),          # «ولا يوقف على {العالمين}»
    ('muktafa', 72, 10, None, 'كاف', 'بعض العلماء'),    # «والوقف على رأس كل آية كاف»
    ('muktafa', 72, 5, 9, 'تام', 'بعض العلماء'),        # «ويتم على قوله {على الله كذبا}»
    ('muktafa', 69, 19, None, 'كاف', ''),      # «وكذلك سائر هاءات الاستراحة في هذه السورة»
    ('muktafa', 69, 45, None, 'كاف', ''),
    ('muktafa', 3, 122, 11, 'تام', ''),        # «{والله وليهما} تام، والآية أتم»
    ('muktafa', 28, 35, 14, 'تام', ''),        # «ورأس الآية أتم»
    ('muktafa', 77, 7, 2, 'تام', ''),          # «جواب القسم {إنما توعدون لواقع} وهو تمام»
    ('muktafa', 112, 4, None, 'تام', ''),      # «والتمام في آخرها»
    ('muktafa', 28, 25, 2, 'لا', ''),          # «لم يوقف على قوله ((تمشي))»
    ('manar', 82, 7, 2, 'جائز', 'بعضهم'),      # «وجوز بعضهم الوقف على: «فسواك» لمن خفف»
    ('manar', 112, 3, None, 'كاف', 'بعضهم'),   # «كذا وسمه بعضهم بالكافي»
])
def test_tenth_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)


# ── coverage sweep (2026-10-11): «قبل» ranges reach back to the previous statement ──

@pytest.mark.parametrize('surah,ayah', [(50, 5), (50, 28), (19, 3), (9, 6), (16, 85), (59, 5)])
def test_qabl_ranges_reach_back(con, surah, ayah):
    # «{بظلام للعبيد} كاف. وكذلك الفواصل قبل» (50:29); «ورؤوس الآي قبل وبعد كافية» (19:21, 9:11 …)
    assert 'كاف' in {g for _, g, _ in rulings(con, 'muktafa', surah, ayah, None)}


def test_bayna_dhalika_stays_between_the_items(con):
    # «{فأوعى} تام. ومثله {مكرمون} والفواصل بين ذلك كافية» — not back to 70:1
    assert not rulings(con, 'muktafa', 70, 9, None)


# ── eleventh passage check (2026-10-11, reviewed by gpt-6-luna) ──────────────

@pytest.mark.parametrize('book,surah,ayah,wpos,grade,by', [
    ('muktafa', 25, 21, 11, 'تام', ''),        # «… كاف عند أبي حاتم … وهو عندي تام»
    ('muktafa', 25, 21, 11, 'كاف', 'أبو حاتم وابن الأنباري وابن عبد الرزاق'),
    ('muktafa', 25, 21, 18, 'كاف', ''),        # «تام ورؤوس الآي كافية» — not «والفواصل تامة» (22 on)
    ('muktafa', 12, 52, 11, 'تام', ''),        # «{… كيد الخائنين} تمام الكلام»
    ('muktafa', 27, 43, 11, 'تام', ''),        # «ورأس الآية أتم»
    ('manar', 102, 5, 4, 'كاف', ''),           # «كلا لو تعلمون علم اليقين»، وهو أكفى مما قبله
    ('manar', 12, 15, 8, 'حسن', ''),           # «وبهذا يحسن الوقف على «الجب»»
    ('anbari', 26, 208, 6, 'حسن', ''),         # «(لها منذرون) [208] وهذا عندنا وقف حسن»
])
def test_eleventh_passage_check(con, book, surah, ayah, wpos, grade, by):
    got = rulings(con, book, surah, ayah, wpos)
    assert any(g == grade and b == by for _, g, b in got)
