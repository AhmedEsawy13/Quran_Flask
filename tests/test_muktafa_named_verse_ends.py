"""المكتفى: a verse end the book names — «ورأس الآية أتم»، «وآخر الآية أكفى منه»، «والتمام
رأس الآية»، «عند رأس الجزء» — must carry that grade, not only a general «رؤوس الآي» row of
another grade (round 25 and the follow-up check, 2026-10-14: 6:3, 2:141, 12:92, 2:181, 4:1,
3:75, 10:92). «وقيل: …» views stay in notes by design."""
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'pipeline' / 'review'), str(ROOT / 'pipeline'), str(ROOT)]
import coverage_check  # noqa: E402
from core.verse_words import verse_word_texts  # noqa: E402

DB = ROOT / 'data' / 'classical_waqf.db'
GRADE = {'أتم': 'تام', 'تام': 'تام', 'تمام': 'تام', 'تامة': 'تام', 'التمام': 'تام', 'والتمام': 'تام',
         'أكفى': 'كاف', 'كاف': 'كاف', 'كافية': 'كاف', 'الكافي': 'كاف', 'والكافي': 'كاف',
         'أحسن': 'حسن', 'حسن': 'حسن'}
_STMT = re.compile(r'(?<![ء-ي])(?:و|ف)?(?:رأس\s+الآية|آخر\s+الآية)\s+(أتم|أكفى|أحسن|تام|تمام|كاف)'
                   r'|(?<![ء-ي])(والتمام|التمام|والكافي|الكافي)(?:\s+عندي)?\s+(?:آخر\s+الآية|رأس\s+الآية)(?![ء-ي])')


def test_named_verse_ends_carry_their_grade():
    con = sqlite3.connect(DB)
    bad = []
    for s, text in sorted(coverage_check._sections('muktafa').items()):
        text = re.sub(r'\s+', ' ', text)
        for m in _STMT.finditer(text):
            if re.search(r'وقيل:?\s*$', text[max(0, m.start() - 8):m.start()]):
                continue
            prev = re.findall(r'\{([^{}]+)\}', text[:m.start()])
            row = prev and con.execute("SELECT ayah FROM classical WHERE source='muktafa' AND surah=? AND quote=? "
                                       "AND ayah IS NOT NULL", (s, prev[-1])).fetchone()
            if not row:
                continue                      # unplaced statement (a range or a cross-reference)
            a = row[0]
            w = len(verse_word_texts(f'{s}:{a}')[1]) - 1
            want = GRADE[m.group(1) or m.group(2)]
            got = {g for (g,) in con.execute("SELECT grade FROM classical WHERE source='muktafa' AND conf=1 "
                                            "AND surah=? AND ayah=? AND wpos=?", (s, a, w))}
            if want not in got:
                bad.append((s, a, want, sorted(got), m.group(0)))
    assert not bad, bad
