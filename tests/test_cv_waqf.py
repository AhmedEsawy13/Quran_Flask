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


def test_page_cache_atomic_outputs_do_not_share_temp_name(tmp_path):
    from pipeline.cv_waqf.pages import _atomic_output

    target = tmp_path / 'page.jpg'
    with _atomic_output(target) as first:
        first.write_bytes(b'first')
        with _atomic_output(target) as second:
            assert first != second
            second.write_bytes(b'second')
        assert target.read_bytes() == b'second'
    assert target.read_bytes() == b'first'
    assert not list(tmp_path.glob('*.tmp'))


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
    from pipeline.cv_waqf.classify import GlyphClassifier
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

    classifier = GlyphClassifier(model_path=out)
    predictions = classifier.predict_many_probs([
        np.full((48, 48), 255, dtype=np.uint8) for _ in range(3)
    ])
    assert len(predictions) == 3
    assert all(label in CLASSES for label, _confidence, _probs in predictions)


def test_two_stage_classifier_gate_rejects_and_accepts_marks():
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.classify import GlyphClassifier

    class FakeNet:
        def __init__(self, rows):
            self.rows = np.asarray(rows, dtype=np.float32)
            self.batch = 0

        def setInput(self, blob):
            self.batch = len(blob)

        def forward(self):
            return self.rows[:self.batch]

    classifier = GlyphClassifier(model_path=Path('/missing/model.onnx'))
    classifier.pipeline = 'two-stage'
    classifier.classes = list(CLASSES)
    classifier.symbol_classes = [label for label in CLASSES if label != 'none']
    classifier.gate_classes = ['none', 'mark']
    # Symbol net strongly prefers qaf for both samples. The gate must still
    # reject the first crop and accept the second.
    q_index = classifier.symbol_classes.index('ق')
    symbol_logits = np.full((2, len(classifier.symbol_classes)), -4.0)
    symbol_logits[:, q_index] = 4.0
    classifier.net = FakeNet(symbol_logits)
    classifier.gate_net = FakeNet([[5.0, -5.0], [-5.0, 5.0]])

    predictions = classifier.predict_many_probs([
        np.full((48, 48), 255, dtype=np.uint8),
        np.full((48, 48), 255, dtype=np.uint8),
    ])

    assert predictions[0][0] == 'none'
    assert predictions[1][0] == 'ق'
    assert all(len(probs) == len(CLASSES) for _, _, probs in predictions)


def test_two_stage_can_gate_an_existing_classifier_with_none_output():
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.classify import GlyphClassifier

    class FakeNet:
        def __init__(self, rows):
            self.rows = np.asarray(rows, dtype=np.float32)

        def setInput(self, blob):
            self.batch = len(blob)

        def forward(self):
            return self.rows[:self.batch]

    classifier = GlyphClassifier(model_path=Path('/missing/model.onnx'))
    classifier.pipeline = 'two-stage'
    classifier.classes = list(CLASSES)
    classifier.symbol_classes = list(CLASSES)
    classifier.gate_classes = ['none', 'mark']
    classifier.gate_mode = 'veto'
    classifier.gate_min_conf = 0.5
    logits = np.full((1, len(CLASSES)), -3.0)
    logits[0, CLASSES.index('ج')] = 4.0
    logits[0, CLASSES.index('none')] = 2.0
    classifier.net = FakeNet(logits)
    classifier.gate_net = FakeNet([[-4.0, 4.0]])

    label, _confidence, probabilities = classifier.predict_probs(
        np.full((48, 48), 255, dtype=np.uint8)
    )

    assert label == 'ج'
    assert float(probabilities.sum()) == pytest.approx(1.0, abs=1e-6)


def test_two_stage_veto_never_rescues_existing_none_prediction():
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.classify import GlyphClassifier

    class FakeNet:
        def __init__(self, rows):
            self.rows = np.asarray(rows, dtype=np.float32)

        def setInput(self, blob):
            self.batch = len(blob)

        def forward(self):
            return self.rows[:self.batch]

    classifier = GlyphClassifier(model_path=Path('/missing/model.onnx'))
    classifier.pipeline = 'two-stage'
    classifier.classes = list(CLASSES)
    classifier.symbol_classes = list(CLASSES)
    classifier.gate_classes = ['none', 'mark']
    classifier.gate_mode = 'veto'
    classifier.gate_min_conf = 0.5
    logits = np.full((1, len(CLASSES)), -3.0)
    logits[0, CLASSES.index('none')] = 4.0
    classifier.net = FakeNet(logits)
    classifier.gate_net = FakeNet([[-4.0, 4.0]])

    label, _confidence, _probabilities = classifier.predict_probs(
        np.full((48, 48), 255, dtype=np.uint8)
    )

    assert label == 'none'


def test_two_stage_export_roundtrip(tmp_path):
    from pipeline.cv_waqf import CLASSES
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.cv_waqf.config import CROP_SIZE
    from pipeline.cv_waqf.train_classifier import export_mlp_onnx

    rng = np.random.default_rng(3)
    d, hidden = CROP_SIZE * CROP_SIZE, 8
    mark_classes = [label for label in CLASSES if label != 'none']

    def weights(outputs):
        return (
            rng.normal(0, 0.02, size=(d, hidden)).astype(np.float32),
            np.zeros(hidden, dtype=np.float32),
            rng.normal(0, 0.02, size=(hidden, outputs)).astype(np.float32),
            np.zeros(outputs, dtype=np.float32),
        )

    symbol_path = tmp_path / 'two_stage.onnx'
    gate_path = tmp_path / 'two_stage_gate.onnx'
    export_mlp_onnx(
        *weights(2), gate_path,
        classes=['none', 'mark'],
        metadata={'pipeline': 'binary-gate'},
    )
    export_mlp_onnx(
        *weights(len(mark_classes)), symbol_path,
        classes=mark_classes,
        metadata={
            'pipeline': 'two-stage',
            'gate_model': gate_path.name,
            'gate_classes': ['none', 'mark'],
            'full_classes': list(CLASSES),
        },
    )

    classifier = GlyphClassifier(model_path=symbol_path)
    assert classifier.ready
    assert classifier.pipeline == 'two-stage'
    label, confidence, probabilities = classifier.predict_probs(
        np.full((48, 48), 255, dtype=np.uint8)
    )
    assert label in CLASSES
    assert 0.0 <= confidence <= 1.0
    assert len(probabilities) == len(CLASSES)


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


def test_bahrain_has_isolated_optional_model_path():
    from pipeline.cv_waqf.config import EDITION_MODEL_PATHS, MODEL_PATH, ROOT

    bahrain = EDITION_MODEL_PATHS['البحرين']
    assert bahrain == ROOT / 'models' / 'waqf_glyph_bahrain.onnx'
    assert bahrain != MODEL_PATH
    assert bahrain.with_name('waqf_glyph_bahrain_gate.onnx') == (
        ROOT / 'models' / 'waqf_glyph_bahrain_gate.onnx'
    )


def test_only_bahrain_defaults_to_hybrid_proposals():
    from pipeline.cv_waqf.config import EDITIONS, resolve_proposal_mode

    assert EDITIONS['البحرين'].default_proposal_mode == 'hybrid'
    assert resolve_proposal_mode('البحرين') == 'hybrid'
    others = {
        key: spec.default_proposal_mode
        for key, spec in EDITIONS.items()
        if key != 'البحرين'
    }
    assert others
    assert all(mode == 'narrow' for mode in others.values())
    assert resolve_proposal_mode('الشمرلي') == 'narrow'
    assert resolve_proposal_mode('المساحة') == 'narrow'
    assert resolve_proposal_mode('الأزهر') == 'narrow'
    assert resolve_proposal_mode('البحرين', 'narrow') == 'narrow'
    assert resolve_proposal_mode('الشمرلي', 'hybrid') == 'hybrid'
    with pytest.raises(ValueError, match='proposal_mode'):
        resolve_proposal_mode('البحرين', 'wide')


def test_detect_and_evaluate_inherit_edition_proposal_default():
    import inspect

    from pipeline.cv_waqf.evaluate_hand import evaluate_labels
    from pipeline.cv_waqf.run_page import detect_page

    assert inspect.signature(detect_page).parameters['proposal_mode'].default is None
    assert inspect.signature(evaluate_labels).parameters['proposal_mode'].default is None
    assert inspect.signature(detect_page).parameters['azhar_prior'].default is None
    assert inspect.signature(evaluate_labels).parameters['azhar_prior'].default is None
    assert inspect.signature(detect_page).parameters['min_conf'].default == 0.55


def test_detect_page_uses_hybrid_line_components_for_bahrain_only(monkeypatch):
    from pipeline.cv_waqf import run_page

    class FakePrepared:
        gray = np.zeros((10, 10), dtype=np.uint8)

    class FakeClassifier:
        ready = True
        model_path = Path('/tmp/waqf_glyph_bahrain.onnx')
        pipeline = 'two-stage'

        def predict_many_probs(self, crops):
            return []

    hybrid_calls = []
    monkeypatch.setattr(run_page, 'ensure_page_image', lambda *_: Path('/tmp/page.jpg'))
    monkeypatch.setattr(
        run_page, 'load_bgr', lambda *_: np.zeros((10, 10, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(run_page, 'preprocess_page', lambda *_: FakePrepared())
    monkeypatch.setattr(run_page, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_above_word_candidates', lambda *_: [])
    monkeypatch.setattr(
        run_page,
        'find_line_component_candidates',
        lambda *_: hybrid_calls.append(True) or [],
    )
    monkeypatch.setattr(run_page, 'GlyphClassifier', lambda **_: FakeClassifier())

    bahrain = run_page.detect_page('البحرين', 198)
    assert hybrid_calls == [True]
    assert bahrain['proposal_mode'] == 'hybrid'
    assert bahrain['strategy'] == 'hybrid-line-components'

    hybrid_calls.clear()
    shamarly = run_page.detect_page('الشمرلي', 5)
    assert hybrid_calls == []
    assert shamarly['proposal_mode'] == 'narrow'
    assert shamarly['strategy'] == 'above-word-per-line'

    hybrid_calls.clear()
    forced = run_page.detect_page('البحرين', 198, proposal_mode='narrow')
    assert hybrid_calls == []
    assert forced['proposal_mode'] == 'narrow'


def test_ui_bootstrap_and_audit_do_not_pin_proposal_mode():
    ui = (ROOT / 'pipeline' / 'cv_waqf' / 'ui_payload.py').read_text(encoding='utf-8')
    bootstrap = (ROOT / 'pipeline' / 'cv_waqf' / 'bootstrap_edition.py').read_text(
        encoding='utf-8',
    )
    audit = (ROOT / 'pipeline' / 'cv_waqf' / 'audit_edition.py').read_text(
        encoding='utf-8',
    )
    flask_ui = (ROOT / 'modules' / 'cv_waqf_ui.py').read_text(encoding='utf-8')
    assert 'proposal_mode=' not in ui
    assert 'proposal_mode=' not in bootstrap
    assert 'proposal_mode=' not in audit
    assert 'proposal_mode=' not in flask_ui
    assert 'resolve_proposal_mode(edition)' in flask_ui
    assert 'resolve_auto_set_min_conf(edition)' in flask_ui


def test_bahrain_readme_documents_hybrid_default():
    text = (ROOT / 'pipeline' / 'cv_waqf' / 'README.md').read_text(encoding='utf-8')
    assert 'Experimental high-recall' not in text
    assert '--proposal-mode' in text
    assert 'defaults to hybrid proposals' in text
    assert 'writes only confidence >= 0.85' in text
    assert '--no-azhar-prior' in text
    assert '31 → 6' in text


def test_only_bahrain_auto_set_is_stricter_than_review():
    from pipeline.cv_waqf.config import (
        EDITIONS,
        classify_mark_trust,
        resolve_auto_set_min_conf,
        split_marks_by_trust,
    )

    bahrain = EDITIONS['البحرين']
    assert bahrain.review_min_conf == 0.55
    assert bahrain.auto_set_min_conf == 0.85
    assert resolve_auto_set_min_conf('البحرين') == 0.85
    others = {
        key: spec.auto_set_min_conf
        for key, spec in EDITIONS.items()
        if key != 'البحرين'
    }
    assert others
    assert all(value == 0.70 for value in others.values())
    assert resolve_auto_set_min_conf('الشمرلي') == 0.70
    assert resolve_auto_set_min_conf('البحرين', 0.90) == 0.90
    assert classify_mark_trust(0.85, 0.85) == 'auto-set'
    assert classify_mark_trust(0.849, 0.85) == 'review'
    trusted, review = split_marks_by_trust(
        [
            {'symbol': 'ج', 'confidence': 0.92},
            {'symbol': 'ص', 'confidence': 0.60},
        ],
        0.85,
    )
    assert [row['confidence'] for row in trusted] == [0.92]
    assert [row['confidence'] for row in review] == [0.60]


def test_bahrain_bootstrap_writes_only_auto_set_marks(monkeypatch):
    from pipeline.cv_waqf import bootstrap_edition

    captured = []
    monkeypatch.setattr(
        bootstrap_edition,
        'detect_page',
        lambda edition, page, **kwargs: captured.append((edition, kwargs)) or {
            'marks': [
                {
                    'word_id': 1, 'word_key': '1:1:1', 'word_id_space': 'qpc',
                    'symbol': 'ج', 'confidence': 0.92, 'text': 'آمنوا',
                },
                {
                    'word_id': 2, 'word_key': '1:1:2', 'word_id_space': 'qpc',
                    'symbol': 'ص', 'confidence': 0.60, 'text': 'به',
                },
            ],
        },
    )
    monkeypatch.setattr(
        bootstrap_edition,
        'within_ayah_token_index',
        lambda _db, word_id: (1, 1, int(word_id) - 1, 'كلمة'),
    )

    plan = bootstrap_edition.bootstrap_pages('البحرين', [2])
    assert captured[0][1]['min_conf'] == 0.55
    assert plan['min_conf'] == 0.85
    assert plan['auto_set_min_conf'] == 0.85
    assert plan['review_min_conf'] == 0.55
    assert [row['confidence'] for row in plan['changes']] == [0.92]
    assert plan['changes'][0]['op'] == 'set'
    assert [row['confidence'] for row in plan['review_candidates']] == [0.60]
    assert plan['review_candidates'][0]['op'] == 'review'

    shamarly = bootstrap_edition.bootstrap_pages('الشمرلي', [2])
    assert shamarly['min_conf'] == 0.70
    assert captured[-1][1]['min_conf'] == 0.55

    overridden = bootstrap_edition.bootstrap_pages('البحرين', [2], min_conf=0.95)
    assert overridden['min_conf'] == 0.95
    assert overridden['changes'] == []
    assert [row['confidence'] for row in overridden['review_candidates']] == [
        0.92, 0.60,
    ]


def test_ui_payload_keeps_review_hits_out_of_auto_set(monkeypatch):
    from pipeline.cv_waqf import ui_payload

    monkeypatch.setattr(
        ui_payload,
        'detect_page',
        lambda *_args, **_kwargs: {
            'proposal_mode': 'hybrid',
            'candidates': 4,
            'classified': 2,
            'marks': [
                {
                    'word_id': 10, 'word_key': '2:2:1', 'surah': 2, 'ayah': 2,
                    'symbol': 'ج', 'confidence': 0.91, 'text': 'آمنوا',
                    'line': 1, 'box': [1, 2, 3, 4],
                },
                {
                    'word_id': 11, 'word_key': '2:2:2', 'surah': 2, 'ayah': 2,
                    'symbol': 'ص', 'confidence': 0.62, 'text': 'به',
                    'line': 1, 'box': [5, 6, 7, 8],
                },
            ],
        },
    )
    monkeypatch.setattr(ui_payload, 'ensure_page_image', lambda *_: Path('/tmp/p.jpg'))
    monkeypatch.setattr(ui_payload, 'load_bgr', lambda *_: None)

    class FakePrepared:
        pass

    monkeypatch.setattr(ui_payload, 'preprocess_page', lambda *_: FakePrepared())
    monkeypatch.setattr(ui_payload, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(ui_payload, 'edition_marks_for_ayahs', lambda *_: {})

    payload = ui_payload.build_ui_payload('البحرين', 2)
    assert payload['min_conf'] == 0.55
    assert payload['auto_set_min_conf'] == 0.85
    assert payload['review_min_conf'] == 0.55
    assert [m['confidence'] for m in payload['trusted_marks']] == [0.91]
    assert [m['confidence'] for m in payload['review_marks']] == [0.62]
    assert {m['trust'] for m in payload['cv_marks']} == {'auto-set', 'review'}
    assert payload['summary']['trusted'] == 1
    assert payload['summary']['review'] == 1
    assert payload['rejected_marks'] == []
    assert payload['summary']['rejected'] == 0

    shamarly = ui_payload.build_ui_payload('الشمرلي', 2)
    assert shamarly['auto_set_min_conf'] == 0.70
    assert [m['trust'] for m in shamarly['cv_marks']] == ['auto-set', 'review']


def test_cv_waqf_ui_grades_review_marks():
    js = (ROOT / 'static' / 'js' / 'cv_waqf.js').read_text(encoding='utf-8')
    html = (ROOT / 'templates' / 'cv_waqf.html').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'css' / 'cv_waqf.css').read_text(encoding='utf-8')
    assert 'review_marks' in js
    assert 'trusted_marks' in js
    assert 'rejected_marks' in js
    assert "trust === 'review'" in js
    assert 'cvw-show-review' in html
    assert 'cvw-show-rejected' in html
    assert '.tag.review' in css
    assert '.tag.rejected' in css


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
    assert isinstance(plan.get('review_candidates'), list)


def test_cv_word_ranges_follow_canonical_order_across_numeric_gaps():
    from core.config import QURAN_SCRIPT_DATABASE
    from pipeline.cv_waqf.layout_geo import _ids_between

    assert _ids_between(QURAN_SCRIPT_DATABASE, 6399, 6485) == [
        6399, 6400, 6401, 6481, 6482, 6483, 6484, 6485,
    ]


def test_training_validation_split_keeps_pages_isolated():
    from pipeline.cv_waqf.train_classifier import split_by_page_group

    groups = np.asarray([
        'shamarly:p0003', 'shamarly:p0003',
        'shamarly:p0004', 'shamarly:p0004',
        'mesaha:p0350', 'mesaha:p0350',
    ], dtype=object)
    train, validation = split_by_page_group(groups, val_fraction=0.34, seed=4)

    train_groups = {groups[index] for index in train}
    validation_groups = {groups[index] for index in validation}
    assert train_groups
    assert validation_groups
    assert train_groups.isdisjoint(validation_groups)


def test_same_edition_page_group_is_shared_across_crop_roots():
    import re

    from pipeline.cv_waqf.train_classifier import _PAGE_RE, _page_group

    positive = Path('/tmp/demo/train/bahrain/j/bahrain-p030-positive.png')
    negative = Path('/tmp/demo/train/hard/none/component_none_bahrain_p030_001.png')
    positive_match = _PAGE_RE.search(positive.stem)
    negative_match = _PAGE_RE.search(negative.stem)
    assert isinstance(positive_match, re.Match)
    assert isinstance(negative_match, re.Match)
    assert _page_group(positive, positive.parents[1], positive_match) == 'bahrain:p0030'
    assert _page_group(negative, negative.parents[1], negative_match) == 'bahrain:p0030'


def test_rtl_attachment_uses_trusted_seat_as_a_soft_prior():
    from pipeline.cv_waqf.attach import _nearest_word
    from pipeline.cv_waqf.candidates import Candidate
    from pipeline.cv_waqf.layout_geo import LayoutWord

    def word(word_id, x0, text):
        return LayoutWord(
            word_id=word_id,
            word_key=f'1:1:{word_id}',
            word_id_space='test',
            surah=1,
            ayah=1,
            text=text,
            line_number=1,
            word_on_line=word_id,
            words_on_line=2,
            x0=x0,
            y0=20,
            x1=x0 + 35,
            y1=80,
        )

    plain = word(1, 100, 'قول')
    trusted_seat = word(2, 140, 'عليمۚ')
    candidate = Candidate(x=92, y=35, w=16, h=16, area=100)

    assert _nearest_word(
        candidate, [plain, trusted_seat], 80, seat_prior=False,
    ) == plain
    assert _nearest_word(candidate, [plain, trusted_seat], 80) == trusted_seat


def test_rtl_attachment_keeps_trusted_seat_when_scores_are_nearly_tied():
    from pipeline.cv_waqf.attach import _nearest_word
    from pipeline.cv_waqf.candidates import Candidate
    from pipeline.cv_waqf.layout_geo import LayoutWord

    def word(word_id, x0, text):
        return LayoutWord(
            word_id=word_id,
            word_key=f'24:2:{word_id}',
            word_id_space='qpc-layout-global-v1',
            surah=24,
            ayah=2,
            text=text,
            line_number=5,
            word_on_line=word_id,
            words_on_line=2,
            x0=x0,
            y0=518,
            x1=x0 + 84,
            y1=594,
        )

    plain = word(20, 382, 'وَٱلْيَوْمِ')
    trusted_seat = word(21, 298, 'ٱلْـَٔاخِرِۖ')
    candidate = Candidate(x=376, y=547, w=24, h=24, area=100)

    assert _nearest_word(candidate, [plain, trusted_seat], 86.7) == trusted_seat


def test_hand_evaluation_scores_symbol_and_word_together(monkeypatch):
    from pipeline.cv_waqf import evaluate_hand

    monkeypatch.setattr(
        evaluate_hand,
        'detect_page',
        lambda *_args, **_kwargs: {
            'marks': [
                {'word_key': '2:2:1', 'symbol': 'ج', 'confidence': 0.98},
                {'word_key': '2:2:2', 'symbol': 'ص', 'confidence': 0.91},
            ],
        },
    )
    report = evaluate_hand.evaluate_labels(
        'البحرين',
        [
            {'page': 2, 'word_key': '2:2:1', 'symbol': 'ج'},
            {'page': 2, 'word_key': '2:2:2', 'symbol': 'ق'},
            {'page': 2, 'word_key': '2:2:3', 'symbol': 'م'},
            {'page': 2, 'word_key': '2:2:4', 'symbol': 'none'},
        ],
    )

    assert report['summary']['correct'] == 1
    assert report['summary']['wrong_symbol'] == 1
    assert report['summary']['missing'] == 1
    assert report['summary']['correct_negative'] == 1


def test_hand_evaluation_does_not_treat_a_rejected_crop_as_word_absence(
    monkeypatch,
):
    from pipeline.cv_waqf import evaluate_hand

    monkeypatch.setattr(
        evaluate_hand,
        'detect_page',
        lambda *_args, **_kwargs: {
            'marks': [
                {'word_key': '24:2:8', 'symbol': 'ص', 'confidence': 0.98},
            ],
        },
    )
    report = evaluate_hand.evaluate_labels(
        'البحرين',
        [
            {
                'id': 'false-crop', 'page': 350,
                'word_key': '24:2:8', 'symbol': 'none',
            },
            {
                'id': 'missed-real-mark', 'page': 350,
                'word_key': '24:2:8', 'symbol': 'ص',
            },
        ],
    )

    assert report['summary']['anchored_seats'] == 1
    assert report['summary']['positive_seats'] == 1
    assert report['summary']['negative_seats'] == 0
    assert report['summary']['correct'] == 1
    assert report['summary']['ignored_crop_or_duplicate_labels'] == 1


def test_hand_evaluation_can_use_an_explicit_demo_model(monkeypatch, tmp_path):
    from pipeline.cv_waqf import evaluate_hand

    calls = []
    monkeypatch.setattr(
        evaluate_hand,
        'detect_page',
        lambda *_args, **kwargs: calls.append(kwargs) or {'marks': []},
    )
    model = tmp_path / 'demo.onnx'
    report = evaluate_hand.evaluate_labels(
        'البحرين',
        [{'page': 2, 'word_key': '2:2:1', 'symbol': 'ج'}],
        model_path=model,
    )

    assert calls == [{'min_conf': 0.70, 'proposal_mode': 'hybrid', 'azhar_prior': True, 'model_path': model}]
    assert report['model'] == str(model)
    assert report['proposal_mode'] == 'hybrid'


def test_hand_evaluation_defaults_to_edition_proposal_mode(monkeypatch):
    from pipeline.cv_waqf import evaluate_hand

    calls = []
    monkeypatch.setattr(
        evaluate_hand,
        'detect_page',
        lambda *_args, **kwargs: calls.append(kwargs) or {'marks': []},
    )
    labels = [{'page': 2, 'word_key': '2:2:1', 'symbol': 'ج'}]

    bahrain = evaluate_hand.evaluate_labels('البحرين', labels)
    assert calls[-1]['proposal_mode'] == 'hybrid'
    assert bahrain['proposal_mode'] == 'hybrid'

    shamarly = evaluate_hand.evaluate_labels('الشمرلي', labels)
    assert calls[-1]['proposal_mode'] == 'narrow'
    assert shamarly['proposal_mode'] == 'narrow'

    overridden = evaluate_hand.evaluate_labels(
        'البحرين', labels, proposal_mode='narrow',
    )
    assert calls[-1]['proposal_mode'] == 'narrow'
    assert overridden['proposal_mode'] == 'narrow'


def test_run_page_cli_omits_proposal_mode_unless_passed(monkeypatch, capsys):
    from pipeline.cv_waqf import run_page

    calls = []
    monkeypatch.setattr(
        run_page,
        'detect_page',
        lambda edition, page, **kwargs: calls.append((edition, kwargs)) or {
            'edition': edition,
            'page': page,
            'marks': [],
        },
    )

    assert run_page.main(['--edition', 'البحرين', '--page', '198']) == 0
    assert calls[-1][0] == 'البحرين'
    assert calls[-1][1]['proposal_mode'] is None
    assert calls[-1][1]['azhar_prior'] is None

    assert run_page.main([
        '--edition', 'البحرين', '--page', '198', '--proposal-mode', 'narrow',
    ]) == 0
    assert calls[-1][1]['proposal_mode'] == 'narrow'

    assert run_page.main([
        '--edition', 'البحرين', '--page', '198', '--no-azhar-prior',
    ]) == 0
    assert calls[-1][1]['azhar_prior'] is False
    capsys.readouterr()


def test_review_queue_is_deterministic_and_covers_every_band():
    from pipeline.cv_waqf.review_queue import select_stratified_pages

    stats = [
        {
            'page': page,
            'line_count': 15,
            'surah_headers': 1 if page % 17 == 0 else 0,
            'basmallah_lines': 1 if page % 17 == 0 else 0,
            'centered_ayah_lines': 1 if page % 29 == 0 else 0,
            'word_count': 35 + (page % 23),
        }
        for page in range(1, 605)
    ]
    first = select_stratified_pages(stats, size=30, bands=6)
    second = select_stratified_pages(stats, size=30, bands=6)

    assert [row['page'] for row in first] == [row['page'] for row in second]
    assert len(first) == 30
    assert first[0]['page'] == 1
    assert first[-1]['page'] == 604
    assert all(
        any(lo <= row['page'] <= hi for row in first)
        for lo, hi in ((1, 101), (102, 202), (203, 302), (303, 403), (404, 503), (504, 604))
    )


def test_bahrain_review_queue_includes_targeted_rare_symbol_batch():
    from pipeline.cv_waqf.review_queue import PRIORITY_PAGES, build_review_queue

    queue = build_review_queue('البحرين')
    pages = [row['page'] for row in queue['pages']]
    targeted = [row for row in queue['pages'] if row.get('priority')]

    assert pages[:len(PRIORITY_PAGES['البحرين'])] == list(
        PRIORITY_PAGES['البحرين']
    )
    assert {row['page'] for row in targeted} == set(PRIORITY_PAGES['البحرين'])
    assert all('targeted' in row['tags'] for row in targeted)
    assert queue['targeted_size'] == len(PRIORITY_PAGES['البحرين'])


def _attached_mark(word_key, symbol='ص', confidence=0.99, word_id=1):
    from pipeline.cv_waqf.attach import AttachedMark
    from pipeline.cv_waqf.candidates import Candidate

    surah, ayah, _position = (int(part) for part in word_key.split(':'))
    return AttachedMark(
        word_id=word_id,
        word_key=word_key,
        word_id_space='qpc',
        surah=surah,
        ayah=ayah,
        text='كلمة',
        symbol=symbol,
        confidence=confidence,
        page=2,
        line_number=1,
        candidate=Candidate(x=10, y=10, w=8, h=8, area=64),
    )


def _stub_detect_pipeline(monkeypatch, attached):
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
    monkeypatch.setattr(run_page, '_attach_from_hits', lambda *_: list(attached))


def test_only_bahrain_enables_azhar_seat_prior():
    from pipeline.cv_waqf.config import EDITIONS, resolve_azhar_seat_prior

    assert EDITIONS['البحرين'].azhar_seat_prior is True
    assert resolve_azhar_seat_prior('البحرين') is True
    others = {
        key: spec.azhar_seat_prior
        for key, spec in EDITIONS.items()
        if key != 'البحرين'
    }
    assert others
    assert all(value is False for value in others.values())
    assert resolve_azhar_seat_prior('الشمرلي') is False
    assert resolve_azhar_seat_prior('البحرين', False) is False
    assert resolve_azhar_seat_prior('الشمرلي', True) is True


def test_azhar_occupancy_keeps_mark_regardless_of_glyph(tmp_path):
    import sqlite3

    from pipeline.cv_waqf.azhar_prior import (
        load_azhar_occupied_seats,
        partition_marks_by_azhar_occupancy,
        reset_azhar_occupancy_cache,
        word_has_azhar_waqf,
    )

    db = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE waqf ('
        '"السورة" INTEGER, "الآية" INTEGER, token_index INTEGER, '
        'word_index INTEGER, "الأزهر" TEXT, "البحرين" TEXT, '
        '"الكويت" TEXT, "قطر" TEXT)'
    )
    conn.execute(
        'INSERT INTO waqf VALUES (2,5,5,5,"ج","ص",NULL,NULL)',
    )
    conn.commit()
    conn.close()
    reset_azhar_occupancy_cache()

    assert load_azhar_occupied_seats(str(db)) == {(2, 5, 5)}
    assert word_has_azhar_waqf(2, 5, 5, db_path=db) is True
    kept, rejected = partition_marks_by_azhar_occupancy(
        [{'word_key': '2:5:5', 'surah': 2, 'ayah': 5, 'symbol': 'ص', 'confidence': 0.99}],
        db_path=db,
    )
    assert [row['symbol'] for row in kept] == ['ص']
    assert rejected == []


def test_azhar_occupancy_drops_empty_azhar_word(tmp_path):
    import sqlite3

    from pipeline.cv_waqf.azhar_prior import (
        partition_marks_by_azhar_occupancy,
        reset_azhar_occupancy_cache,
        word_has_azhar_waqf,
    )

    db = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE waqf ('
        '"السورة" INTEGER, "الآية" INTEGER, token_index INTEGER, '
        'word_index INTEGER, "الأزهر" TEXT, "البحرين" TEXT, "قطر" TEXT)'
    )
    conn.execute('INSERT INTO waqf VALUES (2,5,5,5,"ج",NULL,NULL)')
    conn.execute('INSERT INTO waqf VALUES (4,23,11,11,NULL,"ص","ص")')
    conn.execute('INSERT INTO waqf VALUES (2,5,6,6,"","ص",NULL)')
    conn.commit()
    conn.close()
    reset_azhar_occupancy_cache()

    assert word_has_azhar_waqf(4, 23, 11, db_path=db) is False
    assert word_has_azhar_waqf(2, 5, 6, db_path=db) is False
    kept, rejected = partition_marks_by_azhar_occupancy(
        [
            {'word_key': '2:5:5', 'surah': 2, 'ayah': 5, 'symbol': 'ص'},
            {'word_key': '4:23:11', 'surah': 4, 'ayah': 23, 'symbol': 'ص', 'confidence': 0.99},
        ],
        db_path=db,
    )
    assert [row['word_key'] for row in kept] == ['2:5:5']
    assert [row['word_key'] for row in rejected] == ['4:23:11']


def test_azhar_occupancy_fails_open_when_db_missing(tmp_path):
    from pipeline.cv_waqf.azhar_prior import (
        partition_marks_by_azhar_occupancy,
        reset_azhar_occupancy_cache,
        word_has_azhar_waqf,
    )

    reset_azhar_occupancy_cache()
    missing = tmp_path / 'no-such-mushaf_waqf.db'
    assert word_has_azhar_waqf(2, 2, 4, db_path=missing) is True
    marks = [{'word_key': '2:2:4', 'surah': 2, 'ayah': 2, 'symbol': 'ع'}]
    kept, rejected = partition_marks_by_azhar_occupancy(marks, db_path=missing)
    assert kept == marks
    assert rejected == []


def test_azhar_occupancy_matches_word_index_not_token_index(tmp_path):
    import sqlite3

    from pipeline.cv_waqf.azhar_prior import (
        load_azhar_occupied_seats,
        partition_marks_by_azhar_occupancy,
        reset_azhar_occupancy_cache,
        word_has_azhar_waqf,
    )

    db = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE waqf ('
        '"السورة" INTEGER, "الآية" INTEGER, token_index INTEGER, '
        'word_index INTEGER, "الأزهر" TEXT, "البحرين" TEXT)'
    )
    # 33:51:8 تشاء — printed word_index 8, token_index 9, الأزهر ج البحرين ص.
    conn.execute('INSERT INTO waqf VALUES (33,51,9,8,"ج","ص")')
    conn.execute('INSERT INTO waqf VALUES (33,51,27,26,"ج","ج")')
    conn.execute('INSERT INTO waqf VALUES (33,51,32,31,"ج","ج")')
    conn.execute('INSERT INTO waqf VALUES (1,1,1,NULL,"ج",NULL)')
    conn.commit()
    conn.close()
    reset_azhar_occupancy_cache()

    assert load_azhar_occupied_seats(str(db)) == {
        (33, 51, 8), (33, 51, 26), (33, 51, 31),
    }
    assert word_has_azhar_waqf(33, 51, 8, db_path=db) is True
    assert word_has_azhar_waqf(33, 51, 9, db_path=db) is False
    kept, rejected = partition_marks_by_azhar_occupancy(
        [
            {
                'word_key': '33:51:8', 'surah': 33, 'ayah': 51,
                'symbol': 'ص', 'confidence': 0.99,
            },
            {
                'word_key': '33:51:9', 'surah': 33, 'ayah': 51,
                'symbol': 'ص', 'confidence': 0.99,
            },
        ],
        db_path=db,
    )
    assert [row['word_key'] for row in kept] == ['33:51:8']
    assert [row['word_key'] for row in rejected] == ['33:51:9']


def test_bahrain_detect_keeps_word_index_when_token_index_differs(
    monkeypatch, tmp_path,
):
    import sqlite3

    from pipeline.cv_waqf import azhar_prior, run_page

    db = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE waqf ('
        '"السورة" INTEGER, "الآية" INTEGER, token_index INTEGER, '
        'word_index INTEGER, "الأزهر" TEXT, "البحرين" TEXT)'
    )
    conn.execute('INSERT INTO waqf VALUES (33,51,9,8,"ج","ص")')
    conn.commit()
    conn.close()
    monkeypatch.setattr(azhar_prior, 'WAQF_DB', str(db))
    azhar_prior.reset_azhar_occupancy_cache()
    _stub_detect_pipeline(monkeypatch, [
        _attached_mark('33:51:8', symbol='ص', confidence=0.99, word_id=8),
    ])

    result = run_page.detect_page('البحرين', 425)
    assert [row['word_key'] for row in result['marks']] == ['33:51:8']
    assert result['azhar_rejected'] == []
    assert result['azhar_kept'] == 1


def test_detect_overlay_source_has_no_proposal_or_classified_boxes():
    src = (ROOT / 'pipeline' / 'cv_waqf' / 'run_page.py').read_text(
        encoding='utf-8',
    )
    paint = src.split('def paint_detect_overlay')[1].split('def detect_page')[0]
    assert '(180, 180, 80)' not in src
    assert '(0, 140, 255)' not in src
    assert 'for hit in hits' not in paint
    assert 'raw_classified' not in paint
    assert 'cv2.circle' not in src
    assert 'OVERLAY_KEPT_BGR' in src
    assert 'OVERLAY_REJECTED_BGR' not in src
    assert '(0, 0, 220)' not in src
    assert 'rejected' not in paint


def test_paint_detect_overlay_draws_kept_green_only(monkeypatch):
    from pipeline.cv_waqf.run_page import OVERLAY_KEPT_BGR, paint_detect_overlay

    strokes = []

    def capture_rect(_img, _pt1, _pt2, color, _thickness=1):
        strokes.append(('rect', tuple(color)))

    def capture_text(_img, text, _org, _font, _scale, color, *_a, **_k):
        strokes.append(('text', text, tuple(color)))

    def forbid_circle(*_a, **_k):
        raise AssertionError('overlay must not draw circles')

    monkeypatch.setattr('pipeline.cv_waqf.run_page.cv2.rectangle', capture_rect)
    monkeypatch.setattr('pipeline.cv_waqf.run_page.cv2.putText', capture_text)
    monkeypatch.setattr('pipeline.cv_waqf.run_page.cv2.circle', forbid_circle)

    bgr = np.full((40, 40, 3), 255, dtype=np.uint8)
    kept = _attached_mark('33:51:8', symbol='ص', confidence=0.99, word_id=8)
    paint_detect_overlay(bgr, [kept])

    colors = {item[-1] for item in strokes}
    assert colors == {OVERLAY_KEPT_BGR}
    assert ('rect', OVERLAY_KEPT_BGR) in strokes
    assert any(
        item[0] == 'text' and item[1].startswith('ص:') and item[2] == OVERLAY_KEPT_BGR
        for item in strokes
    )
    assert not any(item[-1] == (0, 0, 220) for item in strokes)


def test_detect_page_overlay_writes_green_kept_only(monkeypatch, tmp_path):
    from pipeline.cv_waqf import azhar_prior, run_page

    strokes = []

    def capture_rect(_img, _pt1, _pt2, color, _thickness=1):
        strokes.append(tuple(color))

    def capture_text(_img, _text, _org, _font, _scale, color, *_a, **_k):
        strokes.append(tuple(color))

    def forbid_circle(*_a, **_k):
        raise AssertionError('overlay must not draw circles')

    monkeypatch.setattr(run_page.cv2, 'rectangle', capture_rect)
    monkeypatch.setattr(run_page.cv2, 'putText', capture_text)
    monkeypatch.setattr(run_page.cv2, 'circle', forbid_circle)
    monkeypatch.setattr(run_page.cv2, 'imwrite', lambda *_a, **_k: True)
    monkeypatch.setattr(
        azhar_prior, 'load_azhar_occupied_seats',
        lambda db_path='': {(33, 51, 8)},
    )
    _stub_detect_pipeline(monkeypatch, [
        _attached_mark('33:51:8', symbol='ص', confidence=0.99, word_id=8),
        _attached_mark('4:23:11', symbol='ج', confidence=0.97, word_id=2),
    ])

    overlay = tmp_path / 'p425.jpg'
    result = run_page.detect_page('البحرين', 425, overlay_path=overlay)
    assert set(strokes) == {run_page.OVERLAY_KEPT_BGR}
    assert [row['word_key'] for row in result['marks']] == ['33:51:8']
    assert [row['word_key'] for row in result['azhar_rejected']] == ['4:23:11']


def test_bahrain_detect_page_applies_azhar_seat_prior(monkeypatch):
    from pipeline.cv_waqf import azhar_prior, run_page

    occupied = {(2, 5, 5)}
    monkeypatch.setattr(
        azhar_prior, 'load_azhar_occupied_seats', lambda db_path='': occupied,
    )
    _stub_detect_pipeline(monkeypatch, [
        _attached_mark('2:5:5', symbol='ص', confidence=0.99, word_id=1),
        _attached_mark('4:23:11', symbol='ص', confidence=0.97, word_id=2),
    ])

    result = run_page.detect_page('البحرين', 2)
    assert result['azhar_prior'] is True
    assert [row['word_key'] for row in result['marks']] == ['2:5:5']
    assert result['marks'][0]['symbol'] == 'ص'
    assert [row['word_key'] for row in result['azhar_rejected']] == ['4:23:11']
    assert result['azhar_rejected'][0]['reject_reason'] == 'azhar_empty'
    assert result['azhar_kept'] == 1
    assert result['azhar_rejected_count'] == 1


def test_azhar_prior_off_does_not_drop_empty_azhar_word(monkeypatch):
    from pipeline.cv_waqf import azhar_prior, run_page

    monkeypatch.setattr(
        azhar_prior, 'load_azhar_occupied_seats', lambda db_path='': {(2, 5, 5)},
    )
    attached = [
        _attached_mark('4:23:11', symbol='ص', confidence=0.97, word_id=2),
    ]
    _stub_detect_pipeline(monkeypatch, attached)

    shamarly = run_page.detect_page('الشمرلي', 5)
    assert shamarly['azhar_prior'] is False
    assert [row['word_key'] for row in shamarly['marks']] == ['4:23:11']
    assert shamarly['azhar_rejected'] == []

    forced_off = run_page.detect_page('البحرين', 2, azhar_prior=False)
    assert forced_off['azhar_prior'] is False
    assert [row['word_key'] for row in forced_off['marks']] == ['4:23:11']
    assert forced_off['azhar_rejected'] == []


def test_bahrain_detect_page_fails_open_without_azhar_db(monkeypatch):
    from pipeline.cv_waqf import azhar_prior, run_page

    monkeypatch.setattr(
        azhar_prior, 'load_azhar_occupied_seats', lambda db_path='': None,
    )
    _stub_detect_pipeline(monkeypatch, [
        _attached_mark('4:23:11', symbol='ص', confidence=0.97, word_id=2),
    ])

    result = run_page.detect_page('البحرين', 2)
    assert [row['word_key'] for row in result['marks']] == ['4:23:11']
    assert result['azhar_rejected'] == []
    assert result['azhar_rejected_count'] == 0


def test_bahrain_bootstrap_does_not_auto_set_azhar_rejected(monkeypatch):
    from pipeline.cv_waqf import bootstrap_edition

    monkeypatch.setattr(
        bootstrap_edition,
        'detect_page',
        lambda edition, page, **kwargs: {
            'marks': [
                {
                    'word_id': 1, 'word_key': '2:5:5', 'word_id_space': 'qpc',
                    'symbol': 'ص', 'confidence': 0.99, 'text': 'آمنوا',
                },
            ],
            'azhar_rejected': [
                {
                    'word_id': 2, 'word_key': '4:23:11', 'word_id_space': 'qpc',
                    'symbol': 'ص', 'confidence': 0.97, 'text': 'به',
                    'reject_reason': 'azhar_empty',
                },
            ],
        },
    )
    monkeypatch.setattr(
        bootstrap_edition,
        'within_ayah_token_index',
        lambda _db, word_id: (2, 5, int(word_id) - 1, 'كلمة'),
    )

    plan = bootstrap_edition.bootstrap_pages('البحرين', [2])
    assert [row['word_key'] for row in plan['changes']] == ['2:5:5']
    assert plan['review_candidates'] == []
    assert all(row.get('word_key') != '4:23:11' for row in plan['changes'])


def test_ui_payload_exposes_azhar_rejected_marks(monkeypatch):
    from pipeline.cv_waqf import ui_payload

    monkeypatch.setattr(
        ui_payload,
        'detect_page',
        lambda *_args, **_kwargs: {
            'proposal_mode': 'hybrid',
            'azhar_prior': True,
            'candidates': 3,
            'classified': 2,
            'marks': [
                {
                    'word_id': 10, 'word_key': '2:5:5', 'surah': 2, 'ayah': 5,
                    'symbol': 'ص', 'confidence': 0.91, 'text': 'آمنوا',
                    'line': 1, 'box': [1, 2, 3, 4],
                },
            ],
            'azhar_rejected': [
                {
                    'word_id': 11, 'word_key': '4:23:11', 'surah': 4, 'ayah': 23,
                    'symbol': 'ص', 'confidence': 0.97, 'text': 'به',
                    'line': 1, 'box': [5, 6, 7, 8],
                    'reject_reason': 'azhar_empty',
                },
            ],
        },
    )
    monkeypatch.setattr(ui_payload, 'ensure_page_image', lambda *_: Path('/tmp/p.jpg'))
    monkeypatch.setattr(ui_payload, 'load_bgr', lambda *_: None)

    class FakePrepared:
        pass

    monkeypatch.setattr(ui_payload, 'preprocess_page', lambda *_: FakePrepared())
    monkeypatch.setattr(ui_payload, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(ui_payload, 'edition_marks_for_ayahs', lambda *_: {})

    payload = ui_payload.build_ui_payload('البحرين', 2)
    assert [m['word_key'] for m in payload['trusted_marks']] == ['2:5:5']
    assert payload['review_marks'] == []
    assert [m['word_key'] for m in payload['rejected_marks']] == ['4:23:11']
    assert payload['rejected_marks'][0]['trust'] == 'rejected'
    assert payload['rejected_marks'][0]['reject_reason'] == 'azhar_empty'
    assert payload['summary']['rejected'] == 1
    assert payload['summary']['trusted'] == 1
    assert all(m['word_key'] != '4:23:11' for m in payload['cv_marks'])
    assert payload['trusted_marks'][0]['glyph'] == 'ۖ'
    assert payload['trusted_marks'][0]['short_name'] == 'صلى'
    assert payload['rejected_marks'][0]['glyph'] == 'ۖ'


def test_cv_waqf_payload_exposes_real_glyphs_for_mismatch():
    from pipeline.cv_waqf.ui_payload import _glyph_fields, _with_db_contrast

    matched = _with_db_contrast({'symbol': 'ج'}, {'symbol': 'ج', **_glyph_fields('ج')})
    assert matched['glyph'] == 'ۚ'
    assert matched['short_name'] == 'جائز'
    assert matched['vs_db'] == 'match'
    assert 'db_glyph' not in matched

    wrong = _with_db_contrast({'symbol': 'ص'}, {'symbol': 'ق', **_glyph_fields('ق')})
    assert wrong['vs_db'] == 'wrong'
    assert wrong['glyph'] == 'ۖ'
    assert wrong['short_name'] == 'صلى'
    assert wrong['db_symbol'] == 'ق'
    assert wrong['db_glyph'] == 'ۗ'
    assert wrong['db_short_name'] == 'قلى'


def test_hand_evaluation_inherits_edition_azhar_prior(monkeypatch):
    from pipeline.cv_waqf import evaluate_hand

    calls = []
    monkeypatch.setattr(
        evaluate_hand,
        'detect_page',
        lambda *_args, **kwargs: calls.append(kwargs) or {'marks': []},
    )
    labels = [{'page': 2, 'word_key': '2:2:1', 'symbol': 'ج'}]

    bahrain = evaluate_hand.evaluate_labels('البحرين', labels)
    assert calls[-1]['azhar_prior'] is True
    assert bahrain['azhar_prior'] is True

    shamarly = evaluate_hand.evaluate_labels('الشمرلي', labels)
    assert calls[-1]['azhar_prior'] is False
    assert shamarly['azhar_prior'] is False

    overridden = evaluate_hand.evaluate_labels('البحرين', labels, azhar_prior=False)
    assert calls[-1]['azhar_prior'] is False
    assert overridden['azhar_prior'] is False
