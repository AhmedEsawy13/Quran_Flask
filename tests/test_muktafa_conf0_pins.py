"""المكتفى pins: proven moves off the book, no invented أحكام.

The regex harvest swallowed سورة المنافقون because OpenITI titles it
`# [سورة] المنافقون.` (not `### | سورة …`). Unique leftover conf=0 rows are
moved or filled off the book; `{quote} [grade]` parser misses are extracted.
Uthmani→imlāʾī folds (ء/ا, ىٰ, fused فيما, last-token ت/ي/ن) make unique
coords align_in_ayah successes. Period quotes pin to the word BEFORE the
period. Two genuinely unpinnable rows stay conf=0.
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
def muktafa():
    if not os.path.exists(DB_PATH):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM classical WHERE source='muktafa'"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        pytest.skip('no muktafa rows')
    return rows


def _row(rows, quote, surah=None):
    hits = [r for r in rows if r['quote'] == quote
            and (surah is None or r['surah'] == surah)]
    assert hits, f'missing muktafa quote {quote!r} surah={surah}'
    return hits[0]


def test_inline_heading_splits_munafiqun_from_jumuah():
    body = (
        '### | سورة الجمعة\n'
        '# {العزيز الحكيم} تام.\n'
        '# [سورة] المنافقون.\n'
        '# {فصدوا عن سبيل الله} كاف.\n'
        '# {كل صيحة عليهم} تام.\n'
        '# {فاحذرهم} كاف. ومثله {لن يغفر الله لهم} .\n'
        '# {حتى ينفضوا} تام. ومثله {الأذل} ومثله {لا يعلمون} .\n'
        '# {عن ذكر الله} [كاف] . ومثله {إذا جاء أجلها} .\n'
        '### | سورة التغابن\n'
        '# {وما في الأرض} كاف.\n'
    )
    rows = []
    pcw.harvest_muktafa(body, rows, 0)
    by_s = {}
    for r in rows:
        by_s.setdefault(r[1], []).append(r)
    assert set(by_s) == {62, 63, 64}
    q63 = [r[5] for r in by_s[63]]
    assert q63 == [
        'فصدوا عن سبيل الله', 'كل صيحة عليهم', 'فاحذرهم',
        'لن يغفر الله لهم', 'حتى ينفضوا', 'الأذل', 'لا يعلمون',
        'عن ذكر الله', 'إذا جاء أجلها',
    ]
    dhikr = next(r for r in by_s[63] if r[5] == 'عن ذكر الله')
    ajal = next(r for r in by_s[63] if r[5] == 'إذا جاء أجلها')
    assert dhikr[6] == 'كاف'
    assert ajal[6] == 'كاف'  # ومثله inherits [كاف], not the previous تام
    assert [r[5] for r in by_s[62]] == ['العزيز الحكيم']
    assert [r[5] for r in by_s[64]] == ['وما في الأرض']


def test_asr_and_falaq_book_sections_have_no_quote_grade_entries():
    body = pcw.normalize_muktafa_headings(
        pcw.load_book(pcw.SOURCES['muktafa']))
    import re
    last = 0
    got = {}
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title:
            continue
        num = pcw.surah_number(title, last)
        if num is None:
            continue
        last = num
        if num in (103, 113):
            got[num] = pcw.parse_muktafa_entries(text)
    assert got[103] == []
    assert got[113] == []


def test_munafiqun_pins_are_on_surah_63_not_62(muktafa):
    expected = {
        'فصدوا عن سبيل الله': (63, 2, 6, 'كاف'),
        'كل صيحة عليهم': (63, 4, 14, 'تام'),
        'فاحذرهم': (63, 4, 17, 'كاف'),
        'لن يغفر الله لهم': (63, 6, 11, 'كاف'),
        'حتى ينفضوا': (63, 7, 11, 'تام'),
        'الأذل': (63, 8, 8, 'تام'),
        'لا يعلمون': (63, 8, 16, 'تام'),
        'عن ذكر الله': (63, 9, 10, 'كاف'),
        'إذا جاء أجلها': (63, 11, 6, 'كاف'),
    }
    for quote, (surah, ayah, wpos, grade) in expected.items():
        r = _row(muktafa, quote, surah)
        assert r['ayah'] == ayah, quote
        assert r['wpos'] == wpos, quote
        assert r['grade'] == grade, quote
        assert r['conf'] == 1, quote
        assert r['surah'] == 63
    jumuah = [r for r in muktafa if r['surah'] == 62]
    assert {r['quote'] for r in jumuah} == {
        'العزيز الحكيم', 'لما يلحقوا بهم', 'يؤتيه من يشاء', 'العظيم',
        'يحمل أسفارا', 'بآيات الله', 'وذروا البيع', 'تفلحون',
        'وتركوك قائما', 'ومن التجارة',
    }
    assert not any(r['surah'] == 62 and r['quote'] in expected for r in muktafa)


def test_ilah_wahid_moved_off_ahad_prefix_false_hits(muktafa):
    r = _row(muktafa, 'إلا إله واحد', 5)
    assert r['ayah'] == 73 and r['wpos'] == 13 and r['conf'] == 1
    assert r['ayah'] != 6

    r = _row(muktafa, 'إلها واحدا', 9)
    assert r['ayah'] == 31 and r['wpos'] == 15 and r['conf'] == 1
    assert r['ayah'] != 4


def test_mukhtalif_alwanuhu_is_the_bee_ayah_not_ibrahim(muktafa):
    r = _row(muktafa, 'مختلف ألوانه', 16)
    assert r['ayah'] == 69 and r['wpos'] == 14 and r['conf'] == 1
    assert r['ayah'] != 122
    assert 'فيه' in (r['note'] or '')


def test_asr_and_falaq_have_no_db_rows(muktafa):
    """Book: لا وقف فيها دون آخرها / ليس فيها وقف كاف. No {quote} grade."""
    surahs = {r['surah'] for r in muktafa}
    assert 103 not in surahs
    assert 113 not in surahs
    assert 63 in surahs


def test_active_classical_sources_include_muktafa():
    from modules import breathing
    assert breathing._ACTIVE_CLASSICAL_SOURCES == {'manar', 'muktafa'}


def test_unique_conf0_pin_mismatches_moved_off_the_book(muktafa):
    """Wrong-word pins from the leftover 112, moved to the unique book landing."""
    expected = {
        ('والذين آمنوا', 2): (9, 3, 1),
        ('تعتدون', 2): (61, 58, 1),
        ('يا أولي الألباب', 2): (197, 28, 1),
        ('من الذين آمنوا', 2): (212, 8, 1),
        ('منهم تقاة', 3): (28, 20, 1),
        ('وهذا النبي والذين آمنوا', 3): (68, 9, 1),
        ('كان آمنا', 3): (97, 8, 1),
        ('العالمين', 3): (108, 10, 1),
        ('قوم آخرين', 6): (133, 17, 1),
        ('فيما آتاكم', 6): (165, 13, 1),
        ('فثبتوا الذين آمنوا', 8): (12, 9, 1),
        ('لا يعلمونهم', 8): (60, 18, 1),
        ('والذين آمنوا', 10): (103, 4, 1),
        ('تلك آيات الكتاب', 13): (1, 3, 1),
        ('القرآن العظيم', 15): (87, 6, 1),
        ('في كتاب', 20): (52, 5, 1),
        ('علمه', 20): (114, 16, 1),
        ('يذكر آلهتكم', 21): (36, 11, 1),
        ('يعقلون', 24): (61, 75, 1),
        ('وعند الذين آمنوا', 40): (35, 14, 1),
        ('لولا فصلت آياته', 41): (44, 7, 1),
    }
    for (quote, surah), (ayah, wpos, conf) in expected.items():
        r = _row(muktafa, quote, surah)
        assert r['ayah'] == ayah, quote
        assert r['wpos'] == wpos, quote
        assert r['conf'] == conf, quote


def test_unmatched_unique_quotes_filled_from_the_book(muktafa):
    expected = {
        ('فيما آتاكم', 5): (48, 39),
        ('ثم إليه ترجعون', 6): (36, 9),
        ('مذءوما مذعورا', 7): (18, 4, 0),
        ('بني إسرائيل', 7): (105, 17),
        ('واتبع هواه', 7): (176, 9),
        ('بنو إسرائيل', 10): (90, 23),
        ('إلا من قد آمن', 11): (36, 11),
        ('ومن آمن', 11): (40, 20),
        ('للظالمين', 11): (44, 16),
        ('الخاسرون', 12): (14, 8),
        ('إلها آخر', 15): (96, 5),
        ('لنريه من آياتنا', 17): (1, 16),
        ('بني إسرائيل', 26): (59, 3),
        ('من نفاذ', 38): (54, 6),
        ('لمن خلفك آية', 10): (92, 6),
        ('فارتدا على آثارهما', 18): (64, 7),
    }
    for (quote, surah), spec in expected.items():
        ayah, wpos = spec[0], spec[1]
        conf = spec[2] if len(spec) > 2 else 1
        r = _row(muktafa, quote, surah)
        assert r['ayah'] == ayah, quote
        assert r['wpos'] == wpos, quote
        assert r['conf'] == conf, quote


def test_bracket_grade_parser_misses_extracted(muktafa):
    """Same class as 63:9 {عن ذكر الله} [كاف] — GRADE_RE now sees [تام]/[كاف]/[حسن]."""
    r = _row(muktafa, 'ونقدس لك', 2)
    assert r['ayah'] == 30 and r['wpos'] == 21 and r['conf'] == 1 and r['grade'] == 'كاف'
    r = _row(muktafa, 'عذاب أليم', 2)
    assert r['ayah'] == 104 and r['wpos'] == 11 and r['conf'] == 1 and r['grade'] == 'كاف'
    r = _row(muktafa, 'ما يوم الفصل', 77)
    assert r['ayah'] == 14 and r['wpos'] == 4 and r['conf'] == 1 and r['grade'] == 'تام'


def test_leftover_unmatched_are_gone(muktafa):
    unmatched = [r for r in muktafa if r['ayah'] is None]
    assert unmatched == []


def test_falyatawakkal_moved_to_tawbah_muminun(muktafa):
    """Book quotes المتوكلون; the ayah is فليتوكل المؤمنون, unique in التوبة."""
    r = _row(muktafa, 'فليتوكل المتوكلون', 9)
    assert r['ayah'] == 51 and r['wpos'] == 13 and r['conf'] == 1
    assert r['stop_word']


def test_alayhim_ayatina_uses_the_second_landing_in_22_72(muktafa):
    """`{عليهم آياتنا} كاف. ومثله {بشر من ذلكم}` — second ءايتنا, before بشر."""
    r = _row(muktafa, 'عليهم آياتنا', 22)
    assert r['ayah'] == 72 and r['wpos'] == 16 and r['conf'] == 1


def test_period_quotes_pin_before_the_period(muktafa):
    """TWO-ayah quotes: stop is the last word BEFORE the period, except ذق."""
    expected = {
        'منزلين. بلى': (3, 124, 12),
        'سترا. كذلك': (18, 90, 14),
        'عهدا. كلا': (19, 78, 6),
        'منذرون. ذكرى': (26, 208, 6),
        'فاكهين. كذلك': (44, 27, 3),
        'متقابلين. كذلك': (44, 53, 4),
        'ينجيه. كلا': (70, 14, 5),
        'جنة نعيم. كلا': (70, 38, 7),
        'أن أزيد. كلا': (74, 15, 3),
        'عظامه. بلى': (75, 3, 4),
        'أساطير الأولين. كلا': (83, 13, 6),
        'أن لن يحور. بلى': (84, 14, 4),
        'بعاد. إرم': (89, 6, 5),
        'أخلده. كلا': (104, 3, 3),
    }
    for quote, (surah, ayah, wpos) in expected.items():
        r = _row(muktafa, quote, surah)
        assert r['ayah'] == ayah, quote
        assert r['wpos'] == wpos, quote
        assert r['conf'] == 1, quote
    r = _row(muktafa, 'من عذاب الحميم. ذق', 44)
    assert r['ayah'] == 49 and r['wpos'] == 0 and r['conf'] == 1
    r = _row(muktafa, 'بعاد. إرم', 89)
    assert r['reported_from'] == 'نافع'
    r = _row(muktafa, 'فاكهين. كذلك', 44)
    assert r['reported_from']


def test_sulaka_ya_musa_moved_off_hadith_musa(muktafa):
    r = _row(muktafa, 'سؤلك يا موسى', 20)
    assert r['ayah'] == 36 and r['wpos'] == 4 and r['conf'] == 1


def test_genuinely_unpinnable_leftovers(muktafa):
    """conf=0: not unique after the aligner pass, plus k=1 SequenceMatcher-only pins."""
    leftover = {(r['id'], r['quote']) for r in muktafa if r['conf'] == 0}
    assert leftover == {
        (27, 'مستهزئون'),
        (260, 'مساكين'),               # مسكين, not مساكين
        (391, 'وأبناءنا'),
        (463, 'شيئا'),
        (524, 'أأسلمتم'),
        (651, 'ههنا'),
        (1303, 'مذءوما مذعورا'),      # qiraʾat مدحورا, quote not in Hafs
        (2397, 'ورئيا'),
        (2542, 'ذلك هو الضلال البعيد يدعو'),
        (2640, 'ملبسون'),             # مبلسون
        (2693, 'والأبصار'),           # والآصال
        (2740, 'بالله ورسوله'),        # twice in 24:62 (wpos 5 and 23)
        (2798, 'يستهزئون'),
        (2992, 'يستهزئون'),
        (3079, 'والأفئدة'),
        (3225, 'العلماء'),
        (3267, 'يستهزؤون'),
        (3303, 'وبالليل'),
        (3765, 'بأيد'),
        (4044, 'فاحذرهم'),
        (4105, 'والأفئدة'),
        (4320, 'باله'),               # بالهزل
        (4403, 'واستغفروه'),
    }


def test_aligner_folds_leftover_quotes():
    """Unique leftover quotes now align_in_ayah uniquely at the recited stop."""
    cases = [
        (7, 105, pcw.quote_words('بني إسرائيل'), 17),
        (5, 48, pcw.quote_words('فيما آتاكم'), 39),
        (36, 52, pcw.quote_words('قالوا يا ويلنا'), 1),
        (101, 10, pcw.quote_words('ماهيه'), 3),
        (79, 33, pcw.quote_words('لأنعامكم'), 2),
        (24, 41, pcw.quote_words('والطير صافات'), 11),
        (2, 9, pcw.quote_words('والذين آمنوا'), 3),
        (20, 36, pcw.quote_words('سؤلك يا موسى'), 4),
    ]
    for surah, ayah, qwords, wpos in cases:
        hit, level = pcw.align_in_ayah(surah, ayah, qwords)
        unique, _ = pcw.align_in_ayah_unique(surah, ayah, qwords)
        assert hit == wpos, (surah, ayah, qwords, hit)
        assert unique == wpos, (surah, ayah, qwords, unique)
        assert level == 1, (surah, ayah, qwords, level)


def test_muktafa_ama_tushrikun_is_nahl_1_not_tashkurun(muktafa):
    """النحل 1 {عما تشركون} must not fuzzy-match 16:14 تشكرون."""
    row = _row(muktafa, 'عما تشركون', 16)
    assert (row['ayah'], row['wpos']) == (1, 8)


def test_muktafa_yakhluqun_is_nahl_20_not_zukhruf_yakhlufun(muktafa):
    """{يخلقون} with أموات is النحل 20, not الزخرف 60 يخلفون."""
    row = _row(muktafa, 'يخلقون', 16)
    assert (row['ayah'], row['wpos']) == (20, 9)


def test_muktafa_alladhina_amanu_is_ghafir_7_not_amatna(muktafa):
    """غافر {للذين آمنوا} is 40:7, not 40:11 أمتنا."""
    row = _row(muktafa, 'للذين آمنوا', 40)
    assert (row['ayah'], row['wpos']) == (7, 12)


def test_quote_words_ama_tushrikun_does_not_align_to_tashkurun():
    """Lone last-token SequenceMatcher must not map تشركون onto تشكرون."""
    q = pcw.quote_words('عما تشركون')
    hit, _ = pcw.align_in_ayah(16, 14, q)
    unique, _ = pcw.align_in_ayah_unique(16, 14, q)
    assert hit is None
    assert unique is None
    import app as quran_app
    _, words, _ = quran_app._verse_word_texts('16:14')
    assert pcw.norm(words[20]) == pcw.norm('تشكرون')
    unique_nahl1, _ = pcw.align_in_ayah_unique(16, 1, q)
    assert unique_nahl1 == 8
