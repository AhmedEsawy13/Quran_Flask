"""المكتفى rulings qualified by an ordinal («{X} الأول كاف»، «الثاني تام»،
«في الموضعين») — see pipeline/audit_muktafa_ordinals.py."""
import os
import sqlite3

import pytest

from core.config import CLASSICAL_WAQF_DATABASE


@pytest.fixture(scope='module')
def db():
    if not os.path.exists(CLASSICAL_WAQF_DATABASE):
        pytest.skip('classical_waqf.db not built')
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    yield conn
    conn.close()


@pytest.mark.parametrize('surah,ayah,wpos,grade', [
    (2, 81, 12, 'تام'), (2, 82, 9, 'تام'),     # «هم فيها خالدون» الأول والثاني تام
    (7, 99, 2, 'كاف'),                         # «مكر الله» الأول كاف
    (13, 24, 6, 'تام'),                        # «عقبى الدار» الثاني تام
    (24, 33, 9, 'تام'),                        # «من فضله» الثاني تام
    (34, 54, 9, 'كاف'),                        # ومثله «من قبل» الثاني
    (89, 17, 0, 'تام'), (89, 21, 0, 'تام'),    # «كلا» في الموضعين
    (94, 5, 3, 'كاف'), (94, 6, 3, 'تام'),      # العسر يسرا الأول كاف، الثاني تام
    (84, 5, 2, 'تام'),                         # «وحقت» الثانية
])
def test_ordinal_ruling_on_named_occurrence(db, surah, ayah, wpos, grade):
    grades = {g for (g,) in db.execute(
        "SELECT grade FROM classical WHERE source='muktafa' AND conf=1 "
        "AND surah=? AND ayah=? AND wpos=?", (surah, ayah, wpos))}
    assert grade in grades


def test_ordinal_audit_has_nothing_left_to_apply():
    from pipeline import audit_muktafa_ordinals as audit
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    try:
        found, _ = audit.resolve(conn)
        for r in found:
            grades = {g for (g,) in conn.execute(
                "SELECT grade FROM classical WHERE source='muktafa' AND surah=? AND ayah=? "
                "AND wpos=?", (r['surah'], r['ayah'], r['wpos']))}
            assert r['grade'] in grades, r
    finally:
        conn.close()
