"""CNN classifier plumbing that must work without torch in the process.

torch and OpenCV each bundle an OpenMP runtime and abort when loaded into one
process, so the trainer is split (see ``train_cnn``) and these tests never
import torch: they cover the exported graph, its use through
``GlyphClassifier``, and the data bundle handed to the trainer.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')
pytest.importorskip('onnx')

from pipeline.cv_waqf import CLASSES  # noqa: E402
from pipeline.cv_waqf import train_cnn  # noqa: E402
from pipeline.cv_waqf.config import CROP_SIZE  # noqa: E402


def _weights(num_classes: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    convs, in_ch = [], 1
    for out_ch in train_cnn.CONV_CHANNELS:
        convs.append((
            rng.normal(0, 0.1, (out_ch, in_ch, 3, 3)).astype(np.float32),
            np.zeros(out_ch, np.float32),
        ))
        in_ch = out_ch
    flat = train_cnn.flatten_size()
    return (
        convs,
        (rng.normal(0, 0.05, (flat, train_cnn.HIDDEN)).astype(np.float32),
         np.zeros(train_cnn.HIDDEN, np.float32)),
        (rng.normal(0, 0.05, (train_cnn.HIDDEN, num_classes)).astype(np.float32),
         np.zeros(num_classes, np.float32)),
    )


def test_this_module_never_imports_opencv_or_the_cv2_trainer():
    """The torch process must stay cv2-free (OpenMP runtime clash)."""
    tree = ast.parse(Path(train_cnn.__file__).read_text(encoding='utf-8'))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert 'cv2' not in imported
    assert 'pipeline.cv_waqf.train_classifier' not in imported
    assert 'pipeline.cv_waqf.train_cnn_data' not in imported


def test_flatten_size_matches_three_pools():
    assert train_cnn.flatten_size() == 64 * 6 * 6


def test_exported_cnn_runs_in_opencv_dnn(tmp_path):
    classes = ['none', 'mark']
    out = train_cnn.export_cnn_onnx(
        *_weights(2), tmp_path / 'gate.onnx', classes=classes,
        metadata={'pipeline': 'binary-gate'},
    )
    meta = json.loads(out.with_suffix('.json').read_text(encoding='utf-8'))
    assert meta['classes'] == classes and meta['architecture'] == 'cnn'
    net = cv2.dnn.readNet(str(out))
    batch = np.random.default_rng(1).random(
        (5, 1, CROP_SIZE, CROP_SIZE), dtype=np.float32,
    )
    net.setInput(batch)
    logits = np.asarray(net.forward()).reshape(5, -1)
    assert logits.shape == (5, 2) and np.isfinite(logits).all()
    # Batch-independent: one crop alone gives the same logits as in a batch.
    net.setInput(batch[2:3])
    assert np.allclose(np.asarray(net.forward()).reshape(1, -1), logits[2], atol=1e-4)


def test_export_rejects_mismatched_class_count_and_flatten(tmp_path):
    convs, fc1, fc2 = _weights(4)
    with pytest.raises(ValueError, match='classes'):
        train_cnn.export_cnn_onnx(
            convs, fc1, fc2, tmp_path / 'x.onnx', classes=['a', 'b'],
        )
    bad = (fc1[0][:-1], fc1[1])
    with pytest.raises(ValueError, match='flatten'):
        train_cnn.export_cnn_onnx(
            convs, bad, fc2, tmp_path / 'y.onnx', classes=list('abcd'),
        )


def test_cnn_pair_loads_through_the_unchanged_two_stage_classifier(tmp_path):
    from pipeline.cv_waqf.classify import GlyphClassifier

    mark_classes = [label for label in CLASSES if label != 'none']
    out = tmp_path / 'm.onnx'
    gate = tmp_path / 'm_gate.onnx'
    train_cnn.export_cnn_onnx(
        *_weights(2, 1), gate, classes=['none', 'mark'],
        metadata={'pipeline': 'binary-gate', 'role': 'mark-gate'},
    )
    train_cnn.export_cnn_onnx(
        *_weights(len(mark_classes), 2), out, classes=mark_classes,
        metadata={
            'pipeline': 'two-stage', 'role': 'symbol-classifier',
            'gate_model': gate.name, 'gate_classes': ['none', 'mark'],
            'full_classes': list(CLASSES),
        },
    )
    clf = GlyphClassifier(model_path=out)
    assert clf.ready and clf.pipeline == 'two-stage'
    crops = [np.full((CROP_SIZE, CROP_SIZE), 255, np.uint8) for _ in range(3)]
    results = clf.predict_many_probs(crops)
    assert len(results) == 3
    for label, confidence, probs in results:
        assert label in CLASSES and 0.0 <= confidence <= 1.0
        assert probs.shape == (len(CLASSES),)
        assert probs.sum() == pytest.approx(1.0, abs=1e-4)


def test_balance_oversamples_every_class_to_the_largest():
    x = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([0, 0, 0, 0, 1, 2])
    bx, by = train_cnn._balance(x, y, seed=3)
    assert sorted(np.bincount(by).tolist()) == [4, 4, 4]
    assert np.array_equal(
        train_cnn._balance(x, y, seed=3)[0], bx,
    )  # deterministic


def test_prepare_bundle_has_the_contract_the_trainer_needs(tmp_path):
    from pipeline.cv_waqf.train_cnn_data import prepare

    side = CROP_SIZE
    rng = np.random.default_rng(0)
    for page in range(1, 7):
        for cls, name in (('s', 'ص'), ('none', 'none')):
            folder = tmp_path / 'qatar' / cls
            folder.mkdir(parents=True, exist_ok=True)
            for k in range(3):
                img = (rng.random((side, side)) * 255).astype(np.uint8)
                cv2.imwrite(str(folder / f'p{page:03d}_w{k}_{name}.png'), img)
    bundle = tmp_path / 'b.npz'
    info = prepare(
        [tmp_path / 'qatar'], bundle, holdout={'qatar:p0001', 'qatar:p0002'},
        augment=2, seed=0,
    )
    with np.load(bundle) as data:
        assert data['x'].shape == (36, side * side)
        assert set(data['val_idx'].tolist()).isdisjoint(data['train_idx'].tolist())
        assert len(data['val_idx']) == 12 and len(data['train_idx']) == 24
        # Augmented copies come only from training crops.
        assert len(data['aug_x']) == 2 * len(data['train_idx'])
        assert set(data['aug_src'].tolist()) <= set(data['train_idx'].tolist())
    assert info['train'] == 24 and info['val'] == 12 and info['augmented'] == 48


# ------------------------------------------------------------ ensemble

def _mlp(seed: int, hidden: int, classes: int):
    rng = np.random.default_rng(seed)
    d = CROP_SIZE * CROP_SIZE
    return (
        rng.normal(0, 0.05, (d, hidden)).astype(np.float32),
        rng.normal(0, 0.1, hidden).astype(np.float32),
        rng.normal(0, 0.2, (hidden, classes)).astype(np.float32),
        rng.normal(0, 0.1, classes).astype(np.float32),
    )


def _forward(model, x):
    w1, b1, w2, b2 = model
    return np.maximum(x @ w1 + b1, 0) @ w2 + b2


def test_merged_mlp_logits_equal_the_mean_of_the_members():
    from pipeline.cv_waqf.ensemble_models import merge_mlps

    members = [_mlp(seed, 32, 5) for seed in (1, 2, 3)]
    merged = merge_mlps(members)
    assert merged[0].shape == (CROP_SIZE * CROP_SIZE, 96)   # hidden concatenated
    x = np.random.default_rng(9).random((7, CROP_SIZE * CROP_SIZE)).astype(np.float32)
    expected = np.mean([_forward(m, x) for m in members], axis=0)
    assert np.allclose(_forward(merged, x), expected, atol=1e-4)


def test_merge_rejects_mismatched_members():
    from pipeline.cv_waqf.ensemble_models import merge_mlps

    with pytest.raises(ValueError, match='nothing'):
        merge_mlps([])
    with pytest.raises(ValueError, match='disagree'):
        merge_mlps([_mlp(1, 8, 4), _mlp(2, 8, 5)])


def test_ensemble_of_two_stage_files_runs_through_the_unchanged_classifier(tmp_path):
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.cv_waqf.ensemble_models import ensemble
    from pipeline.cv_waqf.train_classifier import export_mlp_onnx

    mark_classes = [label for label in CLASSES if label != 'none']
    paths = []
    for seed in (1, 2, 3):
        symbol = tmp_path / f'm{seed}.onnx'
        gate = tmp_path / f'm{seed}_gate.onnx'
        export_mlp_onnx(
            *_mlp(seed * 10, 24, 2), gate, classes=['none', 'mark'],
            metadata={'pipeline': 'binary-gate', 'role': 'mark-gate'},
        )
        export_mlp_onnx(
            *_mlp(seed, 24, len(mark_classes)), symbol, classes=mark_classes,
            metadata={
                'pipeline': 'two-stage', 'role': 'symbol-classifier',
                'gate_model': gate.name, 'gate_classes': ['none', 'mark'],
                'full_classes': list(CLASSES),
            },
        )
        paths.append(symbol)
    out = ensemble(paths, tmp_path / 'ens.onnx')
    meta = json.loads(out.with_suffix('.json').read_text(encoding='utf-8'))
    assert meta['ensemble'] == 3 and meta['gate_model'] == 'ens_gate.onnx'
    assert meta['classes'] == mark_classes and meta['pipeline'] == 'two-stage'

    clf = GlyphClassifier(model_path=out)
    assert clf.ready
    crops = [
        (np.random.default_rng(i).random((CROP_SIZE, CROP_SIZE)) * 255).astype(np.uint8)
        for i in range(4)
    ]
    for label, confidence, probs in clf.predict_many_probs(crops):
        assert label in CLASSES and probs.sum() == pytest.approx(1.0, abs=1e-4)
    # The merged symbol net's logits are the members' mean, in OpenCV DNN too.
    batch = np.stack([c.astype(np.float32) / 255.0 for c in crops])
    batch = (1.0 - batch).reshape(4, 1, CROP_SIZE, CROP_SIZE)
    nets = [cv2.dnn.readNet(str(p)) for p in paths]
    member_logits = []
    for net in nets:
        net.setInput(batch)
        member_logits.append(np.asarray(net.forward()).reshape(4, -1))
    merged = cv2.dnn.readNet(str(out))
    merged.setInput(batch)
    assert np.allclose(
        np.asarray(merged.forward()).reshape(4, -1),
        np.mean(member_logits, axis=0), atol=1e-3,
    )


def test_ensemble_refuses_models_with_different_class_lists(tmp_path):
    from pipeline.cv_waqf.ensemble_models import ensemble
    from pipeline.cv_waqf.train_classifier import export_mlp_onnx

    paths = []
    for seed, classes in ((1, ['a', 'b']), (2, ['a', 'c'])):
        gate = tmp_path / f'g{seed}_gate.onnx'
        symbol = tmp_path / f'g{seed}.onnx'
        export_mlp_onnx(*_mlp(seed, 8, 2), gate, classes=['none', 'mark'])
        export_mlp_onnx(
            *_mlp(seed, 8, 2), symbol, classes=classes,
            metadata={'gate_model': gate.name},
        )
        paths.append(symbol)
    with pytest.raises(ValueError, match='class lists'):
        ensemble(paths, tmp_path / 'e.onnx')
