"""Smoke tests for the offline OpenCV 5 waqf pipeline.

These tests intentionally avoid importing the Flask app (``conftest.py``).
Run with:

    PYTHONPATH=. .venv/bin/python -m pytest tests/test_cv_waqf.py --noconftest -q
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
    from pipeline.cv_waqf.config import (
        EDITION_MODEL_PATHS, EDITION_STRIP_MODEL_PATHS, MODEL_PATH, ROOT,
    )

    bahrain = EDITION_MODEL_PATHS['البحرين']
    assert bahrain == ROOT / 'models' / 'waqf_glyph_bahrain.onnx'
    assert bahrain != MODEL_PATH
    assert bahrain.with_name('waqf_glyph_bahrain_gate.onnx') == (
        ROOT / 'models' / 'waqf_glyph_bahrain_gate.onnx'
    )
    strip = EDITION_STRIP_MODEL_PATHS['البحرين']
    assert strip == ROOT / 'models' / 'waqf_strip_bahrain.onnx'
    assert strip != bahrain
    assert strip != MODEL_PATH


# Bahrain's gated MLP needs hybrid proposals and a strict auto-set; Qatar
# borrows that model, so it inherits the same operating point until it has its
# own; Kuwait runs the multiprint model the same way. Every other print keeps
# the narrow / 0.70 defaults.
HYBRID_EDITIONS = {'البحرين', 'قطر', 'الكويت', 'المساحة'}


def test_only_bahrain_model_family_defaults_to_hybrid_proposals():
    from pipeline.cv_waqf.config import EDITIONS, resolve_proposal_mode

    assert EDITIONS['البحرين'].default_proposal_mode == 'hybrid'
    assert resolve_proposal_mode('البحرين') == 'hybrid'
    others = {
        key: spec.default_proposal_mode
        for key, spec in EDITIONS.items()
        if key not in HYBRID_EDITIONS
    }
    assert EDITIONS['قطر'].default_proposal_mode == 'hybrid'
    assert others
    assert all(mode == 'narrow' for mode in others.values())
    assert resolve_proposal_mode('الشمرلي') == 'narrow'
    assert resolve_proposal_mode('المساحة') == 'hybrid'  # multiprint-model print
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
    monkeypatch.setattr(run_page, 'preprocess_page', lambda *_, **__: FakePrepared())
    monkeypatch.setattr(run_page, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_above_word_candidates', lambda *_: [])
    monkeypatch.setattr(
        run_page,
        'find_line_component_candidates',
        lambda *_: hybrid_calls.append(True) or [],
    )
    monkeypatch.setattr(run_page, 'GlyphClassifier', lambda **_: FakeClassifier())
    monkeypatch.setattr(
        run_page, 'strip_model_path_for_edition',
        lambda *_args, **_kwargs: None,
    )

    bahrain = run_page.detect_page('البحرين', 198)
    assert hybrid_calls == [True]
    assert bahrain['proposal_mode'] == 'hybrid'
    assert bahrain['strategy'] == 'hybrid-line-components'
    assert bahrain['detector'] == 'mlp'

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


def test_only_bahrain_model_family_auto_set_is_stricter_than_review():
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
        if key not in HYBRID_EDITIONS
    }
    assert EDITIONS['قطر'].auto_set_min_conf == 0.85
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

    monkeypatch.setattr(ui_payload, 'preprocess_page', lambda *_, **__: FakePrepared())
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
    monkeypatch.setattr(run_page, 'preprocess_page', lambda *_, **__: FakePrepared())
    monkeypatch.setattr(run_page, 'estimate_layout_words', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_above_word_candidates', lambda *_: [])
    monkeypatch.setattr(run_page, 'find_line_component_candidates', lambda *_: [])
    monkeypatch.setattr(run_page, 'GlyphClassifier', lambda **_: FakeClassifier())
    monkeypatch.setattr(run_page, '_attach_from_hits', lambda *_: list(attached))
    monkeypatch.setattr(
        run_page, 'strip_model_path_for_edition',
        lambda *_args, **_kwargs: None,
    )


def test_only_the_hybrid_multiprint_prints_enable_azhar_seat_prior():
    from pipeline.cv_waqf.config import EDITIONS, resolve_azhar_seat_prior

    # The prints scored with the seat prior on (it removes ~99% of the
    # detector's false positives there). Everything else stays off until it is
    # scored the same way.
    assert EDITIONS['البحرين'].azhar_seat_prior is True
    assert EDITIONS['قطر'].azhar_seat_prior is True
    assert resolve_azhar_seat_prior('البحرين') is True
    others = {
        key: spec.azhar_seat_prior
        for key, spec in EDITIONS.items()
        if key not in HYBRID_EDITIONS
    }
    assert EDITIONS['الكويت'].azhar_seat_prior is True
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
        'word_index INTEGER, "الأزهر" TEXT, "المدينة الجديد" TEXT, '
        '"المدينة القديم" TEXT, "البحرين" TEXT)'
    )
    conn.execute('INSERT INTO waqf VALUES (33,51,9,8,"ج",NULL,NULL,"ص")')
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
        azhar_prior, 'load_occupied_seats', lambda db_path='', editions=(): occupied,
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
        azhar_prior, 'load_occupied_seats', lambda db_path='', editions=(): {(2, 5, 5)},
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
        azhar_prior, 'load_occupied_seats', lambda db_path='', editions=(): None,
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

    monkeypatch.setattr(ui_payload, 'preprocess_page', lambda *_, **__: FakePrepared())
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


def test_reattach_moves_rejected_mark_to_adjacent_occupied_seat(monkeypatch):
    from types import SimpleNamespace

    from pipeline.cv_waqf import azhar_prior

    monkeypatch.setattr(
        azhar_prior, 'load_occupied_seats',
        lambda *_a, **_k: frozenset({(2, 5, 4), (2, 5, 6)}),
    )

    def word(position, line=3):
        return SimpleNamespace(
            word_id=100 + position, word_key=f'2:5:{position}', text=f'w{position}',
            line_number=line, is_content_word=True,
        )

    def mark(position, conf):
        return SimpleNamespace(
            word_id=100 + position, word_key=f'2:5:{position}', text=f'w{position}',
            surah=2, ayah=5, line_number=3, confidence=conf, symbol='ص',
        )

    words = [word(p) for p in range(1, 8)] + [word(8, line=4)]
    # Mark on word 5 (empty seat): neighbours 6 (occupied) and 4 (occupied).
    # The next word is preferred; word 4 already holds a kept mark.
    kept, rejected = azhar_prior.reattach_rejected_marks(
        [mark(4, 0.9)], [mark(5, 0.8)], words,
    )
    assert sorted(m.word_key for m in kept) == ['2:5:4', '2:5:6']
    assert rejected == []

    # No occupied neighbour on the line: stays rejected.
    far = mark(1, 0.8)
    kept, rejected = azhar_prior.reattach_rejected_marks([], [far], words)
    assert kept == [] and rejected == [far]
    kept, rejected = azhar_prior.reattach_rejected_marks(
        [mark(4, 0.9), mark(6, 0.9)], [mark(5, 0.8)], words,
    )
    assert len(kept) == 2 and len(rejected) == 1


def test_only_kuwait_reattaches_prior_rejected_marks():
    from pipeline.cv_waqf.config import EDITIONS

    assert EDITIONS['الكويت'].prior_reattach is True
    assert all(
        not spec.prior_reattach for key, spec in EDITIONS.items() if key != 'الكويت'
    )


def test_kuwait_split_is_disjoint_and_fixed():
    from pipeline.cv_waqf.splits import kuwait_pages

    train, holdout = kuwait_pages()
    assert (len(train), len(holdout)) == (200, 100)
    assert not set(train) & set(holdout)
    assert (train, holdout) == kuwait_pages()


def test_kuwait_uses_its_own_model_and_others_are_unchanged():
    from pipeline.cv_waqf.config import resolve_edition_model

    path, source = resolve_edition_model('الكويت')
    assert source == 'own' and path.name == 'waqf_glyph_kuwait.onnx'
    assert resolve_edition_model('قطر')[1] == 'multiprint'
    assert resolve_edition_model('البحرين')[1] == 'own'


def test_kuwait_extended_train_keeps_the_holdout_out():
    from pipeline.cv_waqf.splits import kuwait_extended_train, kuwait_pages

    train, holdout = kuwait_pages()
    extended = kuwait_extended_train()
    assert not set(extended) & set(holdout)
    assert set(train) <= set(extended)
    assert len(extended) + len(holdout) == 602


def test_band_for_page_is_parity_aware_only_when_configured():
    from pipeline.cv_waqf.config import EDITIONS

    mesaha = EDITIONS['المساحة']
    assert mesaha.band_for_page(51) == (mesaha.text_top, mesaha.text_bottom)
    assert mesaha.band_for_page(50) == mesaha.text_band_even
    assert mesaha.band_for_page(50) != mesaha.band_for_page(51)
    for key, spec in EDITIONS.items():
        if key != 'المساحة':
            assert spec.text_band_even is None
            assert spec.band_for_page(10) == (spec.text_top, spec.text_bottom)


def test_strip_frame_whitens_frame_and_everything_outside_it():
    import numpy as np

    from pipeline.cv_waqf.preprocess import strip_frame

    h, w = 600, 400
    img = np.full((h, w, 3), 255, np.uint8)
    img[40:560, 30:34] = 0      # frame: four closed rules
    img[40:560, 366:370] = 0
    img[40:44, 30:370] = 0
    img[556:560, 30:370] = 0
    img[10:20, 150:250] = 0     # header text outside the frame
    img[300:320, 100:300] = 0   # text inside
    out = strip_frame(img)
    assert out[300:320, 100:300].max() == 0           # text kept
    assert out[10:20, 150:250].min() == 255           # header gone
    assert out[40:560, 30:34].min() == 255            # rule gone
    assert out[40:560, 366:370].min() == 255
    # No closed frame: returned untouched.
    open_page = np.full((h, w, 3), 255, np.uint8)
    open_page[300:320, 100:300] = 0
    assert strip_frame(open_page) is open_page


def test_printed_position_skips_ornament_tokens(tmp_path):
    import sqlite3

    from pipeline.cv_waqf.word_space import _printed_index, printed_position

    db = tmp_path / 'script.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE words (word_index INTEGER, word_key TEXT, surah INT, ayah INT, text TEXT)'
    )
    rows = [('2:243:1', '۞'), ('2:243:2', 'أَلَمۡ'), ('2:243:3', 'تَرَ'), ('2:243:4', '٢٤٣')]
    conn.executemany(
        'INSERT INTO words VALUES (?,?,2,243,?)',
        [(i, k, t) for i, (k, t) in enumerate(rows)],
    )
    conn.commit(); conn.close()
    _printed_index.cache_clear()
    assert printed_position(str(db), 2, 243, 1) is None      # hizb mark
    assert printed_position(str(db), 2, 243, 2) == 1
    assert printed_position(str(db), 2, 243, 3) == 2
    assert printed_position(str(db), 2, 243, 4) is None      # ayah number


def test_edition_marks_never_read_an_unknown_column_as_text():
    import pytest

    from pipeline.cv_waqf.marks import edition_marks_for_ayahs

    # Mesaha has no column of its own: it borrows Shemrly's, and its marks are
    # real symbols (the bug read the missing column name as a string literal).
    marks = edition_marks_for_ayahs('المساحة', [(2, 243)], 'data/quran_script.db')
    assert marks and set(marks.values()) <= {'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع'}
    with pytest.raises(ValueError):
        edition_marks_for_ayahs('not a column', [(2, 243)], 'data/quran_script.db')


def test_mesaha_eval_pages_are_fixed_and_balanced_by_parity():
    from pipeline.cv_waqf.splits import mesaha_eval_pages

    pages = mesaha_eval_pages()
    assert pages == mesaha_eval_pages() and len(set(pages)) == 20
    assert sum(p % 2 for p in pages) == 10
    assert all(3 <= p <= 826 for p in pages)


def test_layout_only_word_payload_honours_the_page_parity_band():
    """The no-OpenCV fallback used by /cv-waqf must place even Mesaha pages
    on their own band, or the suggested word is half a line off."""
    from modules.cv_waqf_ui import _build_logical_word_payload

    odd = _build_logical_word_payload('المساحة', 51)['words']
    even = _build_logical_word_payload('المساحة', 50)['words']
    assert odd and even
    # Same relative geometry, shifted by the even/odd band difference.
    assert min(w['box'][1] for w in even) < min(w['box'][1] for w in odd)


def test_label_page_seats_follow_each_editions_geometry_convention():
    """Measured editions put the stop 0.51 line down / 0.15 in from the word's
    left edge; the legacy above-the-word seat made the suggestion pick the
    line below on 11% of Bahrain hand labels."""
    from modules.cv_waqf_ui import _build_logical_word_payload
    from pipeline.cv_waqf import geometry
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.layout_geo import mark_roi_for_word

    measured = _build_logical_word_payload('المساحة', 51)['words']
    assert EDITIONS['المساحة'].measured_geometry and measured
    for word in measured[:20]:
        assert tuple(word['seat']) == geometry.mark_seat_roi_from_box(*word['box'])
    legacy = _build_logical_word_payload('الشمرلي', 10)['words']
    assert not EDITIONS['الشمرلي'].measured_geometry and legacy
    assert all(
        w['seat'][1] < geometry.mark_seat_roi_from_box(*w['box'])[1]
        for w in legacy[:20]
    ), 'legacy seat stays above the word'


def test_relayout_split_counts_follow_row_capacities():
    from pipeline.cv_waqf.relayout import _split_counts

    # 12 equal words across rows of capacity 3, 6 and 3 words.
    assert _split_counts([1.0] * 12, [3.0, 6.0, 3.0], 1.0) == [3, 6, 3]
    assert _split_counts([1.0] * 5, [5.0], 1.0) == [5]


def test_relayout_chain_is_monotone_and_prefers_rings():
    from pipeline.cv_waqf.relayout import OcrWord, _consistent_chain

    def anchor(idx, row, x0, text='w'):
        return idx, OcrWord(text, '', x0, 0, x0 + 20, 10, row)

    good = [anchor(0, 0, 500), anchor(1, 0, 300), anchor(3, 1, 500), anchor(4, 1, 200)]
    assert [i for i, _ in _consistent_chain(good)] == [0, 1, 3, 4]
    # A word claimed to be in an earlier row than its predecessor is dropped.
    bad = good[:2] + [anchor(2, 0, 450)] + good[2:]
    assert 2 not in [i for i, _ in _consistent_chain(bad)]
    # A ring that conflicts with two plain anchors outranks them (weight 5 > 2).
    mixed = [anchor(0, 0, 500), anchor(1, 1, 500), anchor(2, 0, 300, '<ring>')]
    assert [i for i, _ in _consistent_chain(mixed)] == [0, 2]


def test_relayout_word_width_grows_with_letters_and_ignores_no_ocr():
    from pipeline.cv_waqf.relayout import relayout_page_rows, word_width

    assert word_width('بِسۡمِ') < word_width('ٱلۡمُسۡتَقِيمَ') < word_width('وَلِيُنذِرُواْ قَوۡمَهُمۡ')
    assert word_width('٢٨٢') > 0
    assert relayout_page_rows(
        page=10 ** 6, leaf_offset=-1, image_width=1024.0, texts=['a'], weights=[1.0],
        row_extents=[(0.0, 100.0)] * 12, row_baselines=[10.0 * i for i in range(12)],
        pitch=10.0,
    ) is None


def test_only_mesaha_uses_ocr_relayout():
    from pipeline.cv_waqf.config import EDITIONS

    assert EDITIONS['المساحة'].ocr_relayout is True
    assert all(not s.ocr_relayout for k, s in EDITIONS.items() if k != 'المساحة')


def test_mesaha_reviewed_layout_pages_skip_relayout():
    from pipeline.cv_waqf.config import EDITIONS

    spec = EDITIONS['المساحة']
    assert spec.layout_trusted(2) and spec.layout_trusted(60)
    assert not spec.layout_trusted(61) and not spec.layout_trusted(None)
    assert not EDITIONS['قطر'].layout_trusted(5)


def _kraken_fixture(monkeypatch, n_rows=6, per_row=8, drop=None, extra=0):
    """Distinct synthetic words, one Kraken line per row, optional dropped token."""
    import itertools

    from pipeline.cv_waqf import relayout

    letters = 'جدصطعفقكلمنهو'
    words = [''.join(t) for t in itertools.islice(itertools.product(letters, repeat=3), 0, 4000, 37)]
    page_words = words[extra: extra + n_rows * per_row]
    texts = words[: extra + n_rows * per_row + extra]
    lines = []
    for k in range(n_rows):
        row = page_words[k * per_row:(k + 1) * per_row]
        if drop is not None and drop // per_row == k:
            row = [w for w in row if w != page_words[drop]]
        lines.append({'y': 100 * (k + 1), 'text': ' '.join(row), 'width': 1000})
    monkeypatch.setattr(relayout, '_kraken_pages', lambda: {'7': lines})
    kw = dict(
        page=7, image_width=4124.0, texts=texts, weights=[1.0] * len(texts),
        row_extents=[(0.0, 1000.0)] * n_rows,
        row_baselines=[100.0 * (k + 1) for k in range(n_rows)], pitch=100.0,
    )
    return relayout, kw


def test_kraken_rows_place_a_word_kraken_missed_by_width(monkeypatch):
    relayout, kw = _kraken_fixture(monkeypatch, drop=16)
    rows = relayout.kraken_rows(**kw)
    assert rows == [list(range(k * 8, (k + 1) * 8)) for k in range(6)]


def test_kraken_rows_find_the_page_inside_neighbouring_words(monkeypatch):
    relayout, kw = _kraken_fixture(monkeypatch, extra=10)
    rows = relayout.kraken_rows(**kw)
    assert rows == [list(range(10 + k * 8, 10 + (k + 1) * 8)) for k in range(6)]


def test_token_alignment_prefers_the_real_occurrence_of_a_repeated_word():
    from pipeline.cv_waqf import relayout

    canon = ['كلم', 'نصر', 'جدع', 'وفق', 'كلم', 'نصر', 'جدع', 'طعم']
    tokens = [('كلم', 0), ('نصر', 0), ('جدع', 0), ('طعم', 1)]
    got = relayout._token_alignment(tokens, canon)
    # The page's words are the second run; the identical first run is another page's.
    assert sorted(got) == [4, 5, 6, 7]


def test_mesaha_relayout_words_pulled_from_a_neighbour_page_keep_their_text():
    """Words the Kraken relayout moves onto a page from the next/previous page
    must carry their text and key (page 346's word list starts ~36 words late)."""
    import cv2
    import pytest

    from pipeline.cv_waqf import layout_geo
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.preprocess import preprocess_page

    spec = EDITIONS['المساحة']
    cached = Path(spec.page_cache_dir) / 'p346_w1024.jpg'
    if not cached.is_file():
        pytest.skip('page 346 scan not cached')
    prepared = preprocess_page(cv2.imread(str(cached)), spec, page=346)
    words = layout_geo.estimate_layout_words(spec, 346, prepared)
    assert words and all(w.text and w.word_key for w in words)


def test_mesaha_drafts_move_a_page_edge_to_a_boundary():
    from pipeline.cv_waqf.mesaha_drafts import _move_edge

    rows = {1: [100, 108], 2: [109, 117], 3: [118, 126]}
    assert _move_edge(rows, 'start', 103) == (3, 0)           # trim the start
    assert rows[1] == [103, 108]
    assert _move_edge(rows, 'start', 99) == (4, 0)            # extend backwards
    assert rows[1] == [99, 108]
    assert _move_edge(rows, 'end', 124) == (3, 0)             # trim the end (one past the last word)
    assert rows[3] == [118, 123]
    rows = {1: [100, 104], 2: [105, 110]}
    moved, emptied = _move_edge(rows, 'start', 107)           # longer than the first row
    assert (moved, emptied) == (7, 1) and rows[1][0] > rows[1][1] and rows[2] == [107, 110]


def test_mesaha_draft_pages_make_every_boundary_contiguous(tmp_path):
    import sqlite3

    from pipeline.cv_waqf import mesaha_drafts

    db = tmp_path / 'layout.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE pages (id INTEGER PRIMARY KEY, page_number INT, line_number INT, '
        'line_type TEXT, is_centered INT, first_word_id INT, last_word_id INT, '
        'surah_number INT, line_text TEXT)')
    # page 63 draft, page 64 untouched (starts 5 words too early), page 65 draft
    for page, rows in ((62, [(1, 1, 30)]), (63, [(1, 31, 60)]), (64, [(1, 56, 90)]), (65, [(1, 91, 120)])):
        for ln, a, b in rows:
            conn.execute('INSERT INTO pages (page_number, line_number, line_type, is_centered, '
                         "first_word_id, last_word_id, surah_number, line_text) VALUES (?,?,?,?,?,?,?,?)",
                         (page, ln, 'ayah', 0, a, b, 1, ''))
    conn.commit()
    conn.close()
    positions = {i: i - 1 for i in range(1, 200)}
    ids = tuple(range(1, 200))
    collected = {63: {'source': 'kraken', 'rows': {1: [31, 60, 30]}},
                 65: {'source': 'kraken', 'rows': {1: [91, 120, 30]}}}
    import pytest

    pytest.importorskip('pipeline.cv_waqf.layout_geo')
    original = mesaha_drafts.layout_geo._ordered_word_ids
    mesaha_drafts.layout_geo._ordered_word_ids = lambda _db: (ids, positions)
    try:
        drafts = mesaha_drafts.plan(collected, str(db), 'unused')
    finally:
        mesaha_drafts.layout_geo._ordered_word_ids = original
    # Page 64 started 5 words early; it now starts where draft 63 ends (position 60 = word 61).
    assert drafts['adjusted'][64] == {1: [60, 89]}
    assert drafts['pages'][63]['rows'] == {1: [30, 59]}      # the draft's own boundary stands
    assert drafts['stats']['untouched page adjusted (overlap)'] == 1


def test_mesaha_drafts_never_move_a_fixed_page_and_neighbours_meet_it(tmp_path):
    import sqlite3

    from pipeline.cv_waqf import mesaha_drafts

    db = tmp_path / 'layout.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE pages (id INTEGER PRIMARY KEY, page_number INT, line_number INT, '
        'line_type TEXT, is_centered INT, first_word_id INT, last_word_id INT, '
        'surah_number INT, line_text TEXT)')
    # page 63 reviewed (fixed) ends at word 60; page 64 is a draft whose relayout starts at 56.
    for page, a, b in ((62, 1, 30), (63, 31, 60), (64, 61, 90)):
        conn.execute('INSERT INTO pages (page_number, line_number, line_type, is_centered, '
                     'first_word_id, last_word_id, surah_number, line_text) VALUES (?,?,?,?,?,?,?,?)',
                     (page, 1, 'ayah', 0, a, b, 1, ''))
    conn.commit()
    conn.close()
    ids = tuple(range(1, 200))
    positions = {i: i - 1 for i in ids}
    collected = {64: {'source': 'kraken', 'rows': {1: [56, 90, 35]}}}
    original = mesaha_drafts.layout_geo._ordered_word_ids
    mesaha_drafts.layout_geo._ordered_word_ids = lambda _db: (ids, positions)
    try:
        drafts = mesaha_drafts.plan(collected, str(db), 'unused', fixed={63})
    finally:
        mesaha_drafts.layout_geo._ordered_word_ids = original
    assert 63 not in drafts['pages'] and 63 not in drafts['adjusted']          # never rewritten
    assert drafts['pages'][64]['rows'] == {1: [60, 89]}                          # starts after page 63's last word
    assert 'moved to meet fixed page 63' in drafts['pages'][64]['notes'][0]


def test_mesaha_logical_rows_map_to_physical_slots_around_a_banner():
    from pipeline.cv_waqf import layout_geo
    from pipeline.cv_waqf.config import EDITIONS

    spec = EDITIONS['المساحة']
    lines = [{'line_number': n, 'line_type': 'ayah'} for n in range(1, 8)] + [
        {'line_number': 8, 'line_type': 'surah_name'},
        {'line_number': 9, 'line_type': 'surah_info'},
        {'line_number': 10, 'line_type': 'basmallah'},
        {'line_number': 11, 'line_type': 'ayah'},
    ]
    slot_of, total = layout_geo.physical_slots(spec, lines)
    assert total == 12 and slot_of[7] == 6 and slot_of[10] == 9 and slot_of[11] == 11
    # an edition without header_slots: one slot per row, as before
    plain, total = layout_geo.physical_slots(EDITIONS['قطر'], lines)
    assert total == 11 and plain[11] == 10


def test_kraken_rows_honour_a_forced_surah_boundary(monkeypatch):
    relayout, kw = _kraken_fixture(monkeypatch)
    assert relayout.kraken_rows(**kw, forced={2: 24}) == [list(range(k * 8, (k + 1) * 8)) for k in range(6)]
    # a boundary the Kraken matches contradict is refused, not forced
    assert relayout.kraken_rows(**kw, forced={2: 20}) is None


def test_kraken_rows_accept_a_short_last_row_before_a_banner(monkeypatch):
    import itertools

    from pipeline.cv_waqf import relayout

    letters = 'جدصطعفقكلمنهو'
    words = [''.join(t) for t in itertools.islice(itertools.product(letters, repeat=3), 0, 4000, 37)]
    sizes = [8, 8, 3, 8, 8, 8]                       # the surah ends on a 3-word row
    bounds = [0] + list(itertools.accumulate(sizes))
    texts = words[:bounds[-1]]
    lines = [{'y': 100 * (k + 1), 'text': ' '.join(texts[bounds[k]:bounds[k + 1]]), 'width': 1000}
             for k in range(6)]
    monkeypatch.setattr(relayout, '_kraken_pages', lambda: {'7': lines})
    kw = dict(page=7, image_width=4124.0, texts=texts, weights=[1.0] * len(texts),
              row_extents=[(0.0, 1000.0)] * 6, row_baselines=[100.0 * (k + 1) for k in range(6)], pitch=100.0)
    # Without a banner after row 3 the size gate rejects a 3-word row; with one it is the surah's end.
    assert relayout.kraken_rows(**kw) is None
    rows = relayout.kraken_rows(**kw, forced={2: bounds[3]})
    assert rows is not None and [len(r) for r in rows] == sizes


def test_mesaha_blind_pages_are_finished_unlabelled_and_stable():
    from pipeline.cv_waqf.splits import mesaha_blind_pages

    pages = mesaha_blind_pages()
    assert pages == mesaha_blind_pages() and pages == sorted(pages) and len(set(pages)) == 20
    assert all(5 <= p <= 134 for p in pages)                       # layout reviewed
    assert not {2, 3, 4, 61, 62, 113} & set(pages)                 # opening / already labelled / unmarked
    assert {97, 134} <= set(pages)                                 # the banner pages


def test_blind_score_counts_unlabelled_detections_as_false_positives():
    from pipeline.cv_waqf.blind_eval import positives_by_page, score_pages

    labels = [
        {'page': 5, 'word_key': '2:1:1', 'symbol': 'ج', 'word_text': 'a', 'id': '1'},
        {'page': 5, 'word_key': '2:1:2', 'symbol': 'ق', 'word_text': 'b', 'id': '2'},
        {'page': 5, 'word_key': '2:1:3', 'symbol': 'ص', 'word_text': 'c', 'id': '3'},
        {'page': 5, 'word_key': '2:1:9', 'symbol': 'none', 'id': '4'},      # a rejected crop: not a mark
        {'page': 6, 'word_key': '2:2:1', 'symbol': 'ج', 'id': '5'},         # page 6 is not complete
    ]
    truth = positives_by_page(labels, {5})
    assert set(truth) == {5} and set(truth[5]) == {'2:1:1', '2:1:2', '2:1:3'}
    detected = {5: {
        '2:1:1': {'symbol': 'ج', 'confidence': 0.9},      # right
        '2:1:2': {'symbol': 'ص', 'confidence': 0.8},      # wrong symbol
        '2:1:7': {'symbol': 'ج', 'confidence': 0.99},     # nothing labelled there: false positive
    }}                                                    # 2:1:3 is missed
    r = score_pages(truth, detected)
    assert (r['labelled_marks'], r['detected_marks']) == (3, 3)
    assert (r['correct'], r['wrong_symbol'], r['missed'], r['false_positive']) == (1, 1, 1, 1)
    assert r['recall'] == round(1 / 3, 4) and r['found'] == round(2 / 3, 4) and r['precision'] == round(1 / 3, 4)
    assert r['confusion'] == {'ق->ص': 1} and r['false_positives'][0]['word_key'] == '2:1:7'
    assert r['by_symbol']['ص'] == {'missed': 1}


def test_latest_label_per_word_wins_in_blind_scoring():
    from pipeline.cv_waqf.blind_eval import positives_by_page

    labels = [
        {'page': 5, 'word_key': 'w', 'symbol': 'ج', 'created_at': '2026-10-05T10:00:00Z', 'id': 'a'},
        {'page': 5, 'word_key': 'w', 'symbol': 'ص', 'created_at': '2026-10-05T11:00:00Z', 'id': 'b'},
    ]
    assert positives_by_page(labels, {5})[5]['w']['symbol'] == 'ص'


def test_reviewed_marks_file_is_a_consensus_source(tmp_path):
    import json
    import sqlite3

    from pipeline.cv_waqf.sample_crops import consensus_marks

    db = tmp_path / 'script.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE words (word_index INT, word_key TEXT, surah INT, ayah INT, text TEXT)')
    conn.executemany('INSERT INTO words VALUES (?,?,?,?,?)',
                     [(10, '2:5:1', 2, 5, 'a'), (11, '2:5:2', 2, 5, 'b'), (12, '3:1:1', 3, 1, 'c')])
    conn.commit()
    conn.close()
    marks = tmp_path / 'reviewed.json'
    marks.write_text(json.dumps({'pages': [4], 'marks': {'4': {'2:5:2': 'ج'}, '9': {'3:1:1': 'ق'}}}), encoding='utf-8')
    agreed, marked = consensus_marks((f'reviewed:{marks}',), [(2, 5)], str(db))
    assert agreed == {(2, 5, 11): 'ج'}                    # only the ayahs asked for
    assert marked == {(2, 5, 11)}


def _seat_words():
    """Two neighbouring words on one row (RTL: ``a`` is on the right, ``b`` to its left);
    ``a`` carries a script seat (waqf glyph), ``b`` does not."""
    from pipeline.cv_waqf.layout_geo import LayoutWord

    def word(i, text, x0, x1):
        return LayoutWord(word_id=i, word_key=f'2:1:{i}', word_id_space='s', surah=2, ayah=1, text=text,
                          line_number=1, word_on_line=i, words_on_line=2, x0=x0, y0=100, x1=x1, y1=177)
    return word(1, 'كتابۖ', 300, 400), word(2, 'ربنا', 200, 296)


def test_seat_owner_is_the_word_whose_seat_is_nearest():
    from pipeline.cv_waqf import geometry
    from pipeline.cv_waqf.attach import seat_owner
    from pipeline.cv_waqf.candidates import Candidate

    a, b = _seat_words()
    sx, sy = geometry.mark_seat_centre(b.x0, b.y0, b.y1)
    cand = Candidate(x=int(sx) - 12, y=int(sy) - 12, w=24, h=24, area=100, score=1.0)
    assert seat_owner(cand, [a, b]).word_id == b.word_id           # b has no script seat; a does
    far = Candidate(x=0, y=0, w=24, h=24, area=100, score=1.0)
    assert seat_owner(far, [a, b]) is None                          # nothing near: no owner


def test_attach_by_seat_ignores_a_misleading_cluster_pairing():
    from types import SimpleNamespace

    from pipeline.cv_waqf import geometry
    from pipeline.cv_waqf.candidates import Candidate
    from pipeline.cv_waqf.run_page import _attach_from_hits

    a, b = _seat_words()
    sx, sy = geometry.mark_seat_centre(b.x0, b.y0, b.y1)
    cand = Candidate(x=int(sx) - 12, y=int(sy) - 12, w=24, h=24, area=100, score=1.0)
    # The strip detector paired this ink with word ``a`` (counts matched, boundaries did not).
    hit = SimpleNamespace(candidate=cand, layout_word=a, line_number=1)
    default = _attach_from_hits([(hit, 'ج', 0.9)], 5, [a, b])
    by_seat = _attach_from_hits([(hit, 'ج', 0.9)], 5, [a, b], by_seat=True)
    assert [m.word_id for m in default] == [a.word_id]             # the bug: the neighbour
    assert [m.word_id for m in by_seat] == [b.word_id]             # the fix: the word under the mark


def test_only_mesaha_attaches_by_seat():
    from pipeline.cv_waqf.config import EDITIONS

    assert EDITIONS['المساحة'].attach_by_seat is True
    assert all(not s.attach_by_seat for k, s in EDITIONS.items() if k != 'المساحة')


def test_reconcile_reopens_pages_with_unseen_proposals_and_tags_moves():
    from pipeline.cv_waqf.mesaha_review.reconcile import reconcile

    words = [{'key': f'w{i}', 'text': f't{i}'} for i in range(4)]
    prop = lambda k, sym, d: {'key': k, 'symbol': sym, 'default': d}
    old = [{'page': 5, 'words': words, 'proposals': [prop('w1', 'ج', 'review'), prop('w3', 'ص', 'accept')]}]
    new = [{'page': 5, 'words': words, 'proposals': [prop('w2', 'ج', 'review'), prop('w3', 'ص', 'accept')]},
           {'page': 6, 'words': words, 'proposals': [prop('w0', 'ق', 'accept')]}]
    out = reconcile(old, new, {'5:w1': '-'}, [5, 6])
    assert out['reopen'] == [5]                                     # page 6 has nothing new
    moved = out['pages'][0]['proposals'][0]
    assert moved['moved_from'] == {'key': 'w1', 'text': 't1'}      # the rejected neighbour
    assert out['report']['lost_marks'] == []


def test_word_cuts_are_pinned_by_anchors_so_one_bad_width_cannot_shift_a_row():
    import numpy as np

    from pipeline.cv_waqf import geometry

    mask = np.zeros((100, 600), dtype=bool)
    truth = [(560, 480), (470, 400), (390, 300), (290, 230), (220, 120), (110, 40)]   # RTL (right, left)
    for right, left in truth:
        mask[40:60, left:right] = True
    weights = [1, 1, 4, 1, 1, 1]                      # a bad width estimate for the third word
    plain = geometry.segment_line_words(mask, baseline=50, pitch=60, weights=weights, x_range=(0, 600))
    pinned = geometry.segment_line_words(
        mask, baseline=50, pitch=60, weights=weights, x_range=(0, 600),
        anchors={1: (400.0, 470.0), 3: (230.0, 290.0)},
    )
    expected_cuts = [475, 395, 295, 225, 115]         # the middle of each real gap

    def cut_error(spans):
        return max(abs(spans[i][0] - expected_cuts[i]) for i in range(5))
    assert cut_error(pinned) <= 12 and cut_error(plain) > 40
    # anchors that contradict reading order are ignored, not trusted
    bad = geometry.segment_line_words(mask, baseline=50, pitch=60, weights=[1] * 6, x_range=(0, 600),
                                      anchors={1: (100.0, 150.0), 2: (400.0, 450.0)})
    assert bad is not None and len(bad) == 6


def test_ocr_row_anchors_only_pin_words_the_alignment_is_sure_of():
    from pipeline.cv_waqf import layout_geo, relayout

    def ocr(text, x0, x1, row_y=100):
        return relayout.OcrWord(text, relayout._rasm(text), x0, row_y - 15, x1, row_y + 15)

    texts = ['كتابنا', 'ربنا', 'الرحمن']                  # RTL: first word is rightmost
    words = [ocr('كتابنا', 400, 500), ocr('ربنا', 300, 380), ocr('xyzw', 150, 250), ocr('الرحمن', 40, 140)]
    got = layout_geo._ocr_row_anchors(words, texts, baseline=100.0, pitch=60.0, x_range=(0, 600))
    assert got == {0: (400.0, 500.0), 1: (300.0, 380.0), 2: (40.0, 140.0)}
    # a word on another row is not an anchor
    far = [ocr('كتابنا', 400, 500, row_y=400), ocr('ربنا', 300, 380, row_y=400)]
    assert layout_geo._ocr_row_anchors(far, texts, baseline=100.0, pitch=60.0, x_range=(0, 600)) == {}


def test_only_mesaha_uses_learned_widths_ocr_anchors_and_kraken_windows():
    from pipeline.cv_waqf.config import EDITIONS

    mesaha = EDITIONS['المساحة']
    assert mesaha.learned_widths and mesaha.ocr_word_anchors and mesaha.kraken_word_windows
    assert all(
        not (s.learned_widths or s.ocr_word_anchors or s.kraken_word_windows)
        for k, s in EDITIONS.items() if k != 'المساحة'
    )


def test_a_kraken_window_picks_the_real_word_gap_over_a_nearer_gap_inside_a_word():
    import numpy as np

    from pipeline.cv_waqf import geometry

    mask = np.zeros((100, 600), dtype=bool)
    for right, left in ((590, 470), (460, 412), (400, 250), (235, 40)):     # RTL pieces; gaps at 465, 406 and 242
        mask[40:60, left:right] = True
    kwargs = dict(baseline=50, pitch=60, weights=[1, 1, 1], x_range=(0, 600))
    plain = geometry.segment_line_words(mask, **kwargs)
    windowed = geometry.segment_line_words(mask, **kwargs, windows={1: (465.0, 465.0)})
    assert abs(plain[0][0] - 406) <= 6                  # the gap inside the middle word sits on the expected cut
    assert abs(windowed[0][0] - 465) <= 6               # the window moves the cut to the real word gap
    assert abs(windowed[1][0] - 242) <= 6               # the rest of the row is unchanged
    # a window that is wrong by a lot is overruled by the ink rather than followed
    wrong = geometry.segment_line_words(mask, **kwargs, windows={1: (130.0, 130.0)})
    assert wrong is not None and len(wrong) == 3


def test_kraken_row_marks_read_edges_and_the_space_between_neighbouring_words():
    from pipeline.cv_waqf import relayout

    texts = ['كتابنا', 'ربنا', 'الرحمن']                 # reading order: the first word is rightmost
    # Kraken's line is in display order (left to right), so each word's letters come out reversed.
    text = 'نمحرلا انبر انباتك'
    xs = [40, 50, 60, 70, 80, 90, 105, 120, 130, 140, 150, 165, 180, 190, 200, 210, 220, 230]
    line = {'y': 100.0, 'text': text, 'x': [float(x) for x in xs]}
    edges, cuts = relayout.kraken_row_marks([line], texts, baseline=100.0, pitch=60.0)
    assert edges[0] == (180 + relayout.KRAKEN_LEFT_BIAS * 60, 230 + relayout.KRAKEN_RIGHT_BIAS * 60)
    assert cuts == {1: 165 + relayout.KRAKEN_SPACE_BIAS * 60, 2: 105 + relayout.KRAKEN_SPACE_BIAS * 60}
    # a line on another row says nothing about this one
    assert relayout.kraken_row_marks([line], texts, baseline=400.0, pitch=60.0) == ({}, {})


def test_unread_words_between_matched_neighbours_are_paired_in_order_only_when_counts_agree():
    from pipeline.cv_waqf.relayout import _fill_unread

    assert _fill_unread({0: 0, 3: 3}, 5, 5) == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}
    # two known words between the matches but one read: no guess there; the single word after the last match is paired
    assert _fill_unread({0: 0, 3: 2}, 5, 4) == {0: 0, 3: 2, 4: 3}
    assert _fill_unread({}, 3, 3) == {}


def test_kraken_chars_are_scaled_into_the_working_image(monkeypatch):
    from pipeline.cv_waqf import relayout

    asset = {'width': 1000, 'pages': {'8': [{'y': 400.0, 't': 'ab c', 'x': [10, 20, 30, 40]}]}}
    monkeypatch.setattr(relayout, '_kraken_chars_asset', lambda: asset)
    got = relayout.kraken_chars(8, 500.0)
    assert got == [{'y': 200.0, 'text': 'ab c', 'x': [5.0, 10.0, 15.0, 20.0]}]
    assert relayout.kraken_chars(9, 500.0) == []
