"""Every quoted row ends on the word it is seated on (pipeline/review/seat_check.py).

A planted-error test (2026-10-11) showed the reviewer model and the catalog gate
both miss a row moved a word or two off its stop; this check caught all three
planted ones and six real ones (4:78, 6:158, 9:37, 20:69 المكتفى, 2:14 منار).
Book slips that cannot match are pinned in pipeline/review/hand_pinned_seats.json.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'review'))
import seat_check  # noqa: E402


def test_quotes_end_on_their_seated_word():
    bad = seat_check.check()
    assert not bad, '\n'.join(map(str, bad[:20]))


def test_seat_check_flags_a_moved_row():
    # «وأصحاب اليمين ما أصحاب اليمين»: the quote fits the second «اليمين» only
    words = ['وَأَصۡحَٰبُ', 'ٱلۡيَمِينِ', 'مَآ', 'أَصۡحَٰبُ', 'ٱلۡيَمِينِ']
    q = 'ما أصحاب اليمين'.split()
    assert seat_check.fit(q, words, 4) > seat_check.fit(q, words, 1)
    assert seat_check.fit(['بالكافرين'], ['بِٱلۡكَٰفِرِينَ'], 0)[0] == 2      # article written with waṣla
    assert seat_check.fit(['الصالحين'], ['ٱلصَّٰلِحِينَ'], 0)[0] == 2        # dagger alif
    assert seat_check.fit(['وإياي'], ['وَإِيَّٰيَۖ'], 0)[0] > 0                 # all long vowels
    assert seat_check.fit(['ولكن'], ['أَكۡثَرَهُمۡ'], 0)[0] == 0


def test_unique_two_word_endings_sit_on_their_spot():
    """A quote whose last two words occur once in the surah must sit there (2026-10-14:
    المكتفى «سوأة أخيه» was on 5:30's «قتل أخيه», not 5:31). Listed: the book's own
    spelling differs from the mushaf, or the seat was read against the book's order."""
    import re, sqlite3, unicodedata, collections
    from pathlib import Path
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / 'pipeline')]
    import build_classical_waqf as rx
    from core.verse_words import verse_word_texts

    def sk(s):
        s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
        s = re.sub('[ۖ-ۭـٰ]', '', s); s = re.sub('[ٱأإآءئؤ]', '', s); s = s.replace('ة', 'ه').replace('ى', 'ي')
        return re.sub('[اوي]', '', re.sub(r'[^ء-ي]', '', s))
    ok = {('anbari', 16, 28, 18), ('nahhas', 16, 32, 11), ('nahhas', 29, 8, 20),   # «تعلمون» for «تعملون»
          ('nahhas', 30, 4, 8),                                                     # «من بعده» for «من بعد»
          ('nahhas', 39, 10, 5),                                                    # «اتقوا» dropped
          ('anbari', 51, 25, 4),                                                    # «(قالوا سلاما)» = «فقالوا سلاما»
          ('muktafa', 53, 28, 4), ('muktafa', 70, 21, 3)}                           # read against the book (test_classical_illa)
    con = sqlite3.connect(root / 'data' / 'classical_waqf.db')
    bad = []
    for s in range(1, 115):
        seq = [(sk(x), a, w) for a in range(1, rx.surah_ayah_count(s) + 1)
               for w, x in enumerate(verse_word_texts(f'{s}:{a}')[1])]
        pos = collections.defaultdict(list)
        for i in range(1, len(seq)):
            pos[(seq[i - 1][0], seq[i][0])].append((seq[i][1], seq[i][2]))
        for src, a, w, q, raw in con.execute(
                "SELECT source, ayah, wpos, quote, grade_raw FROM classical WHERE surah=? AND conf=1 "
                "AND ayah IS NOT NULL", (s,)):
            if raw in ('رؤوس الآي', 'رأس الآية', 'آخر السورة') or (src, s, a, w) in ok:
                continue
            ws = [sk(x) for x in re.split(r'\s+', re.sub(r'\.\.\.|…|\(\d+\)|[{}()«»]', ' ', (q or '').split('.')[-1])) if sk(x)]
            hits = pos.get(tuple(ws[-2:]), []) if len(ws) >= 2 else []
            if len(hits) == 1 and (a, w) != hits[0]:
                bad.append((src, s, a, w, hits[0], q))
    assert not bad, bad
