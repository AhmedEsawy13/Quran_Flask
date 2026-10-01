"""Train the two-stage glyph classifier as a small CNN instead of an MLP.

Same data, hold-out, augmentation and sidecar format as ``train_classifier``
(so ``GlyphClassifier`` loads the result unchanged); only the network
differs. The MLP sees a flattened 48×48 crop, so a ``ص`` and a ``ج`` that are
shifted by a pixel are unrelated inputs to it. Three conv/pool stages share
that structure across positions, which is what separates those two small,
similar glyphs.

Torch is train-only. Inference is OpenCV DNN on the exported ONNX, which is
built by hand from the weights (Conv/Relu/MaxPool/Gemm only) like
``train_strip`` does, rather than with ``torch.onnx.export``.

This module never imports OpenCV: torch and OpenCV each bundle their own
OpenMP runtime and abort when loaded into one process. Data preparation
(crop loading, hold-out split, augmentation) therefore lives in
``train_cnn_data`` and hands over an ``.npz``; ``train-cnn`` runs the two as
separate processes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.config import CROP_SIZE

CONV_CHANNELS: tuple[int, ...] = (16, 32, 64)
HIDDEN = 128
KERNEL = 3
POOL = 2


def _balance(
    x: np.ndarray, y: np.ndarray, seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Oversample every class to the size of the largest."""
    rng = np.random.default_rng(seed)
    members = {int(c): np.flatnonzero(y == c) for c in np.unique(y)}
    target = max(len(v) for v in members.values())
    pick = np.concatenate([
        np.concatenate([idx, rng.choice(idx, target - len(idx))])
        if len(idx) < target else idx
        for idx in members.values()
    ])
    rng.shuffle(pick)
    return x[pick], y[pick]


def flatten_size(side: int = CROP_SIZE) -> int:
    for _ in CONV_CHANNELS:
        side //= POOL
    return CONV_CHANNELS[-1] * side * side


def export_cnn_onnx(
    convs: list[tuple[np.ndarray, np.ndarray]],
    fc1: tuple[np.ndarray, np.ndarray],
    fc2: tuple[np.ndarray, np.ndarray],
    out_path: Path,
    *,
    classes: list[str],
    metadata: dict | None = None,
) -> Path:
    """Conv/Relu/MaxPool ×3 → Flatten → Gemm/Relu → Gemm, NCHW ``(N,1,48,48)``.

    ``fc1`` is ``(flatten, hidden)`` and ``fc2`` is ``(hidden, classes)``
    (Gemm with ``transB=0``), matching ``export_mlp_onnx``'s convention.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    k = len(classes)
    if fc2[0].shape[1] != k or fc2[1].shape[0] != k:
        raise ValueError(f'fc2 {fc2[0].shape} does not match {k} classes')
    if fc1[0].shape[0] != flatten_size():
        raise ValueError(
            f'fc1 in-features {fc1[0].shape[0]} != flatten {flatten_size()}'
        )
    nodes, inits, current = [], [], 'input'
    pad = KERNEL // 2
    for index, (weight, bias) in enumerate(convs, start=1):
        inits += [
            numpy_helper.from_array(weight.astype(np.float32), name=f'W{index}'),
            numpy_helper.from_array(bias.astype(np.float32), name=f'B{index}'),
        ]
        nodes += [
            helper.make_node(
                'Conv', [current, f'W{index}', f'B{index}'], [f'c{index}'],
                kernel_shape=[KERNEL, KERNEL], pads=[pad] * 4, strides=[1, 1],
            ),
            helper.make_node('Relu', [f'c{index}'], [f'r{index}']),
            helper.make_node(
                'MaxPool', [f'r{index}'], [f'p{index}'],
                kernel_shape=[POOL, POOL], strides=[POOL, POOL],
                pads=[0, 0, 0, 0],
            ),
        ]
        current = f'p{index}'
    inits += [
        numpy_helper.from_array(fc1[0].astype(np.float32), name='Wfc1'),
        numpy_helper.from_array(fc1[1].astype(np.float32), name='Bfc1'),
        numpy_helper.from_array(fc2[0].astype(np.float32), name='Wfc2'),
        numpy_helper.from_array(fc2[1].astype(np.float32), name='Bfc2'),
    ]
    nodes += [
        helper.make_node('Flatten', [current], ['flat'], axis=1),
        helper.make_node(
            'Gemm', ['flat', 'Wfc1', 'Bfc1'], ['z1'],
            alpha=1.0, beta=1.0, transB=0,
        ),
        helper.make_node('Relu', ['z1'], ['a1']),
        helper.make_node(
            'Gemm', ['a1', 'Wfc2', 'Bfc2'], ['logits'],
            alpha=1.0, beta=1.0, transB=0,
        ),
    ]
    graph = helper.make_graph(
        nodes, 'waqf_glyph_cnn',
        [helper.make_tensor_value_info(
            'input', TensorProto.FLOAT, [None, 1, CROP_SIZE, CROP_SIZE],
        )],
        [helper.make_tensor_value_info('logits', TensorProto.FLOAT, [None, k])],
        inits,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid('', 13)],
        producer_name='pipeline.cv_waqf.train_cnn',
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(out_path))
    meta = {
        'classes': list(classes),
        'crop_size': CROP_SIZE,
        'architecture': 'cnn',
        'conv_channels': list(CONV_CHANNELS),
        'hidden': HIDDEN,
        'input': 'input',
        'output': 'logits',
        'input_layout': 'NCHW',
        'ink_as_positive': True,
    }
    if metadata:
        meta.update(metadata)
    out_path.with_suffix('.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    return out_path


def _build(num_classes: int):
    import torch.nn as nn

    layers, in_ch = [], 1
    for out_ch in CONV_CHANNELS:
        layers += [
            nn.Conv2d(in_ch, out_ch, KERNEL, padding=KERNEL // 2),
            nn.ReLU(), nn.MaxPool2d(POOL),
        ]
        in_ch = out_ch
    layers += [
        nn.Flatten(), nn.Linear(flatten_size(), HIDDEN), nn.ReLU(),
        nn.Dropout(0.25), nn.Linear(HIDDEN, num_classes),
    ]
    return nn.Sequential(*layers)


def _extract(net) -> tuple[list, tuple, tuple]:
    """torch weights → numpy in the layout ``export_cnn_onnx`` expects."""
    import torch.nn as nn

    convs = [m for m in net if isinstance(m, nn.Conv2d)]
    linears = [m for m in net if isinstance(m, nn.Linear)]
    conv_w = [
        (m.weight.detach().numpy().copy(), m.bias.detach().numpy().copy())
        for m in convs
    ]
    # torch Linear stores (out, in); Gemm with transB=0 wants (in, out).
    fc = [
        (m.weight.detach().numpy().T.copy(), m.bias.detach().numpy().copy())
        for m in linears
    ]
    return conv_w, fc[0], fc[1]


def train_cnn(
    x: np.ndarray,
    y: np.ndarray,
    *,
    split: tuple[np.ndarray, np.ndarray],
    num_classes: int,
    epochs: int = 25,
    lr: float = 2e-3,
    batch: int = 128,
    seed: int = 0,
    aug: tuple[np.ndarray, np.ndarray] | None = None,
    log_prefix: str = '',
):
    """Best-epoch (page-level validation) CNN weights for ``(x, y)``.

    ``aug`` is ``(x_aug, y_aug)``: pre-augmented copies of *training* crops
    only (made by ``train_cnn_data``), so validation stays untouched.
    """
    import torch
    import torch.nn.functional as F

    torch.manual_seed(seed)
    train_i, val_i = split
    x_tr, y_tr = x[train_i], y[train_i]
    x_va, y_va = x[val_i], y[val_i]
    if aug is not None and len(aug[0]):
        x_tr = np.concatenate([x_tr, aug[0]])
        y_tr = np.concatenate([y_tr, aug[1]])
    x_tr, y_tr = _balance(x_tr, y_tr, seed=seed)

    def tensor(a):
        return torch.from_numpy(
            a.astype(np.float32).reshape(-1, 1, CROP_SIZE, CROP_SIZE)
        )

    xt, yt = tensor(x_tr), torch.from_numpy(y_tr)
    xv, yv = tensor(x_va), torch.from_numpy(y_va)
    net = _build(num_classes)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    gen = torch.Generator().manual_seed(seed)
    best_acc, best_state = -1.0, None
    for epoch in range(epochs):
        net.train()
        order = torch.randperm(len(xt), generator=gen)
        for start in range(0, len(xt), batch):
            idx = order[start:start + batch]
            opt.zero_grad()
            F.cross_entropy(net(xt[idx]), yt[idx]).backward()
            opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            acc = float((net(xv).argmax(1) == yv).float().mean()) if len(xv) else 0.0
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        print(
            f'{log_prefix}epoch {epoch + 1:02d} val_acc={acc:.3f} n={len(x)}',
            flush=True,
        )
    net.load_state_dict(best_state)
    net.eval()
    return _extract(net)


def train_cnn_two_stage(
    data: dict[str, np.ndarray],
    *,
    out_path: Path,
    epochs: int = 25,
    seed: int = 0,
) -> tuple[Path, Path]:
    """Binary mark gate + mark-symbol CNN from a ``train_cnn_data`` bundle.

    ``data`` holds ``x, y`` (all crops), ``train_idx, val_idx`` (page-level
    split) and ``aug_x, aug_src`` (augmented copies of training crops and the
    index of the crop each came from).
    """
    x, y = data['x'], data['y'].astype(np.int64)
    train_i, val_i = data['train_idx'], data['val_idx']
    aug_x, aug_src = data['aug_x'], data['aug_src']
    none_idx = list(CLASSES).index('none')
    mark_classes = [label for label in CLASSES if label != 'none']
    lookup = {
        list(CLASSES).index(label): i for i, label in enumerate(mark_classes)
    }

    gate_y = (y != none_idx).astype(np.int64)
    gate = train_cnn(
        x, gate_y, split=(train_i, val_i), num_classes=2, epochs=epochs,
        seed=seed, aug=(aug_x, gate_y[aug_src]), log_prefix='gate ',
    )
    gate_path = out_path.with_name(f'{out_path.stem}_gate{out_path.suffix}')
    export_cnn_onnx(
        *gate, gate_path, classes=['none', 'mark'],
        metadata={'pipeline': 'binary-gate', 'role': 'mark-gate'},
    )

    marks = np.flatnonzero(y != none_idx)
    sym_x = x[marks]
    sym_y = np.asarray([lookup[int(label)] for label in y[marks]], np.int64)
    position = {int(src): i for i, src in enumerate(marks.tolist())}
    sym_train = np.asarray(
        [position[int(i)] for i in train_i if int(i) in position], np.int64,
    )
    sym_val = np.asarray(
        [position[int(i)] for i in val_i if int(i) in position], np.int64,
    )
    if not len(sym_train) or not len(sym_val):
        raise RuntimeError('two-stage training needs marks in both splits')
    is_mark = y[aug_src] != none_idx
    sym_aug_y = np.asarray(
        [lookup[int(label)] for label in y[aug_src][is_mark]], np.int64,
    )
    symbol = train_cnn(
        sym_x, sym_y, split=(sym_train, sym_val),
        num_classes=len(mark_classes), epochs=epochs, seed=seed,
        aug=(aug_x[is_mark], sym_aug_y), log_prefix='symbol ',
    )
    export_cnn_onnx(
        *symbol, out_path, classes=mark_classes,
        metadata={
            'pipeline': 'two-stage',
            'role': 'symbol-classifier',
            'gate_model': gate_path.name,
            'gate_classes': ['none', 'mark'],
            'full_classes': list(CLASSES),
        },
    )
    return out_path, gate_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True,
                        help='.npz written by train_cnn_data')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)
    with np.load(args.data) as bundle:
        data = {key: bundle[key] for key in bundle.files}
    print(
        f"loaded {len(data['y'])} crops, {len(data['train_idx'])} train / "
        f"{len(data['val_idx'])} val, {len(data['aug_x'])} augmented"
    )
    _symbol, gate = train_cnn_two_stage(
        data, out_path=args.out, epochs=args.epochs, seed=args.seed,
    )
    print(f'wrote {gate}')
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
