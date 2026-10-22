"""pipeline/cv_waqf/snap.py: a box on a vowel next to a stop sign moves onto the sign."""
from dataclasses import dataclass

import numpy as np
import pytest

pytest.importorskip('cv2')     # the cv_waqf pipeline needs OpenCV

from pipeline.cv_waqf.candidates import Candidate
from pipeline.cv_waqf.snap import snap_hits


@dataclass
class _Hit:
    candidate: Candidate
    line_number: int = 1
    layout_word: object = None
    cluster_index: int = 0


@dataclass
class _Page:
    gray: np.ndarray
    binary: np.ndarray


class _Clf:
    """Reads 'ج' for any window that holds ink of the sign, like the real model."""
    classes = ['none', 'ج']

    def __init__(self, sign_box):
        self.sign_box = sign_box

    def predict_many_probs(self, crops):
        out = []
        for crop in crops:
            hit = bool((crop < 128).sum() > 40)   # a window containing the big sign
            p = np.array([0.0, 1.0] if hit else [1.0, 0.0], dtype=np.float32)
            out.append(('ج' if hit else 'none', float(p.max()), p))
        return out


def _page(blobs):
    gray = np.full((120, 160), 255, np.uint8)
    for x, y, w, h in blobs:
        gray[y:y + h, x:x + w] = 0
    return _Page(gray=gray, binary=(gray < 128).astype(np.uint8) * 255)


def _hit_at(cx, cy):
    return _Hit(candidate=Candidate(x=cx - 12, y=cy - 12, w=24, h=24, area=60))


def test_box_on_vowel_below_moves_up_onto_the_sign():
    sign, dot, vowel = (70, 30, 13, 14), (75, 36, 3, 3), (71, 50, 12, 6)
    page = _page([sign, vowel, dot])
    [(hit, label, conf)] = snap_hits([(_hit_at(77, 53), 'ج', 0.99)], page, _Clf(sign))
    assert (label, conf) == ('ج', 0.99)
    assert hit.candidate.box == (70, 30, 83, 44)        # the sign, dot included, not the vowel


def test_thin_slash_above_the_sign_is_not_taken_for_it():
    sign, slash = (70, 40, 13, 14), (74, 22, 7, 2)
    page = _page([sign, slash])
    [(hit, _l, _c)] = snap_hits([(_hit_at(76, 47), 'ج', 0.99)], page, _Clf(sign))
    assert hit.candidate.box == (70, 40, 83, 54)


def test_owner_is_kept_and_same_word_duplicates_merge():
    sign, vowel = (70, 30, 13, 14), (71, 50, 12, 6)
    page = _page([sign, vowel])
    word = type('W', (), {'word_id': 7})()
    a = _hit_at(77, 53); a.layout_word = word
    b = _hit_at(76, 37); b.layout_word = word
    out = snap_hits([(a, 'ج', 0.9), (b, 'ج', 0.95)], page, _Clf(sign))
    assert len(out) == 1 and out[0][2] == 0.95 and out[0][0].layout_word is word
