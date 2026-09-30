"""Multi-print training pieces: consensus labels, detector-window labelling,
augmentation, fixed hold-out, seat ROI and the reproducible page splits."""
from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip('cv2')

from pipeline.cv_waqf import candidates, geometry, sample_crops, splits  # noqa: E402
from pipeline.cv_waqf.candidate_crops import (  # noqa: E402
    NEGATIVE_RADIUS,
    OWNER_RADIUS,
    POSITIVE_RADIUS,
    label_windows,
)


def _word(word_id, x0, y0=100, x1=None, y1=170):
    return SimpleNamespace(
        word_id=word_id, x0=x0, y0=y0, x1=x1 if x1 is not None else x0 + 80,
        y1=y1, is_content_word=True,
    )


def _hit(cx, cy, area=200):
    cand = candidates.Candidate(
        x=int(cx) - 12, y=int(cy) - 12, w=24, h=24, area=area,
    )
    return SimpleNamespace(candidate=cand)


# ------------------------------------------------------------ consensus

def test_consensus_needs_every_edition_to_agree(monkeypatch):
    tables = {
        'A': {(1, 1, 10): 'ج', (1, 1, 11): 'ص', (1, 1, 12): 'ق'},
        'B': {(1, 1, 10): 'ج', (1, 1, 11): 'ق'},   # disagrees on 11, silent on 12
        'C': {(1, 1, 10): 'ج', (1, 1, 11): 'ص', (1, 1, 12): 'ق'},
    }
    monkeypatch.setattr(
        sample_crops, 'edition_marks_for_ayahs',
        lambda edition, keys, script_db: tables[edition],
    )
    agreed, marked = sample_crops.consensus_marks(('A', 'B', 'C'), [(1, 1)], 'x')
    assert agreed == {(1, 1, 10): 'ج'}
    # Disputed words are "marked by someone", so never a negative either.
    assert marked == {(1, 1, 10), (1, 1, 11), (1, 1, 12)}


def test_single_edition_consensus_is_that_editions_column(monkeypatch):
    monkeypatch.setattr(
        sample_crops, 'edition_marks_for_ayahs',
        lambda edition, keys, script_db: {(1, 1, 5): 'م'},
    )
    agreed, marked = sample_crops.consensus_marks(('A',), [(1, 1)], 'x')
    assert agreed == {(1, 1, 5): 'م'} and marked == set(agreed)


# ------------------------------------------------------ window labelling

def _label(hits, words, positives=None, disputed=None, **kw):
    return list(label_windows(
        hits, words, positives or {}, disputed or set(),
        rng=random.Random(0),
        background_keep=kw.get('background_keep', 1.0),
        empty_keep=kw.get('empty_keep', 1.0),
    ))


def test_the_largest_component_at_an_agreed_seat_is_the_positive():
    word = _word(7, x0=300)
    sx, sy = geometry.mark_seat_centre(word.x0, word.y0, word.y1)
    big, small = _hit(sx, sy, area=300), _hit(sx + 3, sy + 3, area=40)
    out = _label([big, small], [word], positives={7: 'ص'})
    labels = {id(hit): label for hit, label, _ in out}
    assert labels[id(big)] == 'ص'
    assert id(small) not in labels  # ambiguous neighbour: neither class


def test_windows_away_from_the_seat_are_hard_negatives():
    word = _word(7, x0=300)
    sx, sy = geometry.mark_seat_centre(word.x0, word.y0, word.y1)
    h = word.y1 - word.y0
    far = _hit(sx + (NEGATIVE_RADIUS + 0.05) * h, sy)
    mid = _hit(sx + (POSITIVE_RADIUS + 0.05) * h, sy)
    out = _label([far, mid], [word], positives={7: 'ج'})
    labels = {id(hit): label for hit, label, _ in out}
    assert labels[id(far)] == 'none'
    assert id(mid) not in labels  # the ambiguous ring is skipped


def test_empty_and_disputed_words_and_background():
    empty, disputed = _word(1, x0=300), _word(2, x0=500)
    e_seat = geometry.mark_seat_centre(empty.x0, empty.y0, empty.y1)
    d_seat = geometry.mark_seat_centre(disputed.x0, disputed.y0, disputed.y1)
    hits = [_hit(*e_seat), _hit(*d_seat), _hit(900, 900)]
    out = _label(hits, [empty, disputed], disputed={2})
    labelled = {id(hit): (label, word) for hit, label, word in out}
    assert labelled[id(hits[0])] == ('none', empty)
    assert id(hits[1]) not in labelled            # disputed: never labelled
    assert labelled[id(hits[2])] == ('none', None)  # background


def test_sampling_rates_are_respected():
    word = _word(1, x0=300)
    seat = geometry.mark_seat_centre(word.x0, word.y0, word.y1)
    hits = [_hit(*seat) for _ in range(50)]
    assert _label(hits, [word], empty_keep=0.0) == []
    assert len(_label(hits, [word], empty_keep=1.0)) == 50
    assert OWNER_RADIUS > NEGATIVE_RADIUS > POSITIVE_RADIUS


# ---------------------------------------------------------- seat ROI

def test_seat_roi_contains_the_seat_centre_and_scales_with_line_height():
    x0, y0, x1, y1 = geometry.mark_seat_roi_from_box(300, 100, 380, 170)
    cx, cy = geometry.mark_seat_centre(300, 100, 170)
    assert x0 < cx < x1 and y0 < cy < y1
    tall = geometry.mark_seat_roi_from_box(300, 100, 380, 240)
    assert (tall[3] - tall[1]) == pytest.approx(2 * (y1 - y0), rel=0.05)


def test_strip_roi_convention_switches_and_rejects_unknown():
    from pipeline.cv_waqf.strip import above_word_strip_roi_from_box

    legacy = above_word_strip_roi_from_box(300, 100, 380, 170)
    measured = above_word_strip_roi_from_box(
        300, 100, 380, 170, convention='measured',
    )
    assert legacy != measured
    assert measured == geometry.mark_seat_roi_from_box(300, 100, 380, 170)
    with pytest.raises(ValueError, match='convention'):
        above_word_strip_roi_from_box(300, 100, 380, 170, convention='nope')


# ------------------------------------------------- trainer additions

def test_augmentation_shape_range_and_variety():
    pytest.importorskip('onnx')  # the trainer exports ONNX
    from pipeline.cv_waqf.config import CROP_SIZE
    from pipeline.cv_waqf.train_classifier import augment_crops

    ink = np.zeros((4, CROP_SIZE * CROP_SIZE), np.float32)
    ink[:, 900:1000] = 1.0
    out = augment_crops(ink, 3, seed=1)
    assert out.shape == (12, CROP_SIZE * CROP_SIZE)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert not np.allclose(out[0], out[4])         # copies differ
    assert np.array_equal(out, augment_crops(ink, 3, seed=1))  # reproducible
    assert augment_crops(ink, 0).shape == (0, CROP_SIZE * CROP_SIZE)


def test_fixed_holdout_puts_exactly_those_pages_in_validation():
    pytest.importorskip('onnx')
    from pipeline.cv_waqf.train_classifier import split_by_page_group

    groups = np.asarray(['a:p1', 'a:p1', 'a:p2', 'b:p1', 'b:p2'], dtype=object)
    train, val = split_by_page_group(groups, holdout={'a:p2', 'b:p1'})
    assert sorted(val.tolist()) == [2, 3] and sorted(train.tolist()) == [0, 1, 4]
    with pytest.raises(RuntimeError, match='holdout'):
        split_by_page_group(groups, holdout={'zzz:p9'})


def test_page_groups_recognise_every_registered_print(tmp_path):
    from pathlib import Path

    pytest.importorskip('onnx')
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.train_classifier import _PAGE_RE, _page_group

    for spec in EDITIONS.values():
        root = tmp_path / spec.id
        path = Path('p012_w5_x.png')
        group = _page_group(path, root, _PAGE_RE.search(path.stem))
        assert group == f'{spec.id}:p0012'


# ----------------------------------------------------------- splits

def test_splits_are_disjoint_and_deterministic():
    train, holdout = splits.qatar_pages()
    assert (len(train), len(holdout)) == (100, 50)
    assert not set(train) & set(holdout)
    assert (train, holdout) == splits.qatar_pages()

    b_train, b_hold = splits.bahrain_holdout([9, 3, 5, 7, 11, 13, 15, 17])
    assert b_hold == [3, 11] and 3 not in b_train and len(b_train) == 6
    assert splits.group_ids('qatar', [7]) == ['qatar:p0007']
