"""Tests for the above-word strip detector (OpenCV 5 DNN + ONNX).

Run with:

    PYTHONPATH=. .venv-cv/bin/python -m pytest \\
        tests/test_cv_waqf.py tests/test_cv_waqf_strip.py --noconftest -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')

ROOT = Path(__file__).resolve().parents[1]


def _layout_word(**kwargs):
    from pipeline.cv_waqf.layout_geo import LayoutWord

    values = dict(
        word_id=1,
        word_key='2:2:1',
        word_id_space='qpc',
        surah=2,
        ayah=2,
        text='آمنوا',
        line_number=1,
        word_on_line=1,
        words_on_line=4,
        x0=100,
        y0=40,
        x1=180,
        y1=100,
    )
    values.update(kwargs)
    return LayoutWord(**values)


def test_above_word_strip_roi_is_upper_rtl_end_band():
    from pipeline.cv_waqf.strip import above_word_strip_roi

    word = _layout_word()
    x0, y0, x1, y1 = above_word_strip_roi(word)
    line_h = word.y1 - word.y0
    # Stays in the upper portion — not the letter-body / lower half.
    assert y1 <= word.y0 + int(0.25 * line_h)
    assert y0 < word.y0
    # RTL end is the left edge; the strip must not span the whole word.
    assert x0 < word.x0
    assert x1 < word.x1
    assert x1 - x0 < (word.x1 - word.x0)


def test_crop_above_word_strip_letterboxes_fixed_size():
    from pipeline.cv_waqf.config import STRIP_HEIGHT, STRIP_WIDTH
    from pipeline.cv_waqf.strip import (
        above_word_strip_roi,
        crop_above_word_strip,
    )

    gray = np.full((160, 240), 255, dtype=np.uint8)
    word = _layout_word()
    x0, y0, x1, y1 = above_word_strip_roi(word)
    # Paint ink only in the above-word band.
    gray[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 0
    strip = crop_above_word_strip(gray, word)
    assert strip.shape == (STRIP_HEIGHT, STRIP_WIDTH)
    assert strip.dtype == np.uint8
    assert int(strip.min()) < 40

    body_only = np.full((160, 240), 255, dtype=np.uint8)
    body_only[word.y0 + line_mid(word):word.y1, word.x0:word.x1] = 0
    empty_strip = crop_above_word_strip(body_only, word)
    assert int(empty_strip.mean()) > 230


def line_mid(word) -> int:
    return (word.y1 - word.y0) // 2


def test_strip_onnx_input_output_contract(tmp_path):
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.config import STRIP_HEIGHT, STRIP_WIDTH
    from pipeline.cv_waqf.strip import StripClassifier, preprocess_strip
    from pipeline.cv_waqf.train_strip import export_random_strip_onnx

    out = tmp_path / 'waqf_strip_fixture.onnx'
    export_random_strip_onnx(out, seed=1)
    assert out.is_file()
    sidecar = json_sidecar(out)
    assert sidecar['pipeline'] == 'strip'
    assert sidecar['detector'] == 'strip'
    assert sidecar['strip_height'] == STRIP_HEIGHT
    assert sidecar['strip_width'] == STRIP_WIDTH
    assert sidecar['classes'] == list(CLASSES)
    assert sidecar['input'] == 'input'
    assert sidecar['output'] == 'logits'
    assert sidecar['input_layout'] == 'NCHW'

    kwargs = {}
    if hasattr(cv2.dnn, 'ENGINE_AUTO'):
        kwargs['engine'] = cv2.dnn.ENGINE_AUTO
    try:
        net = cv2.dnn.readNet(str(out), **kwargs)
    except TypeError:
        net = cv2.dnn.readNet(str(out))
    blob = np.zeros((2, 1, STRIP_HEIGHT, STRIP_WIDTH), dtype=np.float32)
    net.setInput(blob)
    logits = np.asarray(net.forward(), dtype=np.float32)
    assert logits.reshape(2, -1).shape == (2, len(CLASSES))

    clf = StripClassifier(model_path=out)
    assert clf.ready
    assert clf.pipeline == 'strip'
    blank = np.full((STRIP_HEIGHT, STRIP_WIDTH), 255, dtype=np.uint8)
    label, conf, probs = clf.predict_probs(blank)
    assert label in CLASSES
    assert 0.0 <= conf <= 1.0
    assert len(probs) == len(CLASSES)
    batched = clf.predict_many_probs([blank, blank, blank])
    assert len(batched) == 3
    x = preprocess_strip(blank)
    assert x.shape == (1, 1, STRIP_HEIGHT, STRIP_WIDTH)
    assert x.dtype == np.float32


def json_sidecar(path: Path) -> dict:
    import json
    return json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))


def test_is_strip_model_reads_sidecar_not_filename():
    from pipeline.cv_waqf.strip import is_strip_model

    glyph = ROOT / 'models' / 'waqf_glyph_bahrain.onnx'
    if glyph.with_suffix('.json').is_file():
        assert is_strip_model(glyph) is False
    assert is_strip_model(ROOT / 'models' / 'waqf_strip_bahrain.onnx') is True


def test_strip_model_path_falls_back_when_file_missing():
    from pipeline.cv_waqf.config import EDITION_STRIP_MODEL_PATHS
    from pipeline.cv_waqf.strip import strip_model_path_for_edition

    auto = EDITION_STRIP_MODEL_PATHS['البحرين']
    if auto.is_file():
        pytest.skip('local trained strip ONNX present')
    assert strip_model_path_for_edition('البحرين') is None
    assert strip_model_path_for_edition('الشمرلي') is None
    mlp = ROOT / 'models' / 'waqf_glyph_bahrain.onnx'
    assert strip_model_path_for_edition('البحرين', model_path=mlp) is None


def test_detect_page_falls_back_to_mlp_when_strip_missing(monkeypatch):
    from pipeline.cv_waqf import run_page

    class FakePrepared:
        gray = np.zeros((10, 10), dtype=np.uint8)

    class FakeClassifier:
        ready = True
        model_path = Path('/tmp/waqf_glyph_bahrain.onnx')
        pipeline = 'two-stage'

        def predict_many_probs(self, crops):
            return []

    monkeypatch.setattr(run_page, 'ensure_page_image', lambda *_: Path('/tmp/page.jpg'))
    monkeypatch.setattr(
        run_page, 'load_bgr', lambda *_: np.zeros((10, 10, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(run_page, 'preprocess_page', lambda *_: FakePrepared())
    monkeypatch.setattr(run_page, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_above_word_candidates', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_line_component_candidates', lambda *_: [])
    monkeypatch.setattr(run_page, 'GlyphClassifier', lambda **_: FakeClassifier())
    monkeypatch.setattr(
        run_page, 'strip_model_path_for_edition', lambda *_a, **_k: None,
    )

    result = run_page.detect_page('البحرين', 198)
    assert result['detector'] == 'mlp'
    assert result['strategy'] == 'hybrid-line-components'
    assert result['proposal_mode'] == 'hybrid'


def test_detect_page_uses_strip_for_bahrain_when_file_exists(monkeypatch, tmp_path):
    from pipeline.cv_waqf import CLASSES, run_page
    from pipeline.cv_waqf.train_strip import export_random_strip_onnx

    strip_path = tmp_path / 'waqf_strip_bahrain.onnx'
    export_random_strip_onnx(strip_path, seed=2)

    word = _layout_word()
    gray = np.full((160, 240), 240, dtype=np.uint8)

    class FakePrepared:
        pass

    FakePrepared.gray = gray

    class FakeStrip:
        ready = True
        model_path = strip_path
        pipeline = 'strip'
        classes = list(CLASSES)
        height = 32
        width = 64

        def predict_many_probs(self, crops):
            assert crops
            assert crops[0].shape == (32, 64)
            zeros = np.zeros(len(CLASSES), dtype=np.float32)
            zeros[CLASSES.index('ج')] = 1.0
            return [('ج', 0.96, zeros) for _ in crops]

    constructed = {'mlp': 0, 'strip': 0, 'hybrid': 0}

    def boom_mlp(**_kwargs):
        constructed['mlp'] += 1
        raise AssertionError('MLP path must not run when the strip ONNX is present')

    monkeypatch.setattr(run_page, 'ensure_page_image', lambda *_: Path('/tmp/page.jpg'))
    monkeypatch.setattr(
        run_page, 'load_bgr', lambda *_: np.zeros((160, 240, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(run_page, 'preprocess_page', lambda *_: FakePrepared())
    monkeypatch.setattr(run_page, 'estimate_layout_words', lambda *_: [word])
    monkeypatch.setattr(
        run_page, 'find_line_component_candidates',
        lambda *_: constructed.__setitem__('hybrid', constructed['hybrid'] + 1) or [],
    )
    monkeypatch.setattr(run_page, 'GlyphClassifier', boom_mlp)
    monkeypatch.setattr(
        run_page, 'strip_model_path_for_edition',
        lambda edition, **_k: strip_path if edition == 'البحرين' else None,
    )
    monkeypatch.setattr(
        run_page, 'StripClassifier',
        lambda **_k: constructed.__setitem__('strip', constructed['strip'] + 1) or FakeStrip(),
    )

    bahrain = run_page.detect_page(
        'البحرين', 198, min_conf=0.55, azhar_prior=False,
    )
    assert bahrain['strategy'] == 'above-word-strip'
    assert bahrain['detector'] == 'strip'
    assert bahrain['proposal_mode'] == 'strip'
    assert bahrain['model_pipeline'] == 'strip'
    assert bahrain['marks'][0]['symbol'] == 'ج'
    assert bahrain['marks'][0]['word_key'] == word.word_key
    assert constructed == {'mlp': 0, 'strip': 1, 'hybrid': 0}

    class FakeMlp:
        ready = True
        model_path = Path('/tmp/waqf_glyph.onnx')
        pipeline = 'single-stage'

        def predict_many_probs(self, crops):
            return []

    monkeypatch.setattr(run_page, 'GlyphClassifier', lambda **_: FakeMlp())
    monkeypatch.setattr(run_page, 'find_above_word_candidates', lambda *_: [])
    shamarly = run_page.detect_page('الشمرلي', 5)
    assert shamarly['detector'] == 'mlp'
    assert shamarly['strategy'] == 'above-word-per-line'
    assert constructed['strip'] == 1


def test_explicit_mlp_model_disables_bahrain_strip(tmp_path):
    from pipeline.cv_waqf.strip import strip_model_path_for_edition
    from pipeline.cv_waqf.train_strip import export_random_strip_onnx

    strip = tmp_path / 'waqf_strip_bahrain.onnx'
    export_random_strip_onnx(strip, seed=3)
    mlp = ROOT / 'models' / 'waqf_glyph_bahrain.onnx'
    assert strip_model_path_for_edition(
        'البحرين', model_path=mlp, strip_model_path=None,
    ) is None
    assert strip_model_path_for_edition(
        'البحرين', model_path=strip,
    ) == strip


def test_train_strip_command_is_registered():
    import io
    from contextlib import redirect_stdout

    from pipeline.cv_waqf.__main__ import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(['--help']) == 0
    text = buf.getvalue()
    assert 'train-strip' in text


def test_train_strip_requires_labels(tmp_path):
    from pipeline.cv_waqf.train_strip import main

    empty = tmp_path / 'bahrain'
    empty.mkdir()
    with pytest.raises(SystemExit, match='labels.jsonl'):
        main(['--crops', str(empty), '--edition', 'البحرين'])


def test_repo_does_not_ship_untrained_strip_onnx():
    import json

    path = ROOT / 'models' / 'waqf_strip_bahrain.onnx'
    if not path.is_file():
        return
    meta_path = path.with_suffix('.json')
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    assert not meta.get('untrained')
    assert meta.get('pipeline') == 'strip'


def test_readme_documents_train_strip():
    text = (ROOT / 'pipeline' / 'cv_waqf' / 'README.md').read_text(encoding='utf-8')
    assert 'train-strip' in text
    assert 'waqf_strip_bahrain.onnx' in text
    assert 'requirements-cv-train.txt' in text
    assert 'Does not replace models/waqf_glyph_bahrain.onnx' in text
    assert 'defaults to hybrid proposals' in text
    assert 'writes only confidence >= 0.85' in text
