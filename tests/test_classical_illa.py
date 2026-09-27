"""العلّة shown for classical rulings (core/classical_illa.py, stored by
pipeline/derive_illa.py) and whole-corpus checks across the four books."""
import os
import re
import sqlite3

import pytest

from core.classical_illa import split, _plain

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'classical_waqf.db')


# ── the extractor ───────────────────────────────────────────────────────────
@pytest.mark.parametrize('note,quote,raw,expect', [
    ('ومثله', 'فما أصبرهم على النار', 'تام', ''),                       # chain word only
    ('ومثله «نفيرًا»', 'نفيرا', 'كاف', ''),                               # chain + its own word
    ('ومثله «رحمة»؛ للابتداء بإن', 'رحمة', 'حسن', 'للابتداء بإن'),        # chain + a reason
    ('{ونقدس لك} [كاف] وقيل: تام', 'عليم', 'تام', ''),                    # the NEXT quote's ruling
    ('(قال هذا رحمة من ربي) [98] وقف حسن غير تام، وهو من كلام ذي القرنين إلى قوله: (وعد ربي حقا)',
     'قال هذا رحمة من ربي', 'حسن', 'غير تام، وهو من كلام ذي القرنين إلى قوله: (وعد ربي حقا)'),
    ('وكذلك: (متى نصر الله) [214] والوقف على (إن نصر الله قريب) تام', 'متى نصر الله', 'حسن', ''),
    ('تجري من تحتها الأنهار) [14] [تام]', 'ولبئس العشير', 'تام', ''),      # note began inside the next quote
    ('فقال: أخرهم إلى وقت السحر. ثنا علي بن محمد قال: ثنا عبد الله', 'سوف أستغفر لكم ربي', 'كاف',
     'فقال: أخرهم إلى وقت السحر'),                                       # isnad cut
    ('{وتجعلون له أندادا} قطع كاف وكذا {رب العالمين} إن ابتدأت الخبر {سواء للسائلين} قطع كاف',
     'رب العالمين', 'كاف', 'إن ابتدأت الخبر'),
    ('{كذلك نفصل الآيات لقوم يعلمون} قطع تام تم الوقف على رؤوس الآيات حسن إلى قوله جل وعز {أو كذب بآياته}',
     'يستقدمون', 'رؤوس الآي', 'حكم عام: «تم الوقف على رؤوس الآيات حسن إلى قوله جل وعز {أو كذب بآياته}»'),
    ('{كل شيء هالك إلا وجهه} والتمام آخر السورة', 'ترجعون', 'آخر السورة', 'التمام آخر السورة'),
    ('وكذا رأس الآية التي بعدها {يا أيها الذين آمنوا}', 'حقا على المتقين', 'كاف', ''),
])
def test_split(note, quote, raw, expect):
    assert split(note, quote, raw)[0] == expect


def test_chain_is_detected_from_the_words_before_the_quote():
    assert split('{الوسيلة} قطع صالح وكذا {وجاهدوا في سبيله} والتمام {لعلكم تفلحون}', 'وجاهدوا في سبيله')[1]
    assert not split('{وجاهدوا في سبيله} قطع صالح وكذا {لعلكم تفلحون}', 'وجاهدوا في سبيله')[1]


# ── the stored columns, all four books ──────────────────────────────────────
@pytest.fixture(scope='module')
def rows():
    if not os.path.exists(DB):
        pytest.skip('classical_waqf.db not built')
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if 'illa' not in {c[1] for c in con.execute('PRAGMA table_info(classical)')}:
        pytest.fail('run pipeline/derive_illa.py')
    out = [dict(r) for r in con.execute('SELECT * FROM classical WHERE conf=1')]
    con.close()
    return out


def test_every_served_row_has_a_derived_illa(rows):
    assert not [r['id'] for r in rows if r['illa'] is None], 'run pipeline/derive_illa.py'


def test_illa_is_never_bare_chain_wording_or_an_isnad(rows):
    bad = [(r['source'], r['surah'], r['ayah'], r['illa'][:50]) for r in rows if r['illa'] and (
        re.match(r'^(?:و?مثله|و?كذا|و?كذلك)\s*[:،]?\s*[«{(]', r['illa'])
        or re.search(r'(?<![ء-ي])(?:حدثنا|أخبرنا|ثنا)(?![ء-ي])', r['illa'])
        or r['illa'].rstrip().endswith(('{', '(', '«', '['))
        or re.fullmatch(r'(?:وقف\s+)?(?:تام|كاف|حسن|صالح|جائز)', r['illa'].strip()))]
    assert not bad, bad[:5]


def test_each_follows_names_an_earlier_row_with_the_same_grade(rows):
    by_seat = {}
    for r in rows:
        by_seat.setdefault((r['source'], r['surah'], r['ayah']), []).append(r)
    # checked 2026-09-27: the book lists these after a later verse («ومثله»
    # reaching back), and the phrase occurs only where it is seated
    back_refs = {('muktafa', 9, 63), ('muktafa', 9, 89), ('muktafa', 9, 97), ('muktafa', 10, 18),
                 ('muktafa', 28, 57), ('muktafa', 35, 32), ('muktafa', 35, 33), ('anbari', 24, 11)}
    bad = []
    for r in rows:
        if not r['follows']:
            continue
        quote, ayah = re.fullmatch(r'(.*) \((\d+)\)', r['follows']).groups()
        heads = by_seat.get((r['source'], r['surah'], int(ayah)), [])
        if not any(r['grade'] == h['grade'] and quote in (_plain(h['quote']), _plain(h['stop_word']))
                   for h in heads):
            bad.append((r['source'], r['surah'], r['ayah'], r['follows']))
        elif int(ayah) > r['ayah'] and (r['source'], r['surah'], r['ayah']) not in back_refs:
            bad.append((r['source'], r['surah'], r['ayah'], r['follows'], 'head after item'))
    assert not bad, bad[:5]


@pytest.mark.parametrize('source,surah,ayah,wpos,grade', [
    ('muktafa', 2, 135, 5, 'تام'),     # «تهتدون» — was on 2:150's «لعلكم تهتدون»
    ('muktafa', 6, 94, 11, 'كاف'),     # «وراء ظهورهم» — was 6:31
    ('muktafa', 15, 85, 7, 'تام'),     # «إلا بالحق» — was 15:8
    ('muktafa', 15, 96, 7, 'تام'),     # «فسوف يعلمون» الثاني
    ('muktafa', 54, 21, 3, 'تام'),     # «ونذر حيث وقع … إذا كان بعده ولقد يسرنا»
    ('muktafa', 55, 44, 4, 'تام'),     # «وبين حميم آن» — was 55:33
    ('anbari', 8, 36, 8, 'حسن'),       # «ليصدوا عن سبيل الله» [26] in the book
    ('anbari', 2, 283, 19, 'حسن'),     # «وليتق الله ربه» after «فرهان مقبوضة»
    ('nahhas', 24, 58, 48, 'تام'),     # «والله عليكم حكيم» — was 24:18
])
def test_rows_moved_by_the_book_order_sweep(rows, source, surah, ayah, wpos, grade):
    assert any((r['source'], r['surah'], r['ayah'], r['wpos'], r['grade']) == (source, surah, ayah, wpos, grade)
               for r in rows)


@pytest.mark.parametrize('source,surah,ayah,wpos', [
    ('muktafa', 2, 150, 30),           # only «لعلكم تهتدون» (its own row) may stay here
    ('manar', 78, 36, 4),              # the stray «حسابا» كاف
    ('anbari', 7, 9, 6),               # «أولم يتفكروا في أنفسهم» belongs to الروم
])
def test_stray_rows_are_gone(rows, source, surah, ayah, wpos):
    got = [r for r in rows if (r['source'], r['surah'], r['ayah'], r['wpos']) == (source, surah, ayah, wpos)]
    if (source, surah, ayah) == ('muktafa', 2, 150):
        assert [r['quote'] for r in got] == ['لعلكم تهتدون']
    elif (source, surah, ayah) == ('manar', 78, 36):
        assert all(r['grade'] != 'كاف' for r in got)
    else:
        assert not got


def test_blanket_rows_never_sit_under_an_explicit_ruling(rows):
    explicit = {(r['surah'], r['ayah'], r['wpos']) for r in rows
                if r['source'] == 'muktafa' and r['grade_raw'] != 'رؤوس الآي'}
    assert not [r['id'] for r in rows if r['source'] == 'muktafa' and r['grade_raw'] == 'رؤوس الآي'
                and (r['surah'], r['ayah'], r['wpos']) in explicit]
