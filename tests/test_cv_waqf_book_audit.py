"""Decision rules of the whole-book audit (book_audit / book_review)."""
import pytest

pytest.importorskip('cv2')     # the cv_waqf pipeline needs OpenCV

from pipeline.cv_waqf.book_audit import one_sign_one_word, pick_confirming
from pipeline.cv_waqf.book_review import classify_items, ref_lean


def _missed(key, db, page=1):
    return {'kind': 'cv_missed', 'word_key': key, 'text': 'A', 'db': db, 'cv': None,
            'page': page, 'crop': f'{key}_miss.jpg', 'others': {}}


def _seen(key, cv, raw=None, kind='not_in_db', db=None, page=1):
    item = {'kind': kind, 'word_key': key, 'text': 'B', 'db': db, 'cv': cv, 'conf': 0.99,
            'page': page, 'crop': f'{key}.jpg', 'others': {}}
    if raw:
        item['raw'] = {'raw_key': raw, 'raw_text': 'x'}
    return item


def test_neighbour_settled_for_the_db_without_the_madinah_pull():
    # 6:151: DB ص on «رَبُّكُمۡ» (6), scan puts it on «عَلَيۡكُمۡ» (7), unbiased pass says 6
    out = classify_items([_missed('6:151:6', 'ص'), _seen('6:151:7', 'ص', raw='6:151:6')])
    assert [(i['kind'], i['word_key'], i['from_key']) for i in out] == [('resolved', '6:151:7', '6:151:6')]


def test_neighbour_kept_by_the_unbiased_pass_is_a_shift():
    out = classify_items([_missed('2:5:3', 'ج'), _seen('2:5:4', 'ج', raw='2:5:4')])
    assert [i['kind'] for i in out] == ['shift']


def test_different_sign_on_the_neighbour_is_not_paired():
    out = classify_items([_missed('2:5:3', 'ج'), _seen('2:5:4', 'ص', raw='2:5:4')])
    assert sorted(i['kind'] for i in out) == ['cv_missed', 'not_in_db']


def test_marks_on_other_pages_are_not_paired():
    out = classify_items([_missed('2:5:3', 'ج', page=1), _seen('2:5:4', 'ج', raw='2:5:4', page=2)])
    assert sorted(i['kind'] for i in out) == ['cv_missed', 'not_in_db']


def test_image_confirmed_db_mark_moves_to_confirmed():
    item = _seen('2:144:20', 'ص', kind='symbol_differs', db='ق')
    item['verify'] = {'found': True, 'p': 0.999, 'crop': 'c.jpg'}
    [out] = classify_items([item])
    assert (out['kind'], out['crop'], out['from_crop']) == ('confirmed', 'c.jpg', '2:144:20.jpg')


def test_reference_lean():
    madinah_with_scan = {'cv': 'ج', 'db': 'ص', 'others': {'المدينة الجديد': 'ج', 'المدينة القديم': 'ج'}}
    madinah_with_db = {'cv': 'ج', 'db': 'ص', 'others': {'المدينة الجديد': 'ص'}}
    azhar_on_qili = {'cv': 'ق', 'db': 'ج', 'others': {'الأزهر': 'ج'}}   # Azhar prints no قلى: ignored
    assert ref_lean(madinah_with_scan) == 2
    assert ref_lean(madinah_with_db) == -1
    assert ref_lean(azhar_on_qili) == 0


def test_one_printed_sign_confirms_one_word():
    # 43:80: the صلى over «بَلَىٰ» claimed by both words; the nearer seat keeps it
    found = {'43:80:7': {'box': [1, 1, 9, 9], 'seat_d': 40.0}, '43:80:8': {'box': [1, 1, 9, 9], 'seat_d': 6.0}}
    assert list(one_sign_one_word(found)) == ['43:80:8']


def test_confirming_piece_is_the_highest_with_a_signs_ink():
    vowel = (10, 50, 12, 8, 70)     # x, y, w, h, area — reads as the sign too (the window holds it)
    sign = (11, 30, 13, 14, 95)
    slash = (12, 20, 7, 2, 14)      # thin fatha above: too little ink
    best = pick_confirming([(vowel, 0.99), (sign, 0.98), (slash, 0.97)], ink_share=0.6)
    assert best[0] == sign
    assert pick_confirming([(vowel, 0.5)], ink_share=0.6) is None
