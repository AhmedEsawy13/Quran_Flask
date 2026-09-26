"""القطع والائتناف (النحاس): the parser (pipeline/nahhas_parse.py) and rows
pinned after reading the book (pipeline/audit_nahhas.py)."""
import os
import sqlite3

import pytest

from pipeline import nahhas_parse as P

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'classical_waqf.db')


def parsed(text):
    return [(r.grade, r.by, r.quote) for r in P.parse(text)]


def test_chain_and_grade_before():
    got = parsed('{وما تغيض الأرحام وما تزداد} قطع كاف وكذا {كل شيء عنده بمقدار} والتمام {الكبير المتعال}')
    assert got == [('كاف', None, 'وما تغيض الأرحام وما تزداد'), ('كاف', None, 'كل شيء عنده بمقدار'),
                   ('تام', None, 'الكبير المتعال')]


def test_speaker_covers_only_the_quote_it_introduces():
    got = parsed('قال أحمد بن موسى {فلا يحزنك قولهم} تم الكلام {إنا نعلم ما يسرون وما يعلنون} قطع تام')
    assert got == [('تام', 'أحمد بن موسى', 'فلا يحزنك قولهم'), ('تام', None, 'إنا نعلم ما يسرون وما يعلنون')]


def test_bare_qala_continues_the_named_speaker():
    got = parsed('قال أبو حاتم {متى نصر الله} وقف كاف، قال والتمام {ألا إن نصر الله قريب}')
    assert [b for _, b, _ in got] == ['أبو حاتم', 'أبو حاتم']


def test_second_opinion_and_nafi():
    got = parsed('وعن نافع {لم يؤت سعة من المال} تمام، وأبو حاتم يذهب إلى أنه كاف')
    assert ('تام', 'نافع', 'لم يؤت سعة من المال') in got and ('كاف', 'أبو حاتم', 'لم يؤت سعة من المال') in got


def test_al_hasan_the_scholar_is_not_the_grade():
    got = parsed('والتمام عند عيسى بن عمر {واتخذ سبيله في البحر} وقال الحسن {واتخذ سبيله في البحر} ثم قال')
    assert got == [('تام', 'عيسى بن عمر', 'واتخذ سبيله في البحر')]


def test_negations_and_miscopied_thumma_are_not_rulings():
    assert parsed('{يا ليتي كنت معهم} ليس بقطع كاف') == []
    # «تم القطع على رؤوس الآيات …» is a miscopied «ثم»
    assert parsed('{بئس مثل القوم} تم القطع على رؤوس الآيات تمام إلى {وذروا البيع} فإنه قطع كاف')[0][0] == 'كاف'


def test_quoting_allah_or_a_mufassir_is_not_a_scholar():
    got = parsed('ثم قال الله جل وعز {ذلكم الله ربكم} قطع كاف. قال مجاهد: {الذين من قبلهم} قطع حسن')
    assert [b for _, b, _ in got] == [None, None]


@pytest.fixture(scope='module')
def db():
    if not os.path.exists(DB):
        pytest.skip('classical_waqf.db not built')
    con = sqlite3.connect(DB)
    yield con
    con.close()


def served(db, s, a, w):
    return {(g, rf) for g, rf in db.execute("SELECT grade, reported_from FROM classical WHERE source='nahhas' "
                                            "AND conf=1 AND surah=? AND ayah=? AND wpos=?", (s, a, w))}


@pytest.mark.parametrize('s,a,w,expect', [
    (2, 2, 1, ('تام', None)),              # «التمام {ذلك الكتاب}»
    (1, 7, 8, ('تام', None)),              # الفاتحة, from «باب ذكر السور»
    (113, 1, 3, ('كاف', 'غيره')),          # «ذوات قل»: «وكذا {قل أعوذ برب الفلق}»
    (42, 39, 5, ('تام', 'الأخفش')),        # «والتمام عندهما {هم ينتصرون}»
    (2, 19, 18, ('تام', 'الأخفش')),        # curated: «فالتمام فيه عند قوله …»
    (6, 139, 16, ('حسن', None)),           # curated: repeated text
])
def test_pinned_rows(db, s, a, w, expect):
    assert expect in served(db, s, a, w)


def test_refrain_seats_move_forward(db):
    # «فبأي آلاء ربكما تكذبان» after each verse of الرحمن: no word carries two own grades
    clash = db.execute("SELECT count(*) FROM (SELECT 1 FROM classical WHERE source='nahhas' AND conf=1 "
                       "AND reported_from IS NULL GROUP BY surah, ayah, wpos HAVING count(DISTINCT grade) > 1)"
                       ).fetchone()[0]
    assert clash == 0


def test_audit_is_stable():
    from pipeline import audit_nahhas
    con = sqlite3.connect(DB)
    try:
        assert audit_nahhas.plan(con) == []
    finally:
        con.close()
