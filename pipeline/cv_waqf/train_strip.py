"""Train the above-word strip CNN and export ONNX for OpenCV 5 DNN.

Inference never imports this module's optional torch dependency. Detect,
evaluate-hand, and bootstrap load the ONNX through OpenCV DNN only.

    pip install -r requirements-cv-train.txt   # torch, train-only
    python -m pipeline.cv_waqf train-strip --crops data/cv/crops_hand/bahrain
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.config import (
    EDITION_STRIP_MODEL_PATHS,
    EDITIONS,
    STRIP_HEIGHT,
    STRIP_WIDTH,
)
from pipeline.cv_waqf.evaluate_hand import (
    HAND_ROOT,
    collapse_word_expectations,
    load_anchored_labels,
)
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.pages import page_image_path
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.strip import (
    STRIP_CONV_CHANNELS,
    STRIP_CONV_KERNEL,
    STRIP_POOL,
    STRIP_POOL_STAGES,
    crop_above_word_strip,
    preprocess_strip,
    strip_flatten_size,
    strip_spatial_after_pools,
)
from pipeline.cv_waqf.train_classifier import _balance, split_by_page_group


def export_strip_onnx(
    conv_weights: list[tuple[np.ndarray, np.ndarray]],
    fc_w: np.ndarray,
    fc_b: np.ndarray,
    out_path: Path,
    *,
    classes: list[str] | None = None,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
    metadata: dict | None = None,
) -> Path:
    """Export Conv→Relu→MaxPool×3 → Flatten → Gemm as ONNX (NCHW input).

    ``conv_weights`` is a list of (W, B) with W shaped ``(out, in, k, k)``.
    ``fc_w`` is ``(flatten, num_classes)`` for Gemm with transB=0.
    """
    classes = list(classes or CLASSES)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    k = len(classes)
    if fc_w.shape[1] != k or fc_b.shape[0] != k:
        raise ValueError(
            f'fc weights {fc_w.shape}/{fc_b.shape} do not match {k} classes'
        )
    expected_flat = strip_flatten_size(height, width)
    if fc_w.shape[0] != expected_flat:
        raise ValueError(
            f'fc in-features {fc_w.shape[0]} != flatten size {expected_flat}'
        )

    nodes = []
    initializers = []
    current = 'input'
    for index, (weight, bias) in enumerate(conv_weights, start=1):
        w_name, b_name = f'W{index}', f'B{index}'
        c_name, r_name, p_name = f'c{index}', f'r{index}', f'p{index}'
        initializers.extend([
            numpy_helper.from_array(weight.astype(np.float32), name=w_name),
            numpy_helper.from_array(bias.astype(np.float32), name=b_name),
        ])
        pad = STRIP_CONV_KERNEL // 2
        nodes.extend([
            helper.make_node(
                'Conv', [current, w_name, b_name], [c_name],
                kernel_shape=[STRIP_CONV_KERNEL, STRIP_CONV_KERNEL],
                pads=[pad, pad, pad, pad],
                strides=[1, 1],
            ),
            helper.make_node('Relu', [c_name], [r_name]),
            helper.make_node(
                'MaxPool', [r_name], [p_name],
                kernel_shape=[STRIP_POOL, STRIP_POOL],
                strides=[STRIP_POOL, STRIP_POOL],
                pads=[0, 0, 0, 0],
            ),
        ])
        current = p_name

    initializers.extend([
        numpy_helper.from_array(fc_w.astype(np.float32), name='Wfc'),
        numpy_helper.from_array(fc_b.astype(np.float32), name='Bfc'),
    ])
    nodes.extend([
        helper.make_node('Flatten', [current], ['flat'], axis=1),
        helper.make_node(
            'Gemm', ['flat', 'Wfc', 'Bfc'], ['logits'],
            alpha=1.0, beta=1.0, transB=0,
        ),
    ])
    graph = helper.make_graph(
        nodes,
        'waqf_strip_cnn',
        [helper.make_tensor_value_info(
            'input', TensorProto.FLOAT, [None, 1, height, width],
        )],
        [helper.make_tensor_value_info(
            'logits', TensorProto.FLOAT, [None, k],
        )],
        initializers,
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid('', 13)],
        producer_name='pipeline.cv_waqf.train_strip',
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(out_path))
    feat_h, feat_w = strip_spatial_after_pools(height, width)
    meta = {
        'classes': classes,
        'pipeline': 'strip',
        'detector': 'strip',
        'role': 'above-word-strip',
        'strip_height': height,
        'strip_width': width,
        'crop_size': None,
        'conv_channels': list(STRIP_CONV_CHANNELS),
        'pool_stages': STRIP_POOL_STAGES,
        'feature_map': [feat_h, feat_w],
        'flatten': expected_flat,
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


def random_strip_weights(
    *,
    num_classes: int | None = None,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
    seed: int = 0,
    scale: float = 0.05,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    """Deterministic tiny weights for tests / export-shape checks. Not a model."""
    rng = np.random.default_rng(seed)
    k = int(num_classes or len(CLASSES))
    convs: list[tuple[np.ndarray, np.ndarray]] = []
    in_ch = 1
    for out_ch in STRIP_CONV_CHANNELS:
        w = rng.normal(0, scale, size=(out_ch, in_ch, STRIP_CONV_KERNEL, STRIP_CONV_KERNEL))
        b = np.zeros((out_ch,), dtype=np.float32)
        convs.append((w.astype(np.float32), b))
        in_ch = out_ch
    flat = strip_flatten_size(height, width)
    fc_w = rng.normal(0, scale, size=(flat, k)).astype(np.float32)
    fc_b = np.zeros((k,), dtype=np.float32)
    return convs, fc_w, fc_b


def export_random_strip_onnx(
    out_path: Path,
    *,
    seed: int = 0,
    classes: list[str] | None = None,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
) -> Path:
    """Write a fixture ONNX. Do not promote this as the production Bahrain net."""
    convs, fc_w, fc_b = random_strip_weights(
        num_classes=len(classes or CLASSES),
        height=height, width=width, seed=seed,
    )
    return export_strip_onnx(
        convs, fc_w, fc_b, out_path,
        classes=classes, height=height, width=width,
        metadata={'role': 'test-fixture', 'untrained': True},
    )


def _edition_from_crops(crops: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    hay = str(crops).lower()
    for key, spec in EDITIONS.items():
        if spec.id in hay:
            return key
    return 'البحرين'


def _labels_from_crops(crops: Path, edition_key: str) -> list[dict]:
    labels_path = Path(crops) / 'labels.jsonl'
    if labels_path.is_file():
        rows: list[dict] = []
        for line in labels_path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                page = int(row['page'])
                word_key = str(row.get('word_key') or '').strip()
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if not word_key:
                continue
            rows.append({**row, 'page': page, 'word_key': word_key})
        return rows
    spec = EDITIONS[edition_key]
    default_dir = (HAND_ROOT / spec.id).resolve()
    if Path(crops).resolve() == default_dir:
        return load_anchored_labels(spec.id)
    return []


def _limit_none(
    indices: np.ndarray,
    y: np.ndarray,
    *,
    none_idx: int,
    max_none_ratio: float = 3.0,
    seed: int = 0,
) -> np.ndarray:
    """Keep all positives; downsample unlabeled/none so they do not dominate."""
    chosen = np.asarray(indices, dtype=np.int64)
    labels = y[chosen]
    pos = chosen[labels != none_idx]
    none = chosen[labels == none_idx]
    cap = max(int(len(pos) * max_none_ratio), len(pos), 1)
    if len(none) > cap:
        rng = np.random.default_rng(seed)
        none = rng.choice(none, size=cap, replace=False)
    out = np.concatenate([pos, none]) if len(none) else pos
    return np.sort(out)


def build_strip_dataset(
    edition_key: str,
    labels: list[dict],
    *,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One strip per layout word on labeled pages (unlabeled words → none)."""
    spec = EDITIONS[edition_key]
    collapsed, _stats = collapse_word_expectations(labels)
    by_page: dict[int, dict[str, dict]] = {}
    for row in collapsed:
        by_page.setdefault(int(row['page']), {})[str(row['word_key'])] = row

    class_index = {label: idx for idx, label in enumerate(CLASSES)}
    xs: list[np.ndarray] = []
    ys: list[int] = []
    groups: list[str] = []
    skipped_pages: list[int] = []
    for page, expected in sorted(by_page.items()):
        path = page_image_path(spec, page)
        if not path.is_file():
            skipped_pages.append(page)
            continue
        prepared = preprocess_page(load_bgr(path), spec)
        words = estimate_layout_words(spec, page, prepared)
        group = f'{spec.id}:p{page:04d}'
        for word in words:
            if not word.is_content_word or not word.word_key:
                continue
            row = expected.get(word.word_key)
            symbol = str((row or {}).get('symbol') or 'none')
            if symbol not in class_index:
                continue
            strip = crop_above_word_strip(
                prepared.gray, word, width=width, height=height,
            )
            xs.append(preprocess_strip(strip, height=height, width=width)[0])
            ys.append(class_index[symbol])
            groups.append(group)
    if not xs:
        missing = (
            f'; cached pages missing for {skipped_pages[:8]}'
            if skipped_pages else ''
        )
        raise RuntimeError(
            f'no above-word strips for {edition_key}{missing}. '
            'Cache labeled pages, then rerun train-strip.'
        )
    if skipped_pages:
        print(
            f'warning: skipped {len(skipped_pages)} unlabeled-page-cache misses: '
            f'{skipped_pages[:12]}{"…" if len(skipped_pages) > 12 else ""}'
        )
    return (
        np.stack(xs),
        np.asarray(ys, dtype=np.int64),
        np.asarray(groups, dtype=object),
    )


def _require_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError as exc:
        raise SystemExit(
            'train-strip needs PyTorch (train-only extra). Install:\n'
            '  pip install -r requirements-cv-train.txt\n'
            'Detect / evaluate-hand / bootstrap do not need torch; they load '
            'the exported ONNX with OpenCV DNN.'
        ) from exc
    return torch, nn, F


def _build_strip_cnn(nn, *, height: int, width: int, num_classes: int):
    flat = strip_flatten_size(height, width)
    ch = STRIP_CONV_CHANNELS

    class StripCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(1, ch[0], STRIP_CONV_KERNEL, padding=1)
            self.conv2 = nn.Conv2d(ch[0], ch[1], STRIP_CONV_KERNEL, padding=1)
            self.conv3 = nn.Conv2d(ch[1], ch[2], STRIP_CONV_KERNEL, padding=1)
            self.fc = nn.Linear(flat, num_classes)

        def forward(self, x):
            x = nn.functional.relu(self.conv1(x))
            x = nn.functional.max_pool2d(x, STRIP_POOL)
            x = nn.functional.relu(self.conv2(x))
            x = nn.functional.max_pool2d(x, STRIP_POOL)
            x = nn.functional.relu(self.conv3(x))
            x = nn.functional.max_pool2d(x, STRIP_POOL)
            return self.fc(x.reshape(x.shape[0], -1))

    return StripCNN()


def _numpy_weights_from_torch(model) -> tuple[
    list[tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray,
]:
    convs = []
    for name in ('conv1', 'conv2', 'conv3'):
        layer = getattr(model, name)
        convs.append((
            layer.weight.detach().cpu().numpy().astype(np.float32),
            layer.bias.detach().cpu().numpy().astype(np.float32),
        ))
    fc = model.fc
    # PyTorch Linear is (out, in); Gemm transB=0 wants (in, out).
    fc_w = fc.weight.detach().cpu().numpy().astype(np.float32).T
    fc_b = fc.bias.detach().cpu().numpy().astype(np.float32)
    return convs, fc_w, fc_b


def train_strip_cnn(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    epochs: int = 25,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 0,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray, dict]:
    """Page-grouped train; returns conv weights + fc for ``export_strip_onnx``."""
    torch, nn, F = _require_torch()
    torch.manual_seed(seed)
    np.random.seed(seed)
    none_idx = list(CLASSES).index('none')
    train_i, val_i = split_by_page_group(groups, seed=seed)
    train_i = _limit_none(train_i, y, none_idx=none_idx, seed=seed)
    val_i = _limit_none(val_i, y, none_idx=none_idx, seed=seed + 1)
    x_tr, y_tr = _balance(x[train_i], y[train_i], seed=seed)
    x_va, y_va = x[val_i], y[val_i]

    model = _build_strip_cnn(
        nn, height=height, width=width, num_classes=len(CLASSES),
    )
    device = torch.device('cpu')
    model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    x_tr_t = torch.from_numpy(x_tr.astype(np.float32))
    y_tr_t = torch.from_numpy(y_tr.astype(np.int64))
    x_va_t = torch.from_numpy(x_va.astype(np.float32))
    y_va_t = torch.from_numpy(y_va.astype(np.int64))

    best_acc = -1.0
    best_state = None
    n_train = len(x_tr_t)
    for epoch in range(epochs):
        model.train()
        order = torch.randperm(n_train)
        for start in range(0, n_train, batch_size):
            idx = order[start:start + batch_size]
            xb = x_tr_t[idx]
            yb = y_tr_t[idx]
            opt.zero_grad()
            logits = model(xb)
            loss = F.cross_entropy(logits, yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            pool_x = x_va_t if len(x_va_t) else x_tr_t
            pool_y = y_va_t if len(y_va_t) else y_tr_t
            pred = model(pool_x).argmax(dim=1)
            acc = float((pred == pool_y).float().mean().item()) if len(pool_y) else 0.0
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        print(f'strip epoch {epoch + 1:02d} val_acc={acc:.3f} n={len(y)}')
    if best_state is not None:
        model.load_state_dict(best_state)
    convs, fc_w, fc_b = _numpy_weights_from_torch(model)
    stats = {
        'val_acc': round(best_acc, 4),
        'train_strips': int(len(y_tr)),
        'val_strips': int(len(y_va)),
        'pages': int(len(set(str(g) for g in groups.tolist()))),
        'class_counts': {
            CLASSES[i]: int(c)
            for i, c in enumerate(np.bincount(y, minlength=len(CLASSES)))
        },
    }
    return convs, fc_w, fc_b, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--crops', type=Path, default=None,
        help='hand-label dir containing labels.jsonl '
             '(e.g. data/cv/crops_hand/bahrain)',
    )
    parser.add_argument(
        '--edition', default=None, choices=list(EDITIONS),
        help='defaults from --crops path (bahrain → البحرين)',
    )
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)

    crops = args.crops
    if crops is None:
        crops = Path('data/cv/crops_hand/bahrain')
    edition_key = _edition_from_crops(crops, args.edition)
    labels = _labels_from_crops(crops, edition_key)
    if not labels:
        raise SystemExit(
            f'no labels.jsonl / anchored labels under {crops}. '
            'Label البحرين pages in /cv-waqf (mode تسمية) first.'
        )
    print(f'{edition_key}: {len(labels)} label rows from {crops}')
    x, y, groups = build_strip_dataset(edition_key, labels)
    print(
        f'loaded {len(y)} strips across {len(set(groups.tolist()))} pages; '
        f'classes={dict(Counter(CLASSES[i] for i in y.tolist()))}'
    )
    convs, fc_w, fc_b, stats = train_strip_cnn(
        x, y, groups,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
    )
    out = args.out or EDITION_STRIP_MODEL_PATHS.get(edition_key)
    if out is None:
        out = Path('models') / f'waqf_strip_{EDITIONS[edition_key].id}.onnx'
    export_strip_onnx(
        convs, fc_w, fc_b, out,
        metadata={
            'edition': edition_key,
            'train': stats,
            'source_crops': str(crops),
        },
    )
    print(f'wrote {out}')
    print(f"wrote {out.with_suffix('.json')}")
    print(json.dumps(stats, ensure_ascii=False))
    print(
        'This ONNX is for البحرين detect when present. '
        'It does not replace models/waqf_glyph_bahrain.onnx '
        '(gated MLP fallback).'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
