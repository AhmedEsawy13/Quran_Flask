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


def test_bahrain_readme_documents_hybrid_default():
    text = (ROOT / 'pipeline' / 'cv_waqf' / 'README.md').read_text(encoding='utf-8')
    assert 'Experimental high-recall' not in text
    assert '--proposal-mode' in text
    assert 'defaults to hybrid proposals' in text


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

    assert calls == [{'min_conf': 0.70, 'proposal_mode': 'hybrid', 'model_path': model}]
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

    assert run_page.main([
        '--edition', 'البحرين', '--page', '198', '--proposal-mode', 'narrow',
    ]) == 0
    assert calls[-1][1]['proposal_mode'] == 'narrow'
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
