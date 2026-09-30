"""Edition registry + measured page geometry for the CV waqf pipeline.

Synthetic pages have a known answer (rows, frame, word cuts), so these tests
pin the geometry without needing any scanned page or model on disk.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')

from pipeline.cv_waqf import config, geometry  # noqa: E402

PITCH = 72
TOP = 200
ROWS = 15
BASELINE_SHIFT = geometry.LINE_CENTER_BIAS


def _synthetic_page(word_widths_per_line, *, gap=22, frame=True):
    """White page, red frame, gold inner rule, black word bars on baselines."""
    page = np.full((1500, 1024, 3), 255, np.uint8)
    if frame:
        cv2.rectangle(page, (110, 150), (914, 1350), (40, 30, 170), 46)   # red
        cv2.rectangle(page, (190, 190), (834, 1310), (60, 140, 190), 3)   # gold
    truth = []
    for k, widths in enumerate(word_widths_per_line):
        baseline = TOP + (k + 0.5 + BASELINE_SHIFT) * PITCH
        x = 826  # right edge; RTL, so word 0 is rightmost
        spans = []
        for width in widths:
            x1, x0 = x, x - width
            cv2.rectangle(
                page, (x0, int(baseline) - 14), (x1, int(baseline) + 14),
                (0, 0, 0), -1,
            )
            spans.append((x0, x1))
            x = x0 - gap
        truth.append(spans)
    return page, truth


def test_every_edition_gets_model_paths_from_the_registry():
    for key, spec in config.EDITIONS.items():
        assert config.EDITION_MODEL_PATHS[key] == (
            config.ROOT / 'models' / f'waqf_glyph_{spec.id}.onnx'
        )
        assert config.EDITION_STRIP_MODEL_PATHS[key] == (
            config.ROOT / 'models' / f'waqf_strip_{spec.id}.onnx'
        )
    assert len({spec.id for spec in config.EDITIONS.values()}) == len(
        config.EDITIONS
    )


def test_qatar_is_a_registered_measured_edition():
    qatar = config.EDITIONS['قطر']
    assert qatar.mushaf_version == 'قطر'
    assert qatar.measured_geometry is True
    assert qatar.model_fallback is None  # uses the multi-print model


def test_model_resolution_order_own_fallback_multiprint_legacy(
    monkeypatch, tmp_path,
):
    models = tmp_path / 'models'
    models.mkdir()
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    monkeypatch.setattr(
        config, 'SHARED_MULTIPRINT_MODEL_PATH',
        models / 'waqf_glyph_multiprint.onnx',
    )
    assert config.resolve_edition_model('قطر') == (None, None)

    (models / 'waqf_glyph_multiprint.onnx').write_bytes(b'x')
    path, source = config.resolve_edition_model('قطر')
    assert (path.name, source) == ('waqf_glyph_multiprint.onnx', 'multiprint')

    # An explicit fallback edition beats the multi-print model.
    monkeypatch.setitem(
        config.EDITIONS, 'قطر',
        dataclasses.replace(config.EDITIONS['قطر'], model_fallback='البحرين'),
    )
    (models / 'waqf_glyph_bahrain.onnx').write_bytes(b'x')
    path, source = config.resolve_edition_model('قطر')
    assert (path.name, source) == ('waqf_glyph_bahrain.onnx', 'transfer:البحرين')

    # Its own model beats everything.
    (models / 'waqf_glyph_qatar.onnx').write_bytes(b'x')
    path, source = config.resolve_edition_model('قطر')
    assert (path.name, source) == ('waqf_glyph_qatar.onnx', 'own')


def test_strip_classifier_no_longer_defaults_to_bahrain():
    from pipeline.cv_waqf.strip import StripClassifier

    with pytest.raises(ValueError, match='model_path'):
        StripClassifier()


def test_cache_edition_derives_working_width_from_larger_scan(tmp_path):
    from pipeline.cv_waqf.pages import ensure_page_image

    big = np.full((2800, 2000, 3), 200, np.uint8)
    cv2.imwrite(str(tmp_path / 'p007_w2000.jpg'), big)
    spec = dataclasses.replace(
        config.EDITIONS['قطر'], page_cache_dir=str(tmp_path),
    )
    out = ensure_page_image(spec, 7)
    assert out.name == 'p007_w1024.jpg'
    img = cv2.imread(str(out))
    assert img.shape[:2] == (1434, 1024)

    with pytest.raises(FileNotFoundError):
        ensure_page_image(spec, 8)  # nothing cached → never fabricated


def test_ink_mask_keeps_text_and_drops_coloured_frame():
    page, _ = _synthetic_page([[120, 90, 150]] * ROWS)
    mask = geometry.text_ink_mask(page)
    assert mask[:, :180].sum() == 0          # red frame + gold rule gone
    assert mask[:, 200:830].sum() > 0        # words kept


def test_line_grid_recovers_top_and_pitch_from_a_shifted_nominal():
    page, _ = _synthetic_page([[120, 90, 150, 80]] * ROWS)
    mask = geometry.text_ink_mask(page)
    grid = geometry.fit_line_grid(
        mask, list(range(ROWS)),
        nominal_top=TOP + 24, nominal_pitch=PITCH * 1.04,
    )
    assert grid.fitted and grid.support == 1.0
    assert grid.top == pytest.approx(TOP, abs=3)
    assert grid.pitch == pytest.approx(PITCH, abs=0.6)


def test_line_grid_ignores_header_rows_and_missing_lines():
    # Row 0 is a banner (no words) and row 6 is empty: only 13 word lines.
    words = [[120, 90, 150, 80]] * ROWS
    words[0] = []
    words[6] = []
    page, _ = _synthetic_page(words)
    mask = geometry.text_ink_mask(page)
    slots = [k for k in range(ROWS) if k not in (0, 6)]
    grid = geometry.fit_line_grid(
        mask, slots, nominal_top=TOP - 18, nominal_pitch=PITCH,
    )
    assert grid.fitted
    assert grid.top == pytest.approx(TOP, abs=3)


def test_line_grid_falls_back_to_nominal_without_evidence():
    blank = np.zeros((1500, 1024), np.uint8)
    grid = geometry.fit_line_grid(
        blank, list(range(ROWS)), nominal_top=210.0, nominal_pitch=71.0,
    )
    assert grid.fitted is False
    assert (grid.top, grid.pitch) == (210.0, 71.0)


def test_text_x_bounds_stops_at_the_frames_inner_edge():
    page, _ = _synthetic_page([[120, 90, 150]] * ROWS)
    lo, hi = geometry.text_x_bounds(page, 200, 1280)
    assert 185 <= lo <= 200     # just inside the gold rule at x=190
    assert 826 <= hi <= 836     # just inside the rule at x=834
    plain = np.full((1500, 1024, 3), 255, np.uint8)
    assert geometry.text_x_bounds(plain, 200, 1280) == (0, 1024)


def test_segment_line_words_cuts_at_the_measured_gaps():
    widths = [140, 60, 200, 90, 120, 70]
    page, truth = _synthetic_page([widths] * ROWS)
    mask = geometry.text_ink_mask(page)
    baseline = TOP + (0 + 0.5 + BASELINE_SHIFT) * PITCH
    spans = geometry.segment_line_words(
        mask, baseline=baseline, pitch=PITCH,
        weights=[w / 10 for w in widths], x_range=(0, 1024),
    )
    assert len(spans) == len(widths)
    for (x0, x1), (tx0, tx1) in zip(spans, truth[0]):
        # A cut sits in the middle of a gap, so each side is within half a gap.
        assert abs(x0 - tx0) <= 13 and abs(x1 - tx1) <= 13
    # RTL and contiguous: each word starts where the next one ends.
    assert all(a[0] == b[1] for a, b in zip(spans, spans[1:]))


def test_segment_line_words_fills_missing_gaps_with_expected_cuts():
    # Words touch (no measurable gaps): cuts must fall back to the weights.
    widths = [100, 100, 100, 100]
    page, _ = _synthetic_page([widths] * ROWS, gap=0)
    mask = geometry.text_ink_mask(page)
    baseline = TOP + (0.5 + BASELINE_SHIFT) * PITCH
    spans = geometry.segment_line_words(
        mask, baseline=baseline, pitch=PITCH,
        weights=[10.0] * 4, x_range=(0, 1024),
    )
    assert len(spans) == 4
    widths_found = [x1 - x0 for x0, x1 in spans]
    assert all(80 <= width <= 120 for width in widths_found)


def test_segment_line_words_returns_none_for_an_empty_line():
    mask = np.zeros((1500, 1024), np.uint8)
    assert geometry.segment_line_words(
        mask, baseline=500, pitch=PITCH, weights=[1.0, 1.0],
        x_range=(0, 1024),
    ) is None
