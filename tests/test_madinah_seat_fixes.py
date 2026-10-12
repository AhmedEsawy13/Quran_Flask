"""Seats repaired by pipeline/fix_madinah_seat_rows.py stay on the QPC 1441 word."""
import sqlite3

from pipeline.fix_madinah_seat_rows import DB, LOCAL_COLS


def _marks(surah, ayah, token):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM waqf WHERE السورة=? AND الآية=? AND token_index=?',
                       (surah, ayah, token)).fetchone()
    conn.close()
    return dict(row)


def test_repeated_word_marks_sit_on_the_right_occurrence():
    for surah, ayah, wrong, right, mark in ((3, 7, 16, 41, 'ق'), (3, 66, 7, 14, 'ج')):
        assert _marks(surah, ayah, right)['المدينة الجديد'] == mark
        wrong_row = _marks(surah, ayah, wrong)
        assert not any(wrong_row[col] for col in LOCAL_COLS)


def test_new_madinah_keeps_the_maliyah_sakt():
    assert _marks(69, 28, 4)['المدينة الجديد'] == 'س'
