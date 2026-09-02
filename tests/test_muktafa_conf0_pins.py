"""المكتفى low-confidence pins: proven moves off the book, no invented أحكام.

The regex harvest swallowed سورة المنافقون because OpenITI titles it
`# [سورة] المنافقون.` (not `### | سورة …`). Three other conf=0 rows were
pinned to a prefix-cousin of the quoted stop (أحد/أحدا/وإنه) while the
full phrase is unique later in the same surah. Period quotes and genuinely
repeated/discursive rows stay conf=0.
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
