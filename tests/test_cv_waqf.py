"""Smoke tests for the offline OpenCV 5 waqf pipeline.

These tests intentionally avoid importing the Flask app (``conftest.py``).
Run with:

    PYTHONPATH=. .venv-cv/bin/python -m pytest tests/test_cv_waqf.py --noconftest -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')

ROOT = Path(__file__).resolve().parents[1]


def test_opencv_major_at_least_5():
    major = int(cv2.__version__.split('.', 1)[0])
    assert major >= 5


def test_preprocess_and_candidates_on_blank():
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.candidates import find_candidates
    from pipeline.cv_waqf.preprocess import preprocess_page

    spec = EDITIONS['الشمرلي']
    bgr = np.full((800, 600, 3), 240, dtype=np.uint8)
    for y, x in ((200, 100), (220, 400), (400, 250)):
        cv2.rectangle(bgr, (x, y), (x + 10, y + 10), (20, 20, 20), -1)
    prepared = preprocess_page(bgr, spec)
    assert prepared.text_band.size > 0
    cands = find_candidates(prepared, min_area=10, max_area=500)
    assert isinstance(cands, list)


def test_onnx_model_loads_when_present():
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.cv_waqf.config import MODEL_PATH

    if not MODEL_PATH.is_file():
        pytest.skip('models/waqf_glyph.onnx not built yet')
    clf = GlyphClassifier()
    assert clf.ready
    crop = np.full((48, 48), 255, dtype=np.uint8)
    label, conf = clf.predict_crop(crop)
    assert label in clf.classes
    assert 0.0 <= conf <= 1.0


def test_export_onnx_roundtrip(tmp_path):
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.config import CROP_SIZE
    from pipeline.cv_waqf.train_classifier import export_onnx

    d = CROP_SIZE * CROP_SIZE
    hidden, k = 16, len(CLASSES)
    rng = np.random.default_rng(0)
    w1 = rng.normal(0, 0.05, size=(d, hidden)).astype(np.float32)
    b1 = np.zeros((hidden,), dtype=np.float32)
    w2 = rng.normal(0, 0.05, size=(hidden, k)).astype(np.float32)
    b2 = np.zeros((k,), dtype=np.float32)
    out = tmp_path / 'toy.onnx'
    export_onnx(w1, b1, w2, b2, out)
    assert out.is_file()
    kwargs = {}
    if hasattr(cv2.dnn, 'ENGINE_AUTO'):
        kwargs['engine'] = cv2.dnn.ENGINE_AUTO
    try:
        net = cv2.dnn.readNet(str(out), **kwargs)
    except TypeError:
        net = cv2.dnn.readNet(str(out))
    blob = np.zeros((1, 1, CROP_SIZE, CROP_SIZE), dtype=np.float32)
    net.setInput(blob)
    logits = np.asarray(net.forward()).reshape(-1)
    assert logits.shape == (k,)


def test_shamarly_page2_detect_smoke():
    from pipeline.cv_waqf.config import MODEL_PATH, PAGES_ROOT
    from pipeline.cv_waqf.run_page import detect_page

    if not MODEL_PATH.is_file():
        pytest.skip('model missing')
    page_img = PAGES_ROOT / 'shamarly' / 'p002_w1024.jpg'
    if not page_img.is_file():
        pytest.skip('cached shamarly page 2 missing')
    result = detect_page('الشمرلي', 2, min_conf=0.70)
    assert result['page'] == 2
    assert 'marks' in result


def test_bootstrap_plan_schema():
    from pipeline.cv_waqf.bootstrap_edition import SCHEMA_VERSION, bootstrap_pages
    from pipeline.cv_waqf.config import EDITIONS, MODEL_PATH
    from pipeline.cv_waqf.pages import page_image_path

    if not MODEL_PATH.is_file():
        pytest.skip('model missing')
    spec = EDITIONS['البحرين']
    if not page_image_path(spec, 2).is_file():
        pytest.skip('bahrain page cache missing')
    plan = bootstrap_pages('البحرين', [2], min_conf=0.85)
    assert plan['schema_version'] == SCHEMA_VERSION
    assert plan['edition'] == 'البحرين'
    assert 'plan_digest' in plan
    assert isinstance(plan['changes'], list)
