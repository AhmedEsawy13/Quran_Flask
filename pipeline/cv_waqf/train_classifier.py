"""Train a tiny MLP on glyph crops and export ONNX for OpenCV 5 DNN."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.classify import save_classes
from pipeline.cv_waqf.config import CLASSES_PATH, CROPS_ROOT, CROP_SIZE, MODEL_PATH

CLASS_DIRS = {
    'م': 'm',
    'ق': 'q',
    'ص': 's',
    'ج': 'j',
    'لا': 'la',
    'ع': 'a',
    'س': 'sakta',
    'none': 'none',
}


def load_dataset(crops_root: Path) -> tuple[np.ndarray, np.ndarray]:
    xs: list[np.ndarray] = []
    ys: list[int] = []
    for idx, label in enumerate(CLASSES):
        folder = crops_root / CLASS_DIRS[label]
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob('*.png')):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if img.shape != (CROP_SIZE, CROP_SIZE):
                img = cv2.resize(img, (CROP_SIZE, CROP_SIZE))
            x = img.astype(np.float32) / 255.0
            x = 1.0 - x
            xs.append(x.reshape(-1))
            ys.append(idx)
    if not xs:
        raise RuntimeError(f'no crops found under {crops_root}')
    return np.stack(xs), np.asarray(ys, dtype=np.int64)


def _one_hot(y: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros((len(y), n), dtype=np.float32)
    out[np.arange(len(y)), y] = 1.0
    return out


def train_mlp(
    x: np.ndarray,
    y: np.ndarray,
    *,
    hidden: int = 128,
    epochs: int = 40,
    lr: float = 0.05,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n, d = x.shape
    k = len(CLASSES)
    # Train/val split
    idx = np.arange(n)
    rng.shuffle(idx)
    split = max(1, int(0.85 * n))
    train_i, val_i = idx[:split], idx[split:]
    x_tr, y_tr = x[train_i], y[train_i]
    x_va, y_va = x[val_i], y[val_i]

    w1 = rng.normal(0, 0.05, size=(d, hidden)).astype(np.float32)
    b1 = np.zeros((hidden,), dtype=np.float32)
    w2 = rng.normal(0, 0.05, size=(hidden, k)).astype(np.float32)
    b2 = np.zeros((k,), dtype=np.float32)

    batch = 64
    for epoch in range(epochs):
        order = rng.permutation(len(x_tr))
        for start in range(0, len(x_tr), batch):
            bi = order[start:start + batch]
            xb = x_tr[bi]
            yb = _one_hot(y_tr[bi], k)
            # forward
            z1 = xb @ w1 + b1
            a1 = np.maximum(z1, 0)
            logits = a1 @ w2 + b2
            logits = logits - logits.max(axis=1, keepdims=True)
            exp = np.exp(logits)
            probs = exp / exp.sum(axis=1, keepdims=True)
            # grads
            dlogits = (probs - yb) / len(xb)
            dw2 = a1.T @ dlogits
            db2 = dlogits.sum(axis=0)
            da1 = dlogits @ w2.T
            dz1 = da1 * (z1 > 0)
            dw1 = xb.T @ dz1
            db1 = dz1.sum(axis=0)
            w2 -= lr * dw2
            b2 -= lr * db2
            w1 -= lr * dw1
            b1 -= lr * db1
        # metrics
        pred = _predict(x_va, w1, b1, w2, b2) if len(x_va) else _predict(x_tr, w1, b1, w2, b2)
        truth = y_va if len(x_va) else y_tr
        acc = float((pred == truth).mean()) if len(truth) else 0.0
        print(f'epoch {epoch + 1:02d} val_acc={acc:.3f} n={n}')
    return w1, b1, w2, b2


def _predict(x, w1, b1, w2, b2) -> np.ndarray:
    a1 = np.maximum(x @ w1 + b1, 0)
    logits = a1 @ w2 + b2
    return logits.argmax(axis=1)


def export_onnx(
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    out_path: Path,
) -> Path:
    """Export Flatten→Gemm→Relu→Gemm as ONNX (NCHW input 1x1xSxS)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    d = CROP_SIZE * CROP_SIZE
    hidden = w1.shape[1]
    k = w2.shape[1]

    # Input: NCHW → reshape to N,d
    nodes = [
        helper.make_node('Flatten', ['input'], ['flat'], axis=1),
        helper.make_node(
            'Gemm', ['flat', 'W1', 'B1'], ['z1'],
            alpha=1.0, beta=1.0, transB=0,
        ),
        helper.make_node('Relu', ['z1'], ['a1']),
        helper.make_node(
            'Gemm', ['a1', 'W2', 'B2'], ['logits'],
            alpha=1.0, beta=1.0, transB=0,
        ),
    ]
    graph = helper.make_graph(
        nodes,
        'waqf_glyph_mlp',
        [helper.make_tensor_value_info(
            'input', TensorProto.FLOAT, [None, 1, CROP_SIZE, CROP_SIZE],
        )],
        [helper.make_tensor_value_info(
            'logits', TensorProto.FLOAT, [None, k],
        )],
        [
            numpy_helper.from_array(w1.astype(np.float32), name='W1'),
            numpy_helper.from_array(b1.astype(np.float32), name='B1'),
            numpy_helper.from_array(w2.astype(np.float32), name='W2'),
            numpy_helper.from_array(b2.astype(np.float32), name='B2'),
        ],
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid('', 13)],
        producer_name='pipeline.cv_waqf',
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(out_path))
    # sidecar meta
    meta = {
        'classes': list(CLASSES),
        'crop_size': CROP_SIZE,
        'hidden': hidden,
        'input': 'input',
        'output': 'logits',
        'input_layout': 'NCHW',
        'ink_as_positive': True,
    }
    out_path.with_suffix('.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crops', type=Path, default=CROPS_ROOT)
    parser.add_argument('--out', type=Path, default=MODEL_PATH)
    parser.add_argument('--epochs', type=int, default=35)
    parser.add_argument('--hidden', type=int, default=128)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)

    x, y = load_dataset(args.crops)
    print(f'loaded {len(y)} crops across {len(set(y.tolist()))} classes')
    # Balance lightly by oversampling minority
    x, y = _balance(x, y, seed=args.seed)
    w1, b1, w2, b2 = train_mlp(
        x, y, hidden=args.hidden, epochs=args.epochs, seed=args.seed,
    )
    export_onnx(w1, b1, w2, b2, args.out)
    save_classes(CLASSES_PATH, list(CLASSES))
    print(f'wrote {args.out}')
    print(f'wrote {CLASSES_PATH}')
    return 0


def _balance(x: np.ndarray, y: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    by: dict[int, list[int]] = {}
    for i, label in enumerate(y.tolist()):
        by.setdefault(label, []).append(i)
    target = max(len(v) for v in by.values())
    idx: list[int] = []
    for label, members in by.items():
        chosen = list(members)
        while len(chosen) < target:
            chosen.append(rng.choice(members))
        idx.extend(chosen)
    rng.shuffle(idx)
    return x[idx], y[idx]


if __name__ == '__main__':
    raise SystemExit(main())
