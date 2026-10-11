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
