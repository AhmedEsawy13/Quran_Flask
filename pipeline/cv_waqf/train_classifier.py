"""Train a tiny MLP on glyph crops and export ONNX for OpenCV 5 DNN."""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
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


_PAGE_RE = re.compile(r'(?:^|[-_])p(\d{1,4})(?:[-_]|$)', re.IGNORECASE)


def _page_group(path: Path, crops_root: Path, match: re.Match) -> str:
    """Stable physical-page group across positive/negative crop roots."""
    haystack = '/'.join(part.lower() for part in (*crops_root.parts, path.stem))
    for source in (
        'bahrain', 'shamarly', 'mesaha', 'azhar',
        'madinah_1441', 'madinah_1405',
    ):
        if source in haystack:
            return f'{source}:p{int(match.group(1)):04d}'
    # Unknown datasets remain root-scoped to avoid accidentally merging two
    # unrelated prints that happen to use the same page number.
    return f'{crops_root.resolve()}:p{int(match.group(1)):04d}'


def load_grouped_dataset(
    crops_roots: list[Path],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load crops and retain source-page groups for leakage-free splitting."""
    xs: list[np.ndarray] = []
    ys: list[int] = []
    groups: list[str] = []
    for crops_root in crops_roots:
        root_id = str(crops_root.resolve())
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
                match = _PAGE_RE.search(path.stem)
                # Synthetic/non-page samples remain independent groups; real
                # crops from one printed page always stay in one split.
                group = (
                    _page_group(path, crops_root, match)
                    if match else f'{root_id}:sample:{path.name}'
                )
                xs.append(x.reshape(-1))
                ys.append(idx)
                groups.append(group)
    if not xs:
        roots = ', '.join(str(path) for path in crops_roots)
        raise RuntimeError(f'no crops found under {roots}')
    return (
        np.stack(xs),
        np.asarray(ys, dtype=np.int64),
        np.asarray(groups, dtype=object),
    )


def load_dataset(crops_root: Path) -> tuple[np.ndarray, np.ndarray]:
    """Backward-compatible single-root loader."""
    x, y, _groups = load_grouped_dataset([Path(crops_root)])
    return x, y


def split_by_page_group(
    groups: np.ndarray,
    *,
    val_fraction: float = 0.15,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    unique = sorted({str(group) for group in groups.tolist()})
    if len(unique) < 2:
        raise RuntimeError(
            'at least two source pages/groups are required for validation'
        )
    rng = np.random.default_rng(seed)
    rng.shuffle(unique)
    val_n = max(1, int(round(len(unique) * val_fraction)))
    val_n = min(val_n, len(unique) - 1)
    val_groups = set(unique[:val_n])
    val_mask = np.asarray([str(group) in val_groups for group in groups])
    return np.where(~val_mask)[0], np.where(val_mask)[0]


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
    groups: np.ndarray | None = None,
    num_classes: int | None = None,
    split_indices: tuple[np.ndarray, np.ndarray] | None = None,
    log_prefix: str = '',
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n, d = x.shape
    k = int(num_classes or len(CLASSES))
    # Keep entire printed pages on one side of the split. Random crop splitting
    # reports misleadingly high accuracy when near-identical page noise and
    # oversampled duplicates leak into validation.
    if split_indices is not None:
        train_i, val_i = split_indices
    elif groups is not None:
        train_i, val_i = split_by_page_group(groups, seed=seed)
    else:
        idx = np.arange(n)
        rng.shuffle(idx)
        split = max(1, int(0.85 * n))
        train_i, val_i = idx[:split], idx[split:]
    x_tr, y_tr = x[train_i], y[train_i]
    x_va, y_va = x[val_i], y[val_i]
    x_tr, y_tr = _balance(x_tr, y_tr, seed=seed)

    w1 = rng.normal(0, 0.05, size=(d, hidden)).astype(np.float32)
    b1 = np.zeros((hidden,), dtype=np.float32)
    w2 = rng.normal(0, 0.05, size=(hidden, k)).astype(np.float32)
    b2 = np.zeros((k,), dtype=np.float32)

    batch = 64
    best_acc = -1.0
    best_weights = None
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
        if acc > best_acc:
            best_acc = acc
            best_weights = (
                w1.copy(), b1.copy(), w2.copy(), b2.copy(),
            )
        print(
            f'{log_prefix}epoch {epoch + 1:02d} '
            f'val_acc={acc:.3f} n={n}'
        )
    # Training on small print-specific datasets can oscillate after reaching
    # its best page-level validation score. Export the best epoch, not merely
    # the last one.
    if best_weights is not None:
        return best_weights
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
    """Export the backward-compatible single-stage classifier."""
    return export_mlp_onnx(
        w1, b1, w2, b2, out_path, classes=list(CLASSES),
    )


def export_mlp_onnx(
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    out_path: Path,
    *,
    classes: list[str],
    metadata: dict | None = None,
) -> Path:
    """Export Flatten→Gemm→Relu→Gemm as ONNX (NCHW input)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
        'classes': list(classes),
        'crop_size': CROP_SIZE,
        'hidden': hidden,
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


def train_two_stage(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    out_path: Path,
    hidden: int = 128,
    epochs: int = 35,
    seed: int = 0,
    symbol_model_path: Path | None = None,
) -> tuple[Path, Path]:
    """Train a binary mark gate followed by a mark-symbol classifier.

    Both stages use the same page-level split. This prevents a page from
    leaking into the symbol model merely because the binary stage sees it.
    The public classifier combines ``P(mark) * P(symbol | mark)`` and exposes
    the same probabilities/classes contract as the legacy single-stage model.
    """
    none_idx = list(CLASSES).index('none')
    mark_classes = [label for label in CLASSES if label != 'none']
    mark_lookup = {
        list(CLASSES).index(label): index
        for index, label in enumerate(mark_classes)
    }
    train_i, val_i = split_by_page_group(groups, seed=seed)

    gate_y = (y != none_idx).astype(np.int64)
    gw1, gb1, gw2, gb2 = train_mlp(
        x, gate_y,
        hidden=hidden,
        epochs=epochs,
        seed=seed,
        num_classes=2,
        split_indices=(train_i, val_i),
        log_prefix='gate ',
    )

    symbol_mask = y != none_idx
    symbol_source_indices = np.where(symbol_mask)[0]
    symbol_x = x[symbol_mask]
    symbol_y = np.asarray(
        [mark_lookup[int(label)] for label in y[symbol_mask]],
        dtype=np.int64,
    )
    source_to_symbol = {
        int(source_index): index
        for index, source_index in enumerate(symbol_source_indices.tolist())
    }
    symbol_train = np.asarray(
        [source_to_symbol[int(index)] for index in train_i if int(index) in source_to_symbol],
        dtype=np.int64,
    )
    symbol_val = np.asarray(
        [source_to_symbol[int(index)] for index in val_i if int(index) in source_to_symbol],
        dtype=np.int64,
    )
    if not len(symbol_train) or not len(symbol_val):
        raise RuntimeError(
            'two-stage training needs positive marks in both page splits'
        )
    gate_path = out_path.with_name(f'{out_path.stem}_gate{out_path.suffix}')
    export_mlp_onnx(
        gw1, gb1, gw2, gb2, gate_path,
        classes=['none', 'mark'],
        metadata={'pipeline': 'binary-gate', 'role': 'mark-gate'},
    )
    if symbol_model_path is not None:
        symbol_model_path = Path(symbol_model_path)
        if not symbol_model_path.is_file():
            raise FileNotFoundError(
                f'existing symbol model not found: {symbol_model_path}'
            )
        source_meta_path = symbol_model_path.with_suffix('.json')
        source_meta = (
            json.loads(source_meta_path.read_text(encoding='utf-8'))
            if source_meta_path.is_file() else {}
        )
        existing_classes = list(source_meta.get('classes') or CLASSES)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if symbol_model_path.resolve() != out_path.resolve():
            shutil.copyfile(symbol_model_path, out_path)
        metadata = {
            **source_meta,
            'classes': existing_classes,
            'pipeline': 'two-stage',
            'role': 'existing-symbol-classifier',
            'gate_model': gate_path.name,
            'gate_classes': ['none', 'mark'],
            'gate_mode': 'veto',
            'gate_min_conf': 0.5,
            'full_classes': list(CLASSES),
        }
        out_path.with_suffix('.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    else:
        sw1, sb1, sw2, sb2 = train_mlp(
            symbol_x, symbol_y,
            hidden=hidden,
            epochs=epochs,
            seed=seed,
            num_classes=len(mark_classes),
            split_indices=(symbol_train, symbol_val),
            log_prefix='symbol ',
        )
        export_mlp_onnx(
            sw1, sb1, sw2, sb2, out_path,
            classes=mark_classes,
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
    parser.add_argument(
        '--crops', type=Path, action='append', default=None,
        help='crop root; repeat to train a shared multi-edition model',
    )
    parser.add_argument('--out', type=Path, default=MODEL_PATH)
    parser.add_argument('--epochs', type=int, default=35)
    parser.add_argument('--hidden', type=int, default=128)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument(
        '--two-stage', action='store_true',
        help='train binary mark gate + mark-only symbol classifier',
    )
    parser.add_argument(
        '--reuse-symbol-model', type=Path, default=None,
        help='with --two-stage, gate an existing proven symbol model',
    )
    args = parser.parse_args(argv)

    crop_roots = args.crops or [CROPS_ROOT]
    x, y, groups = load_grouped_dataset(crop_roots)
    print(
        f'loaded {len(y)} crops across {len(set(y.tolist()))} classes '
        f'from {len(set(groups.tolist()))} page/sample groups'
    )
    if args.two_stage:
        _symbol_path, gate_path = train_two_stage(
            x, y, groups,
            out_path=args.out,
            hidden=args.hidden,
            epochs=args.epochs,
            seed=args.seed,
            symbol_model_path=args.reuse_symbol_model,
        )
        print(f'wrote {gate_path}')
    else:
        w1, b1, w2, b2 = train_mlp(
            x, y, hidden=args.hidden, epochs=args.epochs, seed=args.seed,
            groups=groups,
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
