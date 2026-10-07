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
    ('muktafa', 69, 3, 3, 'تام'),      # «وما أدراك ما الحاقة» — was 69:2 (last word only)
    ('muktafa', 11, 99, 5, 'كاف'),     # «ويوم القيامة» — was 11:98's «يوم القيامة»
    ('muktafa', 33, 20, 22, 'تام'),    # «إلا قليلا» after «أشحة على الخير» — was 33:18
    ('anbari', 2, 3, 2, 'حسن'),        # «الغيب» — a «…» quote after a {…} [3] lemma
    ('anbari', 5, 107, 25, 'حسن'),     # «… لمن الظالمين» — not 5:106's «لمن الآثمين»
    ('nahhas', 13, 35, 18, 'تام'),     # «أكلها دائم وظلها ... وعقبى الكافرين النار»
    ('nahhas', 9, 119, 7, 'تام'),      # «يا أيها …» is one word (يَٰٓأَيُّهَا) in the mushaf
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


def test_multi_word_quotes_end_where_they_are_seated(rows):
    """A quote of two or more words must end, word for word, in its own verse
    when it does so in another verse of the surah: 69:2 held «وما أدراك ما
    الحاقة» (69:3) and 11:98 «ويوم القيامة» (11:99, 11:98 has no و) because
    only the last word was matched (found 2026-09-28 against quranpedia.app)."""
    from pipeline import audit_manar_mithl as mm
    from pipeline import build_classical_waqf as rx
    # checked against the book's order: the book drops or adds a leading و
    # («والله واسع عليم» for 2:115's «إن الله»), the phrase is still here
    ok = {('muktafa', 2, 115, 11), ('muktafa', 2, 150, 30), ('muktafa', 4, 102, 55), ('muktafa', 53, 28, 4),
          ('anbari', 2, 217, 17), ('anbari', 9, 106, 11), ('nahhas', 8, 4, 10), ('nahhas', 41, 15, 24)}
    bad = []
    for r in rows:
        q = (r['quote'] or '').replace('...', ' ')
        if (r['source'], r['surah'], r['ayah'], r['wpos']) in ok or r['grade_raw'] in ('رؤوس الآي', 'آخر السورة') or '.' in q or '…' in q:
            continue
        if len(rx.quote_words(q, mm.hnorm)) < 2 or mm.hits_in_ayah(r['surah'], r['ayah'], q, True):
            continue
        if any(mm.hits_in_ayah(r['surah'], b, q, True)
               for b in range(1, rx.surah_ayah_count(r['surah']) + 1) if b != r['ayah']):
            bad.append((r['id'], r['source'], r['surah'], r['ayah'], r['quote']))
    assert not bad, bad[:5]


def test_repeated_words_do_not_stack_a_stop_and_a_no_stop(rows):
    """Two unattributed rulings of one book on ONE occurrence of a word the
    verse repeats, one a stop and one «ليس بوقف», mean one belongs on the other
    occurrence (2:13 «السفهاء» كاف «لحرف التنبيه» is the first, the لا «للاستدراك»
    the second) — unless the book makes one of them conditional."""
    from pipeline import build_classical_waqf as rx
    from core.verse_words import verse_word_texts
    cond = re.compile(r'إن\s|إذا\s|لمن\s|من\s+(?:قرأ|رفع|نصب|جعل|فتح|كسر|وقف)|قرأ|قراءة|جعل|على\s+قول')
    seat = {}
    for r in rows:
        if r['reported_from'] or r['grade_raw'] in ('رؤوس الآي', 'آخر السورة'):
            continue
        seat.setdefault((r['source'], r['surah'], r['ayah'], r['wpos']), []).append(r)
    bad = []
    for (src, s, a, w), rs in seat.items():
        gs = {r['grade'] for r in rs}
        if not (gs & {'لا', 'قبيح'}) or not (gs - {'لا', 'قبيح'}):
            continue
        if any(cond.search(r['note'] or '') for r in rs):
            continue
        words = verse_word_texts(f'{s}:{a}')[1]
        if sum(rx.norm(x) == rx.norm(words[w]) for x in words) > 1:
            bad.append((src, s, a, w, sorted(gs)))
    assert not bad, bad[:5]


@pytest.mark.parametrize('source,surah,ayah,wpos,grade', [
    ('manar', 2, 13, 11, 'كاف'),       # «السفهاءۗ ألا» — was on the second «السفهاء»
    ('manar', 3, 7, 4, 'لا'),          # «أنزل عليك الكتابَ» («منه آيات» صفته)
    ('manar', 2, 246, 20, 'حسن'),      # «{في سبيل الله} حسن. {ألا تقاتلوا} كاف»
    ('manar', 61, 14, 5, 'لا'),        # «ولا يوقف على «الله»» — «كونوا أنصار الله»
    ('manar', 65, 1, 29, 'لا'),        # «حدود الله فقد ظلم» — جواب الشرط لم يأت
    ('manar', 89, 17, 0, 'تام'),       # «كلا» (أبو عمرو), not «بل لا»
    ('manar', 89, 21, 0, 'تام'),       # «كلا في الموضعين»
    ('muktafa', 7, 43, 35, 'تام'),     # «{تعلمون} تام» between «رسل ربنا بالحق» and «قالوا نعم»
    ('muktafa', 28, 71, 16, 'تام'),    # «{بيضاء} تام. والآية أتم» = «بضياء» (28:68…72)
    ('muktafa', 39, 52, 14, 'تام'),    # «لقوم يؤمنون», after «سيئات ما كسبوا» (48)
    ('nahhas', 35, 28, 16, 'تام'),     # «والتمام عند غيره {إن الله عزيز غفور}»
])
def test_rows_seated_by_the_2026_10_07_sweeps(rows, source, surah, ayah, wpos, grade):
    assert any((r['source'], r['surah'], r['ayah'], r['wpos'], r['grade']) == (source, surah, ayah, wpos, grade)
               for r in rows)


def test_remarks_are_not_stops(rows):
    """«و «ثم» لترتيب الأخبار» (4:153), «و «كتب» أجرى مجرى القسم» (58:21) and a
    braced «{عند} غيره» (35:39) are the books' remarks, not rulings."""
    from pipeline import build_classical_waqf as rx
    assert not [(r['source'], r['surah'], r['ayah'], r['quote']) for r in rows
                if ' '.join(map(rx.norm, (r['quote'] or '').split())) in ('ثم', 'كتب', 'عند') and r['grade'] != 'لا'
                and (r['source'], r['surah'], r['ayah']) not in {('manar', 23, 41), ('manar', 75, 12)}]


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (1, 4, 0, 'قبيح'),       # «والوقف على (ملك) قبيح لأنه مضاف» — no [n] in the book
    (2, 11, 10, 'حسن'),      # «والوقف على «المصلحين» حسن»
    (2, 39, 9, 'تام'),       # «والوقف على «خالدين» [39] تام»
    (4, 176, 40, 'حسن'),     # «(مثل حظ الأونثيين) [76]» — a garbled [176]
    (29, 41, 8, 'قبيح'),     # «فلا يحسن الوقف على (العنكبوت)» against الأخفش's «(كمثل العنكبوت) تام»
    (36, 19, 2, 'حسن'),      # Hafs «أئن» بالكسر: «وقف: (طائركم معكم)»
    (24, 36, 13, 'قبيح'),    # Hafs «يسبِّح»: «لم يقف على (الآصال)»
    (53, 6, 2, 'قبيح'),      # «الوقف على (استوى) قبيح لأن (هو) نسق»
])
def test_anbari_rulings_read_from_the_held_list(rows, surah, ayah, wpos, grade):
    assert any((r['source'], r['surah'], r['ayah'], r['wpos'], r['grade']) == ('anbari', surah, ayah, wpos, grade)
               for r in rows)


def test_manar_rulings_on_a_repeated_word_follow_book_order(rows):
    """منار lists a verse's stops in order, so a ruling on a word the verse
    repeats sits between the verse's previous and next rulings (2:229 «حدود
    الله» الأول كاف is 21, not 42; 28:9 ابن عباس's «لا» is «لا تقتلوه»)."""
    from pipeline import audit_manar_mithl as mm
    ok = {(7, 143, 10)}        # «إليك» heads a «ومثله» chain whose items follow it
    byv = {}
    for r in rows:
        if r['source'] == 'manar':
            byv.setdefault((r['surah'], r['ayah']), []).append(r)
    bad = []
    for (s, a), rs in byv.items():
        rs.sort(key=lambda r: (r['seq'], r['id']))
        for i, r in enumerate(rs):
            if (s, a, r['wpos']) in ok:
                continue
            occ = sorted(set(mm.hits_in_ayah(s, a, r['quote'], True) or mm.hits_in_ayah(s, a, r['quote'], False)))
            if len(occ) < 2 or r['wpos'] not in occ:
                continue
            lo = max([x['wpos'] for x in rs[:i] if x['wpos'] != r['wpos']] or [-1])
            hi = min([x['wpos'] for x in rs[i + 1:] if x['wpos'] != r['wpos']] or [999])
            if not lo < r['wpos'] < hi and any(lo < o < hi for o in occ):
                bad.append((s, a, r['wpos'], r['quote']))
    assert not bad, bad[:5]


@pytest.mark.parametrize('source,surah,ayah,wpos,grade', [
    # every «{X} GRADE» the book states has a row (2026-10-07 recall check)
    ('muktafa', 2, 255, 49, 'تام'),    # «{العلي العظيم} تمام الكلام»
    ('muktafa', 54, 5, 4, 'تام'),      # «{بالغة} كاف على الوجهين. {النذر} تام»
    ('muktafa', 6, 163, 4, 'كاف'),     # «وقال الدينوري … تام. وليس كذلك، هما كافيان»
    ('muktafa', 57, 14, 5, 'كاف'),     # «وقالا {قالوا بلى} تمام، وهما كافيان»
    ('nahhas', 3, 122, 7, 'حسن'),      # the grade on the next line after «}»
    ('nahhas', 7, 202, 6, 'كاف'),
    ('anbari', 7, 49, 6, 'حسن'),       # «(لا ينالهم الله برحمة) [49] وقف حسن:»
])
def test_rulings_recalled_from_the_book(rows, source, surah, ayah, wpos, grade):
    assert any((r['source'], r['surah'], r['ayah'], r['wpos'], r['grade']) == (source, surah, ayah, wpos, grade)
               for r in rows)


def test_a_relayed_ruling_and_the_authors_correction_both_stand(rows):
    """6:163 «وقال الدينوري: … {وبذلك أمرت} تام. وليس كذلك، هما كافيان»."""
    got = {(r['grade'], r['reported_from']) for r in rows
           if (r['source'], r['surah'], r['ayah'], r['wpos']) == ('muktafa', 6, 163, 4)}
    assert got == {('تام', 'الدينوري'), ('كاف', None)}
