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


# ------------------------------------------------------- seat prior

def _prior_db(tmp_path):
    import sqlite3

    db = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE waqf ("السورة" INTEGER, "الآية" INTEGER, token_index '
        'INTEGER, word_index INTEGER, "الأزهر" TEXT, "المدينة الجديد" TEXT, '
        '"المدينة القديم" TEXT, "قطر" TEXT)'
    )
    conn.executemany(
        'INSERT INTO waqf VALUES (?,?,?,?,?,?,?,?)',
        [
            (2, 5, 5, 5, 'ج', 'ج', None, 'ج'),   # everyone
            (2, 6, 3, 3, None, 'ص', None, 'ص'),   # Madinah only (Azhar empty)
            (2, 7, 4, 4, None, None, 'ق', None),   # old Madinah only
            (2, 8, 9, 9, None, None, None, 'ص'),   # the print's own column only
        ],
    )
    conn.commit()
    conn.close()
    return db


def test_seat_prior_takes_its_editions_from_the_caller(tmp_path):
    from pipeline.cv_waqf import azhar_prior

    db = _prior_db(tmp_path)
    azhar_prior.reset_azhar_occupancy_cache()
    azhar_only = azhar_prior.load_occupied_seats(str(db))
    madinah = azhar_prior.load_occupied_seats(
        str(db), ('الأزهر', 'المدينة الجديد', 'المدينة القديم'),
    )
    assert azhar_only == {(2, 5, 5)}
    assert madinah == {(2, 5, 5), (2, 6, 3), (2, 7, 4)}
    # The original Azhar-named entry point is unchanged.
    assert azhar_prior.load_azhar_occupied_seats(str(db)) == azhar_only
    # A seat only the print itself marks stays outside every prior.
    assert (2, 8, 9) not in madinah


def test_partition_uses_the_configured_editions(tmp_path):
    from pipeline.cv_waqf import azhar_prior

    db = _prior_db(tmp_path)
    azhar_prior.reset_azhar_occupancy_cache()
    marks = [
        {'word_key': '2:5:5', 'surah': 2, 'ayah': 5, 'symbol': 'ج'},
        {'word_key': '2:6:3', 'surah': 2, 'ayah': 6, 'symbol': 'ص'},
        {'word_key': '2:8:9', 'surah': 2, 'ayah': 8, 'symbol': 'ص'},
    ]
    kept, rejected = azhar_prior.partition_marks_by_azhar_occupancy(
        marks, db_path=db,
    )
    assert [m['word_key'] for m in kept] == ['2:5:5']
    kept, rejected = azhar_prior.partition_marks_by_azhar_occupancy(
        marks, db_path=db, editions=('الأزهر', 'المدينة الجديد'),
    )
    assert [m['word_key'] for m in kept] == ['2:5:5', '2:6:3']
    assert [m['word_key'] for m in rejected] == ['2:8:9']


def test_an_unknown_prior_edition_is_a_configuration_error(tmp_path):
    from pipeline.cv_waqf import azhar_prior

    db = _prior_db(tmp_path)
    azhar_prior.reset_azhar_occupancy_cache()
    with pytest.raises(ValueError, match='unknown edition'):
        azhar_prior.load_occupied_seats(str(db), ('لا يوجد',))


def test_a_print_cannot_use_its_own_column_as_its_prior():
    import dataclasses

    from pipeline.cv_waqf import config

    qatar = config.EDITIONS['قطر']
    with pytest.raises(ValueError, match='own'):
        dataclasses.replace(qatar, seat_prior_editions=('الأزهر', 'قطر'))
    # Inert when the prior is off (Azhar's own default names itself).
    assert config.EDITIONS['الأزهر'].azhar_seat_prior is False
    for spec in config.EDITIONS.values():
        if spec.azhar_seat_prior:
            assert spec.mushaf_version not in spec.seat_prior_editions


def test_bahrain_and_qatar_use_the_azhar_plus_madinah_prior():
    from pipeline.cv_waqf import config

    for key in ('البحرين', 'قطر'):
        spec = config.EDITIONS[key]
        assert spec.azhar_seat_prior is True
        assert spec.seat_prior_editions == config.SEAT_PRIOR_AZHAR_MADINAH
        assert spec.mushaf_version not in spec.seat_prior_editions
    # Untouched prints keep the original Azhar-only default and stay off.
    assert config.EDITIONS['الشمرلي'].seat_prior_editions == ('الأزهر',)
    assert config.EDITIONS['الشمرلي'].azhar_seat_prior is False


def test_detect_reports_the_prior_editions_it_used(monkeypatch):
    from pipeline.cv_waqf import azhar_prior, run_page
    from tests.test_cv_waqf import _attached_mark, _stub_detect_pipeline

    seen = {}

    def fake_load(db_path='', editions=()):
        seen['editions'] = tuple(editions)
        return {(2, 5, 5)}

    monkeypatch.setattr(azhar_prior, 'load_occupied_seats', fake_load)
    _stub_detect_pipeline(monkeypatch, [
        _attached_mark('2:5:5', symbol='ص', confidence=0.99, word_id=1),
    ])
    result = run_page.detect_page('قطر', 2)
    assert seen['editions'] == ('الأزهر', 'المدينة الجديد', 'المدينة القديم')
    assert result['seat_prior_editions'] == list(seen['editions'])
    off = run_page.detect_page('قطر', 2, azhar_prior=False)
    assert off['seat_prior_editions'] == []
