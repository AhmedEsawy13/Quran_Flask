"""المكتفى low-confidence pins: proven moves off the book, no invented أحكام.

The regex harvest swallowed سورة المنافقون because OpenITI titles it
`# [سورة] المنافقون.` (not `### | سورة …`). Unique leftover conf=0 rows are
moved or filled off the book; `{quote} [grade]` parser misses are extracted.
Period quotes, reported-from rulings, and genuinely repeated/discursive
rows stay conf=0. Coords filled under hamza/ت-ي orthography stay conf=0
until align_in_ayah succeeds.
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


def test_active_classical_sources_still_manar_only():
    from modules import breathing
    assert breathing._ACTIVE_CLASSICAL_SOURCES == {'manar'}


def test_unique_conf0_pin_mismatches_moved_off_the_book(muktafa):
    """Wrong-word pins from the leftover 112, moved to the unique book landing."""
    expected = {
        ('والذين آمنوا', 2): (9, 3, 0),
        ('تعتدون', 2): (61, 58, 0),
        ('يا أولي الألباب', 2): (197, 28, 1),
        ('من الذين آمنوا', 2): (212, 8, 0),
        ('منهم تقاة', 3): (28, 20, 0),
        ('وهذا النبي والذين آمنوا', 3): (68, 9, 0),
        ('كان آمنا', 3): (97, 8, 0),
        ('العالمين', 3): (108, 10, 0),
        ('قوم آخرين', 6): (133, 17, 0),
        ('فيما آتاكم', 6): (165, 13, 0),
        ('فثبتوا الذين آمنوا', 8): (12, 9, 0),
        ('لا يعلمونهم', 8): (60, 18, 0),
        ('والذين آمنوا', 10): (103, 4, 0),
        ('تلك آيات الكتاب', 13): (1, 3, 1),
        ('القرآن العظيم', 15): (87, 6, 1),
        ('في كتاب', 20): (52, 5, 0),
        ('علمه', 20): (114, 16, 0),
        ('يذكر آلهتكم', 21): (36, 11, 0),
        ('يعقلون', 24): (61, 75, 0),
        ('وعند الذين آمنوا', 40): (35, 14, 0),
        ('لولا فصلت آياته', 41): (44, 7, 0),
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
        ('مذءوما مذعورا', 7): (18, 4),
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
    for (quote, surah), (ayah, wpos) in expected.items():
        r = _row(muktafa, quote, surah)
        assert r['ayah'] == ayah, quote
        assert r['wpos'] == wpos, quote
        assert r['conf'] == 0, quote


def test_bracket_grade_parser_misses_extracted(muktafa):
    """Same class as 63:9 {عن ذكر الله} [كاف] — GRADE_RE now sees [تام]/[كاف]/[حسن]."""
    r = _row(muktafa, 'ونقدس لك', 2)
    assert r['ayah'] == 30 and r['wpos'] == 21 and r['conf'] == 1 and r['grade'] == 'كاف'
    r = _row(muktafa, 'عذاب أليم', 2)
    assert r['ayah'] == 104 and r['wpos'] == 11 and r['conf'] == 1 and r['grade'] == 'كاف'
    r = _row(muktafa, 'ما يوم الفصل', 77)
    assert r['ayah'] == 14 and r['wpos'] == 4 and r['conf'] == 1 and r['grade'] == 'تام'


def test_leftover_unmatched_are_the_two_non_unique_quotes(muktafa):
    unmatched = [r for r in muktafa if r['ayah'] is None]
    quotes = {(r['surah'], r['quote']) for r in unmatched}
    assert quotes == {
        (9, 'فليتوكل المتوكلون'),
        (22, 'عليهم آياتنا'),
    }
