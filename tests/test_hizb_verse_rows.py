"""Marks in verses opening with ۞ sit on the intended word
(pipeline/fix_hizb_verse_rows.py)."""
import sqlite3

from pipeline.fix_hizb_verse_rows import DB


def _row(surah, ayah, token):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM waqf WHERE السورة=? AND الآية=? AND token_index=?',
                       (surah, ayah, token)).fetchone()
    conn.close()
    return dict(row) if row else {}


def test_old_madinah_2_158_marks_on_allah_and_bihima():
    assert _row(2, 158, 7)['المدينة القديم'] == 'ص'
    assert _row(2, 158, 18)['المدينة القديم'] == 'ج'
    assert not _row(2, 158, 6).get('المدينة القديم')


def test_indopak_marks_follow_the_word_not_the_one_before():
    assert _row(2, 26, 32)['الهندي'] == 'ۙ'      # كَثِيرٗا, not بِهِۦ
    assert _row(2, 26, 40)['الهندي'] == 'ۙ'      # ٱلۡفَٰسِقِينَ, not إِلَّا
    assert _row(76, 19, 5)['الهندي'] == 'ۚ'      # مُّخَلَّدُونَ


def test_hizb_verse_rows_follow_the_token_convention():
    conn = sqlite3.connect(DB)
    hizb_same = conn.execute(
        "SELECT count(*) FROM waqf w WHERE token_index = word_index AND EXISTS ("
        " SELECT 1 FROM waqf x WHERE x.السورة = w.السورة AND x.الآية = w.الآية"
        " AND x.token_index = x.word_index + 1)").fetchone()[0]
    conn.close()
    assert hizb_same == 0
